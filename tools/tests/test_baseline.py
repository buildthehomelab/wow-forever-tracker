"""python -m unittest discover -s tools/tests

Instances WoW: Forever does not use (ft.baseline.Baseline.season_map), against the shipped Classic Era baseline.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import output  # noqa: E402
from ft.baseline import Baseline  # noqa: E402


class SeasonMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Baseline()
        if 'Map' not in cls.baseline.tables:
            raise unittest.SkipTest('no Map table in the Classic Era baseline')

    def test_season_of_discovery_instances(self):
        # The Searing Basin, Demon Fall Canyon, The Tainted Scar, Storm Cliffs, The Crystal Vale, Nightmare Grove,
        # Scarlet Enclave, Karazhan Crypts, The Scarab Dais, the second Naxxramas
        for map_id in (2720, 2784, 2789, 2791, 2804, 2832, 2856, 2875, 2902, 2921):
            self.assertTrue(self.baseline.season_map(map_id), map_id)

    def test_never_opened(self):
        self.assertTrue(self.baseline.season_map(169))  # Emerald Dream
        self.assertTrue(self.baseline.season_map(269))  # Caverns of Time

    def test_original_instances_stay(self):
        for map_id in (33, 36, 189, 230, 249, 309, 409, 429, 469, 489, 509, 529, 531, 533):
            self.assertFalse(self.baseline.season_map(map_id), map_id)

    def test_forever_instances_stay(self):
        # City of Dalaran, The Drowned City, Alcaz Prison, Excavation Site: Wetlands, Krol'dok Stronghold, Manor Mistmantle
        # (a later dungeon: tools/phases/forever.json)
        for map_id in (2959, 2970, 2994, 2998, 3039, 3109):
            self.assertFalse(self.baseline.season_map(map_id), map_id)


class Written(unittest.TestCase):
    """output.write_sql lists such an instance and its bosses under Internal / test, and leaves the others alone."""

    def test_internal_rows(self):
        if 'Map' not in Baseline().tables:
            self.skipTest('no Map table in the Classic Era baseline')
        content = {'dungeon': {2789: {'name': 'The Tainted Scar', 'name_en': 'The Tainted Scar', 'sub': 'Raid'},
                               409: {'name': 'Molten Core', 'name_en': 'Molten Core', 'sub': 'Raid'}},
                   'boss': {3001: {'name': 'Lord Kazzak', 'name_en': 'Lord Kazzak', 'map': 2789},
                            672: {'name': 'Ragnaros', 'name_en': 'Ragnaros', 'map': 409}}}
        results = {(kind, i): ('missing', 0, []) for kind in content for i in content[kind]}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'import.sql')
            output.write_sql(path, [], content, [], results, {}, {}, {}, {}, {'quests': {}, 'quest_fr': {}, 'quest_level': {}}, 0, {}, [])
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
        row = lambda kind, i: re.search(rf"\('{kind}',{i},.*?\)(?=,\n|;\n)", text).group(0)
        internal = lambda kind, i: int(row(kind, i).split(',')[8])
        self.assertEqual(internal('dungeon', 2789), 1)
        self.assertIn('season', row('dungeon', 2789))
        self.assertEqual(internal('boss', 3001), 1)
        self.assertEqual(internal('dungeon', 409), 0)
        self.assertEqual(internal('boss', 672), 0)


if __name__ == '__main__':
    unittest.main()
