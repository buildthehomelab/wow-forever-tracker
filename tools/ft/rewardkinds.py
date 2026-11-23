"""How a quest hands out its item rewards: all of them, or one the player chooses.

A quest row has two lists. RewardItem1-4 are given outright; RewardChoiceItemID1-6 are offered and the player takes
one. Forever turned many of Classic's "choose one" rewards into "you get them all" (and a few the other way), and a
world built from older data still holds the old list. A quest whose row and whose record on the live game disagree
about the list an item is in pays out wrongly, and no other check sees it: the item is "a quest reward" either way.

This module compares the two lists of each row with the newest record of the live game (EG Link's quest records,
ft.refresh.newest_live) and names three things:

    all       the server offers it as a choice, the live game gives it outright (with the others)
    choice    the server gives it outright, the live game offers it as a choice
    twice     the server gives an item and offers the same item as a choice. The core hands out both lists, so the
              player is given it and picks it as well. Named with or without a record; a record that itself names the
              item in both lists is how Blizzard sends it, and is said so

It is a report. The changes themselves come from the quest refresh (ft.refresh), whose card the EG Link import makes:
it moves an item to the list the record names it in, and empties the list it left.

A row from the same or a later build than the record is the newer word, as in the refresh: its lists are not compared
with the record (it is still looked at for "twice"). This module reads no database: it is given the records and rows.
"""
import collections

from . import quests

GIVEN = tuple((f'RewardItem{i}', f'RewardAmount{i}') for i in range(1, 5))
OFFERED = tuple((f'RewardChoiceItemID{i}', f'RewardChoiceItemQuantity{i}') for i in range(1, 7))
COLUMNS = ('ID', 'LogTitle', 'VerifiedBuild') + tuple(name for pair in GIVEN + OFFERED for name in pair)
ISSUES = ('all', 'choice', 'twice')

Finding = collections.namedtuple('Finding', 'quest name issues gives offers live_gives live_offers build note')


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def listed(row, columns):
    """[(item, count)] of one list of a row, in slot order."""
    return [(_int(row.get(a)), _int(row.get(b)) or 1) for a, b in columns if _int(row.get(a))]


def written(pairs):
    """A list as the table holds it: "19991,19992x5" (an amount of 1 is not written)."""
    return ','.join(str(item) if count == 1 else f'{item}x{count}' for item, count in pairs)


def compare(records, rows):
    """(findings, counts). records: {quest: (build, record)} (ft.refresh.newest_live); rows: {quest: its
    quest_template row, at least COLUMNS}. findings: [Finding], by quest; counts: {issue or reason left: quests}."""
    found, counts = [], collections.Counter()
    for quest in sorted(rows):
        row = rows[quest]
        gives, offers = listed(row, GIVEN), listed(row, OFFERED)
        if not gives and not offers:
            continue
        mine_given, mine_offered = {i for i, _ in gives}, {i for i, _ in offers}
        live_gives = live_offers = None
        build = 0
        if quest in records:
            build, record = records[quest]
            made, problems = quests.rows(quest, record)
            if problems:
                counts['record_unreadable'] += 1
            else:
                live_gives, live_offers = listed(made.template, GIVEN), listed(made.template, OFFERED)
        issues, notes = [], []
        compared = live_gives is not None and _int(row.get('VerifiedBuild')) < build
        if live_gives is not None and not compared:
            counts['row_newer'] += 1
        if compared:
            there_given, there_offered = {i for i, _ in live_gives}, {i for i, _ in live_offers}
            if (mine_offered - mine_given) & (there_given - there_offered):
                issues.append('all')
            if (mine_given - mine_offered) & (there_offered - there_given):
                issues.append('choice')
        double = mine_given & mine_offered
        if double:
            issues.append('twice')
            if live_gives is None:
                notes.append('no record of the live game')
            else:
                there_given, there_offered = {i for i, _ in live_gives}, {i for i, _ in live_offers}
                if double <= (there_given & there_offered):
                    notes.append('the live game sends it in both lists as well')
                elif double <= there_given and not double & there_offered:
                    notes.append('the live game gives it outright')
                elif double <= there_offered and not double & there_given:
                    notes.append('the live game offers it as a choice')
        if not issues:
            continue
        for issue in issues:
            counts[issue] += 1
        found.append(Finding(quest, str(row.get('LogTitle') or ''), ','.join(issues), written(gives), written(offers),
                             None if live_gives is None else written(live_gives), None if live_offers is None else written(live_offers),
                             build, '. '.join(notes)))
    return found, counts
