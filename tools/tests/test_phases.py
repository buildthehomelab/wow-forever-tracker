"""python -m unittest discover -s tools/tests

Release phases (ft.phases): which official resources a later phase opens, from a small made-up server.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import phases  # noqa: E402

MC, ONY, WORLD = 409, 249, 0
RAGNAROS, GEDDON, TRASH, VENDOR, KAZZAK, GIVER, TRAINER_NPC = 11502, 12056, 11666, 5000, 12397, 6000, 7000

PHASES = [{'key': 'first-raids', 'name': 'First raids', 'opens': '2026-12-09', 'maps': ["Onyxia's Lair"], 'npcs': [], 'objects': [], 'quests': [], 'items': []},
          {'key': 'later-raids', 'name': 'Later raids', 'opens': None, 'maps': ['Molten Core'], 'npcs': ['Lord Kazzak'], 'objects': [], 'quests': [9999], 'items': [8888]}]


def content():
    return {
        'dungeon': {MC: {'name': 'Molten Core', 'name_en': 'Molten Core', 'facts': {'area': 2717}},
                    ONY: {'name': "Onyxia's Lair", 'name_en': "Onyxia's Lair", 'facts': {'area': 2159}},
                    36: {'name': 'Deadmines', 'name_en': 'Deadmines', 'facts': {'area': 1581}}},
        'boss': {672: {'name': 'Ragnaros', 'name_en': 'Ragnaros', 'map': MC}, 663: {'name': 'Baron Geddon', 'name_en': 'Baron Geddon', 'map': MC},
                 1084: {'name': 'Onyxia', 'name_en': 'Onyxia', 'map': ONY}, 300: {'name': 'Van Cleef', 'name_en': 'Edwin VanCleef', 'map': 36}},
        'quest': {q: {} for q in (100, 101, 102, 103, 104, 105, 9999)},
        'item': {i: {} for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 8888)},
        'spell': {500: {'sub': 'profession'}, 501: {'sub': 'profession'}},
        'recipe': {500: {}, 501: {}},
        'mount': {20: {'spell': 600}},
        'toy': {30: {'item': 6}},
    }


def ctx():
    return {
        # Geddon is spawned in Molten Core; Ragnaros is not spawned anywhere; the trash also stands outside
        'npc_maps': {MC: [{'id': GEDDON}, {'id': TRASH}], WORLD: [{'id': TRASH}, {'id': VENDOR}, {'id': GIVER}, {'id': TRAINER_NPC}, {'id': KAZZAK}]},
        'loot': {'creature': [(RAGNAROS, 0, 1, 0), (GEDDON, 0, 0, 77), (TRASH, 0, 3, 0)],
                 'reference': [(77, 0, 2, 0)],
                 'pickpocketing': [], 'skinning': [], 'gameobject': [], 'item': [(4, 0, 5, 0)], 'spell': [],
                 'fishing': [], 'mail': [], 'disenchant': [], 'prospecting': [], 'milling': []},
        'npc_loot': [(RAGNAROS, RAGNAROS, 0, 0), (GEDDON, GEDDON, 0, 0), (TRASH, TRASH, 0, 0)],
        'go_loot': [], 'vendors': [(VENDOR, 9)], 'quest_items_npc': [], 'quest_items_go': [], 'shop_items': set(),
        # item 7 is crafted with recipe 500 (taught by item 1, Ragnaros' drop); item 8 with recipe 501 (a trainer teaches it too)
        'creates': {7: {500}, 8: {501}}, 'teaches': {500: {1}, 501: {2}, 600: {2}},
        'trainer_spells': [(1, 501)], 'auto_learn': set(), 'create_spells': set(), 'learn_chain': [],
        'quests': {100: {'QuestSortID': 2717}, 105: {'QuestSortID': 2717}, 101: {'QuestSortID': 0, 'RewardItem1': 4}, 102: {'QuestSortID': 0}, 103: {'QuestSortID': 0},
                   104: {'QuestSortID': 0}, 9999: {'QuestSortID': 0}},
        'q_start_npc': [(GIVER, 101), (GIVER, 103), (GIVER, 104), (GIVER, 105)], 'q_start_go': [],
        'q_end_npc': [(GIVER, 101), (GIVER, 102), (GIVER, 103), (GIVER, 104), (GIVER, 105)], 'q_end_go': [],
        # 101 asks for Geddon's drop; 102 starts from item 1 (no giver); 103 asks to kill the trash; 104 asks for the vendor's item
        'objectives': [(101, 1, 2, 1), (103, 0, TRASH, 1), (104, 1, 9, 1)],
        'start_quest_item': {102: 1},
    }


FACTS = {'npc_names': {RAGNAROS: 'Ragnaros', KAZZAK: 'Lord Kazzak'}, 'go_maps': [], 'located': []}


class Assign(unittest.TestCase):
    def setUp(self):
        self.tagged = phases.assign(content(), ctx(), PHASES, FACTS)

    def test_instances_and_bosses(self):
        self.assertEqual(self.tagged[('dungeon', MC)], 2)
        self.assertEqual(self.tagged[('dungeon', ONY)], 1)
        self.assertEqual(self.tagged[('boss', 672)], 2)
        self.assertEqual(self.tagged[('boss', 1084)], 1)
        self.assertNotIn(('dungeon', 36), self.tagged)
        self.assertNotIn(('boss', 300), self.tagged)

    def test_loot_of_spawned_and_unspawned_bosses(self):
        self.assertEqual(self.tagged[('item', 1)], 2)   # Ragnaros: not spawned, matched by the encounter's name
        self.assertEqual(self.tagged[('item', 2)], 2)   # Geddon: spawned in Molten Core, through a reference table

    def test_open_world_source_keeps_it_released(self):
        self.assertNotIn(('item', 3), self.tagged)      # the trash also stands outside
        self.assertNotIn(('item', 9), self.tagged)      # a vendor outside
        self.assertNotIn(('quest', 103), self.tagged)
        self.assertNotIn(('quest', 104), self.tagged)
        self.assertNotIn(('recipe', 501), self.tagged)  # a trainer teaches it
        self.assertNotIn(('item', 8), self.tagged)

    def test_quests(self):
        self.assertEqual(self.tagged[('quest', 100)], 2)  # sorted under Molten Core, no giver on the server
        self.assertNotIn(('quest', 105), self.tagged)       # sorted there too, but given and handed in outside (an attunement)
        self.assertEqual(self.tagged[('quest', 101)], 2)  # asks for a Molten Core drop
        self.assertEqual(self.tagged[('quest', 102)], 2)  # starts from a Molten Core drop
        self.assertEqual(self.tagged[('quest', 9999)], 2)  # listed by id

    def test_chains(self):
        self.assertEqual(self.tagged[('item', 4)], 2)     # reward of quest 101
        self.assertEqual(self.tagged[('item', 5)], 2)     # inside container 4
        self.assertEqual(self.tagged[('recipe', 500)], 2)  # taught only by a Molten Core drop
        self.assertEqual(self.tagged[('spell', 500)], 2)
        self.assertEqual(self.tagged[('item', 7)], 2)     # crafted only with that recipe
        self.assertEqual(self.tagged[('mount', 20)], 2)   # its spell is taught by Geddon's drop
        self.assertEqual(self.tagged[('item', 8888)], 2)  # listed by id

    def test_spells_listed_by_id(self):
        c, x = content(), ctx()
        c['spell'][502] = {'sub': 'class'}
        listed = [dict(p, spells=[]) for p in PHASES]
        listed[1]['spells'] = [502, 501]
        tagged = phases.assign(c, x, listed, FACTS)
        self.assertEqual(tagged[('spell', 502)], 2)    # nothing teaches it: listed, so it waits for the phase
        self.assertEqual(tagged[('spell', 501)], 2)    # the list wins over a trainer, as for items and quests
        self.assertNotIn(('spell', 502), self.tagged)  # without the list it stays released (no source at all)

    def test_items_without_source_stay_released(self):
        self.assertNotIn(('item', 6), self.tagged)
        self.assertNotIn(('toy', 30), self.tagged)

    def test_wowhead_names_no_source(self):
        # item 6 has no source on the server (a toy's item); item 9 a vendor; item 8888 is listed by id; 77 is no item
        listed = [dict(p) for p in PHASES] + [{'key': 'not-out', 'name': 'Not out yet', 'opens': None, 'maps': [], 'npcs': [], 'objects': [],
                                               'quests': [], 'items': [], 'wowhead_no_source': True}]
        facts = dict(FACTS, wowhead_no_source={6, 9, 8888, 77})
        tagged = phases.assign(content(), ctx(), listed, facts)
        self.assertEqual(tagged[('item', 6)], 3)     # no source anywhere: it waits until a page names one
        self.assertEqual(tagged[('toy', 30)], 3)     # and what only it gives waits with it
        self.assertNotIn(('item', 9), tagged)        # the server sells it: the rule is only for items nothing gives
        self.assertEqual(tagged[('item', 8888)], 2)  # a list names its phase first
        self.assertEqual(facts['wowhead_no_source_tagged'], {6})
        # without a phase marked for it, the pages change nothing
        self.assertNotIn(('item', 6), phases.assign(content(), ctx(), PHASES, dict(FACTS, wowhead_no_source={6})))

    def test_a_recipe_wowhead_does_not_have(self):
        # item 11 is crafted with recipe 503, which only item 4444 teaches: a Classic plan Forever dropped (Wowhead has no
        # Forever page for it, and the client does not list it); item 7's recipe item 1 drops from Ragnaros
        listed = [dict(p) for p in PHASES] + [{'key': 'not-out', 'name': 'Not out yet', 'opens': None, 'maps': [], 'npcs': [], 'objects': [],
                                               'quests': [], 'items': [], 'wowhead_no_source': True}]
        c, x = content(), ctx()
        c['item'][11] = {}
        x['creates'][11] = {503}
        x['teaches'][503] = {4444}
        facts = dict(FACTS, wowhead_missing={4444, 1, 9})
        tagged = phases.assign(c, x, listed, facts)
        self.assertEqual(tagged[('item', 11)], 3)        # what only the lost plan teaches waits with it
        self.assertNotEqual(tagged.get(('item', 7)), 3)  # item 1 has a source: a missing page changes nothing
        self.assertNotIn(('item', 9), tagged)            # and an item that teaches nothing is not a lost recipe
        self.assertEqual(facts['wowhead_lost_recipes_tagged'], {4444})
        # a trainer that teaches the spell keeps the craft released
        x['trainer_spells'] = x['trainer_spells'] + [(1, 503)]
        self.assertNotIn(('item', 11), phases.assign(c, x, listed, dict(FACTS, wowhead_missing={4444})))

    def test_wowhead_missing_items(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            def write(folder, rows):
                with open(os.path.join(folder, 'item.jsonl'), 'w', encoding='utf-8') as handle:
                    handle.write('\n'.join(json.dumps(r) for r in rows) + '\n')
            write(old, [{'id': 1, 'fetched': 10, 'status': 'missing'}, {'id': 2, 'fetched': 10, 'status': 'ok', 'tabs': {}}])
            write(new, [{'id': 1, 'fetched': 20, 'status': 'ok', 'tabs': {}}, {'id': 3, 'fetched': 20, 'status': 'missing'}])
            self.assertEqual(phases.wowhead_missing_items([old, new]), {3})

    def test_wowhead_says_black_market(self):
        # item 6 has no source on the server and its page also names none: the Black Market rule comes first
        listed = [dict(p) for p in PHASES] + [
            {'key': 'not-out', 'name': 'Not out yet', 'opens': None, 'maps': [], 'npcs': [], 'objects': [], 'quests': [], 'items': [], 'wowhead_no_source': True},
            {'key': 'black-market', 'name': 'Black Market', 'opens': None, 'maps': [], 'npcs': [], 'objects': [], 'quests': [], 'items': [], 'wowhead_black_market': True}]
        facts = dict(FACTS, wowhead_no_source={6}, wowhead_black_market={6, 9})
        tagged = phases.assign(content(), ctx(), listed, facts)
        self.assertEqual(tagged[('item', 6)], 4)
        self.assertEqual(tagged[('toy', 30)], 4)    # what only it gives waits with it
        self.assertNotIn(('item', 9), tagged)       # the server's vendor sells it
        self.assertEqual(facts['wowhead_black_market_tagged'], {6})
        self.assertNotIn(6, facts.get('wowhead_no_source_tagged', set()))
        # stocked on the realm's Black Market by a seller who stands in the world: released
        x = ctx()
        x['blackmarket_items'] = [(VENDOR, 6)]
        self.assertNotIn(('item', 6), phases.assign(content(), x, listed, dict(FACTS, wowhead_black_market={6})))

    def test_wowhead_black_market_items(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            def write(folder, rows):
                with open(os.path.join(folder, 'item.jsonl'), 'w', encoding='utf-8') as handle:
                    handle.write('\n'.join(json.dumps(r) for r in rows) + '\n')
            write(old, [{'id': 1, 'fetched': 10, 'status': 'ok', 'quick': ['Sold on the Black Market']},
                        {'id': 2, 'fetched': 10, 'status': 'ok', 'quick': ['New in Forever']}])
            write(new, [{'id': 1, 'fetched': 20, 'status': 'ok', 'quick': ['Consumable']},          # the newer page no longer says it
                        {'id': 2, 'fetched': 20, 'status': 'ok', 'quick': ['New in Forever', 'Sold on the Black Market']},
                        {'id': 3, 'fetched': 20, 'status': 'missing', 'quick': ['Sold on the Black Market']}])
            self.assertEqual(phases.wowhead_black_market_items([old, new]), {2})

    def test_unsourced_pages(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            def write(folder, records):
                with open(os.path.join(folder, 'item.jsonl'), 'w', encoding='utf-8') as handle:
                    handle.write('\n'.join(json.dumps(r) for r in records) + '\nnot json\n')
            write(old, [{'id': 1, 'fetched': 10, 'status': 'ok', 'tabs': {}},                      # read again later with a vendor
                        {'id': 2, 'fetched': 10, 'status': 'ok', 'tabs': {'sold-by': {'rows': [{'id': 5}]}}},   # read again later, no source now
                        {'id': 3, 'fetched': 10, 'status': 'ok', 'tabs': {'same-model-as': {'rows': [{'id': 1}]}, 'dropped-by': {'rows': []}}}])
            write(new, [{'id': 1, 'fetched': 20, 'status': 'ok', 'tabs': {'sold-by': {'rows': [{'id': 5}]}}},
                        {'id': 2, 'fetched': 20, 'status': 'ok', 'tabs': {}},
                        {'id': 4, 'fetched': 20, 'status': 'missing'},                              # Wowhead has no page: not "no source"
                        {'id': 5, 'fetched': 20, 'status': 'ok', 'tabs': {'reward-from-q': {'rows': [{'id': 9}]}}}])
            self.assertEqual(phases.wowhead_unsourced_items([old, new, os.path.join(new, 'none')]), {2, 3})

    def test_wowhead_reward_quests(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            def write(folder, rows):
                with open(os.path.join(folder, 'item.jsonl'), 'w', encoding='utf-8') as handle:
                    handle.write('\n'.join(json.dumps(r) for r in rows) + '\nnot json\n')
            write(old, [{'id': 1, 'fetched': 10, 'status': 'ok', 'tabs': {'reward-from-q': {'rows': [{'id': 77}]}}}])
            write(new, [{'id': 1, 'fetched': 20, 'status': 'ok', 'tabs': {'reward-from-q': {'rows': [{'id': 84394}, {'id': 0}]}}},
                        {'id': 2, 'fetched': 20, 'status': 'missing', 'tabs': {'reward-from-q': {'rows': [{'id': 5}]}}},
                        {'id': 3, 'fetched': 20, 'status': 'ok', 'tabs': {'dropped-by': {'rows': [{'id': 9}]}}}])
            # the newest page of item 1 wins (77 is gone from it); a page Wowhead does not have counts for nothing
            self.assertEqual(phases.wowhead_reward_quests([old, new, os.path.join(new, 'none')]), {84394})

    def test_lowest_phase_wins(self):
        c, x = content(), ctx()
        x['npc_maps'][ONY] = [{'id': TRASH}]
        x['npc_maps'][WORLD] = [n for n in x['npc_maps'][WORLD] if n['id'] != TRASH]
        tagged = phases.assign(c, x, PHASES, FACTS)
        self.assertEqual(tagged[('item', 3)], 1)  # the trash stands in Onyxia's Lair (1) and Molten Core (2)

    def test_named_npc(self):
        x = ctx()
        x['vendors'] = [(KAZZAK, 6)]
        tagged = phases.assign(content(), x, PHASES, FACTS)
        self.assertEqual(tagged[('item', 6)], 2)  # Lord Kazzak is listed by name, though spawned outside
        self.assertEqual(tagged[('toy', 30)], 2)

    def test_located_npc(self):
        x = ctx()
        x['npc_loot'].append((4242, 4242, 0, 0))
        x['loot']['creature'].append((4242, 0, 6, 0))
        tagged = phases.assign(content(), x, PHASES, dict(FACTS, located=[('npc', 4242, MC)]))
        self.assertEqual(tagged[('item', 6)], 2)  # not spawned, the locator placed it in Molten Core

    def test_a_copy_without_a_source_waits_with_the_original(self):
        c = content()
        c['item'][1] = {'name_en': 'Sulfuras, Hand of Ragnaros'}        # Ragnaros' drop
        c['item'][6] = {'name_en': 'Sulfuras, Hand of Ragnaros'}        # Forever's own copy: a new id, no source yet
        tagged = phases.assign(c, ctx(), PHASES, FACTS)
        self.assertEqual(tagged[('item', 6)], 2)
        c['item'][9] = {'name_en': 'Sulfuras, Hand of Ragnaros'}        # ...unless one of that name is sold outside
        self.assertNotIn(('item', 6), phases.assign(c, ctx(), PHASES, FACTS))

    def test_a_quest_of_another_game_version_gives_nothing(self):
        x = ctx()
        x['quests'][70000] = {'QuestSortID': 0, 'RewardItem1': 1}       # not in the official client
        x['q_start_npc'].append((GIVER, 70000))
        x['q_end_npc'].append((GIVER, 70000))
        self.assertEqual(phases.assign(content(), x, PHASES, FACTS)[('item', 1)], 2)   # still only Ragnaros' drop

    def test_an_item_that_starts_its_own_quest_is_not_given_by_it(self):
        x = ctx()
        x['quests'][102]['StartItem'] = 1                               # Ragnaros' drop starts quest 102 and is its StartItem
        tagged = phases.assign(content(), x, PHASES, FACTS)
        self.assertEqual(tagged[('item', 1)], 2)                        # the quest does not hand out what starts it
        self.assertEqual(tagged[('quest', 102)], 2)                     # and waits with the item that starts it

    def test_an_item_only_unlisted_quests_reward_waits_with_them(self):
        x = ctx()
        x['quests'][70000] = {'QuestSortID': 0, 'RewardItem1': 6}       # not in the official client; asks for Geddon's drop
        x['q_start_npc'].append((GIVER, 70000))
        x['q_end_npc'].append((GIVER, 70000))
        x['objectives'].append((70000, 1, 2, 1))
        tagged = phases.assign(content(), x, PHASES, FACTS)
        self.assertEqual(tagged[('item', 6)], 2)                        # nothing else gives item 6: it waits for Molten Core
        self.assertEqual(tagged[('toy', 30)], 2)                        # and so does what hangs on it
        self.assertNotIn(('quest', 70000), tagged)                      # the quest itself is still not listed
        x['quests'][70001] = {'QuestSortID': 0, 'RewardChoiceItemID2': 6}   # a second one, open today: no phase says when
        x['q_start_npc'].append((GIVER, 70001))
        x['q_end_npc'].append((GIVER, 70001))
        self.assertNotIn(('item', 6), phases.assign(content(), x, PHASES, FACTS))
        x['quests'][70001]['RewardChoiceItemID2'] = 9                   # an item sold outside stays released
        self.assertNotIn(('item', 9), phases.assign(content(), x, PHASES, FACTS))

    def test_the_package_a_giver_hands_over(self):
        x = ctx()
        x['quests'][104]['StartItem'] = 6                               # quest 104 is open: so is its package
        self.assertNotIn(('item', 6), phases.assign(content(), x, PHASES, FACTS))
        x['quests'][101]['StartItem'] = 8888 + 1
        c = content()
        c['item'][8889] = {}
        self.assertEqual(phases.assign(c, x, PHASES, FACTS)[('item', 8889)], 2)        # quest 101 waits for Molten Core

    def test_no_phases(self):
        self.assertEqual(phases.assign(content(), ctx(), [], FACTS), {})


class Closed(unittest.TestCase):
    """Which phases are not open: the same answer as the website (closed_phases() in app/bootstrap.php)."""

    def test_each_phase_opens_on_its_date(self):
        self.assertEqual(phases.closed(PHASES, today='2026-12-08'), [1, 2])
        self.assertEqual(phases.closed(PHASES, today='2026-12-09'), [2])   # no date: stays closed

    def test_current_decides_when_set(self):
        self.assertEqual(phases.closed(PHASES, 'all', today='2026-01-01'), [])
        self.assertEqual(phases.closed(PHASES, 'none', today='2027-01-01'), [1, 2])
        self.assertEqual(phases.closed(PHASES, 'First-Raids', today='2026-01-01'), [2])
        self.assertEqual(phases.closed(PHASES, '2', today='2026-01-01'), [])
        self.assertEqual(phases.closed(PHASES, 'no-such-phase', today='2026-12-09'), [2])   # a typo: the dates decide


class Load(unittest.TestCase):
    def write(self, data):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(data, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_shipped_file(self):
        loaded = phases.load(phases.DEFAULT)
        self.assertGreaterEqual(len(loaded), 2)
        self.assertTrue(all(set(phases.KINDS) <= set(p) for p in loaded))

    def test_spell_ids_only(self):
        path = self.write({'phases': [{'key': 'x', 'opens': None, 'spells': ['Teleport: Dalaran']}]})
        with self.assertRaises(SystemExit):
            phases.load(path)

    def test_bad_date_stops(self):
        with self.assertRaises(ValueError):
            phases.load(self.write({'phases': [{'key': 'a', 'opens': '2026-13-01', 'maps': []}]}))

    def test_names_in_id_lists_stop(self):
        with self.assertRaises(SystemExit):
            phases.load(self.write({'phases': [{'key': 'a', 'items': ['Eye of Sulfuras']}]}))

    def test_duplicate_key_stops(self):
        with self.assertRaises(SystemExit):
            phases.load(self.write({'phases': [{'key': 'a'}, {'key': 'a'}]}))

    def test_unmatched_names(self):
        self.assertEqual(phases.unmatched_maps([dict(PHASES[0], maps=["Onyxia's Lair", 'Barrow Deeps', 409])], content()), [('first-raids', 'Barrow Deeps')])


if __name__ == '__main__':
    unittest.main()
