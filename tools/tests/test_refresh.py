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


def changes(rec, world_row, build=70938, **more):
    found, left = refresh.quest_changes({7: (build, rec)}, {7: world_row}, **more)
    return {(op['table'], op['set']): op['rows'] for op in found}, left


class Records(unittest.TestCase):
    def test_the_newest_recording_of_the_live_game_is_the_one(self):
        facts = [Fact('quest', 'quest', 7, 0, 70938, 1, {'n': 'new'}), Fact('quest', 'quest', 7, 0, 70888, 1, {'n': 'old'}),
                 Fact('quest', 'quest', 8, 0, 70532, 1, {'n': 'beta'}),     # before the live game: no word on it
                 Fact('gives', 'npc', 9, 7, 70938, 1, {})]
        self.assertEqual(refresh.newest_live(facts, 70755), {7: (70938, {'n': 'new'})})


TIERS = {1: [0, 10, 25, 50, 75, 100, 150, 250, 350, 500], 2: [0, -10, -25, -50, -75, -100, -150, -250, -350, -500]}


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
        self.assertEqual((found, left), ({}, {'quest_mechanics_differ': 1}))

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

    def test_the_level_a_quest_is_offered_from(self):
        found, _left = changes(record(minLevel=6, level=12), row(), levels={7: {'ID': '7', 'QuestLevel': '10', 'MinLevel': '8'}})
        self.assertEqual(found, {('quest_classic_level', 'MinLevel'): [[7, 6]]})   # its own level follows the player: not compared
        self.assertEqual(changes(record(minLevel=6), row())[0], {})                # a world without the table

    def test_what_is_changed_and_what_is_only_counted_never_overlap(self):
        self.assertEqual(set(refresh.REWARDS + refresh.REPUTATION + refresh.TEXTS) & set(refresh.MECHANICS), set())
        made, _problems = quests.rows(7, record())
        self.assertEqual(set(refresh.REWARDS + refresh.REPUTATION + refresh.TEXTS + refresh.MECHANICS) - set(made.template), set())


class SameThingAnotherWay(unittest.TestCase):
    """What the first run on a whole world proposed and should not have: 7,400 changes, most of them no change."""

    def test_a_recording_never_empties_a_value(self):
        rec = record(rewards={'xpDifficulty': 5, 'xpMultiplier': 1})   # no reward item named: chosen by class, perhaps
        found, left = changes(rec, row(QuestCompletionLog='Return to Sara Timberlain.'))   # and no completion text recorded
        self.assertEqual((found, left), ({}, {'quest_value_gone': 1}))
        # nor an objective's amount
        theirs = {9001: {'ID': '9001', 'QuestID': '7', 'Amount': '10', 'Description': 'Linen Cloth', 'VerifiedBuild': '0'}}
        rec = record(objectives=[{'id': 9001, 'typeId': 1, 'objectId': 2589, 'amount': 0, 'text': 'Linen Cloth'}])
        self.assertEqual(changes(rec, row(), objectives=theirs), ({}, {'quest_value_gone': 1}))

    def test_money_is_not_compared(self):
        # the server sends the amount for the player who asked: at the level cap, the money given instead of experience
        rec = record(rewards={'xpDifficulty': 5, 'xpMultiplier': 1, 'money': 6600, 'items': [{'itemId': 2589, 'count': 10}]})
        self.assertEqual(changes(rec, row()), ({}, {'quest_same': 1}))

    def test_a_placeholder_in_another_case_and_spaces(self):
        rec = record(description='We need  cloth.\n\nHurry.', objectivesText='Bring 10 Linen Cloth, $n.')
        self.assertEqual(changes(rec, row(LogDescription='Bring 10 Linen Cloth, $N. '))[0], {})
        self.assertFalse(refresh.same_text('Hello, $N.', 'Hello, $C.'))   # another placeholder is another text

    def test_an_amount_written_as_a_placeholder(self):
        rec = record(objectivesText='Bring $1oa Linen Cloth to Sara.')
        self.assertEqual(changes(rec, row(LogDescription='Bring 10 Linen Cloth to Sara.'))[0], {})
        found, _left = changes(record(objectivesText='Bring $1oa Linen Cloth to Sara in Goldshire.'), row(LogDescription='Bring 10 Linen Cloth to Sara.'))
        self.assertEqual(list(found), [('quest_template', 'LogDescription')])   # reworded besides
        # without a placeholder a number is part of the text
        self.assertFalse(refresh.same_text('Bring 10 Linen Cloth.', 'Bring 8 Linen Cloth.'))

    def test_the_end_text_in_the_other_column(self):
        rec = record(areaDescription='Scout the gazebo on Mystral Lake.')
        self.assertEqual(changes(rec, row(QuestCompletionLog='Scout the gazebo on Mystral Lake.')), ({}, {'quest_same': 1}))
        found, _left = changes(rec, row())   # in neither: it is set
        self.assertEqual(found, {('quest_template', 'AreaDescription'): [[7, 'Scout the gazebo on Mystral Lake.']]})

    def reputation(self, **more):
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 2589, 'count': 10}], 'reputation': [dict(factionId=72, **more)]}
        return record(rewards=rewards)

    def test_reputation_as_a_tier_or_as_points_is_one_reward(self):
        world = row(RewardFactionID1=72, RewardFactionValue1=0, RewardFactionOverride1=7500)   # 75 points, written as an override
        self.assertEqual(changes(self.reputation(tier=4), world, tiers=TIERS), ({}, {'quest_same': 1}))   # tier 4 is 75 points
        found, _left = changes(self.reputation(tier=5), world, tiers=TIERS)                              # 100 points now
        self.assertEqual(found, {('quest_template', 'RewardFactionValue1'): [[7, 5]], ('quest_template', 'RewardFactionOverride1'): [[7, 0]]})
        # a loss reads the other row of the table
        self.assertEqual(changes(self.reputation(tier=-4), row(RewardFactionID1=72, RewardFactionOverride1=-7500), tiers=TIERS)[0], {})

    def test_without_the_table_another_form_is_left_alone(self):
        world = row(RewardFactionID1=72, RewardFactionValue1=0, RewardFactionOverride1=7500)
        self.assertEqual(changes(self.reputation(tier=4), world), ({}, {'quest_reputation_other_form': 1}))
        self.assertEqual(changes(self.reputation(tier=4), row(RewardFactionID1=72, RewardFactionValue1=4)), ({}, {'quest_same': 1}))

    def test_another_faction_is_a_change_and_no_faction_is_not(self):
        world = row(RewardFactionID1=72, RewardFactionValue1=4)
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 2589, 'count': 10}], 'reputation': [{'factionId': 47, 'tier': 4}]}
        self.assertEqual(changes(record(rewards=rewards), world, tiers=TIERS)[0], {('quest_template', 'RewardFactionID1'): [[7, 47]]})
        self.assertEqual(changes(record(), world, tiers=TIERS), ({}, {'quest_value_gone': 1}))   # the record names none

    def test_rewards_in_another_order_are_the_same_rewards(self):
        two = {'xpDifficulty': 5, 'xpMultiplier': 1, 'choices': [{'itemId': 3578, 'count': 1}, {'itemId': 1561, 'count': 1}],
               'items': [{'itemId': 118, 'count': 2}, {'itemId': 2589, 'count': 10}],
               'reputation': [{'factionId': 93, 'tier': 4}, {'factionId': 92, 'tier': -5}]}
        world = row(RewardChoiceItemID1=1561, RewardChoiceItemQuantity1=1, RewardChoiceItemID2=3578, RewardChoiceItemQuantity2=1,
                    RewardItem1=2589, RewardAmount1=10, RewardItem2=118, RewardAmount2=2,
                    RewardFactionID1=92, RewardFactionOverride1=-10000, RewardFactionID2=93, RewardFactionValue2=4)
        self.assertEqual(changes(record(rewards=two), world, tiers=TIERS), ({}, {'quest_same': 1}))

    def test_a_list_that_really_differs_takes_the_records_slots(self):
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 2589, 'count': 10}],
                   'choices': [{'itemId': 3578, 'count': 1}, {'itemId': 20083, 'count': 1}]}
        world = row(RewardChoiceItemID1=1561, RewardChoiceItemQuantity1=1, RewardChoiceItemID2=3578, RewardChoiceItemQuantity2=1)
        found, _left = changes(record(rewards=rewards), world)
        self.assertEqual(found, {('quest_template', 'RewardChoiceItemID1'): [[7, 3578]], ('quest_template', 'RewardChoiceItemID2'): [[7, 20083]]})

    def test_a_record_that_names_fewer_rewards_leaves_the_row(self):
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 2589, 'count': 10}], 'choices': [{'itemId': 3578, 'count': 1}],
                   'reputation': [{'factionId': 93, 'tier': 4}]}
        world = row(RewardChoiceItemID1=1561, RewardChoiceItemQuantity1=1, RewardChoiceItemID2=3578, RewardChoiceItemQuantity2=1,
                    RewardFactionID1=92, RewardFactionValue1=5, RewardFactionID2=93, RewardFactionValue2=4)
        # setting slot 1 to 3578 and leaving slot 2 would give the same item twice: the row stays as it is
        self.assertEqual(changes(record(rewards=rewards), world, tiers=TIERS), ({}, {'quest_value_gone': 1}))

    def test_a_choice_that_became_get_them_all_leaves_no_choice_behind(self):
        # Classic: choose one of three. Forever: all three. The record names no choice: the row's choice goes too
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 20083, 'count': 1}, {'itemId': 19991, 'count': 1}, {'itemId': 19992, 'count': 1}]}
        world = row(RewardItem1=0, RewardAmount1=0, RewardChoiceItemID1=19991, RewardChoiceItemQuantity1=1, RewardChoiceItemID2=19992,
                    RewardChoiceItemQuantity2=1, RewardChoiceItemID3=20083, RewardChoiceItemQuantity3=1)
        found, left = changes(record(rewards=rewards), world)
        self.assertEqual(found, {('quest_template', 'RewardItem1'): [[7, 20083]], ('quest_template', 'RewardAmount1'): [[7, 1]],
                                 ('quest_template', 'RewardItem2'): [[7, 19991]], ('quest_template', 'RewardAmount2'): [[7, 1]],
                                 ('quest_template', 'RewardItem3'): [[7, 19992]], ('quest_template', 'RewardAmount3'): [[7, 1]],
                                 ('quest_template', 'RewardChoiceItemID1'): [[7, 0]], ('quest_template', 'RewardChoiceItemQuantity1'): [[7, 0]],
                                 ('quest_template', 'RewardChoiceItemID2'): [[7, 0]], ('quest_template', 'RewardChoiceItemQuantity2'): [[7, 0]],
                                 ('quest_template', 'RewardChoiceItemID3'): [[7, 0]], ('quest_template', 'RewardChoiceItemQuantity3'): [[7, 0]]})
        self.assertEqual(left, {})

    def test_a_row_that_gives_and_offers_the_same_items_loses_the_list_the_record_lacks(self):
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 17001, 'count': 1}, {'itemId': 18022, 'count': 1}]}
        world = row(RewardItem1=17001, RewardAmount1=1, RewardItem2=18022, RewardAmount2=1,
                    RewardChoiceItemID1=18022, RewardChoiceItemQuantity1=1, RewardChoiceItemID2=17001, RewardChoiceItemQuantity2=1)
        found, _left = changes(record(rewards=rewards), world)
        self.assertEqual(found, {('quest_template', 'RewardChoiceItemID1'): [[7, 0]], ('quest_template', 'RewardChoiceItemQuantity1'): [[7, 0]],
                                 ('quest_template', 'RewardChoiceItemID2'): [[7, 0]], ('quest_template', 'RewardChoiceItemQuantity2'): [[7, 0]]})

    def test_a_given_reward_that_became_a_choice_moves_too(self):
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'choices': [{'itemId': 2589, 'count': 10}, {'itemId': 270126, 'count': 1}]}
        found, _left = changes(record(rewards=rewards), row())   # the row gives 10 Linen Cloth outright
        self.assertEqual(found, {('quest_template', 'RewardItem1'): [[7, 0]], ('quest_template', 'RewardAmount1'): [[7, 0]],
                                 ('quest_template', 'RewardChoiceItemID1'): [[7, 2589]], ('quest_template', 'RewardChoiceItemQuantity1'): [[7, 10]],
                                 ('quest_template', 'RewardChoiceItemID2'): [[7, 270126]], ('quest_template', 'RewardChoiceItemQuantity2'): [[7, 1]]})

    def test_a_choice_the_record_only_partly_explains_is_not_made_a_double(self):
        # the record gives 3578 outright and offers nothing; the row offers 3578 or 1561, and nothing says where 1561 went.
        # Taking the given list alone would give 3578 and offer it as well: both lists stay
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 2589, 'count': 10}, {'itemId': 3578, 'count': 1}]}
        world = row(RewardChoiceItemID1=1561, RewardChoiceItemQuantity1=1, RewardChoiceItemID2=3578, RewardChoiceItemQuantity2=1)
        self.assertEqual(changes(record(rewards=rewards), world), ({}, {'quest_value_gone': 1}))

    def test_a_reputation_that_changed_beside_one_that_did_not(self):
        rewards = {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': 2589, 'count': 10}],
                   'reputation': [{'factionId': 92, 'tier': 4}, {'factionId': 93, 'tier': 6}]}
        world = row(RewardFactionID1=92, RewardFactionOverride1=7500, RewardFactionID2=93, RewardFactionOverride2=10000)
        found, _left = changes(record(rewards=rewards), world, tiers=TIERS)
        # 92 gives 75 points either way and is left as it is written; 93 gives 150 now
        self.assertEqual(found, {('quest_template', 'RewardFactionValue2'): [[7, 6]], ('quest_template', 'RewardFactionOverride2'): [[7, 0]]})

    def test_points(self):
        self.assertEqual((refresh.points(4, 0, TIERS), refresh.points(0, 7500, TIERS), refresh.points(-2, 0, TIERS), refresh.points(0, 0, None)), (75, 75, -25, 0))
        self.assertIsNone(refresh.points(4, 0, None))
        self.assertIsNone(refresh.points(40, 0, TIERS))


if __name__ == '__main__':
    unittest.main()
