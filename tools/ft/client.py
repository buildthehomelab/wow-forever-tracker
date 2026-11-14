"""The official client, kept up to date from Blizzard's own servers (docs/CLIENT.md).

The official list is the client's own tables. Until now they were read from the server's extracted copy only, when
the realm moved to another build: the tracker saw a new client build weeks after players' clients had it, and the
changelog stayed empty. `tracker.py fetch` asks Blizzard's version server which build is live and, when it is newer
than the newest snapshot, reads the tables the tracker needs straight from the CDN (ft.cdn) into a snapshot of that
build. The next analysis then compares the server with what players' clients hold today.

A table is read with the layout the tracker's schema describes (tools/schema/db2-schema.json). When Blizzard changed
a table's layout in the new build, reading it that way would give nonsense, so the whole build is refused and the
tables are named: the schema has to follow the core first (tools/make_db2_schema.py). "Changed" means: another layout
than the same table has in the newest snapshot, which the tracker reads today, and another than the schema names.
"""
import datetime
import json
import os
import shutil
import struct

from . import cdn, content, db2
from .config import BUILDS, CONFIG, DATA

FILES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'schema', 'db2-files.json')
CACHE = os.path.join(DATA, 'cdn')
LOCALE = 'enUS'   # the root file's enUS entries are the ones read (ft.cdn.root_entries)

FETCHED, UP_TO_DATE, REFUSED = 0, 3, 2   # exit codes of `tracker.py fetch`


def files():
    """{table: file data id} of the tables a snapshot holds."""
    with open(FILES_PATH, encoding='utf-8') as handle:
        known = json.load(handle)['files']
    return {name: int(known[name]) for name in content.TABLES if name in known}


def header(data):
    """(table hash, layout hash) of a WDC5 file's bytes, as 8 hex digits each; None when it is no WDC5 file."""
    if len(data) < 172 or data[:4] != b'WDC5':
        return None
    table_hash, layout_hash = struct.unpack_from('<II', data, 136 + 16)
    return f'{table_hash:08X}', f'{layout_hash:08X}'


SECTIONS_AT = 204          # WDC5: where the section headers start (after the header's 204 bytes)
SECTION = struct.Struct('<QIIIIIIII')   # tact key, file offset, records, string table size, ...
DECRYPTED = db2.DECRYPTED  # the mark the core's extractor leaves on a section it could decrypt


def mark_decrypted(data):
    """A table as the core's extractor would have written it. In the client's file a section of unreleased content
    carries the name of its key. The extractor replaces that name with a mark on the sections it could decrypt, and
    the tracker's reader (ft.db2) reads marked sections and skips the others. A file read from the CDN has no marks,
    so every keyed section would be skipped, also the ones whose key is public: mark those whose bytes are there
    (anything but zeros). Returns (bytes, sections still hidden)."""
    if header(data) is None:
        return data, 0
    count = struct.unpack_from('<I', data, 136 + 36 + 4 + 24)[0]
    sections = [SECTION.unpack_from(data, SECTIONS_AT + i * SECTION.size) for i in range(count)]
    out, hidden = bytearray(data), 0
    for i, section in enumerate(sections):
        key, start = section[0], section[1]
        if not key or key == DECRYPTED:
            continue
        end = next((s[1] for s in sections[i + 1:] if s[1] > start), len(data))
        if any(data[start:end]):
            struct.pack_into('<Q', out, SECTIONS_AT + i * SECTION.size, DECRYPTED)
        else:
            hidden += 1
    return bytes(out), hidden


def layout_problems(tables, known=None, schema=None):
    """[(table, why)] for the tables that cannot be trusted to read: not a WDC5 file, or a layout that is neither the
    one the same table has in the newest snapshot (`known`: {name: layout hash}, what the tracker reads today) nor the
    one the schema names. tables: {name: bytes}."""
    schema = db2.SCHEMA if schema is None else schema
    known = known or {}
    out = []
    for name in sorted(tables):
        found = header(tables[name])
        wanted = {str((schema.get(name) or {}).get('layoutHash') or '').upper(), str(known.get(name) or '').upper()} - {''}
        if found is None:
            out.append((name, 'not a WDC5 table'))
        elif name not in schema:
            out.append((name, 'no schema for this table'))
        elif found[1] not in wanted:
            out.append((name, f'layout {found[1]}, the tracker reads {" or ".join(sorted(wanted))}'))
    return out


def snapshot_layouts(build=None):
    """{table: layout hash} of a stored snapshot (the newest by default): the layouts the tracker reads today."""
    builds = content.builds()
    folder = next((b['dir'] for b in builds if b['build'] == build), builds[-1]['dir'] if builds else None)
    out = {}
    for name in content.TABLES if folder else []:
        path = os.path.join(folder, LOCALE, name + '.db2')
        if os.path.isfile(path):
            with open(path, 'rb') as handle:
                found = header(handle.read(172))
            if found:
                out[name] = found[1]
    return out


def newest_snapshot():
    builds = content.builds()
    return builds[-1]['build'] if builds else 0


def status(product=None):
    """What is live, what the tracker holds and what the server runs: {'live': {...} | None, 'snapshot', 'server'}."""
    try:
        live = cdn.live(product or product_name())
    except (RuntimeError, StopIteration, KeyError, ValueError, OSError) as error:
        live = {'error': str(error)}
    return {'live': live, 'snapshot': newest_snapshot(), 'server': CONFIG.server_build()}


def product_name():
    return CONFIG.get('client', 'product', 'wowf') or 'wowf'


def waiting_keys(build):
    """{table: [key names]} a stored snapshot still waits for: the parts of its tables that were unreadable when it was
    read from the CDN (build.json, 'waiting'). {} for a snapshot made from the server's own copy."""
    try:
        with open(os.path.join(BUILDS, str(build), 'build.json'), encoding='utf-8-sig') as handle:
            waiting = json.load(handle).get('waiting') or {}
    except (OSError, ValueError):
        return {}
    return {str(name): [str(key).upper() for key in keys] for name, keys in waiting.items() if isinstance(keys, list)}


def unlocked(build, published):
    """The keys a stored snapshot waits for that have been published since: [key names]. Unreleased content is in the
    client encrypted and its key comes out when the content opens, so a build already stored gains readable parts
    with time; published: the names of the keys known now."""
    known = {str(name).upper() for name in published}
    return sorted({key for keys in waiting_keys(build).values() for key in keys} & known)


def fetch(product=None, force=False, keep_cache=False, log=print, reader=None, live=None, published=None, waiting=None):
    """Snapshots the live build from the CDN when it is newer than the newest snapshot, or reads it again when a key
    the stored copy was waiting for has been published.

    Returns {'code': FETCHED | UP_TO_DATE | REFUSED, 'build', 'version', 'message', 'problems': [(table, why)]}.
    For tests: reader (file data id -> bytes), live ({'build', 'version', 'config'}), published (a function ->
    key names known now), waiting (a function -> {file data id: [key names]} of what the reader could not read).
    """
    product = product or product_name()
    live = live or cdn.live(product)
    build, version = int(live['build']), live['version']
    have = newest_snapshot()
    opened = []
    if build <= have and not force:
        if build == have and waiting_keys(build):
            try:
                opened = unlocked(build, (published or cdn.published_keys)())
            except RuntimeError as error:
                log(f'client: the list of published keys could not be read ({error}): not checked this time')
        if not opened:
            return {'code': UP_TO_DATE, 'build': build, 'version': version, 'problems': [],
                    'message': f'the live build is {version}; the newest snapshot is {have}: nothing to fetch'}
        log(f'client: {len(opened)} key(s) build {version} was waiting for have been published ({", ".join(opened[:4])}'
            f'{"..." if len(opened) > 4 else ""}): reading its tables again')
    else:
        log(f'client: build {version} is live, the newest snapshot is {have or "none"}: reading its tables from the CDN')
    if reader is None:
        tact = cdn.Tact(CACHE, product=product, refresh=True, log=lambda text: log('client: ' + text))
        if tact.version != version:
            # the version server moved between the two questions: take the build the reader pinned
            build, version = int(tact.version.rsplit('.', 1)[-1]), tact.version
        reader = lambda file_id: tact.read(file_id, partial=True)
        waiting = lambda: tact.absent
    tables, problems, hidden = {}, [], 0
    wanted = files()
    for index, (name, file_id) in enumerate(sorted(wanted.items()), 1):
        try:
            tables[name], sections = mark_decrypted(reader(file_id))
            hidden += sections
        except KeyError:
            problems.append((name, 'not in this build'))
        except cdn.Encrypted:
            problems.append((name, 'encrypted: no published key'))
        if index % 20 == 0:
            log(f'client: {index}/{len(wanted)} tables')
    # the layouts the tracker reads today: those of the newest other build (a build read again is no witness for itself)
    earlier = [b['build'] for b in content.builds() if b['build'] != build]
    known = snapshot_layouts(earlier[-1]) if earlier else {}
    # a table the newest snapshot does not have either is no loss (the tracker lives without it today)
    problems = [(name, why) for name, why in problems if name in known or not known]
    problems += layout_problems(tables, known)
    if problems:
        return {'code': REFUSED, 'build': build, 'version': version, 'problems': problems,
                'message': f'build {version} was not stored: ' + '; '.join(f'{name} ({why})' for name, why in problems[:8])
                           + (f' and {len(problems) - 8} more' if len(problems) > 8 else '')
                           + '. The schema has to follow the core first (tools/make_db2_schema.py).'}
    scratch = os.path.join(BUILDS, f'.{build}.part')
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(os.path.join(scratch, LOCALE))
    for name, data in tables.items():
        with open(os.path.join(scratch, LOCALE, name + '.db2'), 'wb') as handle:
            handle.write(data)
    # what could not be read, by table: the keys to watch for (unlocked)
    by_id = {file_id: name for name, file_id in wanted.items()}
    still = {by_id[int(file_id)]: sorted(keys) for file_id, keys in ((waiting or dict)() or {}).items() if int(file_id) in by_id and keys}
    target = os.path.join(BUILDS, str(build))
    info = {}
    try:
        with open(os.path.join(target, 'build.json'), encoding='utf-8-sig') as handle:
            info = json.load(handle)   # a build read again: the day it was first seen and its note stay
    except (OSError, ValueError):
        pass
    today = datetime.date.today().isoformat()
    info.update({'build': build, 'version': version, 'date': info.get('date') or today, 'read': today, 'waiting': still,
                 'source': f'Blizzard CDN ({product}, build config {live.get("config", "")[:12]})'})
    with open(os.path.join(scratch, 'build.json'), 'w', encoding='utf-8') as handle:
        json.dump(info, handle, ensure_ascii=False, indent=1)
    if os.path.isdir(target):          # a build read again: the new copy replaces it whole
        shutil.rmtree(target)
    os.replace(scratch, target)
    if not keep_cache:
        # the lookup database and the indexes of this build (several hundred MB): the next build needs its own
        shutil.rmtree(CACHE, ignore_errors=True)
    return {'code': FETCHED, 'build': build, 'version': version, 'problems': [],
            'message': f'build {version}: {len(tables)} tables stored from the CDN'
                       + (f', {hidden} section(s) of unreleased content still hidden (their keys are not published yet; the build is read again when one is)' if hidden else '')
                       + ' (run the analysis)'}
