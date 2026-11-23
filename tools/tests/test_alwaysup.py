"""python -m unittest discover -s tools/tests

Always up (ft.alwaysup): creatures standing all the time that a script or a holiday should bring in only for a while.
No database and no network: the rows are given.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import alwaysup  # noqa: E402


def ref(counts=None, only=None):
    return {'counts': counts or {}, 'places': {}, 'event_only': only or {}}


GORILLA, KONDA, PROWLER, FOREVER_IMP = 1511, 1516, 1018, 250618
RIBBON, BATTLEMASTER, BAT = 17066, 347, 10716


class Summoned(unittest.TestCase):
    def test_a_creature_a_script_summons_and_no_reference_spawns_is_listed(self):
        spawns = {GORILLA: [(180831, 0), (180832, 0)]}
        causes = {GORILLA: ['SmartAI of action list 144900']}
        refs = {'vmangos': ref({(1, 0): [1, 1.0]}), 'azerothcore': ref()}
        found = list(alwaysup.summoned(spawns, causes, refs, {GORILLA: 'Enraged Silverback Gorilla'}))
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].kind, found[0].spawns, found[0].guids, found[0].maps), ('summoned', 2, [180831, 180832], [0]))
        self.assertIn('azerothcore, vmangos', found[0].witness)
        self.assertFalse(found[0].later)

    def test_a_reference_spawn_anywhere_keeps_it(self):
        # summoned somewhere, but the game also keeps it standing: Stoma the Ancient in AzerothCore's world
        spawns = {KONDA: [(1, 0)]}
        refs = {'vmangos': ref(), 'azerothcore': ref({(KONDA, 1): [1, 1.0]})}
        self.assertEqual(list(alwaysup.summoned(spawns, {KONDA: ['event script 1']}, refs)), [])

    def test_a_spawned_creature_nothing_summons_is_not_listed(self):
        self.assertEqual(list(alwaysup.summoned({PROWLER: [(1, 0)]}, {}, {'vmangos': ref()})), [])

    def test_a_later_creature_is_listed_and_marked_later(self):
        found = list(alwaysup.summoned({FOREVER_IMP: [(5, 2999)]}, {FOREVER_IMP: ['a summoning spell']}, {'vmangos': ref()}))
        self.assertTrue(found[0].later)
        self.assertIn('later creature', found[0].witness)


class Holidays(unittest.TestCase):
    def test_a_yearly_holiday_creature_up_all_year_is_listed(self):
        refs = {'azerothcore': ref(only={RIBBON: [(1, 'Midsummer Fire Festival', True)]})}
        found = list(alwaysup.holidays({RIBBON: [(46888, 1)]}, {}, refs))
        self.assertEqual([(f.kind, f.guids) for f in found], [('holiday', [46888])])
        self.assertIn('Midsummer Fire Festival (azerothcore)', found[0].cause)

    def test_another_cores_own_event_alone_is_not_a_holiday(self):
        # AzerothCore puts battlemasters on Call to Arms; Classic keeps them up
        refs = {'azerothcore': ref(only={BATTLEMASTER: [(18, 'Call to Arms: Alterac Valley!', False)]})}
        self.assertEqual(list(alwaysup.holidays({BATTLEMASTER: [(1, 0)]}, {}, refs)), [])

    def test_our_own_event_holding_other_spawns_makes_it_count(self):
        refs = {'azerothcore': ref(only={BAT: [(73, 'Hourly Bells', False)]})}
        found = list(alwaysup.holidays({BAT: [(21200026, 0)]}, {BAT: {78}}, refs))
        self.assertEqual(len(found), 1)
        self.assertIn('our event 78', found[0].witness)

    def test_a_reference_that_keeps_it_up_wins(self):
        refs = {'azerothcore': ref(only={RIBBON: [(1, 'Midsummer Fire Festival', True)]}), 'vmangos': ref({(RIBBON, 1): [2, 2.0]})}
        self.assertEqual(list(alwaysup.holidays({RIBBON: [(1, 1)]}, {}, refs)), [])


class Running(unittest.TestCase):
    def test_both_kinds_counted(self):
        refs = {'azerothcore': ref(only={RIBBON: [(1, 'Midsummer Fire Festival', True)]})}
        found, tally = alwaysup.run({RIBBON: [(1, 1)], GORILLA: [(2, 0)]}, {}, {GORILLA: ['x']}, refs)
        self.assertEqual([f.kind for f in found], ['summoned', 'holiday'])
        self.assertEqual(tally, {'summoned': 1, 'holiday': 1})


if __name__ == '__main__':
    unittest.main()
