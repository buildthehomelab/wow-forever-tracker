"""An NPC's template rows, from the record the server sent to a client of the live game.

The record (EG Link's `creatures` data) is what the client's creature cache holds: name, title, kind, class, models
and a few multipliers. That is what an NPC looks like, not all the server knows of it. This module turns one record
into rows, and is plain about the three things no record holds:

- **its level** comes from a source that states it (QuestieDB's entry, or the levels players saw it at);
- **its faction** is a stand-in by side. No source states an NPC's faction id. What is recorded is whom it is
  friendly to (see `side`), and the row gets the generic faction of that side: 84 for the Alliance, 83 for the Horde,
  35 for both. A quest giver or a vendor then works for the players it should; which city's guards defend it and
  whose reputation it is tied to is not known, and an NPC of one side is an enemy of the other;
- **what it does** (quest giver, vendor) is not written here: the rows that give it a quest or an item set its flag.

Only an NPC that players were seen to treat as a friend is written: one they talked to, or one that greeted a side
as a friend and was never fought. A monster needs what no source in the build states: how hard it hits, its armour,
its loot.

How the mapping was checked: for the 600 NPCs the replayed world holds from a recording of build 70124 or later that
EG Link also recorded, the rows made here were compared with the world's. Name, title, classification, type, family
and class agree on 97 to 100 %, the models on 597, the health and mana modifiers on 593 and 600.

    creature_template               name, subname (the title), IconName (the cursor), Classification, type, family,
                                    unit_class, movementId, KillCredit1/2 (the creatures it counts as)
      constants of every NPC recorded on Forever: BaseAttackTime 2000, RangeAttackTime 2000, unit_flags2 2048
      the stand-in: faction (by side)
    creature_template_difficulty    DifficultyID 0: HealthModifier, ManaModifier, CreatureDifficultyID, TypeFlags (3)
    creature_template_model         CreatureDisplayID, DisplayScale, Probability, in the record's order
    creature_classic_level          level_min, level_max

Every row carries VerifiedBuild 0 where the table has the column.
"""
import collections

MAX32 = 2 ** 32 - 1
FACTION_OF_SIDE = {'A': 84, 'H': 83, 'AH': 35}             # Alliance Generic, Horde Generic, Friendly
ATTACK_TIME, UNIT_FLAGS2 = 2000, 2048
CLASSES = (1, 2, 4, 8)                                     # warrior, paladin, rogue, mage: the classes a creature can have
NEUTRAL = 4                                                # the reaction of what is neither friend nor foe: a deer, a goblin town's guard
READ = frozenset(('name', 'title', 'cursor', 'classification', 'type', 'family', 'unitClass', 'movementInfoId', 'proxyCreatureIds', 'displays',
                  'hpMultiplier', 'energyMultiplier', 'creatureDifficultyId', 'flags', 'sources', 'totalProbability'))
# What an NPC's rows do not hold. Listed in each export's manifest.
LEFT = ('creature_template.faction is a stand-in by side (84 Alliance, 83 Horde, 35 both): no source states the faction id',
        'creature_template.npcflag beyond what the rows that give it a quest or an item set (gossip, trainer, innkeeper, repair, flight master)',
        'creature_template speeds, unit_flags, scripts and AI; creature_template_difficulty armour and damage modifiers, loot, gold, ContentTuningID',
        'creature (where it stands: no spawn is written), creature_template_addon, creature_equip_template, gossip, trainer and text tables',
        'what else a record carries (the items it drops for quests, a female name, other names): creature_questitem and the rest. '
        'An NPC whose record has any names the fields under "unread"')

Npc = collections.namedtuple('Npc', 'template difficulty models level unread')


def _number(value, high=MAX32, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _factor(value, high=1e6):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= high


def _text(value):
    if not isinstance(value, str) or '\x00' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def side(stated, reactions, talked=None, fought=False, against=()):
    """('A', 'H', 'AH' or '', whose word it is or why not) for an NPC: whom it is friendly to.

    An NPC is friendly when players were seen to treat it as one, never on a list's word alone:

    - `talked`: a player opened its window (quest, goods, gossip) on the live game. None when nobody was seen to;
      else the side the recording gives the NPC ('Alliance', 'Horde'), or '' when it gives none;
    - `reactions`: {'Alliance': [reaction, ...], 'Horde': [...]} as players of each side saw it (1 hated, 4 neutral,
      5 friendly ... 8 exalted). A side that saw it friendly and never below neutral is its friend. Neutral alone
      says nothing: a deer is neutral;
    - `stated`: QuestieDB's friendlyToFaction. It names the side of an NPC players talked to when the recording does
      not; by itself it is not enough (the list also names monsters);
    - `fought`: players killed it or fought it. Then it is no friend, whatever else is said;
    - `against`: the sides ('A', 'H') that a source which may not give rows saw it below neutral.

    Whichever way the side is found, a side whose players saw it below neutral cannot be part of it."""
    if fought:
        return '', 'players fought it: what a monster needs is not known'
    seen = {}
    for who, values in reactions.items() if isinstance(reactions, dict) else ():
        if who in ('Alliance', 'Horde') and isinstance(values, list) and values and all(_number(v, 8, 1) for v in values):
            seen[who[0]] = (min(values), max(values))
    hostile = {who for who, (low, _high) in seen.items() if low < NEUTRAL} | set(against)
    warm = ''.join(sorted(who for who, (low, high) in seen.items() if low >= NEUTRAL and high > NEUTRAL and who not in hostile))
    listed = stated if isinstance(stated, str) and stated in FACTION_OF_SIDE else ''
    if talked is None:
        if warm:
            return warm, 'reactions'
        if hostile:
            return '', 'it is not friendly to players: what a monster needs is not known'
        return '', ('only a list says whom it is friendly to: no player was seen talking to it' if listed else 'nothing states whom it is friendly to')
    found, whose = (talked[0], 'talked') if talked in ('Alliance', 'Horde') else (listed, 'questie') if listed else (warm, 'reactions')
    if not found:
        return '', 'players talked to it, but nothing states whose side it is on'
    if hostile & set(found):
        return '', 'sources disagree about whom it is friendly to'
    return found, whose


def rows(npc, record, level, friendly_to):
    """(Npc, problems) for one record. `level` is (min, max); `friendly_to` is 'A', 'H' or 'AH'."""
    problems = []
    if not isinstance(record, dict):
        return None, ['its record is not a record']
    template = collections.OrderedDict(entry=npc)
    proxies = record.get('proxyCreatureIds', [])
    if not isinstance(proxies, list) or len(proxies) > 2 or not all(_number(p, MAX32, 1) for p in proxies):
        problems.append('proxyCreatureIds is not one or two creatures')
        proxies = []
    template['KillCredit1'], template['KillCredit2'] = (proxies + [0, 0])[:2]
    name, title, cursor = record.get('name'), record.get('title'), record.get('cursor')
    if not _text(name) or not name.strip():
        problems.append('it has no name the file can hold')
    for label, value in (('title', title), ('cursor', cursor)):
        if value is not None and not _text(value):
            problems.append(f'{label} is not text the file can hold')
    if isinstance(cursor, str) and len(cursor) > 64:
        problems.append('cursor is longer than the column')
    template['name'], template['subname'], template['IconName'] = name, title or None, cursor or None
    if friendly_to not in FACTION_OF_SIDE:
        problems.append('its side is not one of A, H, AH')
    template['faction'] = FACTION_OF_SIDE.get(friendly_to, 0)
    for column, key, high in (('Classification', 'classification', 255), ('type', 'type', 255), ('family', 'family', 2 ** 31 - 1), ('movementId', 'movementInfoId', MAX32)):
        value = record.get(key, 0)
        if not _number(value, high):
            problems.append(f'{key} is not a number the column takes')
        template[column] = value
    if not _number(record.get('unitClass')) or record.get('unitClass') not in CLASSES:
        problems.append('unitClass is not a class a creature can have')
    template['unit_class'] = record.get('unitClass')
    template['BaseAttackTime'], template['RangeAttackTime'], template['unit_flags2'] = ATTACK_TIME, ATTACK_TIME, UNIT_FLAGS2

    flags = record.get('flags', [0, 0, 0])
    if not isinstance(flags, list) or len(flags) != 3 or not all(_number(f) for f in flags):
        problems.append('flags is not three numbers')
        flags = [0, 0, 0]
    health, mana, number = record.get('hpMultiplier', 1), record.get('energyMultiplier', 1), record.get('creatureDifficultyId', 0)
    if not _factor(health) or not _factor(mana) or not _number(number, 2 ** 31 - 1):
        problems.append('hpMultiplier, energyMultiplier or creatureDifficultyId is not a number the columns take')
    difficulty = collections.OrderedDict(Entry=npc, DifficultyID=0, HealthModifier=health, ManaModifier=mana, CreatureDifficultyID=number,
                                         TypeFlags=flags[0], TypeFlags2=flags[1], TypeFlags3=flags[2])
    models, displays = [], record.get('displays')
    if not isinstance(displays, list) or not displays or not all(isinstance(d, dict) for d in displays):
        problems.append('it has no model')
        displays = []
    for index, display in enumerate(displays):
        shown, scale, chance = display.get('displayId'), display.get('scale', 1), display.get('probability', 1)
        if not _number(shown, MAX32, 1) or not _factor(scale, 1000) or not scale or not _factor(chance):
            problems.append('a model has no display id, or a scale or probability the columns do not take')
            break
        models.append(collections.OrderedDict(CreatureID=npc, Idx=index, CreatureDisplayID=shown, DisplayScale=scale, Probability=chance))
    if not (isinstance(level, (tuple, list)) and len(level) == 2 and _number(level[0], 255, 1) and _number(level[1], 255, 1) and level[0] <= level[1]):
        problems.append('its level is not a range from 1 to 255')
    if problems:
        return None, problems
    return Npc(template, difficulty, models, tuple(level), sorted(set(record) - READ)), []
