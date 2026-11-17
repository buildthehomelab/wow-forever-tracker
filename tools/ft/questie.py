"""Where QuestieDB says creatures and objects stand on Forever, for the locator.

QuestieDB's Forever corrections give an NPC or an object its `spawns`: {zone (AreaTable id): {{x%, y%}, ...}}, on
that zone's map like Wowhead's points. Two parts of it say where something stands:
    trace   what players' QuestieTrace recordings showed on live Forever (hundreds of thousands of uploads)
    fix     a correction written by hand
The generated part is built from Wowhead's pages and adds nothing beside Wowhead; the converted Classic base says
where things stood in Classic. Neither is read here.

The files are those of the pinned QuestieDB (`tracker.py world pin questie`: the commit of its newest release),
downloaded once into data/questie/<commit>.
"""
import os
import re

from . import facts, layers, luadata
from .config import DATA

KINDS = {'npc': 'npc', 'object': 'go'}
PARTS = ('trace', 'fix')
LOCK = os.path.join(DATA, 'world', 'layers.lock.json')
# the names hand fixes give zones (zoneIDs.ELWYNN_FOREST): AreaTable ids
ZONES = 'src/corrections/enum/zones.lua'


def pinned_folder(fetch=True, log=lambda message: None, resolve=layers.resolve):
    """The folder of the pinned QuestieDB, its files downloaded when `fetch`. Without a pin (the container never runs
    `world pin`) the commit of QuestieDB's newest release, looked up when `fetch`; else the newest folder already
    downloaded. None when there is none."""
    pin = (layers.read_lock(LOCK).get('sources', {}).get('questie') or {}).get('version')
    if not pin and fetch:
        try:
            pin = (resolve(layers.load().source('questie')['pin']) or {}).get('version')
        except (OSError, LookupError, ValueError, KeyError) as error:
            log(f'locator: QuestieDB\'s newest release cannot be read ({error})')
    if not pin:
        kept = os.path.join(DATA, 'questie')
        folders = [f for f in os.listdir(kept) if re.fullmatch(r'[0-9a-f]{40}', f)] if os.path.isdir(kept) else []
        if not folders:
            return None
        pin = max(folders, key=lambda f: os.path.getmtime(os.path.join(kept, f)))
    folder = os.path.join(DATA, 'questie', pin)
    if fetch:
        facts.fetch_questie(pin, folder, log=log)
        target = os.path.join(folder, ZONES)
        if not os.path.isfile(target):
            try:
                body = facts.http_bytes(f'https://raw.githubusercontent.com/{facts.QUESTIE_REPO}/{pin}/{ZONES}')
            except OSError as error:
                raise facts.SourceError(f'QuestieDB {ZONES} could not be downloaded ({error})') from None
            if not zone_ids(body.decode('utf-8', 'replace')):
                raise facts.SourceError(f'QuestieDB {ZONES} names no zone')
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target + '.part', 'wb') as handle:
                handle.write(body)
            os.replace(target + '.part', target)
    return folder


def zone_ids(text):
    """{NAME: AreaTable id} of QuestieDB's zones.lua, also under 'zoneIDs.NAME' (a table key keeps only the last
    part of a name; a value keeps it whole)."""
    found = {name: int(number) for name, number in re.findall(r'^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\d+)\s*,', text, re.M)}
    return {**found, **{'zoneIDs.' + name: number for name, number in found.items()}}


def _points(value, zones):
    """[(zone, x%, y%), ...] of a `spawns` value. A table whose zones happen to be 1, 2, 3 ... reads as a list; a zone
    named (zoneIDs.NAME) is looked up in `zones`, one it does not know is left out. Points below zero are Questie's
    marks for "inside an instance", not places."""
    if isinstance(value, list):
        value = {str(i): v for i, v in enumerate(value, 1)}
    if not isinstance(value, dict):
        return []
    out = []
    for zone, spots in value.items():
        try:
            zone = int(zones.get(zone, zone))
        except (TypeError, ValueError):
            continue
        for spot in (spots if isinstance(spots, list) else []):
            if (isinstance(spot, list) and len(spot) >= 2 and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in spot[:2])
                    and 0 <= spot[0] <= 100 and 0 <= spot[1] <= 100):
                out.append((zone, float(spot[0]), float(spot[1])))
    return out


def spawns(folder):
    """{(kind, entry): {part: [(zone, x%, y%), ...]}} with kind 'npc' or 'go', of the trace and fix files."""
    found = {}
    if not folder:
        return found
    try:
        with open(os.path.join(folder, ZONES), encoding='utf-8') as handle:
            zones = zone_ids(handle.read())
    except OSError:
        zones = {}
    for path, (entity, part) in facts.QUESTIE_FILES.items():
        if entity not in KINDS or part not in PARTS:
            continue
        try:
            with open(os.path.join(folder, path), encoding='utf-8') as handle:
                tables = luadata.tables(handle.read())
        except OSError:
            continue
        for function, table in tables.items():
            if ':' not in function or 'Dynamic' in function:
                continue
            if isinstance(table, list):
                table = {str(i): e for i, e in enumerate(table, 1)}
            if not isinstance(table, dict):
                continue
            for key, entry in table.items():
                if not isinstance(entry, dict) or 'spawns' not in entry:
                    continue
                try:
                    entry_id = int(key)
                except (TypeError, ValueError):
                    continue
                points = _points(entry['spawns'], zones)
                if points:
                    found.setdefault((KINDS[entity], entry_id), {})[part] = points
    return found
