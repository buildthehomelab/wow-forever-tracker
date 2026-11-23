"""python -m unittest discover -s tools/tests

How a quest hands out its item rewards (ft.rewardkinds): all of them or one the player chooses, the server's row
against the newest record of the live game. No database: the records and rows are given.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import rewardkinds  # noqa: E402


def record(items=(), choices=()):
    return {'title': 'The Green Drake', 'objectivesText': 'Bring the tooth.', 'description': 'Go.', 'areaDescription': '', 'completionText': '',
            'raceMask': 'ffffffffffffffff', 'zoneAreaId': 12, 'level': 50, 'minLevel': 50, 'flags': 8, 'objectives': [],
            'rewards': {'xpDifficulty': 5, 'xpMultiplier': 1, 'items': [{'itemId': i, 'count': c} for i, c in items],
                        'choices': [{'itemId': i, 'count': c} for i, c in choices]}}


def row(gives=(), offers=(), build=64978):
    out = {'ID': '8232', 'LogTitle': 'The Green Drake', 'VerifiedBuild': str(build)}
    out.update({name: '0' for pair in rewardkinds.GIVEN + rewardkinds.OFFERED for name in pair})
    for columns, pairs in ((rewardkinds.GIVEN, gives), (rewardkinds.OFFERED, offers)):
        for (a, b), (item, count) in zip(columns, pairs):
            out[a], out[b] = str(item), str(count)
    return out


THREE = ((19991, 1), (19992, 1), (20083, 1))


def check(rec, world, build=71037):
    found, counts = rewardkinds.compare({8232: (build, rec)} if rec else {}, {8232: world})
    return [(f.issues, f.gives, f.offers, f.live_gives, f.live_offers, f.note) for f in found], dict(counts)


class RewardKinds(unittest.TestCase):
    def test_a_choice_the_live_game_gives_outright(self):
        found, counts = check(record(items=THREE), row(offers=THREE))
        self.assertEqual(found, [('all', '', '19991,19992,20083', '19991,19992,20083', '', '')])
        self.assertEqual(counts, {'all': 1})

    def test_a_given_reward_the_live_game_offers_as_a_choice(self):
        found, _counts = check(record(choices=((12059, 1), (270126, 1))), row(gives=((12059, 1),)))
        self.assertEqual(found, [('choice', '12059', '', '', '12059,270126', '')])

    def test_the_same_lists_in_another_order_are_no_finding(self):
        self.assertEqual(check(record(items=((2589, 10),), choices=THREE[::-1]), row(gives=((2589, 10),), offers=THREE)), ([], {}))

    def test_another_item_is_the_refreshs_business_not_this_checks(self):
        # the live game offers other items: the reward changed, the way it is handed out did not
        self.assertEqual(check(record(choices=((1, 1), (2, 1))), row(offers=THREE))[0], [])

    def test_given_and_offered_says_what_the_live_game_does(self):
        both = row(gives=THREE, offers=THREE)
        self.assertEqual(check(record(items=THREE), both)[0][0][::5], ('twice', 'the live game gives it outright'))
        self.assertEqual(check(record(choices=THREE), both)[0][0][::5], ('twice', 'the live game offers it as a choice'))
        self.assertEqual(check(record(items=THREE, choices=THREE), both)[0][0][::5], ('twice', 'the live game sends it in both lists as well'))
        self.assertEqual(check(None, both)[0], [('twice', '19991,19992,20083', '19991,19992,20083', None, None, 'no record of the live game')])

    def test_a_row_from_a_later_build_is_the_newer_word(self):
        found, counts = check(record(items=THREE), row(offers=THREE, build=71100))
        self.assertEqual((found, counts), ([], {'row_newer': 1}))

    def test_a_record_that_cannot_be_read_compares_nothing(self):
        broken = record(items=THREE)
        broken['raceMask'] = 'everyone'
        self.assertEqual(check(broken, row(offers=THREE)), ([], {'record_unreadable': 1}))

    def test_an_amount_is_written_when_it_is_not_one(self):
        self.assertEqual(rewardkinds.written([(2589, 10), (118, 1)]), '2589x10,118')

    def test_a_quest_without_item_rewards_is_not_looked_at(self):
        self.assertEqual(check(record(items=THREE), row()), ([], {}))


if __name__ == '__main__':
    unittest.main()
