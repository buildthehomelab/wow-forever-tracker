"""Spawn audit: how many of each creature the server's world holds, against the worlds of other cores.

Two numbers per creature and map, and they are not the same thing:

    spots     the places a creature can stand: one per spawn row that names it. A row that picks among several
              creatures (VMaNGOS' id, id2..id5; a TrinityCore pool of one) is a spot of each of them.
    up        how many stand at one time. A spawn outside any pool counts 1. A pool shows `max_limit` of its members,
              so each member counts max_limit / members (a pool inside a pool multiplies the two); a row that picks
              among N creatures counts 1/N for each. A world with 12 spots in a pool of 6 has 12 spots and 6 up.

Spawns a world event adds are left out on both sides (a holiday's pumpkin stands a few days a year). A spawn an
event only removes is counted: Pyrewood Village's day guards stand all day and leave for the night's worgen.
A spawn whose creature a script picks when it spawns (the four colours of Blackwing Lair's whelps, stored as one
entry) is counted as a spot of each of them: picked(), from tools/world/spawn_picks.json.

The references are other cores' worlds, each of its own era (ft.spawnrefs): VMaNGOS is the game at patch 1.12,
AzerothCore and TrinityCore 3.3.5 the game at 3.3.5, where some zones were rebuilt and hold more. None of them is WoW
Forever, so a difference alone proves nothing; what counts is where they stand together:

    above_all      more up than every reference that knows the creature on that map: no era of the game had that
                   many. An import laid a second spawn set over the first.
    above_classic  more than VMaNGOS, but a later core has as many: the later game's numbers. Right only where
                   Forever uses the later zone.
    below_all      fewer than every reference, the 1.12 one among them: spawns are missing, or Forever replaced the
                   creature. Fewer than a later core alone is not listed.
    ok             within the references.
    unknown        no reference knows the creature on that map (Forever's own, or a later creature).

Each of the server's spawns is also matched to the references' spots (MATCH_YARDS): `unmatched` is how many stand
where no reference has that creature, and for an above_all creature those are the rows to look at first.

Nothing is changed from here, and this module reads no database and no file: it is given the rows.
"""
import collections
import math

MATCH_YARDS = 5.0             # a server spawn this close to a reference's spot of the same creature is that spot
ABOVE_FACTOR, ABOVE_SLACK = 1.25, 2     # "more than": past factor x the reference plus slack (wandering imports, a few hand fixes)
BELOW_FACTOR, BELOW_SLACK = 0.75, 2
POOL_DEPTH = 6                # pools inside pools: no world nests deeper, and a loop must end
VERDICTS = ('above_all', 'above_classic', 'below_all', 'ok', 'unknown')
CLASSIC = 'vmangos'           # the reference of the 1.12 game (above_classic is measured against it)

Row = collections.namedtuple('Row', 'guid entries map x y z')
Audit = collections.namedtuple('Audit', 'entry map spots up refs verdict unmatched later guids note')


class Pools:
    """The pools of one world. limits: {pool: max_limit}; of_spawn: {guid: pool}; of_entry: {entry: pool} (MaNGOS'
    pool_creature_template: every spawn of that creature is in the pool); mothers: {pool: the pool it is in}."""

    def __init__(self, limits=None, of_spawn=None, of_entry=None, mothers=None):
        self.limits, self.of_spawn = dict(limits or {}), dict(of_spawn or {})
        self.of_entry, self.mothers = dict(of_entry or {}), dict(mothers or {})
        self.members = collections.Counter(self.of_spawn.values())
        self.members.update(self.mothers.values())

    def bind(self, rows):
        """Counts the spawns that are in a pool through their creature (of_entry): call once, with every row."""
        if self.of_entry:
            for row in rows:
                if row.guid not in self.of_spawn and len(row.entries) == 1 and row.entries[0] in self.of_entry:
                    self.members[self.of_entry[row.entries[0]]] += 1
        return self

    def pool(self, row):
        found = self.of_spawn.get(row.guid)
        if found is None and len(row.entries) == 1:
            found = self.of_entry.get(row.entries[0])
        return found

    def share(self, row):
        """The part of `row` that stands at one time: 1 outside pools."""
        part, pool, depth = 1.0, self.pool(row), 0
        while pool is not None and depth < POOL_DEPTH:
            limit, members = self.limits.get(pool, 0), self.members.get(pool, 0)
            if 0 < limit < members:
                part *= limit / members
            pool, depth = self.mothers.get(pool), depth + 1
        return part


def picked(rows, picks):
    """rows with the entries the core may spawn in their place. picks: [{'map', 'stored', 'picks': [entries]}]: a
    spawn that stores `stored` on `map` becomes one of `picks` when it spawns (a script chooses), so it is a spot of
    each of them and a share of one up, as a spot that lists several creatures is."""
    swaps = {}
    for pick in picks or ():
        try:
            entries = tuple(int(e) for e in pick['picks'])
            if entries:
                swaps[(int(pick['map']), int(pick['stored']))] = entries
        except (KeyError, TypeError, ValueError):
            continue
    if not swaps:
        return list(rows)
    return [row._replace(entries=swaps[(row.map, row.entries[0])]) if len(row.entries) == 1 and (row.map, row.entries[0]) in swaps else row
            for row in rows]


def count(rows, pools=None, events=()):
    """{(entry, map): [spots, up]} of a world. rows: Row; pools: Pools; events: the guids of world-event spawns."""
    rows = [r for r in rows if r.guid not in events and r.entries]
    pools = (pools or Pools()).bind(rows)
    out = {}
    for row in rows:
        part = pools.share(row) / len(row.entries)
        for entry in row.entries:
            cell = out.setdefault((entry, row.map), [0, 0.0])
            cell[0] += 1
            cell[1] += part
    return out


def places(rows, events=()):
    """{(entry, map): [(x, y, z)]} of a world's spots, for matching."""
    out = {}
    for row in rows:
        if row.guid in events:
            continue
        for entry in row.entries:
            out.setdefault((entry, row.map), []).append((row.x, row.y, row.z))
    return out


def _grid(points, cell=MATCH_YARDS):
    grid = collections.defaultdict(list)
    for p in points:
        grid[(math.floor(p[0] / cell), math.floor(p[1] / cell))].append(p)
    return grid


def _near(grid, point, cell=MATCH_YARDS):
    gx, gy = math.floor(point[0] / cell), math.floor(point[1] / cell)
    return any(math.dist(point, other) <= cell
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for other in grid.get((gx + dx, gy + dy), ()))


def verdict(up, refs):
    """One of VERDICTS. up: the server's number; refs: {source: up} of the references that know the creature there."""
    known = {source: n for source, n in refs.items() if n > 0}
    if not known:
        return 'unknown'
    if up > max(known.values()) * ABOVE_FACTOR + ABOVE_SLACK:
        return 'above_all'
    if CLASSIC in known and up > known[CLASSIC] * ABOVE_FACTOR + ABOVE_SLACK:
        return 'above_classic'
    # fewer than a later core alone is no gap: the 1.12 world never had the creature there (a later trigger, a later camp)
    if refs.get(CLASSIC, 1) > 0 and up < min(known.values()) * BELOW_FACTOR - BELOW_SLACK:
        return 'below_all'
    return 'ok'


def audit(rows, pools, events, refs, maps=None):
    """Audit rows, one per creature and map the server or the Classic reference spawns. rows, pools, events: the
    server's world (Row, Pools, guids); refs: {source: {'counts': {(entry, map): [spots, up]}, 'places': {(entry,
    map): [(x, y, z)]}}} (ft.spawnrefs.keyed()); maps: only these maps (default: the maps the server spawns on)."""
    rows = [r for r in rows if r.guid not in events and r.entries]
    ours = count(rows, pools)
    if maps is None:
        maps = {m for _entry, m in ours}
    by_key = {}
    for row in rows:
        for entry in row.entries:
            by_key.setdefault((entry, row.map), []).append(row)
    keys = set(ours) | {k for k in (refs.get(CLASSIC) or {}).get('counts', {}) if k[1] in maps}
    for key in sorted(k for k in keys if k[1] in maps):
        spots, up = ours.get(key, [0, 0.0])
        theirs = {source: list(ref['counts'].get(key, (0, 0.0))) for source, ref in refs.items()}
        said = verdict(up, {source: n[1] for source, n in theirs.items()})
        classic = _grid((refs.get(CLASSIC) or {}).get('places', {}).get(key, ()))
        later = _grid([p for source, ref in refs.items() if source != CLASSIC for p in ref.get('places', {}).get(key, ())])
        alone, only_later = [], 0
        if said != 'unknown':
            for row in by_key.get(key, ()):
                point = (row.x, row.y, row.z)
                if _near(classic, point):
                    continue
                if _near(later, point):
                    only_later += 1
                else:
                    alone.append(row.guid)
        known = [f'{source} {n[0]} spots, {n[1]:.4g} up' for source, n in sorted(theirs.items()) if n[0]]
        note = f'{spots} spots, {up:.4g} up on the server; ' + ('; '.join(known) if known else 'no reference has it here')
        yield Audit(key[0], key[1], spots, round(up, 2), {s: [n[0], round(n[1], 2)] for s, n in theirs.items()}, said,
                    len(alone), only_later, sorted(alone), note)
