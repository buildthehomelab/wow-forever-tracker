"""python -m unittest discover -s tools/tests

The locator's heights (ft.locator.Neighbours.place): the server's maps and vmaps give every ready point a z, with the
nearest existing spawn's z as the hint that picks the floor under a roof or a bridge; the nearest spawn's own z only
where the files have no ground. app/spawns.php's database mode writes the points marked 'terrain' whatever the
distance to the nearest spawn.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import locator  # noqa: E402
import test_terrain  # noqa: E402  (imported whole: its test class is not collected twice)
from test_terrain import WX, WY  # noqa: E402


class Heights(unittest.TestCase):
    """Over TerrainTest's files: map 0 rises one yard per height row, a model floor at z 50 over (WX, WY)."""

    @classmethod
    def setUpClass(cls):
        test_terrain.TerrainTest.setUpClass()
        cls.terrain = test_terrain.TerrainTest.terrain
        cls.ground = test_terrain.TerrainTest.ground(None, WX)

    @classmethod
    def tearDownClass(cls):
        test_terrain.TerrainTest.tearDownClass()

    def place(self, spawns, x=WX, y=WY, terrain=True):
        return locator.Neighbours(self.terrain if terrain else None, spawns).place(0, x, y)

    def test_no_spawn_near_takes_the_highest_surface(self):
        x, y, z, dist, _o, source = self.place([])
        self.assertEqual((x, y, z, dist, source), (WX, WY, 50.0, None, 'terrain'))

    def test_the_nearest_spawn_picks_the_floor(self):
        # a spawn on the ground 5 yards away: the terrain under the roof, not the roof
        point = self.place([(0, WX + 5, WY, self.ground + 0.3), (0, WX + 15, WY, 49.0)])
        self.assertEqual((point[2], point[3], point[5]), (round(self.ground, 2), 5.0, 'terrain'))
        # a spawn on the roof: the roof
        point = self.place([(0, WX + 5, WY, 49.5)])
        self.assertEqual((point[2], point[5]), (50.0, 'terrain'))

    def test_a_far_spawn_still_gets_a_terrain_height(self):
        # 18 yards: too far for the database mode to borrow its z, but the terrain answers
        point = self.place([(0, WX + 18, WY, 49.5)])
        self.assertEqual((point[2], point[3], point[5]), (50.0, 18.0, 'terrain'))

    def test_no_ground_falls_back_to_the_spawn(self):
        # no map tile here: the nearest spawn's own z
        point = self.place([(0, 5003.0, 5000.0, 77.7)], 5000.0, 5000.0)
        self.assertEqual((point[2], point[3], point[5]), (77.7, 3.0, 'spawn'))
        # a spawn under the ground with nothing below it (a cave the files lack): no terrain height
        point = self.place([(0, WX + 3, WY, self.ground - 10)])
        self.assertEqual((point[2], point[5]), (round(self.ground - 10, 2), 'spawn'))

    def test_nothing_at_all(self):
        self.assertEqual(self.place([], 5000.0, 5000.0), [5000.0, 5000.0, None, None, 0.0, None])

    def test_without_maps_the_spawn_lends_its_height(self):
        point = self.place([(0, WX + 5, WY, 12.34)], terrain=False)
        self.assertEqual((point[2], point[3], point[5]), (12.34, 5.0, 'spawn'))

    def test_open_terrain_without_maps(self):
        self.assertIsNone(locator.open_terrain(), 'config.sample.ini points at no data folder: no terrain, no error')


if __name__ == '__main__':
    unittest.main()
