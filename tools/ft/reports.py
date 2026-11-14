"""Players' reports as evidence: who gives and takes a quest, who sells an item, what drops it (docs/SOURCES.md).

ForeverChanges (foreverchanges.pro) collects what its players' addon saw on live WoW Forever, over a base of Classic's
data. A pack of its quest and item lists (tools/foreverchanges_pack.py) is read here and turned into the evidence
every source gives the website (app/sources.php): `start`, `end`, `sell`, `drop`.

Two things set it apart from the other sources:

  - **It names things, it does not number them.** "Furmund, Orgrimmar, 50.9 65.3" is a name and a place on a map,
    not a creature entry. A name is matched to the server's creature (or object) of that name that stands there: the
    one whose spawn is nearest the reported place, when it is near enough and no other of that name is about as
    near. A name several creatures share, with nothing to tell them apart, is left out and counted, never guessed.
    A creature nobody spawned is counted too: it is somebody to place, not a row to write.
  - **Not all of it is about Forever.** The site says so itself: its base is Classic's, with what the game server
    answered and what its players saw on top. Only that is taken: a quest marked as seen by players, a drop counted
    in kills (ten at least). A drop given as a bare percentage is Classic's and is left out.
  - **A drop is a creature's own when players saw it more than once, from few creatures.** The first card made on a
    whole world was nine tenths Waylaid Crates: world drops, each listed under some fifty creatures that happened to
    be killed when one fell, nearly always once. One drop is a sighting, not a rate, and an item fifteen different
    creatures drop is nobody's own loot: it belongs to the world's shared tables, which no report describes. Both are
    left out and counted.

This module reads no database and no configuration: it is given the pack and the server's names, spawns and maps.
"""
import collections
import math

FORMAT = 'foreverchanges-pack/1'
MIN_KILLS = 10      # a drop counts from this many kills
MIN_DROPS = 2       # and from this many drops: one is a sighting, not a rate
WORLD_DROP = 15     # an item this many different creatures drop is a world drop, not a creature's own loot
NEAR = 80           # yards: a spawn this close to the reported place is the one
FAR = 300           # yards: the only creature of that name still is, up to here (a patrol, a rough pin)
VENDORS = ('Sold by a vendor', 'Sold by a quartermaster')
DROPS = ('Creature drop', 'From a rare')


def wanted_names(pack):
    """Every NPC or object name the pack's evidence would need, lower case."""
    names = set()
    for quest in pack.get('quests') or []:
        for role in ('start', 'end'):
            for who in quest.get(role) or []:
                if isinstance(who, dict) and who.get('name') and not who.get('item'):
                    names.add(str(who['name']).strip().lower())
    for item in pack.get('items') or []:
        for source in item.get('sources') or []:
            if isinstance(source, dict) and source.get('how') in VENDORS + DROPS and source.get('name'):
                names.add(str(source['name']).strip().lower())
    return names


def zone_name(place):
    """The zone of a "place" as the site writes it: "Rare, Swamp of Sorrows" is the Swamp of Sorrows."""
    place = str(place or '').strip()
    return place.split(', ', 1)[1] if place.startswith('Rare, ') else place


class Matcher:
    """Names to entries. creatures: {lower name: [entry]}; spawns: {entry: [(map, x, y)]}; where: a function (zone,
    x %, y %) -> (map, x, y) or None; box: a function zone -> (map, min x, min y, max x, max y) or None."""

    def __init__(self, creatures, spawns, where, box):
        self.creatures, self.spawns, self.where, self.box = creatures, spawns, where, box

    def find(self, name, zone=None, x=None, y=None):
        """(entry, '') or (None, why): 'name_unknown', 'not_spawned', 'several_same_name', 'position_far'."""
        entries = self.creatures.get(str(name or '').strip().lower()) or []
        if not entries:
            return None, 'name_unknown'
        spawned = [entry for entry in entries if self.spawns.get(entry)]
        if not spawned:
            return None, 'not_spawned'
        zone = zone_name(zone)
        spot = self.where(zone, x, y) if zone and x is not None and y is not None else None
        if spot:
            near = sorted((min((math.hypot(sx - spot[1], sy - spot[2]) for m, sx, sy in self.spawns[entry] if m == spot[0]), default=float('inf')), entry)
                          for entry in spawned)
            best, runner = near[0], near[1] if len(near) > 1 else None
            if best[0] <= NEAR and (runner is None or runner[0] > max(2 * best[0], NEAR)):
                return best[1], ''
            if len(spawned) == 1:
                return (best[1], '') if best[0] <= FAR else (None, 'position_far')
            return None, 'several_same_name'
        if len(spawned) == 1:
            return spawned[0], ''
        frame = self.box(zone) if zone else None
        if frame:
            inside = [entry for entry in spawned
                      if any(m == frame[0] and frame[1] <= sx <= frame[3] and frame[2] <= sy <= frame[4] for m, sx, sy in self.spawns[entry])]
            if len(inside) == 1:
                return inside[0], ''
        return None, 'several_same_name'


ALLIANCE, HORDE = 'Alliance', 'Horde'
RACES = {ALLIANCE: 1 | 4 | 8 | 64, HORDE: 2 | 16 | 32 | 128}     # the eight races every version has, as race mask bits
RACE_SIDE = {'human': ALLIANCE, 'dwarf': ALLIANCE, 'night elf': ALLIANCE, 'gnome': ALLIANCE,
             'orc': HORDE, 'undead': HORDE, 'tauren': HORDE, 'troll': HORDE}


def side_of(text):
    """The sides a quest is for, as the site words it: {'Alliance'}, {'Horde'} or both. "Night Elf" is the
    Alliance's, a list of races the sides of those races; anything else says nothing (an empty set)."""
    text = str(text or '').strip().lower()
    if text in ('alliance', 'horde'):
        return {text.capitalize()}
    if text == 'both factions':
        return {ALLIANCE, HORDE}
    found = {RACE_SIDE.get(part.strip()) for part in text.split(',')}
    return set() if None in found else found


def allowed_sides(mask):
    """The sides a server's AllowableRaces lets take a quest. 0 and "every bit" are everyone."""
    try:
        mask = int(mask or 0)
    except (TypeError, ValueError):
        return {ALLIANCE, HORDE}
    if mask <= 0 or mask >= 2 ** 63:
        return {ALLIANCE, HORDE}
    return {side for side, bits in RACES.items() if mask & bits}


def quest_sides(pack):
    """{quest: the sides it is for} for the quests the site's players saw. A quest nobody saw carries Classic's
    side, which is no word on Forever, and one whose side cannot be read is left out."""
    out = {}
    for quest in (pack or {}).get('quests') or []:
        if isinstance(quest, dict) and quest.get('seen_by_players') and isinstance(quest.get('id'), int):
            sides = side_of(quest.get('side'))
            if sides:
                out[quest['id']] = sides
    return out


def places(pack, known, spawned, named=None, area_map=None):
    """Where the site's maps show things nobody spawned on the server: [[kind, entry, name, [{m, x, y}]]], and what
    was left out. They are for the locator (the Spawns page), which prefers a reported place to a looked-up one.

    known: the creature entries the server has a template of; spawned: {('npc'|'go', entry)} that stand somewhere;
    named: a function (kind 'npc'|'go', lower name) -> [entries] for the pins the site gives by name (rares,
    commerce NPCs, library books); area_map: a function area id -> map id, for a map folder that is one area.
    An NPC of the site's maps counts when its players' addon saw it ("seen"): the others are QuestieDB's list, which
    the tracker reads itself."""
    found, left = {}, collections.Counter()

    def add(kind, entry, name, map_id, x, y):
        if (kind, entry) in spawned:
            left['report_place_already_spawned'] += 1
            return
        points = found.setdefault((kind, entry), [name, []])[1]
        point = {'m': int(map_id), 'x': round(float(x), 1), 'y': round(float(y), 1)}
        if point not in points and len(points) < 20:
            points.append(point)

    for npc in (pack or {}).get('npcs') or []:
        if not isinstance(npc, dict) or not npc.get('seen'):
            continue
        entry = npc.get('entry')
        if not isinstance(entry, int) or entry not in known:
            left['report_place_unknown_creature'] += 1
            continue
        add('npc', entry, str(npc.get('name') or ''), npc.get('map', 0), npc.get('x', 0), npc.get('y', 0))
    for pin in (pack or {}).get('pins') or []:
        if not isinstance(pin, dict) or named is None:
            continue
        map_id = pin.get('map') if pin.get('map') is not None else (area_map(pin.get('area')) if area_map and pin.get('area') else None)
        if map_id is None:
            left['report_place_no_map'] += 1
            continue
        kind = 'go' if pin.get('kind') == 'book' else 'npc'
        entries = named(kind, str(pin.get('name') or '').strip().lower())
        if len(entries) != 1:
            left['report_place_name_unknown' if not entries else 'report_several_same_name'] += 1
            continue
        add(kind, entries[0], str(pin['name']), map_id, pin.get('x', 0), pin.get('y', 0))
    return [[kind, entry, name, points] for (kind, entry), (name, points) in sorted(found.items()) if points], dict(left)


def evidence(pack, npcs, objects=None):
    """(evidence, left): the pack's claims as the website's evidence, and what was left out and why.

    npcs, objects: Matchers for creatures and for world objects (objects may be None). Evidence: {'start': [[kind,
    entry, quest]], 'end': the same, 'sell': [[npc, item, 0]], 'drop': [['npc', entry, item, chance %]]}.
    """
    if not isinstance(pack, dict) or pack.get('format') != FORMAT:
        raise ValueError(f'not a {FORMAT} file (tools/foreverchanges_pack.py makes one)')
    ev = {'start': [], 'end': [], 'sell': [], 'drop': []}
    left = collections.Counter()

    def who(record, zone_key='zone'):
        entry, why = npcs.find(record.get('name'), record.get(zone_key), record.get('x'), record.get('y'))
        if entry:
            return 'npc', entry, ''
        if objects is not None and why == 'name_unknown':
            entry, other = objects.find(record.get('name'), record.get(zone_key), record.get('x'), record.get('y'))
            if entry:
                return 'go', entry, ''
            why = other if other != 'name_unknown' else why
        return None, None, why

    for quest in pack.get('quests') or []:
        quest_id = quest.get('id')
        if not isinstance(quest_id, int) or isinstance(quest_id, bool) or quest_id <= 0:
            continue
        if not quest.get('seen_by_players'):
            left['report_quest_not_seen'] += 1
            continue
        for role in ('start', 'end'):
            for record in quest.get(role) or []:
                if not isinstance(record, dict) or not record.get('name'):
                    continue
                if record.get('item'):
                    left['report_quest_started_by_item'] += 1
                    continue
                kind, entry, why = who(record)
                if entry:
                    ev[role].append([kind, entry, quest_id])
                else:
                    left['report_' + why] += 1
    seen_sell, drops = set(), {}
    for item in pack.get('items') or []:
        item_id = item.get('id')
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            continue
        droppers = {str(s.get('name') or '').strip().lower() for s in item.get('sources') or [] if isinstance(s, dict) and s.get('how') in DROPS}
        world_drop = len(droppers) >= WORLD_DROP
        for source in item.get('sources') or []:
            how = source.get('how') if isinstance(source, dict) else None
            if how in VENDORS:
                entry, why = npcs.find(source.get('name'), source.get('place'), source.get('x'), source.get('y'))
                if not entry:
                    left['report_' + why] += 1
                elif (entry, item_id) not in seen_sell:
                    seen_sell.add((entry, item_id))
                    ev['sell'].append([entry, item_id, 0])
            elif how in DROPS:
                rate = source.get('rate') if isinstance(source.get('rate'), dict) else {}
                kills, count = rate.get('kills'), rate.get('drops')
                if not isinstance(kills, (int, float)) or not isinstance(count, (int, float)) or isinstance(kills, bool) or isinstance(count, bool):
                    left['report_drop_not_counted'] += 1      # a bare percentage: Classic's, not what players counted
                    continue
                if world_drop:
                    left['report_drop_world'] += 1
                    continue
                if kills < MIN_KILLS or count <= 0:
                    left['report_drop_few_kills'] += 1
                    continue
                if count < MIN_DROPS:
                    left['report_drop_seen_once'] += 1
                    continue
                entry, why = npcs.find(source.get('name'), source.get('place'))
                if not entry:
                    left['report_' + why] += 1
                    continue
                drops[entry, item_id] = max(drops.get((entry, item_id), 0), round(min(100.0, 100.0 * count / kills), 4))
    ev['drop'] = [['npc', entry, item_id, chance] for (entry, item_id), chance in sorted(drops.items())]
    for role in ('start', 'end'):
        ev[role] = sorted({tuple(row) for row in ev[role]})
        ev[role] = [list(row) for row in ev[role]]
    ev['sell'].sort()
    return ev, dict(left)
