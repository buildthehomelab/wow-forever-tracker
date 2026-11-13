"""The `world` commands of tools/tracker.py: the world build's layers, sources and pins, and the replay of the server's
world into a scratch database (docs/WORLD-BUILD.md)."""
import collections
import os

from . import facts, layers, replay, sqlio
from .config import CONFIG, DATA

LOCK = os.path.join(DATA, 'world', 'layers.lock.json')


def show(registry, lock, write=print):
    pins = lock.get('sources', {})
    for layer in registry.layers:
        write(f"{layer['name']}: {layer['role']}")
        for source in registry.sources.values():
            if source['layer'] != layer['key']:
                continue
            pin = pins.get(source['id'], {})
            version = str(pin.get('version', ''))[:24] or '-'
            write(f"  {source['id']:20} {source['use']:10} {source['licence']:18} witness {source['group']:15} {version}"
                  + (f"  ({pin['error']})" if pin.get('error') else ''))
    if lock.get('written'):
        write(f"pinned {lock['written']}")


def build_database():
    """(database object, scratch database name) of the world build: [build] database, and its own account when
    [build] user is set."""
    name = CONFIG.get('build', 'database', 'ft_world_build')
    if CONFIG.db(name) != name:          # "world" or "tracker" would be read as a key of [database] and land elsewhere
        raise SystemExit(f'[build] database = "{name}" is the name of a setting of [database]: choose another name')
    return sqlio.Account(CONFIG.get('build', 'user'), CONFIG.get('build', 'password')), name


def run_replay(args):
    folders = []
    if args.core:
        folders += [('core updates', os.path.join(args.core, 'sql', 'updates', 'world')), ('core custom', os.path.join(args.core, 'sql', 'custom', 'world'))]
    if args.data:
        folders.append(('data repository', args.data))
    for item in args.folder or []:
        label, _, folder = item.partition('=')
        if not folder:
            raise SystemExit(f'--folder {item}: write it as label=folder')
        folders.append((label, folder))
    if not folders:
        raise SystemExit('nothing to replay: give --core, --data or --folder')
    protected = [CONFIG.db(name) for name in ('tracker', 'world', 'hotfixes', 'auth')]
    db, build = build_database()
    try:
        result = replay.replay(db, build, args.dump, folders, protected, args.keep_going, args.trust_account, print)
    except (replay.ReplayError, RuntimeError) as error:
        raise SystemExit(f'replay: {str(error).strip()}')
    print(f"{result['files']} files, {len(result['failed'])} failed, {result['rows']} rows written by a file")
    for label, made, changed, gone in replay.summary(db, build):
        print(f'  {label:20} created {made:>8}  changed {changed:>8}  removed {gone:>8}')
    if result['failed']:
        raise SystemExit('failed: ' + ', '.join(name for name, _error in result['failed'][:10]))


def run_why(args):
    db, build = build_database()
    try:
        found = replay.why(db, build, args.table, args.key)
    except (replay.ReplayError, RuntimeError) as error:
        raise SystemExit(f'why: {str(error).strip()}')
    print(f"{args.table} ({', '.join(found['key_columns'])}) = {', '.join(args.key)}"
          + ('' if found['exact'] else '   [this table has no unique key: rows sharing these values are told apart no further]'))
    print(f"  from: {found['origin']}")
    acts = {'I': 'inserted', 'U': 'updated', 'D': 'deleted', 'R': 'table created or rebuilt', 'T': 'table emptied',
            'A': 'table altered (its row changes in that file are not followed)'}
    for act, name, source in found['history']:
        print(f'  {acts.get(act, act):9} by {name}  ({source})')
    for act, name, source in found['table_events']:
        print(f'  {acts.get(act, act)} by {name}  ({source})')
    if not found['history'] and not found['table_events']:
        print('  no update file touched it')


def show_facts():
    try:
        sources, kinds = facts.summary(sqlio)
    except RuntimeError as error:
        raise SystemExit(f'facts: {str(error).strip()}')
    if not sources:
        print('no facts loaded yet: tracker.py world facts <source>   (' + ', '.join(sorted(facts.READERS)) + ')')
        return
    for source, pin, licence, allowed, count, left_out, loaded in sources:
        print(f'{source}  {pin[:24]}  {licence}, {allowed}  loaded {loaded}  {count} facts' + (f', {left_out} records left out' if left_out else ''))
        for _source, kind, n, subjects, first, last in (k for k in kinds if k[0] == source):
            print(f'  {kind:10} {n:>8}  about {subjects:>6} things  builds {first} to {last}')


def run_facts(args):
    if not args.source:
        return show_facts()
    registry = layers.load()
    if args.source not in facts.READERS or args.source not in registry.sources:
        raise SystemExit(f'no facts are read from {args.source} yet (sources read: ' + ', '.join(sorted(facts.READERS)) + ')')
    source = registry.source(args.source)
    pin = (layers.read_lock(LOCK).get('sources', {}).get(args.source) or {}).get('version')
    if not pin:
        raise SystemExit(f'{args.source} is not pinned yet: python tools/tracker.py world pin {args.source}')
    folder = os.path.join(DATA, args.source, pin)
    skipped = collections.Counter()
    path = os.path.join(DATA, 'world', f'facts-{args.source}.sql')
    try:
        fetched = facts.FETCHERS[args.source](pin, folder, log=print)
        counts = facts.write_sql(path, args.source, pin, source['licence'], source['use'], facts.READERS[args.source](folder, skipped), skipped)
        if not counts:
            raise facts.SourceError(f'no fact could be read from {folder}')
        sqlio.execute_file(path, 'tracker')
    except (facts.SourceError, RuntimeError) as error:
        raise SystemExit(f'{args.source}: {str(error).strip()}')
    print(f'{fetched} files downloaded, {sum(counts.values())} facts loaded into {CONFIG.db("tracker")}')
    if source.get('credit'):
        print('credit: ' + source['credit'])
    show_facts()


def run(args):
    if args.world_command == 'facts':
        return run_facts(args)
    if args.world_command == 'replay':
        return run_replay(args)
    if args.world_command == 'why':
        return run_why(args)
    registry = layers.load()
    lock = layers.read_lock(LOCK)
    if args.world_command == 'pin':
        only = set(args.sources) or None
        unknown = sorted((only or set()) - set(registry.sources))
        if unknown:
            raise SystemExit('unknown source: ' + ', '.join(unknown) + ' (see: tracker.py world layers)')
        new = layers.pin_all(registry, lock, only)
        layers.write_lock(LOCK, new)
        moved = layers.changed(lock, new)
        show(registry, new)
        print('moved: ' + (', '.join(moved) if moved else 'nothing'))
        failed = sorted(sid for sid, pin in new['sources'].items() if pin.get('error') and (only is None or sid in only))
        if failed:
            raise SystemExit('not reached, previous pin kept: ' + ', '.join(failed))
    else:
        show(registry, lock)
