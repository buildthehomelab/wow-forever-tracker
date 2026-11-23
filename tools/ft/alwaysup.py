"""Always up: creatures that stand in the world all the time when something should bring them in only for a while.

Two kinds, from the server's permanent spawns (on no world event and in no phase) and the spawn audit's reference worlds
(ft.spawnrefs):

    summoned   a script of ours brings the creature in (SmartAI, a summon group, an event script, a summoning spell,
               the core's C++: ft.summons), and no reference keeps it spawned anywhere. Standing for good, it can be
               killed or talked to without its quest, and the script then summons a second one beside it: Witch Doctor
               Unbagwa's gorillas, Ishamuhale, the captives of Undercity's warlock scene.
    holiday    the references spawn the creature only through world events, and either an event of ours already
               holds other spawns of it, or one of those events is a holiday that comes back once a year. Its spawns
               outside any event stand all year: a Midsummer ribbon pole target, Hallow's End bats.

A creature some reference spawns all the time is never listed: its permanent spawn is the game's. The references are
1.12 and 3.3.5 worlds, so a creature WoW Forever added has no reference to ask: a summoned one is still listed, marked
as later, because only our own scripts speak for it.

Nothing is changed from here, and this module reads no database: it is given the rows.
"""
import collections

KINDS = ('summoned', 'holiday')
LATER_FROM = 100_000          # creature ids from here on came after 3.3.5: no reference world can know them

Finding = collections.namedtuple('Finding', 'kind entry name spawns maps guids cause witness later')


def ever_up(refs):
    """{entry: {source, ...}}: the references that keep each creature spawned outside events, on any map."""
    out = {}
    for source, ref in refs.items():
        for (entry, _map), cell in ref.get('counts', {}).items():
            if cell[0] > 0:
                out.setdefault(entry, set()).add(source)
    return out


def summoned(spawns, causes, refs, names=None):
    """Findings of kind 'summoned'. spawns: {entry: [(guid, map)]} of the server's permanent spawns; causes: {entry:
    [what brings it in]} of the creatures something summons; refs: {source: keyed pack} (ft.spawnrefs.keyed)."""
    names, up = names or {}, ever_up(refs)
    for entry in sorted(set(spawns) & set(causes)):
        if up.get(entry):
            continue
        later = entry >= LATER_FROM
        rows = sorted(spawns[entry])
        witness = ('a later creature: no reference to ask' if later
                   else 'none of ' + ', '.join(sorted(refs)) + ' keeps it spawned') if refs else 'no reference loaded'
        yield Finding('summoned', entry, names.get(entry, ''), len(rows), sorted({m for _g, m in rows}),
                      [g for g, _m in rows], '; '.join(sorted(set(causes[entry]))[:8]), witness, later)


def holidays(spawns, gated, refs, names=None):
    """Findings of kind 'holiday'. spawns: {entry: [(guid, map)]} of the server's permanent spawns; gated: {entry:
    {event, ...}} of the server's spawns an event adds; refs: {source: keyed pack}."""
    names, up = names or {}, ever_up(refs)
    for entry in sorted(spawns):
        said = {}
        for source, ref in refs.items():
            for event, name, yearly in ref.get('event_only', {}).get(entry, ()):
                said.setdefault((name or f'event {event}', yearly), set()).add(source)
        if not said or up.get(entry):
            continue
        ours = sorted(gated.get(entry, ()))
        if not ours and not any(yearly for _name, yearly in said):
            continue      # an event of another core's own (Call to Arms battlemasters, the AQ war effort): not a holiday here
        rows = sorted(spawns[entry])
        cause = '; '.join(f"{name} ({', '.join(sorted(sources))})" for (name, _y), sources in sorted(said.items()))
        witness = (f"{len(rows)} outside any event; others on our event {', '.join(map(str, ours))}" if ours
                   else f'{len(rows)} outside any event; the references spawn it only for the holiday')
        yield Finding('holiday', entry, names.get(entry, ''), len(rows), sorted({m for _g, m in rows}),
                      [g for g, _m in rows], cause, witness, entry >= LATER_FROM)


def run(spawns, gated, causes, refs, names=None):
    """Every finding, summoned first: (findings, {kind: count})."""
    found = list(summoned(spawns, causes, refs, names)) + list(holidays(spawns, gated, refs, names))
    return found, collections.Counter(f.kind for f in found)
