"""Ground height (z) under a point, offline, from the server's extracted maps and vmaps.

The worldserver reads two kinds of files to find the ground: the terrain tiles (data/maps/MMMM_XX_YY.map, written by
mapextractor) and the collision models of buildings, bridges, rocks and other doodads (data/vmaps, written by
vmap4extractor and vmap4assembler). This module reads the same files the same way, so a spawn point gets the height
the server would give it without a game client, a running server or a player typing .gps:

    terrain = Terrain('data/maps', 'data/vmaps')
    terrain.height(1, 1629.4, -4373.4)              # highest surface: terrain, models or water, whichever is on top
    terrain.height(1, 1629.4, -4373.4, hint=15.0)   # the floor under the hint, as .forge height <map> <x> <y> <z>
    terrain.floors(1, 1629.4, -4373.4)              # every surface on that vertical line, top first

What mirrors the core (TrinityCore master / WoW Forever branch):
  - GridMap::getHeightFromFloat / Uint16 / Uint8 / Flat, with terrain holes (src/server/game/Maps/GridMap.cpp)
  - GridMap::getLiquidLevel (the .map liquid layer; models' own liquids are not read)
  - the vmap tile spawns, ModelInstance's rotation and scale, every group's collision triangles
    (src/common/Collision: MapTree.cpp, ModelInstance.cpp, WorldModel.cpp); MOD_PATH_ONLY models are skipped as the
    worldserver skips them
  - TerrainInfo::GetStaticHeight's choice between the terrain and the model surface (TerrainMgr.cpp)

Not read: game objects (doors, elevators, transports: the server's dynamic tree), phased terrain swaps and parent
maps (the files of the map asked are used, nothing else).

The models' collision triangles are moved into world space once per group when a point first falls on that group,
and indexed by a grid of 8-yard cells, so a batch of points in one area stays quick.
"""
import math
import os
import struct

SIZE_OF_GRIDS = 533.3333333
CENTER_GRID_ID = 32
MAP_RESOLUTION = 128
MID = 0.5 * 64.0 * 533.33333333        # VMapManager::convertPositionToInternalRep
INVALID_HEIGHT = -100000.0
MAX_HEIGHT = 100000.0
VMAP_INVALID_HEIGHT_VALUE = -200000.0
GROUND_HEIGHT_TOLERANCE = 0.05
DEFAULT_HEIGHT_SEARCH = 50.0
HINT_LIFT, HINT_SEARCH = 3.0, 40.0     # what .forge height does with a z hint (core/forge_commands.cpp)
VMAP_MAGIC = b'VMAP_4.E'
MAP_MAGIC, MAP_VERSION = b'MAPS', 10
MOD_HAS_BOUND, MOD_PATH_ONLY = 1, 4
CELL = 8.0


class TerrainError(Exception):
    pass


def grid_of(x, y):
    """The (gx, gy) of the .map / .vmtile file holding world x, y (TerrainInfo::GetGrid)."""
    return int(CENTER_GRID_ID - x / SIZE_OF_GRIDS), int(CENTER_GRID_ID - y / SIZE_OF_GRIDS)


class GridMap:
    """One .map tile: height and liquid level (the .map part of GridMap)."""

    def __init__(self, path):
        with open(path, 'rb') as handle:
            data = handle.read()
        magic, version, _build, _ao, _as, height_offset, _hs, liquid_offset, _ls, holes_offset, holes_size = struct.unpack_from('<4s10I', data, 0)
        if magic != MAP_MAGIC or version != MAP_VERSION:
            raise TerrainError(f'{path}: map file version {magic!r} v{version}, this reader knows MAPS v{MAP_VERSION} (extract the maps again?)')
        self.flat = 0.0
        self.v9 = self.v8 = None
        self.multiplier, self.base = 1.0, 0.0
        if height_offset:
            magic, flags, grid_height, grid_max = struct.unpack_from('<4sIff', data, height_offset)
            if magic != b'MHGT':
                raise TerrainError(f'{path}: no MHGT at {height_offset}')
            self.flat = grid_height
            at = height_offset + 16
            if not flags & 1:
                if flags & 2:
                    kind, size, self.multiplier = 'H', 2, (grid_max - grid_height) / 65535
                elif flags & 4:
                    kind, size, self.multiplier = 'B', 1, (grid_max - grid_height) / 255
                else:
                    kind, size = 'f', 4
                self.base = grid_height if kind != 'f' else 0.0
                self.v9 = struct.unpack_from(f'<{129 * 129}{kind}', data, at)
                self.v8 = struct.unpack_from(f'<{128 * 128}{kind}', data, at + size * 129 * 129)
        self.liquid_level, self.liquid_map = INVALID_HEIGHT, None
        if liquid_offset:
            magic, lflags, _type_flags, _type, off_x, off_y, width, height, level = struct.unpack_from('<4sBBHBBBBf', data, liquid_offset)
            if magic != b'MLIQ':
                raise TerrainError(f'{path}: no MLIQ at {liquid_offset}')
            self.liquid_level = level
            at = liquid_offset + 16
            if not lflags & 1:
                at += 256 * 2 + 256
            if not lflags & 2:
                self.liquid_map = struct.unpack_from(f'<{width * height}f', data, at)
            self.liquid_box = (off_x, off_y, width, height)
        self.holes = data[holes_offset:holes_offset + 16 * 16 * 8] if holes_size else None

    def is_hole(self, row, col):
        if not self.holes:
            return False
        return bool(self.holes[(row // 8) * 16 * 8 + (col // 8) * 8 + row % 8] & (1 << (col % 8)))

    def height(self, x, y):
        if self.v9 is None:
            return self.flat
        fx = MAP_RESOLUTION * (CENTER_GRID_ID - x / SIZE_OF_GRIDS)
        fy = MAP_RESOLUTION * (CENTER_GRID_ID - y / SIZE_OF_GRIDS)
        xi, yi = int(fx), int(fy)
        fx -= xi
        fy -= yi
        xi &= MAP_RESOLUTION - 1
        yi &= MAP_RESOLUTION - 1
        if self.is_hole(xi, yi):
            return INVALID_HEIGHT
        v9, v8 = self.v9, self.v8
        h5 = 2 * v8[xi * 128 + yi]
        if fx + fy < 1:
            if fx > fy:   # triangle 1 (h1, h2, h5)
                h1, h2 = v9[xi * 129 + yi], v9[(xi + 1) * 129 + yi]
                a, b, c = h2 - h1, h5 - h1 - h2, h1
            else:         # triangle 2 (h1, h3, h5)
                h1, h3 = v9[xi * 129 + yi], v9[xi * 129 + yi + 1]
                a, b, c = h5 - h1 - h3, h3 - h1, h1
        else:
            if fx > fy:   # triangle 3 (h2, h4, h5)
                h2, h4 = v9[(xi + 1) * 129 + yi], v9[(xi + 1) * 129 + yi + 1]
                a, b, c = h2 + h4 - h5, h4 - h2, h5 - h4
            else:         # triangle 4 (h3, h4, h5)
                h3, h4 = v9[xi * 129 + yi + 1], v9[(xi + 1) * 129 + yi + 1]
                a, b, c = h4 - h3, h3 + h4 - h5, h5 - h4
        return (a * fx + b * fy + c) * self.multiplier + self.base

    def liquid(self, x, y):
        if self.liquid_map is None:
            return self.liquid_level
        off_x, off_y, width, height = self.liquid_box
        cx = (int(MAP_RESOLUTION * (CENTER_GRID_ID - x / SIZE_OF_GRIDS)) & (MAP_RESOLUTION - 1)) - off_y
        cy = (int(MAP_RESOLUTION * (CENTER_GRID_ID - y / SIZE_OF_GRIDS)) & (MAP_RESOLUTION - 1)) - off_x
        if not (0 <= cx < height and 0 <= cy < width):
            return INVALID_HEIGHT
        return self.liquid_map[cx * width + cy]


class Group:
    """The collision triangles of one WMO group (or of a whole M2), in the model's own space."""
    __slots__ = ('low', 'high', 'vertices', 'triangles')


def read_model(path):
    """[Group] of a .vmo file (WorldModel::readFile)."""
    with open(path, 'rb') as handle:
        data = handle.read()
    if data[:8] != VMAP_MAGIC or data[8:12] != b'WMOD':
        raise TerrainError(f'{path}: not a {VMAP_MAGIC.decode()} model')
    at = 8 + 4 + 4 + 8          # magic, WMOD, chunk size, flags + root WMO id
    groups = []
    if data[at:at + 4] != b'GMOD':
        return groups
    count, = struct.unpack_from('<I', data, at + 4)
    at += 8
    for _ in range(count):
        group = Group()
        bound = struct.unpack_from('<6f', data, at)
        group.low, group.high = bound[:3], bound[3:]
        at += 24 + 8               # bound, MOGP flags, group WMO id
        if data[at:at + 4] != b'VERT':
            raise TerrainError(f'{path}: no VERT chunk')
        vertex_count, = struct.unpack_from('<I', data, at + 8)
        at += 12
        group.vertices, group.triangles = (), ()
        if vertex_count:
            group.vertices = struct.unpack_from(f'<{vertex_count * 3}f', data, at)
            at += vertex_count * 12
            if data[at:at + 4] != b'TRIM':
                raise TerrainError(f'{path}: no TRIM chunk')
            triangle_count, = struct.unpack_from('<I', data, at + 8)
            at += 12
            group.triangles = struct.unpack_from(f'<{triangle_count * 3}I', data, at)
            at += triangle_count * 12
            if data[at:at + 4] != b'MBIH':
                raise TerrainError(f'{path}: no MBIH chunk')
            at += 4 + 24               # bounds
            tree_size, = struct.unpack_from('<I', data, at)
            at += 4 + tree_size * 4
            object_count, = struct.unpack_from('<I', data, at)
            at += 4 + object_count * 4
            if data[at:at + 4] != b'LIQU':
                raise TerrainError(f'{path}: no LIQU chunk')
            liquid_size, = struct.unpack_from('<I', data, at + 4)
            at += 8 + liquid_size
        groups.append(group)
    return groups


def rotation(rot):
    """ModelInstance's G3D::Matrix3::fromEulerAnglesZYX(pi*rot.y/180, pi*rot.x/180, pi*rot.z/180): model -> world."""
    yaw, pitch, roll = (math.pi * rot[1] / 180, math.pi * rot[0] / 180, math.pi * rot[2] / 180)
    cz, sz = math.cos(yaw), math.sin(yaw)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cx, sx = math.cos(roll), math.sin(roll)
    z = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))
    y = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    x = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    mul = lambda a, b: tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return mul(z, mul(y, x))


class Spawn:
    """One model placed on a vmap tile (ModelSpawn), its groups moved into world space on first use."""

    def __init__(self, flags, ident, pos, rot, scale, low, high, name):
        self.flags, self.id, self.pos, self.rot, self.scale, self.name = flags, ident, pos, rot, scale, name
        # bound in internal coordinates (x and y mirrored around MID)
        self.low, self.high = low, high
        self.groups = None    # [(world low xy, world high xy, cells, triangles)] once read

    def covers(self, ix, iy):
        return self.low[0] <= ix <= self.high[0] and self.low[1] <= iy <= self.high[1]


class Terrain:
    def __init__(self, maps, vmaps=None):
        if not os.path.isdir(maps):
            raise TerrainError(f'{maps}: no such folder (the server\'s data/maps)')
        self.maps, self.vmaps = maps, vmaps if vmaps and os.path.isdir(vmaps) else None
        self._grids, self._tiles, self._models = {}, {}, {}

    # ---- terrain (.map) ----

    def grid(self, map_id, x, y):
        gx, gy = grid_of(x, y)
        key = (map_id, gx, gy)
        if key not in self._grids:
            path = os.path.join(self.maps, f'{map_id:04d}_{gx:02d}_{gy:02d}.map')
            self._grids[key] = GridMap(path) if os.path.isfile(path) else None
        return self._grids[key]

    def grid_height(self, map_id, x, y):
        """TerrainInfo::GetGridHeight: the terrain under x, y; VMAP_INVALID_HEIGHT_VALUE without a tile, INVALID_HEIGHT in a hole."""
        grid = self.grid(map_id, x, y)
        return grid.height(x, y) if grid else VMAP_INVALID_HEIGHT_VALUE

    def water_level(self, map_id, x, y):
        grid = self.grid(map_id, x, y)
        return grid.liquid(x, y) if grid else 0.0   # TerrainInfo::GetWaterLevel answers 0 without a tile

    # ---- models (vmaps) ----

    def _tile(self, map_id, gx, gy):
        key = (map_id, gx, gy)
        if key in self._tiles:
            return self._tiles[key]
        spawns = []
        path = os.path.join(self.vmaps, f'{map_id:04d}', f'{map_id:04d}_{gx:02d}_{gy:02d}.vmtile') if self.vmaps else None
        if path and os.path.isfile(path):
            with open(path, 'rb') as handle:
                data = handle.read()
            if data[:8] != VMAP_MAGIC:
                raise TerrainError(f'{path}: vmap version {data[:8]!r}, this reader knows {VMAP_MAGIC.decode()} (extract the vmaps again?)')
            count, = struct.unpack_from('<I', data, 8)
            at = 12
            for _ in range(count):
                flags, _adt, ident = struct.unpack_from('<BBI', data, at)
                pos = struct.unpack_from('<3f', data, at + 6)
                rot = struct.unpack_from('<3f', data, at + 18)
                scale, = struct.unpack_from('<f', data, at + 30)
                at += 34
                low = high = None
                if flags & MOD_HAS_BOUND:
                    bound = struct.unpack_from('<6f', data, at)
                    low, high = bound[:3], bound[3:]
                    at += 24
                size, = struct.unpack_from('<I', data, at)
                name = data[at + 4:at + 4 + size].decode('ascii', 'replace')
                at += 4 + size
                if flags & MOD_PATH_ONLY or low is None:
                    continue   # the worldserver skips path-only models; a spawn without bound has no collision box
                spawns.append(Spawn(flags, ident, pos, rot, scale, low, high, name))
        self._tiles[key] = spawns
        return spawns

    def _model(self, name):
        if name not in self._models:
            path = os.path.join(self.vmaps, name + '.vmo')
            self._models[name] = read_model(path) if os.path.isfile(path) else []
        return self._models[name]

    def _world_groups(self, spawn):
        """The spawn's groups as world-space triangles indexed by 8-yard cells (built once)."""
        if spawn.groups is not None:
            return spawn.groups
        r = rotation(spawn.rot)
        s = spawn.scale
        px, py, pz = spawn.pos
        out = []
        for group in self._model(spawn.name):
            if not group.triangles:
                continue
            v = group.vertices
            world = []
            for i in range(0, len(v), 3):
                mx, my, mz = v[i] * s, v[i + 1] * s, v[i + 2] * s
                # internal coordinates back to world ones: x = MID - internal x
                world.append((MID - (r[0][0] * mx + r[0][1] * my + r[0][2] * mz + px),
                              MID - (r[1][0] * mx + r[1][1] * my + r[1][2] * mz + py),
                              r[2][0] * mx + r[2][1] * my + r[2][2] * mz + pz))
            triangles, cells = [], {}
            t = group.triangles
            for i in range(0, len(t), 3):
                a, b, c = world[t[i]], world[t[i + 1]], world[t[i + 2]]
                area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                if abs(area) < 1e-6:
                    continue   # a wall seen edge-on from above: a vertical ray never stops on it
                index = len(triangles)
                triangles.append((a, b, c, area))
                for cx in range(math.floor(min(a[0], b[0], c[0]) / CELL), math.floor(max(a[0], b[0], c[0]) / CELL) + 1):
                    for cy in range(math.floor(min(a[1], b[1], c[1]) / CELL), math.floor(max(a[1], b[1], c[1]) / CELL) + 1):
                        cells.setdefault((cx, cy), []).append(index)
            out.append((cells, triangles))
        spawn.groups = out
        return out

    def model_surfaces(self, map_id, x, y):
        """[(z, spawn)] of every model triangle on the vertical line through x, y, highest first."""
        if not self.vmaps:
            return []
        gx, gy = grid_of(x, y)
        ix, iy = MID - x, MID - y
        cell = (math.floor(x / CELL), math.floor(y / CELL))
        hits = []
        for spawn in self._tile(map_id, gx, gy):
            if not spawn.covers(ix, iy):
                continue
            for cells, triangles in self._world_groups(spawn):
                for index in cells.get(cell, ()):
                    a, b, c, area = triangles[index]
                    # barycentric weights of (x, y) in the triangle's shadow on the ground
                    u = ((b[0] - x) * (c[1] - y) - (b[1] - y) * (c[0] - x)) / area
                    v = ((c[0] - x) * (a[1] - y) - (c[1] - y) * (a[0] - x)) / area
                    w = 1.0 - u - v
                    if u < -1e-7 or v < -1e-7 or w < -1e-7:
                        continue
                    hits.append((u * a[2] + v * b[2] + w * c[2], spawn))
        hits.sort(key=lambda hit: -hit[0])
        return hits

    def vmap_height(self, map_id, x, y, z, max_search=DEFAULT_HEIGHT_SEARCH):
        """VMapManager::getHeight: the first model surface below z within max_search, or VMAP_INVALID_HEIGHT_VALUE."""
        for surface, _spawn in self.model_surfaces(map_id, x, y):
            if z - max_search < surface < z:
                return surface
        return VMAP_INVALID_HEIGHT_VALUE

    # ---- what the server answers ----

    def static_height(self, map_id, x, y, z, check_vmap=True, max_search=DEFAULT_HEIGHT_SEARCH):
        """TerrainInfo::GetStaticHeight."""
        map_height = VMAP_INVALID_HEIGHT_VALUE
        grid_height = self.grid_height(map_id, x, y)
        if z >= grid_height - GROUND_HEIGHT_TOLERANCE - 1e-5:
            map_height = grid_height
        vmap_height = self.vmap_height(map_id, x, y, z, max_search) if check_vmap else VMAP_INVALID_HEIGHT_VALUE
        if vmap_height > INVALID_HEIGHT:
            if map_height > INVALID_HEIGHT:
                if vmap_height > map_height or abs(map_height - z) > abs(vmap_height - z):
                    return vmap_height
                return map_height
            return vmap_height
        return map_height

    def forge_height(self, map_id, x, y, hint=None):
        """Exactly what `.forge height <map> <x> <y> [zHint]` answers (core/forge_commands.cpp GroundHeight), or None.

        Without a hint the core looks down from MAX_HEIGHT only DEFAULT_HEIGHT_SEARCH yards, so it never meets a
        model: the answer is the terrain or the water, whichever is higher, even under a roof or over a bridge."""
        if hint is not None:
            z = self.static_height(map_id, x, y, hint + HINT_LIFT, True, HINT_SEARCH)
            if z <= INVALID_HEIGHT:
                z = hint
        else:
            z = max(self.static_height(map_id, x, y, MAX_HEIGHT), self.water_level(map_id, x, y))
        return None if z <= INVALID_HEIGHT else z

    def floors(self, map_id, x, y):
        """Every surface on the vertical line through x, y, highest first: [{'z', 'what'}] where what is
        'terrain', 'water' or 'model <file> spawn <id>'. Surfaces of one model closer than 0.05 yards are merged."""
        out = []
        ground = self.grid_height(map_id, x, y)
        if ground > INVALID_HEIGHT:
            out.append({'z': ground, 'what': 'terrain'})
        water = self.water_level(map_id, x, y) if self.grid(map_id, x, y) else INVALID_HEIGHT
        if water > INVALID_HEIGHT and (ground <= INVALID_HEIGHT or water > ground + GROUND_HEIGHT_TOLERANCE):
            out.append({'z': water, 'what': 'water'})
        last = {}
        for z, spawn in self.model_surfaces(map_id, x, y):
            what = f'model {spawn.name} spawn {spawn.id}'
            if what in last and last[what] - z < 0.05:
                continue
            last[what] = z
            out.append({'z': z, 'what': what})
        out.sort(key=lambda floor: -floor['z'])
        return out

    def height(self, map_id, x, y, hint=None):
        """The z to spawn at, or None where there is nothing (no tile, a hole with nothing under it).

        With a hint: the server's answer for that hint, the same as .forge height with that z: the nearest model floor
        from 3 yards above the hint to 37 below, or the terrain under hint + 3 yards at any depth when it is closer
        (or higher than the model), else the hint itself. Without one: the highest surface, terrain, model
        or water, which is where a creature standing outdoors belongs; under a roof, a bridge or in a cave give a hint."""
        if hint is not None:
            return self.forge_height(map_id, x, y, hint)
        found = self.floors(map_id, x, y)
        return found[0]['z'] if found else None
