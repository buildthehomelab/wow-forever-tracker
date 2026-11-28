"""python -m unittest discover -s tools/tests

Gathering (ft.gather): the work list of what the content still to come needs, from made-up sources.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import facts, gather  # noqa: E402

Fact = facts.Fact
PHASES = [{'key': 'now', 'name': 'Open now', 'opens': None}, {'key': 'first-raids', 'name': 'First raids', 'opens': '2026-12-09'},
          {'key': 'not-out', 'name': 'Not out yet', 'opens': None, 'wowhead_no_source': True}]


def sources(icy=None):
    src = gather.Sources()
    answers = icy or {}
    src.icy = lambda kind, entry: answers.get((kind, entry))
    return src


class Read(unittest.TestCase):
    def test_eglink_records_objectives_and_givers(self):
        src = sources()
        src.read_eglink([
            Fact('quest', 'quest', 100, 0, 70959, 3, {'title': 'x', 'objectives': [{'type': 'monster', 'objectId': 7}, {'type': 'gameObject', 'objectId': 8},
                                                                                     {'type': 'item', 'objectId': 9}, {'type': 'talkTo', 'objectId': 10}]}),
            Fact('gives', 'npc', 50, 100, 70959, 1, {}), Fact('takes', 'object', 51, 100, 70959, 1, {}),
            Fact('creature', 'npc', 7, 0, 70959, 1, {}), Fact('seen', 'npc', 7, 0, 70959, 4, {'positions': [[1, 2], [3, 4]]})])
        self.assertEqual(src.records, {100: 'eglink'})
        self.assertEqual(src.objectives[100], {('npc', 7), ('object', 8), ('item', 9)})
        self.assertEqual(dict(src.relations[100]['gives']), {('npc', 50): {'eglink'}})
        self.assertEqual(dict(src.relations[100]['takes']), {('object', 51): {'eglink'}})
        self.assertEqual(src.creature_records, {7})
        self.assertEqual(src.seen[7], 2)

    def test_wowhead_quick_facts_and_tabs(self):
        src = sources()
        src.read_wowhead({'quest': {100: {'id': 100, 'status': 'ok', 'quick': ['Start: [url=/forever/npc=50]', 'End: [url=/forever/object=51]', 'Level: 10']}},
                          'npc': {60: {'id': 60, 'status': 'ok', 'tabs': {'ends': {'rows': [{'id': 101}]}}}}})
        self.assertEqual(set(src.relations[100]['gives']), {('npc', 50)})
        self.assertEqual(set(src.relations[100]['takes']), {('object', 51)})
        self.assertEqual(set(src.relations[101]['takes']), {('npc', 60)})

    def test_icyveins_quest(self):
        src = sources({('quest', 100): {'relations': {'addon_givers': [{'npc_id': 50, 'starts': 1, 'ends': 1}],
                                                      'started_by_items': [{'id': 900}], 'quest_items': [{'id': 901}]}}})
        self.assertTrue(src.icyveins_quest(100))
        self.assertFalse(src.icyveins_quest(101))
        self.assertEqual(set(src.relations[100]['gives']), {('npc', 50), ('item', 900)})
        self.assertEqual(set(src.relations[100]['takes']), {('npc', 50)})
        self.assertIn(('item', 901), src.objectives[100])

    def test_pages_newest_wins(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            with open(os.path.join(a, 'npc.jsonl'), 'w') as f:
                f.write(json.dumps({'id': 5, 'fetched': 10, 'status': 'missing'}) + '\nnot json\n')
            with open(os.path.join(b, 'npc.jsonl'), 'w') as f:
                f.write(json.dumps({'id': 5, 'fetched': 20, 'status': 'ok'}) + '\n')
            with open(os.path.join(b, 'forever-list.jsonl'), 'w') as f:
                f.write(json.dumps({'kind': 'list', 'query': 'npcs?filter=37:37;2:4;1:20000', 'rows': [{'id': 5, 'location': [3456]}, {'id': 6}]}) + '\n')
            self.assertEqual(gather.wowhead_pages(('npc', 'item'), [a, b])['npc'][5]['status'], 'ok')
            self.assertEqual(gather.wowhead_listed([a, b]), {('npc', 5): [3456]})


class Compact(unittest.TestCase):
    def test_keeps_what_is_read(self):
        page = {'id': 60, 'fetched': 5, 'v': 2, 'status': 'ok', 'quick': ['Level: 10', 'Start: [url=/forever/npc=1]'],
                'tabs': {'drops': {'rows': [{'id': 9, 'count': 3}]}, 'dropped-by': {'rows': [{'id': 7, 'count': 1, 'outof': 9}]}, 'ends': {'rows': [{'id': 101}]}},
                'map': {'1519': [{'count': 2, 'coords': [[10, 20], [11, 21]]}], '12': [{'coords': [[1, 1]]}]}, 'model': [123]}
        small = gather.compact(page)
        self.assertEqual(small['quick'], ['Start: [url=/forever/npc=1]'])
        self.assertEqual(small['tabs'], {'dropped-by': {'rows': [{'id': 7}]}, 'ends': {'rows': [{'id': 101}]}})
        self.assertTrue(small['model'])
        src = sources()
        src.read_wowhead({'npc': {60: small}})
        targets = {'now': {'quest': {}, 'item': {}, 'npc': {60: ['quest:5']}, 'object': {}}}
        row = gather.build(targets, Build.SERVER, src, PHASES)['phases'][0]['npcs'][0]
        self.assertEqual((row['pins'], row['model']), (3, True))
        self.assertEqual(set(src.relations[101]['takes']), {('npc', 60)})


class Build(unittest.TestCase):
    SERVER = {'quest': {200}, 'npc_template': {50, 70}, 'npc_spawned': {50}, 'object_template': set(), 'object_spawned': set()}

    def work(self, targets, src):
        return gather.build(targets, self.SERVER, src, PHASES)

    def test_quest_needs_and_wanted_pages(self):
        src = sources({('item', 300): {'relations': {'addon_dropped_by': [{'npc_id': 80, 'chance': 0.2}]}}})
        src.read_eglink([Fact('quest', 'quest', 100, 0, 70959, 3, {'objectives': [{'type': 'monster', 'objectId': 70}]})])
        src.read_questie([Fact('gives', 'npc', 50, 100, 0, 1, {}), Fact('takes', 'npc', 60, 100, 0, 1, {})])
        targets = {'now': {'quest': {100: {'name': 'New quest', 'status': 'missing'}}, 'item': {}, 'npc': {}, 'object': {}},
                   'first-raids': {'quest': {}, 'item': {300: {'name': 'Raid loot', 'status': 'missing', 'for': []}}, 'npc': {}, 'object': {}}}
        out = self.work(targets, src)
        now, raids, _ = out['phases']
        quest = now['quests'][0]
        self.assertEqual((quest['record'], quest['server'], quest['ready']), ('eglink', False, True))
        self.assertEqual(quest['gives'], {'npc:50': ['questie']})
        self.assertEqual(quest['objectives'], ['npc:70'])
        # 50 has a template and a spawn: nothing needed; 60 has nothing; 70 a template but no spawn
        self.assertEqual([r['id'] for r in now['npcs']], [60, 70])
        self.assertEqual(now['npcs'][1]['template'], True)
        self.assertFalse(now['npcs'][0]['ready'])
        self.assertEqual(out['wowhead']['now'], {'quest': [100], 'npc': [60, 70]})
        # the raid's item: Icy Veins names its creature, which the server lacks
        self.assertEqual(raids['items'][0]['icy_dropped_by'], 1)
        self.assertTrue(raids['items'][0]['ready'])
        self.assertEqual([r['id'] for r in raids['npcs']], [80])
        self.assertEqual(raids['npcs'][0]['for'], ['item:300'])
        self.assertEqual(out['wowhead']['first-raids'], {'npc': [80], 'item': [300]})
        self.assertEqual(sorted(out['icyveins']['npc']), [60, 70, 80])
        self.assertEqual(raids['counts']['item'], {'all': 1, 'ready': 1})

    def test_not_out_items_are_not_queued_again(self):
        targets = {'not-out': {'quest': {}, 'item': {400: {'name': 'x', 'status': 'missing', 'for': []}}, 'npc': {}, 'object': {}}}
        out = self.work(targets, sources())
        self.assertEqual(out['wowhead']['not-out'], {})
        self.assertEqual(out['phases'][2]['items'][0]['id'], 400)

    def test_world_drops_name_no_creature(self):
        page = {'status': 'ok', 'tabs': {'dropped-by': {'rows': [{'id': n} for n in range(1000, 1020)]}}}
        src = sources()
        src.read_wowhead({'item': {300: page}})
        targets = {'first-raids': {'quest': {}, 'item': {300: {'name': 'x', 'status': 'missing', 'for': []}}, 'npc': {}, 'object': {}}}
        out = self.work(targets, src)
        self.assertEqual(out['phases'][1]['npcs'], [])
        self.assertEqual(out['phases'][1]['items'][0]['tabs'], ['dropped-by'])

    def test_placed_by_pins(self):
        src = sources()
        src.read_wowhead({'npc': {60: {'status': 'ok', 'map': {'1519': [{'count': 2, 'coords': [[10, 20], [11, 21]]}]}, 'model': [123]}}})
        targets = {'now': {'quest': {}, 'item': {}, 'npc': {60: ['quest:5']}, 'object': {}}}
        row = self.work(targets, src)['phases'][0]['npcs'][0]
        self.assertEqual((row['pins'], row['model'], row['wowhead'], row['ready']), (2, True, 'ok', False))   # no template source yet


class Targets(unittest.TestCase):
    def test_rows_to_targets(self):
        rows = [('quest', 100, 'Missing', 'missing', 'now', ''),
                ('quest', 101, 'Partial', 'partial', 'now', '[{"detail": "creature 260373 not spawned | item 268990 not obtainable | object 668004 not spawned"}]'),
                ('quest', 102, 'Raid', 'partial', 'first-raids', ''),
                ('item', 300, 'Loot', 'missing', 'first-raids', ''),
                ('item', 301, 'Open item', 'missing', 'now', '')]
        out = gather.targets_from(rows, {'first-raids': {2159}}, {('npc', 90): [2159], ('npc', 91): [12]})
        self.assertEqual(set(out['now']['quest']), {100})
        self.assertEqual(out['now']['npc'], {260373: ['quest:101']})
        self.assertEqual(out['now']['object'], {668004: ['quest:101']})
        self.assertEqual(out['now']['item'][268990]['for'], ['quest:101'])
        self.assertEqual(set(out['first-raids']['quest']), {102})
        self.assertEqual(out['first-raids']['item'][300]['name'], 'Loot')
        self.assertEqual(out['first-raids']['npc'], {90: ['instance']})
        self.assertNotIn(301, out['now']['item'])

    def test_spells_that_make_an_item(self):
        # Creeping Pain 2895: made by spell 2838 nothing here casts; Wowhead's page of a second spell names an unspawned caster
        checks = json.dumps([{'code': 'source', 'ok': False, 'detail': {'en': 'Inactive source: recipe that cannot be learned (spell 2838, 2840); '
                                                                            'on Wowhead it is cast by creature 7 not spawned'}}])
        out = gather.targets_from([('item', 2895, 'Creeping Pain', 'partial', 'now', checks)], {}, {})
        self.assertEqual(out['now']['spell'], {2838: ['item:2895'], 2840: ['item:2895']})
        self.assertEqual(out['now']['npc'], {7: ['item:2895']})
        self.assertEqual(out['now']['item'], {})                     # an open item itself is not the list's
        built = gather.build(out, {'quest': set(), 'npc_template': set(), 'npc_spawned': set(), 'object_template': set(),
                                   'object_spawned': set()}, sources(), [{'key': 'now', 'name': 'Open now', 'opens': None}])
        self.assertEqual(built['wowhead']['now']['spell'], [2838, 2840])

    def test_open_quest_without_ender(self):
        # a Craftsman's Writ the server has, with no ender: listed so the crawl reads its page; one with both is not
        no_ender = json.dumps([{'code': 'starter', 'ok': True}, {'code': 'ender', 'ok': False}])
        no_giver = json.dumps([{'code': 'starter', 'ok': False}, {'code': 'ender', 'ok': True}])
        both = json.dumps([{'code': 'starter', 'ok': True}, {'code': 'ender', 'ok': True}, {'code': 'objectives', 'ok': False}])
        rows = [('quest', 94330, 'Writ', 'partial', 'now', no_ender), ('quest', 98830, 'Glaive', 'partial', 'now', no_giver),
                ('quest', 98893, 'Marks', 'partial', 'now', both), ('quest', 7, 'Broken', 'partial', 'now', '{not json')]
        out = gather.targets_from(rows, {}, {})
        self.assertEqual(set(out['now']['quest']), {94330, 98830})


class Run(unittest.TestCase):
    """run() end to end: the tracker's rows and the world from a made-up database, EG Link from a made-up download."""

    def test_writes_the_list(self):
        out = self.run_gather(set())
        now, raids = out['phases']
        self.assertEqual(out['sources'], {'eglink': self.commit, 'wowhead_pages': 0})
        self.assertEqual(now['quests'][0]['gives'], {'npc:50': ['eglink']})
        self.assertTrue(now['quests'][0]['ready'])
        self.assertEqual([r['id'] for r in now['npcs']], [70])      # 205 drops the objective item and stands on the server
        self.assertEqual(raids['key'], 'first-raids')
        self.assertEqual(raids['items'][0]['id'], 300)
        self.assertEqual(out['wowhead'], {'now': {'quest': [100], 'npc': [70], 'item': [4234]}, 'first-raids': {'item': [300]}})

    def test_a_summoned_creature_is_in_the_world(self):
        # creature 70 has no spawn row, but a script summons it (ft.summons): nothing to place, no page wanted for it
        out = self.run_gather({70})
        self.assertEqual([r['id'] for r in out['phases'][0]['npcs']], [])
        self.assertNotIn('npc', out['wowhead']['now'])

    commit = 'a' * 40

    def run_gather(self, summoned):
        from unittest import mock
        commit = self.commit
        commit = 'a' * 40
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as pages:
            build = os.path.join(data, 'eglink', commit, '1.60.1.70959')
            os.makedirs(build)
            with open(os.path.join(build, 'quests.enUS.json'), 'w') as f:
                json.dump({'quests': {'100': {'title': 'New', 'objectives': [{'type': 'monster', 'objectId': 70}]}}}, f)
            with open(os.path.join(build, 'npcs.json'), 'w') as f:
                json.dump({'npcs': {'50': {'offers': {'100': {}}, 'takes': {'100': {}}}}}, f)
            entities = [{'type': 'quest', 'id': '100', 'name_en': 'New', 'status': 'missing', 'phase': '0', 'checks': None},
                        {'type': 'item', 'id': '300', 'name_en': 'Loot', 'status': 'missing', 'phase': '1', 'checks': ''}]
            # a summoned creature has its template (Majordomo Executus): only its spawn row is missing
            world = {'quest_template': [], 'creature_template': ['50', '205'] + [str(e) for e in summoned], 'creature': ['50', '205'], 'gameobject_template': [], 'gameobject': []}
            # the quest also asks for item 4234, which creature 205 (on the server, spawned) drops
            icy = {('item', 4234): {'relations': {'addon_dropped_by': [{'npc_id': 205}]}}}
            with open(os.path.join(build, 'quests.enUS.json')) as f:
                quests = json.load(f)
            quests['quests']['100']['objectives'].append({'type': 'item', 'objectId': 4234})
            with open(os.path.join(build, 'quests.enUS.json'), 'w') as f:
                json.dump(quests, f)

            def column(sql, database='world'):
                table = sql.split('FROM `')[1].split('`')[0]
                asked = sql.split('IN (')[1].rstrip(')').split(',')
                return [entry for entry in world[table] if entry in asked]

            phase_list = [{'key': 'first-raids', 'name': 'First raids', 'opens': '2026-12-09', 'counts': {}}]
            with mock.patch.object(gather, 'DATA', data), mock.patch.object(gather, 'FILE', os.path.join(data, 'gather.json')), \
                    mock.patch.object(gather.sqlio, 'query', lambda sql, database='world': entities), \
                    mock.patch.object(gather.sqlio, 'column', column), \
                    mock.patch.object(gather.facts, 'fetch_eglink', lambda *a, **k: 0), \
                    mock.patch.object(gather.phase_rules, 'load', lambda: []), \
                    mock.patch.object(gather.icyveins, 'cached', lambda kind, entry, folder=None: icy.get((kind, entry))), \
                    mock.patch.object(gather.summons, 'known', lambda: (summoned, set(), {})), \
                    mock.patch.object(gather, 'log', lambda message: None):
                gather.run({'dungeon': {}}, phase_list, folders=[pages])
            with open(os.path.join(data, 'gather.json')) as f:
                return json.load(f)


if __name__ == '__main__':
    unittest.main()
