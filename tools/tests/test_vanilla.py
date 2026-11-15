"""python -m unittest discover -s tools/tests

The original game as the changelog's start (ft.vanilla, docs/VANILLA.md): how its tables are read into the tracker's
rows, what is compared with the game's first build and in which form, what happens to the resources a hotfix alone
carries, and how the tables are stored. No network and no game files: a table is a few lines of CSV.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import client, content, tooltips, vanilla  # noqa: E402

SPARSE = ('ID,Display_lang,OverallQualityID,ItemLevel,RequiredLevel,InventoryType,AllowableClass,SellPrice,StatModifier_bonusStat_0,StatModifier_bonusAmount_0,'
          'StatModifier_bonusStat_1,StatModifier_bonusAmount_1\n'
          '12640,Lionheart Helm,4,61,56,1,-1,21894,4,18,0,0\n'
          '9999,"Sword, of Kings",3,40,35,13,3,100,7,5,32,14\n')
EFFECT = ('ID,DifficultyID,EffectIndex,Effect,EffectAura,EffectBasePoints,EffectDieSides,EffectTriggerSpell,SpellID\n'
          '1,0,0,2,0,13,9,0,133\n2,0,1,6,3,0,1,0,133\n3,0,0,6,33,-41,1,0,116\n4,0,0,6,4,25,0,0,7\n')


def entity(name, **facts):
    return {'name': name, 'facts': {'name': name, **facts}}


class Reading(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        os.makedirs(os.path.join(self.folder.name, 'enUS'))

    def table(self, name, text):
        with open(os.path.join(self.folder.name, 'enUS', name + '.csv'), 'w', encoding='utf-8') as handle:
            handle.write(text)

    def test_the_two_spellings_of_a_column_are_one(self):
        self.assertEqual(vanilla.plain('StatModifier_bonusStat_0'), vanilla.plain('StatModifierBonusStat1'))
        self.assertEqual(vanilla.plain('Display_lang'), vanilla.plain('Display'))
        self.assertEqual(vanilla.plain('Flags_1'), vanilla.plain('Flags2'))
        self.assertEqual(vanilla.plain('MapDescription0_lang'), vanilla.plain('MapDescription0'))
        self.assertNotEqual(vanilla.plain('Display1_lang'), vanilla.plain('Display'))

    def test_rows_come_out_as_the_trackers_reader_gives_them(self):
        self.table('ItemSparse', SPARSE)
        rows = {row['ID']: row for row in vanilla.rows(self.folder.name, 'ItemSparse')}
        helm = rows[12640]
        self.assertEqual((helm['Display'], helm['OverallQualityID'], helm['ItemLevel'], helm['AllowableClass']), ('Lionheart Helm', 4, 61, -1))
        self.assertEqual((helm['StatModifierBonusStat1'], helm['StatPercentEditor1'], helm['Description']), (4, 0, ''))   # a column the 2019 table lacks: 0 or ''
        self.assertEqual(set(helm) - {'amounts'}, {name for name, _kind in vanilla.columns('ItemSparse')})
        self.assertEqual(helm['amounts'], {4: 18})                  # the amount itself, as the original game wrote it
        self.assertEqual(rows[9999]['Display'], 'Sword, of Kings')  # a comma inside a name
        self.assertIsInstance(helm['DmgVariance'], float)

    def test_a_spell_effects_points_are_the_middle_of_the_range(self):
        self.assertEqual((vanilla.points(13, 9), vanilla.points(17, 3), vanilla.points(-41, 1), vanilla.points(25, 0), vanilla.points(9, 4), vanilla.points(0, 6)),
                         (18.0, 19.0, -40.0, 25.0, 11.0, 3.0))   # Fireball 14 to 22, Frostbolt 18 to 20, a slow, no die; an even range is rounded down
        self.table('SpellEffect', EFFECT)
        rows = vanilla.rows(self.folder.name, 'SpellEffect')
        self.assertEqual([(row['SpellID'], row['EffectIndex'], row['EffectBasePoints']) for row in rows], [(133, 0, 18.0), (133, 1, 1.0), (116, 0, -40.0), (7, 0, 25.0)])

    def test_an_items_effects_are_joined_as_todays_tables_join_them(self):
        self.table('ItemEffect', 'ID,LegacySlotIndex,TriggerType,SpellID,ParentItemID\n70,0,1,133,12640\n71,1,1,116,12640\n72,0,0,7,0\n')
        self.assertEqual([(row['ItemEffectID'], row['ItemID']) for row in vanilla.rows(self.folder.name, 'ItemXItemEffect')], [(70, 12640), (71, 12640)])

    def test_a_table_that_is_not_stored_is_empty(self):
        self.assertEqual(vanilla.rows(self.folder.name, 'Mount'), [])

    def test_the_official_content_is_read_like_any_builds(self):
        self.table('ItemSparse', SPARSE)
        self.table('SpellName', 'ID,Name_lang\n133,Fireball\n')
        self.table('Spell', 'ID,NameSubtext_lang,Description_lang,AuraDescription_lang\n133,Rank 1,Hurls a fiery ball.,\n')
        self.table('SpellEffect', EFFECT)
        self.table('QuestV2', 'ID,UniqueBitFlag\n783,1\n')
        found = vanilla.official(self.folder.name)
        self.assertEqual(found['item'][12640]['facts']['name'], 'Lionheart Helm')
        self.assertEqual(found['item'][12640]['amounts'], {4: 18})
        self.assertEqual(found['item'][9999]['amounts'], {7: 5})   # primary stats only: a rating is no stat of the original game
        self.assertEqual(found['spell'][133]['facts']['effects'], [(0, 2, 0, 18.0, 0), (1, 6, 3, 1.0, 0)])
        self.assertEqual((found['spell'][133]['facts']['rank'], sorted(found['quest']), found['mount']), ('Rank 1', [783], {}))


class Comparing(unittest.TestCase):
    def test_a_class_restriction_counts_over_the_original_classes(self):
        self.assertEqual([vanilla.classes(mask) for mask in (-1, 0, 0x5DF, 32767, 400, 31296 | 400)], [0, 0, 0, 0, 400, (31296 | 400) & 0x5DF])

    def test_ranged_weapons_take_the_ranged_budget(self):
        budgets = {40: {**{f'{quality}{slot}': slot * 10 for quality in ('GoodF', 'SuperiorF', 'EpicF') for slot in range(1, 6)}, 'ID': 40}}
        row = lambda slot, quality=3: {'InventoryType': slot, 'OverallQualityID': quality, 'ItemLevel': 40}
        self.assertEqual([vanilla.budget(row(slot), budgets) for slot in (1, 3, 2, 13, 15, 25, 26, 28)], [10, 20, 30, 40, 50, 50, 50, 50])
        self.assertEqual((vanilla.budget(row(1, 1), budgets), vanilla.budget({**row(1), 'ItemLevel': 41}, budgets), vanilla.budget(row(19), budgets)), (0, 0, 0))
        self.assertIs(tooltips.budget, vanilla.budget)   # the tooltips work an item's stats out with the same rule

    def test_an_item_is_compared_by_what_both_sides_can_say(self):
        before = {'item': {1: {**entity('Helm', classes=0x5DF, stats=[], ilvl=61), 'amounts': {4: 18}},
                           2: {**entity('Wand', classes=128, stats=[], ilvl=40), 'amounts': {5: 3}},
                           3: {**entity('Old', classes=-1, stats=[]), 'amounts': {}}},
                  'taxi': {7: entity('Stormwind', flags=3, map=0)}}
        after = {'item': {1: entity('Helm', classes=-1, stats=[(4, 4000)], ilvl=61),
                          2: entity('Wand', classes=-1, stats=[(5, 5000)], ilvl=42),
                          4: entity('New', classes=-1, stats=[])},
                 'taxi': {7: entity('Stormwind', flags=1025, map=0)}, '_meta': {}}
        changes = vanilla.compare(before, after, {1: {4: 18}, 2: {5: 4}, 4: {}})
        self.assertEqual(sorted(changes, key=str), sorted([
            ('item', 2, 'modified', {'classes': [128, 0], 'ilvl': [40, 42], 'stats': [[['intellect', 3]], [['intellect', 4]]]}),
            ('item', 3, 'removed', {}), ('item', 4, 'added', {})], key=str))
        # without the budget table the stats are left out on both sides, not called changed
        self.assertEqual([fields for _k, entity_id, _c, fields in vanilla.compare(before, after) if entity_id == 2], [{'classes': [128, 0], 'ilvl': [40, 42]}])


class Step(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.builds = []
        for number in (50, 100, 300):
            path = os.path.join(self.folder.name, str(number))
            os.makedirs(os.path.join(path, 'enUS'))
            self.builds.append({'build': number, 'dir': path, 'version': f'1.0.0.{number}', 'baseline': 'vanilla' if number == 50 else ''})
        self.original = {'item': {1: entity('Sword', ilvl=1), 2: entity('Boots', ilvl=9), 3: entity('Old Sword')},
                         'spell': {10: {**entity('Bite'), 'sub': 'other'}, 11: {**entity('Fireball'), 'sub': 'class'}, 12: {**entity('Increased Critical 28'), 'sub': 'item'}},
                         '_meta': {}}
        self.official = {100: {'item': {1: entity('Sword', ilvl=5), 5: entity('Helm')}, 'spell': {}, '_meta': {'hidden': {'ItemSparse': 3}}},
                         300: {'item': {1: entity('Sword', ilvl=5), 2: entity('Boots', ilvl=7), 5: entity('Helm'), 6: entity('Cloak')}, 'spell': {}, '_meta': {}}}
        self.read, self.loaded = [], []

    def step(self, late):
        def load(build):
            self.loaded.append(build['build'])
            return self.official[build['build']]

        def read(folder):
            self.read.append(folder)
            return self.original
        return vanilla.step(self.builds[0], self.builds[1:], late, load, read=read)

    def test_the_first_build_against_the_original_game(self):
        found = self.step({})
        self.assertEqual(sorted(found['changes']), [['item', 1, 'modified', {'ilvl': [1, 5]}, 'Sword'], ['item', 2, 'removed', {}, 'Boots'],
                                                    ['item', 3, 'removed', {}, 'Old Sword'], ['item', 5, 'added', {}, 'Helm'],
                                                    ['spell', 10, 'removed', {}, 'Bite'], ['spell', 11, 'removed', {}, 'Fireball'],
                                                    ['spell', 12, 'removed', {}, 'Increased Critical 28']])
        self.assertEqual((found['counts'], found['ids']), ({'item': 3, 'spell': 3}, {'item': [1, 2, 3], 'spell': [10, 11, 12]}))
        self.assertEqual(sorted(found['minor']), [['spell', 10], ['spell', 12]])   # removed spells players never learned themselves: a creature's, an item's
        self.assertEqual((found['hidden'], found['alone'], found['compared']), ({'ItemSparse': 3}, [], True))

    def test_what_a_hotfix_alone_carries_is_compared_as_the_hotfix_stands(self):
        # the Boots and the Cloak are in no table: build 300's hotfixes carry them, and they count as known since build 100
        found = self.step({300: {('item', 2): 'aa', ('item', 6): 'bb'}})
        self.assertIn(['item', 2, 'modified', {'ilvl': [9, 7]}, 'Boots'], found['changes'])        # the original game's: compared, not removed
        self.assertEqual([change for change in found['changes'] if change[1] == 6], [])          # not the original game's: not called added
        self.assertEqual(found['alone'], [['item', 2]])
        self.assertEqual(sorted(change[1] for change in found['changes'] if change[2] == 'removed' and change[0] == 'item'), [3])

    def test_it_is_worked_out_once(self):
        first = self.step({})
        self.read.clear(), self.loaded.clear()
        self.assertEqual(self.step({}), first)
        self.assertEqual((self.read, self.loaded), ([], []))
        self.step({300: {('item', 2): 'aa'}})                    # until what it rests on changes: a resource a hotfix carries
        self.assertEqual(len(self.read), 1)
        self.read.clear()
        self.step({300: {('item', 2): 'aa'}})
        self.step({300: {('item', 2): 'changed by a later hotfix'}})
        self.assertEqual(len(self.read), 1)                      # the same resources as they stood: kept; one of them changed: again

    def test_a_first_build_stored_in_french_is_not_compared(self):
        os.makedirs(os.path.join(self.builds[1]['dir'], 'frFR'))
        said = []
        found = vanilla.step(self.builds[0], self.builds[1:], {}, lambda build: self.official[build['build']], said.append, read=lambda folder: self.original)
        self.assertEqual((found['compared'], found['changes'], found['counts']), (False, [], {'item': 3, 'spell': 3}))
        self.assertIn('stored in French', said[-1])

    def test_an_items_amounts_are_worked_out_from_the_budget(self):
        sparse = lambda item, slot, quality, level, *stats: {
            'ID': item, 'InventoryType': slot, 'OverallQualityID': quality, 'ItemLevel': level,
            **{f'StatModifierBonusStat{i}': (stats[i - 1][0] if i <= len(stats) else -1) for i in range(1, 11)},
            **{f'StatPercentEditor{i}': (stats[i - 1][1] if i <= len(stats) else 0) for i in range(1, 11)}}
        tables = {'RandPropPoints': [{'ID': 61, **{f'{q}{n}': 45.0 for q in ('GoodF', 'SuperiorF', 'EpicF') for n in range(1, 6)}},
                                     {'ID': 40, **{f'{q}{n}': n * 10.0 for q in ('GoodF', 'SuperiorF', 'EpicF') for n in range(1, 6)}}],
                  'ItemSparse': [sparse(1, 1, 4, 61, (4, 4000), (32, 6222)),      # +18 Strength, and a rating that is no stat of the original game
                                 sparse(2, 26, 3, 40, (5, 600)),                  # a wand: the ranged column (50), +3 Intellect
                                 sparse(3, 1, 1, 61, (7, 5000)),                  # a white item has no budget
                                 sparse(4, 1, 4, 99, (7, 5000))]}                 # a level the budget table does not have
        saved = content.table
        self.addCleanup(lambda: setattr(content, 'table', saved))
        content.table = lambda folder, name, locale='frFR': tables.get(name, [])
        self.assertEqual(vanilla.amounts('first', 'budget'), {1: {4: 18}, 2: {5: 3}, 3: {}, 4: {}})
        self.assertIsNone(vanilla.budget_folder(self.builds[1:]))
        with open(os.path.join(self.builds[2]['dir'], 'enUS', 'RandPropPoints.db2'), 'wb') as handle:
            handle.write(b'x')
        self.assertEqual(vanilla.budget_folder(self.builds[1:]), self.builds[2]['dir'])   # the oldest build that has the table


class Storing(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        return b'\xef\xbb\xbfID,Name_lang\n1,Something\n'

    def fetch(self, **more):
        return vanilla.fetch(log=lambda text: None, get=more.pop('get', self.get), choice=('wow_classic', '1.13.2.31650', 31650), builds=self.folder.name, **more)

    def test_the_tables_are_stored_as_the_build_before_the_first(self):
        result = self.fetch()
        self.assertEqual((result['code'], result['build']), (vanilla.STORED, 31650))
        self.assertEqual(len(self.asked), len(vanilla.TABLES))
        self.assertIn('https://wago.tools/db2/ItemSparse/csv?build=1.13.2.31650', self.asked)
        self.assertFalse([url for url in self.asked if 'Mount' in url or 'Achievement' in url])   # the original game has no such tables
        folder = os.path.join(self.folder.name, '31650')
        self.assertEqual(sorted(os.listdir(os.path.join(folder, 'enUS'))), sorted(name + '.csv' for name in vanilla.TABLES))
        with open(os.path.join(folder, 'build.json'), encoding='utf-8') as handle:
            info = json.load(handle)
        self.assertEqual((info['baseline'], info['tables'], info['version'], info['date']), ('vanilla', 'changelog', '1.13.2.31650', '2019-08-26'))
        self.assertNotIn('beta', info['source'].lower())             # the website tells a beta build by its source
        saved = content.BUILDS
        self.addCleanup(lambda: setattr(content, 'BUILDS', saved))
        content.BUILDS = self.folder.name
        self.assertEqual((content.builds(), client.newest_snapshot()), ([], 0))   # alone it is nothing: no build of the client's
        os.makedirs(os.path.join(self.folder.name, '69876', 'enUS'))
        build = content.builds()[0]
        self.assertTrue(vanilla.is_baseline(build) and build['partial'])
        self.assertEqual(client.newest_snapshot(), 69876)

    def test_once(self):
        self.fetch()
        self.asked.clear()
        self.assertEqual((self.fetch()['code'], self.asked), (vanilla.UP_TO_DATE, []))
        os.makedirs(os.path.join(self.folder.name, '.31650.vanilla.999.part', 'enUS'))   # left by a run that was stopped
        self.assertEqual(self.fetch(again=True)['code'], vanilla.STORED)
        self.assertEqual(os.listdir(self.folder.name), ['31650'])      # replaced whole, nothing left beside it
        os.remove(os.path.join(self.folder.name, '31650', 'build.json'))   # stopped while replacing: tables without their note
        self.assertEqual(self.fetch()['code'], vanilla.STORED)
        with open(os.path.join(self.folder.name, '31650', 'build.json'), 'w') as handle:
            handle.write('[]')                                         # not what this writes: left alone
        with self.assertRaises(RuntimeError):
            self.fetch()

    def test_an_answer_that_is_no_table_stores_nothing(self):
        answers = iter([b'ID,Name_lang\n1,x\n', b'{"errors":"Table not found."}'])
        with self.assertRaises(RuntimeError):
            self.fetch(get=lambda url: next(answers))
        self.assertEqual(os.listdir(self.folder.name), [])

    def test_a_table_cut_short_is_no_table(self):
        vanilla.check_table('Map', b'ID,Name_lang\n1,"a, b"\n2,"two\nlines"\n')
        for cut in (b'ID,Name_lang\n1,x\n2', b'ID,Name_lang\n1,x\n2,y', b'ID,Name_lang\n', b'Name_lang\nx\n', b'ID,Name_lang\n1,"x\n'):
            with self.assertRaises(RuntimeError, msg=cut):
                vanilla.check_table('Map', cut)

    def test_a_folder_that_is_a_build_of_the_game_is_never_replaced(self):
        folder = os.path.join(self.folder.name, '31650', 'enUS')
        os.makedirs(folder)
        with open(os.path.join(folder, 'Map.db2'), 'wb') as handle:
            handle.write(b'a client build')
        for again in (False, True):
            with self.assertRaises(RuntimeError):
                self.fetch(again=again)
        self.assertEqual((os.listdir(folder), self.asked), (['Map.db2'], []))

    def test_only_the_build_the_setting_names_is_the_original_game(self):
        self.fetch()
        os.makedirs(os.path.join(self.folder.name, '69876', 'enUS'))
        saved = (content.BUILDS, vanilla.setting)
        self.addCleanup(lambda: (setattr(content, 'BUILDS', saved[0]), setattr(vanilla, 'setting', saved[1])))
        content.BUILDS = self.folder.name
        listed = lambda: [(b['build'], b['baseline']) for b in content.builds()]
        self.assertEqual(listed(), [(31650, 'vanilla'), (69876, '')])
        vanilla.setting = lambda value=None: None                                  # [client] vanilla = off: the folder stays, the changelog does not use it
        self.assertEqual(listed(), [(69876, '')])
        vanilla.setting = lambda value=None: ('wow_classic', '1.13.2.31727', 31727)   # another build chosen: the old folder is not it
        self.assertEqual(listed(), [(69876, '')])
        vanilla.setting = saved[1]
        os.makedirs(os.path.join(self.folder.name, '30000', 'enUS'))               # a build of the game older than it: it cannot be the start
        self.assertEqual(listed(), [(30000, ''), (69876, '')])

    def test_the_setting(self):
        self.assertEqual(vanilla.setting('wow_classic:1.13.2.31650'), ('wow_classic', '1.13.2.31650', 31650))
        self.assertIsNone(vanilla.setting('off'))
        with self.assertRaises(ValueError):
            vanilla.setting('1.13.2.31650')
        self.assertEqual(vanilla.fetch(choice=None, builds=self.folder.name, log=lambda text: None)['code'], vanilla.UP_TO_DATE)


if __name__ == '__main__':
    unittest.main()
