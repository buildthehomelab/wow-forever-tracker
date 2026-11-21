"""Extras: what the server's world holds that the live game does not (The Forge > Extras).

Everything else in the tracker looks for what is missing. This looks the other way, for the rows an import brought in
that live Forever never had: an invented portal, the Classic copy of a creature that Forever replaced, the same NPC
spawned twice on one spot. Absence alone is never a finding here either (that nobody recorded something does not
mean it is gone): each issue needs a witness that says something else stands in its place.

    twin      the server spawns creature A; the live server never sent A's record to a client, but did send the
              record of B, which has the same name. Live uses B (Forever's copy of a Classic creature, as the
              mechanostriders 12363-14553 against 267683-276736). A name is no proof that one creature stands twice
              (chickens, credits and snakes share names across the world), so each of A's spawns is weighed: one
              with a spawn of B within TWIN_YARDS, on its map, in its phase and world events, is the same creature
              shown twice and is listed by its guid, to remove. A's other spawns are listed together, by entry: B
              stands elsewhere (left alone, a person decides) or nowhere (give these spawns B's entry).
    stacked   two spawns of the same name on one map within STACK_YARDS (objects: STACK_YARDS_OBJECT) of each other, in the same phase, neither
              in a pool (a pool's members share a spot on purpose). Two models in one place read as one broken
              creature. Spawns of world events count only beside spawns of the same events (each holiday has its
              own pumpkin on the same spot, never shown together). The spawn to keep is a live entry's, else the
              oldest guid.
    crowded   the server spawns a creature on a map at least CROWD_FACTOR times (plus CROWD_SLACK) as often as
              Wowhead's Forever map shows it there: Wowhead marks every spot it saw, so far more spawns than spots
              is an import's leftovers.
    invented  an entry the server spawns that nothing outside the server knows. A creature: not in the client's
              tables, in no recording of the game (beta or live), and Wowhead's Forever database answers "not found"
              (Wowhead lists every creature). An object is never judged by Wowhead: it lists only the objects
              players use, not a chair, a lamp, a door or a holiday pumpkin, on any of its databases. Any entry from
              CUSTOM_FROM up is the server's own (Blizzard's ids stay far below): a stand-in an import made where the
              real data was missing (the city portals 8380101-8380102, spell focus objects). Listed to find the real
              entry, never to remove: until it is in, removing the stand-in leaves a hole.
    giver     the server has an NPC or object give (or take) a quest that the live game's players saw given (taken)
              only by others. Weaker: a quest with two givers may have had only one recorded.

Nothing is changed from here: the page lists, a person decides. This module reads no database and no configuration:
it is given the rows.
"""
import collections
import math
import re

STACK_YARDS = 1.0             # a creature this close to another of its name stands in it
TWIN_YARDS = 15.0             # an old twin this close to a spawn of its live entry is that creature twice
STACK_YARDS_OBJECT = 0.3      # objects sit close on purpose (chairs at a table, candles): only near-exact copies
CROWD_FACTOR, CROWD_SLACK = 2, 3
CUSTOM_FROM = 1_000_000      # Blizzard's creature and object ids stay below this (Forever's reach about 700,000)
CROWD_MARGIN = 150.0          # yards around Wowhead's points that still count as the same place
ISSUES = ('twin', 'stacked', 'crowded', 'invented', 'giver')

Spawn = collections.namedtuple('Spawn', 'kind guid entry name map x y z phase phase_group events', defaults=((),))
Finding = collections.namedtuple('Finding', 'issue kind entry name guid map x y z server live note')


def normal(name):
    """A name as compared: case, spacing and punctuation do not count."""
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').lower()).strip()


def twins(spawned, names, recorded, spawns=()):
    """Creatures the server spawns that the live game shows under another entry of the same name.
    spawned: {entry: number of spawns}; names: {entry: name} of the server's templates; recorded: {entry: name} of
    the creatures the live server sent records of; spawns: the server's Spawn rows (creatures). Yields Finding rows:
    one per spawn that stands within TWIN_YARDS of a live entry's spawn (its guid set: remove it), and one per entry
    for its other spawns (guid None). Without spawns, one row per entry, as before positions were weighed."""
    live_by_name = collections.defaultdict(set)
    for entry, name in recorded.items():
        if normal(name):
            live_by_name[normal(name)].add(entry)
    by_entry = collections.defaultdict(list)
    for s in spawns:
        if s.kind == 'npc':
            by_entry[s.entry].append(s)
    for entry in sorted(spawned):
        if entry in recorded:
            continue
        live = sorted(live_by_name.get(normal(names.get(entry)), ()))
        if not live:
            continue
        name = names.get(entry) or ''
        has_live = [e for e in live if spawned.get(e)]
        if not has_live:
            yield Finding('twin', 'npc', entry, name, None, None, None, None, None, spawned[entry], live,
                          'the server spawns no live entry: give these spawns the live entry')
            continue
        if not spawns:
            yield Finding('twin', 'npc', entry, name, None, None, None, None, None, spawned[entry], live,
                          'the server spawns ' + ', '.join(map(str, has_live)) + ' as well: remove these')
            continue
        alone = 0
        for s in sorted(by_entry.get(entry, ()), key=lambda s: s.guid):
            place = (s.map, s.phase, s.phase_group, tuple(sorted(s.events)))
            best = None
            for e in has_live:
                for o in by_entry.get(e, ()):
                    if (o.map, o.phase, o.phase_group, tuple(sorted(o.events))) != place:
                        continue
                    d = math.dist((s.x, s.y, s.z), (o.x, o.y, o.z))
                    if d <= TWIN_YARDS and (best is None or d < best[0]):
                        best = (d, o)
            if best is None:
                alone += 1
                continue
            d, o = best
            yield Finding('twin', 'npc', entry, name, s.guid, s.map, s.x, s.y, s.z, 1, [o.entry],
                          f'live entry {o.entry} (guid {o.guid}) stands {d:.1f} yd away: remove this spawn')
        if alone:
            yield Finding('twin', 'npc', entry, name, None, None, None, None, None, alone, has_live,
                          f'no spawn of the live entry within {TWIN_YARDS:g} yd of these {alone}: it stands elsewhere, '
                          'so they are not one creature twice; left alone, check by hand')


def _cell(x, y):
    return int(math.floor(x / STACK_YARDS)), int(math.floor(y / STACK_YARDS))


def stacked(spawns, pooled=frozenset(), live=frozenset()):
    """Spawns of the same name on top of each other. spawns: Spawn rows; pooled: {(kind, guid)} in a pool; live:
    {(kind, entry)} the live game recorded. Yields one Finding per spawn to remove (the one to keep is named)."""
    cells = collections.defaultdict(list)
    for s in spawns:
        if (s.kind, s.guid) in pooled or not normal(s.name):
            continue
        cells[(s.kind, s.map, s.phase, s.phase_group, tuple(sorted(s.events)), normal(s.name)) + _cell(s.x, s.y)].append(s)
    parent = {}

    def root(key):
        while parent.get(key, key) != key:
            key = parent[key]
        return key

    for (kind, map_id, phase, group, events, name, cx, cy), members in cells.items():
        around = [o for i in (-1, 0, 1) for j in (-1, 0, 1) for o in cells.get((kind, map_id, phase, group, events, name, cx + i, cy + j), ())]
        for a in members:
            for b in around:
                if a.guid < b.guid and math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) <= (STACK_YARDS_OBJECT if a.kind == 'go' else STACK_YARDS):
                    parent[root((a.kind, b.guid))] = root((a.kind, a.guid))
    groups = collections.defaultdict(list)
    by_key = {(s.kind, s.guid): s for s in spawns}
    for key in list(parent):
        groups[root(key)].append(by_key[key])
    for key, members in groups.items():
        members = sorted({m.guid: m for m in members + [by_key[key]]}.values(), key=lambda m: m.guid)
        keep = next((m for m in members if (m.kind, m.entry) in live), members[0])
        for m in members:
            if m is keep:
                continue
            same = 'a copy of the same entry' if m.entry == keep.entry else f'entry {m.entry} beside entry {keep.entry}'
            yield Finding('stacked', m.kind, m.entry, m.name, m.guid, m.map, m.x, m.y, m.z, len(members), [keep.entry],
                          f'{same}: keep guid {keep.guid}' + (' (the live entry)' if (keep.kind, keep.entry) in live else ''))


def crowded(spawns, points, names):
    """Creatures spawned far more often than Wowhead's map shows them. spawns: {(entry, map): [(x, y)]}; points:
    {entry: {map: [(x, y)]}} from Wowhead's Forever map; names: {entry: name}. Only spawns within CROWD_MARGIN of
    Wowhead's points are counted (its map shows one zone). Yields one Finding per entry and map."""
    for (entry, map_id), ours in sorted(spawns.items()):
        theirs = (points.get(entry) or {}).get(map_id)
        if not theirs:
            continue
        lo_x, hi_x = min(p[0] for p in theirs) - CROWD_MARGIN, max(p[0] for p in theirs) + CROWD_MARGIN
        lo_y, hi_y = min(p[1] for p in theirs) - CROWD_MARGIN, max(p[1] for p in theirs) + CROWD_MARGIN
        near = sum(1 for x, y in ours if lo_x <= x <= hi_x and lo_y <= y <= hi_y)
        if near >= CROWD_FACTOR * len(theirs) + CROWD_SLACK:
            yield Finding('crowded', 'npc', entry, names.get(entry) or '', None, map_id, None, None, None, near, [len(theirs)],
                          f'{near} spawns on the server where Wowhead marks {len(theirs)}')


def invented(spawned, names, known, wowhead):
    """Entries nothing outside the server knows. spawned: {(kind, entry): spawns}; known: {(kind, entry)} the
    client's tables or any recording hold; wowhead: (kind, entry) -> 'unknown', 'forever', 'season' or None (not
    asked). A creature below CUSTOM_FROM needs Wowhead's 'unknown' (a lookup that did not happen proves nothing); an
    object below it is never listed (Wowhead's silence on objects proves nothing); an entry from CUSTOM_FROM up is a
    stand-in, listed without asking Wowhead. Nothing here is to be removed: see the module's docstring."""
    for (kind, entry), count in sorted(spawned.items()):
        if (kind, entry) in known:
            continue
        if entry >= CUSTOM_FROM:
            note = ("the server's own entry (an id beyond Blizzard's): a stand-in an import made where the real data "
                    'was missing. Keep it until the real entry is found; removing it leaves a hole')
        elif kind == 'npc' and wowhead(kind, entry) == 'unknown':
            note = 'not in the client, never recorded on the game, not on Wowhead (Forever)'
        else:
            continue
        yield Finding('invented', kind, entry, names.get((kind, entry)) or '', None, None, None, None, None, count, [], note)


def givers(server, live, names):
    """Quest givers and enders the live game's players never saw, where they saw others. server: {(kind, giver,
    quest, role)} with role 'gives' or 'takes'; live: the same, recorded on live; names: {(kind, giver): name}.
    Yields one Finding per pair."""
    seen = collections.defaultdict(set)
    for kind, giver, quest, role in live:
        seen[(quest, role)].add((kind, giver))
    for kind, giver, quest, role in sorted(server):
        others = seen.get((quest, role))
        if not others or (kind, giver) in others:
            continue
        live_names = sorted(f'{names.get(o) or o[1]} ({o[0]} {o[1]})' for o in others)
        yield Finding('giver', kind, giver, names.get((kind, giver)) or '', None, None, None, None, None, quest, sorted(o[1] for o in others),
                      f"{'gives' if role == 'gives' else 'takes'} quest {quest} on the server; on live: " + ', '.join(live_names))
