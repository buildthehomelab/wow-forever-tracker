#!/usr/bin/env python3
"""Trims a copy of foreverchanges.pro down to the pack the tracker reads (docs/SOURCES.md, ForeverChanges).

    python tools/foreverchanges_pack.py foreverchanges.db foreverchanges.fcpack

The input is the SQLite file a crawl of the site leaves (tables `exports` and `responses`, bodies gzipped). It is
several hundred MB of pages; the tracker needs its lists only: who gives and takes each quest and where, which side
a quest is for, what sells or drops each item, and where the NPCs, rares and books of its maps stand. The pack is
those lists, gzipped JSON, about a megabyte: small enough to send through the Imports page. The tracker never asks
the site for anything.

The pack is a zip. `pack.json` is what the tracker reads today: the lists above, a few MB. Beside it, under `site/`,
is every data file of the site in English as the crawl has it (the whole quest and item lists with every field, the
maps, the dungeons, the professions), so that a later version of the tracker can read more without a new crawl or a
new upload. Left out: the HTML pages, which show the same data inside the site's own layout, and the data files in
the six other languages.

The site's base is Classic's data with what Forever changed on top. What its players saw is marked, and only that
is evidence about Forever: a quest with `seen_by_players`, a drop counted in kills. The rest is kept in the pack as
the site gives it and left out by the tracker's rules, not here.
"""
import gzip
import json
import sqlite3
import sys
import zipfile

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


CONTINENTS = {'eastern-kingdoms': 0, 'kalimdor': 1}      # the map folders whose places are world coordinates of a known map
PINS = {'rares.json': 'rare', 'commerce.json': 'commerce', 'books.json': 'book'}


def one(db, path):
    row = db.execute('SELECT body_gzip FROM exports WHERE path = ?', (path,)).fetchone()
    try:
        return json.loads(gzip.decompress(row[0])) if row else None
    except (ValueError, OSError):
        return None


def maps(db):
    """(npcs, pins): the NPCs of the two continents' maps, by entry, and the named pins of every map (rares, commerce
    NPCs, library books). A place is world coordinates; its map is a continent's, or the area a map folder stands for."""
    areas = {str(p.get('slug')): p.get('id') for p in one(db, 'tracker-pages/map/places.json') or [] if isinstance(p, dict)}
    npcs, pins = [], []
    for slug, map_id in CONTINENTS.items():
        for row in (one(db, f'tracker-pages/map/{slug}/npcs.json') or {}).get('npcs') or []:
            if isinstance(row, list) and len(row) >= 7 and isinstance(row[0], int):
                npcs.append({'entry': row[0], 'name': row[1], 'side': row[3], 'map': map_id, 'x': row[4], 'y': row[5], 'kind': row[6],
                             'seen': 'addon' in row[7:]})
    for (path,) in db.execute("SELECT path FROM exports WHERE path LIKE 'tracker-pages/map/%'"):
        parts = path.split('/')
        if len(parts) != 4 or parts[3] not in PINS:
            continue
        where = {'map': CONTINENTS[parts[2]]} if parts[2] in CONTINENTS else {'area': areas.get(parts[2])}
        for pin in (one(db, path) or {}).get('pins') or []:
            if isinstance(pin, dict) and pin.get('name') and isinstance(pin.get('x'), (int, float)) and isinstance(pin.get('y'), (int, float)):
                pins.append(dict(where, kind=PINS[parts[3]], name=pin['name'], x=pin['x'], y=pin['y'], side=pin.get('faction') or ''))
    return npcs, pins


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
    npcs, pins = maps(db)
    return {'format': FORMAT, 'site': 'foreverchanges.pro', 'retrieved': newest[:10], 'quests': quests, 'items': items, 'npcs': npcs, 'pins': pins}


OTHER_LANGUAGES = ('de', 'es', 'fr', 'ru', 'zh-cn', 'zh-tw')


def english(path):
    """A data file of the site that is not one of another language's copies."""
    parts = path.split('/')
    if path.endswith(('.xml', '.html')):
        return False          # the sitemaps and the terms page: no data
    if parts[0] != 'tracker-pages':
        return True
    if any(part in OTHER_LANGUAGES for part in parts[1:-1]):
        return False
    return not (len(parts) > 3 and parts[1] == 'items' and parts[2] == 'u' and parts[3] != 'en')


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__.strip().split('\n\n')[1].strip())
    db = sqlite3.connect(f'file:{argv[1]}?mode=ro&immutable=1', uri=True)
    data = pack(db)
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    files = size = 0
    with zipfile.ZipFile(argv[2], 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('pack.json', body)
        for path, blob in db.execute('SELECT path, body_gzip FROM exports ORDER BY path'):
            if english(path):
                raw = gzip.decompress(blob)
                archive.writestr('site/' + path, raw)
                files += 1
                size += len(raw)
    print(f'{files} data files of the site kept beside it ({size / 1048576:.0f} MB as text)')
    print(f"{len(data['quests'])} quests, {len(data['items'])} items with a source, {len(data['npcs'])} NPCs and {len(data['pins'])} pins of its maps, "
          f"read {data['retrieved']}: {argv[2]}")


if __name__ == '__main__':
    main(sys.argv)
