"""foreverchanges.pro, read from the site itself, slowly, and kept privately (docs/SOURCES.md, ForeverChanges).

The site was rebuilt in November 2026: the data files a crawl of it used to hold (`quests.jsonl`, `items.jsonl`,
`tracker-pages/...`) are gone (404), and what it knows is now on its pages and in its map's data files. This module
reads both, the way the site asks to be read, and makes of them the same pack `tools/ft/reports.py` has always read,
so the matching, the evidence, the snapshot and the card stay as they are.

What the site holds (measured 2026-11-15) and what it is used for:

  map data files   /map/<map>/<file>.json for each map of its sitemap (about 70; a dungeon map has fewer files).
                   `quest-givers.json` names who starts each quest *by id* ("n620", "o9000"), with an `addon` mark on
                   what its players saw: those are rows, no name to match. `npcs.json` (QuestieDB's NPCs, `addon` on
                   what players saw), `rares.json`, `commerce.json` and `books.json` give places for what nobody
                   spawned. `manifest.json` says which map a folder is. The rest (`services`, `nodes`, `creatures`,
                   `quests`, `convergences`, `pins`: inns, gathering nodes, flight paths, entrances) is kept, not read
                   into cards yet.
  quest pages      /quest/<id>/<slug>, 5,729: who starts and ends it (name, zone, coordinates), its side, whether its
                   players saw it, the hand-in and progress texts.
  item pages       /item/<id>/<slug>, 13,340: who sells it, what drops it ("88 in 288 kills").
  other pages      the dungeons and the topic pages (rares, library books, hidden items ...): kept, not read.

How it reads (`pull`): `robots.txt` first, and obeyed (the site closes /api/, /search, /spell/, /admin); one request
at a time, asked for compressed, English pages only. The pause between two requests starts at `pause` and moves with
what the site says: a 429 or 503 doubles it and waits what Retry-After asks (a minute at least), an answer slower than
four seconds lengthens it, and it eases back after a run of quick answers. What it learnt is kept (pacer.json) for
the next run. A 401, 403 or 451, a Cloudflare challenge, or three throttles or failures in a row stop the run:
nothing is retried around a refusal and no script is dressed up as a browser.

The whole site is read, the gaps first. On 2026-11-16 the project decided to look up only its gaps and never to
mirror the site; on 2026-11-21 it reversed that: the tracker held too little of it, so a visit now goes on through
every quest page, every item page and every map's data files once the gaps are done, and everything read goes into
the pack and the card's snapshot (ft_source_facts), where it can be queried. The order:

  0 the three sitemaps and robots.txt (every run: they say where each page is)
  1 the two continents' map data files (24 files; who starts a quest, by id)
  2 the quests without a giver or an ender, the items other content waits for, then the other items players cannot
    get, as `wanted` lists them
    then again whichever of those was read longer ago than `older` days, in the same order, oldest first
  3 (`whole`, the default) the rest of the site: the other maps' data files, then every other quest page, then every
    other item page, by id
    then again whichever of those was read longer ago than `older` days, oldest first

Not read: the dungeons and topic pages, Classic's pages and the other languages. `whole=False` (`--gaps-only`, the
website's `[foreverchanges] whole = 0`) is the old way: the gaps alone. At the site's pace (2.5 s a request) the
whole site, about 20,000 files, is some 14 hours of requests: at 3,000 files a visit and a visit every 6 hours (the
container's default) a first full pass takes two to three days, and then about 1,400 files a day keep it 14 days
fresh.

`limit` bounds a run; the next one goes on where the order left off. Every `pack_every` files (500) the pack is
written again, so that a visit a restart cuts short still leaves what it read in the pack: the website makes the card
of such a pack at the start of the next visit (app/sources.php).

Where it keeps things, all under the tracker's data/ folder, never in the repository:

  data/sources/blobs/<xx>/sha256-<hex>     each file once, named by its content (as app/store.php keeps them)
  data/foreverchanges/site/<path>          a link to the newest copy of each file (a page's <title> and <main>,
                                           gzipped; a map file as it came)
  data/foreverchanges/pages.jsonl          a line a reading: {"f", "at", "s" (status), "key"}; the last line of a
                                           file counts, the earlier ones are its history
  data/foreverchanges/parsed.jsonl         what each kept page states, by its key: a page is read once
  data/foreverchanges/pacer.json           the pause the site was last happy with
  data/foreverchanges/pack.fcpack          the pack (pack.json in a zip), as tools/ft/reports.py reads it
"""
import collections
import gzip
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser

BASE = 'https://foreverchanges.pro'
AGENT = 'ForeverTracker/1.1 (private server admin tool; one request at a time)'
FORMAT = 'foreverchanges-pack/1'
SITEMAPS = ('/sitemap.xml', '/quest/sitemap.xml', '/item/sitemap.xml')
MAP_FILES = ('manifest', 'quest-givers', 'npcs', 'rares', 'commerce', 'books', 'quests', 'creatures', 'services', 'nodes', 'convergences', 'pins')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,80}')
CONTINENTS = {'eastern-kingdoms': 0, 'kalimdor': 1}
PINS = {'rares.json': 'rare', 'commerce.json': 'commerce', 'books.json': 'book'}
QUEST_FIELDS = ('id', 'title', 'new', 'seen_by_players', 'side', 'class', 'type', 'level', 'min_level', 'start', 'end', 'xp',
                'reputation', 'reward_items', 'texts')
ITEM_SOURCES = ('Creature drop', 'From a rare', 'Sold by a vendor', 'Sold by a quartermaster')


class Refused(Exception):
    """The site said "not you", or stopped answering: the run stops here."""


# Where things are kept ----------------------------------------------------------------------------------------------

def blob_path(data, key):
    return os.path.join(data, 'sources', 'blobs', key[7:9], key)


def keep(data, path, body):
    """Keeps body once in the blob store and links it at site/<path>. Returns its key."""
    key = 'sha256-' + hashlib.sha256(body).hexdigest()
    blob = blob_path(data, key)
    if not os.path.isfile(blob):
        os.makedirs(os.path.dirname(blob), exist_ok=True)
        with open(blob + f'.{os.getpid()}.part', 'wb') as handle:
            handle.write(body)
        os.replace(blob + f'.{os.getpid()}.part', blob)
    dest = os.path.join(data, 'foreverchanges', 'site', path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + f'.{os.getpid()}.link'
    if os.path.lexists(part):
        os.remove(part)
    try:
        os.link(blob, part)
    except OSError:
        with open(blob, 'rb') as src, open(part, 'wb') as out:
            out.write(src.read())
    os.replace(part, dest)
    return key


def folder(data):
    return os.path.join(data, 'foreverchanges')


def readings(data):
    """{file: its last reading} from pages.jsonl."""
    out = {}
    try:
        with open(os.path.join(folder(data), 'pages.jsonl'), encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get('f'), str):
                    out[row['f']] = row
    except FileNotFoundError:
        pass
    return out


def note(data, row):
    os.makedirs(folder(data), exist_ok=True)
    with open(os.path.join(folder(data), 'pages.jsonl'), 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, separators=(',', ':')) + '\n')


def kept(data, file):
    """The kept body of a file (unzipped), or None."""
    path = os.path.join(folder(data), 'site', file)
    try:
        with open(path, 'rb') as handle:
            body = handle.read()
    except OSError:
        return None
    return gzip.decompress(body) if file.endswith('.gz') else body


# Reading the site ---------------------------------------------------------------------------------------------------

def http_get(path, timeout=60):
    """(status, headers {lower name: value}, body) of one request, asked for compressed. A status is returned, not
    raised; a connection that fails raises OSError."""
    request = urllib.request.Request(BASE + path, headers={'User-Agent': AGENT, 'Accept-Encoding': 'gzip'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, headers, body = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, headers, body = error.code, error.headers, error.read() if error.fp else b''
    heads = {k.lower(): v for k, v in (headers.items() if headers else [])}
    if heads.get('content-encoding', '').lower() == 'gzip' and body:
        body = gzip.decompress(body)
    return status, heads, body


def challenged(headers, body):
    """A Cloudflare bot check instead of the page: a refusal, never something to get around."""
    return headers.get('cf-mitigated', '').lower() == 'challenge' or b'challenge-platform' in body[:20000] or b'<title>Just a moment' in body[:2000]


class Pacer:
    """The pause between two requests, moved by what the site says. `pause` is the floor; what a run learnt is kept
    in pacer.json and the next run starts from it."""

    SLOW = 4.0          # seconds: an answer slower than this lengthens the pause
    EASE_AFTER = 50     # quick answers in a row before the pause eases back
    MOST = 120.0

    def __init__(self, pause=2.5, learnt=None, clock=time.time, sleep=time.sleep):
        self.floor = max(1.0, float(pause))
        self.pause = max(self.floor, float((learnt or {}).get('pause') or 0))
        self.throttles = int((learnt or {}).get('throttles') or 0)
        self.quick = 0
        self.clock, self.sleep = clock, sleep
        self.last = None

    def wait(self):
        if self.last is not None:
            left = self.last + self.pause - self.clock()
            if left > 0:
                self.sleep(left)
        self.last = self.clock()

    def answered(self, seconds):
        if seconds > self.SLOW:
            self.pause = min(self.MOST, self.pause * 1.25)
            self.quick = 0
            return
        self.quick += 1
        if self.quick >= self.EASE_AFTER and self.pause > self.floor:
            self.pause = max(self.floor, self.pause * 0.9)
            self.quick = 0

    def throttled(self, retry_after=None):
        """A 429 or 503: the pause doubles; returns how long to wait before asking again."""
        self.throttles += 1
        self.quick = 0
        self.pause = min(self.MOST, self.pause * 2)
        try:
            asked = float(retry_after) if retry_after is not None else 0.0
        except ValueError:
            asked = 0.0
        return max(60.0, min(asked, 3600.0))

    def learnt(self):
        return {'pause': round(self.pause, 2), 'throttles': self.throttles, 'at': int(self.clock())}


def disallowed(robots):
    """The paths robots.txt closes to every agent."""
    closed, ours = [], False
    for line in robots.splitlines():
        line = line.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        field, value = (part.strip() for part in line.split(':', 1))
        if field.lower() == 'user-agent':
            ours = value == '*'
        elif ours and field.lower() == 'disallow' and value:
            closed.append(value)
    return closed


def allowed(path, closed):
    return not any(path.startswith(prefix) for prefix in closed)


def main_of(body):
    """A page's <title> and <main>: the rest is the site's frame, the same on every page."""
    text = body.decode('utf-8', 'replace')
    main = re.search(r'<main\b.*?</main>', text, re.S)
    if not main:
        return None
    title = re.search(r'<title>(.*?)</title>', text, re.S)
    return ((title.group(0) if title else '') + '\n' + main.group(0)).encode('utf-8')


def locs(sitemap):
    return [html.unescape(loc)[len(BASE):] for loc in re.findall(r'<loc>([^<]+)</loc>', sitemap) if loc.startswith(BASE + '/')]


# What to read, in what order ----------------------------------------------------------------------------------------

REST = 40   # the tiers from here on are the rest of the site, after every gap


def plan(sitemap, quest_sitemap, item_sitemap, wanted=None, whole=False):
    """[(tier, path on the site, file kept)] in the order of the top of this file: the gaps (tiers below REST), then
    with `whole` the rest of the site (every other map's files, quest page and item page). Without `wanted` and
    without `whole` that is the continents' map files only."""
    wanted = wanted or {}
    gap_quests = {int(q) for q in wanted.get('quests') or []}
    first_items = {int(i) for i in wanted.get('items_first') or []}
    gap_items = {int(i) for i in wanted.get('items') or []}
    out, maps = [], []
    for path in locs(sitemap):
        parts = [p for p in path.split('/') if p]
        if not parts or not all(SLUG.fullmatch(p) for p in parts):
            continue
        if parts[0] == 'map' and len(parts) == 2 and (whole or parts[1] in CONTINENTS) and parts[1] not in maps:
            maps.append(parts[1])
    # the continents first (who starts a quest, by id: what a quest without a giver is looked up in), then the others
    # in the sitemap's order
    for rank, slug in enumerate(sorted(maps, key=lambda s: (CONTINENTS.get(s, len(CONTINENTS)), maps.index(s)))):
        for name in MAP_FILES:
            out.append((10 if slug in CONTINENTS else REST, f'/map/{slug}/{name}.json', f'map/{slug}/{name}.json', rank))
    for kind, text in (('quest', quest_sitemap), ('item', item_sitemap)):
        pages = {}
        for path in locs(text):
            m = re.fullmatch(rf'/{kind}/(\d{{1,10}})/([a-z0-9-]{{1,160}})', path)
            if m:
                pages.setdefault(int(m.group(1)), path)
        for number, path in pages.items():
            if kind == 'quest':
                tier = 20 if number in gap_quests else REST + 1 if whole else None
            else:
                tier = 21 if number in first_items else 31 if number in gap_items else REST + 2 if whole else None
            if tier is not None:            # without `whole`, a page no gap asks about is never read
                out.append((tier, path, f'{kind}/{number}.html.gz', number))
    seen = set()
    out = [row for row in out if not (row[2] in seen or seen.add(row[2]))]
    # within a tier: the maps in the order above, the quests and items by id
    return [row[:3] for row in sorted(out, key=lambda row: (row[0], row[3]))]


def due(steps, read, older_days, now):
    """The steps of a run. The gaps (tiers below REST) first: what was never read, in the plan's order, then what was
    read longer than older_days ago, oldest first within each tier. Then the rest of the site the same way, its old
    files oldest first whatever their tier, so that a full pass goes round evenly. A file the site did not have (404)
    is asked again four times less often: most maps have three of their twelve files."""
    def old(row):
        return int(row.get('at') or 0) < now - older_days * 86400 * (4 if row.get('s') == 404 else 1)
    out = []
    for gaps in (True, False):
        group = [s for s in steps if (s[0] < REST) == gaps]
        fresh = [s for s in group if s[2] not in read]
        stale = [s for s in group if s[2] in read and old(read[s[2]])]
        stale.sort(key=lambda s: (s[0] if gaps else 0, int(read[s[2]].get('at') or 0)))
        out += fresh + stale
    return out


def pull(data, wanted=None, pause=2.5, limit=3000, older=14, whole=True, pack_every=500, get=http_get, clock=time.time, sleep=time.sleep, log=print):
    """One visit of the site (see the top of this file): the gaps `wanted` names, then with `whole` the rest of the
    site. Every `pack_every` files read (0: never) the pack is written again, so a visit cut short (a restart) leaves
    a pack of what it read; the caller writes it at the end. Returns {'read', 'new', 'changed', 'missing', 'left',
    'left_gaps', 'stopped', 'pause'}."""
    os.makedirs(folder(data), exist_ok=True)
    try:
        with open(os.path.join(folder(data), 'pacer.json'), encoding='utf-8') as handle:
            learnt = json.load(handle)
    except (OSError, ValueError):
        learnt = None
    pacer = Pacer(pause, learnt, clock, sleep)
    counts = collections.Counter()
    stopped = ''

    def ask(path):
        """(status, headers, body) of one path, after the pause; throttles waited out; a refusal raises."""
        throttled = failed = 0
        while True:
            pacer.wait()
            started = clock()
            try:
                status, headers, body = get(path)
            except OSError as error:
                failed += 1
                if failed >= 3:
                    raise Refused(f'{path}: no answer three times ({error})')
                sleep(30)
                continue
            if status in (429, 503):
                throttled += 1
                wait = pacer.throttled(headers.get('retry-after'))
                log(f'foreverchanges: {path} answered {status}: waiting {wait:.0f} s, then one request every {pacer.pause:.1f} s')
                if throttled >= 3:
                    raise Refused(f'{path}: {status} three times in a row')
                sleep(wait)
                continue
            if status in (401, 403, 451) or challenged(headers, body):
                raise Refused(f'{path}: {status} (the site refused; nothing is retried around a refusal)')
            pacer.answered(clock() - started)
            return status, headers, body

    try:
        status, _h, robots = ask('/robots.txt')
        closed = disallowed(robots.decode('utf-8', 'replace')) if status == 200 else []
        maps = []
        for path in SITEMAPS:
            if not allowed(path, closed):
                maps.append('')
                continue
            status, _h, body = ask(path)
            if status != 200:
                raise Refused(f'{path}: {status}')
            maps.append(body.decode('utf-8', 'replace'))
        steps = [s for s in plan(*maps, wanted=wanted, whole=whole) if allowed(s[1], closed)]
        read = readings(data)
        todo = due(steps, read, older, clock())
        counts['left'] = max(0, len(todo) - limit)
        counts['left_gaps'] = sum(1 for s in todo[limit:] if s[0] < REST)
        for tier, path, file in todo[:limit]:
            status, headers, body = ask(path)
            row = {'f': file, 'at': int(clock()), 's': status}
            if status == 200:
                if file.endswith('.json'):
                    try:
                        json.loads(body)
                    except ValueError:
                        raise Refused(f'{path}: not the data file (a page that is not the page)')
                    content = body
                else:
                    main = main_of(body)
                    if main is None:
                        raise Refused(f'{path}: no <main> in the answer (a page that is not the page)')
                    content = gzip.compress(main, mtime=0)
                row['key'] = keep(data, file, content)
                before = read.get(file, {}).get('key')
                counts['new' if before is None else 'changed' if before != row['key'] else 'same'] += 1
            elif status == 404:
                counts['missing'] += 1
            else:
                raise Refused(f'{path}: {status}')
            note(data, row)
            counts['read'] += 1
            if counts['read'] % 100 == 0:
                log(f"foreverchanges: {counts['read']} of {min(limit, len(todo))} read (tier {tier}), one request every {pacer.pause:.1f} s")
            if pack_every > 0 and counts['read'] % pack_every == 0 and counts['read'] < min(limit, len(todo)):
                try:
                    content = write_pack(data)
                    log(f"foreverchanges: pack written ({len(content['quests'])} quests, {len(content['items'])} items with a source)")
                except (OSError, ValueError) as error:
                    log(f'foreverchanges: the pack could not be written ({error}): kept for the end of the visit')
    except Refused as error:
        stopped = str(error)
        log(f'foreverchanges: stopped: {stopped}')
    with open(os.path.join(folder(data), 'pacer.json'), 'w', encoding='utf-8') as handle:
        json.dump(pacer.learnt(), handle)
    return dict(counts, stopped=stopped, pause=round(pacer.pause, 2))


def status(data, clock=time.time):
    """What the folder holds: {'files', 'by_group', 'missing', 'newest', 'pause'}."""
    read = readings(data)
    groups = collections.Counter(f.split('/', 1)[0] for f, r in read.items() if r.get('s') == 200)
    try:
        with open(os.path.join(folder(data), 'pacer.json'), encoding='utf-8') as handle:
            pause = json.load(handle).get('pause')
    except (OSError, ValueError):
        pause = None
    newest = max((int(r.get('at') or 0) for r in read.values()), default=0)
    return {'files': sum(groups.values()), 'by_group': dict(groups), 'missing': sum(1 for r in read.values() if r.get('s') == 404),
            'newest': time.strftime('%Y-%m-%d %H:%M', time.localtime(newest)) if newest else '', 'pause': pause}


# A small tree of a page (the parsers below are those of the reader in PR 35, tried on the pages of 2026-11-15) ------

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


def _parents(node):
    while node.parent is not None:
        node = node.parent
        yield node


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
        if coord:
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
    known = work.first(cls='qp-known')
    out['new'] = bool(work.first(cls='qp-new')) or bool(re.search(r'\bNew in Forever\b', work.text()[:3000]))
    out['seen_by_players'] = bool(known and 'players of our addon saw' in known.text())
    sheet = work.first(cls='qp-sheet')
    for child in (sheet.children if sheet else ()):
        if not isinstance(child, Node):
            continue
        if 'qp-gains' in child.classes():
            xp = child.first('b')
            out['xp'] = _number(xp.text()) if xp else None
        if 'qp-rep' in child.classes():
            out['reputation'] = [li.text() for li in child.all('li')]
        if 'qp-more' in child.classes():
            for details in child.all('details'):
                label = details.first('summary').text() if details.first('summary') else ''
                body = _paragraphs(details.all('p'))
                if body and label in QUEST_TEXTS:
                    out['texts'][QUEST_TEXTS[label]] = body
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
            elif label in ('Side', 'Class', 'Type'):
                out[label.lower()] = child.text()
    return out


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
    """Where an item comes from, as its page states it, or None when it is not an item page. Each source is
    {'how': the group's heading, 'name', 'place', 'x', 'y', 'price' (copper), 'rate'}. A source the site names no
    one for ("Creature drop" under "Creature drop") keeps its heading as its name, and matches nobody."""
    root = tree(text)
    heading = root.first('h1')
    if not heading or not root.first(cls='it-from') and 'item ' not in root.text()[:4000]:
        return None
    out = {'name': heading.text(), 'sources': []}
    m = re.search(r'\bitem (\d+)\b', root.text())
    out['id'] = int(m.group(1)) if m else None
    out['new'] = 'New in Forever' in root.text()
    for section in root.all('section', 'it-from'):
        for group in section.all(cls='it-from-group'):
            how = group.first('h3').text() if group.first('h3') else ''
            if how not in ITEM_SOURCES:
                continue                                   # "Asked for by", "Reward from": quests, not sources
            for li in group.all('li'):
                name, place, last = li.first('b'), li.first('span'), li.first('em')
                words = list(li.strings())
                entry = {'how': how, 'name': name.text() if name else (words[0] if words else '')}
                if not name and len(words) > 2:            # a dungeon's boss: "Boss", "Dungeon", "31%"
                    entry['place'] = words[1]
                if place:
                    words = place.text()
                    c = re.search(r'\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)', words)
                    entry['place'] = words[:c.start()].strip() if c else words
                    if c:
                        entry['x'], entry['y'] = float(c.group(1)), float(c.group(2))
                if last:
                    price = _copper(last.text())
                    if price is not None and how.startswith('Sold by'):
                        entry['price'] = price
                    else:
                        entry['rate'] = _rate(last.text())
                        counted = re.search(r'(\d+) in (\d+) kills?', last.attrs.get('title') or '')
                        if counted:
                            entry['rate'].update(drops=int(counted.group(1)), kills=int(counted.group(2)))
                out['sources'].append(entry)
    return out


# The pack ----------------------------------------------------------------------------------------------------------

def _json(data, file):
    body = kept(data, file)
    try:
        return json.loads(body) if body is not None else None
    except ValueError:
        return None


def parsed(data, read):
    """{file: what its kept page states}, each page read once: parsed.jsonl remembers what a key stated."""
    path = os.path.join(folder(data), 'parsed.jsonl')
    known = {}
    try:
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    known[row['key']] = row['rec']
                except (ValueError, KeyError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    out, fresh = {}, []
    for file, row in read.items():
        kind = file.split('/', 1)[0]
        if kind not in ('quest', 'item') or row.get('s') != 200 or not row.get('key'):
            continue
        if row['key'] not in known:
            body = kept(data, file)
            text = body.decode('utf-8', 'replace') if body else ''
            known[row['key']] = (quest if kind == 'quest' else item)(text) if text else None
            fresh.append({'key': row['key'], 'rec': known[row['key']]})
        if known[row['key']]:
            out[file] = known[row['key']]
    if fresh:
        with open(path, 'a', encoding='utf-8') as handle:
            for row in fresh:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
    return out


def _entry(code):
    """'n620' -> ('npc', 620); 'o9000' -> ('go', 9000); else None."""
    m = re.fullmatch(r'([no])(\d{1,9})', str(code or ''))
    return ({'n': 'npc', 'o': 'go'}[m.group(1)], int(m.group(2))) if m else None


def maps(data, read):
    """(npcs, pins, givers) of every map folder kept. A folder's map is its manifest's mapId (the continents' are
    known without it): a pin or an NPC of a folder whose map is not known is left out."""
    slugs = sorted({f.split('/')[1] for f in read if f.startswith('map/') and f.count('/') == 2})
    npcs, pins, givers = [], [], []
    for slug in slugs:
        manifest = _json(data, f'map/{slug}/manifest.json') or {}
        map_id = CONTINENTS.get(slug, manifest.get('mapId') if isinstance(manifest.get('mapId'), int) else None)
        if map_id is None:
            continue
        for row in (_json(data, f'map/{slug}/npcs.json') or {}).get('npcs') or []:
            if isinstance(row, list) and len(row) >= 7 and isinstance(row[0], int) and isinstance(row[4], (int, float)) and isinstance(row[5], (int, float)):
                npcs.append({'entry': row[0], 'name': row[1], 'side': row[3], 'map': map_id, 'x': row[4], 'y': row[5], 'kind': row[6], 'seen': 'addon' in row[7:]})
        for name, kind in PINS.items():
            for pin in (_json(data, f'map/{slug}/{name}') or {}).get('pins') or []:
                if isinstance(pin, dict) and pin.get('name') and isinstance(pin.get('x'), (int, float)) and isinstance(pin.get('y'), (int, float)):
                    pins.append({'map': map_id, 'kind': kind, 'name': pin['name'], 'x': pin['x'], 'y': pin['y'], 'side': pin.get('faction') or ''})
        for row in (_json(data, f'map/{slug}/quest-givers.json') or {}).get('givers') or []:
            # [code, name, title, side, x, y, [quests], 'addon'?]
            if not isinstance(row, list) or len(row) < 7 or not isinstance(row[6], list):
                continue
            who = _entry(row[0])
            quests = [q for q in row[6] if isinstance(q, int) and not isinstance(q, bool) and q > 0]
            if who and quests and isinstance(row[4], (int, float)) and isinstance(row[5], (int, float)):
                givers.append({'kind': who[0], 'entry': who[1], 'name': str(row[1] or ''), 'map': map_id, 'x': row[4], 'y': row[5],
                               'quests': quests, 'seen': 'addon' in row[7:]})
    return npcs, pins, givers


def pack(data):
    """The pack tools/ft/reports.py reads, from what is kept: {'format', 'site', 'retrieved', 'quests', 'items',
    'npcs', 'pins', 'givers'}."""
    read = readings(data)
    records = parsed(data, read)
    quests, items = [], []
    for file, rec in sorted(records.items()):
        number = int(re.search(r'(\d+)', file).group(1))
        if file.startswith('quest/'):
            rec = dict(rec, id=rec.get('id') if isinstance(rec.get('id'), int) else number)
            quests.append({k: rec[k] for k in QUEST_FIELDS if rec.get(k) not in (None, [], {}, '')})
        else:
            sources = [s for s in rec.get('sources') or [] if isinstance(s, dict) and s.get('how') in ITEM_SOURCES]
            if sources:
                items.append({'id': number, 'name': rec.get('name', ''), 'new': bool(rec.get('new')), 'sources': sources})
    npcs, pins, givers = maps(data, read)
    newest = max((int(r.get('at') or 0) for r in read.values() if r.get('s') == 200), default=0)
    return {'format': FORMAT, 'site': 'foreverchanges.pro', 'retrieved': time.strftime('%Y-%m-%d', time.localtime(newest)) if newest else '',
            'quests': quests, 'items': items, 'npcs': npcs, 'pins': pins, 'givers': givers}


def write_pack(data, out=None):
    """Writes the pack (pack.json in a zip) where the tracker reads it. Returns the pack."""
    content = pack(data)
    out = out or os.path.join(folder(data), 'pack.fcpack')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out + '.part', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('pack.json', json.dumps(content, ensure_ascii=False, separators=(',', ':')))
    os.replace(out + '.part', out)
    return content
