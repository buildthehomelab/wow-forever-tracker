"""python -m unittest discover -s tools/tests

Players' reports as evidence (ft.reports): a name and a place matched to the server's creature that stands there,
and which of a report site's lines are about Forever at all. No database: the names and spawns are given.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import reports  # noqa: E402

# a zone 1000 yards wide whose map's percentages are yards / 10, on map 1
WHERE = lambda zone, x, y: (1, x * 10.0, y * 10.0) if zone == 'Orgrimmar' else None
BOX = lambda zone: (1, 0.0, 0.0, 1000.0, 1000.0) if zone in ('Orgrimmar', 'The Barrens') else None


def matcher(creatures, spawns):
    return reports.Matcher({name.lower(): entries for name, entries in creatures.items()}, spawns, WHERE, BOX)


def pack(quests=(), items=()):
    return {'format': reports.FORMAT, 'quests': list(quests), 'items': list(items)}


class Names(unittest.TestCase):
    def test_the_creature_of_that_name_that_stands_there(self):
        npcs = matcher({'Furmund': [100]}, {100: [(1, 509.0, 653.0)]})
        self.assertEqual(npcs.find('furmund', 'Orgrimmar', 50.9, 65.3), (100, ''))
        self.assertEqual(npcs.find('Furmund'), (100, ''))                             # the only one of that name: no place needed
        self.assertEqual(npcs.find('Nobody', 'Orgrimmar', 1, 1), (None, 'name_unknown'))

    def test_two_of_a_name_are_told_apart_by_the_place(self):
        npcs = matcher({'Grunt': [200, 201]}, {200: [(1, 100.0, 100.0)], 201: [(1, 900.0, 900.0)]})
        self.assertEqual(npcs.find('Grunt', 'Orgrimmar', 10.2, 10.1), (200, ''))
        self.assertEqual(npcs.find('Grunt', 'Orgrimmar', 89.0, 90.5), (201, ''))
        self.assertEqual(npcs.find('Grunt', 'Orgrimmar', 50.0, 50.0), (None, 'several_same_name'))   # near neither
        self.assertEqual(npcs.find('Grunt'), (None, 'several_same_name'))                             # nothing to tell them by

    def test_two_of_a_name_standing_together_are_not_guessed(self):
        npcs = matcher({'Grunt': [200, 201]}, {200: [(1, 100.0, 100.0)], 201: [(1, 110.0, 100.0)]})
        self.assertEqual(npcs.find('Grunt', 'Orgrimmar', 10.2, 10.0), (None, 'several_same_name'))

    def test_a_creature_nobody_spawned_and_one_that_stands_elsewhere(self):
        npcs = matcher({'Elder': [300], 'Wanderer': [301]}, {301: [(1, 100.0, 100.0)]})
        self.assertEqual(npcs.find('Elder', 'Orgrimmar', 50, 50), (None, 'not_spawned'))
        self.assertEqual(npcs.find('Wanderer', 'Orgrimmar', 12.0, 12.0), (301, ''))               # 28 yards off: a rough pin
        self.assertEqual(npcs.find('Wanderer', 'Orgrimmar', 90.0, 90.0), (None, 'position_far'))  # 1,100 yards off: another one

    def test_a_zone_tells_two_of_a_name_apart_when_there_is_no_place(self):
        npcs = matcher({'Kolkar': [400, 401]}, {400: [(1, 500.0, 500.0)], 401: [(0, 500.0, 500.0)]})
        self.assertEqual(npcs.find('Kolkar', 'The Barrens'), (400, ''))
        self.assertEqual(npcs.find('Kolkar', 'Rare, The Barrens'), (400, ''))


class Evidence(unittest.TestCase):
    def setUp(self):
        self.npcs = matcher({'Furmund': [100], 'Sagorne': [101], 'Bale': [102], 'Defias Thug': [103], 'Twin': [104, 105]},
                            {100: [(1, 509.0, 653.0)], 101: [(1, 387.0, 359.0)], 102: [(1, 10.0, 10.0)], 103: [(1, 5.0, 5.0)],
                             104: [(1, 1.0, 1.0)], 105: [(1, 2.0, 2.0)]})
        self.objects = matcher({'Wanted Poster': [9000]}, {9000: [(1, 400.0, 400.0)]})

    def test_a_quest_players_saw(self):
        quest = {'id': 7, 'seen_by_players': True, 'start': [{'name': 'Furmund', 'zone': 'Orgrimmar', 'x': 50.9, 'y': 65.3}, {'name': 'Wanted Poster', 'zone': 'Orgrimmar', 'x': 40, 'y': 40}],
                 'end': [{'name': 'Sagorne', 'zone': 'Orgrimmar', 'x': 38.7, 'y': 35.9}]}
        ev, left = reports.evidence(pack([quest]), self.npcs, self.objects)
        self.assertEqual((ev['start'], ev['end'], left), ([['go', 9000, 7], ['npc', 100, 7]], [['npc', 101, 7]], {}))

    def test_a_quest_nobody_saw_is_classics_word(self):
        quest = {'id': 7, 'start': [{'name': 'Furmund', 'zone': 'Orgrimmar', 'x': 50.9, 'y': 65.3}]}
        ev, left = reports.evidence(pack([quest]), self.npcs, self.objects)
        self.assertEqual((ev['start'], left), ([], {'report_quest_not_seen': 1}))

    def test_what_cannot_be_matched_is_counted(self):
        quest = {'id': 7, 'seen_by_players': True, 'start': [{'name': 'Twin'}, {'name': 'Stranger'}, {'name': 'A Letter', 'item': 123}]}
        ev, left = reports.evidence(pack([quest]), self.npcs, self.objects)
        self.assertEqual((ev['start'], left), ([], {'report_several_same_name': 1, 'report_name_unknown': 1, 'report_quest_started_by_item': 1}))

    def test_vendors_and_counted_drops(self):
        item = {'id': 159, 'sources': [{'how': 'Sold by a vendor', 'name': 'Bale', 'place': 'Orgrimmar', 'x': 1.0, 'y': 1.0, 'price': 23},
                                       {'how': 'Sold by a vendor', 'name': 'Bale', 'place': 'Orgrimmar', 'x': 1.0, 'y': 1.0, 'price': 23},
                                       {'how': 'Creature drop', 'name': 'Defias Thug', 'place': 'Orgrimmar', 'rate': {'drops': 3, 'kills': 40}},
                                       {'how': 'Creature drop', 'name': 'Defias Thug', 'place': 'Orgrimmar', 'rate': {'percent': 6.7}},
                                       {'how': 'Creature drop', 'name': 'Bale', 'place': '', 'rate': {'drops': 1, 'kills': 4}},
                                       {'how': 'Reward of', 'name': 'Some Quest'}]}
        ev, left = reports.evidence(pack(items=[item]), self.npcs, self.objects)
        self.assertEqual(ev['sell'], [[102, 159, 0]])                    # once, whatever the pack repeats
        self.assertEqual(ev['drop'], [['npc', 103, 159, 7.5]])          # 3 in 40 kills
        self.assertEqual(left, {'report_drop_not_counted': 1, 'report_drop_few_kills': 1})   # Classic's percentage; four kills

    def test_another_file_is_refused(self):
        with self.assertRaises(ValueError):
            reports.evidence({'quests': []}, self.npcs)

    def test_the_names_to_look_up(self):
        found = reports.wanted_names(pack([{'id': 1, 'start': [{'name': ' Furmund '}, {'name': 'A Letter', 'item': 5}], 'end': [{'name': 'Sagorne'}]}],
                                          [{'id': 2, 'sources': [{'how': 'Sold by a vendor', 'name': 'Bale'}, {'how': 'Reward of', 'name': 'Quest'}]}]))
        self.assertEqual(found, {'furmund', 'sagorne', 'bale'})


if __name__ == '__main__':
    unittest.main()
