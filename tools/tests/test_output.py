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
            'mount': {3113: named('[PH] Brown Prideclaw', spell=1), 3000: named('Swift Hyjal Stag', spell=2), 7: named('Gray Wolf', spell=459)},
            'pet': {3500: named('Gill\'el', spell=3)},
            'recipe': {1252979: named(''), 1252000: named('Test Recipe'), 1251000: named('Elderwild Pants'), 2369: named('Herbalism'), 2330: named(''), 2337: named('#2337')},
            'item': {269326: named('NOT USED'), 279254: named('Elderwild Pants')},
            'quest': {55296: named(''), 9999999: named(''), 2000: named(''), 5561: named(''), 8237: named(''), 9378: named('')},
        }
        results = {(kind, i): ('missing', 0, []) for kind in cls.content for i in cls.content[kind]}
        off = [{'ok': False, 'code': 'enabled'}, {'ok': False, 'code': 'starter'}, {'ok': False, 'code': 'ender'}]
        results[('quest', 2000)] = ('missing', 0, off)
        results[('quest', 5561)] = ('missing', 0, off[1:])
        quests = {2000: {'LogTitle': 'Rokar Bladeshadow'}, 5561: {'LogTitle': 'Kodo Roundup'}, 8237: {'LogTitle': 'REUSE'},
                  9378: {'LogTitle': 'DND FLAG The Dread Citadel - Naxxramas'}}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'import.sql')
            output.write_sql(path, [], cls.content, [], results, {}, {}, {}, {}, {'quests': quests, 'quest_fr': {}, 'quest_level': {},
                                                                                    'granted_spells': {459, 2369}}, 0, {}, [])
            with open(path, encoding='utf-8') as handle:
                cls.text = handle.read()

    def row(self, kind, entity_id):
        return re.search(rf"\('{kind}',{entity_id},.*?\)(?=,\n|;\n)", self.text).group(0)

    def internal(self, kind, entity_id):
        return int(re.search(r",(\d),\d,'missing'", self.row(kind, entity_id)).group(1))

    def test_a_recipe_follows_its_spell(self):
        # spell 2369 is in granted_spells (nothing teaches it here or in the original game): its recipe goes with it
        self.assertEqual(self.internal('recipe', 2369), 1)
        self.assertEqual(self.internal('recipe', 1251000), 0)

    def test_an_old_recipe_whose_spell_the_client_dropped(self):
        # 2330 (an old healing potion): no name, no spell in the client, an id of the original game
        self.assertEqual(self.internal('recipe', 2330), 1)
        self.assertEqual(self.internal('recipe', 2337), 1)   # as ft.content names it: '#' and the id
        self.assertEqual(self.internal('recipe', 1252979), 0)   # a new one, unnamed: content still locked, stays

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
        self.assertEqual(self.internal('mount', 7), 1)   # its spell's line: only items the original game never gave out teach it
        self.assertEqual(self.internal('pet', 3500), 0)
        self.assertEqual(self.internal('recipe', 1252000), 1)
        self.assertEqual(self.internal('recipe', 1251000), 0)

    def test_an_old_recipe_whose_spell_the_client_dropped(self):
        # 2330 (an old healing potion): no name, no spell in the client, an id of the original game
        self.assertEqual(self.internal('recipe', 2330), 1)
        self.assertEqual(self.internal('recipe', 2337), 1)   # as ft.content names it: '#' and the id
        self.assertEqual(self.internal('recipe', 1252979), 0)   # a new one, unnamed: content still locked, stays

    def test_an_unnamed_recipe_stays_visible(self):
        # the client keeps some content unnamed for players to discover: no name is no reason to hide it
        self.assertEqual(self.internal('recipe', 1252979), 0)

    def test_an_unnamed_quest_of_the_classic_era_client(self):
        # the Classic Era client's own tracking quests have no title: nothing to add; Forever's unnamed quests stay until
        # Wowhead says it does not know them either
        self.assertEqual(self.internal('quest', 55296), 1)
        self.assertEqual(self.internal('quest', 9999999), 0)

    def test_a_quest_the_server_disables_and_nobody_gives(self):
        self.assertEqual(self.internal('quest', 2000), 1)
        self.assertEqual(self.internal('quest', 5561), 0, 'no giver alone is a gap to fix')

    def test_reused_and_do_not_display_quests(self):
        self.assertEqual(self.internal('quest', 8237), 1)
        self.assertEqual(self.internal('quest', 9378), 1)

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


class Leftovers(unittest.TestCase):
    """A spell only an item outside the game teaches is filed with that item, under Internal / test."""

    ITEMS = {213117: named('Rune of Berserk'), 902: named('Deprecated Palomino Summoning (Mount)'), 13517: named("Recipe: Alchemist's Stone")}
    SEASON = {('item', 213117): 'season'}

    class Old:
        """Nothing is new: every spell is as old as the Classic Era client."""
        def is_new(self, kind, entity_id, entity):
            return False

    class New(Old):
        def is_new(self, kind, entity_id, entity):
            return True

    def left(self, spell_id, teach, status='partial', baseline=None, trained=()):
        return output.leftover('spell', spell_id, {'teach': teach}, status, self.ITEMS, self.SEASON, baseline or self.Old(), trained)

    def test_taught_by_a_season_or_test_item_only(self):
        self.assertTrue(self.left(424760, [213117]))        # the rune Wowhead marks as not in Forever
        self.assertTrue(self.left(471, [902]))              # "Deprecated ..."
        self.assertTrue(self.left(430409, [211849]))        # an item the client does not have at all
        self.assertTrue(self.left(430410, [213117, 902, 211849]))

    def test_one_real_item_keeps_it_on_the_list(self):
        self.assertFalse(self.left(17632, [13517]))
        self.assertFalse(self.left(17632, [213117, 13517]))

    def test_an_original_recipe_whose_unused_pattern_is_gone_stays(self):
        # Glacial Wrists: taught in Naxxramas, its pattern item was never used and is not in the client
        self.assertFalse(self.left(28209, [22687]))
        self.assertFalse(self.left(28209, [22687, 902]))
        self.assertTrue(self.left(471, [902]))             # a test item still decides, whatever the spell's age

    def test_no_item_no_verdict(self):
        self.assertFalse(self.left(5, []))
        self.assertFalse(self.left(424760, [213117], status='ok'))        # players can get it after all
        self.assertFalse(self.left(424760, [213117], trained={424760}))   # a trainer lists it: that is what is missing

    def test_new_in_forever_and_its_item_not_there_yet(self):
        # a mount Blizzard has not unlocked: the item's row is still encrypted, the spell stays on the list
        self.assertFalse(self.left(1309346, [280583], baseline=self.New()))
        self.assertTrue(self.left(1309346, [213117], baseline=self.New()))

    def test_the_items_own_verdict(self):
        self.assertIs(output.item_internal(213117, self.ITEMS, self.SEASON), True)
        self.assertIs(output.item_internal(213117, self.ITEMS, None), False)
        self.assertIs(output.item_internal(13517, self.ITEMS, self.SEASON), False)
        self.assertIsNone(output.item_internal(1, self.ITEMS, self.SEASON))


class NeverGiven(unittest.TestCase):
    """An original item players cannot get that the original game gave out nowhere either is listed as internal."""

    def test_internal_rows(self):
        content = {'item': {842: {'name': 'Horn of the Gray Wolf', 'name_en': 'Horn of the Gray Wolf', 'quality': 1},
                            13517: {'name': "Recipe: Alchemist's Stone", 'name_en': "Recipe: Alchemist's Stone", 'quality': 3},
                            1134: {'name': 'Horn of the Gray Wolf', 'name_en': 'Horn of the Gray Wolf', 'quality': 1}}}
        results = {('item', 842): ('partial', 50, []), ('item', 13517): ('partial', 50, []), ('item', 1134): ('ok', 100, [])}
        ctx = {'quests': {}, 'quest_fr': {}, 'quest_level': {}, 'classic_never_given': {842, 1134}}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'import.sql')
            output.write_sql(path, [], content, [], results, {}, {}, {}, {}, ctx, 0, {}, [])
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
        internal = lambda i: int(re.search(rf"\('item',{i},.*?\)(?=,\n|;\n)", text).group(0).split(',')[8])
        self.assertEqual(internal(842), 1)     # never given out, and players cannot get it here
        self.assertEqual(internal(13517), 0)   # the original game gave it out
        self.assertEqual(internal(1134), 0)    # players can get it here after all


if __name__ == '__main__':
    unittest.main()
