"""python -m unittest discover -s tools/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import classstats  # noqa: E402

# warrior base stats by level (the realm's player_classlevelstats, Spirit 20/20/21/21 at 1-4), race offsets as on the realm
LEVELS = {(1, lv): {'str': 23, 'agi': 20, 'sta': 22, 'inte': 20, 'spi': spi} for lv, spi in ((1, 20), (2, 20), (3, 21), (4, 21))}
RACES = {1: {'spi': 1}, 2: {'str': 3, 'agi': -3, 'sta': 2, 'inte': -3, 'spi': 3}, 3: {'str': 2, 'agi': -4, 'sta': 3, 'inte': -1, 'spi': -1},
         95: {'str': -3, 'agi': 4, 'sta': -1, 'inte': 4, 'spi': -3}}


class Formulas(unittest.TestCase):
    def test_warrior_regen_and_the_dwarf_floor(self):
        self.assertAlmostEqual(classstats.hp_regen(1, 18), 0.08, places=2)          # the Skyborne warrior at level 4
        self.assertAlmostEqual(classstats.hp_regen_floored(1, 18, 20), 2.6, places=2)  # with a Dwarf's 20 Spirit
        self.assertEqual(classstats.hp_regen(1, 10), 0.0)                             # never below 0
        self.assertEqual(classstats.hp_regen_floored(1, 30, 20), classstats.hp_regen(1, 30))  # the floor never lowers it

    def test_attack_power_and_mana(self):
        s = {'str': 20, 'agi': 20, 'sta': 20, 'inte': 20, 'spi': 20}
        self.assertEqual(classstats.melee_ap(1, 1, s), 23)   # 3 + 40 - 20
        self.assertEqual(classstats.ranged_ap(3, 1, s), 32)  # 2 + 40 - 10
        self.assertEqual(classstats.mana_regen(1, 20), 0.0)
        self.assertAlmostEqual(classstats.mana_regen(8, 20), 8.75)


class Check(unittest.TestCase):
    def test_without_the_floor_the_skyborne_warrior_is_found(self):
        combos = {(1, 1), (2, 1), (95, 1)}   # no Dwarf warrior: no floor, as on a core before #144
        found = classstats.check(combos, LEVELS, RACES, max_level=4)
        self.assertEqual([f[:5] for f in found], [(95, 1, 'hp_regen', 1, 4)])

    def test_the_floor_clears_it(self):
        combos = {(1, 1), (2, 1), (3, 1), (95, 1)}
        self.assertEqual(classstats.check(combos, LEVELS, RACES, max_level=4), [])

    def test_a_stat_at_zero_and_no_attack_power(self):
        races = dict(RACES); races[99] = {'str': -23, 'agi': -20}
        found = classstats.check({(99, 1), (3, 1)}, LEVELS, races, max_level=1)
        issues = {f[2] for f in found}
        self.assertIn('stat', issues)
        self.assertIn('melee_ap', issues)

    def test_only_what_players_can_make(self):
        combos = {(1, 1), (1, 6), (27, 1), (95, 1)}   # a Death Knight and an allied race are not made on Forever
        self.assertEqual(classstats.playable(combos, {1, 95}), {(1, 1), (95, 1)})

    def test_levels_run_together(self):
        self.assertEqual(classstats._runs([3, 4, 5, 9]), [(3, 5), (9, 9)])


if __name__ == '__main__':
    unittest.main()
