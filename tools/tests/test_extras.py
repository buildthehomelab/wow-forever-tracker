"""python -m unittest discover -s tools/tests

Extras (ft.extras): what the server holds that the live game does not. No database: the rows are given.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import extras  # noqa: E402
from ft.extras import Spawn  # noqa: E402


class Twins(unittest.TestCase):
    def test_classic_copy_of_a_forever_creature(self):
        # the Steelgrill's Depot mechanostriders: both sets spawned, live only ever sent Forever's
        spawned = {12365: 1, 267683: 1, 12364: 1}
        names = {12365: 'Red Mechanostrider', 267683: 'Red Mechanostrider', 12364: 'Icy Blue Mechanostrider Mod A'}
        found = list(extras.twins(spawned, names, {267683: 'Red Mechanostrider'}))
        self.assertEqual([(f.entry, f.live) for f in found], [(12365, [267683])])
        self.assertIn('remove', found[0].note)

    def test_no_live_spawn_means_swap_not_remove(self):
        found = list(extras.twins({100: 3}, {100: 'Guard'}, {900: 'guard'}))
        self.assertEqual(found[0].server, 3)
        self.assertIn('give these spawns the live entry', found[0].note)

    def test_recorded_or_unmatched_is_left_alone(self):
        self.assertEqual(list(extras.twins({1: 1, 2: 1}, {1: 'A', 2: 'B'}, {1: 'A'})), [])

    def test_only_spawns_beside_a_live_spawn_are_removed(self):
        # Ironforge's Red Mechanostrider stands on Forever's; Bub's live copy is 1,300 yards away (2026-11-21 check)
        rows = [spawn(20001725, 12365, 'Red Mechanostrider', -5461.2, -619.6), spawn(46110001, 267683, 'Red Mechanostrider', -5461.3, -619.6),
                spawn(27467700, 274677, 'Bub', 0.0, 0.0), spawn(21200445, 274854, 'Bub', 1336.8, 0.0)]
        names = {12365: 'Red Mechanostrider', 267683: 'Red Mechanostrider', 274677: 'Bub', 274854: 'Bub'}
        found = list(extras.twins({12365: 1, 267683: 1, 274677: 1, 274854: 1}, names, {267683: 'Red Mechanostrider', 274854: 'Bub'}, rows))
        removed = [f for f in found if f.guid is not None]
        self.assertEqual([(f.guid, f.live) for f in removed], [(20001725, [267683])])
        self.assertIn('guid 46110001', removed[0].note)
        bub = [f for f in found if f.entry == 274677]
        self.assertEqual((bub[0].guid, bub[0].server), (None, 1))
        self.assertIn('left alone', bub[0].note)

    def test_distance_phase_and_events_count(self):
        names = {1: 'Chicken', 2: 'Chicken'}
        live = {2: 'Chicken'}
        near = [spawn(10, 1, 'Chicken', 0, 0), spawn(20, 2, 'Chicken', 14.9, 0)]
        far = [spawn(10, 1, 'Chicken', 0, 0), spawn(20, 2, 'Chicken', 15.1, 0)]
        other_map = [spawn(10, 1, 'Chicken', 0, 0), spawn(20, 2, 'Chicken', 0, 0, map_id=1)]
        other_phase = [spawn(10, 1, 'Chicken', 0, 0), spawn(20, 2, 'Chicken', 0, 0, phase=169)]
        holiday = [spawn(10, 1, 'Chicken', 0, 0, events=(12,)), spawn(20, 2, 'Chicken', 0, 0)]
        for rows, removed in ((near, [10]), (far, []), (other_map, []), (other_phase, []), (holiday, [])):
            found = list(extras.twins({1: 1, 2: 1}, names, live, rows))
            self.assertEqual([f.guid for f in found if f.guid is not None], removed)

    def test_no_live_spawn_still_says_swap(self):
        found = list(extras.twins({100: 3}, {100: 'Guard'}, {900: 'guard'}, [spawn(1, 100, 'Guard', 0, 0)]))
        self.assertEqual((found[0].guid, found[0].server), (None, 3))
        self.assertIn('give these spawns the live entry', found[0].note)


def spawn(guid, entry, name, x, y, z=0.0, kind='npc', phase=0, group=0, map_id=0, events=()):
    return Spawn(kind, guid, entry, name, map_id, x, y, z, phase, group, events)


class Stacked(unittest.TestCase):
    def test_keeps_the_live_entry(self):
        rows = [spawn(20001725, 12365, 'Red Mechanostrider', -5461.2, -619.6), spawn(46110001, 267683, 'Red Mechanostrider', -5461.3, -619.6)]
        found = list(extras.stacked(rows, live={('npc', 267683)}))
        self.assertEqual([(f.guid, f.entry) for f in found], [(20001725, 12365)])
        self.assertIn('keep guid 46110001 (the live entry)', found[0].note)

    def test_same_entry_copies_keep_the_oldest(self):
        rows = [spawn(5, 7, 'Barrel', 1, 1, kind='go'), spawn(3, 7, 'Barrel', 1.2, 1, kind='go'), spawn(9, 7, 'Barrel', 1.4, 1.1, kind='go')]
        found = list(extras.stacked(rows))
        self.assertEqual(sorted(f.guid for f in found), [5, 9])
        self.assertTrue(all('keep guid 3' in f.note for f in found))

    def test_far_apart_other_phase_pooled_or_other_name(self):
        rows = [spawn(1, 7, 'Wolf', 0, 0), spawn(2, 7, 'Wolf', 1.5, 0), spawn(3, 7, 'Wolf', 0, 0.5, phase=170),
                spawn(6, 9, 'Chair', 10, 10, kind='go'), spawn(7, 9, 'Chair', 11, 10, kind='go'),
                spawn(4, 8, 'Bear', 0, 0.3), spawn(5, 7, 'Wolf', 0.2, 0.2)]
        self.assertEqual(list(extras.stacked(rows, pooled={('npc', 5)})), [])

    def test_holiday_copies_are_not_stacked(self):
        rows = [spawn(1, 7, 'Campfire', 0, 0, kind='go', events=(12,)), spawn(2, 7, 'Campfire', 0, 0, kind='go', events=(1,)),
                spawn(3, 7, 'Campfire', 0, 0.1, kind='go', events=(12,))]
        self.assertEqual([f.guid for f in extras.stacked(rows)], [3])

    def test_across_a_cell_edge(self):
        rows = [spawn(1, 7, 'Wolf', 0.9, 0), spawn(2, 7, 'Wolf', 1.1, 0)]
        self.assertEqual([f.guid for f in extras.stacked(rows)], [2])

    def test_height_counts(self):
        # a creature upstairs is not on top of the one below
        self.assertEqual(list(extras.stacked([spawn(1, 7, 'Wolf', 0, 0, 0), spawn(2, 7, 'Wolf', 0, 0, 3)])), [])


class Crowded(unittest.TestCase):
    def test_far_more_than_wowhead_marks(self):
        ours = {(5, 0): [(i, 0) for i in range(9)] + [(5000, 5000)]}
        found = list(extras.crowded(ours, {5: {0: [(0, 0), (8, 0)]}}, {5: 'Kobold'}))
        self.assertEqual([(f.entry, f.server, f.live) for f in found], [(5, 9, [2])])

    def test_close_to_wowhead_or_no_points(self):
        ours = {(5, 0): [(i, 0) for i in range(6)], (6, 0): [(0, 0)] * 30}
        self.assertEqual(list(extras.crowded(ours, {5: {0: [(0, 0), (8, 0)]}}, {})), [])


class Invented(unittest.TestCase):
    def test_stand_ins_and_unknown_creatures(self):
        spawned = {('go', 8380101): 1, ('go', 8380102): 1, ('go', 2061): 1585, ('go', 652087): 1, ('npc', 70): 2, ('npc', 71): 1,
                   ('npc', 8110000): 26, ('npc', 72): 1}
        verdict = {('go', 2061): 'unknown', ('go', 652087): 'unknown', ('npc', 70): None, ('npc', 71): 'unknown', ('npc', 72): 'forever'}
        asked = []

        def wowhead(kind, entry):
            asked.append((kind, entry))
            return verdict.get((kind, entry))
        found = list(extras.invented(spawned, {('go', 8380101): 'Portal to Stormwind'}, {('npc', 999)}, wowhead))
        # the campfire and Forever's Ironforge plaque: Wowhead lists neither, which proves nothing for an object
        self.assertEqual([(f.kind, f.entry) for f in found], [('go', 8380101), ('go', 8380102), ('npc', 71), ('npc', 8110000)])
        self.assertIn('Keep it until the real entry is found', found[0].note)
        self.assertIn('not on Wowhead', found[2].note)
        # objects and stand-ins cost no Wowhead question
        self.assertEqual(sorted(asked), [('npc', 70), ('npc', 71), ('npc', 72)])


class Givers(unittest.TestCase):
    def test_a_giver_live_never_used(self):
        server = {('npc', 1, 100, 'gives'), ('npc', 2, 100, 'gives'), ('npc', 3, 200, 'takes'), ('npc', 4, 300, 'gives')}
        live = {('npc', 2, 100, 'gives'), ('object', 9, 200, 'takes')}
        found = list(extras.givers(server, live, {('npc', 1): 'Old Giver', ('object', 9): 'Chest'}))
        self.assertEqual([(f.entry, f.server, f.live) for f in found], [(1, 100, [2]), (3, 200, [9])])
        self.assertIn('Chest (object 9)', found[1].note)


if __name__ == '__main__':
    unittest.main()
