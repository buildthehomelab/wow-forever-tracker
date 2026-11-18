"""python -m unittest discover -s tools/tests"""
import os
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import terrain  # noqa: E402
from ft.terrain import MID, Terrain  # noqa: E402

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'height.py')
# a model square 10 yards wide (20 once scaled by 2) standing at z 50 over (-100, -100), in tile 32_32 of map 0
WX, WY = -100.0, -100.0


def map_file(path, heights=None, flat=0.0, liquid=None, hole=False):
    """A MAPS v10 tile: a float height grid (heights(row) gives the V9 row value) or a flat one, optional liquid and hole."""
    blocks, offset = [], 44

    def add(data):
        nonlocal offset
        start = offset
        blocks.append(data)
        offset += len(data)
        return start, len(data)
    if heights:
        v9 = [heights(i) for i in range(129) for _ in range(129)]
        v8 = [heights(i) + 0.5 for i in range(128) for _ in range(128)]
        height = add(struct.pack('<4sIff', b'MHGT', 0, 0.0, 0.0) + struct.pack(f'<{len(v9)}f', *v9) + struct.pack(f'<{len(v8)}f', *v8))
    else:
        height = add(struct.pack('<4sIff', b'MHGT', 1, flat, flat))
    liquid_at = add(struct.pack('<4sBBHBBBBf', b'MLIQ', 3, 1, 0, 0, 0, 128, 128, liquid)) if liquid is not None else (0, 0)
    holes = bytearray(16 * 16 * 8)
    if hole:
        holes[0] = 1           # row 0, column 0: the corner square of the tile
    holes_at = add(bytes(holes)) if hole else (0, 0)
    header = struct.pack('<4s10I', b'MAPS', 10, 70790, 0, 0, *height, *liquid_at, *holes_at)
    with open(path, 'wb') as handle:
        handle.write(header + b''.join(blocks))


def model_file(path, z=0.0):
    """A .vmo of one group: a 10 x 10 square at model height z."""
    vertices = [(-5, -5, z), (5, -5, z), (5, 5, z), (-5, 5, z)]
    triangles = [(0, 1, 2), (0, 2, 3)]
    group = struct.pack('<6f', -5, -5, z, 5, 5, z) + struct.pack('<II', 0, 0)
    group += b'VERT' + struct.pack('<II', 4 + 12 * len(vertices), len(vertices)) + b''.join(struct.pack('<3f', *v) for v in vertices)
    group += b'TRIM' + struct.pack('<II', 4 + 12 * len(triangles), len(triangles)) + b''.join(struct.pack('<3I', *t) for t in triangles)
    group += b'MBIH' + struct.pack('<6f', -5, -5, z, 5, 5, z) + struct.pack('<II', 0, 0)
    group += b'LIQU' + struct.pack('<I', 0)
    with open(path, 'wb') as handle:
        handle.write(b'VMAP_4.E' + b'WMOD' + struct.pack('<III', 8, 0, 0) + b'GMOD' + struct.pack('<I', 1) + group + b'GBIH' + struct.pack('<6fII', 0, 0, 0, 0, 0, 0, 0, 0))


def spawn(flags, ident, x, y, z, yaw, scale, name, half):
    ix, iy = MID - x, MID - y
    out = struct.pack('<BBI', flags | 1, 0, ident) + struct.pack('<3f', ix, iy, z) + struct.pack('<3f', 0, yaw, 0) + struct.pack('<f', scale)
    out += struct.pack('<6f', ix - half, iy - half, z - 1, ix + half, iy + half, z + 1)
    return out + struct.pack('<I', len(name)) + name.encode()


class TerrainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        os.makedirs(os.path.join(root, 'maps'))
        os.makedirs(os.path.join(root, 'vmaps', '0000'))
        # map 0: the ground rises one yard per height row, 10 at the tile's first row; a hole in the tile's corner
        map_file(os.path.join(root, 'maps', '0000_32_32.map'), heights=lambda row: 10.0 + row, hole=True)
        # map 2: flat ground at 0 under water at 5
        map_file(os.path.join(root, 'maps', '0002_32_32.map'), flat=0.0, liquid=5.0)
        model_file(os.path.join(root, 'vmaps', 'FLOOR.vmo'))
        model_file(os.path.join(root, 'vmaps', 'PATHONLY.vmo'))
        tile = spawn(0, 7, WX, WY, 50.0, 90.0, 2.0, 'FLOOR', 10) + spawn(4, 8, WX, WY, 70.0, 0.0, 2.0, 'PATHONLY', 10)
        with open(os.path.join(root, 'vmaps', '0000', '0000_32_32.vmtile'), 'wb') as handle:
            handle.write(b'VMAP_4.E' + struct.pack('<I', 2) + tile)
        cls.root = root
        cls.terrain = Terrain(os.path.join(root, 'maps'), os.path.join(root, 'vmaps'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ground(self, x):
        rows = terrain.MAP_RESOLUTION * (terrain.CENTER_GRID_ID - x / terrain.SIZE_OF_GRIDS) % terrain.MAP_RESOLUTION
        return 10.0 + rows

    def test_terrain_follows_the_grid(self):
        for x, y in ((-100.0, -300.0), (-250.5, -10.0), (-1.0, -532.0)):
            self.assertAlmostEqual(self.terrain.grid_height(0, x, y), self.ground(x), places=3)

    def test_hole_and_missing_tile(self):
        self.assertEqual(self.terrain.grid_height(0, -0.5, -0.5), terrain.INVALID_HEIGHT)
        self.assertIsNone(self.terrain.height(0, -0.5, -0.5))
        self.assertIsNone(self.terrain.height(0, 5000.0, 5000.0))

    def test_model_on_top_without_hint(self):
        self.assertAlmostEqual(self.terrain.height(0, WX, WY), 50.0, places=3)
        # scaled by 2: the square reaches 10 yards from its centre, whatever its turn
        self.assertAlmostEqual(self.terrain.height(0, WX + 9.5, WY - 9.5), 50.0, places=3)
        self.assertAlmostEqual(self.terrain.height(0, WX + 10.5, WY), self.ground(WX + 10.5), places=3)

    def test_path_only_models_are_skipped(self):
        whats = [f['what'] for f in self.terrain.floors(0, WX, WY)]
        self.assertEqual(whats, ['model FLOOR spawn 7', 'terrain'])

    def test_hint_picks_the_floor_under_it(self):
        ground = self.ground(WX)
        self.assertAlmostEqual(self.terrain.height(0, WX, WY, hint=ground + 1), ground, places=3)
        self.assertAlmostEqual(self.terrain.height(0, WX, WY, hint=49.0), 50.0, places=3)
        # far above: models only within 40 yards under the hint, the terrain at any depth
        self.assertAlmostEqual(self.terrain.height(0, WX, WY, hint=200.0), ground, places=3)
        # under the ground with nothing below: the hint itself, as .forge height
        self.assertAlmostEqual(self.terrain.height(0, WX, WY, hint=ground - 10), ground - 10, places=3)

    def test_forge_without_hint_ignores_models(self):
        self.assertAlmostEqual(self.terrain.forge_height(0, WX, WY), self.ground(WX), places=3)

    def test_water(self):
        self.assertAlmostEqual(self.terrain.height(2, -10.0, -10.0), 5.0)
        self.assertAlmostEqual(self.terrain.forge_height(2, -10.0, -10.0), 5.0)
        self.assertEqual([f['what'] for f in self.terrain.floors(2, -10.0, -10.0)], ['water', 'terrain'])

    def test_rotation_matches_g3d(self):
        r = terrain.rotation((0.0, 90.0, 0.0))     # a quarter turn about z
        self.assertAlmostEqual(r[0][1], -1.0)
        self.assertAlmostEqual(r[1][0], 1.0)
        self.assertAlmostEqual(r[2][2], 1.0)

    def test_command_line(self):
        points = os.path.join(self.root, 'points.txt')
        with open(points, 'w') as handle:
            handle.write(f'# a comment\n0 {WX} {WY} roof\n0, {WX}, {WY}, 40, under it\n0 5000 5000\n')
        run = subprocess.run([sys.executable, TOOL, '--data', self.root, '--file', points], capture_output=True, text=True)
        lines = [line.split('\t') for line in run.stdout.splitlines()]
        self.assertEqual(run.returncode, 1, run.stderr)    # the last point has no ground
        self.assertEqual(lines[0][3:], ['50.00', 'model FLOOR spawn 7', 'roof'])
        self.assertEqual(lines[1][3:], [f'{self.ground(WX):.2f}', 'terrain', 'under it'])
        self.assertEqual(lines[2][3], 'none')


if __name__ == '__main__':
    unittest.main()
