"""The cache of Wowhead pages (tools/wowhead-pages/cache/<kind>.jsonl) and what to read next.

Wowhead's pages cannot be asked from a script (403), so they are read slowly from a browser tab by
tools/wowhead-pages/crawler.js, which keeps facts only (docs/WOWHEAD-PAGES.md). This tool is the other half:

    python tools/wowhead_pages.py todo forever-tracker-todo.csv      what the crawler should read next, as the
                                                                     WHC.add(...) lines to paste in the tab
    python tools/wowhead_pages.py merge wowhead-pages.jsonl          what the crawler saved, into the cache
    python tools/wowhead_pages.py stats                              what the cache holds

The cache is one line a page, sorted by id, so that a new crawl is a readable diff. A page is never asked twice:
`todo` leaves out what the cache has, unless it is older than --max-age days.
"""
import argparse
import csv
import json
import os
import re
import sys
import time

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wowhead-pages', 'cache')
KINDS = ('item', 'npc', 'quest', 'object', 'spell', 'zone', 'faction', 'itemset')
KEPT = ('ok', 'missing')   # 'blocked' and 'odd' are no answer: the page is asked again
MAX_ID = 2 ** 31 - 1


def path(kind, folder=CACHE):
    return os.path.join(folder, f'{kind}.jsonl')


def numbers_only(value):
    """True when a tab's row holds nothing but numbers, true/false and null, at any depth: the cache keeps no text."""
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, list):
        return all(numbers_only(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and re.fullmatch(r'[\w-]{1,40}', k) and numbers_only(v) for k, v in value.items())
    return False


def clean(record):
    """A crawler record as the cache keeps it, or None when it is not one: a known kind, a whole id, an answer
    ('ok' or 'missing'), Quick Facts lines of a line's length, tabs of rows that hold numbers only."""
    if not isinstance(record, dict) or record.get('kind') not in KINDS or record.get('status') not in KEPT:
        return None
    entity, fetched = record.get('id'), record.get('fetched')
    if not isinstance(entity, int) or isinstance(entity, bool) or not 0 < entity <= MAX_ID or not isinstance(fetched, int) or fetched <= 0:
        return None
    out = {'id': entity, 'fetched': fetched, 'v': int(record.get('v') or 0), 'status': record['status']}
    if record['status'] == 'missing':
        return out
    quick = record.get('quick') or []
    tabs = record.get('tabs') or {}
    if not isinstance(quick, list) or not isinstance(tabs, dict):
        return None
    out['quick'] = [line for line in quick if isinstance(line, str) and 0 < len(line) <= 300 and '\n' not in line]
    out['tabs'] = {}
    for name, tab in sorted(tabs.items()):
        if not re.fullmatch(r'[\w-]{1,60}', str(name)) or not isinstance(tab, dict) or not isinstance(tab.get('rows'), list):
            continue
        rows = [row for row in tab['rows'] if isinstance(row, dict) and numbers_only(row)]
        kept = {'template': str(tab.get('template') or '')[:40], 'rows': rows}
        if isinstance(tab.get('total'), int) and tab['total'] > len(rows):
            kept['total'] = tab['total']
        out['tabs'][name] = kept
    for extra in ('map', 'series'):
        if record.get(extra) and numbers_only(record[extra]):
            out[extra] = record[extra]
    return out


def load(kind, folder=CACHE):
    """{id: record} of one kind; a line that does not read is skipped."""
    pages = {}
    try:
        with open(path(kind, folder), encoding='utf-8') as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and isinstance(record.get('id'), int):
                    pages[record['id']] = record
    except OSError:
        pass
    return pages


def save(kind, pages, folder=CACHE):
    """Writes one kind whole or not at all, sorted by id."""
    os.makedirs(folder, exist_ok=True)
    scratch = f'{path(kind, folder)}.{os.getpid()}.tmp'
    with open(scratch, 'w', encoding='utf-8', newline='\n') as handle:
        for entity in sorted(pages):
            handle.write(json.dumps(pages[entity], ensure_ascii=False, separators=(',', ':')) + '\n')
    os.replace(scratch, path(kind, folder))


def merge(files, folder=CACHE):
    """Reads what the crawler saved into the cache: the newer answer of a page wins. Returns the counts."""
    counts = {'new': 0, 'newer': 0, 'older': 0, 'not_a_page': 0}
    incoming = {}
    for name in files:
        with open(name, encoding='utf-8') as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    counts['not_a_page'] += 1
                    continue
                record = clean(raw)
                if record is None:
                    counts['not_a_page'] += 1
                    continue
                incoming.setdefault(raw['kind'], []).append(record)
    for kind, records in incoming.items():
        pages = load(kind, folder)
        for record in records:
            have = pages.get(record['id'])
            if have is None:
                counts['new'] += 1
            elif have.get('fetched', 0) < record['fetched']:
                counts['newer'] += 1
            else:
                counts['older'] += 1
                continue
            pages[record['id']] = record
        save(kind, pages, folder)
    return counts


# what a line of the tracker's "To add" list says about the pages worth reading (app/pages/todo.php, ?format=csv)
ITEM_IN_REASON = (
    ('quest', re.compile(r'item (\d+) not obtainable')),
    ('quest', re.compile(r'Quest giver: item (\d+)')),
    ('toy', re.compile(r'Item (\d+) has no source')),
)
ITEMS_IN_REASON = (
    ('recipe', re.compile(r'(?:cannot be obtained: |Taught by item )([\d, ]+)')),
    ('mount', re.compile(r'cannot be obtained: ([\d, ]+)')),
    ('spell', re.compile(r'Taught by item ([\d, ]+)')),
)
QUEST_REASONS = re.compile(r'No quest giver|No quest ender|\(not spawned\)|Quest giver: item')


def wanted(rows, min_item=0):
    """From the To add list: {'item': [...], 'quest': [...]}, the pages that can close a gap, the most useful first.
    Items another thing waits for (a quest objective, a recipe, a mount, a toy, a spell) come before the items that
    only lack a source; of those, only ids from min_item up (0: all)."""
    blocking, plain, quests = {}, {}, {}
    for row in rows:
        kind, reason = row.get('type', ''), row.get('missing', '')
        try:
            entity = int(row.get('id', ''))
        except ValueError:
            continue
        if row.get('phase'):
            continue   # waits for a release phase: no gap today
        if kind == 'item' and 'No source' in reason and entity >= min_item:
            plain[entity] = True
        if kind == 'quest' and QUEST_REASONS.search(reason):
            quests[entity] = True
        for owner, pattern in ITEM_IN_REASON:
            if kind == owner:
                for found in pattern.finditer(reason):
                    blocking[int(found.group(1))] = True
        for owner, pattern in ITEMS_IN_REASON:
            found = pattern.search(reason) if kind == owner else None
            if found:
                for number in re.findall(r'\d+', found.group(1)):
                    blocking[int(number)] = True
    blocking.pop(0, None)
    return {'item': sorted(blocking) + sorted(i for i in plain if i not in blocking), 'quest': sorted(quests)}


def todo(csv_path, kinds, min_item, max_age, folder=CACHE, now=None):
    """{kind: [ids]} still to read: wanted and not in the cache (or older than max_age days, 0: never too old)."""
    now = time.time() if now is None else now
    with open(csv_path, encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle, delimiter=';'))
    out = {}
    for kind, ids in wanted(rows, min_item).items():
        if kinds and kind not in kinds:
            continue
        pages = load(kind, folder)
        fresh = {i for i, p in pages.items() if not max_age or now - p.get('fetched', 0) <= max_age * 86400}
        out[kind] = [i for i in ids if i not in fresh]
    return out


def stats(folder=CACHE):
    lines = []
    for kind in KINDS:
        pages = load(kind, folder)
        if not pages:
            continue
        ok = [p for p in pages.values() if p['status'] == 'ok']
        tabs = {}
        for page in ok:
            for name, tab in page.get('tabs', {}).items():
                if tab['rows']:
                    tabs[name] = tabs.get(name, 0) + 1
        newest = time.strftime('%Y-%m-%d', time.gmtime(max(p['fetched'] for p in pages.values())))
        lines.append(f'{kind}: {len(ok)} pages, {len(pages) - len(ok)} Wowhead does not have, newest {newest}')
        lines.extend(f'    {name:<28}{n:>6} pages' for name, n in sorted(tabs.items(), key=lambda t: -t[1]))
    return lines or ['the cache is empty']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    m = sub.add_parser('merge', help='what the crawler saved (wowhead-pages.jsonl), into the cache')
    m.add_argument('files', nargs='+')
    t = sub.add_parser('todo', help="the pages worth reading, from the tracker's To add list (Export CSV)")
    t.add_argument('csv')
    t.add_argument('--kind', action='append', choices=('item', 'quest'), help='only this kind (may be given twice)')
    t.add_argument('--min-item', type=int, default=190000, help='items that only lack a source: from this id up (default 190000: '
                   'below it are the original game\'s items, whose missing ones are mostly test items; 0 for all)')
    t.add_argument('--max-age', type=float, default=0, help='read a cached page again when it is older than this many days (default: never)')
    t.add_argument('--limit', type=int, default=0, help='at most this many pages a kind')
    sub.add_parser('stats', help='what the cache holds')
    args = parser.parse_args(argv)
    if args.command == 'merge':
        counts = merge(args.files)
        print(', '.join(f'{n} {name.replace("_", " ")}' for name, n in counts.items()))
    elif args.command == 'todo':
        for kind, ids in todo(args.csv, args.kind, args.min_item, args.max_age).items():
            ids = ids[:args.limit] if args.limit else ids
            print(f'// {kind}: {len(ids)} pages, about {len(ids) / 2.8 / 60:.1f} h at one page every 20 seconds or so', file=sys.stderr)
            if ids:
                print(f"await WHC.add('{kind}', {json.dumps(ids, separators=(',', ':'))});")
    else:
        print('\n'.join(stats()))


if __name__ == '__main__':
    main()
