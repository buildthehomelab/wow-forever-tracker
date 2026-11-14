"""python -m unittest discover -s tools/tests

Boss encounters (ft.bosses): the client's rows that are no boss of their own, and how a boss is found on the server.
The rows are the client's own for Blackfathom Deeps and the Sunken Temple (build 70862).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import bosses  # noqa: E402

BFD, TEMPLE, STRATHOLME = 48, 109, 329


def boss(name, map_id, difficulty=0):
    return {'name': name, 'name_en': name, 'map': map_id, 'facts': {'difficulty': difficulty}}


def npc(entry, name, **more):
    return {'id': entry, 'name': name, 'scripted': False, **more}


class Shadows(unittest.TestCase):
    def setUp(self):
        self.bosses = {
            2694: boss('Baron Aquanis', BFD, 198), 2697: boss('Ghamoo-ra', BFD, 198), 2704: boss('Gelihast', BFD, 198),
            2761: boss('Ghamoo-ra', BFD, 201), 2763: boss('Geilhast', BFD, 201), 2767: boss("Aku'mai", BFD, 201),
            2910: boss("Aku'mai", BFD, 1), 2914: boss('Geilhast', BFD), 2916: boss('Ghamoo-ra', BFD),
            492: boss('Avatar of Hakkar', TEMPLE, 201), 2956: boss('Avatar of Hakkar', TEMPLE, 215), 3583: boss('Avatar of Hakkar', TEMPLE),
            478: boss('Balnazzar', STRATHOLME), 3185: boss('Balnazzar', 2856),
        }
        self.shadows = bosses.shadows(self.bosses)

    def test_season_of_discovery_raid_versions_are_no_bosses(self):
        for boss_id in (2694, 2697, 2704, 2956):
            self.assertEqual(self.shadows[boss_id], ('season', 0), boss_id)

    def test_a_fight_listed_again_is_counted_once_under_its_lowest_id(self):
        self.assertEqual(self.shadows[2910], ('duplicate', 2767))
        self.assertEqual(self.shadows[2914], ('duplicate', 2763))
        self.assertEqual(self.shadows[2916], ('duplicate', 2761))
        self.assertEqual(self.shadows[3583], ('duplicate', 492))
        for kept in (2761, 2763, 2767, 492):
            self.assertNotIn(kept, self.shadows)

    def test_the_same_name_in_another_instance_is_another_boss(self):
        self.assertNotIn(478, self.shadows)
        self.assertNotIn(3185, self.shadows)

    def test_a_season_row_never_keeps_the_place_of_the_real_one(self):
        # Gelihast 2704 is Season of Discovery's: the first real row (the client's "Geilhast") is the one kept
        self.assertNotIn(2763, self.shadows)


class Find(unittest.TestCase):
    def test_spawned_by_name(self):
        found, how = bosses.find(2761, boss('Ghamoo-ra', BFD), [npc(4887, 'Ghamoo-Ra')])
        self.assertEqual((found['id'], how), (4887, 'spawned'))

    def test_the_clients_misspelling_still_finds_the_creature(self):
        found, how = bosses.find(2763, boss('Geilhast', BFD), [npc(6243, 'Gelihast')])
        self.assertEqual((found['id'], how), (6243, 'spawned'))

    def test_a_short_name_inside_a_longer_one(self):
        found, _ = bosses.find(2742, boss('Sneed', 36), [npc(642, "Sneed's Shredder")])
        self.assertEqual(found['id'], 642)
        self.assertEqual(bosses.find(1, boss('Skum', 43), [npc(2, 'Skumbag Raider')]), (None, None))  # too short to guess from

    def test_an_event_is_found_by_one_of_its_creatures(self):
        found, how = bosses.find(243, boss('The Seven', 230), [npc(9039, "Doom'rel")])
        self.assertEqual((found['id'], how), (9039, 'spawned'))
        found, _ = bosses.find(478, boss('Balnazzar', STRATHOLME), [npc(10812, 'Grand Crusader Dathrohan')])
        self.assertEqual(found['id'], 10812)

    def test_a_boss_a_script_summons_is_there(self):
        mutanus = npc(3654, 'Mutanus the Devourer', script=False)
        self.assertEqual(bosses.find(592, boss('Mutanus the Devourer', 43), [], [mutanus]), (None, None))
        found, how = bosses.find(592, boss('Mutanus the Devourer', 43), [], [mutanus], summoned={3654})
        self.assertEqual((found['id'], how), (3654, 'summoned'))

    def test_a_scripted_boss_counts_only_in_an_instance_with_a_script(self):
        ramstein = npc(10439, 'Ramstein the Gorger', script=True)
        self.assertEqual(bosses.find(483, boss('Ramstein the Gorger', STRATHOLME), [], [ramstein]), (None, None))
        found, how = bosses.find(483, boss('Ramstein the Gorger', STRATHOLME), [], [ramstein], instance_scripted=True)
        self.assertEqual((found['id'], how), (10439, 'scripted'))  # a guess: no summon of him is known
        found, how = bosses.find(483, boss('Ramstein the Gorger', STRATHOLME), [], [ramstein], summoned={10439}, instance_scripted=True)
        self.assertEqual((found['id'], how), (10439, 'summoned'))

    def test_the_creature_the_instance_script_names_is_the_boss(self):
        # the core's Zul'Farrak script counts creature 7273 as encounter 594 and creates it from a variable:
        # no table and no SummonCreature(NPC_...) call says so, and the template has no script of its own
        gahzrilla = npc(7273, "Gahz'rilla", script=False)
        self.assertEqual(bosses.find(594, boss("Gahz'rilla", 209), [], [gahzrilla]), (None, None))
        found, how = bosses.find(594, boss("Gahz'rilla", 209), [], [gahzrilla], bound=[7273])
        self.assertEqual((found['id'], how), (7273, 'summoned'))
        # spawned under another name than the client's: the script's word is enough
        found, how = bosses.find(2810, boss('Ras Frostwhisperer', 289), [npc(1, 'Scholomance Student'), npc(10508, 'Ras Frostwhisper')], bound=[10508])
        self.assertEqual((found['id'], how), (10508, 'spawned'))

    def test_an_exact_name_wins_over_a_longer_one(self):
        spawned = [npc(15589, "Eye of C'Thun"), npc(15727, "C'Thun")]
        self.assertEqual(bosses.find(717, boss("C'Thun", 531), spawned)[0]['id'], 15727)

    def test_a_name_inside_another_word_is_not_the_boss(self):
        self.assertEqual(bosses.find(1084, boss('Onyxia', 249), [npc(12129, 'Onyxian Warder')]), (None, None))
        self.assertEqual(bosses.find(793, boss('Hakkar', 309), [npc(11830, 'Hakkari Priest')]), (None, None))

    def test_a_long_name_a_letter_or_two_off(self):
        found, _ = bosses.find(2810, boss('Ras Frostwhisperer', 289), [npc(10508, 'Ras Frostwhisper')])
        self.assertEqual(found['id'], 10508)

    def test_a_template_nothing_brings_in_stays_a_gap(self):
        template = npc(260001, 'Nanaya', script=False)
        self.assertEqual(bosses.find(3502, boss('Nanaya', 3001), [], [template], summoned={1}, instance_scripted=True), (None, None))

    def test_an_unspawned_creature_needs_the_whole_name(self):
        # "Hakkar" inside "Avatar of Hakkar" is enough for a creature standing in the instance, not for a template
        template = npc(8443, 'Avatar of Hakkar Image', script=True)
        self.assertEqual(bosses.find(492, boss('Avatar of Hakkar', TEMPLE), [], [template], instance_scripted=True), (None, None))


if __name__ == '__main__':
    unittest.main()
