"""Quests the world already has, read again from the newest recording of the live game (docs/SOURCES.md).

An import adds what the server lacks. A quest the server has is never looked at again that way, and Blizzard keeps
changing quests: a reward is swapped, an amount is lowered, a text is rewritten. EG Link records each quest as the
live server sent it to a client (the client's quest cache), per client build. This module compares that record with
the server's rows and says what differs, as "set" changes for an import card: nothing is changed until the card is
applied, each change names the value it replaces, and each keeps its rollback.

The later word wins. A row carries the client build it was recorded on (VerifiedBuild); the record carries the build
it was seen on. A record is taken only when it is from the live game and from a later build than the row. A row from
the same or a later build is the newer word and is left alone, and so is a row whose record cannot be read.

A difference is only a difference when the two say something else. The first run on a whole world proposed 7,400
changes, and most were the same thing written another way. So:

  - **A recording never empties a value.** A record that names no reward item, no completion text, no faction is not
    proof there is none: rewards chosen by class or by condition are not in the plain fields, and the recorder does
    not keep every text. What the row holds stays.
  - **Reputation is compared as points.** A row says how much reputation either as a tier (RewardFactionValue, read in
    the client's QuestFactionReward table) or as points times a hundred (RewardFactionOverride). 75 points written
    one way or the other is no change. Without the table, a row written the other way is left alone.
  - **Text is compared as it reads.** Line breaks ($B or a line feed), runs of spaces, and the case of a placeholder
    ($n, $N) do not count. Where the record writes an amount as a placeholder ("$1oa Gnarlpine Fangs") and the row as
    its number ("15 Gnarlpine Fangs"), the text is the same: the amount itself is compared with the objective.
  - **Rewards are compared as a list, not slot by slot.** The same items, choices, currencies or reputations in
    another order are no change. Where the list really differs, the slots take the record's; a record with fewer
    entries than the row is a record that names less, and the row stays.
  - **The end text stands in either column.** Rows of older data hold it in QuestCompletionLog, the record in
    AreaDescription: the same text in the other column is no change.
  - **Not compared at all:** the money (the server sends the amount for the player who asked: at the level cap it is
    the money given instead of experience) and the quest's own level (it follows the player for a scaling quest).

What is compared (ft.quests turns a record into the rows' columns):

    quest_template         what a quest gives (items, choices, currencies, reputation, spell, XP) and what it says
                           (title, objectives text, description, area, completion log)
    quest_objectives       an objective's amount and its text, by Forever's own objective id
    quest_classic_level    the level the quest is offered from

What decides how the server handles a quest (its type, flags, start item, time limit, zone, races, the quest after
it) is compared and counted, never changed here: a server may hold those differently on purpose, and a wrong one
breaks a quest instead of misstating a reward.

This module reads no database and no configuration: it is given the records and the rows.
"""
import collections
import re

from . import quests

SLOTS = 5   # reputation rewards of a quest
# rewards a quest gives several of: (the thing, how many, slots)
LISTS = (('RewardItem{}', 'RewardAmount{}', 4), ('RewardChoiceItemID{}', 'RewardChoiceItemQuantity{}', 6), ('RewardCurrencyID{}', 'RewardCurrencyQty{}', 4))
SINGLE = ('RewardSpell', 'RewardXPDifficulty', 'RewardXPMultiplier')
REWARDS = tuple(name.format(i) for thing, count, most in LISTS for i in range(1, most + 1) for name in (thing, count)) + SINGLE
REPUTATION = tuple(name.format(i) for i in range(1, SLOTS + 1) for name in ('RewardFactionID{}', 'RewardFactionValue{}', 'RewardFactionOverride{}'))
TEXTS = tuple(column for column, _name in quests.TEXTS)
END_TEXTS = {'AreaDescription': 'QuestCompletionLog', 'QuestCompletionLog': 'AreaDescription'}
# what decides how the server handles the quest: counted, never changed
MECHANICS = ('QuestType', 'QuestInfoID', 'Flags', 'FlagsEx', 'FlagsEx2', 'StartItem', 'RewardNextQuest', 'TimeAllowed', 'QuestSortID', 'AllowableRaces') \
    + tuple(name.format(i) for i in range(1, 5) for name in ('ItemDrop{}', 'ItemDropQuantity{}'))
BREAK = re.compile(r'[ \t]*(?:\r\n|\r|\n|\$[Bb])[ \t]*')
SPACES = re.compile(r'[ \t]+')
PLACEHOLDER = re.compile(r'\$([A-Za-z])')
AMOUNT = re.compile(r'\$\d+oa')
NUMBER = re.compile(r'\b\d+\b')


def text(value):
    """A text as it reads: line breaks in one form, single spaces, placeholders in one case, nothing at its ends."""
    out = SPACES.sub(' ', BREAK.sub('\n', '' if value is None else str(value))).strip()
    return PLACEHOLDER.sub(lambda match: '$' + match.group(1).upper(), out)


def same_text(old, new):
    """The row's text reads as the record's. A record may write an amount as a placeholder ($1oa) where the row has
    the number: then the numbers are not what is compared."""
    old, new = text(old), text(new)
    if old == new:
        return True
    if AMOUNT.search(new) or AMOUNT.search(old):
        return NUMBER.sub('#', AMOUNT.sub('#', old)) == NUMBER.sub('#', AMOUNT.sub('#', new))
    return False


def same(old, new):
    """The row's value (text, as a database client prints it) says what the record's value says."""
    if isinstance(new, str):
        return same_text(old, new)
    try:
        if isinstance(new, float):
            return abs(float(old) - new) < 0.005
        return int(old) == int(new)
    except (TypeError, ValueError):
        return False


def empty(value):
    """Nothing: no text, no number, 0."""
    if value is None:
        return True
    if isinstance(value, str):
        try:
            return float(value) == 0
        except ValueError:
            return not value.strip()
    return value == 0


def points(value, override, tiers):
    """The reputation a row or a record gives, in points: the override when there is one (points times a hundred),
    else the tier read in the client's table (tiers: {1: [points per tier], 2: the same for a loss}). None when the
    tier cannot be read (no table, a tier outside it)."""
    try:
        value, override = int(value or 0), int(override or 0)
    except (TypeError, ValueError):
        return None
    if override:
        return override / 100
    if not value:
        return 0
    row = (tiers or {}).get(2 if value < 0 else 1)
    if not row or abs(value) >= len(row):
        return None
    return row[abs(value)]


def newest_live(facts, live_from):
    """{quest: (build, record)}: each quest's record from the newest build of the live game that has one. facts: the
    facts of a recording (ft.facts.eglink); live_from: the first build of the live game."""
    out = {}
    for fact in facts:
        if fact.kind == 'quest' and fact.build >= live_from and (fact.subject not in out or fact.build >= out[fact.subject][0]):
            out[fact.subject] = (fact.build, fact.data)
    return out


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _build(row):
    try:
        return int(row.get('VerifiedBuild') or 0)
    except (TypeError, ValueError):
        return 0


def quest_changes(records, rows, objectives=None, levels=None, tiers=None):
    """What the newest live records would change in the world's quest rows.

    records: {quest: (build, record)} (newest_live); rows: {quest: its quest_template row}; objectives: {objective id:
    its quest_objectives row}; levels: {quest: its quest_classic_level row}; tiers: the client's QuestFactionReward
    table as {1: [points per tier], 2: [points per tier, for a loss]}. Rows are {column: value as text}, as ft.sqlio
    gives them. A table that is not given is not compared.

    Returns (changes, left): changes as the Forge's "set" operations, one per table and column, rows sorted;
    left: {reason: count of quests} of what was compared and left alone.
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
        new = made.template
        changed, why = False, set()

        def take(table, key, column, old, value):
            """One value: proposed when the record says something else, never when the record says nothing."""
            if same(old, value):
                return False
            if empty(value):
                why.add('quest_value_gone')
                return False
            found[table, ('ID',), column].append([key, value])
            return True

        for thing, count, most in LISTS:
            columns = [(thing.format(i), count.format(i)) for i in range(1, most + 1)]
            if not all(a in row and b in row for a, b in columns):
                continue
            old_list = sorted((_int(row[a]), _int(row[b])) for a, b in columns if _int(row[a]))
            new_list = sorted((_int(new[a]), _int(new[b])) for a, b in columns if _int(new[a]))
            if old_list == new_list:
                continue   # the same rewards, in whatever order
            if len(new_list) < len(old_list):
                why.add('quest_value_gone')
                continue
            for a, b in columns:
                for column in (a, b):
                    if not same(row[column], new[column]):
                        found['quest_template', ('ID',), column].append([quest, new[column]])
                        changed = True
        for column in SINGLE + TEXTS:
            if column not in row:
                continue
            other = END_TEXTS.get(column)
            if other and other in row and not empty(new[column]) and same(row[other], new[column]):
                continue   # the end text, in the other of its two columns
            if other and empty(new[column]) and not empty(row[column]) and same(row[column], new[other]):
                continue   # and the same seen from the column the row holds it in
            changed |= take('quest_template', quest, column, row[column], new[column])
        slots = [tuple(f'{name}{slot}' for name in ('RewardFactionID', 'RewardFactionValue', 'RewardFactionOverride')) for slot in range(1, SLOTS + 1)]
        if all(column in row for names in slots for column in names):
            def given(source, names):
                faction, value, override = (source[name] for name in names)
                return _int(faction), points(value, override, tiers), (_int(value), _int(override))
            old_rep = [given(row, names) for names in slots if _int(row[names[0]])]
            new_rep = [given(new, names) for names in slots if _int(new[names[0]])]
            if any(amount is None for _faction, amount, _raw in old_rep + new_rep):
                # a tier that cannot be read: only the same form can be compared
                if sorted((f, raw) for f, _a, raw in old_rep) != sorted((f, raw) for f, _a, raw in new_rep):
                    why.add('quest_reputation_other_form')
            elif sorted((f, round(a, 2)) for f, a, _raw in old_rep) == sorted((f, round(a, 2)) for f, a, _raw in new_rep):
                pass   # the same reputations, as tiers or overrides, in whatever order
            elif len(new_rep) < len(old_rep):
                why.add('quest_value_gone')
            else:
                for names in slots:
                    ours, theirs = given(row, names), given(new, names)
                    if ours[0] == theirs[0] and (not ours[0] or abs(ours[1] - theirs[1]) < 0.005):
                        continue   # this slot gives the same already
                    for column in names:
                        if not same(row[column], new[column]):
                            found['quest_template', ('ID',), column].append([quest, new[column]])
                            changed = True
        if any(column in row and not same(row[column], new[column]) for column in MECHANICS):
            why.add('quest_mechanics_differ')
        for objective in made.objectives:
            theirs = (objectives or {}).get(objective['ID'])
            if theirs is None or str(theirs.get('QuestID')) != str(quest) or _build(theirs) >= build:
                continue   # an objective the world lacks is not added here: a quest's shape is not a value
            for column in ('Amount', 'Description'):
                if column in theirs:
                    changed |= take('quest_objectives', objective['ID'], column, theirs[column], objective[column])
        if levels is not None and quest in levels and 'MinLevel' in levels[quest]:
            changed |= take('quest_classic_level', quest, 'MinLevel', levels[quest]['MinLevel'], made.level[1])
        for reason in why:
            left[reason] += 1
        if not changed and not why:
            left['quest_same'] += 1
    changes = [{'db': 'world', 'table': table, 'columns': list(keys) + [column], 'match': list(keys), 'set': column, 'rows': sorted(found[table, keys, column])}
               for table, keys, column in sorted(found)]
    return changes, dict(left)
