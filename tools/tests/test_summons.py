"""python -m unittest discover -s tools/tests

What the core's C++ scripts bring into the world (tools/make_summoned.py -> ft.summons): the reader of the script
files, on small copies of the shapes TrinityCore's instance scripts use, and the shipped list itself.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import make_summoned  # noqa: E402
from ft import summons  # noqa: E402

HEADER = '''
enum SPCreatureIds
{
    NPC_UROK_DOOMHOWL   = 10584,
    NPC_GIZRUL          = 10268,
    NPC_OGRE            = 10601
};
enum SPData { DATA_UROK_DOOMHOWL = 4, DATA_HALYCON = 6, DATA_GIZRUL = 7, DATA_DOOR = 9 };
enum SPObjects { GO_CHEST = 175245, GO_DOOR = 175244 };
'''
INSTANCE = '''
static constexpr DoorData doorData[] = { { GO_DOOR, DATA_HALYCON, EncounterDoorBehavior::OpenWhenDone } };
static constexpr ObjectData creatureData[] = { { NPC_GIZRUL, DATA_GIZRUL } };
static constexpr DungeonEncounterData Encounters[] =
{
    { DATA_UROK_DOOMHOWL, { { 271 } } },
    { DATA_HALYCON, { { 274 } } },
    { DATA_GIZRUL, {{ 273 }} },
};
void Spawn() { me->SummonCreature(NPC_OGRE, pos); instance->DoSummonGameObject(GO_CHEST, pos); }
// me->SummonCreature(99999, pos);
void Other(uint32 entry) { me->SummonCreature(entry, pos); me->SummonCreature(12345, pos); }
'''
CLASSIC = '''
enum { CZF_ENC_GAHZRILLA = 1, CZF_ENC_UKORZ = 7 };
constexpr ClassicDungeonBossEntry Entries[] =
{
    { CZF_ENC_GAHZRILLA, 7273 }, // Gahz'rilla
    { CZF_ENC_UKORZ, 7267 },
    { CZF_ENC_UKORZ, 7797, CLASSIC_DUNGEON_BOSS_ENGAGE_ONLY }
};
static constexpr DungeonEncounterData encounters[] = { { CZF_ENC_GAHZRILLA, {{ 594 }} }, { CZF_ENC_UKORZ, {{ 600 }} } };
'''


class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        for path, text in (('Spire/spire.h', HEADER), ('Spire/instance_spire.cpp', INSTANCE), ('Classic/zf/classic_zf.cpp', CLASSIC)):
            full = os.path.join(cls.folder.name, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as handle:
                handle.write(text)
        cls.creatures, cls.objects, cls.encounters = make_summoned.scan(cls.folder.name)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_a_summon_call_with_a_constant_or_a_number(self):
        self.assertEqual(self.creatures, {10601: 'Spire/instance_spire.cpp', 12345: 'Spire/instance_spire.cpp'})
        self.assertEqual(self.objects, {175245: 'Spire/instance_spire.cpp'})

    def test_a_variable_and_a_comment_are_left_out(self):
        self.assertNotIn(99999, self.creatures)

    def test_an_object_table_ties_the_creature_to_the_encounter(self):
        self.assertEqual(self.encounters[273], {10268})

    def test_the_constant_of_the_same_name_when_no_table_does(self):
        self.assertEqual(self.encounters[271], {10584})

    def test_a_door_is_no_boss(self):
        self.assertNotIn(274, self.encounters)  # Halycon: only a door row names the slot

    def test_a_table_of_slot_and_number(self):
        self.assertEqual(self.encounters[594], {7273})
        self.assertEqual(self.encounters[600], {7267, 7797})


class Shipped(unittest.TestCase):
    def test_the_list_reads_and_knows_the_classic_events(self):
        lists = summons.core()
        self.assertGreater(len(lists['creatures']), 300)
        self.assertEqual(lists['encounters'].get(594), [7273])     # Gahz'rilla, Zul'Farrak
        self.assertIn(1853, lists['encounters'].get(2801, []))     # Darkmaster Gandling, Scholomance
        self.assertIn(12580, lists['creatures'])                   # Reginald Windsor walks into Stormwind

    def test_a_missing_or_broken_file_is_an_empty_list(self):
        self.assertEqual(summons.core('/nonexistent/summoned.json')['encounters'], {})
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            handle.write('{"creatures": [1, 2]}')
        try:
            self.assertEqual(summons.core(handle.name)['creatures'], {})
        finally:
            os.unlink(handle.name)


if __name__ == '__main__':
    unittest.main()
