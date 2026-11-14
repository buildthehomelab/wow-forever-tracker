"""Quests the world already has, read again from the newest recording of the live game (docs/SOURCES.md).

An import adds what the server lacks. A quest the server has is never looked at again that way, and Blizzard keeps
changing quests: a reward is swapped, an amount is lowered, a text is rewritten. EG Link records each quest as the
live server sent it to a client (the client's quest cache), per client build. This module compares that record with
the server's rows and says what differs, as "set" changes for an import card: nothing is changed until the card is
applied, each change names the value it replaces, and each keeps its rollback.

The later word wins. A row carries the client build it was recorded on (VerifiedBuild); the record carries the build
it was seen on. A record is taken only when it is from the live game and from a later build than the row. A row from
the same or a later build is the newer word and is left alone, and so is a row whose record cannot be read.

What is compared (ft.quests turns a record into the rows' columns, and says how that mapping was checked):

    quest_template         what a quest gives (items, choices, currencies, reputation, spell, XP) and what it says
                           (title, objectives text, description, area, completion log)
    quest_objectives       an objective's amount and its text, by Forever's own objective id
    quest_classic_money    the money, when the record states any
    quest_classic_level    the level the quest is offered from, and its own level

A text is the same when only its line breaks are written another way ($B, a line feed). What decides how the server
handles a quest (its type, flags, start item, time limit, zone, races, the quest after it) is compared and counted,
never changed here: a server may hold those differently on purpose, and a wrong one breaks a quest instead of
misstating a reward.

This module reads no database and no configuration: it is given the records and the rows.
"""
import collections
import re

from . import quests

REWARDS = tuple(name.format(i) for names, most in ((('RewardItem{}', 'RewardAmount{}'), 4), (('RewardChoiceItemID{}', 'RewardChoiceItemQuantity{}'), 6),
                                                   (('RewardFactionID{}', 'RewardFactionValue{}', 'RewardFactionOverride{}'), 5),
                                                   (('RewardCurrencyID{}', 'RewardCurrencyQty{}'), 4)) for i in range(1, most + 1) for name in names) \
    + ('RewardSpell', 'RewardXPDifficulty', 'RewardXPMultiplier')
TEXTS = tuple(column for column, _name in quests.TEXTS)
# what decides how the server handles the quest: counted, never changed
MECHANICS = ('QuestType', 'QuestInfoID', 'Flags', 'FlagsEx', 'FlagsEx2', 'StartItem', 'RewardNextQuest', 'TimeAllowed', 'QuestSortID', 'AllowableRaces') \
    + tuple(name.format(i) for i in range(1, 5) for name in ('ItemDrop{}', 'ItemDropQuantity{}'))
BREAK = re.compile(r'[ \t]*(?:\r\n|\r|\n|\$[Bb])[ \t]*')


def text(value):
    """A text as it reads: line breaks in one form, nothing at its ends."""
    return BREAK.sub('\n', '' if value is None else str(value)).strip()


def same(old, new):
    """The row's value (text, as a database client prints it) says what the record's value says."""
    if isinstance(new, str):
        return text(old) == text(new)
    try:
        if isinstance(new, float):
            return abs(float(old) - new) < 0.005
        return int(old) == int(new)
    except (TypeError, ValueError):
        return False


def newest_live(facts, live_from):
    """{quest: (build, record)}: each quest's record from the newest build of the live game that has one. facts: the
    facts of a recording (ft.facts.eglink); live_from: the first build of the live game."""
    out = {}
    for fact in facts:
        if fact.kind == 'quest' and fact.build >= live_from and (fact.subject not in out or fact.build >= out[fact.subject][0]):
            out[fact.subject] = (fact.build, fact.data)
    return out


def _build(row):
    try:
        return int(row.get('VerifiedBuild') or 0)
    except (TypeError, ValueError):
        return 0


def quest_changes(records, rows, objectives=None, money=None, levels=None):
    """What the newest live records would change in the world's quest rows.

    records: {quest: (build, record)} (newest_live); rows: {quest: its quest_template row}; objectives: {objective id:
    its quest_objectives row}; money: {quest: its quest_classic_money row}; levels: {quest: its quest_classic_level
    row}. Rows are {column: value as text}, as ft.sqlio gives them. A table that is not given is not compared.

    Returns (changes, left): changes as the Forge's "set" operations, one per table and column, rows sorted;
    left: {reason: count} of what was compared and left alone.
    """
    found = collections.defaultdict(list)   # (table, key columns, column) -> [[key..., new value]]
    left = collections.Counter()
    for quest in sorted(set(records) & set(rows)):
        build, record = records[quest]
        row = rows[quest]
        if _build(row) >= build:
            left['quest_row_newer'] += 1
            continue
        made, problems = quests.rows(quest, record)
        if problems:
            left['quest_record_unreadable'] += 1
            continue
        changed = False
        for column in REWARDS + TEXTS:
            if column in row and not same(row[column], made.template[column]):
                found['quest_template', ('ID',), column].append([quest, made.template[column]])
                changed = True
        if any(column in row and not same(row[column], made.template[column]) for column in MECHANICS):
            left['quest_mechanics_differ'] += 1
        for objective in made.objectives:
            theirs = (objectives or {}).get(objective['ID'])
            if theirs is None or str(theirs.get('QuestID')) != str(quest) or _build(theirs) >= build:
                continue   # an objective the world lacks is not added here: a quest's shape is not a value
            for column in ('Amount', 'Description'):
                if column in theirs and not same(theirs[column], objective[column]):
                    found['quest_objectives', ('ID',), column].append([objective['ID'], objective[column]])
                    changed = True
        if made.money and money is not None and quest in money and 'RewardMoney' in money[quest] and not same(money[quest]['RewardMoney'], made.money):
            found['quest_classic_money', ('ID',), 'RewardMoney'].append([quest, made.money])
            changed = True
        if levels is not None and quest in levels:
            for column, value in (('QuestLevel', made.level[0]), ('MinLevel', made.level[1])):
                if column in levels[quest] and not same(levels[quest][column], value):
                    found['quest_classic_level', ('ID',), column].append([quest, value])
                    changed = True
        left['quest_changed' if changed else 'quest_same'] += 1
    changes = [{'db': 'world', 'table': table, 'columns': list(keys) + [column], 'match': list(keys), 'set': column, 'rows': sorted(found[table, keys, column])}
               for table, keys, column in sorted(found)]
    left.pop('quest_changed', None)
    return changes, dict(left)
