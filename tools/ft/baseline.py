"""'New in Forever' = not in the Classic Era client (tools/baseline/classic-era.json, see tools/make_baseline.py).

The Forever client still carries the Classic Era data, Season of Discovery included, so an ID cut-off alone
marks runes, Waylaid Supplies or Karazhan Crypts as new. Wowhead labels "New in Forever" the same way.
"""
import bisect
import json
import os

from .config import PROJECT

PATH = os.path.join(PROJECT, 'tools', 'baseline', 'classic-era.json')

# IDs below these were in Classic: never new, whatever the baseline says.
NEW_FROM = {'item': 190000, 'quest': 60000, 'spell': 400000, 'talent': 3000, 'dungeon': 1000, 'boss': 3000, 'zone': 5000, 'recipe': 400000,
            'mount': 1000, 'toy': 0, 'pet': 3000, 'achievement': 0, 'taxi': 500}
# The Classic Era table holding each kind's IDs; collections have no table there, so their spell or item decides.
TABLE = {'item': 'ItemSparse', 'spell': 'SpellName', 'recipe': 'SpellName', 'quest': 'QuestV2', 'dungeon': 'Map', 'boss': 'DungeonEncounter',
         'zone': 'AreaTable', 'achievement': 'Achievement', 'taxi': 'TaxiNodes', 'talent': 'Talent'}
VIA = {'mount': ('spell', 'SpellName'), 'pet': ('spell', 'SpellName'), 'toy': ('item', 'ItemSparse')}
# Instances the client carries that no version of the game opened: the original game's unused Emerald Dream raid and
# its Caverns of Time placeholder.
UNRELEASED_MAPS = {169, 269}


class Baseline:
    def __init__(self, path=PATH):
        self.tables, self.build = {}, None
        if os.path.isfile(path):
            data = json.load(open(path, encoding='utf-8'))
            self.build = data.get('build')
            for name, spans in data.get('tables', {}).items():
                self.tables[name] = ([s for s, _ in spans], [e for _, e in spans])

    def has(self, table, entity_id):
        """True/False, or None when the baseline lacks that table."""
        if table not in self.tables:
            return None
        starts, ends = self.tables[table]
        i = bisect.bisect_right(starts, entity_id) - 1
        return i >= 0 and entity_id <= ends[i]

    def season_map(self, map_id):
        """An instance WoW: Forever does not use: one the Classic Era client gained after the original game (Season of
        Discovery's: The Tainted Scar, Karazhan Crypts, Scarlet Enclave...), or one no version opened. Forever's own
        instances are not in the Classic Era client, and the original ones sit below the 'new' cut-off."""
        return map_id in UNRELEASED_MAPS or (map_id >= NEW_FROM['dungeon'] and self.has('Map', map_id) is True)

    def is_new(self, kind, entity_id, entity):
        if entity_id < NEW_FROM.get(kind, 10 ** 9):
            return False
        if kind in VIA:
            key, table = VIA[kind]
            return not self.has(table, int(entity.get(key) or 0))
        return not self.has(TABLE.get(kind, ''), entity_id)
