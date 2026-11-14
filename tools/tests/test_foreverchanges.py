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
        'Dungeons': 'ForeverMasterData.dungeons = {{id="fixture",name="Fixture",bosses={{name="Boss",items={100}}},quests={{id=50,npc=77,title="Quest",xp=200}},steps={[51]={title="Previous"}}}}\nForeverMasterData.instances = {[3000]={"fixture"}}',
        'World': 'ForeverMasterData.world = {quests={[50]={"Quest",10},[52]={"Label only",nil}}}',
        'Chains': 'ForeverMasterData.books = {books={{quest=53,item=101,tier=20}}}\nForeverMasterData.sleepingBag = {steps={{quest=54,side="a"}}}',
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
        self.assertEqual(by['recipe', 900].data['datasets']['recipe'][0]['teaching_item'], '101')
        self.assertEqual(by['recipe', 900].data['datasets']['recipe'][0]['green'], '')
        self.assertEqual(by['quest', 50].data['datasets']['dungeon_quest'][0]['npc'], 77)
        self.assertTrue(by['spell', 901].data['datasets']['class_training'][0]['first_rank_from_talent'])
        self.assertFalse(by['spell', 902].data['datasets']['class_training'][0]['first_rank_from_talent'])
        self.assertEqual(by['dungeon', 3000].data['inventory']['talent_presets'], 1)
        self.assertFalse(any(r.subject_kind == 'talent' for r in records))

    def test_reference_source_cannot_supply_public_or_live_values(self):
        registry = layers.load()
        self.assertEqual(registry.source('foreverchanges')['use'], 'reference')
        self.assertFalse(registry.publishable(['foreverchanges']))
        self.assertFalse(registry.trusted('foreverchanges'))
        self.assertFalse(registry.witness('foreverchanges', '', 70888)[1])
        self.assertEqual(registry.witnesses(['foreverchanges','atlasloot']), 1)

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
