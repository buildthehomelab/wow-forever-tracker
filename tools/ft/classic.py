"""What the original game's database says about a recipe the realm cannot teach yet.

The source is a pack of cmangos' classic-db (tools/classicdb_pack.py, GPL-3.0): the 1.12 game, not WoW: Forever. It is
the least trusted source there is and is only asked about what nothing else answers: a profession recipe that exists
in the Forever client, that no trainer, quest or obtainable item of the realm teaches, and that no live recording
names a teacher for. Where Forever kept the original game's recipe, the original game's teacher is the best word left.

    evidence(pack, wanted, teachers, quests) ->
        train     [npc, spell, cost, level, skill line, skill rank, [], 1]   as app/sources.php takes trainers
        changes   quest_template.RewardSpell for quests of the realm that cast nothing at the turn-in
        gossip    [npc, spell]  taught by a line of a creature's conversation: a script, not a row; counted, not written
        left      what was not taken, by reason

Classic's trainers and quests name the spell that teaches (10843 teaches Heavy Mageweave Bandage, 10841); the realm's
own learn effects say which recipe that is.
"""
import gzip
import json

FORMAT = 1


def load(path):
    """The pack, or ValueError when the file is no pack of this format."""
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        pack = json.load(handle)
    if not isinstance(pack, dict) or pack.get('format') != FORMAT:
        raise ValueError('not a pack made by tools/classicdb_pack.py')
    for key, width in (('trainers', 6), ('quests', 3), ('gossip', 2)):
        rows = pack.get(key)
        if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) != width or any(not isinstance(v, int) or v < 0 for v in r) for r in rows):
            raise ValueError(f'the pack\'s {key} are not what tools/classicdb_pack.py writes')
    return pack


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

    train, fills, gossip, left = {}, {}, set(), {}

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
            for npc in by_spell['gossip'].get(key, ()):
                if (npc, spell) not in train:
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
    return {'train': [train[key] for key in sorted(train)], 'changes': changes, 'gossip': sorted(gossip), 'left': left}
