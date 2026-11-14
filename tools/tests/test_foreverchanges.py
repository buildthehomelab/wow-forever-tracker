"""Synthetic ForeverMaster fixtures: no third-party addon tables in the tests."""
import collections
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft import facts, foreverchanges as fc, layers


def archive(overrides=None, extra=None):
    data = {name: '' for name in fc.FILES}
    data.update({
        'Pack': 'ForeverMasterData.pack = {version="fixture", build="1.60.1.70888", hash="fixture"}',
        'Items': 'ForeverMasterData.items = {[100]="n|m|Fixture boss",[101]="|v|Vendor in Classic"}',
        'Search': 'ForeverMasterData.names = [==[\n2s Fixture item\n1 Other item\n]==]',
        'Recipes': 'ForeverMasterData.recipes = {Alchemy = {[900]="10|15||20|100||101|n|2:3,4"}}',
        'Professions': 'ForeverMasterData.professions = {Alchemy = {learn={[900]=10}}}',
        'Leveling': 'ForeverMasterData.leveling["Alchemy"] = {recipes={"900|10|15|17|20|100|1|2:3,4|d|0|0|0|101"}}',
        'Training': 'ForeverMasterData.training = {MAGE={{name="Fixture",talent=true,ranks={{901,10},{902,20}}}}}',
        'Trainers': 'ForeverMasterData.trainers = {class={MAGE={{77,"Trainer","A",1,50,50}}},prof={}}',
        'Dungeons': 'ForeverMasterData.dungeons = {{id="fixture",name="Fixture",bosses={{name="Boss",level=20,items={100,101},chances={12.5,3}},{name="Empty",items={}}},'
                    'questItems={{item=101,quest=50,title="Quest",from={"Boss"}}},quests={{id=50,npc=77,title="Quest",xp=200}},steps={[51]={title="Previous"}}},'
                    '{id="new",name="New",bosses={{name="New boss",items={100}}},quests={},questItems={}}}\nForeverMasterData.instances = {[3000]={"fixture"}}',
        'Journal': 'ForeverMasterData.entrances = {{"fixture",1455,43.6,51.7,1415,48.5,52.5}}',
        'World': 'ForeverMasterData.world = {layers={"givers","vendor"},words={"","Giver","Captain","Seller"},quests={[50]={"Quest",10},[52]={"Label only",nil}},'
                 'maps={[1429]="1,48.9,40.2,1,2,0,a,50/52;2,10,10,3,0,0,h;1,1,1,1,0,0,,;broken",[1453]="1,5.5,6.5,1,2,0,a,50"}}',
        'Chains': 'ForeverMasterData.books = {librarians={{side="a",npc=78,name="Librarian",uiMap=1453,x=1,y=2}},books={{quest=53,item=101,tier=20}}}\nForeverMasterData.sleepingBag = {steps={{quest=54,side="a"}}}',
        'Rewards': 'ForeverMasterData.reputation = {vendors={town={npc=77}},items={[101]={"town","Honored",500}}}',
        'Talents': 'ForeverMasterData.talents = {MAGE={{level=20,code="123"}}}',
    })
    data.update(overrides or {})
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, text in data.items():
            z.writestr(f'ForeverMaster/Data/{name}.lua', text)
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return out.getvalue()


class ForeverChanges(unittest.TestCase):
    def load(self, raw):
        folder = Path(self.temp.name) / hashlib.sha256(raw).hexdigest()[:16]
        fc.fetch(folder.name, folder, fetch=lambda url: raw)
        return folder, list(fc.read(folder))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_relations_merged_under_resource_ids_without_world_claims(self):
        _, records = self.load(archive())
        by = {(r.subject_kind, r.subject): r for r in records}
        self.assertEqual({r.kind for r in records}, {'reference'})
        self.assertTrue(all(r.samples == 0 and r.build == 70888 and facts.check(r) for r in records))
        self.assertEqual(len(by), len(records))
        self.assertEqual(set(by['item', 100].data['datasets']), {'search_name','item_hint','crafted_by','boss_loot_hint'})
        self.assertTrue(by['item', 101].data['datasets']['item_hint'][0]['explicitly_classic'])
        self.assertEqual(by['recipe', 900].data['datasets']['recipe'][0]['teaching_item'], 101)
        self.assertIsNone(by['recipe', 900].data['datasets']['recipe'][0]['green'])
        self.assertEqual(by['quest', 50].data['datasets']['dungeon_quest'][0]['npc'], 77)
        self.assertTrue(by['spell', 901].data['datasets']['class_training'][0]['first_rank_from_talent'])
        self.assertFalse(by['spell', 902].data['datasets']['class_training'][0]['first_rank_from_talent'])
        self.assertFalse(any(r.subject_kind == 'talent' for r in records))

    def test_fields_are_named_and_numbers_are_numbers(self):
        _, records = self.load(archive())
        by = {(r.subject_kind, r.subject): r.data['datasets'] for r in records}
        self.assertEqual(by['item', 100]['item_hint'][0], {'status': 'new', 'source_kind': 'creature', 'hint': 'Fixture boss', 'explicitly_classic': False})
        self.assertEqual(by['recipe', 900]['recipe'][0], {'profession': 'Alchemy', 'learn': 10, 'yellow': 15, 'green': None, 'grey': 20, 'creates': 100,
                                                          'count': 1, 'teaching_item': 101, 'status': 'new', 'reagents': [[2, 3], [4, 1]]})
        self.assertEqual(by['recipe', 900]['leveling'][0], {'profession': 'Alchemy', 'learn': 10, 'yellow': 15, 'green': 17, 'grey': 20, 'creates': 100,
                                                            'count': 1, 'reagents': [[2, 3], [4, 1]], 'source': 'drop', 'rod': None, 'price': 0, 'fee': 0,
                                                            'teaching_item': 101})
        self.assertEqual(by['npc', 77]['trainer_location'][0], {'category': 'MAGE', 'name': 'Trainer', 'side': 'A', 'map': 1, 'x': 50, 'y': 50})
        self.assertEqual(fc._recipe_source('vl'), {'source': 'vendor', 'limited_stock': True})
        self.assertEqual(fc._recipe_source('vh'), {'source': 'vendor', 'side': 'Horde'})
        self.assertEqual(fc._recipe_source('f'), {'source': "merchant's favor"})

    def test_what_the_pack_states_by_id_is_kept(self):
        _, records = self.load(archive())
        by = {(r.subject_kind, r.subject): r.data['datasets'] for r in records}
        # a boss's level, and the pack's own chance for a Classic boss only (as many chances as items)
        self.assertEqual(by['item', 101]['boss_loot_hint'][0]['classic_chance'], 3)
        self.assertEqual(by['item', 101]['boss_loot_hint'][0]['level'], 20)
        self.assertEqual([h for h in by['item', 100]['boss_loot_hint'] if h['boss'] == 'New boss'][0].get('classic_chance'), None)
        # which quest an item is for, on both sides
        self.assertEqual(by['item', 101]['quest_item'][0], {'item': 101, 'quest': 50, 'title': 'Quest', 'from': ['Boss'], 'dungeon': 'fixture'})
        self.assertEqual(by['quest', 50]['quest_item'][0]['item'], 101)
        self.assertEqual(by['dungeon', 3000]['dungeon'][0]['entrances'], [{'map': 1455, 'x': 43.6, 'y': 51.7, 'continent': 1415, 'continent_x': 48.5, 'continent_y': 52.5}])
        self.assertEqual(by['npc', 78]['librarian'][0]['name'], 'Librarian')
        self.assertEqual(by['npc', 77]['reputation_vendor'][0], {'item': 101, 'standing': 'Honored', 'price': 500})

    def test_quest_givers_of_the_map_layer_come_by_name_with_their_pins(self):
        skipped = collections.Counter()
        folder, _ = self.load(archive())
        by = {(r.subject_kind, r.subject): r.data['datasets'] for r in fc.read(folder, skipped)}
        self.assertEqual(by['quest', 50]['map_giver'], [{'name': 'Giver', 'title': 'Captain', 'side': 'a', 'pins': [[1429, 48.9, 40.2], [1453, 5.5, 6.5]]}])
        self.assertEqual(by['quest', 52]['map_giver'][0]['pins'], [[1429, 48.9, 40.2]])        # a vendor pin and a giver without quests say nothing
        self.assertFalse(any('map_giver' in d for (kind, _), d in by.items() if kind != 'quest'))

    def test_what_is_the_same_for_every_record_is_said_once(self):
        folder, records = self.load(archive())
        self.assertTrue(all(set(r.data) == {'pack', 'datasets'} and r.data['pack'] == 'fixture' for r in records))
        about = {}
        list(fc.read(folder, about=about))
        self.assertEqual(about['inventory']['talent_presets'], 1)
        self.assertEqual(about['pack']['build'], '1.60.1.70888')
        self.assertEqual(len(about['archive_sha256']), 64)

    def test_reference_source_cannot_supply_public_or_live_values(self):
        registry = layers.load()
        self.assertEqual(registry.source('foreverchanges')['use'], 'reference')
        self.assertFalse(registry.publishable(['foreverchanges']))
        self.assertFalse(registry.trusted('foreverchanges'))
        self.assertFalse(registry.witness('foreverchanges', '', 70888)[1])
        self.assertEqual(registry.witnesses(['foreverchanges','atlasloot']), 1)
        # its map layer is QuestieDB's and its town services cmangos': no second witness beside them, and one with its own pages
        self.assertEqual(registry.witnesses(['foreverchanges','questie']), 1)
        self.assertEqual(registry.witnesses(['foreverchanges','cmangos']), 1)
        self.assertEqual(registry.witnesses(['foreverchanges','foreverchanges-pages']), 1)
        self.assertEqual(registry.source('foreverchanges-pages')['use'], 'reference')
        self.assertFalse(registry.publishable(['foreverchanges-pages']))
        self.assertFalse(registry.witness('foreverchanges-pages', '', 70938)[1])

    def test_archive_pin_and_cache_are_verified(self):
        folder, _ = self.load(archive())
        self.assertEqual(fc.fetch(folder.name, folder, fetch=lambda _: self.fail('cache should be used')), 0)
        (folder/'ForeverMaster.zip').write_bytes(b'corrupted')
        with self.assertRaises(facts.SourceError):
            fc.fetch(folder.name, folder)
        with self.assertRaises(facts.SourceError):
            fc.archive_data(archive(), '0'*16)
        with self.assertRaises(facts.SourceError):
            fc.fetch('../bad', folder)

    def test_no_zip_paths_escape_and_no_lua_is_executed(self):
        raw = archive(extra={'../outside': 'no'})
        with self.assertRaises(facts.SourceError):
            self.load(raw)
        raw = archive({'Recipes': 'ForeverMasterData.recipes = {Alchemy = function() error("not data") end}'})
        with self.assertRaises(facts.SourceError):
            self.load(raw)

    def test_invalid_compact_data_fails_before_database_load(self):
        for override in ({'Items':'ForeverMasterData.items = {[100]="broken"}'},
                         {'Recipes':'ForeverMasterData.recipes = {Alchemy = {[900]="broken"}}'},
                         {'Recipes':'ForeverMasterData.recipes = {Alchemy = {[900]="ten|15||20|100||101|n|2:3,4"}}'},
                         {'Leveling':'ForeverMasterData.leveling["Alchemy"] = {recipes={"900|10|15"}}'},
                         {'Pack':'ForeverMasterData.pack = {build="wrong"}'}):
            with self.subTest(override=override), self.assertRaises(facts.SourceError):
                self.load(archive(override))

    def test_sql_targets_only_tracker_fact_tables(self):
        folder, records = self.load(archive())
        output = folder/'facts.sql'
        facts.write_sql(str(output), 'foreverchanges', folder.name, 'All Rights Reserved', 'reference', records)
        sql = output.read_text()
        self.assertIn('START TRANSACTION;', sql)
        self.assertIn("DELETE FROM ft_world_facts WHERE source = 'foreverchanges'", sql)
        self.assertNotIn('INSERT INTO npc_vendor', sql)
        self.assertNotIn('INSERT INTO quest_template', sql)
        self.assertTrue(sql.endswith('COMMIT;\n'))


if __name__ == '__main__':
    unittest.main()
