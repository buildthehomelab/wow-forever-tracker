"""Checkout: the client's data as it stood at any step of the timeline, as your server's hotfixes database
(docs/CHECKOUT.md).

A step is a build (`70450`) or one of a build's hotfix updates (`70938+1`), as the timeline lists them; `latest` is the
newest. The tables of that step, with the hotfixes that stood over it, are compared with the DB2 files your server
loads, and every record that differs becomes a row of the server's hotfix table and a `hotfix_data` line: the server
loads it over its own files, and sends it to the game clients that connect. A record your server's files have and the
step does not is removed the same way (status 2). Nothing is written to a database: the result is an SQL file, and
loading it replaces the tables it names in the hotfixes database it is loaded into (a test realm's), with a JSON
manifest beside it that says what it holds and what it left out.

What a checkout can and cannot say:
  - only the tables the tracker reads (tools/schema/db2-files.json) whose layout is the one your server's hotfix
    table has: another layout cannot be sent to a client of your server's build, and is left out, with the reason;
  - Blizzard's hotfixes of a build are known only from the day the tracker kept them (ft.hotfixes.history). Before
    that, the records that exist by hotfix alone (thousands of items) come from the earliest cache kept after it, as
    the changelog counts them (known since the first build): `carry` False leaves them out;
  - a build stored for the changelog alone holds 25 tables: the others are read from Blizzard's CDN first
    (ft.client.complete) when `fetch` says so.
"""
import datetime
import json
import math
import os
import zlib

from . import content, db2, hotfixes, sqlio
from .config import CONFIG, DATA
from .forge import snake

OUT = os.path.join(DATA, 'checkout')
BATCH = 500
BITS = {'tinyint': 8, 'smallint': 16, 'mediumint': 24, 'int': 32, 'bigint': 64}


def tracked():
    """The tables the tracker reads from the client's files (tools/schema/db2-files.json)."""
    from .client import files
    return [name for name in content.TABLES if name in files()]


def steps():
    """Every step of the timeline that can be checked out, oldest first: {'id', 'build', 'hotfix', 'version', 'date',
    'dir', 'cache' (the kept hotfix cache that stands over it, None: the newest or none), 'partial'}."""
    out = []
    for b in content.builds():
        if b.get('baseline'):
            continue   # the original game's tables are another client's, in another layout: no hotfix of this server's
        kept = hotfixes.history(b['dir'])
        # partial: a table the tracker reads is not stored (a build stored for the changelog, not completed since)
        partial = any(not os.path.isfile(os.path.join(b['dir'], 'enUS', name + '.db2')) for name in tracked())
        base = {'build': b['build'], 'version': b['version'], 'dir': b['dir'], 'partial': partial}
        out.append({**base, 'id': str(b['build']), 'hotfix': 0, 'date': b['date'], 'cache': kept[0] if len(kept) > 1 else None,
                    'cache_day': kept[0]['read'] if kept else None})
        for number in range(1, len(kept)):
            out.append({**base, 'id': f"{b['build']}+{number}", 'hotfix': number, 'date': kept[number]['read'],
                        'cache': kept[number] if number < len(kept) - 1 else None, 'cache_day': kept[number]['read']})
    return out


def find(spec, found=None):
    """The step a name means: 'latest', a build ('70450', '1.60.1.70450'), or a hotfix update ('70938+1')."""
    found = steps() if found is None else found
    if not found:
        raise ValueError('no build is stored')
    spec = str(spec).strip()
    if spec in ('latest', 'newest', ''):
        return found[-1]
    build, plus, number = spec.partition('+')
    build = build.rsplit('.', 1)[-1]
    if plus and not number.isdigit():
        raise ValueError(f'no step {spec}: a hotfix update is a number after the build (70938+1)')
    for step in found:
        if str(step['build']) == build and step['hotfix'] == (int(number) if plus else 0):
            return step
    raise ValueError(f'no step {spec}: `tracker.py checkout list` names them')


def server_columns():
    """{hotfix table: [(column, integer bits or 0, unsigned)]} of the hotfixes database [database] hotfixes names."""
    out = {}
    for row in sqlio.query("SELECT TABLE_NAME t, COLUMN_NAME c, DATA_TYPE d, COLUMN_TYPE ct FROM information_schema.columns "
                           "WHERE table_schema = DATABASE() ORDER BY TABLE_NAME, ORDINAL_POSITION", 'hotfixes'):
        out.setdefault(row['t'], []).append((row['c'], BITS.get(row['d'], 0), 'unsigned' in row['ct']))
    return out


def fit(value, bits, unsigned):
    """A value as the column stores it: the same bits in its integer type (the core reads DB2 values as raw bits), a
    float that is a number."""
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if bits and isinstance(value, int):
        value &= (1 << bits) - 1
        return value if unsigned or value < 1 << (bits - 1) else value - (1 << bits)
    return value


_sources = {}


def _carry_source(step):
    """(the later build's step, {table hash: {id: Record}} of its earliest kept cache) for a step whose build has no
    cache of its own; None when there is none to carry from."""
    if step['dir'] not in _sources:
        found = None
        if not hotfixes.history(step['dir']):
            later = [s for s in steps() if s['build'] > step['build'] and s['hotfix'] == 0 and hotfixes.history(s['dir'])]
            if later:
                entry = hotfixes.history(later[0]['dir'])[0]
                try:
                    _build, records = hotfixes.parse(hotfixes._read(os.path.join(later[0]['dir'], hotfixes.HISTORY, entry['file'])))
                    found = (later[0], hotfixes.newest(records))
                except (OSError, hotfixes.CacheError, EOFError, ValueError):
                    found = None
        _sources[step['dir']] = found
    return _sources[step['dir']]


def carried(step, name, have, meta):
    """{id: row} of the records that exist by hotfix alone in the earliest hotfix cache kept after a step's build, for
    a step whose build has no cache of its own: the changelog counts them as known since the first build. have: the
    ids the step's table already holds; meta: its layout (a record of another layout is left out)."""
    found = _carry_source(step)
    if found is None:
        return {}
    first, records = found
    path = os.path.join(first['dir'], 'enUS', name + '.db2')
    if not os.path.isfile(path):
        return {}
    own = db2.Table(path, name)
    in_table = {row['ID'] for row in own}
    names = [column for column, _field in own.columns]
    out = {}
    for record_id, record in records.get(own.table_hash, {}).items():
        if record.status != hotfixes.VALID or record_id in have or record_id in in_table:
            continue
        row = hotfixes.decode(record.data, meta, record_id, names)
        if row is not None:
            out[record_id] = row
    return out


def target(step, name, carry=True):
    """(the table as read, {id: row}, how many of them were carried) of a table at a step, with the hotfixes that stood
    over it; (None, {}, 0) when the step has no such table."""
    path = os.path.join(step['dir'], 'enUS', name + '.db2')
    if not os.path.isfile(path):
        return None, {}, 0
    source = db2.Table(path, name)   # under the cache plan() let stand over the step
    rows = {row['ID']: row for row in hotfixes.overlay(step['dir'], source, list(source))}
    more = carried(step, name, set(rows), source.meta) if carry else {}
    rows.update(more)
    return source, rows, len(more)


def server_rows(name):
    """{id: row} of the DB2 file your server loads, and its table; ({}, None) when it has none."""
    from .server import server_dbc
    path = os.path.join(server_dbc(), name + '.db2')
    if not os.path.isfile(path):
        return {}, None
    table = db2.Table(path, name)
    return {row['ID']: row for row in table}, table


VERIFIED = object()   # the VerifiedBuild column's place in a row: written as the server's build


def table_hash_of(name, step, their_table):
    """The hash a table's hotfix_data lines carry: from your server's file, the step's, or the newest stored build's."""
    if their_table is not None:
        return their_table.table_hash
    for folder in [step['dir']] + [b['dir'] for b in reversed(content.builds()) if not b.get('baseline')]:
        path = os.path.join(folder, 'enUS', name + '.db2')
        if os.path.isfile(path):
            return db2.Table(path, name).table_hash
    return None


def plan(step, carry=True, columns=None, server=None, names=None, log=lambda text: None):
    """What a checkout of a step writes: {'tables': {table: {'hash', 'target', 'columns', 'rows' (lists, in the columns'
    order, VERIFIED where VerifiedBuild goes), 'removed' (ids), 'records'}}, 'skipped': {table: why}, 'cleared': {table:
    {'target', 'hash'}} (the left-out tables your server keeps a hotfix table for: the file empties them too, so that
    no earlier checkout's rows stay behind), 'carried': records that exist by hotfix alone, carried to the step}.
    columns: server_columns() (tests); server: a table's name -> (its rows by id, its table) as your server loads it
    (tests); names: the tables (all the tracker reads by default)."""
    columns = server_columns() if columns is None else columns
    server = server or server_rows
    out = {'tables': {}, 'skipped': {}, 'cleared': {}, 'carried': 0}
    saved, pinned = db2.FLOAT_DIGITS, hotfixes._pinned.get(step['dir'])
    db2.FLOAT_DIGITS = None   # the exact values: a checkout writes them
    hotfixes.pin(step['dir'], step['cache'])   # once for every table: a pin reads the whole cache again

    def leave(name, why, their_table=None, source=None):
        out['skipped'][name] = why
        hot = snake(name)
        found = table_hash_of(name, step, their_table) if source is None else (their_table or source).table_hash
        if hot in columns and found is not None:
            # emptied with its hotfix_data lines; a table whose hash nobody knows is left as it is (its lines could not go)
            out['cleared'][name] = {'target': hot, 'hash': found}
    try:
        for name in names or content.TABLES:
            hot = snake(name)
            if hot not in columns:
                out['skipped'][name] = 'your server keeps no hotfix table for it'
                continue
            source, rows, brought = target(step, name, carry)
            if source is None:
                leave(name, 'not stored for this build (`--fetch` reads it from the CDN)' if step['partial'] else 'not in this build')
                continue
            wanted = [(column, bits, unsigned) for column, bits, unsigned in columns[hot] if column != 'VerifiedBuild']
            have = {column for column, _field in source.columns}
            missing = [column for column, _bits, _unsigned in wanted if column not in have]
            extra = sorted(have - {column for column, _bits, _unsigned in wanted})
            if missing or extra:
                leave(name, 'the tracker reads it with other columns than your server\'s hotfix table: '
                      + ', '.join(([f'{len(missing)} column(s) it lacks ({", ".join(missing[:3])})'] if missing else [])
                                  + ([f'{len(extra)} more ({", ".join(extra[:3])})'] if extra else [])), source=source)
                continue
            theirs, their_table = server(name)
            if their_table is not None and their_table.table_hash != source.table_hash:
                leave(name, f'another table than your server\'s ({source.table_hash:08X}, the server has {their_table.table_hash:08X})', their_table, source)
                continue
            if their_table is not None and their_table.layout_hash != source.layout_hash:
                # the same columns by name, another layout: a record of this build cannot be sent to a client of the server's
                leave(name, f'the layout of this build is not your server\'s ({source.layout_hash:08X}, the server has {their_table.layout_hash:08X})', their_table, source)
                continue
            ordered = [column for column, _bits, _unsigned in columns[hot]]
            shaped = lambda row: [VERIFIED if column == 'VerifiedBuild' else fit(row.get(column), bits, unsigned) for column, bits, unsigned in columns[hot]]
            changed = []
            for record_id in sorted(rows):
                mine = shaped(rows[record_id])
                if record_id in theirs and mine == shaped(theirs[record_id]):
                    continue
                changed.append(mine)
            removed = sorted(set(theirs) - set(rows))
            hidden = getattr(source, 'hidden_records', 0) > getattr(their_table, 'hidden_records', 0)
            if hidden and removed:
                # the step's file holds sections nobody can decrypt yet: what your server's file has there is not gone
                log(f'{name}: {len(removed)} record(s) your server has are not removed: {source.hidden_records} records of this build are still encrypted')
                removed = []
            out['carried'] += brought
            out['tables'][name] = {'hash': source.table_hash, 'target': hot, 'columns': ordered, 'rows': changed, 'removed': removed,
                                   'records': len(rows)}
            log(f'{name}: {len(rows)} records, {len(changed)} differ from your server\'s file, {len(removed)} it has and the step does not')
    finally:
        db2.FLOAT_DIGITS = saved
        hotfixes.pin(step['dir'], {'file': os.path.basename(pinned)} if pinned else None)
    return out


def unique(table_hash, record_id, step_id):
    return zlib.crc32(f'{table_hash}:{record_id}:{step_id}'.encode()) & 0x7FFFFFFF or 1


def write(step, made, path, server_build, now=None):
    """Writes the SQL file of a plan() and its manifest (path + '.json'); returns the manifest."""
    e = sqlio.escape
    now = now or datetime.datetime.now().isoformat(timespec='seconds')
    tables, cleared = made['tables'], made.get('cleared') or {}
    hashes = sorted({info['hash'] for info in tables.values()} | {info['hash'] for info in cleared.values()})
    label = f"build {step['version']}" + (f", hotfixes of {step['date']}" if step['hotfix'] else (f", hotfixes of {step['cache_day']}" if step.get('cache_day') else ''))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    scratch = f'{path}.{os.getpid()}.tmp'   # two runs of the same step never write into one file
    with open(scratch, 'w', encoding='utf-8') as out:
        out.write(f"-- ForeverTracker checkout: the client's data at {label} (step {step['id']})\n"
                  f"-- made {now} for a server that loads build {server_build}'s DB2 files\n"
                  f"-- Loading it REPLACES these tables of the hotfixes database it is loaded into, and their hotfix_data lines:\n"
                  + ''.join(f"--   {info['target']}: {len(info['rows'])} record(s) over your server's file, {len(info['removed'])} removed\n" for name, info in sorted(tables.items()))
                  + (f"-- and EMPTIES these, which it leaves out (your server's own files stand for them):\n"
                     + ''.join(f"--   {info['target']}: {made['skipped'].get(name, '')}\n" for name, info in sorted(cleared.items())) if cleared else '')
                  + "-- Meant for a test realm. Restart its worldserver after loading it, and clear the game client's Cache folder\n"
                  "-- when it saw another checkout before: a record that is now what the server's file says is not sent again.\n"
                  "SET NAMES utf8mb4;\nSTART TRANSACTION;\n"
                  # one push for the whole checkout, after every push the database holds (also the lines it is about to remove)
                  "SET @push := (SELECT COALESCE(MAX(`Id`), 0) + 1 FROM `hotfix_data`);\n")
        for name, info in sorted({**cleared, **tables}.items()):
            out.write(f"DELETE FROM `{info['target']}`;\n")
        if hashes:
            out.write(f"DELETE FROM `hotfix_data` WHERE `TableHash` IN ({','.join(str(h) for h in hashes)});\n")
        for name, info in sorted(tables.items()):
            head = f"INSERT INTO `{info['target']}` (" + ','.join(f'`{c}`' for c in info['columns']) + ') VALUES\n'
            for at in range(0, len(info['rows']), BATCH):
                chunk = info['rows'][at:at + BATCH]
                out.write(head + ',\n'.join('(' + ','.join(str(server_build) if v is VERIFIED else e(v) for v in row) + ')' for row in chunk) + ';\n')
        lines = []
        for name, info in sorted(tables.items()):
            at = info['columns'].index('ID')
            lines += [(info['hash'], row[at], 1) for row in info['rows']]
            lines += [(info['hash'], record_id, 2) for record_id in info['removed']]
        for at in range(0, len(lines), BATCH):
            chunk = lines[at:at + BATCH]
            out.write('INSERT INTO `hotfix_data` (`Id`,`UniqueId`,`TableHash`,`RecordId`,`Status`,`VerifiedBuild`) VALUES\n'
                      + ',\n'.join(f'(@push,{unique(h, r, step["id"])},{h},{r},{status},{server_build})' for h, r, status in chunk) + ';\n')
        out.write('COMMIT;\n')
    manifest = {'step': step['id'], 'build': step['build'], 'version': step['version'], 'hotfix': step['hotfix'], 'date': step['date'],
                'hotfixes_of': step.get('cache_day'), 'made': now, 'server_build': server_build, 'file': os.path.basename(path),
                'tables': {name: {'hotfix_table': info['target'], 'records': info['records'], 'rows': len(info['rows']), 'removed': len(info['removed'])}
                           for name, info in sorted(tables.items())},
                'skipped': made['skipped'], 'emptied': sorted(info['target'] for info in cleared.values()),
                'carry': made.get('carry', True), 'carried': made.get('carried', 0)}
    # the manifest after the file, each whole: the website offers a file only beside a manifest of its step
    with open(f'{path}.json.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)
    try:
        os.remove(f'{path}.json')   # while the new file replaces the old one, no manifest says the old one's numbers
    except OSError:
        pass
    os.replace(scratch, path)
    os.replace(f'{path}.json.{os.getpid()}.tmp', f'{path}.json')
    return manifest
