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

    def test_one_drop_is_a_sighting_and_an_item_everything_drops_is_nobodys_own(self):
        once = {'id': 262890, 'sources': [{'how': 'Creature drop', 'name': 'Defias Thug', 'place': 'Orgrimmar', 'rate': {'drops': 1, 'kills': 256}}]}
        crate = {'id': 248690, 'sources': [{'how': 'Creature drop', 'name': f'Creature {n}', 'place': '', 'rate': {'drops': 3, 'kills': 400}} for n in range(14)]
                 + [{'how': 'Creature drop', 'name': 'Defias Thug', 'place': 'Orgrimmar', 'rate': {'drops': 3, 'kills': 400}}]}
        beads = {'id': 263439, 'sources': [{'how': 'Creature drop', 'name': 'Defias Thug', 'place': 'Orgrimmar', 'rate': {'drops': 83, 'kills': 156}}]}
        ev, left = reports.evidence(pack(items=[once, crate, beads]), self.npcs, self.objects)
        self.assertEqual(ev['drop'], [['npc', 103, 263439, 53.2051]])
        self.assertEqual(left, {'report_drop_seen_once': 1, 'report_drop_world': 15})

    def test_another_file_is_refused(self):
        with self.assertRaises(ValueError):
            reports.evidence({'quests': []}, self.npcs)

    def test_the_names_to_look_up(self):
        found = reports.wanted_names(pack([{'id': 1, 'start': [{'name': ' Furmund '}, {'name': 'A Letter', 'item': 5}], 'end': [{'name': 'Sagorne'}]}],
                                          [{'id': 2, 'sources': [{'how': 'Sold by a vendor', 'name': 'Bale'}, {'how': 'Reward of', 'name': 'Quest'}]}]))
        self.assertEqual(found, {'furmund', 'sagorne', 'bale'})



class Sides(unittest.TestCase):
    def test_the_side_a_quest_is_for_as_the_site_words_it(self):
        both = {'Alliance', 'Horde'}
        self.assertEqual([reports.side_of(t) for t in ('Alliance', 'Horde', 'Both factions', 'Night Elf', 'Tauren',
                                                       'Human, Orc, Dwarf, Night Elf, Undead, Tauren, Gnome, Troll', 'Human, Dwarf')],
                         [{'Alliance'}, {'Horde'}, both, {'Alliance'}, {'Horde'}, both, {'Alliance'}])
        self.assertEqual((reports.side_of('Skyborne'), reports.side_of(None), reports.side_of('Human, Somebody')), (set(), set(), set()))

    def test_the_sides_a_race_mask_lets_through(self):
        both = {'Alliance', 'Horde'}
        self.assertEqual([reports.allowed_sides(m) for m in (0, '0', 18446744073709551615, -1, 77, 178, 8, 255, 1 | 2, None, 'x')],
                         [both, both, both, both, {'Alliance'}, {'Horde'}, {'Alliance'}, both, both, both, both])
        # the masks the live server sends: all of a side's races (the top bit is set in the Horde's: it is not "everyone")
        self.assertEqual((reports.allowed_sides(0x55155555B1354C4D), reports.allowed_sides(0xAA2AAAAA4E0AB3B2), reports.allowed_sides('12261800583900083122')),
                         ({'Alliance'}, {'Horde'}, {'Horde'}))
        # Forever's new race of each side
        self.assertEqual((reports.allowed_sides(0x100000000), reports.allowed_sides(0x200000000), reports.allowed_sides(0x300000000)), ({'Alliance'}, {'Horde'}, both))
        self.assertEqual(reports.allowed_sides(1 << 40) - both, set())

    def test_only_quests_players_saw_have_a_word_on_their_side(self):
        found = reports.quest_sides(pack([{'id': 1, 'side': 'Alliance', 'seen_by_players': True}, {'id': 2, 'side': 'Horde'},
                                          {'id': 3, 'side': 'Skyborne', 'seen_by_players': True}, {'id': 'x', 'side': 'Horde', 'seen_by_players': True}]))
        self.assertEqual(found, {1: {'Alliance'}})


class Places(unittest.TestCase):
    PACK = {'npcs': [{'entry': 244808, 'name': 'Aramis Hammerhand', 'map': 0, 'x': 1840, 'y': 1628, 'seen': True},
                     {'entry': 244808, 'name': 'Aramis Hammerhand', 'map': 0, 'x': 1840, 'y': 1628, 'seen': True},       # twice on the map
                     {'entry': 54, 'name': 'Corina Steele', 'map': 0, 'x': -9465, 'y': 94, 'seen': True},                 # stands already
                     {'entry': 999999, 'name': 'Nobody', 'map': 0, 'x': 1, 'y': 1, 'seen': True},                          # no template
                     {'entry': 300, 'name': 'From a list', 'map': 0, 'x': 1, 'y': 1, 'seen': False}],                      # QuestieDB's, not seen
            'pins': [{'kind': 'rare', 'name': "Den'dralass", 'area': 2521, 'x': 3576.8, 'y': 827.0},
                     {'kind': 'book', 'name': 'Arcanic Systems Manual', 'map': 1, 'x': 1017.9, 'y': -3082.1},
                     {'kind': 'rare', 'name': 'Twin', 'map': 1, 'x': 1, 'y': 1}, {'kind': 'rare', 'name': 'Stranger', 'map': 1, 'x': 1, 'y': 1},
                     {'kind': 'commerce', 'name': 'Lost', 'area': 77, 'x': 1, 'y': 1}]}
    NAMES = {('npc', "den'dralass"): [270001], ('go', 'arcanic systems manual'): [180001], ('npc', 'twin'): [1, 2], ('npc', 'lost'): [3]}

    def test_things_nobody_spawned_get_the_place_players_reported(self):
        found, left = reports.places(self.PACK, {244808, 54, 300}, {('npc', 54)}, lambda kind, name: self.NAMES.get((kind, name), []), {2521: 2800}.get)
        self.assertEqual(found, [['go', 180001, 'Arcanic Systems Manual', [{'m': 1, 'x': 1017.9, 'y': -3082.1}]],
                                 ['npc', 244808, 'Aramis Hammerhand', [{'m': 0, 'x': 1840.0, 'y': 1628.0}]],
                                 ['npc', 270001, "Den'dralass", [{'m': 2800, 'x': 3576.8, 'y': 827.0}]]])
        self.assertEqual(left, {'report_place_already_spawned': 1, 'report_place_unknown_creature': 1, 'report_several_same_name': 1,
                                'report_place_name_unknown': 1, 'report_place_no_map': 1})

    def test_a_pack_without_maps_has_no_places(self):
        self.assertEqual(reports.places({'quests': []}, set(), set()), ([], {}))

if __name__ == '__main__':
    unittest.main()
