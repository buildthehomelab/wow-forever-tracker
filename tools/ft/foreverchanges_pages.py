"""Reads the public pages of foreverchanges.pro into a local folder, slowly, and turns them into reference records.

The addon pack (foreverchanges.py) is a part of what the site knows. Its pages state more: a new quest's hand-in and
progress text and who starts and ends it, who sells an item and for how much, what drops it and how often, and the
map's NPCs by id. The site publishes no licence and its terms forbid republishing its compiled data, so what is read
here is a `reference`: shown to an administrator beside a resource, never a row. The pages are read the way
the site asks: `robots.txt` is fetched first and obeyed, one request at a time with a pause, and the first answer that
says "not you" (403, 429, a page that is not the page) stops the run. Nothing is retried around a refusal.

    python tools/ft/foreverchanges_pages.py mirror  --out <folder> [--only maps,dungeons,topics,quests,items] [--pause 2.5] [--limit N]
    python tools/ft/foreverchanges_pages.py extract --out <folder>

`mirror` keeps each page once (`quest/<id>.html.gz` holds the page's <main> element, `map/<slug>/<file>.json` the map's
own data files) and can be stopped and started again: what is there is not asked for twice. A full run is about
19,800 pages, most of a day at the default pause. `extract` reads the kept pages into `quests.jsonl` and
`items.jsonl`, one record a line, with no network; `read` gives the same records as reference facts
(tools/foreverchanges-import.py --pages <folder> loads them).

What a page states is by NPC *name*, not id. The map's own data files carry ids (its NPCs, its rares and elites,
who starts a quest), so a name on a page gets the id those files know it by when exactly one thing carries the name
(`match`); several are listed as candidates and none is picked.
"""
import argparse
import collections
import gzip
import html
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

BASE = 'https://foreverchanges.pro'
AGENT = 'Mozilla/5.0 (compatible; slow reader, one request at a time)'
GROUPS = ('maps', 'dungeons', 'topics', 'quests', 'items')
MAP_FILES = ('npcs', 'quest-givers', 'quests', 'creatures', 'rares', 'services', 'commerce', 'books', 'nodes', 'convergences', 'pins')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,80}')
NEW_QUEST, NEW_ITEM = 76000, 200000                    # Forever's own ids come first: they are what no Classic source has
# Sections of the site that say nothing about the world (its own rankings, builds and calculators) are not read.
TOPIC_SECTIONS = ('quests', 'professions')
LEFT_OUT = ('fr', 'de', 'es', 'ru', 'zh-tw', 'zh-cn', 'bis', 'builds', 'talents', 'spellbook', 'class', 'gear-planner', 'transmog',
            'patch-notes', 'items', 'map', 'dungeons', 'item', 'quest')


class Refused(Exception):
    """The site said no, or answered with something that is not the page: the run stops."""


# robots.txt ---------------------------------------------------------------------------------------------------------

def disallowed(robots):
    """The path prefixes `robots.txt` closes to every reader (the `User-agent: *` group)."""
    out, mine = [], False
    for line in robots.splitlines():
        key, _, value = line.split('#', 1)[0].partition(':')
        key, value = key.strip().lower(), value.strip()
        if key == 'user-agent':
            mine = value == '*'
        elif key == 'disallow' and mine and value:
            out.append(value)
    return out


def allowed(path, closed):
    return not any(path.startswith(prefix) for prefix in closed)


# The plan -----------------------------------------------------------------------------------------------------------

def _locs(sitemap):
    return [html.unescape(loc)[len(BASE):] for loc in re.findall(r'<loc>([^<]+)</loc>', sitemap) if loc.startswith(BASE)]


def plan(sitemap, quest_sitemap, item_sitemap):
    """[(group, path on the site, file in the folder)], in the order read: the map's data files, the dungeons, the
    topic pages, then quests and items, Forever's own ids first. Only English pages; a name that is not a plain slug
    never becomes a path."""
    out, maps, seen = [], [], set()
    for path in _locs(sitemap):
        parts = [p for p in path.split('/') if p]
        if not parts or not all(SLUG.fullmatch(p) for p in parts):
            continue
        if parts[0] == 'map' and len(parts) >= 2 and parts[1] not in maps:
            maps.append(parts[1])
        elif parts[0] == 'dungeons' and len(parts) == 2:
            out.append(('dungeons', path, f'dungeons/{parts[1]}.html.gz'))
        elif (len(parts) == 1 and parts[0] not in LEFT_OUT) or (len(parts) == 2 and parts[0] in TOPIC_SECTIONS):
            out.append(('topics', path, 'page/' + '--'.join(parts) + '.html.gz'))
    for slug in maps:
        for name in MAP_FILES:
            out.append(('maps', f'/map/{slug}/{name}.json', f'map/{slug}/{name}.json'))
    for group, text, first in (('quests', quest_sitemap, NEW_QUEST), ('items', item_sitemap, NEW_ITEM)):
        kind = group[:-1]
        pages = {}
        for path in _locs(text):
            m = re.fullmatch(rf'/{kind}/(\d{{1,10}})/([a-z0-9-]{{1,160}})', path)
            if m:
                pages.setdefault(int(m.group(1)), path)
        for number in sorted(pages, key=lambda n: (n < first, n)):
            out.append((group, pages[number], f'{kind}/{number}.html.gz'))
    order = {group: i for i, group in enumerate(GROUPS)}
    out = [row for row in out if not (row[2] in seen or seen.add(row[2]))]
    return sorted(out, key=lambda row: order[row[0]])


# Reading the site ---------------------------------------------------------------------------------------------------

def http_get(path):
    """(status, content type, body) of one page. A status the site answers with is returned, not raised."""
    request = urllib.request.Request(BASE + path, headers={'User-Agent': AGENT, 'Accept-Encoding': 'identity'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers.get('Content-Type', ''), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get('Content-Type', '') if error.headers else '', b''


def main_of(body):
    """The page's <title> and <main> element: the rest is the site's frame, the same on every page."""
    text = body.decode('utf-8', 'replace')
    main = re.search(r'<main\b.*?</main>', text, re.S)
    if not main:
        return None
    title = re.search(r'<title>(.*?)</title>', text, re.S)
    return ((title.group(0) if title else '') + '\n' + main.group(0)).encode('utf-8')


def _keep(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.part', 'wb') as handle:
        handle.write(data)
    os.replace(path + '.part', path)


def lock(folder):
    """An open file that says "a reader is at work in this folder", held until it is closed or the process ends.
    A second reader on the same folder would double what the site is asked: it is refused."""
    os.makedirs(folder, exist_ok=True)
    handle = open(os.path.join(folder, 'mirror.lock'), 'a+')
    try:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:                                  # Windows
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise Refused(f'another reader is already at work in {folder}: one at a time') from None
    return handle


def mirror(folder, only=GROUPS, pause=2.5, limit=None, get=http_get, sleep=time.sleep, log=print):
    """Reads what the plan names and the folder does not hold yet, one reader a folder. See `_mirror`."""
    held = lock(folder)
    try:
        return _mirror(folder, only, pause, limit, get, sleep, log)
    finally:
        held.close()


def _mirror(folder, only, pause, limit, get, sleep, log):
    """Reads what the plan names and the folder does not hold yet. Returns {'read', 'kept', 'missing', 'left'}.

    Stops (Refused) when another reader holds the folder, when robots.txt cannot be read, when the site refuses (401, 403, 429, 451), when it fails three
    times in a row, or when a page comes back without its <main>: a check page is not the page."""
    def ask(path):
        nonlocal asked
        if asked:
            sleep(pause)
        asked += 1
        last = None
        for attempt in range(3):
            try:
                status, kind, body = get(path)
            except (OSError, http.client.HTTPException) as error:
                last = f'{type(error).__name__}: {error}'
                sleep(30 * (attempt + 1))
                continue
            if status in (401, 403, 429, 451):
                raise Refused(f'{path}: the site answered {status}; nothing is retried around a refusal')
            if status >= 500:
                last = f'status {status}'
                sleep(30 * (attempt + 1))
                continue
            return status, kind, body
        raise Refused(f'{path}: no answer after three tries ({last})')

    asked = 0
    status, _kind, body = ask('/robots.txt')
    if status != 200:
        raise Refused(f'robots.txt answered {status}: without it nothing is read')
    closed = disallowed(body.decode('utf-8', 'replace'))
    _keep(os.path.join(folder, 'robots.txt'), body)
    sitemaps = {}
    for name, path in (('sitemap', '/sitemap.xml'), ('quest', '/quest/sitemap.xml'), ('item', '/item/sitemap.xml')):
        if not allowed(path, closed):
            raise Refused(f'robots.txt closes {path}')
        status, _kind, body = ask(path)
        if status != 200 or b'<loc>' not in body:
            raise Refused(f'{path} answered {status} and no list of pages')
        _keep(os.path.join(folder, name + '-sitemap.xml' if name != 'sitemap' else 'sitemap.xml'), body)
        sitemaps[name] = body.decode('utf-8', 'replace')
    rows = [row for row in plan(sitemaps['sitemap'], sitemaps['quest'], sitemaps['item']) if row[0] in only]
    gone_file = os.path.join(folder, 'missing.txt')
    gone = set()
    if os.path.isfile(gone_file):
        with open(gone_file, encoding='utf-8') as handle:
            gone = set(handle.read().split())
    todo = [row for row in rows if row[1] not in gone and not os.path.isfile(os.path.join(folder, row[2]))]
    log(f'{len(rows)} pages in the plan, {len(rows) - len(todo)} already here or known missing, {len(todo)} to read')
    result = {'read': 0, 'kept': 0, 'missing': 0, 'left': len(todo)}
    for group, path, file in todo:
        if limit is not None and result['read'] >= limit:
            break
        if not allowed(path, closed):
            raise Refused(f'robots.txt closes {path}: the plan must not name it')
        status, kind, body = ask(path)
        result['read'] += 1
        result['left'] -= 1
        if status == 404:
            gone.add(path)
            with open(gone_file, 'a', encoding='utf-8') as handle:
                handle.write(path + '\n')
            result['missing'] += 1
            continue
        if status != 200:
            raise Refused(f'{path}: unexpected status {status}')
        if file.endswith('.json'):
            try:
                json.loads(body)
            except ValueError:
                raise Refused(f'{path}: not the data file (no JSON)') from None
            _keep(os.path.join(folder, file), body)
        else:
            kept = main_of(body)
            if kept is None:
                raise Refused(f'{path}: the answer is not the page (no <main>)')
            _keep(os.path.join(folder, file), gzip.compress(kept, 6))
        result['kept'] += 1
        if result['read'] % 100 == 0:
            log(f"{time.strftime('%H:%M:%S')} {result['read']} read, {result['left']} left, at {path}")
    return result


# A small tree of a page ---------------------------------------------------------------------------------------------

VOID = {'img', 'br', 'hr', 'input', 'meta', 'link', 'path', 'circle', 'rect', 'source', 'wbr'}


class Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or ()), parent, []

    def classes(self):
        return (self.attrs.get('class') or '').split()

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def all(self, tag=None, cls=None):
        return [n for n in self.walk() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())]

    def first(self, tag=None, cls=None):
        return next(iter(self.all(tag, cls)), None)

    def strings(self):
        for child in self.children:
            if isinstance(child, Node):
                yield from child.strings()
            elif child.strip():
                yield child.strip()

    def text(self, joiner=' '):
        return re.sub(r'[ \t]+', ' ', joiner.join(self.strings())).strip()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.at = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.at)
        self.at.children.append(node)
        if tag not in VOID:
            self.at = node

    def handle_startendtag(self, tag, attrs):
        self.at.children.append(Node(tag, attrs, self.at))

    def handle_endtag(self, tag):
        node = self.at
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.at = node.parent

    def handle_data(self, data):
        self.at.children.append(data)


def tree(text):
    parser = _Tree()
    parser.feed(text)
    return parser.root


def _number(text):
    m = re.search(r'-?\d+(?:\.\d+)?', (text or '').replace(',', ''))
    return (float(m.group(0)) if '.' in m.group(0) else int(m.group(0))) if m else None


def _paragraphs(nodes):
    return '\n\n'.join(t for t in (n.text() for n in nodes) if t)


def _money(node):
    """Copper, from the page's "0 gold, 4 silver, 0 copper" line for screen readers."""
    spoken = node.first(cls='qp-sr') if node else None
    m = re.fullmatch(r'(\d+) gold, (\d+) silver, (\d+) copper', spoken.text() if spoken else '')
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3)) if m else None


# A quest page -------------------------------------------------------------------------------------------------------

QUEST_TEXTS = {'When you hand it in': 'complete', 'When you come back': 'progress'}


def _who(dd):
    """[{name, zone, x, y}] of a Start or End entry; an item that starts the quest is {'item': name}."""
    out = []
    for span in [c for c in dd.children if isinstance(c, Node)] or [dd]:
        coord = span.first(cls='qp-coord')
        name = ' '.join(c.strip() for c in span.children if isinstance(c, str) and c.strip()) or span.text()
        if name.startswith('an item:'):
            out.append({'item': name[len('an item:'):].strip()})
            continue
        entry = {'name': name}
        if coord:                                            # "Zone 21.8, 45.3", the numbers in tags of their own or not
            words = coord.text()
            at = re.search(r'(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*$', words)
            entry['zone'] = (words[:at.start()] if at else words).strip()
            if at:
                entry['x'], entry['y'] = float(at.group(1)), float(at.group(2))
        if entry['name']:
            out.append(entry)
    return out


def quest(text):
    """What a quest page states, or None when it is not a quest page."""
    root = tree(text)
    work = root.first(cls='qp-work')
    if not work:
        return None
    out = {'title': (work.first('h1').text() if work.first('h1') else ''), 'texts': {}, 'start': [], 'end': []}
    crumbs = work.first(cls='qp-crumbs')
    if crumbs:
        out['category'] = [s for s in crumbs.strings() if s != '›'][1:]
    lede, known = work.first(cls='qp-lede'), work.first(cls='qp-known')
    out['lede'] = lede.text() if lede else ''
    out['new'] = bool(work.first(cls='qp-new'))
    out['seen_by_players'] = bool(known and 'players of our addon saw' in known.text())
    sheet = work.first(cls='qp-sheet')
    section, parts = None, {}
    for child in (sheet.children if sheet else ()):
        if not isinstance(child, Node):
            continue
        if child.tag == 'h2':
            section = child.text()
        elif section and child.tag == 'p' and 'qp-gains' not in child.classes():
            parts.setdefault(section, []).append(child)
        if 'qp-need' in child.classes():
            out['needs'] = [{'item': _number(a.attrs.get('data-tip')), 'name': a.text()} for a in child.all('a', 'qp-item')]
            out['counts'] = [li.text() for li in child.all('li') if not li.first('a')]
        if 'qp-gains' in child.classes():
            out['money'] = _money(child)
            xp = child.first('b')
            out['xp'] = _number(xp.text()) if xp else None
        if 'qp-rep' in child.classes():
            out['reputation'] = [li.text() for li in child.all('li')]
        if 'qp-more' in child.classes():
            for details in child.all('details'):
                label = details.first('summary').text() if details.first('summary') else ''
                body = _paragraphs(details.all('p'))
                if body:
                    out['texts'][QUEST_TEXTS.get(label, label)] = body
    out['objectives'] = _paragraphs(parts.get('Quest Objectives', []))
    out['description'] = _paragraphs(parts.get('Description', []))
    if sheet:
        rewards = [a for a in sheet.all('a', 'qp-item') if not any('qp-need' in p.classes() for p in _parents(a))]
        out['reward_items'] = [{'item': _number(a.attrs.get('data-tip')), 'name': a.text()} for a in rewards]
    facts = work.first('dl', 'qp-facts')
    label = None
    for child in (facts.children if facts else ()):
        if not isinstance(child, Node):
            continue
        if child.tag == 'dt':
            label = child.text()
        elif child.tag == 'dd' and label:
            if label in ('Start', 'End'):
                out[label.lower()] = _who(child)
            elif label == 'Level':
                numbers = re.findall(r'\d+', child.text())
                out['level'] = int(numbers[0]) if numbers else None
                out['min_level'] = int(numbers[1]) if len(numbers) > 1 else None
            elif label == 'Quest ID':
                out['id'] = _number(child.text())
            elif label in ('Side', 'Class', 'Race', 'Type'):
                out[label.lower()] = child.text()
    frame = work.first(cls='qp-map-frame')
    if frame:
        image = frame.first('img')
        m = re.search(r'/quests/maps/(\d+)\.', image.attrs.get('src', '')) if image else None
        out['ui_map'] = int(m.group(1)) if m else None
        out['objective_spots'] = len(frame.all(cls='qp-dot'))
    return out


def _parents(node):
    while node.parent is not None:
        node = node.parent
        yield node


# An item page -------------------------------------------------------------------------------------------------------

def _rate(text):
    """{'percent': 11.0} or {'drops': 5, 'kills': 41} of an item page's rate, or {'text': ...} when it is neither."""
    m = re.fullmatch(r'(\d+(?:\.\d+)?)%', text)
    if m:
        return {'percent': float(m.group(1))}
    m = re.fullmatch(r'(\d+) in (\d+) kills?', text)
    if m:
        return {'drops': int(m.group(1)), 'kills': int(m.group(2))}
    return {'text': text} if text else {}


def _copper(text):
    m = re.fullmatch(r'(?:(\d+)g)? ?(?:(\d+)s)? ?(?:(\d+)c)?', text.strip())
    if not m or not text.strip():
        return None
    return int(m.group(1) or 0) * 10000 + int(m.group(2) or 0) * 100 + int(m.group(3) or 0)


def item(text):
    """What an item page states about where the item comes from, or None when it is not an item page.
    Each source is {'how': the group's heading, 'name', 'place', 'x', 'y', 'price' (copper), 'rate'}."""
    root = tree(text)
    heading = root.first('h1')
    if not heading or not (root.first(cls='it-from') or 'item ' in root.text()[:4000]):
        return None
    out = {'name': heading.text(), 'sources': []}
    m = re.search(r'\bitem (\d+)\b', root.text())
    out['id'] = int(m.group(1)) if m else None
    out['new'] = 'New in Forever' in root.text()
    section = root.first(cls='it-from')
    for group in (section.all(cls='it-from-group') if section else ()):
        how = group.first('h3').text() if group.first('h3') else ''
        for li in group.all('li'):
            name, place, last = li.first('b'), li.first('span'), li.first('em')
            link = li.first('a')
            words = list(li.strings())
            entry = {'how': how, 'name': name.text() if name else (words[0] if words else '')}
            if link and link.attrs.get('href'):
                entry['link'] = link.attrs['href']
            if not name and len(words) > 2:                  # a dungeon's boss: "Boss", "Dungeon", "31%", no tags around them
                entry['place'] = words[1]
            if place:
                words = place.text()
                c = re.search(r'\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)', words)
                entry['place'] = words[:c.start()].strip() if c else words
                if c:
                    entry['x'], entry['y'] = float(c.group(1)), float(c.group(2))
            if last:
                price = _copper(last.text())
                if price is not None and 'vendor' in how.lower():
                    entry['price'] = price
                else:
                    entry['rate'] = _rate(last.text())
                    counted = re.search(r'(\d+) in (\d+) kills?', last.attrs.get('title') or '')
                    if counted:                              # the page's own count behind a percentage
                        entry['rate'].update(drops=int(counted.group(1)), kills=int(counted.group(2)))
            out['sources'].append(entry)
    return out


# The folder as records ----------------------------------------------------------------------------------------------

def _pages(folder, kind):
    path = os.path.join(folder, kind)
    for name in sorted(os.listdir(path)) if os.path.isdir(path) else ():
        if name.endswith('.html.gz'):
            with gzip.open(os.path.join(path, name), 'rt', encoding='utf-8') as handle:
                yield name[:-len('.html.gz')], handle.read()


def _links(folder, kind):
    """{id: the page's address} from the list of pages the mirror kept."""
    path = os.path.join(folder, kind + '-sitemap.xml')
    text = ''
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
    return {int(number): BASE + link for link, number in re.findall(rf'<loc>{re.escape(BASE)}(/{kind}/(\d+)/[a-z0-9-]+)</loc>', text)}


def _day(path):
    return time.strftime('%Y-%m-%d', time.gmtime(os.path.getmtime(path)))


MAX_SPOTS = 8
MAX_CANDIDATES = 8
NPC_ROW = ('name', 'title', 'side', 'x', 'y', 'role', 'kind', 'origin')
GIVER_KINDS = {'n': 'npc', 'o': 'object'}


def _map_files(folder, name, skipped):
    """(map slug, the day it was read, content) of each map's `<name>.json` the mirror kept."""
    root = os.path.join(folder, 'map')
    for slug in sorted(os.listdir(root)) if os.path.isdir(root) else ():
        path = os.path.join(root, slug, name + '.json')
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as handle:
                content = json.load(handle)
        except (OSError, ValueError):
            skipped['map_file'] += 1
            continue
        if isinstance(content, dict):
            yield slug, _day(path), content


def _rows(content, key):
    return content[key] if isinstance(content.get(key), list) else []


def _spot(record, slug, x, y):
    if len(record['spots']) < MAX_SPOTS and [slug, x, y] not in record['spots']:
        record['spots'].append([slug, x, y])


def map_npcs(folder, skipped):
    """{npc id: record} of the map's `npcs.json` files.

    A row is [id, name, title, side, x, y, role, kind, origin]: world coordinates in whole yards, side A, H or AH,
    role npc, vendor or trainer. The file names where its rows come from (`source`, "QuestieDB" when read); a row
    whose origin is "addon" was recorded by the site's own players, and its side AH then means "not known"."""
    out = {}
    for slug, day, content in _map_files(folder, 'npcs', skipped):
        for row in _rows(content, 'npcs'):
            if not (isinstance(row, list) and len(row) >= 7 and isinstance(row[0], int) and row[0] > 0):
                skipped['map_npc'] += 1
                continue
            about = dict(zip(NPC_ROW, row[1:]))
            record = out.setdefault(row[0], {'name': about['name'], 'title': about['title'], 'side': about['side'], 'role': about['role'],
                                             'kind': about.get('kind') or '', 'recorded_by_players': False, 'spots': [],
                                             'layer_from': str(content.get('source', '')), 'read': day})
            record['recorded_by_players'] = record['recorded_by_players'] or about.get('origin') == 'addon'
            _spot(record, slug, about['x'], about['y'])
    return out


def map_creatures(folder, skipped):
    """{npc id: record} of the map's `creatures.json` files (its rares and elites): a row is
    [id, name, lowest level, highest level, a class of the site's own, [[x, y], ...]]."""
    out = {}
    for slug, day, content in _map_files(folder, 'creatures', skipped):
        for row in _rows(content, 'mobs'):
            if not (isinstance(row, list) and len(row) >= 6 and isinstance(row[0], int) and row[0] > 0 and isinstance(row[5], list)):
                skipped['map_creature'] += 1
                continue
            record = out.setdefault(row[0], {'name': row[1], 'levels': [row[2], row[3]], 'class': row[4], 'spots': [],
                                             'layer_from': str(content.get('source', '')), 'read': day})
            for spot in row[5]:
                if isinstance(spot, list) and len(spot) >= 2:
                    _spot(record, slug, spot[0], spot[1])
    return out


def map_givers(folder, skipped):
    """{quest id: {(kind, id): record}} of the map's `quest-givers.json` files: who starts a quest, by id.

    A row is ["n<npc id>" or "o<object id>", name, title, side, x, y, [quest ids]]. Starts only: the layer does not
    say who ends a quest."""
    out = collections.defaultdict(dict)
    for slug, day, content in _map_files(folder, 'quest-givers', skipped):
        for row in _rows(content, 'givers'):
            key = re.fullmatch(r'([no])(\d{1,10})', row[0]) if isinstance(row, list) and len(row) >= 7 and isinstance(row[0], str) else None
            if not key or not isinstance(row[6], list):
                skipped['map_giver'] += 1
                continue
            who = (GIVER_KINDS[key.group(1)], int(key.group(2)))
            for quest in row[6]:
                if not (isinstance(quest, int) and quest > 0):
                    continue
                record = out[quest].setdefault(who, {'kind': who[0], 'id': who[1], 'name': row[1], 'title': row[2], 'side': row[3], 'spots': [],
                                                     'layer_from': str(content.get('source', '')), 'read': day})
                _spot(record, slug, row[4], row[5])
    return out


# Names to ids -------------------------------------------------------------------------------------------------------

def fold(name):
    """A name as it is compared: case, the kind of apostrophe and runs of spaces do not tell two names apart."""
    return re.sub(r'\s+', ' ', str(name).replace('’', "'").replace('‘', "'")).strip().casefold()


def name_index(folder, skipped=None, extra=()):
    """{folded name: {(kind, id): where the name is known from}} of everything the kept map files name by id: the
    map's NPCs, its rares and elites, and who starts a quest (NPCs and objects). `extra` adds (kind, id, name,
    where from) rows of your own: `known_names` gives the ones your server's world and the other sources hold."""
    skipped = collections.Counter() if skipped is None else skipped
    return _index(map_npcs(folder, skipped), map_creatures(folder, skipped), map_givers(folder, skipped), extra)


def _index(npcs, creatures, givers, extra=()):
    index = collections.defaultdict(lambda: collections.defaultdict(set))
    for found in (npcs, creatures):
        for npc, record in found.items():
            index[fold(record['name'])][('npc', npc)].add('map')
    for starters in givers.values():
        for who, record in starters.items():
            index[fold(record['name'])][who].add('map')
    for kind, number, name, origin in extra:
        index[fold(name)][(kind, number)].add(origin)
    index.pop('', None)
    return index


def known_names(query, log=lambda message: None):
    """(kind, id, name, where from) of the NPCs and objects the tracker already knows by id, for `name_index`:
    the server's own world ('world': creature_template and gameobject_template) and the records the other sources
    gave ('facts': what EG Link and QuestieDB name). `query(sql, database)` is sqlio.query. A database that cannot
    be read gives nothing from it, with a line saying so: the map files alone still match."""
    out = []
    for kind, table in (('npc', 'creature_template'), ('object', 'gameobject_template')):
        try:
            out += [(kind, int(row['entry']), row['name'], 'world') for row in query(f'SELECT entry, name FROM {table}', 'world') if row.get('name')]
        except (RuntimeError, KeyError, ValueError, TypeError) as error:
            log(f'names of {table} not read ({str(error).strip()[:120]})')
    try:
        rows = query("SELECT subject_kind, subject, data FROM ft_world_facts WHERE source NOT LIKE 'foreverchanges%' AND subject_kind IN ('npc', 'object') "
                     "AND kind IN ('creature', 'object', 'seen', 'talked', 'entry')", 'tracker')
    except RuntimeError as error:
        rows = []
        log(f'names of the stored facts not read ({str(error).strip()[:120]})')
    for row in rows:
        try:
            data = json.loads(row['data'])
        except (ValueError, TypeError, KeyError):
            continue
        parts = data.get('parts') if isinstance(data.get('parts'), dict) else {}
        for about in [data] + [part for part in parts.values() if isinstance(part, dict)]:
            if isinstance(about.get('name'), str) and about['name']:
                out.append((row['subject_kind'], int(row['subject']), about['name'], 'facts'))
    return out


def match(index, name):
    """What a name on a page is, by the ids the index knows under that name:

    - exactly one: {'kind': 'npc', 'id': 257008, 'matched_by': 'name', 'named_in': ['map']} (`named_in`: which
      list carries the name: the site's map files, your server's world, the other sources' facts);
    - several (an object such as "Wanted Poster", a creature with one name and several ids):
      {'candidates': [[kind, id], ...]}, eight at most, and nothing is picked;
    - none: {}.
    A match says that one thing known by id carries this name. It is no second witness of what the page states,
    and it does not show that nothing else in the game is called the same."""
    found = index.get(fold(name), {})
    if len(found) == 1:
        (kind, number), origins = next(iter(found.items()))
        return {'kind': kind, 'id': number, 'matched_by': 'name', 'named_in': sorted(origins)}
    if found:
        return {'candidates': [list(who) for who in sorted(found)[:MAX_CANDIDATES]]}
    return {}


def _identify(entries, index, counts):
    for entry in entries:
        name = entry.get('name')
        if not name or name == entry.get('how'):             # "Creature drop": the page names nobody
            continue
        found = match(index, name)
        counts['one id' if 'id' in found else 'several ids' if found else 'no id'] += 1
        entry.update(found)


def read(folder, skipped=None, about=None, extra=()):
    """The kept pages and map files as reference facts, one per resource:

    - a quest: its page (`quest_page`) and who starts it by id on the map (`map_givers`);
    - an item: its page when it names a source (`item_page`);
    - an NPC: the map's row for it (`map_npc`), and its rare or elite row (`map_creature`).
    The names a page gives (who starts and ends a quest, who sells or drops an item) get the id the map files know
    them by (`match`). No build: a page does not say on which build something was seen. A Classic quest's own text
    is left out (it is Classic's). `extra` is more names known by id (`known_names`); `about`, when given, is
    filled with how many names found an id."""
    from .facts import Fact
    skipped = collections.Counter() if skipped is None else skipped
    npcs, creatures, givers = map_npcs(folder, skipped), map_creatures(folder, skipped), map_givers(folder, skipped)
    index, counts = _index(npcs, creatures, givers, extra), collections.Counter()
    found = collections.OrderedDict()                        # (kind, id) -> {'read', 'page', 'datasets'}

    def add(kind, number, dataset, record, day, page=None):
        data = found.setdefault((kind, number), {'read': day, 'datasets': {}})
        data['read'] = max(data['read'], day)
        if page:
            data['page'] = page
        data['datasets'].setdefault(dataset, []).append(record)

    for kind, parse in (('quest', quest), ('item', item)):
        links = _links(folder, kind)
        for name, text in _pages(folder, kind):
            record = parse(text)
            if record is None:
                skipped[kind + '_page'] += 1
                continue
            record.pop('id', None)
            if kind == 'item' and not record['sources']:
                continue
            if kind == 'quest' and not record['new']:
                record.pop('description', None)
                record.pop('objectives', None)
            _identify(record['sources'] if kind == 'item' else record['start'] + record['end'], index, counts)
            add(kind, int(name), kind + '_page', record, _day(os.path.join(folder, kind, name + '.html.gz')), links.get(int(name)))
    for quest_id, starters in sorted(givers.items()):
        for record in starters.values():
            add('quest', quest_id, 'map_givers', record, record.pop('read'))
    for dataset, rows in (('map_npc', npcs), ('map_creature', creatures)):
        for npc, record in sorted(rows.items()):
            add('npc', npc, dataset, record, record.pop('read'), BASE + '/map')
    if about is not None:
        about.update(names=dict(counts), known_names=len(index))
    for (kind, number), data in found.items():
        yield Fact('reference', kind, number, 0, 0, 0, data)


def extract(folder, log=print):
    """Writes quests.jsonl and items.jsonl from the kept pages. Returns the counts."""
    counts = {}
    for kind, read in (('quest', quest), ('item', item)):
        kept = unread = 0
        with open(os.path.join(folder, kind + 's.jsonl.part'), 'w', encoding='utf-8') as out:
            for name, text in _pages(folder, kind):
                record = read(text)
                if record is None:
                    unread += 1
                    continue
                record['id'] = int(name)
                out.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
                kept += 1
        os.replace(os.path.join(folder, kind + 's.jsonl.part'), os.path.join(folder, kind + 's.jsonl'))
        counts[kind + 's'] = kept
        counts[kind + 's not read'] = unread
        log(f'{kind}s: {kept} records, {unread} pages not read')
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    get = sub.add_parser('mirror', help='read the pages the folder does not hold yet')
    get.add_argument('--out', required=True, help='the folder the pages are kept in')
    get.add_argument('--only', default=','.join(GROUPS), help='which groups, comma separated: ' + ', '.join(GROUPS))
    get.add_argument('--pause', type=float, default=2.5, help='seconds between two requests (2 at least)')
    get.add_argument('--limit', type=int, help='stop after this many pages')
    ext = sub.add_parser('extract', help='turn the kept pages into records')
    ext.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.command == 'extract':
        extract(args.out)
        return 0
    only = tuple(g for g in args.only.split(',') if g in GROUPS)
    try:
        result = mirror(args.out, only, max(2.0, args.pause), args.limit, log=lambda m: print(m, flush=True))
    except Refused as error:
        print(f'Stopped: {error}', file=sys.stderr, flush=True)
        return 2
    print(json.dumps(result), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
