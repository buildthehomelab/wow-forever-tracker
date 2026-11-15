"""python -m unittest discover -s tools/tests

A checkout (ft.checkout): the client's data at a step of the timeline as rows of the server's hotfixes database. No
game files and no database: a step's tables and the server's files are small dictionaries.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import checkout  # noqa: E402

# (column, integer bits or 0, unsigned)
COLUMNS = {'item_sparse': [('ID', 32, False), ('Display', 0, False), ('ItemLevel', 16, False), ('Flags', 32, True), ('Speed', 0, False), ('VerifiedBuild', 32, False)]}


class Table:
    def __init__(self, table_hash, columns=('ID', 'Display', 'ItemLevel', 'Flags', 'Speed'), layout_hash=0x1111, hidden_records=0):
        self.table_hash, self.columns = table_hash, [(name, None) for name in columns]
        self.layout_hash, self.hidden_records = layout_hash, hidden_records


def row(item_id, name, level, flags=0, speed=1.5):
    return {'ID': item_id, 'Display': name, 'ItemLevel': level, 'Flags': flags, 'Speed': speed}


STEP = {'id': '70707', 'build': 70707, 'hotfix': 0, 'version': '1.60.1.70707', 'date': '2026-10-30', 'dir': '/x/70707', 'cache': None,
        'cache_day': None, 'partial': False}


class Plan(unittest.TestCase):
    def setUp(self):
        saved = checkout.target
        self.addCleanup(lambda: setattr(checkout, 'target', saved))
        self.step_rows = {1: row(1, 'Sword', 10), 2: row(2, 'Shield', 12, flags=-1), 3: row(3, 'Helm', 5)}
        self.table = Table(0xAAAA)
        checkout.target = lambda step, name, carry=True: (self.table, self.step_rows, 0)
        self.server = {1: row(1, 'Sword', 10), 2: row(2, 'Shield', 11, flags=0xFFFFFFFF), 4: row(4, 'Boots', 50)}

    def plan(self, **more):
        return checkout.plan(STEP, columns=COLUMNS, server=lambda name: (self.server, Table(0xAAAA)), names=['ItemSparse'], **more)

    def test_only_what_differs_from_the_servers_file_and_what_it_lacks(self):
        made = self.plan()['tables']['ItemSparse']
        self.assertEqual([r[0] for r in made['rows']], [2, 3])     # 1 is the same, 2 changed, 3 is new
        self.assertEqual(made['removed'], [4])                     # the server has it, the step does not
        self.assertEqual(made['rows'][0][2], 12)

    def test_values_as_the_column_stores_them(self):
        made = self.plan()['tables']['ItemSparse']
        self.assertEqual(made['rows'][0][3], 4294967295)           # -1 in an unsigned column: the same bits
        self.assertIs(made['rows'][0][5], checkout.VERIFIED)       # VerifiedBuild: the server's build, at writing

    def test_the_same_bits_read_two_ways_are_no_change(self):
        self.step_rows[2] = row(2, 'Shield', 11, flags=-1)
        self.assertEqual([r[0] for r in self.plan()['tables']['ItemSparse']['rows']], [3])

    def test_a_float_that_differs_by_little_is_a_change(self):
        self.step_rows[1] = row(1, 'Sword', 10, speed=1.5000001)
        self.assertIn(1, [r[0] for r in self.plan()['tables']['ItemSparse']['rows']])

    def test_another_layout_of_the_same_table_is_left_out(self):
        made = checkout.plan(STEP, columns=COLUMNS, server=lambda name: (self.server, Table(0xAAAA, layout_hash=0x2222)), names=['ItemSparse'])
        self.assertIn('layout', made['skipped']['ItemSparse'])

    def test_a_left_out_table_is_emptied_all_the_same(self):
        # no rows of an earlier checkout may stay behind in a table this one leaves out
        made = checkout.plan(STEP, columns=COLUMNS, server=lambda name: (self.server, Table(0xAAAA, layout_hash=0x2222)), names=['ItemSparse'])
        self.assertEqual(made['cleared'], {'ItemSparse': {'target': 'item_sparse', 'hash': 0xAAAA}})

    def test_records_of_sections_still_encrypted_are_not_removed(self):
        self.table = Table(0xAAAA, hidden_records=7)
        self.assertEqual(self.plan()['tables']['ItemSparse']['removed'], [])

    def test_another_layout_is_left_out_with_the_reason(self):
        self.table = Table(0xAAAA, columns=('ID', 'Display', 'ItemLevel', 'Flags', 'Speed', 'AmmunitionType'))
        made = self.plan()
        self.assertEqual(made['tables'], {})
        self.assertIn('AmmunitionType', made['skipped']['ItemSparse'])

    def test_another_table_is_left_out(self):
        made = checkout.plan(STEP, columns=COLUMNS, server=lambda name: (self.server, Table(0xBBBB)), names=['ItemSparse'])
        self.assertIn('another table', made['skipped']['ItemSparse'])

    def test_no_hotfix_table_no_rows(self):
        made = checkout.plan(STEP, columns={}, server=lambda name: (self.server, Table(0xAAAA)), names=['ItemSparse'])
        self.assertIn('no hotfix table', made['skipped']['ItemSparse'])


class Write(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        made = {'tables': {'ItemSparse': {'hash': 0xAAAA, 'target': 'item_sparse', 'columns': ['ID', 'Display', 'ItemLevel', 'Flags', 'Speed', 'VerifiedBuild'],
                                          'rows': [[2, "Shield's", 12, 4294967295, 0.1, checkout.VERIFIED]], 'removed': [4], 'records': 3}},
                'skipped': {'Spell': 'no table', 'ItemEffect': 'not in this build'}, 'cleared': {'ItemEffect': {'target': 'item_effect', 'hash': 0xCCCC}}}
        self.path = os.path.join(self.folder.name, 'out.sql')
        self.manifest = checkout.write(STEP, made, self.path, 70938, now='2026-11-15T10:00:00')
        with open(self.path, encoding='utf-8') as handle:
            self.sql = handle.read()

    def test_it_replaces_the_tables_it_names_in_one_transaction(self):
        self.assertLess(self.sql.index('START TRANSACTION'), self.sql.index('DELETE FROM `item_sparse`'))
        self.assertIn(f'DELETE FROM `hotfix_data` WHERE `TableHash` IN ({0xAAAA},{0xCCCC})', self.sql)
        self.assertIn('DELETE FROM `item_effect`', self.sql)   # left out, emptied all the same

    def test_the_push_is_numbered_before_anything_is_removed(self):
        self.assertLess(self.sql.index('SET @push'), self.sql.index('DELETE FROM'))
        self.assertTrue(self.sql.rstrip().endswith('COMMIT;'))

    def test_rows_carry_the_servers_build(self):
        self.assertIn("(2,'Shield\\'s',12,4294967295,0.1,70938)", self.sql)

    def test_one_push_after_the_others_valid_and_removed(self):
        self.assertIn('SET @push := (SELECT COALESCE(MAX(`Id`), 0) + 1 FROM `hotfix_data`)', self.sql)
        lines = re.findall(r'\(@push,(\d+),(\d+),(\d+),(\d),70938\)', self.sql)
        self.assertEqual(sorted((int(r), int(s)) for _u, _h, r, s in lines), [(2, 1), (4, 2)])

    def test_the_manifest_says_what_it_holds_and_left_out(self):
        self.assertEqual(self.manifest['tables']['ItemSparse'], {'hotfix_table': 'item_sparse', 'records': 3, 'rows': 1, 'removed': 1})
        self.assertEqual(self.manifest['skipped'], {'Spell': 'no table', 'ItemEffect': 'not in this build'})
        self.assertEqual(self.manifest['emptied'], ['item_effect'])
        self.assertTrue(os.path.isfile(self.path + '.json'))
        self.assertEqual([n for n in os.listdir(self.folder.name) if n.endswith('.tmp')], [])   # nothing left beside them


class Steps(unittest.TestCase):
    def test_a_step_by_its_name(self):
        found = [dict(STEP), {**STEP, 'id': '70938', 'build': 70938}, {**STEP, 'id': '70938+1', 'build': 70938, 'hotfix': 1}]
        self.assertEqual(checkout.find('70707', found)['build'], 70707)
        self.assertEqual(checkout.find('1.60.1.70707', found)['build'], 70707)
        self.assertEqual(checkout.find('70938+1', found)['hotfix'], 1)
        self.assertEqual(checkout.find('latest', found)['id'], '70938+1')
        for bad in ('70938+2', '70938+x', '70938+'):
            with self.assertRaises(ValueError):
                checkout.find(bad, found)

    def test_fit(self):
        self.assertEqual(checkout.fit(-1, 8, False), -1)
        self.assertEqual(checkout.fit(-1, 8, True), 255)
        self.assertEqual(checkout.fit(255, 8, False), -1)
        self.assertEqual(checkout.fit(float('inf'), 0, False), 0.0)
        self.assertEqual(checkout.fit('x', 0, False), 'x')


class ServerBuild(unittest.TestCase):
    """The build a checkout writes its rows for: config.ini first, else the realms' client build (as the analysis)."""

    def setUp(self):
        import tracker
        self.tracker = tracker
        self.saved = (tracker.CONFIG.server_build, tracker.sqlio.column, tracker.log)
        tracker.log = lambda *a, **k: None

    def tearDown(self):
        self.tracker.CONFIG.server_build, self.tracker.sqlio.column, self.tracker.log = self.saved

    def test_config_first(self):
        self.tracker.CONFIG.server_build = lambda: 70938
        self.tracker.sqlio.column = lambda *a: self.fail('the realm list is not asked when config.ini says it')
        self.assertEqual(self.tracker.known_server_build(), 70938)

    def test_realm_list_when_config_is_silent(self):
        self.tracker.CONFIG.server_build = lambda: 0
        self.tracker.sqlio.column = lambda sql, db: [70938] if 'realmlist' in sql and db == 'auth' else []
        self.assertEqual(self.tracker.known_server_build(), 70938)

    def test_unknown(self):
        self.tracker.CONFIG.server_build = lambda: 0
        def down(*a):
            raise RuntimeError('no auth database')
        self.tracker.sqlio.column = down
        self.assertEqual(self.tracker.known_server_build(), 0)
        self.tracker.sqlio.column = lambda *a: [None]
        self.assertEqual(self.tracker.known_server_build(), 0)


if __name__ == '__main__':
    unittest.main()
