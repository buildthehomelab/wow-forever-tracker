"""Ground height (z) of spawn points, from the server's maps and vmaps, without a game client or a running server.

    python3 tools/height.py <map> <x> <y> [zHint]
    python3 tools/height.py --zone <zone>[:floor] <x%> <y%> [zHint]      (Wowhead's zone id and map percentages)
    python3 tools/height.py --file points.txt                           (- reads standard input)

Options:
    --data <folder>   the server's data folder (maps/, vmaps/ and dbc/<locale>/ inside); default: config.ini [server]
    --floors          also list every surface on that vertical line (terrain, water, each model), top first
    --forge           answer exactly as `.forge height` does (without a hint the core ignores buildings and bridges)
    --json            one JSON object per point instead of tab-separated text

A point file has one point per line, as on the command line: "<map> <x> <y> [zHint]" or
"zone <zone>[:floor] <x%> <y%> [zHint]"; commas work as separators, "#" starts a comment and words after the numbers
are a label printed back with the answer.

Output, one line per point: map, x, y, z (2 decimals, "none" where there is no ground), what the z stands on, the
label. Without a hint the z is the highest surface (terrain, a model or water): right outdoors, wrong under a roof, a
bridge or in a cave. There, give a hint near the floor wanted (a model floor from 3 yards above the hint to 37
below, or the terrain under it, as `.forge height` picks), or read --floors and pick. docs/SPAWNS.md, "Heights without the game".
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# the data folder alone is enough: without config.ini the sample's paths are never used
if not os.environ.get('FOREVER_TRACKER_CONFIG') and not os.path.isfile(os.path.join(HERE, '..', 'config.ini')):
    os.environ['FOREVER_TRACKER_CONFIG'] = os.path.join(HERE, '..', 'config.sample.ini')

from ft.terrain import Terrain, TerrainError  # noqa: E402

NUMBER = re.compile(r'^-?\d+(\.\d+)?$')


def parse(words):
    """{'map' | 'zone', 'floor', 'x', 'y', 'hint', 'label'} of one point, or raises ValueError."""
    words = [w for w in words if w]
    point = {'hint': None, 'label': ''}
    if words and words[0] in ('zone', '--zone'):
        if len(words) < 4:
            raise ValueError('zone <zone>[:floor] <x%> <y%> [zHint]')
        zone, _, floor = words[1].partition(':')
        point.update(zone=int(zone), floor=int(floor or 0), x=float(words[2]), y=float(words[3]))
        rest = words[4:]
    else:
        if len(words) < 3 or not all(NUMBER.match(w) for w in words[:3]):
            raise ValueError('<map> <x> <y> [zHint]')
        point.update(map=int(words[0]), x=float(words[1]), y=float(words[2]))
        rest = words[3:]
    if rest and NUMBER.match(rest[0]):
        point['hint'] = float(rest[0])
        rest = rest[1:]
    point['label'] = ' '.join(rest)
    return point


def read_points(path):
    handle = sys.stdin if path == '-' else open(path, encoding='utf-8-sig')
    points = []
    for number, line in enumerate(handle, 1):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        try:
            points.append(parse(re.split(r'[\s,;]+', line)))
        except ValueError as error:
            raise SystemExit(f'{path}:{number}: {line!r} is not a point ({error})')
    return points


def folders(data):
    """(maps, vmaps, dbc) folders: under --data, else config.ini [server]."""
    if data:
        dbc = os.path.join(data, 'dbc')
        for locale in ('enUS', 'enGB', 'frFR', 'deDE', 'esES', 'esMX', 'ruRU', 'ptBR', 'itIT', 'koKR', 'zhCN', 'zhTW'):
            if os.path.isfile(os.path.join(dbc, locale, 'UiMap.db2')):
                dbc = os.path.join(dbc, locale)
                break
        return os.path.join(data, 'maps'), os.path.join(data, 'vmaps'), dbc
    from ft.config import CONFIG
    return CONFIG.server_path('maps'), CONFIG.server_path('vmaps'), CONFIG.dbc_folder()[0]


def geography(dbc):
    """ft.geo.Geo over the newest client snapshot, else over the server's own DB2 files."""
    from ft import content, db2, geo
    snapshots = content.builds()
    if snapshots:
        return geo.Geo(snapshots[-1]['dir'])
    if not dbc or not os.path.isfile(os.path.join(dbc, 'UiMapAssignment.db2')):
        raise SystemExit(f'zone percentages need the client tables UiMap, UiMapAssignment...: none in {dbc or "(no dbc folder)"} and no snapshot in data/builds')
    read = lambda name: list(db2.Table(os.path.join(dbc, name + '.db2'), name)) if os.path.isfile(os.path.join(dbc, name + '.db2')) else []
    return geo.Geo(None, read)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    parser.add_argument('point', nargs='*', help='<map> <x> <y> [zHint], or with --zone: <x%%> <y%%> [zHint]')
    parser.add_argument('--zone', help="Wowhead's zone id (AreaTable), :floor for a floor of a multi-level map (12:1)")
    parser.add_argument('--file', help='a file of points, one per line (- for standard input)')
    parser.add_argument('--data', help="the server's data folder (maps, vmaps, dbc)")
    parser.add_argument('--floors', action='store_true', help='list every surface under the point')
    parser.add_argument('--forge', action='store_true', help='answer exactly as .forge height does')
    parser.add_argument('--json', action='store_true', help='JSON lines')
    args = parser.parse_args()

    if args.file:
        points = read_points(args.file)
    elif args.point:
        try:
            points = [parse((['zone', args.zone] if args.zone else []) + args.point)]
        except ValueError as error:
            parser.error(f'a point is {error}')
    else:
        parser.error('give a point or --file')

    maps, vmaps, dbc = folders(args.data)
    try:
        terrain = Terrain(maps, vmaps)
    except TerrainError as error:
        raise SystemExit(str(error))
    if not terrain.vmaps:
        print(f'warning: no vmaps in {vmaps or "(none)"}: buildings, bridges and rocks are left out', file=sys.stderr)
    geo = geography(dbc) if any('zone' in p for p in points) else None

    status = 0
    for point in points:
        out = {'label': point['label'], 'hint': point['hint']}
        if 'zone' in point:
            found = geo.wowhead(point['zone'], point['floor'], point['x'], point['y'])
            out.update(zone=point['zone'], floor=point['floor'], percent=[point['x'], point['y']])
            if not found:
                out.update(map=None, x=None, y=None, z=None, on='zone percentages not on any map')
                status = 1
                emit(out, args)
                continue
            out['map'], out['x'], out['y'] = found[0], found[1], found[2]
        else:
            out['map'], out['x'], out['y'] = point['map'], point['x'], point['y']
        try:
            if args.forge:
                z, on = terrain.forge_height(out['map'], out['x'], out['y'], point['hint']), '.forge height'
            else:
                z = terrain.height(out['map'], out['x'], out['y'], point['hint'])
                on = describe(terrain, out, z)
            floors = terrain.floors(out['map'], out['x'], out['y']) if args.floors else None
        except TerrainError as error:
            raise SystemExit(str(error))
        out['z'] = None if z is None else round(z, 2)
        out['on'] = on if z is not None else 'no ground (no map tile here, or a hole)'
        if floors is not None:
            out['floors'] = [{'z': round(f['z'], 2), 'what': f['what']} for f in floors]
        if z is None:
            status = 1
        emit(out, args)
    sys.exit(status)


def describe(terrain, point, z):
    """What a z stands on: terrain, water, a model, or the hint itself (nothing near it)."""
    if z is None:
        return ''
    for floor in terrain.floors(point['map'], point['x'], point['y']):
        if abs(floor['z'] - z) < 0.01:
            return floor['what']
    return 'the hint (no floor near it)'


def emit(out, args):
    if args.json:
        print(json.dumps(out))
        return
    number = lambda v: 'none' if v is None else f'{v:.2f}'
    cells = [str(out['map']) if out['map'] is not None else 'none', number(out['x']), number(out['y']), number(out['z']), out['on'], out['label']]
    if 'floors' in out:
        cells.append('floors: ' + ', '.join(f"{f['z']:.2f} {f['what']}" for f in out['floors']))
    print('\t'.join(cells).rstrip('\t'))


if __name__ == '__main__':
    main()
