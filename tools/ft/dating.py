"""When each of Blizzard's hotfixes came: the live cache taken apart along the builds (docs/CLIENT.md, "Hotfixes back to
the beta").

The public cache (ft.hotfixes) is downloaded once a day and only from the day the tracker first ran: the hotfixes that
came before stood in no entry of the timeline. Yet the cache of today holds them all: every row Blizzard changes by hotfix
stays in it, at its current value, until the client is rebuilt from scratch. What it does not say is WHEN. Its push
numbers do not tell: they are not in the order the hotfixes came (a push numbered 112742 is in the client of October
16, one numbered 112623 only in the client of October 27).

The CDN does. Blizzard writes the hotfixes of a build into the next client it ships ("baked in"). Every build since the
beta is stored (ft.client.history), so for every row of the cache the tracker looks for the last build whose table
still held another value: the build right after it is the first to carry the hotfix, and the hotfix came while the
build before that one was live. That is the row's window.

    a row the same in every build ............. sent again, changes nothing: part of every build's cache
    a row first carried by build B ............ a hotfix to the build before B, live until B shipped
    a row no build carries yet ................ a hotfix to the newest build
    a row of a record no build has at all ..... there by hotfix alone (thousands of items): part of every build's cache,
                                                never called "added" (ft.content.hotfix_only)

Each build then gets two caches of its own, written from today's cache with the build's number in the header: the build
as it shipped (only the rows it already carries, which change nothing) and the build at the end of its life (with the
rows of its window). ft.content.changelog makes the second one a step of its own, a hotfix entry of the timeline, and
compares the next build with the build as its hotfixes left it: what the next build only baked in is not counted twice.

What the CDN cannot give: the day inside a window (the written notes name the days, ft.notes), and a value a hotfix
had before a later hotfix replaced it, when no client was built in between (the cache keeps the current value only).
"""
import datetime
import hashlib
import json
import os

from . import db2, hotfixes

FILE = 'dated.json'        # in the newest build's hotfixes/ folder: the window of each row, with what it was worked out from
REBUILT = 'rebuilt'        # the mark of the caches written here, in a build's hotfixes/index.json
KINDS = 'base', 'window', 'newest'
_VERSION = 1


def _row_key(build_folder, table_name):
    return os.path.join(build_folder, 'enUS', table_name + '.db2')


def _sha(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def windows(chain, blob, log=print):
    """{entry index: window} for the entries of a cache: 'base' (in every build's cache), a build number (the build whose
    window the hotfix came in: the build before the first one that carries it) or 'newest' (no build carries it yet).

    chain: the stored builds, oldest first ({'build', 'dir'}; the original game left out). blob: the cache. Entries of
    tables no stored build has, the keys (push -1) and the records that are neither valid nor removed are 'base'."""
    _build, records = hotfixes.parse(blob)
    wanted = {}                     # table hash -> [entry index]
    for index, record in enumerate(records):
        if record.push != -1 and record.status in (hotfixes.VALID, hotfixes.REMOVED):
            wanted.setdefault(record.table, []).append(index)
    found = {index: 'base' for index in range(len(records))}
    names = {}                      # table hash -> table name, from the newest build that has it
    for b in reversed(chain):
        for path in _tables(b['dir']):
            name = os.path.basename(path)[:-4]
            if name in names.values():
                continue
            try:
                names[db2.Table(path, name).table_hash] = name
            except (KeyError, ValueError, OSError):
                continue
    for table_hash, indexes in wanted.items():
        name = names.get(table_hash)
        if name is None:
            continue
        # per build: does the row match the hotfix (True), differ (False), or can it not be told (None: the table is not
        # stored for that build, or the record was written for another layout)
        verdicts = {index: [] for index in indexes}
        seen = {}                   # file sha -> verdicts of the builds before with the same file
        for b in chain:
            path = _row_key(b['dir'], name)
            if not os.path.isfile(path):
                for index in indexes:
                    verdicts[index].append(None)
                continue
            digest = _sha(path)
            if digest not in seen:
                seen[digest] = _verdicts(path, name, [(index, records[index]) for index in indexes])
            for index in indexes:
                verdicts[index].append(seen[digest].get(index))
        present_somewhere = set()
        for b in chain:
            path = _row_key(b['dir'], name)
            if os.path.isfile(path):
                present_somewhere |= _ids(path, name)
        for index in indexes:
            record = records[index]
            if record.status == hotfixes.VALID and record.record not in present_somewhere:
                continue            # there by hotfix alone: base
            told = [(position, v) for position, v in enumerate(verdicts[index]) if v is not None]
            if not told:
                continue
            last_differs = max((position for position, v in told if v is False), default=None)
            if last_differs is None:
                continue            # the same in every build that can tell: base
            if last_differs == told[-1][0]:
                found[index] = 'newest'
                continue
            carrier = next(position for position, v in told if position > last_differs)
            found[index] = chain[carrier - 1]['build'] if carrier > 0 else 'base'
    counts = {}
    for value in found.values():
        counts[value] = counts.get(value, 0) + 1
    log('hotfix windows: ' + ', '.join(f'{k}: {v}' for k, v in sorted(counts.items(), key=lambda kv: (str(kv[0]) != 'base', str(kv[0])))))
    return found


def _run_heads(chain):
    """{build: the first build of its run}: a run is builds whose compared tables are the same, byte for byte."""
    heads, previous, head = {}, None, None
    for position, b in enumerate(chain):
        state = tuple(_sha(path) for path in _tables(b['dir']))
        if previous is None or state != previous or position == 1:
            head = b['build']
        heads[b['build']] = head
        previous = state
    return heads


def _tables(folder):
    path = os.path.join(folder, 'enUS')
    return [os.path.join(path, n) for n in sorted(os.listdir(path)) if n.endswith('.db2')] if os.path.isdir(path) else []


_ID_CACHE = {}


def _ids(path, name):
    key = (path, os.path.getmtime(path))
    if key not in _ID_CACHE:
        table = db2.Table(path, name)
        _ID_CACHE.clear() if len(_ID_CACHE) > 64 else None
        _ID_CACHE[key] = {row['ID'] for row in table} if 'ID' in [c for c, _ in table.columns] else set()
    return _ID_CACHE[key]


def _verdicts(path, name, entries):
    """{entry index: True | False | None} for one build's table: the hotfix's row is the table's (True), is not (False),
    cannot be told (None). A removal matches when the record is not in the table."""
    try:
        table = db2.Table(path, name)
    except (KeyError, ValueError, OSError):
        return {}
    columns = [c for c, _ in table.columns]
    if 'ID' not in columns:
        return {}
    rows = {row['ID']: row for row in table}
    out = {}
    for index, record in entries:
        if record.status == hotfixes.REMOVED:
            out[index] = record.record not in rows
            continue
        row = hotfixes.decode(record.data, table.meta, record.record, columns)
        out[index] = None if row is None else rows.get(record.record) == row
    return out


def write_cache(blob, build, keep):
    """A cache with the entries whose index is in keep, written for build (the header's number)."""
    _build, _records = hotfixes.parse(blob)
    out = bytearray(blob[:hotfixes.HEADER_SIZE])
    out[8:12] = int(build).to_bytes(4, 'little')
    at, index = hotfixes.HEADER_SIZE, 0
    while at < len(blob):
        size = hotfixes.ENTRY.unpack_from(blob, at)[6]
        end = at + hotfixes.ENTRY.size + size
        if index in keep:
            out += blob[at:end]
        at, index = end, index + 1
    return bytes(out)


def _days(b, after, notes_days):
    """(first day, last day) of a build's window: from its release to the day before the next build; the first day is
    the first hotfix day the notes name in it (the window's own date when they name none)."""
    start = b.get('date') or ''
    end = (after or {}).get('date') or datetime.date.today().isoformat()
    named = sorted(day for day in notes_days if start <= day < end) if start else []
    last = named[-1] if named else (end if after is None else max(start, _day_before(end)))
    return (named[0] if named else start or end), last, named


def _day_before(day):
    try:
        return (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    except ValueError:
        return day


def rebuild(chain, notes_days=(), log=print, force=False):
    """Writes the caches of every stored build from the newest build's cache (see the top of this file). Returns
    {'code': 0 written | 3 unchanged | 2 nothing to do, 'windows': {build: rows}, 'message'}.

    chain: ft.content.builds() without the original game, oldest first; the newest one must have its own cache.
    notes_days: the hotfix days named by written notes (ft.notes), to date the windows. Kept caches the tracker
    downloaded itself (the newest build's) are never touched; the caches written here are marked 'rebuilt' in each
    build's hotfixes/index.json and written again when the newest cache or the builds change."""
    chain = [b for b in chain if not b.get('baseline')]
    if len(chain) < 2:
        return {'code': 2, 'windows': {}, 'message': 'hotfix windows: fewer than two builds stored'}
    newest = chain[-1]
    path = os.path.join(newest['dir'], hotfixes.FILE)
    if not os.path.isfile(path):
        return {'code': 2, 'windows': {}, 'message': f"hotfix windows: build {newest['build']} has no hotfix cache of its own"}
    with open(path, 'rb') as handle:
        blob = handle.read()
    mark = {'version': _VERSION, 'cache': hashlib.sha256(blob).hexdigest(),
            'builds': [[b['build'], b.get('date')] for b in chain], 'days': sorted(notes_days)}
    state_path = os.path.join(newest['dir'], hotfixes.HISTORY, FILE)
    try:
        with open(state_path, encoding='utf-8') as handle:
            done = json.load(handle)
    except (OSError, ValueError, AttributeError):
        done = {}
    if not force and done.get('mark') == mark:
        return {'code': 3, 'windows': done.get('windows', {}), 'message': 'hotfix windows: unchanged'}
    # the rows' windows depend on the cache and the builds alone (minutes of work); the notes only date them
    rows_mark = {k: v for k, v in mark.items() if k != 'days'}
    if not force and done.get('rows_mark') == rows_mark and isinstance(done.get('rows'), list):
        found = {index: 'base' for index in range(len(hotfixes.parse(blob)[1]))}
        found.update({int(index): window for index, window in done['rows']})
        log('hotfix windows: read back (same cache, same builds)')
    else:
        found = windows(chain, blob, log)
    # A build Blizzard shipped with the very tables of the build before (a program-only build) does not end the window:
    # the hotfixes it did not bake in may have come while the build before was live. The window goes to the first build
    # of such a run (not the game's first build: the original game's step reads that one with its newest hotfixes).
    raw = found
    head = _run_heads(chain)
    found = {i: head.get(w, w) for i, w in found.items()}
    base = {i for i, w in found.items() if w == 'base'}
    by_window = {}
    for index, window in found.items():
        if window != 'base':
            by_window.setdefault(window, set()).add(index)
    summary = {}
    for position, b in enumerate(chain):
        if b is newest:
            continue
        run = head.get(b['build'], b['build'])
        if run != b['build']:
            # a program-only build in the middle of a window: live with the hotfixes of the window's first build
            carried = write_cache(blob, b['build'], base | by_window.get(run, set()))
            _rebuilt_history(b['dir'], carried, b.get('date') or '', len(base | by_window.get(run, set())), 'carried', None)
            _write(os.path.join(b['dir'], hotfixes.FILE), carried)
            continue
        # the window ends with the first build that is not a program-only copy of this one
        after = next((x for x in chain[position + 1:] if head.get(x['build']) != run), newest)
        # the build as it shipped: what it carries already. Rows dated to earlier windows match its tables (that is how
        # they were dated) and change nothing: they are left out, so the build's own cache is the base alone
        shipped = write_cache(blob, b['build'], base)
        own = by_window.get(b['build'], set())
        first, last, named = _days(b, after, notes_days)
        entries = _rebuilt_history(b['dir'], shipped, b.get('date') or first, len(base), 'base', None)
        if own:
            ended = write_cache(blob, b['build'], base | own)
            entries = _rebuilt_history(b['dir'], ended, first, len(base | own), 'window',
                                       {'from': first, 'until': last, 'days': named, 'rows': len(own), 'next': after['build']}, entries)
            final = ended
        else:
            final = shipped
        _write(os.path.join(b['dir'], hotfixes.FILE), final)
        summary[b['build']] = len(own)
    # the newest build: the build as it shipped first, before the caches the tracker downloaded
    shipped = write_cache(blob, newest['build'], base)
    _prepend_newest(newest, shipped, len(base), found, notes_days)
    summary[newest['build']] = sum(1 for w in found.values() if w == 'newest')
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(f'{state_path}.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
        json.dump({'mark': mark, 'rows_mark': rows_mark, 'windows': {str(k): v for k, v in summary.items()},
                   'rows': [[index, window] for index, window in sorted(raw.items()) if window != 'base']}, handle)
    os.replace(f'{state_path}.{os.getpid()}.tmp', state_path)
    hotfixes._loaded.clear()
    told = ', '.join(f'{b}: {n}' for b, n in summary.items() if n)
    return {'code': 0, 'windows': summary, 'message': f'hotfix windows written for {len(chain)} builds ({told or "no dated rows"})'}


def _write(path, blob):
    with open(f'{path}.{os.getpid()}.tmp', 'wb') as handle:
        handle.write(blob)
    os.replace(f'{path}.{os.getpid()}.tmp', path)


def _rebuilt_history(folder, blob, day, records, kind, window, entries=None):
    """The history of an earlier build, written anew: the caches written here only (an earlier build has no download
    of its own: the public cache is only ever the newest build's)."""
    if entries is None:
        entries = []
        old = os.path.join(folder, hotfixes.HISTORY)
        if os.path.isdir(old):
            for entry in hotfixes.history_kept(folder):
                if entry.get(REBUILT):
                    for name in (entry.get('file'), str(entry.get('file', '')).split('.')[0] + '.changelog.json'):
                        try:
                            os.remove(os.path.join(old, name))
                        except (OSError, TypeError):
                            pass
            try:
                os.remove(os.path.join(old, hotfixes.INDEX))
            except OSError:
                pass
    entries = hotfixes.keep(folder, blob, day, records, entries)
    entries[-1][REBUILT] = kind
    if window:
        entries[-1]['window'] = window
    _save_index(folder, entries)
    return entries


def _save_index(folder, entries):
    path = os.path.join(folder, hotfixes.HISTORY, hotfixes.INDEX)
    with open(f'{path}.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
        json.dump(entries, handle, indent=1)
    os.replace(f'{path}.{os.getpid()}.tmp', path)


def _prepend_newest(newest, shipped, records, found, notes_days):
    """The newest build's history: the build as it shipped, then the caches the tracker downloaded (left as they are).
    The first download carries every hotfix sent since the build came out: its window is dated from the notes."""
    folder = newest['dir']
    kept = [e for e in hotfixes.history(folder) if not e.get(REBUILT)]
    digest = hashlib.sha256(shipped).hexdigest()
    name = f"{newest.get('date') or 'shipped'}-{digest[:12]}.bin.gz"
    target = os.path.join(folder, hotfixes.HISTORY, name)
    if not os.path.isfile(target):
        import gzip
        _write(target, gzip.compress(shipped, 6))
    for entry in hotfixes.history_kept(folder):
        if entry.get(REBUILT) and entry.get('file') != name:
            for stale in (entry['file'], entry['file'].split('.')[0] + '.changelog.json'):
                try:
                    os.remove(os.path.join(folder, hotfixes.HISTORY, stale))
                except OSError:
                    pass
    first = {'file': name, 'read': newest.get('date'), 'sha': digest, 'records': records, REBUILT: 'base'}
    if kept:
        start, last, named = _days(newest, None, notes_days)
        kept[0] = dict(kept[0], window={'from': start, 'until': kept[0].get('read'), 'days': [d for d in named if d <= (kept[0].get('read') or '')],
                                        'rows': sum(1 for w in found.values() if w == 'newest'), 'next': None})
    _save_index(folder, [first] + kept)
