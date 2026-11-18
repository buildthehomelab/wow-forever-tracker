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
import hashlib
import json
import os
import shutil
import struct
import tempfile

from . import cdn, content, db2, hotfixes, vanilla
from .config import BUILDS, CONFIG, DATA, SCHEMA

FILES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'schema', 'db2-files.json')
CACHE = os.path.join(DATA, 'cdn')
COMPLETE_CACHE = os.path.join(DATA, 'cdn-checkout')   # complete()'s own: the client check removes CACHE when it is done
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
    whole = [b for b in builds if not b['partial']] or builds
    folder = next((b['dir'] for b in builds if b['build'] == build), whole[-1]['dir'] if whole else None)
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
    builds = [b for b in content.builds() if not b.get('baseline')]   # the original game is no build of the client's
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


KEY_LOOKUP_FILE = 1302851   # TactKeyLookup.db2: a key's number -> its name (8 bytes)
KEY_LOOKUP_META = {'fields': [{'type': 'byte', 'array': 8, 'signed': False}], 'index': -1, 'parent': -1,
                   'fieldCount': 1, 'fileFieldCount': 1, 'layoutHash': '', 'names': ['ID', 'TACTID']}


def key_numbers(data):
    """{key name: key number} from the bytes of the client's TactKeyLookup table. Blizzard hands a key out by its
    number (a TactKey hotfix record); a table's hidden section names its key by name: this table joins the two.
    {} when the bytes are not that table."""
    db2.SCHEMA.setdefault('TactKeyLookup', KEY_LOOKUP_META)
    folder = tempfile.mkdtemp(prefix='ft-keys-')
    try:
        path = os.path.join(folder, 'TactKeyLookup.db2')
        with open(path, 'wb') as handle:
            handle.write(data)
        out = {}
        for row in db2.Table(path, 'TactKeyLookup'):
            values = list(row.values())
            if len(values) == 9:   # the id, then the name's 8 bytes as the file has them (the name is read backwards)
                out[bytes(values[:0:-1]).hex().upper()] = int(values[0])
        return out
    except (KeyError, ValueError, struct.error, IndexError, TypeError):
        return {}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def build_info(build):
    try:
        with open(os.path.join(BUILDS, str(build), 'build.json'), encoding='utf-8-sig') as handle:
            info = json.load(handle)
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def key_ids(build):
    """{key name: key number} of the keys a stored snapshot waits for (build.json, 'key_ids'); None when the snapshot
    was stored before the tracker kept them."""
    numbers = build_info(build).get('key_ids')
    if not isinstance(numbers, dict):
        return None
    return {str(name).upper(): int(number) for name, number in numbers.items() if str(number).lstrip('-').isdigit()}


def hotfix_keys(build, numbers=None):
    """{key name: 16 bytes}: the keys Blizzard has handed out by hotfix, by name. numbers: {key name: number} (the
    stored snapshot's by default); the hotfix cache is the one that stands over that snapshot."""
    numbers = key_ids(build) if numbers is None else numbers
    if not numbers:
        return {}
    handed = hotfixes.tact_keys(os.path.join(BUILDS, str(build)))
    return {name: handed[number] for name, number in numbers.items() if number in handed}


def unlocked(build, published):
    """The keys a stored snapshot waits for that have been published since: [key names]. Unreleased content is in the
    client encrypted and its key comes out when the content opens, so a build already stored gains readable parts
    with time; published: the names of the keys known now."""
    known = {str(name).upper() for name in published}
    return sorted({key for keys in waiting_keys(build).values() for key in keys} & known)


def read_key_numbers(reader):
    """{key name: number} through a reader (file data id -> bytes); {} when the build has no such table."""
    try:
        return key_numbers(reader(KEY_LOOKUP_FILE))
    except (KeyError, cdn.Encrypted):
        return {}


def remember_key_ids(build, numbers):
    """Writes the numbers of the keys a stored snapshot waits for into its build.json."""
    info = build_info(build)
    if not info:
        return
    info['key_ids'] = {key: numbers[key] for keys in waiting_keys(build).values() for key in keys if key in numbers}
    path = os.path.join(BUILDS, str(build), 'build.json')
    with open(f'{path}.tmp', 'w', encoding='utf-8') as handle:
        json.dump(info, handle, ensure_ascii=False, indent=1)
    os.replace(f'{path}.tmp', path)


STATUS = os.path.join(DATA, 'client-check.json')


def note(kind, message, code=None, path=None, now=None):
    """Keeps the last answer of a check for the website (the Forge says when Blizzard's servers were last asked and
    what they said): kind 'client' or 'hotfixes'. code: the result's code, None when the server could not be read."""
    path = path or STATUS
    try:
        with open(path, encoding='utf-8') as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    state[kind] = {'at': int(now if now is not None else datetime.datetime.now().timestamp()), 'code': code, 'message': str(message)}
    try:
        with open(f'{path}.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False)
        os.replace(f'{path}.{os.getpid()}.tmp', path)
    except OSError:
        pass   # a note that cannot be written is no reason to fail the check


def noted(kind, call, path=None):
    """call (-> a result with 'code' and 'message'), with its answer kept by note(); an error is noted and raised on."""
    def run():
        try:
            result = call()
        except Exception as error:
            note(kind, f'could not be read ({error})', None, path)
            raise
        note(kind, result['message'], result['code'], path)
        return result
    return run


def calm(log):
    """A log for the lines of a check. They go to the file the website reads to tell how a run ended, and it takes
    "Error" or "Traceback" anywhere in it for a crash: a server that answered "HTTP Error 503" is no crash."""
    return lambda text: log(str(text).replace('Error', 'error').replace('Traceback', 'traceback'))


def check(fetch_client, fetch_hotfixes, log=print, fetch_history=None, fetch_notes=None):
    """The live build, then Blizzard's hotfixes, then the builds before: True when one of them stored something the
    analysis has not seen.

    fetch_client: a function -> the result of fetch(); fetch_hotfixes: a function -> the result of hotfixes.fetch(),
    asked after the build so that a cache for the build just stored finds its snapshot; fetch_history: a function ->
    the result of history(), asked last (it fills in below the newest snapshot, with the keys handed out so far). A
    source that cannot be reached is said and passed over: the others are still asked."""
    say = calm(log)
    new = False
    try:
        result = fetch_client()
        say('client: ' + result['message'])
        new = result['code'] == FETCHED
    except (RuntimeError, OSError, LookupError, StopIteration, ValueError) as error:
        say(f"client: Blizzard's servers could not be read ({error}): the stored build stays")
    stored = False
    try:
        result = fetch_hotfixes()
        say('hotfixes: ' + result['message'])
        stored = result['code'] == 0
    except (RuntimeError, OSError, LookupError, ValueError) as error:
        say(f'hotfixes: the cache could not be read ({error})')
    if stored:
        # new hotfixes may hand out a key the stored build waits for: the build is asked once more, and read again
        # at once when they do
        try:
            result = fetch_client()
            if result['code'] == FETCHED:
                say('client: ' + result['message'])
        except (RuntimeError, OSError, LookupError, StopIteration, ValueError) as error:
            say(f"client: Blizzard's servers could not be read ({error}): the stored build stays")
    before = False
    if fetch_history:
        try:
            result = fetch_history()
            say('earlier builds: ' + result['message'])
            before = result['code'] == FETCHED
        except (RuntimeError, OSError, LookupError, StopIteration, ValueError) as error:
            say(f'earlier builds: the list of builds could not be read ({error}): asked again at the next check')
    written = False
    if fetch_notes:
        # the notes date the hotfixes: new ones are a reason to work the timeline out again
        try:
            result = fetch_notes()
            say('notes: ' + result['message'])
            written = result['code'] == 0
        except (RuntimeError, OSError, LookupError, ValueError) as error:
            say(f'notes: could not be read ({error}): asked again at the next check')
    return new or stored or before or written


def store(build, version, tables, still, numbers, source, day=None, more=None):
    """Writes a build's tables as its snapshot, whole or not at all. tables: {name: bytes}; still: {table: [key
    names]} of the parts nobody can read yet; numbers: {key name: number}; day: the day the build came out, when
    something says so (else the day it was first stored); more: other things build.json says of it."""
    scratch = os.path.join(BUILDS, f'.{build}.part')
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(os.path.join(scratch, LOCALE))
    for name, data in tables.items():
        with open(os.path.join(scratch, LOCALE, name + '.db2'), 'wb') as handle:
            handle.write(data)
    target = os.path.join(BUILDS, str(build))
    info = {}
    try:
        with open(os.path.join(target, 'build.json'), encoding='utf-8-sig') as handle:
            info = json.load(handle)   # a build read again: the day it was first seen and its note stay
    except (OSError, ValueError):
        pass
    today = datetime.date.today().isoformat()
    info.update({'build': build, 'version': version, 'date': info.get('date') or day or today, 'read': today, 'waiting': still,
                 # the numbers of the keys still waited for: a hotfix hands a key out by its number
                 'key_ids': {key: numbers[key] for keys in still.values() for key in keys if key in numbers},
                 'source': source})
    info.update(more or {})
    with open(os.path.join(scratch, 'build.json'), 'w', encoding='utf-8') as handle:
        json.dump(info, handle, ensure_ascii=False, indent=1)
    if os.path.isdir(target):          # a build read again: the new copy replaces it whole
        # but its hotfixes are not the CDN's to give back: the newest cache and every cache kept before it (with the
        # steps worked out of them) go over to the new copy
        kept = os.path.join(target, hotfixes.FILE)
        if os.path.isfile(kept):
            shutil.copy2(kept, os.path.join(scratch, hotfixes.FILE))
        kept = os.path.join(target, hotfixes.HISTORY)
        if os.path.isdir(kept):
            shutil.copytree(kept, os.path.join(scratch, hotfixes.HISTORY))
        shutil.rmtree(target)
    os.replace(scratch, target)


def fetch(product=None, force=False, keep_cache=False, log=print, reader=None, live=None, published=None, waiting=None, use_keys=None):
    """Snapshots the live build from the CDN when it is newer than the newest snapshot, or reads it again when a key
    the stored copy was waiting for is out: on the published list, or handed out by Blizzard in a hotfix.

    Returns {'code': FETCHED | UP_TO_DATE | REFUSED, 'build', 'version', 'message', 'problems': [(table, why)]}.
    For tests: reader (file data id -> bytes), live ({'build', 'version', 'config'}), published (a function ->
    key names known now), waiting (a function -> {file data id: [key names]} of what the reader could not read),
    use_keys (a function taking {key name: key}: the keys from hotfixes the reader is given).
    """
    product = product or product_name()
    live = live or cdn.live(product)
    build, version = int(live['build']), live['version']
    have = newest_snapshot()
    opened = []
    tact = None
    if build <= have and not force:
        if build == have and waiting_keys(build):
            if key_ids(build) is None and reader is None and hotfixes.tact_keys(os.path.join(BUILDS, str(build))):
                # stored before the tracker kept the keys' numbers: without them a key that comes by hotfix cannot be
                # told from any other. Learned once, from the build's own table.
                log(f'client: learning the numbers of the keys build {version} waits for (once; the build is indexed for it)')
                tact = cdn.Tact(CACHE, product=product, refresh=True, log=lambda text: log('client: ' + text))
                if tact.version == version:
                    remember_key_ids(build, read_key_numbers(tact.read))
            names = set(hotfix_keys(build))
            try:
                names |= set(published() if published else cdn.published_keys(product))
            except RuntimeError as error:
                log(f'client: the list of published keys could not be read ({error}): only the keys from hotfixes are checked this time')
            opened = unlocked(build, names)
        if not opened:
            if tact is not None and not keep_cache:
                shutil.rmtree(CACHE, ignore_errors=True)
            return {'code': UP_TO_DATE, 'build': build, 'version': version, 'problems': [],
                    'message': f'the live build is {version}; the newest snapshot is {have}: nothing to fetch'}
        log(f'client: {len(opened)} key(s) build {version} was waiting for are out ({", ".join(opened[:4])}'
            f'{"..." if len(opened) > 4 else ""}): reading its tables again')
    else:
        log(f'client: build {version} is live, the newest snapshot is {have or "none"}: reading its tables from the CDN')
    if reader is None:
        tact = tact or cdn.Tact(CACHE, product=product, refresh=True, log=lambda text: log('client: ' + text))
        if tact.version != version:
            # the version server moved between the two questions: take the build the reader pinned
            build, version = int(tact.version.rsplit('.', 1)[-1]), tact.version
        reader = lambda file_id: tact.read(file_id, partial=True)
        waiting = lambda: tact.absent
        use_keys = tact.extra_keys.update
    # the keys Blizzard handed out by hotfix, by the numbers this build gives them. The hotfix cache that stands over
    # the newest stored build is asked: a key is a key, whichever build's cache carries it
    numbers = read_key_numbers(reader)
    handed = hotfix_keys(have, numbers) if have else {}
    if handed and use_keys:
        use_keys(handed)
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
    earlier = [b['build'] for b in content.builds() if b['build'] != build and not b['partial']]
    known = snapshot_layouts(earlier[-1]) if earlier else {}
    # a table the newest snapshot does not have either is no loss (the tracker lives without it today)
    problems = [(name, why) for name, why in problems if name in known or not known]
    problems += layout_problems(tables, known)
    if problems:
        return {'code': REFUSED, 'build': build, 'version': version, 'problems': problems,
                'message': f'build {version} was not stored: ' + '; '.join(f'{name} ({why})' for name, why in problems[:8])
                           + (f' and {len(problems) - 8} more' if len(problems) > 8 else '')
                           + '. The schema has to follow the core first (tools/make_db2_schema.py).'}
    # what could not be read, by table: the keys to watch for (unlocked)
    by_id = {file_id: name for name, file_id in wanted.items()}
    still = {by_id[int(file_id)]: sorted(keys) for file_id, keys in ((waiting or dict)() or {}).items() if int(file_id) in by_id and keys}
    store(build, version, tables, still, numbers, f'Blizzard CDN ({product}, build config {live.get("config", "")[:12]})')
    if not keep_cache and tact is not None:
        # the lookup database and the indexes of this build (several hundred MB): the next build needs its own
        shutil.rmtree(CACHE, ignore_errors=True)
    return {'code': FETCHED, 'build': build, 'version': version, 'problems': [],
            'message': f'build {version}: {len(tables)} tables stored from the CDN'
                       + (f', {hidden} section(s) of unreleased content still hidden (their keys are not published yet; the build is read again when one is)' if hidden else '')
                       + ' (run the analysis)'}


# --- the builds before: the changelog back to the beta -------------------------------------------

REFUSALS = os.path.join(BUILDS, 'history.json')   # the earlier builds that could not be stored, and why
HISTORY = 'wow_classic_beta:1.60.'                # [client] history, when config.ini does not say
GIVE_UP = 3                                       # builds in a row that could not be reached: the rest waits


def history_products(product=None, setting=None):
    """{product: version prefix} of the products whose builds make the history: the live product itself, and those
    [client] history names, each with the versions that count ("wow_classic_beta:1.60.": WoW: Forever's beta was
    shipped under the Classic beta's name, next to other games' betas). None when it says "off"."""
    setting = CONFIG.get('client', 'history', HISTORY) if setting is None else setting
    if setting.strip().lower() in ('off', 'no', 'none', '0'):
        return None
    out = {product or product_name(): ''}
    for part in setting.replace(';', ',').split(','):
        name, _sep, prefix = part.strip().partition(':')
        if name:
            out.setdefault(name.strip(), prefix.strip())
    return out


def schema_mark():
    """What a refusal depends on: the tables' layouts as the tracker reads them (a refused build is asked again when
    the schema has changed)."""
    try:
        with open(SCHEMA, 'rb') as handle:
            return hashlib.sha1(handle.read()).hexdigest()[:12]
    except OSError:
        return ''


def refusals(path=None):
    try:
        with open(path or REFUSALS, encoding='utf-8') as handle:
            found = json.load(handle)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def earlier_files():
    """{table: file data id} of what an earlier build is stored with: the tables compared build after build."""
    known = files()
    return {name: known[name] for name in content.DIFF_TABLES if name in known}


def alone_here(name):
    """An open file whose lock says "one at a time" (the container's check and the Forge's can start together), or
    None when another run holds it. Where the system has no such lock (Windows), a file all the same: nothing there
    starts two checks by itself."""
    os.makedirs(BUILDS, exist_ok=True)
    handle = open(os.path.join(BUILDS, name), 'a')
    try:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        pass
    except OSError:
        handle.close()
        return None
    return handle


def complete(build, names, product=None, log=print, listed=None, opener=None, keep_cache=False):
    """Reads the tables an earlier build was stored without (ft.checkout needs every table of a step), from Blizzard's
    CDN, into its folder. names: the tables wanted. Returns {table: why} of those it could not store (another layout,
    not in this build, encrypted without a published key); the rest are stored, also when one is refused. listed and
    opener as for history_run (tests)."""
    folder = os.path.join(BUILDS, str(build))
    wanted = {name: file_id for name, file_id in files().items() if name in names and not os.path.isfile(os.path.join(folder, LOCALE, name + '.db2'))}
    if not wanted:
        return {}
    product = product or product_name()
    entries = (listed or (lambda: cdn.builds(history_products(product) or {product: ''}, CONFIG.get('client', 'build_list') or None)))()
    entry = next((e for e in entries if e['build'] == build), None)
    if entry is None:
        return {name: f'build {build} is not on the list of builds' for name in wanted}
    log(f'client: reading {len(wanted)} more table(s) of build {entry["version"]} from the CDN')
    try:
        if opener:
            reader, waiting, use_keys = opener(entry)
        else:
            tact = cdn.Earlier(COMPLETE_CACHE, entry, product=entry.get('product') or product, log=lambda text: None)
            tact.prepare(list(wanted.values()) + [KEY_LOOKUP_FILE])
            reader, waiting, use_keys = (lambda file_id, tact=tact: tact.read(file_id, partial=True)), (lambda tact=tact: tact.absent), tact.extra_keys.update
        numbers = read_key_numbers(reader)
        handed = hotfix_keys(newest_snapshot(), numbers)
        if handed and use_keys:
            use_keys(handed)
        tables, refused = {}, {}
        for name, file_id in sorted(wanted.items()):
            try:
                tables[name], _hidden = mark_decrypted(reader(file_id))
            except KeyError:
                refused[name] = 'not in this build'
            except cdn.Encrypted:
                refused[name] = 'encrypted: no published key'
        for name, why in layout_problems(tables, snapshot_layouts()):
            refused[name] = why
            tables.pop(name, None)
        os.makedirs(os.path.join(folder, LOCALE), exist_ok=True)
        for name, data in tables.items():
            path = os.path.join(folder, LOCALE, name + '.db2')
            with open(f'{path}.tmp', 'wb') as handle:
                handle.write(data)
            os.replace(f'{path}.tmp', path)
        if tables:
            info = build_info(build) or {}
            by_id = {file_id: name for name, file_id in wanted.items()}
            still = {by_id[int(file_id)]: sorted(keys) for file_id, keys in (waiting() or {}).items() if int(file_id) in by_id and by_id[int(file_id)] in tables and keys}
            info['waiting'] = {**(info.get('waiting') or {}), **still}
            info['key_ids'] = {**(info.get('key_ids') or {}), **{key: numbers[key] for keys in still.values() for key in keys if key in numbers}}
            meta = os.path.join(folder, 'build.json')
            with open(f'{meta}.tmp', 'w', encoding='utf-8') as handle:
                json.dump(info, handle, ensure_ascii=False, indent=1)
            os.replace(f'{meta}.tmp', meta)
        log(f'client: build {entry["version"]}: {len(tables)} more table(s) stored' + (f', {len(refused)} not ({", ".join(f"{n}: {w}" for n, w in sorted(refused.items())[:4])})' if refused else ''))
        return refused
    finally:
        if not keep_cache and not opener:
            shutil.rmtree(COMPLETE_CACHE, ignore_errors=True)


def history(product=None, log=print, listed=None, opener=None, keep_cache=False, again=False, limit=0, path=None, origin=None):
    """history_run(), one at a time: a second run started while the first is reading the builds stores nothing. Then
    the original game, once: the build the changelog starts with (ft.vanilla). origin: a function -> the result of
    ft.vanilla.fetch (for tests; with a made-up list of builds it is not asked for unless given)."""
    gate = alone_here('history.lock')
    if gate is None:
        return {'code': UP_TO_DATE, 'stored': [], 'refused': {}, 'failed': {}, 'message': 'another check is reading the earlier builds: left to it'}
    try:
        result = history_run(product, log, listed, opener, keep_cache, again, limit, path)
        if origin is None and listed is None and opener is None:
            origin = lambda: vanilla.fetch(log=log)
        if origin and newest_snapshot():
            try:
                found = origin()
                if found['code'] == vanilla.STORED:
                    result['code'] = FETCHED
                    result['message'] = result['message'].replace(' (run the analysis)', '') + '; ' + found['message']
            except (RuntimeError, OSError, LookupError, ValueError) as error:
                result['message'] += f'; the original game could not be read ({error}): asked again at the next check'
        return result
    finally:
        gate.close()


def history_run(product=None, log=print, listed=None, opener=None, keep_cache=False, again=False, limit=0, path=None):
    """Stores the builds that came before the newest snapshot and have none, from Blizzard's CDN: the changelog then
    goes back build by build to the first beta. Only the tables the changelog compares are stored (the tooltips, the
    Forge and the map read the newest build alone).

    A build whose tables have another layout than the tracker reads is not stored and remembered (history.json): it
    is asked again when the schema changes, or with again. A build that could not be reached is tried at the next
    call. Returns {'code': FETCHED | UP_TO_DATE, 'stored': [builds], 'refused': {build: why}, 'failed': {build: why},
    'message'}. For tests: listed (a function -> cdn.builds()), opener (an entry of the list -> (reader, waiting,
    use_keys))."""
    product = product or product_name()
    have = newest_snapshot()
    products = history_products(product)
    done = {'code': UP_TO_DATE, 'stored': [], 'refused': {}, 'failed': {}}
    if products is None:
        return {**done, 'message': 'the earlier builds are not asked for ([client] history = off)'}
    if not have:
        return {**done, 'message': 'no snapshot yet: the earlier builds are read once there is one'}
    builds = (listed or (lambda: cdn.builds(products, CONFIG.get('client', 'build_list') or None)))()
    stored = {b['build']: b for b in content.builds() if not b.get('baseline')}
    # the day a stored build came out, where the list knows better than the day the tracker first saw it
    for entry in builds:
        info = build_info(entry['build']) if entry['build'] in stored else {}
        if info and entry['date'] and info.get('date') != entry['date'] and not info.get('dated'):
            info.update({'date': entry['date'], 'dated': 'list'})
            meta = os.path.join(BUILDS, str(entry['build']), 'build.json')
            with open(f'{meta}.tmp', 'w', encoding='utf-8') as handle:
                json.dump(info, handle, ensure_ascii=False, indent=1)
            os.replace(f'{meta}.tmp', meta)
            done['code'] = FETCHED   # the analysis writes the builds' days
    mark = schema_mark()
    refused = {} if again else {build: note for build, note in refusals(path).items() if isinstance(note, dict) and note.get('schema') == mark}
    todo = [entry for entry in builds if entry['build'] < have and entry['build'] not in stored and str(entry['build']) not in refused]
    if limit:
        todo = todo[-limit:]
    if not todo:
        waiting = len([b for b in refused if int(b) < have and int(b) not in stored])
        return {**done, 'message': f'every earlier build the list names is stored ({len([b for b in stored if b < have])} before {have})'
                                   + (f'; {waiting} could not be read with this schema' if waiting else '')}
    log(f'client: {len(todo)} earlier build(s) have no snapshot ({todo[0]["version"]} to {todo[-1]["version"]}): reading their tables from the CDN (once)')
    wanted = earlier_files()
    known = snapshot_layouts()
    unreachable = 0
    for index, entry in enumerate(todo, 1):
        build, version = entry['build'], entry['version']
        try:
            if opener:
                reader, waiting, use_keys = opener(entry)
            else:
                tact = cdn.Earlier(CACHE, entry, product=product, log=lambda text: None)
                tact.prepare(list(wanted.values()) + [KEY_LOOKUP_FILE])
                reader, waiting, use_keys = (lambda file_id, tact=tact: tact.read(file_id, partial=True)), (lambda tact=tact: tact.absent), tact.extra_keys.update
            numbers = read_key_numbers(reader)
            handed = hotfix_keys(have, numbers)   # the keys Blizzard has handed out since open what was hidden then
            if handed and use_keys:
                use_keys(handed)
            tables, problems = {}, []
            for name, file_id in sorted(wanted.items()):
                try:
                    tables[name], _hidden = mark_decrypted(reader(file_id))
                except KeyError:
                    if name in known:
                        problems.append((name, 'not in this build'))
                except cdn.Encrypted:
                    problems.append((name, 'encrypted: no published key'))
            problems += layout_problems(tables, known)
        except cdn.Gone as error:
            # a definite answer, not a server in trouble: the next build is asked as usual
            done['failed'][build] = str(error)
            log(f"client: earlier build {version} ({index}/{len(todo)}) is not on Blizzard's CDN whole any more ({error}): asked again at the next check")
            continue
        except (RuntimeError, OSError, LookupError, ValueError, struct.error, StopIteration) as error:
            done['failed'][build] = str(error)
            log(f'client: earlier build {version} ({index}/{len(todo)}) could not be read ({error}): tried again at the next check')
            unreachable += 1
            if unreachable >= GIVE_UP:
                log(f'client: {GIVE_UP} builds in a row could not be read: the others wait for the next check')
                break
            continue
        unreachable = 0
        if problems:
            why = '; '.join(f'{name} ({reason})' for name, reason in problems[:6]) + (f' and {len(problems) - 6} more' if len(problems) > 6 else '')
            done['refused'][build] = why
            log(f'client: earlier build {version} ({index}/{len(todo)}) was not stored: {why}')
            continue
        by_id = {file_id: name for name, file_id in wanted.items()}
        still = {by_id[int(file_id)]: sorted(keys) for file_id, keys in (waiting() or {}).items() if int(file_id) in by_id and keys}
        store(build, version, tables, still, numbers, f'Blizzard CDN ({entry["product"]}, build config {entry["config"][:12]})', entry['date'] or None,
              {'tables': 'changelog', 'dated': 'list', **({'note': 'Beta build.'} if 'beta' in entry['product'] else {})})
        done['stored'].append(build)
        log(f'client: earlier build {version} ({index}/{len(todo)}): {len(tables)} tables stored')
    if done['refused'] or again:
        kept = {} if again else refusals(path)
        kept.update({str(build): {'why': why, 'schema': mark} for build, why in done['refused'].items()})
        for build in done['stored']:
            kept.pop(str(build), None)
        target = path or REFUSALS
        with open(f'{target}.tmp', 'w', encoding='utf-8') as handle:
            json.dump(kept, handle, ensure_ascii=False, indent=1)
        os.replace(f'{target}.tmp', target)
    if not keep_cache and not opener:
        shutil.rmtree(CACHE, ignore_errors=True)
    if done['stored']:
        done['code'] = FETCHED
    parts = [f'{len(done["stored"])} earlier build(s) stored']
    if done['refused']:
        parts.append(f'{len(done["refused"])} not stored (another table layout)')
    if done['failed']:
        parts.append(f'{len(done["failed"])} could not be read (tried again at the next check)')
    return {**done, 'message': ', '.join(parts) + (' (run the analysis)' if done['code'] == FETCHED else '')}
