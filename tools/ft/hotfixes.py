"""Blizzard's hotfixes over the official list (docs/CLIENT.md).

Between two client builds Blizzard changes the game's tables by hotfix: a record is added, replaced or removed, and
every client gets it at login and keeps it in its hotfix cache (DBCache.bin). The cache of live WoW: Forever is
mirrored publicly, refreshed daily ([client] hotfix_cache). Without it the official list is the build as it shipped,
not the game as it is played today.

Which word is the last one (the later one always wins):
  - a hotfix is newer than the build it was written for: it stands over that build's table;
  - of two hotfixes of one row, the later push stands;
  - a newer build is newer than an older build's hotfixes: where the new build's table has the row, the table stands.
    An older hotfix is kept only for a row the new table does not have at all (thousands of items exist by hotfix
    alone), and only until the new build's own cache arrives, which then says everything.

A cache record is one row of one table, written the way the client stores it: the table's fields one after the other
at their full size, text in place and zero-terminated, the id left out when the table keeps its ids apart, and the
parent id (a relationship column that is not in the file) last. That is the layout of tools/schema/db2-schema.json,
so a record is read with the same schema as the table itself. A record that does not end exactly where its bytes end
was written for another layout: it is left out and counted, never half believed.

Layout of the cache (XFTH version 9, https://wowdev.wiki/DBCache.bin), little-endian:
    header  'XFTH', u32 version, u32 build, 32 bytes hash                                         44 bytes
    entry   'XFTH', i32 region, i32 push id, u32 unique id, u32 table hash, i32 record id, i32 size,
            u8 status, 3 bytes padding, then <size> bytes: the record                             32 bytes + record
Status: 1 valid, 2 removed, 3 invalid, 4 not public (the record exists; its content is withheld).
"""
import hashlib
import json
import os
import struct
import urllib.error
import urllib.request
from collections import namedtuple

MAGIC = b'XFTH'
VERSION = 9
HEADER_SIZE = 44
ENTRY = struct.Struct('<4siiIIiiB3x')

VALID, REMOVED, INVALID, NOT_PUBLIC = 1, 2, 3, 4
SIZES = {'byte': 1, 'short': 2, 'int': 4, 'float': 4, 'long': 8}

Record = namedtuple('Record', 'push table record status data')


class CacheError(ValueError):
    pass


def parse(blob):
    """(build, [Record]) in file order. CacheError on anything that is not a whole XFTH v9 cache."""
    if len(blob) < HEADER_SIZE or blob[:4] != MAGIC:
        raise CacheError('not a hotfix cache (no XFTH header)')
    version, build = struct.unpack_from('<II', blob, 4)
    if version != VERSION:
        raise CacheError(f'XFTH version {version}, this reader knows {VERSION}')
    records, at = [], HEADER_SIZE
    while at < len(blob):
        if at + ENTRY.size > len(blob):
            raise CacheError(f'entry header cut off at byte {at}')
        magic, _region, push, _unique, table, record, size, status = ENTRY.unpack_from(blob, at)
        if magic != MAGIC:
            raise CacheError(f'entry at byte {at} has no XFTH mark')
        start = at + ENTRY.size
        if size < 0 or start + size > len(blob):
            raise CacheError(f'entry at byte {at} says {size} bytes, past the end of the file')
        records.append(Record(push, table, record, status, blob[start:start + size]))
        at = start + size
    return build, records


def newest(records):
    """{table hash: {record id: Record}}: the last word on each record (the highest push; a push of -1, sent with
    every connection, counts as the oldest; of two with the same push, the later in the file)."""
    out = {}
    for r in records:
        rows = out.setdefault(r.table, {})
        old = rows.get(r.record)
        if old is None or r.push >= old.push:
            rows[r.record] = r
    return out


def layout(meta, names=None):
    """The fields of a cache record of a table, in order: [(column name, type, signed)], and whether the id is among
    them. The same columns as ft.db2.Table gives a row, without the id when the table keeps its ids apart."""
    fields = meta['fields'][:meta['fileFieldCount']]
    names = list(names or meta.get('names') or [])
    flat = []
    for field in fields:
        for _element in range(field['array']):
            flat.append((field['type'], field['signed']))
    if meta['fieldCount'] > meta['fileFieldCount']:
        flat.append(('int', False))   # the parent id, last
    own_id = meta['index'] == -1      # the id is not a field: the cache entry carries it
    wanted = len(flat) + (1 if own_id else 0)
    if len(names) != wanted:
        names = (['ID'] if own_id else []) + [f'f{i}' for i in range(len(flat))]
    columns = names[1:] if own_id else names
    return [(name, kind, signed) for name, (kind, signed) in zip(columns, flat)], (names[0] if own_id else None)


def decode(data, meta, record_id, names=None):
    """One cache record as a row {column: value}, like a row of ft.db2.Table; None when the bytes do not fit the
    table's layout exactly (another layout, or a format this reader does not know)."""
    columns, id_name = layout(meta, names)
    row, at = {}, 0
    if id_name:
        row[id_name] = record_id
    for name, kind, signed in columns:
        if kind.startswith('string'):
            end = data.find(b'\0', at)
            if end < 0:
                return None
            row[name] = data[at:end].decode('utf-8', 'replace')
            at = end + 1
            continue
        size = SIZES[kind]
        if at + size > len(data):
            return None
        if kind == 'float':
            row[name] = round(struct.unpack_from('<f', data, at)[0], 4)
        else:
            # as ft.db2 reads the same field from the table (a 64-bit value is never taken as negative there)
            row[name] = int.from_bytes(data[at:at + size], 'little', signed=bool(signed) and size < 8)
        at += size
    return row if at == len(data) else None


# ------------------------------------------------------------------ over a snapshot
FILE = 'hotfixes.bin'                 # in data/builds/<build>/: the cache as it was downloaded
MIRROR = 'https://storage.googleapis.com/raidbots-static/wow/forever/enUS/DBCache.bin'
STATS = {}                            # build folder -> {table: [added, changed, removed, misfit]} of the last overlay
ORIGIN = {}                           # build folder -> the earlier build its hotfixes were carried over from, or None
_loaded = {}


def _own(folder):
    """{table hash: {record id: Record}} of the cache stored in this snapshot's folder, None when there is none, when
    it cannot be read, or when it was written for another build than the folder's."""
    path = os.path.join(folder, FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as handle:
            build, records = parse(handle.read())
    except (OSError, CacheError):
        return None
    return newest(records) if str(build) == os.path.basename(os.path.normpath(folder)) else None


def cached(folder):
    """(records, from build): the hotfixes that stand over a snapshot, as {table hash: {record id: Record}}.

    The snapshot's own cache: from build = None, every record counts. Without one, the cache of the newest earlier
    build that has one: from build = that build, and only its rows the new table lacks count (see the top of this
    file). ({}, None) when there is neither."""
    if folder not in _loaded:
        found = _own(folder)
        origin = None
        if found is None:
            found = {}
            parent, name = os.path.split(os.path.normpath(folder))
            earlier = sorted((int(n) for n in os.listdir(parent) if n.isdigit() and name.isdigit() and int(n) < int(name)), reverse=True) if os.path.isdir(parent) else []
            for build in earlier:
                older = _own(os.path.join(parent, str(build)))
                if older is not None:
                    found, origin = older, build
                    break
        _loaded[folder] = (found, origin)
    return _loaded[folder]


def overlay(folder, table, rows):
    """A table's rows with the hotfixes that stand over them (cached): a valid record replaces the row of its id or
    adds one, a removed record takes the row away; "invalid" and "not public" records change nothing. Records carried
    over from an earlier build only add the rows the table does not have: the newer table has the last word on its
    own rows. table: the ft.db2.Table the rows were read from. The count of what changed is kept in STATS."""
    found, origin = cached(folder)
    records = found.get(table.table_hash)
    names = [name for name, _field in table.columns]
    if not records or 'ID' not in names:
        return rows
    by_id = {row['ID']: row for row in rows}
    stat = STATS.setdefault(folder, {}).setdefault(table.name, [0, 0, 0, 0])
    ORIGIN[folder] = origin
    for record_id, record in records.items():
        if origin is not None and (record.status != VALID or record_id in by_id):
            continue   # an older build's hotfix: the newer table stands where it has the row, and nothing is taken away
        if record.status == REMOVED:
            stat[2] += by_id.pop(record_id, None) is not None
        elif record.status == VALID:
            row = decode(record.data, table.meta, record_id, names)
            if row is None:
                stat[3] += 1
            elif record_id not in by_id:
                by_id[record_id] = row
                stat[0] += 1
            elif by_id[record_id] != row:
                by_id[record_id] = row
                stat[1] += 1
    return list(by_id.values())


def summary(folder):
    """"ItemSparse +12 ~340 -1, ..." for the log: what the hotfixes changed in the snapshot's tables; '' when nothing."""
    parts = []
    for name, (added, changed, removed, misfit) in sorted(STATS.get(folder, {}).items()):
        if added or changed or removed or misfit:
            parts.append(f'{name} +{added} ~{changed} -{removed}' + (f' (!{misfit} not read)' if misfit else ''))
    if parts and ORIGIN.get(folder):
        return f'(carried over from build {ORIGIN[folder]} until this build has its own: only rows its tables lack) ' + ', '.join(parts)
    return ', '.join(parts)


def fetch(builds_folder, known_builds, url=None, get=None):
    """Downloads the live cache and keeps it with the snapshot of its build.

    Returns {'code': 0 stored | 3 unchanged | 2 not usable, 'build', 'records', 'message'}. known_builds: the builds
    that have a snapshot. get: a function url -> bytes (tests)."""
    url = url or MIRROR
    try:
        blob = (get or _download)(url)
        build, records = parse(blob)
    except (OSError, urllib.error.URLError, CacheError, RuntimeError) as error:
        return {'code': 2, 'build': 0, 'records': 0, 'message': f'the hotfix cache could not be read ({error})'}
    if build not in known_builds:
        return {'code': 2, 'build': build, 'records': len(records),
                'message': f'the hotfix cache is for build {build}, which has no snapshot (run "tracker.py fetch" first): not stored'}
    folder = os.path.join(builds_folder, str(build))
    path = os.path.join(folder, FILE)
    digest = hashlib.sha256(blob).hexdigest()
    try:
        with open(path, 'rb') as handle:
            if hashlib.sha256(handle.read()).hexdigest() == digest:
                return {'code': 3, 'build': build, 'records': len(records), 'message': f'the hotfixes of build {build} have not changed ({len(records)} records)'}
    except OSError:
        pass
    scratch = f'{path}.{os.getpid()}.tmp'
    with open(scratch, 'wb') as handle:
        handle.write(blob)
    os.replace(scratch, path)
    _loaded.clear()   # this build's cache, and any later build that was carrying an older one over
    meta = os.path.join(folder, 'build.json')
    try:
        with open(meta, encoding='utf-8-sig') as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        info = {}
    import datetime
    info['hotfixes'] = {'read': datetime.date.today().isoformat(), 'records': len(records), 'source': url}
    with open(meta, 'w', encoding='utf-8') as handle:
        json.dump(info, handle, ensure_ascii=False, indent=1)
    return {'code': 0, 'build': build, 'records': len(records), 'message': f'build {build}: {len(records)} hotfix records stored (run the analysis)'}


def _download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ForeverTracker/1.3 (private server admin tool)'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()
