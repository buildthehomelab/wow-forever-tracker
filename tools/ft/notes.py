"""Written notes for the timeline's builds and hotfix days, from other sites (docs/CLIENT.md, "Notes").

The CDN says WHAT changed in a build or a hotfix; it says nothing of WHY, and a hotfix cache carries no dates. Blizzard's
own notes are posted on its forums, one thread a patch, and a few sites collect them day by day. The first of those read
here is ForeverChanges (https://foreverchanges.pro/patch-notes): every build and every hotfix day since the beta, each
with the notes Blizzard posted for it (and a link to the post), or a line the site wrote itself where Blizzard posted
none. It fills gaps until the tracker's own sources (the CDN first, then Wowhead, then Icy Veins) say as much: what it
says is shown as its words, under its name, and never changes a value of the official list.

A note: {'source', 'id' ('hotfix-2026-11-13' or '1.60.1.70938'), 'kind' ('hotfix' | 'build'), 'day', 'build' (a build's
number, None for a hotfix day), 'title', 'url', 'blizzard' (links to Blizzard's posts), 'summary' (the site's opening
lines), 'sections' ([{'name', 'lines': [{'text', 'mark' ('buff' | 'nerf' | 'change' | '')}]}])}.
"""
import datetime
import email.utils
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree

FOREVERCHANGES = 'https://foreverchanges.pro/patch-notes'
FILE = 'foreverchanges.json'
SOURCE = 'ForeverChanges'
MAX_PAGES = 20            # the site has 5 pages today; a page that is not there (404) ends the list
PAUSE = 2.0               # seconds between two pages: a small site, read slowly
ENTRY = re.compile(r'<li id="((?:hotfix|update)-\d{4}-\d\d-\d\d|\d+\.\d+\.\d+\.\d+)"[^>]*>')
# a block of lines: a section of a topic or class, or a folded class (<details>, its name in <summary>)
FOLD = re.compile(r'<details\b[^>]*class="bt-note-class[^"]*"[^>]*>(.*?)</details>', re.S)
SECTION = re.compile(r'<section\b[^>]*\bdata-(?:topic|class)="([^"]+)"[^>]*>(.*?)</section>', re.S)
LINE = re.compile(r'<li\b[^>]*>(.*?)</li>', re.S)
MARK = re.compile(r'aria-label="(Buffs|Nerfs|Changes)"')
MARKS = {'Buffs': 'buff', 'Nerfs': 'nerf', 'Changes': 'change'}


def text(fragment):
    """The words of an HTML fragment, on one line: tags, icons' titles and comments taken away."""
    fragment = re.sub(r'<title>.*?</title>|<!--.*?-->', '', fragment, flags=re.S)
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', fragment))).strip()


def parse_page(page, base=FOREVERCHANGES):
    """The notes of one page of the site, in the page's order (newest first)."""
    found = []
    starts = list(ENTRY.finditer(page))
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(page)
        if index + 1 == len(starts):
            close = page.find('</ol>', start.end())   # the last note of a page ends with the list
            end = close if close > 0 else end
        body = page[start.end():end]
        anchor = start.group(1)
        day = re.search(r'<time [^>]*date[Tt]ime="(\d{4}-\d\d-\d\d)"', body)
        hotfix = not re.match(r'\d', anchor)    # a hotfix day, or a server update without a build
        if not day and hotfix:
            day = re.search(r'(\d{4}-\d\d-\d\d)', anchor)
        sections = []
        blocks = []
        for fold in FOLD.finditer(body):
            summary = re.search(r'<summary[^>]*>(.*?)</summary>', fold.group(1), re.S)
            name = re.search(r'<span[^>]*>(.*?)</span>', summary.group(1), re.S) if summary else None
            blocks.append((text(name.group(1)) if name else 'Notes', fold.group(1)[summary.end() if summary else 0:]))
        rest = FOLD.sub('', body)
        for section in SECTION.finditer(rest):
            heading = re.search(r'<h3[^>]*>(.*?)</h3>', section.group(2), re.S)
            blocks.append((text(heading.group(1)) if heading else section.group(1).replace('-', ' ').title(), section.group(2)))
        for name, block in blocks:
            lines = []
            for line in LINE.finditer(block):
                if '<li' in line.group(1):
                    continue   # a list inside a line: its own lines are read
                words = text(line.group(1))
                if words:
                    mark = MARK.search(line.group(1))
                    lines.append({'text': words, 'mark': MARKS.get(mark.group(1), '') if mark else ''})
            if lines:
                sections.append({'name': name, 'lines': lines})
        # the site's own opening lines: the paragraphs before the first block
        head = re.split(r'<section\b|<details\b', body, maxsplit=1)[0]
        summary = [words for words in (text(p) for p in re.findall(r'<p\b[^>]*>(.*?)</p>', head, re.S)) if words and words != 'From Blizzard’s notes:']
        found.append({
            'source': SOURCE, 'id': anchor, 'kind': 'hotfix' if hotfix else 'build',
            'day': day.group(1) if day else None,
            'build': None if hotfix else int(anchor.rsplit('.', 1)[1]),
            'url': f'{base}#{anchor}',
            'blizzard': sorted(set(re.findall(r'href="(https://[a-z]+\.forums\.blizzard\.com/[^"]+)"', body))),
            'summary': summary[:3], 'sections': sections,
        })
    return found


def parse_feed(feed):
    """{anchor: {'title', 'day', 'description'}} from the site's RSS feed: the dates the site gives each note."""
    out = {}
    try:
        root = ElementTree.fromstring(feed)
    except ElementTree.ParseError:
        return out
    for item in root.iter('item'):
        link = item.findtext('link') or ''
        anchor = link.split('#', 1)[1] if '#' in link else ''
        if not anchor:
            continue
        day = None
        try:
            day = email.utils.parsedate_to_datetime(item.findtext('pubDate') or '').date().isoformat()
        except (TypeError, ValueError):
            pass
        out[anchor] = {'title': (item.findtext('title') or '').strip(), 'day': day, 'description': (item.findtext('description') or '').strip()}
    return out


def title(note):
    if note['kind'] == 'hotfix':
        return 'Hotfix, ' + (datetime.date.fromisoformat(note['day']).strftime('%B %-d, %Y') if note.get('day') else note['id'])
    return f"Build {note['id']}"


def fetch(folder, get=None, pause=PAUSE, log=print):
    """Reads every page of ForeverChanges' patch notes and its feed, and stores the notes in <folder>/foreverchanges.json.
    Returns {'code': 0 stored | 3 unchanged | 2 not read, 'notes', 'message'}. get: url -> text (tests)."""
    get = get or _download
    notes, seen = [], set()
    try:
        feed = parse_feed(get(f'{FOREVERCHANGES}/feed.xml'))
    except (OSError, urllib.error.URLError, RuntimeError) as error:
        log(f'ForeverChanges: the feed could not be read ({error}); the pages are read alone')
        feed = {}
    for number in range(1, MAX_PAGES + 1):
        url = FOREVERCHANGES if number == 1 else f'{FOREVERCHANGES}/page/{number}'
        try:
            page = get(url)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                break
            return {'code': 2, 'notes': 0, 'message': f'ForeverChanges: {url} answered {error.code}: nothing stored'}
        except (OSError, urllib.error.URLError, RuntimeError) as error:
            return {'code': 2, 'notes': 0, 'message': f'ForeverChanges: {url} could not be read ({error}): nothing stored'}
        found = [n for n in parse_page(page, f'{FOREVERCHANGES}' + ('' if number == 1 else f'/page/{number}')) if n['id'] not in seen]
        if not found:
            break
        for note in found:
            seen.add(note['id'])
            info = feed.get(note['id']) or {}
            note['day'] = note['day'] or info.get('day')
            note['title'] = info.get('title') or title(note)
            if not note['summary'] and not note['sections'] and info.get('description'):
                note['summary'] = [info['description']]
            notes.append(note)
        if pause:
            time.sleep(pause)
    if not notes:
        return {'code': 2, 'notes': 0, 'message': 'ForeverChanges: no note found on the pages: nothing stored'}
    notes.sort(key=lambda n: (n.get('day') or '', n['kind'] == 'hotfix', n['id']))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, FILE)
    blob = json.dumps({'source': SOURCE, 'url': FOREVERCHANGES, 'read': datetime.date.today().isoformat(), 'notes': notes},
                      ensure_ascii=False, indent=1)
    try:
        with open(path, encoding='utf-8') as handle:
            if json.load(handle).get('notes') == notes:
                return {'code': 3, 'notes': len(notes), 'message': f'ForeverChanges: {len(notes)} notes, unchanged'}
    except (OSError, ValueError, AttributeError):
        pass
    with open(f'{path}.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
        handle.write(blob)
    os.replace(f'{path}.{os.getpid()}.tmp', path)
    return {'code': 0, 'notes': len(notes), 'message': f'ForeverChanges: {len(notes)} notes stored'}


def load(folder):
    """The stored notes, oldest first; [] when none are stored."""
    try:
        with open(os.path.join(folder, FILE), encoding='utf-8') as handle:
            return [n for n in json.load(handle).get('notes') or [] if isinstance(n, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def hotfix_days(folder):
    """{day: note} of the hotfix days the notes name."""
    return {n['day']: n for n in load(folder) if n.get('kind') == 'hotfix' and n.get('day')}


def _download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ForeverTracker/1.3 (private server admin tool)'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode('utf-8', 'replace')


# ------------------------------------------------------------------ Blizzard's own posts (the blue posts)
# Blizzard's forums run Discourse, which serves every page as JSON as well. Its "Blizzard tracker" group lists every
# post by Blizzard staff (the blue posts) across all of WoW's forums, newest first; WoW: Forever's posts are those in its
# own forum (category 346, the categories under it, and the beta's forum, which sat under the Classic forums). The hotfix threads among them are Blizzard's notes, a day at a
# time; the others (maintenance, known issues, "XP adjustment" announcements) tell of changes made on the servers, which
# no client file shows. Blizzard's words come first, ForeverChanges fills what Blizzard did not post.
FORUM = 'https://us.forums.blizzard.com/en/wow'
BLUE_FILE = 'blizzard.json'
BLIZZARD = 'Blizzard'
FOREVER_FORUM = 346
SINCE = '2026-08-01'          # WoW: Forever was revealed in August 2026: nothing older is read
DAY = re.compile(r'^(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})$')
MONTHS = {m: i for i, m in enumerate(('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
                                      'October', 'November', 'December'), 1)}


def _as_day(words):
    found = DAY.match(words.strip().rstrip(':'))
    if not found:
        return None
    return datetime.date(int(found.group(3)), MONTHS[found.group(1)], int(found.group(2))).isoformat()


def post_days(cooked, fallback):
    """A post's text as [{'day', 'sections': [{'name', 'lines': [{'text', 'mark'}]}]}]: a paragraph that is only a date in
    bold ("November 13, 2026") starts a day, one that is only other bold words a section; a list item that starts with
    bold words and holds a list names the lines under it ("Druid: Feral: ..."). Without any date: the post's own day."""
    days, day, section = [], None, None

    def start_day(value):
        nonlocal day, section
        day = {'day': value, 'sections': []}
        days.append(day)
        section = None

    def add(line, heading=None):
        nonlocal section
        if day is None:
            start_day(fallback)
        name = heading or (section['name'] if section else 'Notes')
        if section is None or section['name'] != name:
            section = {'name': name, 'lines': []}
            day['sections'].append(section)
        section['lines'].append({'text': line, 'mark': ''})

    heading = None
    # the blocks of the post in order: paragraphs, headings, and the top-level lists
    for block in re.finditer(r'<(p|h[1-6])\b[^>]*>(.*?)</\1>|<ul>(.*?)</ul>(?=\s*(?:<p|<h[1-6]|<ul|<hr|<ol|$))', cooked, re.S):
        if block.group(1):
            words = text(block.group(2))
            if not words:
                continue
            bold = re.fullmatch(r'\s*<strong>(.*?)</strong>\s*', block.group(2), re.S)
            as_day = _as_day(words)
            if as_day:
                start_day(as_day)
                heading = None
            elif bold or block.group(1).startswith('h'):
                heading = words
                section = None
            else:
                add(words, heading)
            continue
        for line in _list_lines(block.group(3)):
            add(line, heading)
    return [d for d in days if d['sections']]


def _list_lines(fragment, prefix=''):
    """The lines of a list, nested lists flattened: 'Druid: Feral: Fixed an issue ...'."""
    out, depth, start, items = [], 0, None, []
    for tag in re.finditer(r'<(/?)(li|ul|ol)\b[^>]*>', fragment):
        closing, name = tag.group(1) == '/', tag.group(2)
        if name == 'li':
            if not closing:
                if depth == 0:
                    start = tag.end()
                depth += 1
            else:
                depth -= 1
                if depth == 0 and start is not None:
                    items.append(fragment[start:tag.start()])
                    start = None
    for item in items:
        inner = re.search(r'<(ul|ol)\b', item)
        if inner:
            label = text(item[:inner.start()]).rstrip(':')
            nested = item[inner.start():]
            lines = _list_lines(nested, f'{prefix}{label}: ' if label else prefix)
            out.extend(lines)
        else:
            words = text(item)
            if words:
                out.append(prefix + words)
    return out


def fetch_blizzard(folder, get=None, pause=1.0, log=print, since=SINCE):
    """Reads the blue posts of WoW: Forever's forum, newest first, until the posts already stored or the day 'since', and
    stores them in <folder>/blizzard.json. A post's whole text is read once (its own page); a post edited since (Blizzard
    adds to its hotfix posts) is read again when the list shows a newer edit. get: url -> parsed JSON (tests)."""
    get = get or _json
    path = os.path.join(folder, BLUE_FILE)
    try:
        with open(path, encoding='utf-8') as handle:
            kept = json.load(handle)
        stored = {p['id']: p for p in kept.get('posts') or [] if isinstance(p, dict) and 'id' in p}
        complete = kept.get('complete') or {}
    except (OSError, ValueError, AttributeError):
        stored, complete = {}, {}
    try:
        site = get(f'{FORUM}/site.json')
        # its own forum and the forums under it, and the beta's forum, which sat under the Classic forums
        forever = {FOREVER_FORUM} | {c['id'] for c in site.get('categories') or []
                                     if c.get('parent_category_id') == FOREVER_FORUM or 'forever' in str(c.get('slug', '')).lower()}
    except (OSError, urllib.error.URLError, ValueError, RuntimeError) as error:
        return {'code': 2, 'posts': len(stored), 'message': f"Blizzard's forums could not be read ({error}): nothing stored"}
    before, listed, pages, new, oldest = None, [], 0, 0, ''
    while pages < 100:
        url = f'{FORUM}/groups/blizzard-tracker/posts.json' + (f'?before_post_id={before}' if before else '')
        try:
            posts = get(url).get('posts') or []
        except (OSError, urllib.error.URLError, ValueError, RuntimeError) as error:
            return {'code': 2, 'posts': len(stored), 'message': f"Blizzard's blue posts could not be read ({error}): nothing stored"}
        pages += 1
        if not posts:
            break
        listed.extend(p for p in posts if p.get('category_id') in forever)
        before = min(p['id'] for p in posts)
        oldest = min(p.get('created_at') or '' for p in posts)
        # stop at the day 'since', or, once a whole pass back to that day was made for the same forums, at the first page
        # whose posts are all stored already
        whole = complete.get('since') == since and sorted(complete.get('forums') or []) == sorted(forever)
        if oldest < since or (whole and all(p['id'] in stored for p in posts if p.get('category_id') in forever)):
            break
        if pause:
            time.sleep(pause)
    for item in listed:
        known = stored.get(item['id'])
        # a post is read once; Blizzard's hotfix posts are edited as days are added: those are read again while listed
        if known and not ('hotfix' in (item.get('topic_title') or '').lower() and pages <= 2):
            continue
        try:
            post = get(f"{FORUM}/posts/{item['id']}.json")
        except (OSError, urllib.error.URLError, ValueError, RuntimeError) as error:
            log(f"Blizzard's forums: post {item['id']} could not be read ({error}); its excerpt is kept")
            post = {}
        cooked = post.get('cooked') or ''
        created = item.get('created_at') or ''
        fresh = {
            'id': item['id'], 'date': created, 'edited': post.get('updated_at') or created,
            'author': item.get('username') or '', 'role': item.get('user_title') or '',
            'topic': item.get('topic_title') or '', 'topic_id': item.get('topic_id'), 'reply': (item.get('post_number') or 1) > 1,
            'category': item.get('category_id'),
            'url': f"{FORUM}/t/{item.get('topic_slug') or 'topic'}/{item.get('topic_id')}/{item.get('post_number') or 1}",
            'excerpt': text(item.get('excerpt') or '')[:600],
            'days': post_days(cooked, created[:10]) if cooked else [],
            'hotfixes': 'hotfix' in (item.get('topic_title') or '').lower(),
        }
        if not post and known:
            continue                     # not read this time: what is stored stays
        if not known or any(known.get(k) != fresh[k] for k in ('days', 'excerpt', 'topic')):
            new += 1                     # an edit that only moved the date is no news
        stored[item['id']] = fresh
        if pause:
            time.sleep(pause)
    if not stored:
        return {'code': 2, 'posts': 0, 'message': "Blizzard's forums: no WoW: Forever blue post found: nothing stored"}
    reached = {'since': since, 'forums': sorted(forever)} if oldest < since else complete
    if not new and reached == complete:
        return {'code': 3, 'posts': len(stored), 'message': f"Blizzard's forums: {len(stored)} blue posts, nothing new"}
    os.makedirs(folder, exist_ok=True)
    posts = sorted(stored.values(), key=lambda p: p.get('date') or '')
    with open(f'{path}.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
        json.dump({'source': BLIZZARD, 'url': FORUM, 'read': datetime.date.today().isoformat(), 'complete': reached, 'posts': posts},
                  handle, ensure_ascii=False, indent=1)
    os.replace(f'{path}.{os.getpid()}.tmp', path)
    return {'code': 0, 'posts': len(posts), 'message': f"Blizzard's forums: {new} blue post(s) read, {len(posts)} in all"}


def blue_posts(folder):
    try:
        with open(os.path.join(folder, BLUE_FILE), encoding='utf-8') as handle:
            return [p for p in json.load(handle).get('posts') or [] if isinstance(p, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def days(folder):
    """{day: {'blizzard': {'sections': [{'name', 'lines'}], 'urls': [...]}, 'posts': [ids of the blue posts of that day],
    'foreverchanges': the note's id or None}}: every day something was written about, from both sources. A hotfix post's
    days are the days its text names (Blizzard edits its first post to hold every day, and posts each day again as a
    reply: a line is kept once); any other post counts on the day it was posted (UTC)."""
    out = {}

    def at(day):
        return out.setdefault(day, {'blizzard': {'sections': [], 'urls': []}, 'posts': [], 'foreverchanges': None})
    for post in blue_posts(folder):
        if post.get('hotfixes'):
            for named in post.get('days') or []:
                entry = at(named['day'])['blizzard']
                if post['url'] not in entry['urls']:
                    entry['urls'].append(post['url'])
                for section in named['sections']:
                    into = next((s for s in entry['sections'] if s['name'] == section['name']), None)
                    if into is None:
                        into = {'name': section['name'], 'lines': []}
                        entry['sections'].append(into)
                    seen = {line['text'] for line in into['lines']}
                    into['lines'].extend(line for line in section['lines'] if line['text'] not in seen)
        if post.get('date'):
            at(post['date'][:10])['posts'].append(post['id'])
    for note in load(folder):
        if note.get('kind') == 'hotfix' and note.get('day'):
            at(note['day'])['foreverchanges'] = note['id']
    return out


def _json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ForeverTracker/1.3 (private server admin tool)', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)
