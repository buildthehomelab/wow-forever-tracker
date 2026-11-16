"""Makes a pack of what VMaNGOS' world database says about who teaches a spell, in the Classic database pack's format.

    python tools/vmangos_pack.py mangos.sql out.cdbpack           (the dump inside VMaNGOS' db-<commit>.zip)
    python tools/vmangos_pack.py db-13a411e.zip out.cdbpack       (or the release zip itself: mysql-dump/mangos.sql)

The source is the world database of VMaNGOS (github.com/vmangos/core, GPL-2.0, the "db_latest" release): the content
of the 1.12 game, kept with every row's patch so that each patch of 1.2 to 1.12 can be served. Only the dump is read,
as text; nothing is run and no database is needed.

VMaNGOS' tables are MaNGOS' with other column names and a version on most rows. This keeps patch 1.12 (PATCH) only:
  - a template of several patches (creature, object, item, quest): the newest version up to 1.12;
  - a row with patch_min / patch_max (loot, spawns, events): only if 1.12 is in its range;
  - a trainer line with build_min / build_max, a spell with build: the same, by the client build of 1.12.1 (BUILD).
A spawn that picks among several creatures (id, id2..id5) keeps that list the way cmangos keeps one (*_spawn_entry).
The rows are then renamed to cmangos' columns and made into a pack by tools/classicdb_pack.py pack(): the same format,
read by the same code (ft.classic, app/sources.php), with VMaNGOS named as its source.
"""
import datetime
import io
import json
import os
import re
import sys
import zipfile
import gzip

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import classicdb_pack  # noqa: E402
from classicdb_pack import values, whole  # noqa: E402

PATCH = 10      # VMaNGOS' patch numbers: 0 = 1.2 ... 10 = 1.12
BUILD = 5875    # the client build of 1.12.1

# VMaNGOS table -> the cmangos table classicdb_pack.pack() reads
TABLES = {name: name for name in classicdb_pack.WANTED}
TABLES['gossip_scripts'] = 'dbscripts_on_gossip'
TABLES['migrations'] = 'migrations'
# VMaNGOS column -> cmangos column, per table (the others keep their name)
RENAME = {
    'creature_template': {'entry': 'Entry', 'name': 'Name', 'gossip_menu_id': 'GossipMenuId', 'trainer_id': 'TrainerTemplateId',
                          'loot_id': 'LootId', 'vendor_id': 'VendorTemplateId'},
    'spell_template': {'effect1': 'Effect1', 'effect2': 'Effect2', 'effect3': 'Effect3',
                       'effectItemType1': 'EffectItemType1', 'effectItemType2': 'EffectItemType2', 'effectItemType3': 'EffectItemType3'},
    'creature': {'wander_distance': 'spawndist', 'movement_type': 'MovementType'},
}
# A template kept in several patches: its key columns, the newest patch up to PATCH wins
PATCHED = {'creature_template': ('entry',), 'gameobject_template': ('entry',), 'item_template': ('entry',), 'quest_template': ('entry',)}


def read(lines):
    """{VMaNGOS table: [row as {column: value}]} for the tables the pack is made from."""
    columns, rows, current = {}, {name: [] for name in TABLES}, None
    for line in lines:
        insert = re.match(r'INSERT INTO `(\w+)` VALUES ', line)
        if insert:
            if insert.group(1) in TABLES:
                names = columns.get(insert.group(1), [])
                rows[insert.group(1)].extend(dict(zip(names, row)) for row in values(line[insert.end():]))
            continue
        made = re.match(r'CREATE TABLE `(\w+)`', line)
        if made:
            current = made.group(1) if made.group(1) in TABLES else None
            if current:
                columns[current] = []
            continue
        if current:
            column = re.match(r'\s+`([^`]+)`', line)
            if column:
                columns[current].append(column.group(1))
            elif line.startswith(')'):
                current = None
    return rows


def in_range(row, low, high, at):
    """A row whose [low, high] range holds `at`; a row without the columns always."""
    lo, hi = row.get(low), row.get(high)
    return (lo is None or lo <= at) and (hi is None or at <= hi)


def newest(rows, keys, column, at):
    """Of the rows sharing `keys`, the one with the highest `column` up to `at` (rows above it are left out)."""
    best = {}
    for row in rows:
        version = row.get(column) or 0
        if version > at:
            continue
        key = tuple(row.get(k) for k in keys)
        if key not in best or version > (best[key].get(column) or 0):
            best[key] = row
    return list(best.values())


def to_cmangos(tables):
    """VMaNGOS' rows of patch 1.12, as the cmangos tables classicdb_pack.pack() reads."""
    out = {name: [] for name in classicdb_pack.WANTED}
    for name, rows in tables.items():
        if name in PATCHED:
            rows = newest(rows, PATCHED[name], 'patch', PATCH)
        elif name == 'spell_template':
            rows = newest(rows, ('entry',), 'build', BUILD)
        rows = [r for r in rows if in_range(r, 'patch_min', 'patch_max', PATCH) and in_range(r, 'build_min', 'build_max', BUILD)]
        rename = RENAME.get(name, {})
        if rename:
            rows = [{rename.get(k, k): v for k, v in r.items()} for r in rows]
        if name in TABLES and TABLES[name] in out:
            out[TABLES[name]].extend(rows)
    # a spawn that picks among several creatures: id 0 and the list, as cmangos keeps it
    for row in out['creature']:
        choices = [whole(row.get(c)) for c in ('id', 'id2', 'id3', 'id4', 'id5')]
        choices = sorted({c for c in choices if c})
        if len(choices) > 1:
            out['creature_spawn_entry'].extend({'guid': row.get('guid'), 'entry': c} for c in choices)
            row['id'] = 0
    newest_migration = max((str(r.get('id') or '') for r in tables.get('migrations') or ()), default='')
    out['db_version'] = [{'version': 'VMaNGOS world database' + (f', migration {newest_migration}' if newest_migration else '') + ', patch 1.12'}]
    return out


def open_dump(path):
    """The dump as lines of text: a .sql file, a .sql.gz, or VMaNGOS' release zip (its mysql-dump/mangos.sql)."""
    if path.endswith('.zip'):
        archive = zipfile.ZipFile(path)
        name = next((n for n in archive.namelist() if n.endswith('/mangos.sql') or n == 'mangos.sql'), None)
        if not name:
            sys.exit(f'{path}: no mangos.sql inside: is this VMaNGOS\' db-<commit>.zip?')
        return io.TextIOWrapper(archive.open(name), encoding='utf-8', errors='replace')
    opener = gzip.open if path.endswith('.gz') else open
    return opener(path, 'rt', encoding='utf-8', errors='replace')


def pack(tables, today=None):
    made = classicdb_pack.pack(to_cmangos(tables), today)
    made.update(source='VMaNGOS', licence='GPL-2.0')
    return made


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    with open_dump(argv[1]) as handle:
        made = pack(read(handle), datetime.date.today().isoformat())
    if not made['trainers'] and not made['quests']:
        sys.exit('no trainer and no quest found: is this the world dump of VMaNGOS (mangos.sql)?')
    with gzip.open(argv[2], 'wt', encoding='utf-8') as out:
        json.dump(made, out, ensure_ascii=False, separators=(',', ':'))
    print(f"{argv[2]}: {len(made['drops'])} drops and {len(made['sells'])} vendor lines of items that teach, "
          f"{sum(len(e['creatures']) + len(e['objects']) for e in made['holidays'].values())} spawns of {len(made['holidays'])} events "
          f"({len(made['world_drops'])} world drops left out; {len(made['never_given'])} given out nowhere), "
          f"{len(made['trainers'])} trainer lines, {len(made['quests'])} quests with a spell, {len(made['talk'])} conversation lines that cast a spell"
          f" ({made['talk_dropped']} left out: a condition not carried over) ({made['version']})")


if __name__ == '__main__':
    main(sys.argv)
