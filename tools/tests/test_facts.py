"""python -m unittest discover -s tools/tests

The last class needs a MySQL server: it runs when FT_TEST_CONFIG names a config.ini of a throwaway server (its
[database] tracker database is created and dropped), and is skipped otherwise.
"""
import collections
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import facts  # noqa: E402
from ft.facts import Fact  # noqa: E402

COMMIT = 'a' * 40
MANY = [{'instance': 0, 'worldX': float(i), 'worldY': 1.0} for i in range(55)]
BUILD = {
    'npcs': {'meta': {}, 'approached': {'47': {'name': 'Wanted poster'}},
             'npcs': {'240': {'name': 'Marshal Dughan', 'levels': [25], 'side': 'Alliance', 'interactions': ['QuestGiver'], 'sources': 3, 'windows': 9,
                              'positions': [{'instance': 0, 'worldX': -9465.5, 'worldY': 74.0, 'uiMap': 1429}],
                              'options': {'96270': {'name': 'I would like to buy from you.'}},
                              'offers': {'35': {'title': 'Further Concerns', 'level': 10, 'repeatable': False}, 'x': {}, '²': {}},
                              'takes': {'54': {'title': 'Report to Goldshire'}}},
                      '241': {'name': 'Seen by one player, window never counted', 'sources': 1, 'positions': MANY},
                      'npc:9': {'name': 'bad key'}, '242': ['not', 'a', 'record']},
             'objects': {'35': {'name': "Captain's Footlocker", 'sources': 1, 'windows': 0, 'offers': {'138': {}}}}},
    'creatures': {'creatures': {'474': {'name': 'Defias Rogue Wizard', 'levels': {'9': 4, '10': 1}, 'classifications': ['normal'], 'seen': 5, 'sources': 2,
                                        'rep': {'72': 5}, 'combatLog': {'entries': 3, 'levels': {'9': 3}, 'casts': {'133': 2}, 'positions': MANY}},
                                'ghost': 'not a record'}},
    'vendors': {'vendors': {'74': {'name': 'Kurran Steele', 'repairs': True, 'entries': {
        'item:1839': {'itemId': 1839, 'name': 'Rough Leather Belt', 'costs': {'5': 184}, 'stack': 1, 'sources': 2},
        'item:1839#2': {'itemId': 1839, 'name': 'Rough Leather Belt', 'costs': {'5': 900}, 'stack': 5, 'sources': 1},
        'item:10938': {'itemId': 10938, 'bartered': True, 'limited': True, 'stockMax': 2, 'stack': 1, 'sources': 1},
        'item:0': {'itemId': 0}}}, '75': {'name': 'No stock seen'}, '76': {'entries': ['odd']}}},
    'trainers': {'trainers': {'377': {'name': 'Priestess Josetta', 'trainerType': 0, 'tradeskill': False, 'services': {
        '17': {'spellId': 17, 'name': 'Power Word: Shield', 'costs': {'5': 100, '6': 90}, 'level': 6, 'rankText': 'Rank 1', 'skillRank': 0, 'sources': 1},
        'broken': {'name': 'no spell'}}}}},
    'loot': {'format': 3,
             'kills': {'npc:474': {'deaths': 14, 'unknown': 2, 'empty': 6}, 'npc:474|group': {'deaths': 5, 'unknown': 0, 'empty': 1},
                       'npc:474|quest|group': {'deaths': 2, 'unknown': 0, 'empty': 0}},
             'rolls': {'encounter:2732|threshold:2': {'items': {'272998': {'drops': 1}}}},
             'sources': {
                 # the source's chance is per kill, not drops over windows: it is kept, not worked out again
                 'npc:474': {'windows': 10, 'coins': 9, 'copper': 236, 'copperWindows': 9,
                             'items': {'2589': {'drops': 4, 'quantity': 6, 'chance': 0.2}, '1210': {'drops': 1, 'quantity': 1, 'chance': 0.05, 'quest': 76}}},
                 'npc:474|group': {'windows': 5, 'items': {'2589': {'drops': 1, 'quantity': 1, 'chance': 0.16}}},
                 'npc:474|quest|group': {'windows': 2, 'items': {'2589': {'drops': 2, 'quantity': 2, 'chance': 1.0}}},
                 'npc:474|spell:8613': {'windows': 3, 'items': {'2318': {'drops': 3, 'quantity': 3, 'chance': 1.0}}},
                 'npc:474|spell:8617': {'windows': 4, 'items': {'2319': {'drops': 1, 'quantity': 1, 'chance': 0.25}}},
                 'npc:474|spell:8613|bountifulHarvest:2': {'windows': 1, 'items': {'2318': {'drops': 1, 'quantity': 4, 'chance': 1.0}}},
                 'object:2843|spell:6478': {'windows': 4, 'copper': 12, 'items': {'118': {'drops': 2, 'quantity': 2, 'chance': 0.5}}},
                 'object:2843|spell:6478|group': {'windows': 6, 'items': {'118': {'drops': 1, 'quantity': 1, 'chance': 0.17}}},
                 'item:20708': {'windows': 2, 'items': {'6358': {'drops': 2, 'quantity': 2, 'chance': 1.0}}},
                 'fishing:1413': {'windows': 55, 'items': {'6361': {'drops': 22, 'quantity': 22, 'chance': 0.4}}},
                 'npc:abc': {'windows': 1, 'items': {}}, 'mailbox:7': {'windows': 1, 'items': {'1': {'drops': 1}}},
                 'npc:475': {'windows': 1, 'items': {'x': {'drops': 1}, '9': 'odd'}}}},
    'quests.enUS': {'quests': {'91724': {'title': 'Delicate Instruments', 'level': 10, 'minLevel': 6, 'sources': 3,
                                         'description': "Line one.\r\nIt's 'quoted' \\ and é \U0001f600."}}},
    'creature_details.enUS': {'creatures': {'4578': {'name': 'Josephine Lister', 'displays': [{'displayId': 2664}], 'sources': 3}}},
    'object_details.enUS': {'objects': {'180006': {'name': 'Outhouse', 'type': 5, 'sources': 1}}},
    'objectives': {'quests': {'1014': {'1': {'type': 'item', 'required': 1, 'gains': 1, 'sources': 1, 'positions': MANY}, 'x': {}}, '1015': ['odd']},
                   'completed': {'2843': {}}},
    'turn_ins': {'quests': {'1109': [{'xp': 6950, 'money': 0, 'sources': 2}, 'junk', {'xp': 7000, 'sources': 1}], '1110': 'junk'}, 'withLegacy': {}},
    'game_rules': {'rules': {'1': 2}},
}


def tree(folder, builds=('1.60.1.70862',), content=BUILD):
    for build in builds:
        os.makedirs(os.path.join(folder, build))
        for dataset, body in content.items():
            with open(os.path.join(folder, build, dataset + '.json'), 'w', encoding='utf-8') as handle:
                json.dump(body, handle)


class EgLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        tree(cls.folder.name)
        os.makedirs(os.path.join(cls.folder.name, 'not-a-build'))
        os.makedirs(os.path.join(cls.folder.name, '1.60.1.70862\n'))
        with open(os.path.join(cls.folder.name, '1.60.1.70862', 'flights.json'), 'w') as handle:
            handle.write('{broken: a dataset nothing reads may be anything')
        cls.skipped = collections.Counter()
        cls.facts = list(facts.eglink(cls.folder.name, cls.skipped))
        cls.by = {(f.kind, f.subject_kind, f.subject, f.object): f for f in cls.facts}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_every_fact_is_storable_on_its_build_and_none_hides_another(self):
        self.assertEqual(len(self.by), len(self.facts))
        for fact in self.facts:
            self.assertIsNotNone(facts.check(fact), fact)
            self.assertEqual(fact.build, 70862)
        self.assertEqual(collections.Counter(f.kind for f in self.facts), {
            'talked': 3, 'gives': 2, 'takes': 1, 'seen': 1, 'sells': 2, 'teaches': 1, 'drops': 4, 'gathers': 2, 'fishes': 1, 'coins': 2,
            'quest': 1, 'creature': 1, 'object': 1, 'objective': 1, 'turn_in': 1})

    def test_who_gives_and_takes_a_quest(self):
        self.assertEqual(self.by[('gives', 'npc', 240, 35)], Fact('gives', 'npc', 240, 35, 70862, 3, {'title': 'Further Concerns', 'level': 10, 'repeatable': False}))
        self.assertEqual(self.by[('takes', 'npc', 240, 54)].data, {'title': 'Report to Goldshire'})
        self.assertEqual(self.by[('gives', 'object', 35, 138)], Fact('gives', 'object', 35, 138, 70862, 1, {}))
        self.assertNotIn(('talked', 'npc', 47, 0), self.by)          # "approached" is not a window a player opened

    def test_a_window_a_player_opened(self):
        talked = self.by[('talked', 'npc', 240, 0)]
        self.assertEqual((talked.samples, talked.data['levels'], talked.data['options']), (9, [25], {'96270': {'name': 'I would like to buy from you.'}}))
        self.assertNotIn('offers', talked.data)                      # its quests are facts of their own
        uncounted = self.by[('talked', 'npc', 241, 0)]
        self.assertEqual(uncounted.samples, 0)                       # no window counted: players are not windows
        self.assertEqual((len(uncounted.data['positions']), uncounted.data['positionsSeen']), (40, 55))

    def test_what_was_seen_in_the_world(self):
        seen = self.by[('seen', 'npc', 474, 0)]
        self.assertEqual((seen.samples, seen.data['levels'], seen.data['rep'], seen.data['combatLog']['casts']), (5, {'9': 4, '10': 1}, {'72': 5}, {'133': 2}))
        self.assertEqual((len(seen.data['combatLog']['positions']), seen.data['combatLog']['positionsSeen']), (40, 55))

    def test_what_a_vendor_sells_every_listing(self):
        belt = self.by[('sells', 'npc', 74, 1839)]
        self.assertEqual(belt.samples, 2)
        self.assertEqual([(l['costs'], l['stack']) for l in belt.data['listings']], [({'5': 184}, 1), ({'5': 900}, 5)])
        self.assertEqual(self.by[('sells', 'npc', 74, 10938)].data['listings'],
                         [{'itemId': 10938, 'bartered': True, 'limited': True, 'stockMax': 2, 'stack': 1, 'sources': 1}])

    def test_what_a_trainer_teaches(self):
        taught = self.by[('teaches', 'npc', 377, 17)]
        self.assertEqual(taught.samples, 1)
        self.assertEqual(taught.data, {'spellId': 17, 'name': 'Power Word: Shield', 'costs': {'5': 100, '6': 90}, 'level': 6, 'rankText': 'Rank 1',
                                       'skillRank': 0, 'sources': 1, 'trainerType': 0, 'tradeskill': False})

    def test_drops_keep_each_way_of_looting_with_the_source_s_numbers(self):
        linen = self.by[('drops', 'npc', 474, 2589)]
        self.assertEqual(linen.samples, 10)                          # the windows that show every item: a group's do not
        self.assertEqual(linen.data, {'ways': {
            'plain': {'drops': 4, 'quantity': 6, 'chance': 0.2, 'windows': 10, 'kills': 12, 'empty': 6},
            'group': {'drops': 1, 'quantity': 1, 'chance': 0.16, 'windows': 5, 'kills': 5, 'empty': 1},
            'quest|group': {'drops': 2, 'quantity': 2, 'chance': 1.0, 'windows': 2, 'kills': 2, 'empty': 0}}})
        self.assertEqual(self.by[('drops', 'npc', 474, 1210)].data['ways']['plain']['quest'], 76)

    def test_loot_through_a_spell_keeps_each_spell_apart(self):
        leather = self.by[('gathers', 'npc', 474, 2318)]
        self.assertEqual(leather.samples, 4)
        self.assertEqual(leather.data['ways'], {'spell:8613': {'drops': 3, 'quantity': 3, 'chance': 1.0, 'windows': 3},
                                                'spell:8613|bountifulHarvest:2': {'drops': 1, 'quantity': 4, 'chance': 1.0, 'windows': 1}})
        self.assertEqual(list(self.by[('gathers', 'npc', 474, 2319)].data['ways']), ['spell:8617'])       # another spell, another loot
        chest = self.by[('drops', 'object', 2843, 118)]
        self.assertEqual((chest.samples, sorted(chest.data['ways'])), (4, ['spell:6478', 'spell:6478|group']))
        self.assertEqual(self.by[('drops', 'item', 20708, 6358)].samples, 2)
        self.assertEqual(self.by[('fishes', 'uimap', 1413, 6361)].data['ways']['plain']['chance'], 0.4)

    def test_money(self):
        self.assertEqual(self.by[('coins', 'npc', 474, 0)], Fact('coins', 'npc', 474, 0, 70862, 10, {'ways': {
            'plain': {'coins': 9, 'copper': 236, 'copperWindows': 9, 'windows': 10, 'kills': 12, 'empty': 6}}}))
        self.assertEqual(self.by[('coins', 'object', 2843, 0)].data, {'ways': {'spell:6478': {'copper': 12, 'windows': 4}}})

    def test_records_as_the_server_sent_them(self):
        quest = self.by[('quest', 'quest', 91724, 0)]
        self.assertEqual((quest.samples, quest.data), (3, BUILD['quests.enUS']['quests']['91724']))
        self.assertEqual(self.by[('creature', 'npc', 4578, 0)].data['displays'], [{'displayId': 2664}])
        self.assertEqual(self.by[('object', 'object', 180006, 0)].data['type'], 5)

    def test_objectives_and_turn_ins(self):
        objective = self.by[('objective', 'quest', 1014, 1)]
        self.assertEqual((objective.samples, objective.data['required'], len(objective.data['positions']), objective.data['positionsSeen']), (1, 1, 40, 55))
        self.assertEqual(self.by[('turn_in', 'quest', 1109, 0)],
                         Fact('turn_in', 'quest', 1109, 0, 70862, 2, {'seen': [{'xp': 6950, 'money': 0, 'sources': 2}, {'xp': 7000, 'sources': 1}]}))

    def test_what_could_not_be_read_is_counted_not_guessed(self):
        self.assertEqual(dict(self.skipped), {'npcs': 4, 'creatures': 1, 'vendors': 1, 'trainers': 1, 'loot': 4, 'objectives': 2, 'turn_ins': 1})

    def test_builds_in_order_and_a_missing_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            tree(folder, ('1.60.1.70862', '1.60.1.70790', '1.60.1.9'), {'vendors': BUILD['vendors']})
            self.assertEqual([f.build for f in facts.eglink(folder)], [9, 9, 70790, 70790, 70862, 70862])
            self.assertEqual(list(facts.eglink(os.path.join(folder, 'nowhere'))), [])

    def test_a_broken_download_stops_the_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            tree(folder, content={'vendors': BUILD['vendors']})
            with open(os.path.join(folder, '1.60.1.70862', 'loot.json'), 'w') as handle:
                handle.write('{"sources": {"npc:474": {"windows": 10, "ite')
            with self.assertRaises(facts.SourceError) as broken:
                list(facts.eglink(folder))
            self.assertIn('loot.json', str(broken.exception))

    def test_ids(self):
        self.assertEqual([facts._id(v) for v in ('474', 474, '0', '-1', '4294967296', '²', '٣', ' 5', '5\n', 'abc', None)],
                         [474, 474, None, None, None, None, None, None, None, None, None])


class Fetch(unittest.TestCase):
    INDEX = {'products': {'wowf': {'1.60.1.70862': {'vendors': {'records': 2}, 'loot': {'records': 1}, 'game_rules': {'records': 9}},
                                   '1.60.1.70790': {'vendors': {'records': 1}}, '../../etc': {'vendors': {}}, '1.60.1.1': 'odd',
                                   '1.60.1.70900\n': {'vendors': {}}},
                          'wow_classic_beta': {'1.60.1.70009': {'vendors': {'records': 5}}}}}

    def setUp(self):
        self.asked, self.body = [], b'{"vendors": {}}'

    def fetch(self, url):
        self.asked.append(url.replace(f'https://raw.githubusercontent.com/JIVESCORP/eg-link-output-wowf/{COMMIT}/data/', ''))
        return json.dumps(self.INDEX).encode() if url.endswith('index.json') else self.body

    def test_only_forever_builds_and_the_datasets_read(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(facts.fetch_eglink(COMMIT, folder, self.fetch), 3)
            self.assertEqual(self.asked, ['index.json', 'wowf/1.60.1.70790/vendors.json', 'wowf/1.60.1.70862/vendors.json', 'wowf/1.60.1.70862/loot.json'])
            self.assertEqual(sorted(os.listdir(folder)), ['1.60.1.70790', '1.60.1.70862'])
            self.assertEqual(sorted(os.listdir(os.path.join(folder, '1.60.1.70862'))), ['loot.json', 'vendors.json'])
            self.asked = []
            self.assertEqual(facts.fetch_eglink(COMMIT, folder, self.fetch), 0)          # what is there is not asked again
            self.assertEqual(self.asked, ['index.json'])

    def test_a_download_cut_short_is_not_kept(self):
        self.body = b'{"vendors": {"74": {"entr'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(facts.SourceError):
                facts.fetch_eglink(COMMIT, folder, self.fetch)
            self.assertEqual([names for _root, _dirs, names in os.walk(folder) if names], [])

    def test_what_goes_wrong_on_the_way_is_one_kind_of_error(self):
        import http.client

        def unreachable(url):
            raise OSError('no route')

        def cut(url):
            raise http.client.IncompleteRead(b'')
        for broken in (unreachable, cut, lambda url: b'not json'):
            with tempfile.TemporaryDirectory() as folder, self.assertRaises(facts.SourceError):
                facts.fetch_eglink(COMMIT, folder, broken)
        with tempfile.TemporaryDirectory() as folder:                # an index that lists nothing downloads nothing
            self.assertEqual(facts.fetch_eglink(COMMIT, folder, lambda url: b'[1, 2]'), 0)

    def test_a_pin_that_is_not_a_commit_is_refused(self):
        for pin in ('main', '', None, 'a' * 39, '../' + 'a' * 37, 'a' * 40 + '\n'):
            with self.assertRaises(facts.SourceError):
                facts.fetch_eglink(pin, '/nonexistent', self.fetch)
        self.assertEqual(self.asked, [])


class Storing(unittest.TestCase):
    def test_check(self):
        good = Fact('sells', 'npc', 74, 1839, 70862, 2, {})
        self.assertIs(facts.check(good), good)
        for bad in (good._replace(kind='steals'), good._replace(subject_kind='player'), good._replace(subject=0), good._replace(object=-1),
                    good._replace(build=2 ** 32), good._replace(samples=True), good._replace(subject='74')):
            self.assertIsNone(facts.check(bad), bad)

    def test_sql_value(self):
        self.assertEqual(facts.sql_value(5), '5')
        self.assertEqual(facts.sql_value("a'b\\c\nd\re\0f"), "'a\\'b\\\\c\\nd\\re\\0f'")

    def write(self, rows, **more):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'world', 'facts.sql')
            counts = facts.write_sql(path, 'eglink', COMMIT, 'CC-BY-4.0', 'public', iter(rows), **more)
            with open(path, 'rb') as handle:
                return counts, handle.read().decode('ascii')         # nothing but ASCII reaches the server

    def test_the_file_replaces_the_source_in_one_transaction(self):
        rows = [Fact('sells', 'npc', 74, 1839, 70862, 2, {'costs': {'5': 184}}), Fact('steals', 'npc', 1, 1, 1, 1, {}),
                Fact('quest', 'quest', 91724, 0, 70862, 3, {'description': "It's a \\ é \U0001f600 \ud83d\r\nline"}), Fact('gives', 'npc', 240, 35, 70862, 3, {})]
        skipped = collections.Counter(loot=4)
        counts, text = self.write(rows, skipped=skipped, now="'2026-11-13 06:00:00'", batch=2)
        self.assertEqual(counts, {'sells': 1, 'quest': 1, 'gives': 1})
        self.assertTrue(text.startswith("SET NAMES utf8mb4;\nSET SESSION sql_mode = 'STRICT_ALL_TABLES';\nCREATE TABLE IF NOT EXISTS ft_world_facts"))
        self.assertLess(text.index('START TRANSACTION'), text.index("DELETE FROM ft_world_facts WHERE source = 'eglink'"))
        self.assertLess(text.index('DELETE FROM'), text.index('INSERT INTO ft_world_facts'))
        self.assertTrue(text.endswith('COMMIT;\n'))
        self.assertEqual(text.count('INSERT INTO ft_world_facts'), 2)          # two batches of at most two
        self.assertIn("('eglink', 'sells', 'npc', 74, 1839, 70862, 2, '{\"costs\":{\"5\":184}}')", text)
        # JSON's own escapes survive the SQL string; a quote cannot end it; a lone surrogate cannot stop the writing
        self.assertIn("It\\'s a \\\\\\\\ \\\\u00e9 \\\\ud83d\\\\ude00 \\\\ud83d\\\\r\\\\nline", text)
        self.assertNotIn('steals', text)
        self.assertIn("'public', (SELECT COUNT(*) FROM ft_world_facts WHERE source = 'eglink'), 5, '2026-11-13 06:00:00')", text)   # 4 unread + 1 unfit

    def test_what_the_reader_left_out_is_known_only_once_it_has_read(self):
        skipped = collections.Counter()

        def reading():
            yield Fact('sells', 'npc', 74, 1839, 70862, 2, {})
            skipped['vendors'] += 3
        _counts, text = self.write(reading(), skipped=skipped)
        self.assertIn("WHERE source = 'eglink'), 3, NOW());", text)


class Unescape(unittest.TestCase):
    """tools/ft/sqlio.py reads what the mysql client prints in batch mode."""
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        path = os.path.join(cls.folder.name, 'config.ini')
        with open(path, 'w') as handle:
            handle.write('[database]\nuser = "x"\npassword = "y"\n')
        cls.before = os.environ.get('FOREVER_TRACKER_CONFIG')
        if 'ft.sqlio' not in sys.modules:
            os.environ['FOREVER_TRACKER_CONFIG'] = os.environ.get('FT_TEST_CONFIG') or path
        from ft import sqlio
        cls.sqlio = sqlio

    @classmethod
    def tearDownClass(cls):
        if cls.before is None:
            os.environ.pop('FOREVER_TRACKER_CONFIG', None)
        cls.folder.cleanup()

    def test_one_pass(self):
        un = self.sqlio._unescape
        self.assertIsNone(un('NULL'))
        self.assertEqual(un('a\\tb\\nc\\0d\\\\e'), 'a\tb\nc\0d\\e')
        self.assertEqual(un('\\\\n'), '\\n')                      # an escaped backslash, then an n: not a line break
        self.assertEqual(un('{"t":"a\\\\r\\\\nb \\\\u00e9"}'), '{"t":"a\\r\\nb \\u00e9"}')
        self.assertEqual(un('odd\\q'), 'odd\\q')


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server')
class OnMySQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['FOREVER_TRACKER_CONFIG'] = os.environ['FT_TEST_CONFIG']
        from ft import sqlio
        from ft.config import CONFIG
        cls.db, cls.name = sqlio, CONFIG.db('tracker')
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.name}`;\nCREATE DATABASE `{cls.name}` CHARACTER SET utf8mb4;\n', 'information_schema')
        cls.folder = tempfile.TemporaryDirectory()
        tree(os.path.join(cls.folder.name, 'eg'), ('1.60.1.70790', '1.60.1.70862'))
        cls.path = os.path.join(cls.folder.name, 'facts.sql')

    @classmethod
    def tearDownClass(cls):
        cls.db.execute(f'DROP DATABASE IF EXISTS `{cls.name}`;\n', 'information_schema')
        cls.folder.cleanup()

    def load(self, rows, pin=COMMIT, skipped=None):
        counts = facts.write_sql(self.path, 'eglink', pin, 'CC-BY-4.0', 'public', rows, skipped)
        self.db.execute_file(self.path, 'tracker')
        return counts

    def test_load_read_back_and_replace(self):
        self.assertEqual(facts.summary(self.db), ([], []))
        everything = list(facts.eglink(os.path.join(self.folder.name, 'eg')))
        counts = self.load(everything, skipped=collections.Counter(loot=7))
        sources, kinds = facts.summary(self.db)
        self.assertEqual([s[:6] for s in sources], [('eglink', COMMIT, 'CC-BY-4.0', 'public', len(everything), 7)])
        self.assertEqual({k[1]: k[2] for k in kinds}, counts)
        self.assertEqual({k[1]: k[4:] for k in kinds}['sells'], (70790, 70862))
        stored = self.db.query("SELECT samples, data FROM ft_world_facts WHERE kind = 'quest' AND subject = 91724 AND build = 70862", 'tracker')
        self.assertEqual(stored[0]['samples'], '3')
        self.assertEqual(json.loads(stored[0]['data']), BUILD['quests.enUS']['quests']['91724'])        # text, quotes, line breaks, an emoji
        ways = self.db.query("SELECT data FROM ft_world_facts WHERE kind = 'drops' AND subject = 474 AND object = 2589 AND build = 70790", 'tracker')
        self.assertEqual(json.loads(ways[0]['data'])['ways']['quest|group']['kills'], 2)
        # what the client escapes comes back as it was stored: a backslash before an n is not a line break
        self.assertEqual(self.db.query("SELECT 'a\\\\nb' x, 'tab\\there' y, 'line\\nbreak' z, NULL n", 'tracker'),
                         [{'x': 'a\\nb', 'y': 'tab\there', 'z': 'line\nbreak', 'n': None}])
        # a second load replaces the source's facts, and another source's are left alone
        self.db.execute("INSERT INTO ft_world_facts (source, kind, subject_kind, subject, object, build, samples, data) VALUES "
                        "('other', 'sells', 'npc', 1, 2, 3, 4, '{}');", 'tracker')
        self.load([Fact('sells', 'npc', 74, 1839, 70862, 2, {}), Fact('sells', 'npc', 74, 1839, 70862, 5, {'again': True})], pin='b' * 40)
        rows = self.db.query('SELECT source, samples, data FROM ft_world_facts ORDER BY source', 'tracker')
        self.assertEqual(rows, [{'source': 'eglink', 'samples': '5', 'data': '{"again":true}'}, {'source': 'other', 'samples': '4', 'data': '{}'}])
        self.assertEqual(facts.summary(self.db)[0][0][:6], ('eglink', 'b' * 40, 'CC-BY-4.0', 'public', 1, 0))


if __name__ == '__main__':
    unittest.main()
