"""What the original game's database says about a recipe the realm cannot teach yet.

The source is a pack of cmangos' classic-db (tools/classicdb_pack.py, GPL-3.0): the 1.12 game, not WoW: Forever. It is
the least trusted source there is and is only asked about what nothing else answers: a profession recipe that still
exists in the Forever client (askable), that no trainer, quest or obtainable item of the realm teaches, and that no live recording
names a teacher for. Where Forever kept the original game's recipe, the original game's teacher is the best word left.

    evidence(pack, wanted, teachers, quests) ->
        train     [npc, spell, cost, level, skill line, skill rank, [], 1]   as app/sources.php takes trainers
        changes   quest_template.RewardSpell for quests of the realm that cast nothing at the turn-in
        gossip    [npc, spell]  taught by a line of a creature's conversation (a pack of the first format: counted only)
        talk      [kind, entry, text, recipe, cast, terms]  taught by a line of a creature's ('npc') or an object's ('go')
                  conversation that casts `cast`, with Classic's conditions as plain terms (tools/classicdb_pack.py
                  terms()); the website writes the line, its conditions and the SmartAI that casts the spell
        left      what was not taken, by reason

Classic's trainers and quests name the spell that teaches (10843 teaches Heavy Mageweave Bandage, 10841); the realm's
own learn effects say which recipe that is.
"""
import gzip
import json

FORMATS = (1, 2, 3, 4, 5)   # 2 adds the conversation lines (talk); 3 the drops, vendors and never-given items; 4 the event spawns;
# 5 the creatures it never spawns (never_spawned) and those it spawns only for a world event (event_only)
TERMS = {'skill': 3, 'quest': 2, 'rep': 3, 'level': 2, 'knows': 2, 'lacks': 2}   # a term's kind and its length
NEVER_LEARNED = 3   # SkillLineAbility.AcquireMethod


def load(path):
    """The pack, or ValueError when the file is no pack of this format."""
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        pack = json.load(handle)
    if not isinstance(pack, dict) or pack.get('format') not in FORMATS:
        raise ValueError('not a pack made by tools/classicdb_pack.py')
    for key, width in (('trainers', 6), ('quests', 3), ('gossip', 2)):
        rows = pack.get(key)
        if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) != width or any(not isinstance(v, int) or v < 0 for v in r) for r in rows):
            raise ValueError(f'the pack\'s {key} are not what tools/classicdb_pack.py writes')
    pack['talk'] = [line for line in pack.get('talk') or [] if spoken(line)]
    pack['drops'] = [r for r in pack.get('drops') or [] if isinstance(r, list) and len(r) == 4 and r[0] in ('npc', 'go')
                     and all(isinstance(v, int) and v > 0 for v in r[1:3]) and isinstance(r[3], (int, float)) and 0 < r[3] <= 100]
    pack['sells'] = [r for r in pack.get('sells') or [] if isinstance(r, list) and len(r) == 3 and all(isinstance(v, int) and v >= 0 for v in r) and r[0] and r[1]]
    pack['never_given'] = [i for i in pack.get('never_given') or [] if isinstance(i, int) and i > 0]
    pack['world_drops'] = [i for i in pack.get('world_drops') or [] if isinstance(i, int) and i > 0]
    pack['never_spawned'] = [i for i in pack.get('never_spawned') or [] if isinstance(i, int) and i > 0]
    only = pack.get('event_only') if isinstance(pack.get('event_only'), dict) else {}
    pack['event_only'] = {int(k): [e for e in v if isinstance(e, int) and e > 0] for k, v in only.items()
                          if str(k).isdigit() and int(k) > 0 and isinstance(v, list) and any(isinstance(e, int) and e > 0 for e in v)}
    return pack


def spawning(pack):
    """(never spawned, {creature: [events]}, {event: name}) of the original game, or None for a pack made before
    format 5, which does not say: a pack that cannot tell must not make every creature look summoned."""
    if pack.get('format', 0) < 5:
        return None
    names = {int(e): str(v.get('name') or '') for e, v in (pack.get('holidays') or {}).items() if str(e).isdigit() and isinstance(v, dict)}
    return set(pack['never_spawned']), pack['event_only'], names


def not_spawned(entry, facts):
    """Why the original game would not have this creature stand all year, as a note for the locator; '' when it does,
    or when it does not know the creature. facts: spawning() of a pack."""
    if not facts:
        return ''
    never, only, names = facts
    if entry in never:
        return 'summoned in Classic: a script, a spell or an event brings it (VMaNGOS never spawns it)'
    if entry in only:
        events = ', '.join(f'{e} {names.get(e, "")}'.strip() for e in only[entry])
        return f'event {events} only in Classic'[:250]
    return ''


def taught(pack):
    """Every spell the original game's trainers, quest turn-ins and conversations teach or cast (before the learn
    effects are followed): a spell nothing in it teaches was never a line of anyone's spellbook there."""
    spells = {row[1] for row in pack['trainers']} | {s for row in pack['quests'] for s in row[1:] if s}
    spells |= {row[1] for row in pack['gossip']} | {line[3] for line in pack.get('talk') or []}
    return spells - {0}


def item_sources(pack, gaps):
    """What the original game says about items players cannot get: (drops [[kind, entry, item, chance]], vendors [[npc,
    item, stock]], {left out: count}). gaps: the item IDs. Only items that teach (recipes, items learned on use) are in
    a pack; a world drop of one is left out and counted."""
    drops = [row for row in pack.get('drops') or [] if row[2] in gaps]
    sells = [row for row in pack.get('sells') or [] if row[1] in gaps]
    left = {'classic_world_drop': len(set(pack.get('world_drops') or ()) & set(gaps))}
    return drops, sells, {why: n for why, n in left.items() if n}


def spoken(line):
    """A conversation line of the pack of the right shape: ['npc'|'go', entry, text, spell, [terms]]."""
    if not isinstance(line, list) or len(line) != 5 or line[0] not in ('npc', 'go') or not isinstance(line[2], str) or not isinstance(line[4], list):
        return False
    if not all(isinstance(v, int) and v > 0 for v in (line[1], line[3])) or not 0 < len(line[2]) <= 500:
        return False
    return all(isinstance(t, list) and t and TERMS.get(t[0]) == len(t) and all(isinstance(v, int) and v >= 0 for v in t[1:]) for t in line[4])


def askable(spells, known, acquire):
    """The recipes it makes sense to ask the original game about: the ones WoW: Forever still has. A recipe whose spell
    the server's data no longer holds, or that every skill line marks as never learned, is one Forever took away (the
    old healing potions, replaced by new ones): the original game would hand it back to every trainer.
    spells: {spell: skill line}; known: the server's spells; acquire: {spell: {AcquireMethod of each skill line row}}."""
    return {spell: line for spell, line in spells.items() if spell in known and acquire.get(spell) != {NEVER_LEARNED}}


def evidence(pack, wanted, teachers, quests):
    """wanted: {spell: skill line} of the profession recipes nobody can learn yet. teachers: {spell: {spells that
    teach it}} by the realm's learn effects. quests: {quest: RewardSpell} of the realm's quests the pack names."""
    by_spell = {'trainers': {}, 'quests': {}, 'gossip': {}}
    for npc, spell, cost, line, rank, level in pack['trainers']:
        by_spell['trainers'].setdefault(spell, []).append((npc, cost, line, rank, level))
    for quest, shown, cast in pack['quests']:
        by_spell['quests'].setdefault(cast or shown, []).append(quest)   # the spell the turn-in casts
    for npc, spell in pack['gossip']:
        by_spell['gossip'].setdefault(spell, []).append(npc)
    for kind, entry, text, cast, terms in pack.get('talk', ()):
        by_spell.setdefault('talk', {}).setdefault(cast, []).append((kind, entry, text, terms))

    train, fills, gossip, talk, left = {}, {}, set(), {}, {}

    def count(reason, n=1):
        left[reason] = left.get(reason, 0) + n

    for spell, line in sorted(wanted.items()):
        keys = sorted({spell} | set(teachers.get(spell, ())))
        found = False
        for key in keys:
            for npc, cost, skill, rank, level in by_spell['trainers'].get(key, ()):
                train.setdefault((npc, spell), [npc, spell, cost, level, skill or line, rank, [], 1])
                found = True
        for key in keys:
            for quest in by_spell['quests'].get(key, ()):
                found = True
                if quest not in quests:
                    count('classic_quest_unknown')
                elif quests[quest]:
                    count('classic_quest_casts_already')   # the realm's quest casts a spell at the turn-in: left as it is
                else:
                    fills.setdefault(quest, key)
        for key in keys:
            for kind, entry, text, terms in by_spell.get('talk', {}).get(key, ()):
                if kind != 'npc' or (entry, spell) not in train:
                    talk.setdefault((kind, entry, spell), [kind, entry, text, spell, key, terms])
                found = True
        for key in keys:
            for npc in by_spell['gossip'].get(key, ()):
                if (npc, spell) not in train and ('npc', npc, spell) not in talk:
                    gossip.add((npc, spell))
                found = True
        if not found:
            count('classic_silent')
    if gossip:
        count('classic_conversation', len({spell for _npc, spell in gossip}))
    changes = []
    if fills:
        changes.append({'table': 'quest_template', 'columns': ['ID', 'RewardSpell'], 'match': ['ID'], 'set': 'RewardSpell',
                        'rows': [[quest, spell] for quest, spell in sorted(fills.items())]})
    return {'train': [train[key] for key in sorted(train)], 'changes': changes, 'gossip': sorted(gossip),
            'talk': [talk[key] for key in sorted(talk)], 'left': left}
