"""python -m unittest discover -s tools/tests

What output.write_sql files under Internal / test: rows of the client that are no content players can reach.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import output  # noqa: E402
from ft.baseline import Baseline  # noqa: E402

FACTION_FREE, ALLIANCE, HORDE = 1024, 1025, 1026


def taxi(name, flags, map_id=0):
    return {'name': name, 'name_en': name, 'map': map_id, 'sub': '', 'pos': [0, 0, 0], 'facts': {'flags': flags}}


def named(name, **more):
    return {'name': name, 'name_en': name, 'sub': '', **more}


class Written(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'TaxiNodes' not in Baseline().tables:
            raise unittest.SkipTest('no TaxiNodes table in the Classic Era baseline')
        cls.content = {
            'dungeon': {13: named('Test Dungeon'), 48: named('Blackfathom Deeps'), 30: named('Alterac Valley')},
            'boss': {3078: named('Rahuz', map=13), 3061: named('No Longer in Use', map=0),
                     2761: named('Ghamoo-ra', map=48),
                     2697: named('Ghamoo-ra', map=48, shadow={'reason': 'season', 'kept': 0}),
                     2916: named('Ghamoo-ra', map=48, shadow={'reason': 'duplicate', 'kept': 2761})},
            'taxi': {2: taxi('Stormwind, Elwynn', ALLIANCE), 23: taxi('Orgrimmar, Durotar', HORDE, 1),
                     34: taxi('Transport, Booty Bay - Ratchet', FACTION_FREE, 1), 3: taxi('Programmer Isle', FACTION_FREE),
                     59: taxi('Dun Baldar, Alterac Valley', ALLIANCE, 30),
                     3274: taxi('Powderfuse Port, Riverglades', FACTION_FREE), 3205: taxi('Tidegear Coast, Dun Morogh', 1152)},
            'mount': {3113: named('[PH] Brown Prideclaw', spell=1), 3000: named('Swift Hyjal Stag', spell=2)},
            'pet': {3500: named('Gill\'el', spell=3)},
            'recipe': {1252979: named(''), 1252000: named('Test Recipe'), 1251000: named('Elderwild Pants')},
            'item': {269326: named('NOT USED'), 279254: named('Elderwild Pants')},
        }
        results = {(kind, i): ('missing', 0, []) for kind in cls.content for i in cls.content[kind]}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'import.sql')
            output.write_sql(path, [], cls.content, [], results, {}, {}, {}, {}, {'quests': {}, 'quest_fr': {}, 'quest_level': {}}, 0, {}, [])
            with open(path, encoding='utf-8') as handle:
                cls.text = handle.read()

    def row(self, kind, entity_id):
        return re.search(rf"\('{kind}',{entity_id},.*?\)(?=,\n|;\n)", self.text).group(0)

    def internal(self, kind, entity_id):
        return int(re.search(r",(\d),\d,'missing'", self.row(kind, entity_id)).group(1))

    def test_a_boss_of_a_test_instance_and_an_unused_row(self):
        self.assertEqual(self.internal('boss', 3078), 1)
        self.assertEqual(self.internal('boss', 3061), 1)

    def test_a_boss_listed_again_is_internal_and_says_why(self):
        self.assertEqual(self.internal('boss', 2761), 0)
        self.assertEqual(self.internal('boss', 2697), 1)
        self.assertIn('"encounter":"season"', self.row('boss', 2697).replace(' ', ''))
        self.assertEqual(self.internal('boss', 2916), 1)
        self.assertIn('"same":2761', self.row('boss', 2916).replace(' ', ''))

    def test_flight_points_nobody_flies_from(self):
        for node in (34, 3, 59):   # a boat, an unused node of the original game, a battleground's
            self.assertEqual(self.internal('taxi', node), 1, node)

    def test_real_flight_points_stay(self):
        for node in (2, 23, 3274, 3205):   # Forever's new nodes carry no faction bit: they stay
            self.assertEqual(self.internal('taxi', node), 0, node)

    def test_placeholder_collections_and_recipes(self):
        self.assertEqual(self.internal('mount', 3113), 1)
        self.assertEqual(self.internal('mount', 3000), 0)
        self.assertEqual(self.internal('pet', 3500), 0)
        self.assertEqual(self.internal('recipe', 1252000), 1)
        self.assertEqual(self.internal('recipe', 1251000), 0)

    def test_an_unnamed_recipe_stays_visible(self):
        # the client keeps some content unnamed for players to discover: no name is no reason to hide it
        self.assertEqual(self.internal('recipe', 1252979), 0)

    def test_not_used_item(self):
        self.assertEqual(self.internal('item', 269326), 1)
        self.assertEqual(self.internal('item', 279254), 0)



class Names(unittest.TestCase):
    """Words a test name and a real name share: only the test's shape hides a resource."""

    def test_real_names_stay(self):
        for name in ('Monster Omelet', 'Recipe: Monster Omelet', 'Test of Faith', 'Test of Lore', 'Test of Endurance', 'The Test of Righteousness',
                     'Put to the Test', 'Signed copy of the Green Hills of Stranglethorn', 'Unused Scraping Vial', "Old Serra'kis",
                     'Thunderfury, Blessed Blade of the Windseeker'):
            self.assertFalse(output.named_internal(name), name)

    def test_test_and_placeholder_names_are_internal(self):
        for name in ('Monster - Sword2H, Corrupted Ashbringer', '[PH] Brown Prideclaw', 'Test Dungeon', 'QA Test Item', 'TEST Sword', 'Test Item 3',
                     'TestItem', 'Test2', '76 test item', 'Thunderfury, Blessed Blade of the Windseeker DEPRECATED', "Bloodied Zin'rokh Visual [DNT]",
                     'Copy of Hearthstone', 'Sword (copy)', 'Cloak - Unused', 'UNUSED Boots', 'NOT USED', 'No Longer in Use', 'OLD Cloak', '<Unused>'):
            self.assertTrue(output.named_internal(name), name)


if __name__ == '__main__':
    unittest.main()
