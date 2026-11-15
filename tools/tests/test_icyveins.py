"""The Icy Veins mirror as the locator reads it (tools/ft/icyveins.py): gzipped answers, the older plain files too."""
import gzip
import json
import os
import tempfile
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import icyveins  # noqa: E402


class MirrorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        os.makedirs(os.path.join(self.root, 'npc'))
        os.makedirs(os.path.join(self.root, 'gameobject'))

    def tearDown(self):
        self.dir.cleanup()

    def write(self, kind, entry, data, gz=True):
        path = os.path.join(self.root, kind, f'{entry}.json' + ('.gz' if gz else ''))
        with (gzip.open if gz else open)(path, 'wt', encoding='utf-8') as f:
            json.dump(data, f)

    def test_points_in_map_units(self):
        self.write('npc', 1284, {'entity': {'id': 1284}, 'relations': {'addon_points': [
            {'ui_map_id': 1453, 'via': 'talk', 'x': 503.2, 'y': 456.3}, {'ui_map_id': None, 'x': 1, 'y': 1}]}})
        [(ui, u, v)] = icyveins.points('npc', 1284, self.root)
        self.assertEqual(ui, 1453)
        self.assertAlmostEqual(u, 0.5032)
        self.assertAlmostEqual(v, 0.4563)

    def test_objects_and_plain_files(self):
        self.write('gameobject', 1731, {'relations': {'addon_points': [{'ui_map_id': 1429, 'x': 100, 'y': 900}]}}, gz=False)
        self.assertEqual(icyveins.points('go', 1731, self.root), [(1429, 0.1, 0.9)])

    def test_nothing(self):
        self.write('npc', 5, {'missing': True})
        self.assertEqual(icyveins.points('npc', 5, self.root), [])
        self.assertEqual(icyveins.points('npc', 6, self.root), [])


if __name__ == '__main__':
    unittest.main()
