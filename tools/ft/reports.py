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

This module reads no database and no configuration: it is given the pack and the server's names, spawns and maps.
"""
import collections
import math

FORMAT = 'foreverchanges-pack/1'
MIN_KILLS = 10      # a drop counts from this many kills
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
                if kills < MIN_KILLS or count <= 0:
                    left['report_drop_few_kills'] += 1
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
