"""Reads the Icy Veins mirror the website keeps (app/icyveins.php): data/icyveins/<kind>/<id>.json.gz, one answer of
db.icy-veins.com/wow-forever per NPC, object, quest, item... The analysis never asks Icy Veins itself: Import Icy Veins
(The Forge > Imports) fills the mirror, and this module reads what is there.

Used by the locator: where players' addons saw a creature or an object (addon_points: a UiMap and x/y in thousandths).
A point is where someone talked to it, looted it or saw it, not a spawn: the locator clusters them like Wowhead's.
"""
import gzip
import json
import os

from .config import DATA

FOLDER = os.path.join(DATA, 'icyveins')
KIND = {'npc': 'npc', 'go': 'gameobject'}


def cached(kind, entry, folder=None):
    """The kept answer of an Icy Veins kind ('npc', 'gameobject', ...) and id, or None."""
    base = os.path.join(folder or FOLDER, kind, f'{int(entry)}.json')
    for path, opener in ((base + '.gz', gzip.open), (base, open)):
        if os.path.isfile(path):
            try:
                with opener(path, 'rt', encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return None


def points(kind, entry, folder=None):
    """[(ui_map, u, v), ...] in 0..1 units where players saw a creature ('npc') or an object ('go'); [] when none."""
    data = cached(KIND.get(kind, kind), entry, folder)
    if not data or data.get('missing'):
        return []
    out = []
    for p in (data.get('relations') or {}).get('addon_points') or []:
        try:
            out.append((int(p['ui_map_id']), float(p['x']) / 1000, float(p['y']) / 1000))
        except (KeyError, TypeError, ValueError):
            continue
    return out
