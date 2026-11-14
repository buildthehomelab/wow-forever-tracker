#!/usr/bin/env python3
"""Trims a copy of foreverchanges.pro down to the pack the tracker reads (docs/SOURCES.md, ForeverChanges).

    python tools/foreverchanges_pack.py foreverchanges.db foreverchanges.fcpack

The input is the SQLite file a crawl of the site leaves (tables `exports` and `responses`, bodies gzipped). It is
several hundred MB of pages; the tracker needs the quest and item lists only: who gives and takes each quest and
where, what sells or drops each item. The pack is those two lists, gzipped JSON, a few MB: small enough to send
through the Imports page. The tracker never asks the site for anything.

The site's base is Classic's data with what Forever changed on top. What its players saw is marked, and only that
is evidence about Forever: a quest with `seen_by_players`, a drop counted in kills. The rest is kept in the pack as
the site gives it and left out by the tracker's rules, not here.
"""
import gzip
import json
import sqlite3
import sys

FORMAT = 'foreverchanges-pack/1'
QUEST_FIELDS = ('id', 'title', 'new', 'seen_by_players', 'side', 'class', 'type', 'level', 'min_level', 'start', 'end', 'xp',
                'reputation', 'reward_items', 'texts')
# how an item is come by, as the site words it: the ones the tracker turns into rows
ITEM_SOURCES = ('Creature drop', 'From a rare', 'Sold by a vendor', 'Sold by a quartermaster')


def lines(db, path):
    row = db.execute('SELECT body_gzip FROM exports WHERE path = ?', (path,)).fetchone()
    if not row:
        raise SystemExit(f'{path} is not in this file: is it a crawl of foreverchanges.pro?')
    for line in gzip.decompress(row[0]).decode('utf-8', 'replace').split('\n'):
        if line.strip():
            yield json.loads(line)


def pack(db):
    quests, items, newest = [], [], ''
    for quest in lines(db, 'quests.jsonl'):
        newest = max(newest, str(quest.get('retrieved') or ''))
        quests.append({field: quest[field] for field in QUEST_FIELDS if quest.get(field) not in (None, [], {}, '')})
    for item in lines(db, 'items.jsonl'):
        newest = max(newest, str(item.get('retrieved') or ''))
        sources = [s for s in item.get('sources') or [] if isinstance(s, dict) and s.get('how') in ITEM_SOURCES]
        if sources:
            items.append({'id': item['id'], 'name': item.get('name', ''), 'new': bool(item.get('new')), 'sources': sources})
    return {'format': FORMAT, 'site': 'foreverchanges.pro', 'retrieved': newest[:10], 'quests': quests, 'items': items}


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__.strip().split('\n\n')[1].strip())
    db = sqlite3.connect(f'file:{argv[1]}?mode=ro&immutable=1', uri=True)
    data = pack(db)
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with gzip.open(argv[2], 'wb', compresslevel=9) as handle:
        handle.write(body)
    print(f"{len(data['quests'])} quests, {len(data['items'])} items with a source, read {data['retrieved']}: {argv[2]}")


if __name__ == '__main__':
    main(sys.argv)
