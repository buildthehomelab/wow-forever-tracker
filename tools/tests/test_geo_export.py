"""World positions onto the official zone maps (ft.geo.to_ui / export) for the Spawns page's map pictures."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ft.geo import Geo, save  # noqa: E402

# Rows of WoW: Forever 1.60.1.70959 (UiMap, UiMapAssignment)
UI_MAPS = [
    {'ID': 947, 'Name': 'Azeroth', 'Type': 1},
    {'ID': 1411, 'Name': 'Durotar', 'Type': 3},
    {'ID': 1414, 'Name': 'Kalimdor', 'Type': 2},
    {'ID': 1454, 'Name': 'Orgrimmar', 'Type': 3},
    {'ID': 2548, 'Name': 'Riverglades', 'Type': 3},
]


def assignment(ui, map_id, area, x1, y1, x2, y2, order=0):
    return {'UiMapID': ui, 'MapID': map_id, 'AreaID': area, 'OrderIndex': order, 'UiMinX': 0, 'UiMinY': 0, 'UiMaxX': 1, 'UiMaxY': 1,
            'Region1X': x1, 'Region1Y': y1, 'Region2X': x2, 'Region2Y': y2}


ASSIGNMENTS = [
    assignment(1411, 1, 14, -1716.6666259766, -7249.9995117188, 1808.3332519531, -1962.4998779297),
    assignment(1414, 1, 0, -11733.299804688, -19733.2109375, 12799.900390625, 17066.599609375),
    assignment(1454, 1, 1637, 1338.4605712891, -5083.2055664062, 2273.8771972656, -3680.6010742188),
    assignment(2548, 0, 16591, -9700, -6741.666015625, -6466.666015625, -1891.666015625),
    assignment(947, 1, 0, -20000, -20000, 20000, 20000),
]


def geo():
    tables = {'UiMap': UI_MAPS, 'UiMapAssignment': ASSIGNMENTS, 'UiMapGroupMember': [], 'AreaTable': [], 'Map': []}
    return Geo(None, read=lambda name: tables[name])


class ToUi(unittest.TestCase):
    def test_round_trip(self):
        g = geo()
        for ui, u, v in ((1411, 0.4, 0.6), (1454, 0.12, 0.88), (2548, 0.5, 0.5), (1414, 0.43, 0.71)):
            map_id, x, y = g.to_world(ui, u, v)
            back = g.to_ui(ui, map_id, x, y)
            self.assertAlmostEqual(back[0], u, places=3)
            self.assertAlmostEqual(back[1], v, places=3)

    def test_outside_or_other_continent(self):
        g = geo()
        self.assertIsNone(g.to_ui(1411, 0, 1000.0, -4000.0))      # Durotar is on Kalimdor (map 1)
        self.assertIsNone(g.to_ui(1411, 1, 5000.0, -4000.0))      # north of its rectangle
        self.assertIsNone(g.to_ui(9999, 1, 1000.0, -4000.0))

    def test_north_is_up_and_west_is_left(self):
        g = geo()
        u1, v1 = g.to_ui(1411, 1, 1000.0, -4000.0)
        u2, v2 = g.to_ui(1411, 1, 1200.0, -4000.0)    # further north (world x grows northwards)
        self.assertLess(v2, v1)
        u3, _ = g.to_ui(1411, 1, 1000.0, -3800.0)     # further west (world y grows westwards)
        self.assertLess(u3, u1)


class Export(unittest.TestCase):
    def test_zones_and_continents_only(self):
        data = geo().export(70959)
        self.assertEqual(data['build'], 70959)
        self.assertEqual(sorted(data['maps']), ['1411', '1414', '1454', '2548'])   # not the world map 947
        durotar = data['maps']['1411']
        self.assertEqual((durotar['name'], durotar['type']), ('Durotar', 3))
        self.assertEqual(durotar['rects'], [[1, -1716.6666, -7249.9995, 1808.3333, -1962.4999, 0.0, 0.0, 1.0, 1.0, 14]])

    def test_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'ui-maps.json')
            self.assertTrue(save(geo().export(70959), path))
            with open(path, encoding='utf-8') as handle:
                self.assertIn('2548', json.load(handle)['maps'])
            self.assertFalse(save({'build': 1, 'maps': {}}, os.path.join(folder, 'none.json')))
            self.assertFalse(os.path.exists(os.path.join(folder, 'none.json')))


if __name__ == '__main__':
    unittest.main()
