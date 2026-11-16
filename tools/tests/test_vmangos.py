"""python -m unittest discover -s tools/tests

VMaNGOS' world database as a pack of the original game (tools/vmangos_pack.py): patch 1.12 of each row, cmangos'
column names, and the pack ft.classic reads.
"""
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import vmangos_pack  # noqa: E402
from ft import classic  # noqa: E402

DUMP = r"""
CREATE TABLE `creature_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `patch` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `name` varchar(100) NOT NULL DEFAULT '',
  `gossip_menu_id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `loot_id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `trainer_id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `vendor_id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`entry`,`patch`)
) ENGINE=MyISAM;
INSERT INTO `creature_template` VALUES (12939,0,'Doctor Old',0,0,0,0),(12939,10,'Doctor Gustaf VanHowzen',0,0,0,0),(2836,0,'Brikk Keencraft',0,0,77,0),(500,0,'Looter',0,500,0,0),(600,0,'Seller',0,0,0,9);
CREATE TABLE `npc_trainer` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spell` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spellcost` int(10) unsigned NOT NULL DEFAULT '0',
  `reqskill` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqskillvalue` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqlevel` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `build_min` smallint(5) unsigned NOT NULL DEFAULT '0',
  `build_max` smallint(5) unsigned NOT NULL DEFAULT '5875',
  PRIMARY KEY (`entry`,`spell`)
) ENGINE=MyISAM;
INSERT INTO `npc_trainer` VALUES (12939,10843,100000,129,240,0,0,5875),(12939,7929,1,129,1,0,0,4222);
CREATE TABLE `npc_trainer_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spell` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spellcost` int(10) unsigned NOT NULL DEFAULT '0',
  `reqskill` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqskillvalue` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqlevel` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `build_min` smallint(5) unsigned NOT NULL DEFAULT '0',
  `build_max` smallint(5) unsigned NOT NULL DEFAULT '5875'
) ENGINE=MyISAM;
INSERT INTO `npc_trainer_template` VALUES (77,12597,2000,202,125,0,0,5875);
CREATE TABLE `item_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `patch` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `class` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `name` varchar(255) NOT NULL DEFAULT '',
  `spellid_1` mediumint(8) NOT NULL DEFAULT '0',
  `spelltrigger_1` tinyint(3) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`entry`,`patch`)
) ENGINE=MyISAM;
INSERT INTO `item_template` VALUES (7000,0,9,'Recipe',0,0),(7001,0,9,'Pattern',0,0),(7002,0,9,'Never',0,0);
CREATE TABLE `creature_loot_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `item` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `ChanceOrQuestChance` float NOT NULL DEFAULT '100',
  `groupid` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `mincountOrRef` mediumint(9) NOT NULL DEFAULT '1',
  `maxcount` tinyint(3) unsigned NOT NULL DEFAULT '1',
  `condition_id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `patch_min` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `patch_max` tinyint(3) unsigned NOT NULL DEFAULT '10'
) ENGINE=MyISAM;
INSERT INTO `creature_loot_template` VALUES (500,7000,2.5,0,1,1,0,0,10),(500,7002,50,0,1,1,0,0,4);
CREATE TABLE `npc_vendor_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `slot` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `item` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `maxcount` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `incrtime` int(10) unsigned NOT NULL DEFAULT '0',
  `itemflags` int(10) unsigned NOT NULL DEFAULT '0',
  `condition_id` mediumint(8) unsigned NOT NULL DEFAULT '0'
) ENGINE=MyISAM;
INSERT INTO `npc_vendor_template` VALUES (9,0,7001,2,0,0,0);
CREATE TABLE `creature` (
  `guid` int(10) unsigned NOT NULL,
  `id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `id2` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `id3` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `id4` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `id5` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `map` smallint(5) unsigned NOT NULL DEFAULT '0',
  `position_x` float NOT NULL DEFAULT '0',
  `position_y` float NOT NULL DEFAULT '0',
  `position_z` float NOT NULL DEFAULT '0',
  `orientation` float NOT NULL DEFAULT '0',
  `spawntimesecsmin` int(10) unsigned NOT NULL DEFAULT '120',
  `spawntimesecsmax` int(10) unsigned NOT NULL DEFAULT '120',
  `wander_distance` float NOT NULL DEFAULT '5',
  `movement_type` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `patch_min` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `patch_max` tinyint(3) unsigned NOT NULL DEFAULT '10'
) ENGINE=MyISAM;
INSERT INTO `creature` VALUES (1,14829,0,0,0,0,0,1,2,3,0.5,180,180,2,1,0,10),(2,600,601,0,0,0,0,1,2,3,0,60,60,0,0,0,10),(3,14829,0,0,0,0,0,9,9,9,0,60,60,0,0,0,3);
CREATE TABLE `game_event` (
  `entry` int(10) unsigned NOT NULL,
  `description` varchar(255) DEFAULT NULL,
  `patch_min` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `patch_max` tinyint(3) unsigned NOT NULL DEFAULT '10'
) ENGINE=MyISAM;
INSERT INTO `game_event` VALUES (4,'Darkmoon Faire (Elwynn)',0,10);
CREATE TABLE `game_event_creature` (
  `guid` int(10) unsigned NOT NULL,
  `event` smallint(6) NOT NULL DEFAULT '0'
) ENGINE=MyISAM;
INSERT INTO `game_event_creature` VALUES (1,4),(2,4),(3,4);
CREATE TABLE `migrations` (
  `id` varchar(255) NOT NULL
) ENGINE=MyISAM;
INSERT INTO `migrations` VALUES ('20260101000000'),('20261111193532');
"""


class VmangosPack(unittest.TestCase):
    def setUp(self):
        self.pack = vmangos_pack.pack(vmangos_pack.read(io.StringIO(DUMP)), '2026-11-16')

    def test_names_its_source(self):
        self.assertEqual((self.pack['source'], self.pack['licence'], self.pack['format']), ('VMaNGOS', 'GPL-2.0', 4))
        self.assertEqual(self.pack['version'], 'VMaNGOS world database, migration 20261111193532, patch 1.12')

    def test_trainers_of_1_12_through_templates(self):
        self.assertEqual(sorted(map(list, self.pack['trainers'])), [[2836, 12597, 2000, 202, 125, 0], [12939, 10843, 100000, 129, 240, 0]],
                         'a line that ended before 1.12.1 is left out; a template reaches its creatures')
        self.assertEqual(self.pack['npc_names']['12939'], 'Doctor Gustaf VanHowzen', 'the 1.12 version of a template')

    def test_drops_and_vendors_of_1_12(self):
        self.assertEqual(self.pack['drops'], [['npc', 500, 7000, 2.5]], 'a loot row that ended before 1.12 is left out')
        self.assertEqual(self.pack['sells'], [[600, 7001, 2]], 'a vendor template reaches its creature')
        self.assertEqual(self.pack['never_given'], [7002])

    def test_holiday_spawns(self):
        faire = self.pack['holidays']['4']
        self.assertEqual([c[:2] for c in faire['creatures']], [[1, 14829], [2, 600]], 'a spawn gone before 1.12 is left out')
        self.assertEqual(faire['creatures'][0][7:], [180, 2.0, 1], "respawn, VMaNGOS' wander distance and movement type")
        self.assertIn(faire['creatures'][1][1], (600, 601), 'a spawn that picks among creatures keeps one of them')

    def test_unreachable_givers_dropped(self):
        out = {'creature': [{'id': 600}, {'id': 0}], 'creature_spawn_entry': [{'guid': 2, 'entry': 601}],
               'creature_template': [{'Entry': 600, 'VendorTemplateId': 9}, {'Entry': 7747, 'VendorTemplateId': 8}],
               'npc_vendor': [{'entry': 600, 'item': 1}, {'entry': 601, 'item': 2}, {'entry': 7747, 'item': 2413}],
               'npc_vendor_template': [{'entry': 9, 'item': 3}, {'entry': 8, 'item': 4}, {'entry': 1279201, 'item': 16509}],
               'quest_template': [{'entry': q, 'Title': t} for q, t in ((1, 'Call of Water'), (2, '<NYI> <TXT> Ring of the Dawn'),
                                  (3, '<UNUSED>Infused Bandages'), (4, 'Legends of the Earth <NYI>'), (5, 'REUSE'),
                                  (6, 'Hunter test quest'), (7, 'The Test of Righteousness'), (8, 'Test Kill Quest'))]}
        vmangos_pack.unreachable(out)
        self.assertEqual([r['entry'] for r in out['npc_vendor']], [600, 601], 'a vendor never spawned sells nothing')
        self.assertEqual([r['entry'] for r in out['npc_vendor_template']], [9], 'a list only unspawned or no creatures use')
        self.assertEqual([q['entry'] for q in out['quest_template']], [1, 7], 'a real quest with "Test" in its name stays')

    def test_newest_patch_up_to_1_12(self):
        rows = [{'entry': 1, 'patch': 0}, {'entry': 1, 'patch': 7}, {'entry': 1, 'patch': 11}, {'entry': 2, 'patch': 12}]
        self.assertEqual(vmangos_pack.newest(rows, ('entry',), 'patch', 10), [{'entry': 1, 'patch': 7}])

    def test_ft_classic_reads_it_from_the_release_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, 'db-test.zip')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('mysql-dump/mangos.sql', DUMP)
            out = os.path.join(tmp, 'out.cdbpack')
            vmangos_pack.main(['vmangos_pack.py', archive, out])
            pack = classic.load(out)
            self.assertEqual(pack['source'], 'VMaNGOS')
            self.assertIn(10843, classic.taught(pack))


if __name__ == '__main__':
    unittest.main()
