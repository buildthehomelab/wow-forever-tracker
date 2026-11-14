"""python -m unittest discover -s tools/tests

Quests the server already has, read again from the newest recording of the live game (ft.refresh): which record is
taken, what counts as a difference, and what is never changed. No database: the rows are given.
"""
import collections
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import quests, refresh  # noqa: E402

Fact = collections.namedtuple('Fact', 'kind subject_kind subject object build samples data')


def record(**more):
    """A quest as the live server sent it: 10 Linen Cloth, 1 silver, one objective."""
    out = {'title': 'Cloth for the Front', 'objectivesText': 'Bring 10 Linen Cloth.', 'description': 'We need cloth.\n\nHurry.',
           'areaDescription': '', 'completionText': '', 'raceMask': 'ffffffffffffffff', 'zoneAreaId': 12, 'level': 10, 'minLevel': 8,
           'flags': 8, 'rewards': {'xpDifficulty': 5, 'xpMultiplier': 1, 'money': 100, 'items': [{'itemId': 2589, 'count': 10}]},
           'objectives': [{'id': 9001, 'typeId': 1, 'objectId': 2589, 'amount': 10, 'text': 'Linen Cloth'}]}
    out.update(more)
    return out


def row(quest=7, build=70124, **more):
    """The world's row for that quest, as a database client prints it: every value text."""
    made, problems = quests.rows(quest, record())
    assert not problems, problems
    out = {column: str(value) for column, value in made.template.items()}
    out['QuestDescription'] = 'We need cloth.$B$BHurry.'   # the world writes its line breaks as $B
    out['VerifiedBuild'] = str(build)
    out.update({column: str(value) for column, value in more.items()})
    return out


def changes(rec, world_row, build=70938, **tables):
    found, left = refresh.quest_changes({7: (build, rec)}, {7: world_row}, **tables)
    return {(op['table'], op['set']): op['rows'] for op in found}, left


class Records(unittest.TestCase):
    def test_the_newest_recording_of_the_live_game_is_the_one(self):
        facts = [Fact('quest', 'quest', 7, 0, 70938, 1, {'n': 'new'}), Fact('quest', 'quest', 7, 0, 70888, 1, {'n': 'old'}),
                 Fact('quest', 'quest', 8, 0, 70532, 1, {'n': 'beta'}),     # before the live game: no word on it
                 Fact('gives', 'npc', 9, 7, 70938, 1, {})]
        self.assertEqual(refresh.newest_live(facts, 70755), {7: (70938, {'n': 'new'})})


class Quests(unittest.TestCase):
    def test_a_quest_that_says_the_same_changes_nothing(self):
        found, left = changes(record(), row())
        self.assertEqual((found, left), ({}, {'quest_same': 1}))   # $B and a line feed are one line break

    def test_a_reward_blizzard_changed_is_set(self):
        rec = record(rewards={'xpDifficulty': 6, 'xpMultiplier': 1, 'money': 100, 'items': [{'itemId': 2589, 'count': 5}, {'itemId': 118, 'count': 2}]})
        found, left = changes(rec, row())
        self.assertEqual(found, {('quest_template', 'RewardAmount1'): [[7, 5]], ('quest_template', 'RewardItem2'): [[7, 118]],
                                 ('quest_template', 'RewardAmount2'): [[7, 2]], ('quest_template', 'RewardXPDifficulty'): [[7, 6]]})
        self.assertEqual(left, {})

    def test_a_text_that_was_rewritten_is_set_to_the_character(self):
        found, _left = changes(record(description='We need cloth.\n\nHurry, $N!'), row())
        self.assertEqual(found, {('quest_template', 'QuestDescription'): [[7, 'We need cloth.\n\nHurry, $N!']]})

    def test_the_later_word_wins(self):
        rec = record(title='Cloth for the Rear')
        self.assertEqual(changes(rec, row(build=70938)), ({}, {'quest_row_newer': 1}))    # the row is from the same build
        self.assertEqual(changes(rec, row(build=71000)), ({}, {'quest_row_newer': 1}))    # or a later one
        self.assertEqual(changes(rec, row(build=0))[0], {('quest_template', 'LogTitle'): [[7, 'Cloth for the Rear']]})

    def test_how_the_server_handles_a_quest_is_counted_never_changed(self):
        found, left = changes(record(flags=8 | 4096, zoneAreaId=40), row())
        self.assertEqual((found, left), ({}, {'quest_mechanics_differ': 1, 'quest_same': 1}))

    def test_a_record_that_does_not_fit_is_left_alone(self):
        found, left = changes(record(raceMask='not hex'), row())
        self.assertEqual((found, left), ({}, {'quest_record_unreadable': 1}))

    def test_an_objective_keeps_its_shape_and_takes_the_new_amount(self):
        rec = record(objectives=[{'id': 9001, 'typeId': 1, 'objectId': 2589, 'amount': 8, 'text': 'Linen Cloth'},
                                 {'id': 9002, 'typeId': 0, 'objectId': 40, 'amount': 3, 'text': 'Kobolds slain'}])
        theirs = {9001: {'ID': '9001', 'QuestID': '7', 'Amount': '10', 'Description': 'Linen Cloth', 'VerifiedBuild': '70124'},
                  9002: {'ID': '9002', 'QuestID': '12', 'Amount': '1', 'Description': '', 'VerifiedBuild': '0'}}   # another quest's row under that id
        found, _left = changes(rec, row(), objectives=theirs)
        self.assertEqual(found, {('quest_objectives', 'Amount'): [[9001, 8]]})   # 9002 is not added and not touched

    def test_money_and_levels_where_the_world_has_the_rows(self):
        rec = record(minLevel=6, rewards={'xpDifficulty': 5, 'xpMultiplier': 1, 'money': 250, 'items': [{'itemId': 2589, 'count': 10}]})
        found, _left = changes(rec, row(), money={7: {'ID': '7', 'RewardMoney': '100'}}, levels={7: {'ID': '7', 'QuestLevel': '10', 'MinLevel': '8'}})
        self.assertEqual(found, {('quest_classic_money', 'RewardMoney'): [[7, 250]], ('quest_classic_level', 'MinLevel'): [[7, 6]]})
        # a world without those tables: nothing is said about them
        self.assertEqual(changes(rec, row())[0], {})

    def test_what_is_changed_and_what_is_only_counted_never_overlap(self):
        self.assertEqual(set(refresh.REWARDS + refresh.TEXTS) & set(refresh.MECHANICS), set())
        made, _problems = quests.rows(7, record())
        self.assertEqual(set(refresh.REWARDS + refresh.TEXTS + refresh.MECHANICS) - set(made.template), set())


if __name__ == '__main__':
    unittest.main()
