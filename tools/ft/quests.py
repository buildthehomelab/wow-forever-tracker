"""A quest's rows, from the record the server sent to a client of the live game.

The record (EG Link's `quests` data, one per quest and build) is what the client's quest cache holds: the fields of
the server's own answer to "what is quest N". This module turns one record into the rows the world's tables take.
It reads no database and guesses nothing: a field is the record's value, a constant every row of its kind holds, or
left to the table's own default and named in `LEFT`.

How the mapping was checked: for the 463 quests the replayed world holds from a recording of build 70124 or later
and EG Link also recorded, the rows made here were compared with the world's, column by column. Every column below
agrees on 97 to 100 % of them; where they differ the record is the newer word (a reward changed on live after the
world's recording).

    quest_template                  from the record
      QuestType, QuestInfoID, Flags, FlagsEx, FlagsEx2, StartItem, RewardNextQuest, RewardSpell, TimeAllowed
      QuestSortID                   the zone, or minus the category when the record names a category
      RewardXPDifficulty, RewardXPMultiplier
      AllowableRaces                the race mask (64 bits)
      RewardItemN, RewardAmountN (4), ItemDropN, ItemDropQuantityN (4), RewardChoiceItemIDN, ...QuantityN (6)
      RewardFactionIDN, RewardFactionValueN = the tier, RewardFactionOverrideN (5), RewardCurrencyIDN, ...QtyN (4)
      LogTitle, LogDescription (the objectives text), QuestDescription, AreaDescription, QuestCompletionLog
    quest_template                  constants of every quest recorded on Forever
      RewardFactionCapInN = 7, AcceptedSoundKitID 890, CompleteSoundKitID 878, Expansion -2
    quest_objectives                ID (Forever's own), Type, Order (its place in the record), StorageIndex, ObjectID,
                                    Amount, Description
    quest_classic_level             MinLevel (and QuestLevel)          the level from which the quest is offered
    quest_template_classic_level    LevelType 2, QuestLevel            the level shown in the quest log
    quest_classic_money             RewardMoney                        when the record states money
    quest_reward_display_spell      SpellID, Type                      in the record's order
    quest_template_addon            AllowableClasses                   the class of a class category: a quest filed
                                    under "Paladin" is a paladin's quest (303 of the 308 such rows the world holds
                                    from a Forever recording carry exactly that class); QuestieDB's word comes first

Every row carries VerifiedBuild 0 where the table has the column: it is written from a record, it is not a recording
of this server.
"""
import collections
import re

MAX32 = 2 ** 32 - 1
TEXTS = (('LogTitle', 'title'), ('LogDescription', 'objectivesText'), ('QuestDescription', 'description'),
         ('AreaDescription', 'areaDescription'), ('QuestCompletionLog', 'completionText'))
NUMBERS = (('QuestType', 'questType', 3), ('QuestInfoID', 'questInfoId', 65535), ('RewardNextQuest', 'nextQuestId', MAX32),
           ('StartItem', 'startItemId', MAX32), ('Flags', 'flags', MAX32), ('FlagsEx', 'flagsEx', MAX32), ('FlagsEx2', 'flagsEx2', MAX32),
           ('TimeAllowed', 'timeLimitSeconds', 2 ** 62))
SOUNDS = (('AcceptedSoundKitID', 890), ('CompleteSoundKitID', 878))
EXPANSION, CAP_IN, LEVEL_TYPE, OBJECTIVE_FLAGS = -2, 7, 2, 32
SLOTS = tuple(name.format(i) for names, most in ((('RewardItem{}', 'RewardAmount{}', 'ItemDrop{}', 'ItemDropQuantity{}'), 4),
                                                 (('RewardChoiceItemID{}', 'RewardChoiceItemQuantity{}'), 6),
                                                 (('RewardFactionID{}', 'RewardFactionValue{}', 'RewardFactionOverride{}', 'RewardFactionCapIn{}'), 5),
                                                 (('RewardCurrencyID{}', 'RewardCurrencyQty{}'), 4)) for i in range(1, most + 1) for name in names)
# What a quest's rows do not hold: left to the table's default, or not written at all. Listed in each export's manifest.
LEFT = ('quest_template.RewardMoneyDifficulty, RewardMoneyMultiplier and RewardBonusMoney (the money is written exactly, in quest_classic_money)',
        'quest_template.RewardFactionFlags, SuggestedGroupNum, ContentTuningID, QuestPackageID, the honor, title, skill and artifact rewards, RewardChoiceItemDisplayID',
        'quest_template.POI and Portrait columns',
        'the texts and rewards a record gives for a player condition (conditionalDescriptions, conditionalCompletionTexts, treasurePickerIds): '
        'quest_description_conditional, quest_completion_log_conditional, quest_treasure_pickers. A quest that has any names them under "unread"',
        f'quest_objectives.Flags is {OBJECTIVE_FLAGS} for every objective: what four in five recorded Forever objectives hold, not this quest\'s own',
        'quest_template_addon beyond the classes (QuestieDB\'s word, else the class of a class category) and the one quest before it that QuestieDB states',
        'quest_offer_reward, quest_request_items, quest_details (what the NPC says and does at the turn-in), quest_poi')

# the quest categories that are a class (QuestSort), and that class's bit in a class mask
CLASS_OF_CATEGORY = {81: 1, 141: 2, 261: 4, 162: 8, 262: 16, 82: 64, 161: 128, 61: 256, 263: 1024}

# the fields of a record that are read; any other a record carries is named in the quest's `unread`
READ = frozenset(name for _column, name, _high in NUMBERS) | frozenset(name for _column, name in TEXTS) | frozenset(
    ('zoneAreaId', 'categoryId', 'raceMask', 'rewards', 'objectives', 'itemDrops', 'level', 'minLevel', 'sources'))
READ_REWARDS = frozenset(('xpDifficulty', 'xpMultiplier', 'spellId', 'money', 'items', 'choices', 'currencies', 'reputation', 'displaySpells'))

Quest = collections.namedtuple('Quest', 'template objectives level money spells classes unread')


def _text(value):
    """True for a text the file can hold to the character."""
    if not isinstance(value, str) or '\x00' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def _number(value, high=MAX32, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _list(record, name, most, problems):
    value = record.get(name, [])
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        problems.append(f'{name} is not a list of records')
        return []
    if len(value) > most:
        problems.append(f'{len(value)} {name}: the row has room for {most}')
        return []
    return value


def _pairs(entries, name, first, second, problems, high=MAX32):
    out = []
    for entry in entries:
        if not _number(entry.get(first), MAX32, 1) or not _number(entry.get(second), high, 1):
            problems.append(f'{name}: {first} or {second} is not a number above 0')
            return []
        out.append((entry[first], entry[second]))
    return out


def rows(quest, record):
    """(Quest, problems) for one record. With problems the quest cannot be written and they say why."""
    problems = []
    if not isinstance(record, dict):
        return None, ['its record is not a record']
    rewards = record.get('rewards', {})
    if not isinstance(rewards, dict):
        problems.append('rewards is not a record')
        rewards = {}
    template = collections.OrderedDict(ID=quest)
    for column in SLOTS:                 # every row names every column it may fill: an empty slot is 0, as the world's own rows hold it
        template[column] = CAP_IN if column.startswith('RewardFactionCapIn') else 0
    for column, name, high in NUMBERS:
        value = record.get(name, 0)
        if not _number(value, high):
            problems.append(f'{name} is not a number the column takes')
        template[column] = value
    zone, category = record.get('zoneAreaId', 0), record.get('categoryId', 0)
    if not _number(zone, 32767) or not _number(category, 32767):
        problems.append('zoneAreaId or categoryId is not a number the column takes')
    elif zone and category:
        problems.append('it names both a zone and a category: the row has room for one')
    else:
        template['QuestSortID'] = zone if zone else -category
    difficulty, multiplier = rewards.get('xpDifficulty', 0), rewards.get('xpMultiplier', 1)
    if not _number(difficulty) or isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not 0 <= multiplier < 1000:
        problems.append('xpDifficulty or xpMultiplier is not a number')
    template['RewardXPDifficulty'], template['RewardXPMultiplier'] = difficulty, multiplier
    spell = rewards.get('spellId', 0)
    if not _number(spell):
        problems.append('spellId is not a number')
    template['RewardSpell'] = spell
    races = record.get('raceMask')
    if not isinstance(races, str) or not re.fullmatch(r'[0-9a-fA-F]{1,16}', races):
        problems.append('raceMask is not 64 bits written in hex')
    else:
        template['AllowableRaces'] = int(races, 16)
    for name, source, most, first, second, columns in (
            ('items', rewards, 4, 'itemId', 'count', ('RewardItem{}', 'RewardAmount{}')),
            ('itemDrops', record, 4, 'itemId', 'count', ('ItemDrop{}', 'ItemDropQuantity{}')),
            ('choices', rewards, 6, 'itemId', 'count', ('RewardChoiceItemID{}', 'RewardChoiceItemQuantity{}')),
            ('currencies', rewards, 4, 'currencyId', 'amount', ('RewardCurrencyID{}', 'RewardCurrencyQty{}'))):
        for index, (thing, count) in enumerate(_pairs(_list(source, name, most, problems), name, first, second, problems), 1):
            template[columns[0].format(index)], template[columns[1].format(index)] = thing, count
    for index, entry in enumerate(_list(rewards, 'reputation', 5, problems), 1):
        faction, tier, override = entry.get('factionId'), entry.get('tier', 0), entry.get('override', 0)
        if not _number(faction, MAX32, 1) or not _number(tier, 9, -9) or not _number(override, 2 ** 31 - 1, -2 ** 31):
            problems.append('reputation: factionId, tier or override is not a number the columns take')
            break
        template[f'RewardFactionID{index}'], template[f'RewardFactionValue{index}'] = faction, tier
        template[f'RewardFactionOverride{index}'] = override
    for column, value in SOUNDS:
        template[column] = value
    template['Expansion'] = EXPANSION
    for column, name in TEXTS:
        value = record.get(name, '')
        if not _text(value):
            problems.append(f'{name} is not text the file can hold')
            value = ''
        template[column] = value
    if not template['LogTitle'].strip():
        problems.append('it has no title')

    objectives = []
    for order, entry in enumerate(_list(record, 'objectives', 250, problems)):
        number, kind, target = entry.get('id'), entry.get('typeId'), entry.get('objectId')
        index, amount, said = entry.get('storageIndex', 0), entry.get('amount', 0), entry.get('text', '')
        if not (_number(number, MAX32, 1) and _number(kind, 255) and _number(target, 2 ** 31 - 1, -2 ** 31) and _number(index, 127, -128)
                and _number(amount, 2 ** 31 - 1, -2 ** 31) and _text(said)):
            problems.append('an objective has no id, or a field the columns do not take')
            break
        objectives.append(collections.OrderedDict(ID=number, QuestID=quest, Type=kind, Order=order, StorageIndex=index, ObjectID=target, Amount=amount,
                                                  Flags=OBJECTIVE_FLAGS, Description=said))
    if len({o['ID'] for o in objectives}) != len(objectives):
        problems.append('two objectives share an id')

    level, least = record.get('level'), record.get('minLevel')
    if not _number(level, 32767, -1) or not _number(least, 255):
        problems.append('level or minLevel is not a number')
    money = rewards.get('money', 0)
    if not _number(money, 2 ** 31 - 1, -2 ** 31):
        problems.append('money is not a number')
    spells = []
    for entry in _list(rewards, 'displaySpells', 250, problems):
        if not _number(entry.get('spellId'), MAX32, 1) or not _number(entry.get('type', 0), MAX32):
            problems.append('displaySpells: spellId or type is not a number')
            break
        spells.append((entry['spellId'], entry.get('type', 0)))
    if problems:
        return None, problems
    unread = sorted(set(record) - READ) + sorted(f'rewards.{name}' for name in set(rewards) - READ_REWARDS)
    return Quest(template, objectives, (level, least), money, spells, CLASS_OF_CATEGORY.get(-template['QuestSortID'], 0), unread), []


def targets(quest):
    """The NPCs and objects a quest's objectives need: {'npc': ids, 'object': ids}. An objective to kill or to talk
    to names an NPC, one to use an object names an object; the other kinds name nothing the world's templates hold."""
    return {'npc': sorted({o['ObjectID'] for o in quest.objectives if o['Type'] in (0, 3) and o['ObjectID'] > 0}),
            'object': sorted({o['ObjectID'] for o in quest.objectives if o['Type'] == 2 and o['ObjectID'] > 0})}
