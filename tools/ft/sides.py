"""Whose side a creature is on: the server's word against what players saw on the live game (docs/FORGE.md, Checks).

A creature's faction decides who it helps and who it attacks, and whose reputation lowers a vendor's prices. No client
table holds a creature's faction, so nothing so far compared it with anything. EG Link's recordings do not state it
either, but they state what follows from it: how players of each side saw the creature (a reaction, 1 hated to 8
exalted), and which side's players it served (a vendor's window, a quest, a flight). This module puts the two side
by side and names the creatures where they cannot both be right:

    faction   players of a side saw the creature neutral or friendly, or it served them, and on the server its
              faction attacks that side; or they only ever saw it hostile and on the server its faction is their
              friend
    sides     the server shows the creature to one side only (a phase or a condition on the player's team), and
              players of the other side saw it or were served by it on live
    discount  a vendor the recordings show selling to one side only, whose faction on the server is a general one
              (it treats both sides alike and has no reputation behind it): no reputation discount can apply to its
              prices. The weakest of the three: the other side may simply not have come by.

Only a contradiction is named. Neutral against friendly is not one: that depends on the reputation the player who
recorded it had earned. For the same reason a faction players can earn reputation with says nothing either way (a
Gelkis centaur is friendly to the player who earned it and hostile to the next one): such a faction is compared only
where a side's standing is fixed at the bottom, as the Horde's is with Stormwind. A creature nobody spawned is left out (a warlock's demon, a totem: its side is its master's),
and a beast that players only saw friendly is somebody's pet unless it also served them. That a side never recorded a creature says nothing either (nobody of that side went there,
or looked): so a creature the server shows to everyone, which only one side should see, cannot be found this way.

Nothing is changed from here: no source states which faction is the right one. This module reads no database and no
configuration: it is given the recordings and the server's rows.
"""
import collections

ALLIANCE, HORDE = 'Alliance', 'Horde'
SIDES = (ALLIANCE, HORDE)
OTHER = {ALLIANCE: HORDE, HORDE: ALLIANCE}
PLAYERS, GROUP = 1, {ALLIANCE: 2, HORDE: 4}        # FactionTemplate group bits
PLAYER_FACTION = {ALLIANCE: 1, HORDE: 2}           # a human's and an orc's own faction (Faction.db2)
TEAM = {469: ALLIANCE, 67: HORDE}                  # a team condition's value
VENDOR = 128                                       # npcflag
BEAST = 1                                          # creature_template.type
SERVICES = ('Merchant', 'Trainer', 'TaxiNode', 'Binder', 'CharacterBanker', 'Auctioneer', 'QuestGiver')


def stance(template, side):
    """How a faction template stands to players of a side, by the template alone (the core's IsHostileTo and
    IsFriendlyTo, against a player of that side): 'hostile', 'friendly' or 'neutral'. None without the template."""
    if not template:
        return None
    theirs = PLAYER_FACTION[side]
    group = PLAYERS | GROUP[side]
    enemies = {template.get(f'Enemies{i}') for i in range(1, 9)} - {0, None}
    friends = {template.get(f'Friend{i}') for i in range(1, 9)} - {0, None}
    if theirs in enemies:
        return 'hostile'
    if theirs in friends:
        return 'friendly'
    if int(template.get('EnemyGroup') or 0) & group:
        return 'hostile'
    # the creature counts the side among its friends, or it is of the side's own group
    if int(template.get('FriendGroup') or 0) & group or int(template.get('FactionGroup') or 0) & GROUP[side]:
        return 'friendly'
    return 'neutral'


FLOOR = -42000   # a reputation that cannot be earned out of: the other side's cities
RACE = {ALLIANCE: 1, HORDE: 2}   # a human's and an orc's bit in a race mask


def standing(faction, side):
    """The reputation players of a side start at with a faction, or None when the faction has no reputation. faction:
    its Faction row. The core's rule: the first of the faction's four entries that names the side's race; 0 when
    none does."""
    if not faction or int(faction.get('ReputationIndex') if faction.get('ReputationIndex') is not None else -1) < 0:
        return None
    for i in range(1, 5):
        mask = int(faction.get(f'ReputationRaceMask{i}1') or 0) | int(faction.get(f'ReputationRaceMask{i}2') or 0) << 32
        classes = int(faction.get(f'ReputationClassMask{i}') or 0)
        if mask & RACE[side] or (not mask and classes):
            return int(faction.get(f'ReputationBase{i}') or 0)
    return 0


def recorded(facts, live_from):
    """What the recordings of the live game say of each creature: {entry: {'name', 'seen': {side: set of reactions},
    'served': {side: set of services}}}. facts: the facts of a recording (ft.facts.eglink, the creatures and npcs
    datasets); live_from: the first build of the live game."""
    out = collections.defaultdict(lambda: {'name': '', 'seen': {side: set() for side in SIDES}, 'served': {side: set() for side in SIDES}})
    for fact in facts:
        if fact.build < live_from or fact.subject_kind != 'npc' or not isinstance(fact.data, dict):
            continue
        if fact.kind == 'seen':
            entry = out[fact.subject]
            entry['name'] = fact.data.get('name') or entry['name']
            reactions = fact.data.get('reactions')
            for side in SIDES:
                values = reactions.get(side) if isinstance(reactions, dict) else None
                entry['seen'][side].update(v for v in values or [] if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 8)
        elif fact.kind == 'talked' and fact.data.get('side') in SIDES:
            entry = out[fact.subject]
            entry['name'] = fact.data.get('name') or entry['name']
            kinds = fact.data.get('interactions')
            entry['served'][fact.data['side']].update(k for k in kinds if isinstance(k, str)) if isinstance(kinds, list) else None
            entry['served'][fact.data['side']].add('talked')
    return dict(out)


def team_of(conditions):
    """The one side a set of conditions lets through, or None. conditions: rows of the server's `conditions` table for
    one source ({ElseGroup, ConditionTypeOrReference, ConditionValue1, NegativeCondition}); the groups are
    alternatives, so every one of them must ask for the same team."""
    groups = collections.defaultdict(set)
    seen = set()
    for row in conditions:
        seen.add(int(row.get('ElseGroup') or 0))
        if int(row.get('ConditionTypeOrReference') or 0) != 6:
            continue
        side = TEAM.get(int(row.get('ConditionValue1') or 0))
        if side:
            groups[int(row.get('ElseGroup') or 0)].add(OTHER[side] if int(row.get('NegativeCondition') or 0) else side)
    if not seen or set(groups) != seen:
        return None   # no condition, or a way through that asks for no team
    sides = {side for found in groups.values() for side in found}
    return sides.pop() if len(sides) == 1 and all(len(found) == 1 for found in groups.values()) else None


def shown_to(spawns, phase_side, group_side, entry_side=None):
    """The one side a creature is shown to on the server, or None when everyone may see it. spawns: its spawns as
    (phase id, phase group, spawn group); phase_side, group_side: {id: side} of the phases and spawn groups a team
    condition closes to one side; entry_side: the side a visibility condition on the creature itself asks for.
    A creature with a spawn anyone may see is shown to everyone."""
    if entry_side:
        return entry_side
    sides = set()
    for phase, phase_group, spawn_group in spawns:
        side = phase_side.get(phase) or phase_side.get(('group', phase_group)) or group_side.get(spawn_group)
        if not side:
            return None
        sides.add(side)
    return sides.pop() if len(sides) == 1 else None


def _words(values):
    names = {1: 'hated', 2: 'hostile', 3: 'unfriendly', 4: 'neutral', 5: 'friendly', 6: 'honored', 7: 'revered', 8: 'exalted'}
    return ', '.join(names[v] for v in sorted(values))


def compare(live, creatures, templates, factions=None, shown=None):
    """The creatures whose side on the server contradicts the live game: [(entry, name, issue, note)], sorted.

    live: recorded(); creatures: {entry: {'name', 'faction' (a FactionTemplate id), 'npcflag', 'type' (1: a beast),
    'spawned' (0: nobody spawned it; taken as spawned when absent)}} of the server;
    templates: {id: FactionTemplate row}; factions: {id: Faction row} (for 'discount'; without it that check is not
    made); shown: {entry: side} of the creatures the server shows to one side only (shown_to).
    """
    out = []
    counts = collections.Counter()
    for entry in sorted(set(live) & set(creatures)):
        told, ours = live[entry], creatures[entry]
        name = ours.get('name') or told['name'] or ''
        template = templates.get(int(ours.get('faction') or 0))
        if not int(ours.get('spawned') if ours.get('spawned') is not None else 1):
            counts['not_spawned'] += 1
            continue
        counts['compared'] += 1
        beast = int(ours.get('type') or 0) == BEAST
        if template is None:
            counts['no_template'] += 1
            continue
        which = f"faction {int(ours['faction'])}"
        if factions is not None:
            label = (factions.get(int(template.get('Faction') or 0)) or {}).get('Name')
            which += f' ({label})' if label else ''
        notes = []
        faction_row = (factions or {}).get(int(template.get('Faction') or 0))
        earned = False
        for side in SIDES:
            seen, served = told['seen'][side], told['served'][side]
            if not seen and not served:
                continue
            start = standing(faction_row, side)
            if start is not None and start > FLOOR:
                earned = True   # players earn and lose this faction's reputation: what one of them saw says nothing
                continue
            ours_stance = stance(template, side)
            welcome = (seen and min(seen) >= 4 and not (beast and not served)) or (served and not (seen and min(seen) <= 2))
            if welcome and ours_stance == 'hostile':
                how = f'saw it {_words(seen)}' if seen else ''
                if served:
                    how = (how + ' and ' if how else '') + 'were served by it (' + ', '.join(sorted(served - {'talked'}) or ['talked to it']) + ')'
                notes.append(f'{side} players {how} on live; on the server its {which} attacks them')
            elif seen and max(seen) <= 2 and not served and ours_stance == 'friendly':
                notes.append(f'{side} players only saw it {_words(seen)} on live; on the server its {which} is their friend')
        if notes:
            out.append((entry, name, 'faction', '; '.join(notes)))
            counts['faction'] += 1
        elif earned:
            counts['reputation_decides'] += 1
        side_only = (shown or {}).get(entry)
        if side_only:
            other = OTHER[side_only]
            if told['seen'][other] or told['served'][other]:
                what = 'were served by it' if told['served'][other] else f"saw it ({_words(told['seen'][other])})"
                out.append((entry, name, 'sides', f'the server shows it to {side_only} players only; {other} players {what} on live'))
                counts['sides'] += 1
        if factions is not None and int(ours.get('npcflag') or 0) & VENDOR:
            served_sides = [side for side in SIDES if 'Merchant' in told['served'][side]]
            faction = factions.get(int(template.get('Faction') or 0))
            # a general faction: no reputation, and the same to both sides (one side's own faction without a reputation,
            # as the Revantusk trolls', is Blizzard's choice and gives no discount on live either)
            general = standing(faction, ALLIANCE) is None and stance(template, ALLIANCE) == stance(template, HORDE)
            if len(served_sides) == 1 and not told['seen'][OTHER[served_sides[0]]] and general:
                out.append((entry, name, 'discount', f'a vendor the recordings show selling to {served_sides[0]} players only (the other side may not have come by); '
                                                     f'its {which} on the server is a general one without a reputation, so no reputation discount applies to its prices'))
                counts['discount'] += 1
    return out, dict(counts)
