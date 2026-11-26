"""python -m unittest discover -s tools/tests

The talent trees of Classic 1.60 are trait tables (C_ClassTalents). The tracker reads them from the client like every
other table, so the checkout copies a tree Blizzard changed: each one needs its file data id and a layout.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import checkout, client, content  # noqa: E402
from ft.config import SCHEMA  # noqa: E402


class TraitTables(unittest.TestCase):
    def test_read_from_the_client(self):
        files = client.files()
        for name in content.TRAIT_TABLES:
            self.assertIn(name, content.TABLES)
            self.assertIn(name, files, f'{name}: no file data id in tools/schema/db2-files.json')
            self.assertIn(name, checkout.tracked())

    def test_every_table_has_a_layout(self):
        with open(SCHEMA, encoding='utf-8') as handle:
            schema = json.load(handle)
        for name in content.TRAIT_TABLES:
            self.assertIn(name, schema, f'{name}: no layout in tools/schema/db2-schema.json')
            self.assertTrue(schema[name]['names'], f'{name}: the core loads it, so its columns have names')

    def test_file_ids_are_distinct(self):
        files = client.files()
        ids = [files[name] for name in content.TRAIT_TABLES]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == '__main__':
    unittest.main()
