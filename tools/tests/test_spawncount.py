"""python -m unittest discover -s tools/tests

Spawn audit (ft.spawncount, ft.spawnrefs): spots and how many are up, against other cores' worlds. No database and no
network: the rows are given.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import spawncount, spawnrefs  # noqa: E402
from ft.spawncount import Pools, Row  # noqa: E402


def row(guid, entries, x=0.0, y=0.0, map_id=0):
    return Row(guid, tuple(entries) if isinstance(entries, (list, tuple)) else (entries,), map_id, float(x), float(y), 0.0)


def ref(rows, pools=None, events=()):
    return {'counts': spawncount.count(rows, pools, events), 'places': spawncount.places(rows, events)}


class Counting(unittest.TestCase):
    def test_a_spawn_outside_pools_is_one_spot_and_one_up(self):
        self.assertEqual(spawncount.count([row(1, 1134), row(2, 1134), row(3, 1135)]), {(1134, 0): [2, 2.0], (1135, 0): [1, 1.0]})

    def test_a_pool_keeps_its_limit_up_of_all_its_spots(self):
        # the Grizzled Den's mouth: 12 spots in a pool of 6 are 12 spots and 6 up
        rows = [row(g, 1134, x=g * 10) for g in range(1, 13)]
        pools = Pools({900: 6}, {g: 900 for g in range(1, 13)})
        spots, up = spawncount.count(rows, pools)[(1134, 0)]
        self.assertEqual(spots, 12)
        self.assertAlmostEqual(up, 6.0)

    def test_a_spot_that_picks_among_creatures_is_a_spot_of_each_and_a_share_up(self):
        counts = spawncount.count([row(1, [1161, 1162])])     # VMaNGOS id, id2
        self.assertEqual(counts[(1161, 0)], [1, 0.5])
        self.assertEqual(counts[(1162, 0)], [1, 0.5])
        # the same spot the TrinityCore way: two rows in a pool of one
        same = spawncount.count([row(1, 1161), row(2, 1162)], Pools({5: 1}, {1: 5, 2: 5}))
        self.assertEqual(same, counts)

    def test_a_pool_inside_a_pool_multiplies(self):
        # two child pools of two spots each, one spot of each child, and the mother shows one child
        rows = [row(g, 7) for g in (1, 2, 3, 4)]
        pools = Pools({10: 1, 11: 1, 20: 1}, {1: 10, 2: 10, 3: 11, 4: 11}, None, {10: 20, 11: 20})
        self.assertAlmostEqual(spawncount.count(rows, pools)[(7, 0)][1], 1.0)

    def test_a_pool_by_creature_counts_every_spawn_of_it(self):
        rows = [row(g, 99) for g in (1, 2, 3, 4)]
        self.assertAlmostEqual(spawncount.count(rows, Pools({3: 1}, None, {99: 3}))[(99, 0)][1], 1.0)

    def test_a_limit_at_or_past_the_members_shows_them_all_and_event_spawns_are_left_out(self):
        rows = [row(1, 5), row(2, 5), row(3, 5)]
        self.assertEqual(spawncount.count(rows, Pools({1: 5}, {1: 1, 2: 1}), events={3})[(5, 0)], [2, 2.0])


class Picked(unittest.TestCase):
    def test_a_spawn_whose_creature_a_script_picks_is_a_spot_of_each(self):
        # Blackwing Lair stores 200 red whelps in a pool of 134; the instance script rolls one of four colours
        rows = [row(g, 14022, x=g, map_id=469) for g in range(1, 201)] + [row(999, 14022, map_id=0)]
        swapped = spawncount.picked(rows, [{'map': 469, 'stored': 14022, 'picks': [14022, 14023, 14024, 14025]}])
        counts = spawncount.count(swapped, Pools({7: 134}, {g: 7 for g in range(1, 201)}))
        for colour in (14022, 14023, 14024, 14025):
            self.assertEqual(counts[(colour, 469)][0], 200)
            self.assertAlmostEqual(counts[(colour, 469)][1], 33.5)
        self.assertEqual(counts[(14022, 0)], [1, 1.0])              # the same entry on another map is itself
        self.assertEqual(spawncount.verdict(33.5, {'vmangos': 50, 'azerothcore': 40, 'trinitycore': 40}), 'ok')

    def test_a_line_that_does_not_read_is_left_out(self):
        rows = [row(1, 5)]
        self.assertEqual(spawncount.picked(rows, [{'map': 0}, {'map': 0, 'stored': 5, 'picks': []}, 'x']), rows)
        self.assertEqual(spawncount.picked(rows, None), rows)

    def test_the_file_the_tracker_ships_reads(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'world', 'spawn_picks.json')
        with open(path, encoding='utf-8') as handle:
            picks = json.load(handle)['picks']
        self.assertTrue(picks and all(p['stored'] in p['picks'] for p in picks))


class Verdicts(unittest.TestCase):
    def test_above_every_reference(self):
        self.assertEqual(spawncount.verdict(14, {'vmangos': 5, 'azerothcore': 5, 'trinitycore': 5}), 'above_all')

    def test_the_later_game_explains_it(self):
        self.assertEqual(spawncount.verdict(26, {'vmangos': 6, 'azerothcore': 26, 'trinitycore': 26}), 'above_classic')

    def test_within_below_and_unknown(self):
        self.assertEqual(spawncount.verdict(27, {'vmangos': 26, 'azerothcore': 26}), 'ok')
        self.assertEqual(spawncount.verdict(3, {'vmangos': 40, 'azerothcore': 38}), 'below_all')
        self.assertEqual(spawncount.verdict(9, {'vmangos': 0, 'azerothcore': 0}), 'unknown')
        # a reference that does not have the creature there is no witness against it
        self.assertEqual(spawncount.verdict(30, {'vmangos': 0, 'azerothcore': 30}), 'ok')


class Auditing(unittest.TestCase):
    def test_a_second_spawn_set_over_the_first(self):
        classic = [row(g, 1134, x=g * 50) for g in range(1, 6)]
        refs = {'vmangos': ref(classic), 'azerothcore': ref(classic)}
        ours = [row(20000000 + r.guid, 1134, x=r.x) for r in classic] + [row(g, 1134, x=1000 + g * 20) for g in range(1, 10)]
        found = {(a.entry, a.map): a for a in spawncount.audit(ours, Pools(), set(), refs)}
        a = found[(1134, 0)]
        self.assertEqual((a.verdict, a.spots, a.up, a.unmatched), ('above_all', 14, 14.0, 9))
        self.assertEqual(a.guids, list(range(1, 10)))            # the rows no reference has a spot for
        self.assertEqual(a.refs['vmangos'], [5, 5.0])

    def test_pooling_the_extra_spots_brings_it_back_within(self):
        classic = [row(g, 1134, x=g * 50) for g in range(1, 6)]
        ours = [row(g, 1134, x=g * 20) for g in range(1, 15)]
        pools = Pools({1: 5}, {g: 1 for g in range(1, 15)})
        a = next(spawncount.audit(ours, pools, set(), {'vmangos': ref(classic)}))
        self.assertEqual((a.verdict, a.spots, a.up), ('ok', 14, 5.0))

    def test_a_spot_only_a_later_core_has_is_told_apart(self):
        refs = {'vmangos': ref([row(1, 4382, x=0)]), 'azerothcore': ref([row(1, 4382, x=0), row(2, 4382, x=300)])}
        a = next(spawncount.audit([row(1, 4382, x=1), row(2, 4382, x=301), row(3, 4382, x=900)], Pools(), set(), refs))
        self.assertEqual((a.unmatched, a.later, a.guids), (1, 1, [3]))

    def test_what_classic_spawns_and_the_server_does_not_is_listed_and_other_maps_are_not(self):
        refs = {'vmangos': ref([row(g, 40, x=g * 9) for g in range(1, 9)] + [row(50, 41, map_id=530)])}
        found = list(spawncount.audit([row(1, 7)], Pools(), set(), refs))
        self.assertEqual([(a.entry, a.map, a.verdict) for a in found], [(7, 0, 'unknown'), (40, 0, 'below_all')])


MYSQLDUMP = """CREATE TABLE `creature` (
  `guid` int unsigned NOT NULL,
  `id` int unsigned NOT NULL,
  `map` smallint unsigned NOT NULL,
  `position_x` float NOT NULL,
  `position_y` float NOT NULL,
  `position_z` float NOT NULL,
  PRIMARY KEY (`guid`)
) ENGINE=InnoDB;
INSERT INTO `creature` VALUES (1,1134,0,1.5,2,3),(2,1134,0,40,2,3),(3,721,1,0,0,0);
CREATE TABLE `pool_template` (
  `entry` int unsigned NOT NULL,
  `max_limit` int unsigned NOT NULL,
  `description` varchar(255)
) ENGINE=InnoDB;
INSERT INTO `pool_template` VALUES (7,1,'Wendigo (one, two)');
CREATE TABLE `pool_members` (
  `type` smallint unsigned NOT NULL,
  `spawnId` int unsigned NOT NULL,
  `poolSpawnId` int unsigned NOT NULL
) ENGINE=InnoDB;
INSERT INTO `pool_members` VALUES (0,1,7),(0,2,7),(1,3,7);
CREATE TABLE `game_event_creature` (
  `eventEntry` tinyint NOT NULL,
  `guid` int unsigned NOT NULL
) ENGINE=InnoDB;
INSERT INTO `game_event_creature` VALUES (12,3);
"""

AZEROTHCORE = """CREATE TABLE IF NOT EXISTS `creature` (
  `guid` int unsigned NOT NULL,
  `id1` int unsigned NOT NULL,
  `id2` int unsigned NOT NULL,
  `id3` int unsigned NOT NULL,
  `map` smallint unsigned NOT NULL,
  `position_x` float NOT NULL,
  `position_y` float NOT NULL,
  `position_z` float NOT NULL
) ENGINE=InnoDB;
INSERT INTO `creature` VALUES
(1,1161,1162,0,0,1,2,3),
(2,1161,0,0,0,9,2,3);
"""


class Reading(unittest.TestCase):
    def test_a_mysqldump_with_trinitycore_pools(self):
        creatures = spawnrefs.from_tables(spawnrefs.read_dump(MYSQLDUMP.splitlines(True)))
        self.assertEqual(creatures['1134']['0'][:2], [2, 1.0])       # two spots, one up
        self.assertEqual(creatures['1134']['0'][2], [[1.5, 2.0, 3.0], [40.0, 2.0, 3.0]])
        self.assertNotIn('721', creatures)                           # a world event's spawn

    def test_azerothcore_one_row_per_line_and_several_ids(self):
        creatures = spawnrefs.from_tables(spawnrefs.read_dump(AZEROTHCORE.splitlines(True)))
        self.assertEqual(creatures['1161']['0'][:2], [2, 1.5])
        self.assertEqual(creatures['1162']['0'][:2], [1, 0.5])

    def test_a_pack_is_kept_and_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            dump = os.path.join(folder, 'creature.sql')
            with open(dump, 'w', encoding='utf-8') as handle:
                handle.write(AZEROTHCORE)
            spawnrefs.save(folder, spawnrefs.make('azerothcore', [dump], 'abc'))
            refs = spawnrefs.load(folder)
        self.assertEqual(list(refs), ['azerothcore'])
        self.assertEqual(refs['azerothcore']['counts'][(1161, 0)], [2, 1.5])
        self.assertEqual(refs['azerothcore']['places'][(1162, 0)], [(1.0, 2.0, 3.0)])
        self.assertEqual(refs['azerothcore']['version'], 'abc')

    def test_fetching_azerothcore_asks_for_its_pinned_files(self):
        asked = []

        def http(url):
            asked.append(url)
            return (AZEROTHCORE if url.endswith('/creature.sql') else '-- nothing\n').encode()

        with tempfile.TemporaryDirectory() as folder:
            path = spawnrefs.fetch('azerothcore', folder, http)
            with open(path, encoding='utf-8') as handle:
                made = json.load(handle)
        self.assertEqual(made['version'], spawnrefs.AZEROTHCORE_COMMIT)
        self.assertEqual(len(asked), len(spawnrefs.AZEROTHCORE_FILES))
        self.assertTrue(all(spawnrefs.AZEROTHCORE_COMMIT in url for url in asked))

    def test_trinitycore_without_a_7z_program_is_skipped_with_a_reason(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(spawnrefs.RefError) as raised:
            spawnrefs.fetch('trinitycore', folder, lambda url: b'', seven_zip='')
            # an empty name: nothing to run
        self.assertIn('7z', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
