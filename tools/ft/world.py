"""The `world` commands of tools/tracker.py: the world build's layers, sources and pins (docs/WORLD-BUILD.md)."""
import os

from . import layers
from .config import DATA

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


def run(args):
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
