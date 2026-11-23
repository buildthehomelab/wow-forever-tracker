"""The reference worlds of the spawn audit (ft.spawncount): where other cores spawn each creature.

Three public worlds, each read once into a small pack (data/spawnrefs/<source>.json: per creature and map its spots,
how many are up at one time, and where the spots are). Only the pack is kept; the downloads are thrown away.

    vmangos      VMaNGOS (github.com/vmangos/core, GPL-2.0): the game at patch 1.12. Its rolling "db_latest" release,
                 the SQLite dump (db-sqlite-<commit>.zip). Rows of other patches are left out, and the spawns it
                 keeps disabled (spawn_flags 2).
    azerothcore  AzerothCore (github.com/azerothcore/azerothcore-wotlk, AGPL-3.0): the game at 3.3.5. Its base world
                 files at a pinned commit (data/sql/base/db_world), without the update files after that base.
    trinitycore  TrinityCore 3.3.5 (github.com/TrinityCore/TrinityCore, GPL-2.0): the game at 3.3.5. Its full world
                 release (TDB_full_world_335.*.7z): needs a 7z program to unpack, and is skipped without one.

None of them is WoW Forever. They are witnesses of how many of a creature the game had in their era, nothing more
(docs/SPAWNS.md, "Spawn audit").

A pack: {'format': 3, 'source', 'version', 'made', 'creatures': {entry: {map: [spots, up, [[x, y, z], ...]]}},
'event_only': {entry: [[event, name, yearly], ...]}}. event_only lists the creatures a world spawns only through world
events (every spawn of it is one an event adds), with those events; yearly is true for a holiday that comes back once a
year (Midsummer, Children's Week), false for the rest (Call to Arms, the AQ war effort). The always-up check
(ft.alwaysup) reads it.
"""
import collections
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile

from ft import spawncount
from ft.spawncount import Pools, Row

FORMAT = 3      # 2: a spawn a world event only removes is counted, VMaNGOS' disabled spawns are not; 3: event_only
SOURCES = {'vmangos': 'VMaNGOS', 'azerothcore': 'AzerothCore', 'trinitycore': 'TrinityCore 3.3.5'}
VMANGOS_PATCH = 10      # VMaNGOS' patch numbers: 0 = 1.2 ... 10 = 1.12
VMANGOS_DISABLED = 2    # creature.spawn_flags SPAWN_FLAG_DISABLED: a row VMaNGOS keeps and never spawns
VMANGOS_RELEASE = 'https://api.github.com/repos/vmangos/core/releases/tags/db_latest'
AZEROTHCORE_COMMIT = 'aebaf3e7164cbdb96ab345f71ccc99d53e07c73e'
AZEROTHCORE_FILES = ('creature', 'pool_creature', 'pool_pool', 'pool_template', 'game_event_creature', 'game_event')
AZEROTHCORE_RAW = 'https://raw.githubusercontent.com/azerothcore/azerothcore-wotlk/{commit}/data/sql/base/db_world/{name}.sql'
TRINITYCORE_TAG = 'TDB335.26091'
TRINITYCORE_URL = 'https://github.com/TrinityCore/TrinityCore/releases/download/TDB335.26091/TDB_full_world_335.26091_2026_09_09.7z'
TABLES = ('creature', 'pool_creature', 'pool_creature_template', 'pool_pool', 'pool_template', 'pool_members', 'game_event_creature', 'game_event')
YEAR_MINUTES = 525600   # game_event.occurence of an event that comes back once a year
SEVEN_ZIP = ('7z', '7zz', '7za', '7zr')


class RefError(Exception):
    pass


def values(text):
    """The rows of a VALUES list: numbers as numbers, strings unescaped, NULL as None."""
    from classicdb_pack import values as rows   # tools/classicdb_pack.py: the dump reader the packs share
    return rows(text)


def read_dump(lines, wanted=TABLES):
    """{table: [row as {column: value}]} of a MySQL dump, for the wanted tables. A dump writes an INSERT on one line
    (mysqldump) or one row per line after it (AzerothCore's files): both are read."""
    columns, rows, making, filling = {}, {name: [] for name in wanted}, None, None
    for line in lines:
        made = re.match(r'CREATE TABLE (?:IF NOT EXISTS )?`(\w+)`', line)
        if made:
            making, filling = (made.group(1) if made.group(1) in wanted else None), None
            if making:
                columns[making] = []
            continue
        if making:
            column = re.match(r'\s+`([^`]+)`', line)
            if column:
                columns[making].append(column.group(1))
            elif line.startswith(')'):
                making = None
            continue
        insert = re.match(r'INSERT INTO `(\w+)`(?: \([^)]*\))? VALUES\s*', line)
        if insert:
            filling = insert.group(1) if insert.group(1) in wanted else None
            line = line[insert.end():]
        elif filling and not line.lstrip().startswith('('):
            filling = None
        if filling:
            names = columns.get(filling, [])
            rows[filling].extend(dict(zip(names, row)) for row in values(line))
            if line.rstrip().endswith(';'):
                filling = None
    return rows


def _world(creatures, limits, of_spawn, of_entry, mothers, events):
    """(rows, Pools, events) -> the pack's 'creatures'."""
    pools = Pools(limits, of_spawn, of_entry, mothers)
    counts = spawncount.count(creatures, pools, events)
    where = spawncount.places(creatures, events)
    out = {}
    for (entry, map_id), (spots, up) in counts.items():
        out.setdefault(str(entry), {})[str(map_id)] = [spots, round(up, 3), [[round(c, 1) for c in p] for p in where.get((entry, map_id), ())]]
    return out


def event_only(creatures, added, events):
    """{entry: [[event, name, yearly]]} of the creatures whose every spawn an event adds. creatures: Row; added: {guid:
    {event, ...}} (events that add the spawn); events: {event: (name, yearly)}."""
    every, by_event = collections.Counter(), {}
    for row in creatures:
        for entry in row.entries:
            every[entry] += 1
            if row.guid in added:
                by_event.setdefault(entry, collections.Counter())[None] += 1
                for event in added[row.guid]:
                    by_event[entry][event] += 1
    out = {}
    for entry, counted in by_event.items():
        if counted[None] == every[entry]:
            out[str(entry)] = [[event, *(events.get(event) or ('', False))] for event in sorted(e for e in counted if e is not None)]
    return out


def _yearly(row):
    try:
        return int(row.get('occurence') or 0) == YEAR_MINUTES and int(row.get('holiday') or 0) > 0
    except (TypeError, ValueError):
        return False


def from_tables(tables):
    """(the pack's 'creatures', its 'event_only') from a dump's tables (AzerothCore's, TrinityCore 3.3.5's or MaNGOS'
    column names)."""
    creatures = []
    for r in tables.get('creature') or []:
        entries = [int(r[c]) for c in ('id', 'id1', 'id2', 'id3', 'id4', 'id5') if r.get(c)]
        if entries and r.get('guid') is not None and r.get('position_x') is not None:
            creatures.append(Row(int(r['guid']), tuple(entries), int(r.get('map') or 0), float(r['position_x']), float(r['position_y']), float(r['position_z'])))
    limits = {int(r['entry']): int(r.get('max_limit') or 0) for r in tables.get('pool_template') or []}
    of_spawn = {int(r['guid']): int(r['pool_entry']) for r in tables.get('pool_creature') or []}
    of_entry = {int(r['id']): int(r['pool_entry']) for r in tables.get('pool_creature_template') or []}
    mothers = {int(r['pool_id']): int(r['mother_pool']) for r in tables.get('pool_pool') or []}
    for r in tables.get('pool_members') or []:            # TrinityCore: one table, type 0 creature, 2 pool
        if int(r['type']) == 0:
            of_spawn[int(r['spawnId'])] = int(r['poolSpawnId'])
        elif int(r['type']) == 2:
            mothers[int(r['spawnId'])] = int(r['poolSpawnId'])
    # only what an event adds is left out: a spawn an event removes (a negative event) stands the rest of the time
    added = {}
    for r in tables.get('game_event_creature') or []:
        event = int(r.get('eventEntry') or r.get('event') or 0)
        if event > 0:
            added.setdefault(int(r['guid']), set()).add(event)
    events = set(added)
    if not creatures:
        raise RefError('no creature spawn found: is this a world dump?')
    named = {int(r.get('eventEntry') or r.get('entry') or 0): (str(r.get('description') or ''), _yearly(r)) for r in tables.get('game_event') or []}
    return _world(creatures, limits, of_spawn, of_entry, mothers, events), event_only(creatures, added, named)


def from_vmangos(path):
    """(the pack's 'creatures', its 'event_only') from VMaNGOS' SQLite world (mangos.sqlite), at patch 1.12."""
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        patch = f'patch_min <= {VMANGOS_PATCH} AND patch_max >= {VMANGOS_PATCH}'
        creatures = [Row(guid, tuple(i for i in ids if i), map_id, x, y, z) for guid, *ids, map_id, x, y, z in db.execute(
            f'SELECT guid, id, id2, id3, id4, id5, map, position_x, position_y, position_z FROM creature WHERE {patch} AND (spawn_flags & {VMANGOS_DISABLED}) = 0')]
        limits = dict(db.execute(f'SELECT entry, max_limit FROM pool_template WHERE {patch}'))
        of_spawn = dict(db.execute(f'SELECT guid, pool_entry FROM pool_creature WHERE {patch}'))
        of_entry = dict(db.execute(f'SELECT id, pool_entry FROM pool_creature_template WHERE {patch}'))
        mothers = dict(db.execute('SELECT pool_id, mother_pool FROM pool_pool'))
        added = {}
        for guid, event in db.execute('SELECT guid, event FROM game_event_creature WHERE event > 0'):
            added.setdefault(guid, set()).add(event)
        events = set(added)
        try:
            named = {entry: (description or '', _yearly({'occurence': occurence, 'holiday': holiday}))
                     for entry, description, occurence, holiday in db.execute('SELECT entry, description, occurence, holiday FROM game_event')}
        except sqlite3.Error:   # an older dump without the holiday column, or without the table
            named = {}
    except sqlite3.Error as error:
        raise RefError(f'{os.path.basename(path)} is not VMaNGOS\' world ({error})') from None
    finally:
        db.close()
    if not creatures:
        raise RefError('no creature spawn at patch 1.12: is this VMaNGOS\' mangos.sqlite?')
    return _world(creatures, limits, of_spawn, of_entry, mothers, events), event_only(creatures, added, named)


def pack(source, version, creatures, today=None, only=None):
    """creatures: the 'creatures' part, or (creatures, event_only) as from_tables() and from_vmangos() give them."""
    if isinstance(creatures, tuple):
        creatures, only = creatures
    return {'format': FORMAT, 'source': source, 'version': version,
            'made': (today or datetime.date.today()).isoformat(), 'creatures': creatures, 'event_only': only or {}}


def keyed(made):
    """A pack as ft.spawncount.audit() takes a reference: {'counts': {(entry, map): [spots, up]}, 'places': {...}}."""
    counts, where = {}, {}
    for entry, maps in (made.get('creatures') or {}).items():
        for map_id, cell in maps.items():
            key = (int(entry), int(map_id))
            counts[key] = [int(cell[0]), float(cell[1])]
            where[key] = [tuple(p) for p in (cell[2] if len(cell) > 2 else [])]
    only = {}
    for entry, events in (made.get('event_only') or {}).items():
        try:
            only[int(entry)] = [(int(e[0]), str(e[1] or ''), bool(e[2])) for e in events]
        except (TypeError, ValueError, IndexError):
            continue
    return {'counts': counts, 'places': where, 'event_only': only, 'version': made.get('version') or '', 'made': made.get('made') or ''}


def path_of(folder, source):
    return os.path.join(folder, source + '.json')


def usable(folder, source):
    """Whether the pack kept for `source` reads and is of this format: one that does not is made again."""
    try:
        with open(path_of(folder, source), encoding='utf-8') as handle:
            made = json.load(handle)
    except (OSError, ValueError):
        return False
    return isinstance(made, dict) and made.get('format') == FORMAT and isinstance(made.get('creatures'), dict)


def load(folder):
    """{source: keyed pack} of the packs kept in `folder` (those that read)."""
    out = {}
    for source in SOURCES:
        try:
            with open(path_of(folder, source), encoding='utf-8') as handle:
                made = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(made, dict) and made.get('format') == FORMAT and isinstance(made.get('creatures'), dict):
            out[source] = keyed(made)
    return out


def save(folder, made):
    os.makedirs(folder, exist_ok=True)
    target = path_of(folder, made['source'])
    with open(target + '.part', 'w', encoding='utf-8') as handle:
        json.dump(made, handle, separators=(',', ':'))
    os.replace(target + '.part', target)
    return target


def _lines(path):
    with open(path, encoding='utf-8', errors='replace') as handle:
        yield from handle


def make(source, paths, version=''):
    """A pack from files already on disk. vmangos: mangos.sqlite, or the release zip that holds it; azerothcore: its
    base world files (creature.sql, pool_*.sql, game_event_creature.sql), or a folder of them; trinitycore: the full
    world dump (.sql)."""
    if source not in SOURCES:
        raise RefError(f'unknown source {source!r}: one of {", ".join(SOURCES)}')
    if source == 'vmangos':
        path = paths[0]
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as scratch:
                name = next((n for n in archive.namelist() if n.endswith('mangos.sqlite')), None)
                if not name:
                    raise RefError(f'{os.path.basename(path)}: no mangos.sqlite inside: is this VMaNGOS\' db-sqlite-<commit>.zip?')
                target = os.path.join(scratch, 'mangos.sqlite')
                with archive.open(name) as inside, open(target, 'wb') as out:
                    shutil.copyfileobj(inside, out)
                return pack(source, version, from_vmangos(target))
        return pack(source, version, from_vmangos(path))
    files = []
    for path in paths:
        if os.path.isdir(path):
            files += [os.path.join(path, name + '.sql') for name in TABLES if os.path.isfile(os.path.join(path, name + '.sql'))]
        else:
            files.append(path)
    tables = {name: [] for name in TABLES}
    for path in files:
        for name, rows in read_dump(_lines(path)).items():
            tables[name].extend(rows)
    return pack(source, version, from_tables(tables))


def _download(url, target, fetch):
    body = fetch(url)
    with open(target + '.part', 'wb') as handle:
        handle.write(body)
    os.replace(target + '.part', target)


def fetch(source, folder, http, log=lambda message: None, seven_zip=None):
    """Downloads one reference world, makes its pack in `folder` and returns the pack's path. http: url -> bytes.
    seven_zip: the 7z program to unpack TrinityCore's archive with (default: the first of SEVEN_ZIP installed; '' for
    none). Raises RefError when the source cannot be had (no 7z program, a download that fails)."""
    with tempfile.TemporaryDirectory() as scratch:
        try:
            if source == 'vmangos':
                release = json.loads(http(VMANGOS_RELEASE))
                asset = next((a for a in release.get('assets') or [] if re.fullmatch(r'db-sqlite-[0-9a-f]+\.zip', a.get('name') or '')), None)
                if not asset:
                    raise RefError('VMaNGOS\' db_latest release holds no db-sqlite-<commit>.zip')
                target = os.path.join(scratch, 'vmangos.zip')
                _download(asset['browser_download_url'], target, http)
                made = make(source, [target], re.search(r'db-sqlite-([0-9a-f]+)', asset['name']).group(1))
            elif source == 'azerothcore':
                for name in AZEROTHCORE_FILES:
                    _download(AZEROTHCORE_RAW.format(commit=AZEROTHCORE_COMMIT, name=name), os.path.join(scratch, name + '.sql'), http)
                made = make(source, [scratch], AZEROTHCORE_COMMIT)
            elif source == 'trinitycore':
                program = seven_zip if seven_zip is not None else next((shutil.which(name) for name in SEVEN_ZIP if shutil.which(name)), None)
                if not program:
                    raise RefError('TrinityCore\'s world is a .7z archive and no 7z program is installed (7z, 7zz, 7za): skipped')
                target = os.path.join(scratch, 'tdb.7z')
                _download(TRINITYCORE_URL, target, http)
                done = subprocess.run([program, 'x', '-y', '-o' + scratch, target], capture_output=True, text=True)
                dumps = [os.path.join(scratch, n) for n in os.listdir(scratch) if n.endswith('.sql')]
                if done.returncode or not dumps:
                    raise RefError(f'TrinityCore\'s archive did not unpack ({(done.stderr or done.stdout).strip()[-200:]})')
                made = make(source, dumps[:1], TRINITYCORE_TAG)
            else:
                raise RefError(f'unknown source {source!r}')
        except (OSError, ValueError, KeyError) as error:
            raise RefError(f'{SOURCES.get(source, source)} could not be read ({error})') from None
    spots = sum(cell[0] for maps in made['creatures'].values() for cell in maps.values())
    log(f"spawn audit: {SOURCES[source]} {made['version'][:12]}: {spots} spots of {len(made['creatures'])} creatures")
    return save(folder, made)


def summary(refs):
    """{source: (creatures, spots)} of loaded packs, for a log line."""
    out = collections.OrderedDict()
    for source, ref in refs.items():
        out[source] = (len({entry for entry, _map in ref['counts']}), sum(n[0] for n in ref['counts'].values()))
    return out
