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
    NPC_OGRE            = 10601,
    NPC_THELDREN_CREDIT = 16166
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
struct NodeInfo { uint32 Flag; uint32 KillCredit; };
static NodeInfo const NodeData[] = { { 180087, 15001 }, { 180088, 15002 } };
void Capture(Player* player, uint8 node) { player->KilledMonsterCredit(NodeData[node].KillCredit); player->KilledMonsterCredit(NPC_THELDREN_CREDIT); }
void Player::KilledMonsterCredit(uint32 entry, ObjectGuid guid) { }
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
# The Classic scripts' shapes: a helper of their own, an array a summon picks from, an entry swap, and the ones that
# are no creature (a summon group's id, a passenger slot)
SHAPES = '''
enum { NPC_SOLAKAR = 10264, NPC_FIREBRAND_GRUNT = 9045, NPC_BANNOK_GRIMAXE = 9596, SUMMON_ACOLYTES = 1, SLOT_MAGE = 11 };
uint32 const BrdRingBoss[] = { 9027, 9028, 9029 };
uint32 const Waves[] = { 1, 2, 3 };
TempSummon* SummonRookeryCreature(uint32 entry, Position const& pos) { return instance->SummonCreature(entry, pos); }
void Rookery() { SummonRookeryCreature(NPC_SOLAKAR, Position(43.7f, -259.8f, 91.6f, 0.0f)); }
void Ring() { me->SummonCreature(BrdRingBoss[urand(0, 2)], x, y, z); me->SummonCreature(Waves[i], x, y, z); }
void Group() { me->SummonCreatureGroup(SUMMON_ACOLYTES); _controller.SummonCreatures(SLOT_MAGE, SLOT_MAGE); }
uint32 GetCreatureEntry(ObjectGuid::LowType spawnId, CreatureData const* data) override
{
    if (data->id == NPC_FIREBRAND_GRUNT && urand(0, 99) < 5)
        return NPC_BANNOK_GRIMAXE;
    return data->id;
}
'''


class Shapes(unittest.TestCase):
    def test_helpers_arrays_and_entry_swaps(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'Classic', 'brs.cpp')
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(SHAPES)
            creatures, _objects, _encounters, _credits = make_summoned.scan(folder)
        self.assertEqual(set(creatures), {10264, 9027, 9028, 9029, 9596})   # no 1, 2, 3 or 11: indexes, a group, a slot

    def test_numbered_boss_slots(self):
        text = '''
constexpr Entry Bosses[] = { { 0, 253201 }, { 1, 261811 }, { 1, 253218 }, { 2, 7 } };
constexpr Spell Spells[] = { { 261811, 1287747 } };
static constexpr DungeonEncounterData encounters[] = { { 0, {{ 3498 }} }, { 1, {{ 3499 }} }, { 2, {{ 3500 }} } };
'''
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'Custom', 'terrace.cpp')
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(text)
            # a row in another file of the folder says nothing about this one's numbered slots
            with open(os.path.join(folder, 'Custom', 'other.cpp'), 'w', encoding='utf-8') as handle:
                handle.write('constexpr Entry Other[] = { { 0, 99999 } };\n')
            encounters = make_summoned.scan(folder)[2]
        self.assertEqual(encounters[3498], {253201})
        self.assertEqual(encounters[3499], {261811, 253218})   # two creatures, one encounter
        self.assertNotIn(3500, encounters)                     # 7 is no creature

# zone_silithus.cpp's own helper takes the entry third, sometimes picked at random; tables a summon reads a field of
SILITHUS = '''
enum { NPC_TEMPLAR_FIRE = 15209, NPC_TEMPLAR_WATER = 15211, NPC_DUKE_FIRE = 15206, SPELL_TEMPLAR_FIRE = 24748, NPC_HELPER_SPELL_NPC_X = 1 };
enum { SPELL_SUMMON_NPC_ROYAL = 24800, CLASSIC_BWL_NPC_DRAKANOID = 14302, NPC_RIDER = 13576, NPC_THORIM_ADD = 32885, NPC_SCRYER_ADD = 14514, NPC_ROYAL_GONE = 15999 };
struct WaveData
{
    uint8 SpawnCount;
    uint8 UsedSpawnPoint;
    uint32 CreatureId;
    uint32 SpawnTimer;
};
static WaveData WavesInfo[3] =
{
    {30,  0, 15423, 0},    // Kaldorei Soldier
    { 3, 35, 15424, 0},
    {12, 38, 15414, 0}
};
struct SummonLocation
{
    Position pos;
    uint32 entry;
};
SummonLocation const PreAddLocations[] =
{
    { { 2149.68f, -263.477f, 419.679f, 3.120f }, NPC_THORIM_ADD },
    { { 2131.31f, -271.640f, 419.840f, 2.188f }, 32886 },
};
struct Scryer { uint8 Wave; uint32 DelaySeconds; uint32 Entry; bool Attacks; Position Pos; };
std::array<Scryer, 2> const Scryers = {{
    { 1, 1, NPC_SCRYER_ADD, true, { 103.0f, 141.2f, 93.9f, 1.4f } },
    { 2, 5, 14516, false, { 121.7f, 136.9f, 93.4f, 1.0f } },
}};
void SummonNPC(GameObject* go, Player* player, uint32 npc, uint32 spell) { go->SummonCreature(npc, pos); }
void Use() { SummonNPC(me, player, NPC_TEMPLAR_FIRE, SPELL_TEMPLAR_FIRE); SummonNPC(me, player, RAND(NPC_TEMPLAR_WATER, NPC_DUKE_FIRE), SPELL_SUMMON_NPC_ROYAL); }
void Waves() { me->SummonCreature(WavesInfo[WaveCount].CreatureId, SpawnLocation[i]); }
void Adds() { for (SummonLocation const& s : PreAddLocations) me->SummonCreature(s.entry, s.pos); }
void Scry(uint8 i) { Scryer const& data = Scryers[i]; me->SummonCreature(data.Entry, data.Pos); }
void Bwl() { me->SummonCreature(urand(0, 1) ? CLASSIC_BWL_NPC_DRAKANOID : NPC_RIDER, pos); }
Creature* found = me->GetSummonedCreatureByEntry(NPC_ROYAL_GONE);
'''


class Helpers(unittest.TestCase):
    """Summons a first-argument reading misses: an entry given later, picked at random, or read from a table."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'Kalimdor', 'zone_silithus.cpp')
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(SILITHUS)
            cls.creatures = set(make_summoned.scan(folder)[0])

    def test_an_entry_given_after_other_arguments(self):
        self.assertTrue({15209, 15211, 15206} <= self.creatures, 'SummonNPC(me, player, NPC_TEMPLAR_FIRE, ...) and RAND(...)')

    def test_a_spell_is_no_creature(self):
        self.assertFalse({24748, 24800, 1, 15999} & self.creatures, "a spell, and a look-up of what was summoned")

    def test_a_field_of_a_table_of_numbers(self):
        self.assertTrue({15423, 15424, 15414} <= self.creatures)
        self.assertFalse({30, 3, 12, 35, 38} & self.creatures, 'the other fields of the rows are counts and points')

    def test_a_row_of_a_range_for_and_a_reference(self):
        self.assertTrue({32885, 32886, 14514, 14516} <= self.creatures, 'nested positions, std::array, `Row const& data = Table[i]`')

    def test_a_scripts_own_prefix_and_a_ternary(self):
        self.assertTrue({14302, 13576} <= self.creatures)


class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        for path, text in (('Spire/spire.h', HEADER), ('Spire/instance_spire.cpp', INSTANCE), ('Classic/zf/classic_zf.cpp', CLASSIC)):
            full = os.path.join(cls.folder.name, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as handle:
                handle.write(text)
        cls.creatures, cls.objects, cls.encounters, cls.credits = make_summoned.scan(cls.folder.name)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_a_summon_call_with_a_constant_or_a_number(self):
        self.assertEqual(self.creatures, {10601: 'Spire/instance_spire.cpp', 12345: 'Spire/instance_spire.cpp'})
        self.assertEqual(self.objects, {175245: 'Spire/instance_spire.cpp'})

    def test_a_kill_credit_a_script_gives(self):
        # a field of a table's rows (Arathi Basin's bases) and a constant; the function's own definition is no call
        self.assertEqual(set(self.credits), {15001, 15002, 16166})

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


class Teleports(unittest.TestCase):
    """A map a script teleports the player into: the instance has an entrance no table shows."""

    def test_a_constant_a_number_and_a_variable(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, 'cod'))
            with open(os.path.join(folder, 'cod', 'cod.cpp'), 'w', encoding='utf-8') as handle:
                handle.write('constexpr uint32 CLASSIC_COD_MAP_ID = 2959;\n'
                             'void a(Player* player) { player->TeleportTo(CLASSIC_COD_MAP_ID, 1.0f, 2.0f, 3.0f, 0.0f); }\n'
                             'void b(Player* player) { player->TeleportTo(3065, 1.0f, 2.0f, 3.0f, 0.0f); }\n'
                             'void c(Player* player, uint32 mapId) { player->TeleportTo(mapId, 1.0f, 2.0f, 3.0f, 0.0f); }\n'
                             '// player->TeleportTo(1234, 0, 0, 0, 0);\n')
            self.assertEqual(make_summoned.teleports(folder), {2959: 'cod/cod.cpp', 3065: 'cod/cod.cpp'})

    def test_the_shipped_list_knows_city_of_dalaran(self):
        self.assertIn(2959, summons.core()['teleports'])


class Shipped(unittest.TestCase):
    def test_the_list_reads_and_knows_the_classic_events(self):
        lists = summons.core()
        self.assertGreater(len(lists['creatures']), 300)
        self.assertEqual(lists['encounters'].get(594), [7273])     # Gahz'rilla, Zul'Farrak
        self.assertIn(1853, lists['encounters'].get(2801, []))     # Darkmaster Gandling, Scholomance
        self.assertIn(12580, lists['creatures'])                   # Reginald Windsor walks into Stormwind
        for entry in (9028, 10264, 9596):                          # Grizzle, Solakar Flamewreath, Bannok Grimaxe
            self.assertIn(entry, lists['creatures'])
        for entry in (15209, 15211, 15212, 15307, 15203, 15305):   # the Abyssal Council of Silithus' Wind Stones
            self.assertIn(entry, lists['creatures'])

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
