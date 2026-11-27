"""python -m unittest discover -s tools/tests

The availability rules (ft.rules.evaluate_all) on a world small enough to read: a handful of creatures, quests and
items built by hand. No database: the context is what ft.server would have read.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import rules, server  # noqa: E402

rules.log = lambda *_: None   # the analysis' progress lines

KINDS = ('item', 'spell', 'talent', 'quest', 'dungeon', 'boss', 'zone', 'recipe', 'mount', 'pet', 'toy', 'achievement', 'taxi')
LOOT_TABLES = ('creature', 'gameobject', 'item', 'reference', 'pickpocketing', 'skinning', 'fishing', 'disenchant', 'prospecting', 'milling', 'spell', 'mail')


def world(**over):
    """An empty server: every list the rules read, with nothing in it."""
    ctx = {
        'known': {kind: set() for kind in KINDS}, 'spawned_npc': set(), 'spawned_go': set(), 'summoned_npc': set(), 'summoned_go': set(),
        'kill_credit': {}, 'encounter_npc': {}, 'unspawned_npc': [], 'npc_maps': {}, 'go_counts': {}, 'spawns': [], 'flight_spawns': [],
        'script_taxi_nodes': set(), 'trainers': [], 'trainer_spells': [], 'loot': {name: [] for name in LOOT_TABLES}, 'npc_loot': [], 'go_loot': [],
        'quest_items_npc': [], 'quest_items_go': [], 'vendors': [], 'shop_items': set(), 'quests': {}, 'quest_turn_in_text': set(),
        'quest_display_spells': {}, 'q_start_npc': [], 'q_start_go': [], 'q_end_npc': [], 'q_end_go': [], 'objectives': [], 'disabled': {},
        'start_quest_item': {}, 'auto_learn': set(), 'teaches': {}, 'creates': {}, 'create_spells': set(), 'learn_chain': [], 'pet_training': set(),
        'never_learned': set(), 'cast_by': {}, 'tree_spells': set(), 'spell_teaches': set(), 'achievement_currency': set(),
        'conversation_casts': [],
        'scripted_spells': set(), 'spell_ids': set(), 'achievement_rewards': set(), 'graveyards': set(), 'instance_template': {}, 'entrances': set(),
        'battlegrounds': set(), 'map_tiles': {}, 'mmaps': set(), 'vmaps': set(), 'ui_maps': [],
    }
    ctx.update(over)
    return ctx


def quest_row(**more):
    return {'QuestType': 2, 'HasText': 1, 'QuestSortID': 0, 'StartItem': 0, 'RewardSpell': 0, **more}


def evaluate(content, ctx):
    full = {kind: {} for kind in KINDS}
    full.update(content)
    for kind, rows in full.items():
        ctx['known'][kind] |= set(rows)
    return rules.evaluate_all(full, ctx)


def failed(result):
    return sorted(c['code'] for c in result[2] if not c['ok'])


class ReplacedGiver(unittest.TestCase):
    """A quest only an old twin gives (a creature live never sent, replaced by a spawned one of its name) is not given
    on WoW: Forever; a giver that is merely unspawned still fails."""

    def setUp(self):
        # 16012 Mokvar: the Classic copy, no spawn; 230317 Mokvar: live's copy, spawned in Orgrimmar
        self.ctx = world(spawned_npc={230317}, npc_maps={1: [{'id': 230317, 'n': 1, 'name': 'Mokvar', 'scripted': False}]},
                         q_start_npc=[(16012, 10), (230317, 11)], q_end_npc=[(16012, 10), (230317, 11)],
                         quests={10: quest_row(), 11: quest_row()}, quest_turn_in_text={10, 11},
                         quest_npc_names={16012: 'Mokvar', 230317: 'Mokvar'}, live_npcs={230317: 'Mokvar'})
        self.content = {'quest': {10: {}, 11: {}}}

    def test_a_quest_only_the_replaced_giver_gives(self):
        results = evaluate(self.content, self.ctx)
        self.assertEqual(results[('quest', 10)][0], 'ok')
        starter = [c for c in results[('quest', 10)][2] if c['code'] == 'starter'][0]
        self.assertIn('230317', starter['detail']['en'])
        self.assertEqual(results[('quest', 11)][0], 'ok')

    def test_without_live_records_it_is_a_missing_giver(self):
        self.ctx['live_npcs'] = {}
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('quest', 10)]), ['ender', 'starter'])

    def test_live_sent_the_old_one_too(self):
        self.ctx['live_npcs'] = {230317: 'Mokvar', 16012: 'Mokvar'}
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('quest', 10)]), ['ender', 'starter'])

    def test_nobody_gives_it_and_only_the_replaced_one_takes_it(self):
        # quest 12: its giver link was taken away, only the old copy takes it
        self.ctx['q_end_npc'].append((16012, 12))
        self.ctx['quests'][12] = quest_row()
        self.ctx['quest_turn_in_text'].add(12)
        self.content['quest'][12] = {}
        results = evaluate(self.content, self.ctx)
        self.assertEqual(results[('quest', 12)][0], 'ok')
        self.assertIn('nobody gives it', [c for c in results[('quest', 12)][2] if c['code'] == 'starter'][0]['detail']['en'])

    def test_an_ender_merely_unspawned_still_fails(self):
        self.ctx['q_end_npc'].append((555, 13))
        self.ctx['quests'][13] = quest_row()
        self.content['quest'][13] = {}
        self.assertIn('starter', failed(evaluate(self.content, self.ctx)[('quest', 13)]))

    def test_live_copy_not_spawned(self):
        self.ctx['spawned_npc'], self.ctx['npc_maps'] = set(), {}
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('quest', 10)]), ['ender', 'starter'])

    def test_the_imports_are_told_which_quests_are_not_given(self):
        # quest 12: a giver still gives it on this server (an import put it back), only the old copy takes it
        self.ctx['q_start_npc'].append((230317, 12))
        self.ctx['q_end_npc'].append((16012, 12))
        self.ctx['quests'][12] = quest_row()
        self.content['quest'][12] = {}
        evaluate(self.content, self.ctx)
        self.assertEqual(self.ctx['not_given_quests'], {10, 12})

    def test_an_item_only_a_not_given_quest_rewards(self):
        # item 500: quest 10's reward (only the old Mokvar gives it); item 501: also rewarded by quest 14, which a
        # creature nobody spawned gives: still a gap
        self.ctx['quests'][10] = quest_row(RewardChoiceItemID1=500, RewardChoiceItemID2=501)
        self.ctx['q_start_npc'].append((555, 14))
        self.ctx['q_end_npc'].append((555, 14))
        self.ctx['quests'][14] = quest_row(RewardItem1=501)
        self.content['quest'][14] = {}
        self.content['item'] = {500: {}, 501: {}}
        results = evaluate(self.content, self.ctx)
        self.assertEqual(results[('item', 500)][0], 'ok')
        source = [c for c in results[('item', 500)][2] if c['code'] == 'source'][0]
        self.assertIn('Not given on WoW: Forever', source['detail']['en'])
        self.assertEqual(failed(results[('item', 501)]), ['source'])

    def test_a_disabled_quest_is_no_other_way_in(self):
        self.ctx['quests'][10] = quest_row(RewardItem1=500)
        self.ctx['quests'][15] = quest_row(RewardItem1=500)
        self.ctx['disabled'] = {1: {15}}
        self.content['quest'][15] = {}
        self.content['item'] = {500: {}}
        self.assertEqual(evaluate(self.content, self.ctx)[('item', 500)][0], 'ok')

    def test_without_live_records_the_reward_is_a_gap(self):
        self.ctx['live_npcs'] = {}
        self.ctx['quests'][10] = quest_row(RewardItem1=500)
        self.content['item'] = {500: {}}
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('item', 500)]), ['source'])

    def test_no_live_records_nothing_is_not_given(self):
        self.ctx['live_npcs'] = {}
        evaluate(self.content, self.ctx)
        self.assertEqual(self.ctx['not_given_quests'], set())


class Summoned(unittest.TestCase):
    """A creature a script brings in is there: its loot, its stock and its quests count."""

    def setUp(self):
        # creature 100 drops item 1, sells item 2, gives and takes quest 10; creature 200 trains spell 5
        self.ctx = world(npc_loot=[(100, 900, 0, 0)], vendors=[(100, 2)], q_start_npc=[(100, 10)], q_end_npc=[(100, 10)],
                         quests={10: quest_row()}, quest_turn_in_text={10}, trainers=[(200, 7)], trainer_spells=[(7, 5)])
        self.ctx['loot']['creature'] = [(900, 0, 1, 0)]
        self.content = {'item': {1: {}, 2: {}}, 'quest': {10: {}}, 'spell': {5: {'sub': 'class'}}}

    def test_nothing_spawned_nothing_summoned(self):
        results = evaluate(self.content, self.ctx)
        self.assertEqual(failed(results[('item', 1)]), ['source'])
        self.assertEqual(failed(results[('item', 2)]), ['source'])
        self.assertEqual(failed(results[('quest', 10)]), ['ender', 'starter'])

    def test_summoned_counts_as_there(self):
        self.ctx['summoned_npc'] = {100, 200}
        results = evaluate(self.content, self.ctx)
        for key in (('item', 1), ('item', 2), ('quest', 10)):
            self.assertEqual(results[key][0], 'ok', key)

    def test_nobody_trains_at_a_summoned_creature(self):
        self.ctx['summoned_npc'] = {200}
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('spell', 5)]), ['learn'])
        self.ctx['spawned_npc'] = {200}
        self.assertEqual(evaluate(self.content, self.ctx)[('spell', 5)][0], 'ok')

    def test_a_chests_personal_loot(self):
        # the supply cart 694054: its only loot is personal (data30 144443), one of its go_loot rows
        ctx = world(go_loot=[(694054, 3, 144443)], spawned_go={694054})
        ctx['loot']['gameobject'] = [(144443, 0, 286153, 0)]
        self.assertEqual(evaluate({'item': {286153: {}}}, ctx)[('item', 286153)][0], 'ok')

    def test_a_summoned_chest(self):
        ctx = world(go_loot=[(500, 3, 901)], summoned_go={500})
        ctx['loot']['gameobject'] = [(901, 0, 3, 0)]
        self.assertEqual(evaluate({'item': {3: {}}}, ctx)[('item', 3)][0], 'ok')


class BlackMarket(unittest.TestCase):
    """The realm's Black Market Auction House (blackmarket_template) sells an item when its seller stands in the world."""

    def test_stocked_by_a_spawned_seller(self):
        ctx = world(blackmarket_items=[(300, 1)])
        self.assertEqual(failed(evaluate({'item': {1: {}}}, ctx)[('item', 1)]), ['source'])   # the seller is nowhere
        ctx = world(blackmarket_items=[(300, 1)], spawned_npc={300})
        self.assertEqual(evaluate({'item': {1: {}}}, ctx)[('item', 1)][0], 'ok')


class MadeByUse(unittest.TestCase):
    """An item made by using another one players hold: the Empty Leaden Collection Phial fills itself."""

    def setUp(self):
        # creature 100 drops the empty phial 1; using it casts spell 50, which triggers 51, which creates the full phial 2
        self.ctx = world(spawned_npc={100}, npc_loot=[(100, 900, 0, 0)], item_spells={1: {50}}, creates={2: {51}}, used_spells={50: {1}, 51: {1}})
        self.ctx['loot']['creature'] = [(900, 0, 1, 0)]

    def test_using_a_held_item_makes_it(self):
        self.assertEqual(evaluate({'item': {1: {}, 2: {}}}, self.ctx)[('item', 2)][0], 'ok')

    def test_an_item_nobody_holds_makes_nothing(self):
        self.ctx['spawned_npc'] = set()
        self.assertEqual(failed(evaluate({'item': {1: {}, 2: {}}}, self.ctx)[('item', 2)]), ['source'])

    def test_a_credit_an_item_gives(self):
        # quest 10 asks for creature 300, a credit marker no one spawns: using item 1 casts spell 50, which credits it
        self.ctx.update(quests={10: quest_row()}, objectives=[(10, 0, 300, 1)], q_start_npc=[(100, 10)], q_end_npc=[(100, 10)],
                        quest_turn_in_text={10}, credit_spells={300: {51}})
        self.assertEqual(evaluate({'quest': {10: {}}, 'item': {1: {}}}, self.ctx)[('quest', 10)][0], 'ok')
        self.ctx['credit_spells'] = {300: {77}}
        self.assertEqual(failed(evaluate({'quest': {10: {}}, 'item': {1: {}}}, self.ctx)[('quest', 10)]), ['objectives'])

    def test_the_server_reads_what_an_item_casts(self):
        # a learn effect (36) teaches its spell, it does not cast it: a recipe makes nothing by being used
        effects = [{'SpellID': 50, 'Effect': 64, 'EffectTriggerSpell': 51, 'EffectItemType': 0, 'EffectMiscValue1': 0},
                   {'SpellID': 51, 'Effect': 24, 'EffectTriggerSpell': 0, 'EffectItemType': 2, 'EffectMiscValue1': 0},
                   {'SpellID': 60, 'Effect': 36, 'EffectTriggerSpell': 61, 'EffectItemType': 0, 'EffectMiscValue1': 0},
                   {'SpellID': 61, 'Effect': 24, 'EffectTriggerSpell': 0, 'EffectItemType': 3, 'EffectMiscValue1': 0}]
        used = server.used_spells({1: {50}, 4: {60}}, effects)
        self.assertEqual(used, {50: {1}, 51: {1}, 60: {4}})


class Quests(unittest.TestCase):
    def setUp(self):
        self.ctx = world(spawned_npc={100}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)], quests={10: quest_row()}, quest_turn_in_text={10})

    def run_quest(self):
        return evaluate({'quest': {10: {}}}, self.ctx)[('quest', 10)]

    def test_a_complete_quest(self):
        self.assertEqual(self.run_quest()[0], 'ok')

    def starter_detail(self):
        return next(c for c in self.run_quest()[2] if c['code'] == 'starter')

    def test_a_quest_a_spell_offers(self):
        # Legacy of Valor 84124: no giver, offered by [DNT] Arena Victory 459623/459625, which nothing casts here
        self.ctx.update(q_start_npc=[], quest_start_spells={10: {459623, 459625}})
        starter = self.starter_detail()
        self.assertFalse(starter['ok'])
        self.assertTrue(starter['detail']['en'].startswith('Spell 459623, 459625 offers it (quest-start effect), but nothing casts it'))
        # a spawned creature casts it (its script, a spell click): given
        self.ctx['world_casts'] = {459625: {('npc', 100)}}
        starter = self.starter_detail()
        self.assertTrue(starter['ok'])
        self.assertEqual(starter['detail']['en'], 'Spell 459623, 459625 offers it, cast by a spawned creature')
        # the creature is not there: not given
        self.ctx['spawned_npc'] = set()
        self.assertFalse(self.starter_detail()['ok'])
        # the core's C++ names the spell: counted as cast
        self.ctx['core_spells'] = {'spells': {459623: 'scripts/Custom/x.cpp'}}
        self.assertEqual(self.starter_detail()['detail']['en'], 'Spell 459623, 459625 offers it, cast by the core’s C++')

    def test_a_giver_still_comes_first(self):
        self.ctx['quest_start_spells'] = {10: {459623}}
        self.assertEqual(self.starter_detail()['detail']['en'], 'NPC 100')

    def test_no_quest_text(self):
        self.ctx['quests'][10]['HasText'] = 0
        result = self.run_quest()
        self.assertEqual((result[0], failed(result)), ('partial', ['texts']))
        self.assertGreaterEqual(result[1], 85)   # a doable quest without its words stays near the top

    def test_a_text_the_official_game_lacks_is_no_gap(self):
        # The Black Box (708) has no turn-in text anywhere; An Apple Treat (91738) no giver's text
        for quest, change in ((708, lambda ctx: ctx.update(quest_turn_in_text=set())), (91738, lambda ctx: ctx['quests'][quest].update(HasText=0))):
            self.ctx = world(spawned_npc={100}, q_start_npc=[(100, quest)], q_end_npc=[(100, quest)], quests={quest: quest_row()},
                             quest_turn_in_text={quest})
            change(self.ctx)
            self.assertEqual(evaluate({'quest': {quest: {}}}, self.ctx)[('quest', quest)][0], 'ok', quest)

    def test_no_turn_in_text(self):
        self.ctx['quest_turn_in_text'] = set()
        self.assertEqual(failed(self.run_quest()), ['texts'])

    def test_an_auto_complete_quest_has_no_givers_text(self):
        self.ctx['quests'][10].update(QuestType=0, HasText=0)
        self.assertEqual(self.run_quest()[0], 'ok')

    def test_a_quest_nobody_gives_is_not_asked_for_words(self):
        self.ctx.update(q_start_npc=[], q_end_npc=[])
        self.ctx['quests'][10]['HasText'] = 0
        self.assertEqual(failed(self.run_quest()), ['ender', 'starter'])

    def test_a_kill_objective_through_its_credit_creature(self):
        self.ctx['objectives'] = [(10, 0, 300, 8)]           # kill 8 of credit creature 300, which nobody spawns
        self.assertEqual(failed(self.run_quest()), ['objectives'])
        self.ctx['kill_credit'] = {300: {301}}
        self.assertEqual(failed(self.run_quest()), ['objectives'])   # creature 301 is not there either
        self.ctx['spawned_npc'] = {100, 301}
        self.assertEqual(self.run_quest()[0], 'ok')

    def test_an_unmet_credit_names_what_gives_it(self):
        # Sickening Lights 95602: credit 272603 comes from killing the Twilight Ritual Circle 262006, which nobody spawns
        self.ctx['objectives'] = [(10, 0, 272603, 5)]
        self.ctx['kill_credit'] = {272603: {262006}}
        self.assertEqual(self.objective_detail(), 'credit 272603 from creature 262006 not spawned')
        # credited by an item's spell that nobody can get, or by a spell nothing casts
        self.ctx['kill_credit'] = {}
        self.ctx.update(credit_spells={272603: {77}}, used_spells={77: {5000}})
        self.assertEqual(self.objective_detail(), 'credit 272603 from item 5000 not obtainable')
        self.ctx['used_spells'] = {}
        self.assertEqual(self.objective_detail(), 'credit 272603: nothing casts spell 77')
        self.ctx['credit_spells'] = {}
        self.assertEqual(self.objective_detail(), 'creature 272603 not spawned')

    def objective_detail(self):
        result = self.run_quest()
        return next(c['detail']['en'] for c in result[2] if c['code'] == 'objectives')

    def test_the_package_handed_over_on_accept(self):
        self.ctx['quests'][10]['StartItem'] = 4
        results = evaluate({'quest': {10: {}}, 'item': {4: {}}}, self.ctx)
        self.assertEqual(results[('item', 4)][0], 'ok')
        self.ctx['spawned_npc'] = set()                       # nobody gives the quest: nobody hands the package over
        self.assertEqual(failed(evaluate({'quest': {10: {}}, 'item': {4: {}}}, self.ctx)[('item', 4)]), ['source'])

    def test_a_spell_the_quest_shows_as_its_reward(self):
        self.ctx['quest_display_spells'] = {10: {6}}
        self.assertEqual(evaluate({'quest': {10: {}}, 'spell': {6: {'sub': 'class'}}}, self.ctx)[('spell', 6)][0], 'ok')


class Bosses(unittest.TestCase):
    def boss(self, name, map_id):
        return {'name': name, 'name_en': name, 'map': map_id, 'facts': {}}

    def test_the_instance_scripts_creature(self):
        ctx = world(unspawned_npc=[{'id': 7273, 'name': "Gahz'rilla", 'script': False}])
        content = {'boss': {594: self.boss("Gahz'rilla", 209)}}
        self.assertEqual(failed(evaluate(content, ctx)[('boss', 594)]), ['boss_spawn'])
        ctx['encounter_npc'] = {594: [7273]}
        self.assertEqual(evaluate(content, ctx)[('boss', 594)][0], 'ok')

    def test_a_guess_counts_and_says_so(self):
        ctx = world(unspawned_npc=[{'id': 10439, 'name': 'Ramstein the Gorger', 'script': True}], instance_template={329: 'instance_stratholme'})
        result = evaluate({'boss': {483: self.boss('Ramstein the Gorger', 329)}}, ctx)[('boss', 483)]
        self.assertEqual((result[0], failed(result)), ('ok', ['boss_placed']))


class Zones(unittest.TestCase):
    def test_a_quest_heading_has_no_graveyard(self):
        content = {'zone': {12: {'map': 0}, 16941: {'map': 0}}}   # Elwynn Forest, and "Crafting": quests are sorted under it
        ctx = world(map_tiles={0: 900}, mapped_zones={12, 14})
        results = evaluate(content, ctx)
        self.assertEqual(failed(results[('zone', 12)]), ['graveyard'])
        self.assertEqual(failed(results[('zone', 16941)]), [])

    def test_without_map_data_every_zone_is_asked(self):
        results = evaluate({'zone': {16941: {'map': 0}}}, world(map_tiles={0: 900}))
        self.assertEqual(failed(results[('zone', 16941)]), ['graveyard'])

    def test_a_map_of_buildings_only_has_its_terrain_in_the_vmaps(self):
        # the Deeprun Tram (map 369) has no ground tiles: mapextractor writes no .map for it, the vmaps carry it all
        content = {'zone': {2257: {'map': 369}}}
        self.assertEqual(failed(evaluate(content, world(graveyards={2257}))[('zone', 2257)]), ['terrain'])
        self.assertEqual(failed(evaluate(content, world(vmaps={369}, graveyards={2257}))[('zone', 2257)]), [])

    def test_unused_quests_do_not_count_against_their_zone(self):
        # Azshara: fourteen "<UNUSED>" quests nobody gives kept the zone under 80 % with every real quest done
        quests = {10: quest_row(QuestSortID=16, LogTitle='Poisoned Water')}
        quests.update({20 + i: quest_row(QuestSortID=16, LogTitle='<UNUSED>') for i in range(3)})
        ctx = world(map_tiles={1: 900}, graveyards={16}, spawned_npc={100}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)],
                    quests=quests, quest_turn_in_text={10})
        content = {'zone': {16: {'map': 1}}, 'quest': {q: {} for q in quests}}
        result = evaluate(content, ctx)[('zone', 16)]
        self.assertEqual(failed(result), [])
        self.assertIn('1 / 1', next(c for c in result[2] if c['code'] == 'zone_quests')['detail']['en'])


    def test_a_quest_forever_does_not_give_does_not_count_against_its_zone(self):
        # Orgrimmar: the old Tier 3 quests ("An Earnest Proposition") only the Classic Mokvar gives, whom live replaced; with
        # them counted the city stayed under 80 % with every quest Forever gives done
        quests = {10: quest_row(QuestSortID=1637, LogTitle='Real')}
        quests.update({20 + i: quest_row(QuestSortID=1637, LogTitle='An Earnest Proposition') for i in range(3)})
        ctx = world(map_tiles={1: 900}, graveyards={1637}, spawned_npc={100, 230317},
                    q_start_npc=[(100, 10)] + [(16012, 20 + i) for i in range(3)], q_end_npc=[(100, 10)] + [(16012, 20 + i) for i in range(3)],
                    quests=quests, quest_turn_in_text=set(quests), npc_maps={1: [{'id': 230317, 'n': 1, 'name': 'Mokvar', 'scripted': False}]},
                    quest_npc_names={16012: 'Mokvar', 230317: 'Mokvar'}, live_npcs={230317: 'Mokvar'})
        content = {'zone': {1637: {'map': 1}}, 'quest': {q: {} for q in quests}}
        result = evaluate(content, ctx)[('zone', 1637)]
        self.assertEqual(failed(result), [])
        self.assertIn('1 / 1', next(c for c in result[2] if c['code'] == 'zone_quests')['detail']['en'])

class Vendors(unittest.TestCase):
    def test_a_borrowed_list_is_written_out(self):
        from ft import server
        rows = server.vendor_items([(1, 10), (1, -2), (2, 20), (2, -3), (3, 30), (3, -1), (4, -9)])
        self.assertEqual(sorted(rows), [(1, 10), (1, 20), (1, 30), (2, 10), (2, 20), (2, 30), (3, 10), (3, 20), (3, 30)])


class FlightPoints(unittest.TestCase):
    def test_a_flight_an_npcs_script_starts(self):
        content = {'taxi': {62: {'pos': [7800.0, -2500.0, 490.0], 'map': 1}}}
        ctx = world(flight_spawns=[(1, 7450.0, -2490.0)])      # the ordinary flight master, 350 yards off
        self.assertEqual(failed(evaluate(content, ctx)[('taxi', 62)]), ['flightmaster'])
        ctx['script_taxi_nodes'] = {62}
        self.assertEqual(evaluate(content, ctx)[('taxi', 62)][0], 'ok')
        # whatever starts the flight on this server: a point the client never marks as known needs no flight master
        ctx['script_taxi_nodes'] = set()
        content['taxi'][62]['learned'] = False
        self.assertEqual(evaluate(content, ctx)[('taxi', 62)][0], 'ok')
        content['taxi'][62]['learned'] = True
        self.assertEqual(failed(evaluate(content, ctx)[('taxi', 62)]), ['flightmaster'])



class QuestSides(unittest.TestCase):
    """Whose quest it is: the side players on live got it on, against the races the server offers it to."""

    def result(self, races, told):
        content = {'quest': {7: {'name': 'Cloth for the Front'}}}
        ctx = world(quests={7: quest_row(AllowableRaces=str(races))}, report_sides={7: told} if told else {})
        ctx['known']['quest'] = {7}
        return failed(evaluate(content, ctx)[('quest', 7)])

    def test_a_quest_kept_to_the_wrong_side(self):
        self.assertIn('side', self.result(0x55155555B1354C4D, {'Horde'}))       # the server keeps it to the Alliance
        self.assertIn('side', self.result(77, {'Horde'}))
        self.assertNotIn('side', self.result(0xAA2AAAAA4E0AB3B2, {'Horde'}))    # the Horde's races: as on live
        self.assertNotIn('side', self.result(0x200000000, {'Horde'}))           # the Horde's new race alone

    def test_everyone_on_the_server_is_no_finding(self):
        # the giver's faction keeps the other side out: the live server itself says "every race" for such quests
        self.assertNotIn('side', self.result(0, {'Horde'}))
        self.assertNotIn('side', self.result(18446744073709551615, {'Alliance'}))
        self.assertNotIn('side', self.result(0, {'Alliance', 'Horde'}))
        self.assertNotIn('side', self.result(77, {'Alliance', 'Horde'}))        # a side players got it on, if not the only one

    def test_without_a_report_nothing_is_asked(self):
        self.assertNotIn('side', self.result(77, None))


class HowASpellIsLearned(unittest.TestCase):
    """A spell of a class or profession is asked for a way to learn it, unless the game data says nobody learns it."""

    def spell(self, spell_id, **over):
        ctx = world(**over)
        results = evaluate({'spell': {spell_id: {'sub': 'class'}}}, ctx)
        learn = next(c for c in results[('spell', spell_id)][2] if c['code'] == 'learn')
        return results[('spell', spell_id)][0], learn['detail']['en'], ctx['granted_spells']

    def test_a_talent_of_a_trait_tree_is_learned_there(self):
        status, detail, granted = self.spell(400574, tree_spells={400574})
        self.assertEqual((status, detail, granted), ('ok', 'talent or perk tree', set()))

    def test_learning_one_spell_teaches_the_next(self):
        # Alchemy's old rank comes from a trainer; the game teaches Forever's new rank spell with it, and that one a third
        trained = dict(trainers=[(200, 7)], trainer_spells=[(7, 2259)], spawned_npc={200})
        status, detail, _ = self.spell(1240954, spell_teaches={(2259, 1240943), (1240943, 1240954)}, **trained)
        self.assertEqual((status, detail), ('ok', 'learned through another spell'))
        self.assertEqual(self.spell(1240954, spell_teaches={(1240943, 1240954)}, **trained)[0], 'partial')   # nothing teaches the first

    def test_what_nobody_learns_is_not_asked_for_a_trainer(self):
        status, detail, granted = self.spell(5857, never_learned={5857})
        self.assertEqual(status, 'ok')
        self.assertIn('never learned', detail)
        self.assertEqual(granted, {5857})
        status, detail, granted = self.spell(16177, cast_by={16177: 16176})
        self.assertEqual((status, detail, granted), ('ok', 'Not learned: spell 16176 casts it.', {16177}))

    def test_a_spell_a_trainer_or_an_item_holds_is_still_asked_for(self):
        # never learned by the table, yet a trainer lists it: the trainer is what is missing
        status, detail, granted = self.spell(5857, never_learned={5857}, trainers=[(200, 7)], trainer_spells=[(7, 5857)])
        self.assertEqual((status, detail, granted), ('partial', 'Trainer 200 has it but is not spawned.', set()))
        status, detail, granted = self.spell(17632, cast_by={17632: 1}, teaches={17632: {13517}})
        self.assertEqual((status, detail, granted), ('partial', 'Taught by item 13517, which players cannot get.', set()))

    def test_a_reward_of_a_quest_nobody_can_do_yet_names_the_quest(self):
        # quest 2771 casts 11203 on its reward, which teaches Ornate Mithril Helm; nobody gives the quest yet
        waiting = dict(quests={2771: quest_row(RewardSpell=11203)}, spell_teaches={(11203, 9980)})
        status, detail, granted = self.spell(9980, never_learned={9980}, **waiting)
        self.assertEqual((status, detail, granted), ('partial', 'Reward of quest 2771, which players cannot do yet.', set()))
        # the quest's display spell counts the same way, and a pattern nobody can get is not what it waits for
        shown = dict(quests={7: quest_row(), 8: quest_row()}, quest_display_spells={7: {9980}, 8: {9980}}, teaches={9980: {7987}})
        self.assertEqual(self.spell(9980, **shown)[1], 'Reward of quest 7, 8, which players cannot do yet.')
        # once somebody gives and takes the quest the spell is simply learnable
        done = dict(waiting, q_start_npc=[(100, 2771)], q_end_npc=[(100, 2771)], spawned_npc={100}, quest_turn_in_text={2771})
        self.assertEqual(evaluate({'spell': {9980: {'sub': 'class'}}, 'quest': {2771: {}}}, world(**done))[('spell', 9980)][0], 'ok')

    def test_a_quest_outside_the_official_list_still_gives_its_reward(self):
        # quest 8878 (Festive Recipes) is on the server but not in the client's QuestV2: its pattern teaches spell 26403
        ctx = world(spawned_npc={100}, q_start_npc=[(100, 8878)], q_end_npc=[(100, 8878)], quests={8878: quest_row(RewardChoiceItemID1=21722)},
                    quest_turn_in_text={8878}, teaches={26403: {21722}})
        results = evaluate({'item': {21722: {}}, 'spell': {26403: {'sub': 'profession'}}}, ctx)
        self.assertEqual(results[('item', 21722)][0], 'ok')
        self.assertEqual(results[('spell', 26403)][0], 'ok')
        # nobody gives it: still nothing
        ctx = world(q_end_npc=[(100, 8878)], spawned_npc={100}, quests={8878: quest_row(RewardChoiceItemID1=21722)}, teaches={26403: {21722}})
        self.assertEqual(evaluate({'item': {21722: {}}}, ctx)[('item', 21722)][0], 'partial')

    def test_a_trainer_list_no_creature_uses(self):
        self.assertEqual(self.spell(10841, trainer_spells=[(7, 10841)])[1], 'A trainer list has it, but no creature uses that list.')

    def test_nothing_known_is_said_as_before(self):
        self.assertEqual(self.spell(5)[:2], ('partial', 'No trainer, automatic learning or item.'))

    def test_a_recipe_taught_by_another_spell(self):
        ctx = world(trainers=[(200, 7)], trainer_spells=[(7, 2259)], spawned_npc={200}, spell_teaches={(2259, 818)})
        results = evaluate({'recipe': {818: {}}, 'spell': {818: {'sub': 'profession'}}}, ctx)
        self.assertEqual(results[('recipe', 818)][0], 'ok')
        self.assertEqual(results[('spell', 818)][0], 'ok')

    def test_a_recipe_says_what_it_waits_for(self):
        detail = lambda **over: next(c for c in evaluate({'recipe': {30021: {}}, 'spell': {30021: {'sub': 'profession'}}}, world(**over))[('recipe', 30021)][2]
                                     if c['code'] == 'learn')['detail']['en']
        self.assertEqual(detail(), 'No trainer and no recipe.')
        self.assertEqual(detail(teaches={30021: {23689}}), 'Taught by item 23689, which players cannot get.')
        self.assertEqual(detail(teaches={30021: {23689}}, quests={6: quest_row(RewardSpell=30021)}), 'Reward of quest 6, which players cannot do yet.')
        self.assertEqual(detail(trainers=[(12939, 7)], trainer_spells=[(7, 30021)]), 'Trainer 12939 has it but is not spawned.')


class AchievementRewards(unittest.TestCase):
    """A title or a mailed item needs its achievement_reward row; a Legacy Point is paid by the trait system."""

    def reward(self, entity, **over):
        results = evaluate({'achievement': {61499: entity}}, world(**over))
        return results[('achievement', 61499)][0], failed(results[('achievement', 61499)])

    def test_a_legacy_point_needs_no_row(self):
        point = {'reward': 'Earn 1 Legacy Point.', 'reward_item': 0}
        self.assertEqual(self.reward(point, achievement_currency={61499}), ('ok', []))
        self.assertEqual(self.reward(point), ('partial', ['reward']))                         # the server has no such source
        self.assertEqual(self.reward(point, achievement_rewards={61499}), ('ok', []))

    def test_an_item_still_needs_its_row(self):
        tabard = {'reward': '', 'reward_item': 191481}
        self.assertEqual(self.reward(tabard, achievement_currency={61499}), ('partial', ['reward']))
        self.assertEqual(self.reward(tabard, achievement_rewards={61499}), ('ok', []))

    def test_no_reward_no_check(self):
        self.assertEqual(self.reward({'reward': '', 'reward_item': 0}), ('ok', []))


class HowAMountIsLearned(unittest.TestCase):
    """A mount's spell is learned the same ways as any spell: the paladin's and the warlock's mounts are quest rewards."""

    def mount(self, **over):
        ctx = world(**over)
        results = evaluate({'mount': {84: {'spell': 23214}}, 'spell': {23214: {'sub': 'mount'}}, 'quest': {7647: {}}}, ctx)
        check = next(c for c in results[('mount', 84)][2] if c['code'] == 'obtainable')
        return results[('mount', 84)][0], check['detail']['en']

    def test_a_quest_reward(self):
        given = dict(quests={7647: quest_row(RewardSpell=23214)}, q_start_npc=[(100, 7647)], q_end_npc=[(100, 7647)], spawned_npc={100},
                     quest_turn_in_text={7647})
        self.assertEqual(self.mount(**given), ('ok', 'quest reward'))

    def test_a_quest_nobody_can_do_yet_is_named(self):
        self.assertEqual(self.mount(quests={7647: quest_row(RewardSpell=23214)}), ('missing', 'Reward of quest 7647, which players cannot do yet.'))

    def test_learned_through_another_spell_or_a_trainer(self):
        self.assertEqual(self.mount(auto_learn={1}, spell_teaches={(1, 23214)}), ('ok', 'learned through another spell'))
        self.assertEqual(self.mount(trainers=[(200, 7)], trainer_spells=[(7, 23214)], spawned_npc={200}), ('ok', 'trainer'))

    def test_nothing_teaches_it(self):
        self.assertEqual(self.mount(), ('missing', 'No item and no trainer.'))
        self.assertEqual(self.mount(teaches={23214: {5874}}), ('missing', 'Item exists but cannot be obtained: 5874'))


class NotContent(unittest.TestCase):
    """Spells listed as internal instead of incomplete: Season of Discovery additions only Season items teach, and
    original spells nothing teaches that the original game taught nowhere either (Classic database pack)."""

    SEASON = {('spell', 435481), ('spell', 400104), ('item', 215129)}

    def season(self, kind, entity_id):
        return (kind, entity_id) in self.SEASON

    def result(self, spell, **over):
        ctx = world(season=self.season, **over)
        results = evaluate({'spell': {spell: {'sub': 'profession'}}}, ctx)
        return results[('spell', spell)], ctx

    def test_a_season_spell_only_season_items_teach(self):
        (status, _, checks), ctx = self.result(435481, teaches={435481: {215129}})
        self.assertEqual(status, 'ok')
        self.assertIn('Season of Discovery', next(c for c in checks if c['code'] == 'learn')['detail']['en'])
        self.assertIn(435481, ctx['granted_spells'])
        (status, _, _), ctx = self.result(400104)   # a rune nothing teaches
        self.assertIn(400104, ctx['granted_spells'])

    def test_a_season_spell_forever_reissued(self):
        # Forever's own item for the same pattern (273590): the recipe is Forever's to place, it stays on the list
        (status, _, _), ctx = self.result(435481, teaches={435481: {215129, 273590}})
        self.assertEqual(status, 'partial')
        self.assertNotIn(435481, ctx['granted_spells'])

    def test_an_original_spell_nothing_ever_taught(self):
        (status, _, checks), ctx = self.result(26363, classic_taught={10843})   # a Lightning Shield proc
        self.assertEqual(status, 'ok')
        self.assertIn('original game taught it nowhere', next(c for c in checks if c['code'] == 'learn')['detail']['en'])
        self.assertIn(26363, ctx['granted_spells'])

    def test_what_the_original_game_taught_stays(self):
        # Classic's quest casts 11522, which teaches Restorative Potion: a real gap of the realm
        (status, _, _), ctx = self.result(11452, classic_taught={11522}, spell_teaches={(11522, 11452)})
        self.assertEqual(status, 'partial')
        self.assertNotIn(11452, ctx['granted_spells'])

    def test_a_quest_forever_rewards_otherwise(self):
        # Badlands Reagent Run II (2501) cast 11522, which taught Restorative Potion; on Forever it casts 366567, which
        # teaches Greater Mender's Potion: the realm lacks nothing
        changed = dict(classic_taught={11522}, classic_quest_taught={11522: {2501}}, spell_teaches={(11522, 11452), (366567, 1251744)},
                       quests={2501: quest_row(RewardSpell=366567)})
        (status, _, checks), ctx = self.result(11452, **changed)
        self.assertEqual(status, 'ok')
        self.assertIn('quest 2501 taught it in the original game', next(c for c in checks if c['code'] == 'learn')['detail']['en'])
        self.assertIn(11452, ctx['granted_spells'])
        # the quest still teaches it, or the realm lacks the quest: a real gap
        for quests in ({2501: quest_row(RewardSpell=11522)}, {}):
            (status, _, _), ctx = self.result(11452, **dict(changed, quests=quests))
            self.assertEqual(status, 'partial', quests)
            self.assertNotIn(11452, ctx['granted_spells'])

    def test_a_spell_forever_made_is_not_excused(self):
        # Lacerate (24118): below the 'new' cut-off, but neither the original game nor the Classic Era client had it;
        # that the Classic database never taught it says nothing, so the missing trainer shows
        made = lambda kind, entity_id: (kind, entity_id) == ('spell', 24118)
        (status, _, _), ctx = self.result(24118, classic_taught={1}, forever_made=made)
        self.assertEqual(status, 'partial')
        self.assertNotIn(24118, ctx['granted_spells'])
        (status, _, _), ctx = self.result(24118, classic_taught={1}, forever_made=made, cast_by={24118: 7})   # a seal's judgement
        self.assertEqual(status, 'ok')
        self.assertEqual(self.result(26363, classic_taught={1}, forever_made=made)[0][0], 'ok')   # the original game's own

    def test_without_a_pack_or_with_a_teacher_it_stays(self):
        for over in ({}, {'classic_taught': {1}, 'teaches': {26363: {13323}}}, {'classic_taught': {1}, 'trainer_spells': [(5, 26363)]}):
            (status, _, _), ctx = self.result(26363, **over)
            self.assertEqual(status, 'partial', over)
            self.assertNotIn(26363, ctx['granted_spells'])

    def test_a_spell_only_never_given_items_teach(self):
        # the Gray Wolf: its two items the original game gave out nowhere
        (status, _, checks), ctx = self.result(459, classic_taught={1}, classic_never_given={842, 1134}, teaches={459: {842, 1134}})
        self.assertEqual(status, 'ok')
        self.assertIn('never gave out', next(c for c in checks if c['code'] == 'learn')['detail']['en'])
        self.assertIn(459, ctx['granted_spells'])
        # one item it did give out: the spell stays (the Panda: a quest gave its item)
        (status, _, _), ctx = self.result(17707, classic_taught={1}, classic_never_given={842}, teaches={17707: {842, 13583}})
        self.assertEqual(status, 'partial')
        # taught by the original game anyway
        (status, _, _), ctx = self.result(459, classic_taught={459}, classic_never_given={842}, teaches={459: {842}})
        self.assertEqual(status, 'partial')

    def test_a_skill_line_not_for_players(self):
        from ft import content
        self.assertTrue(content.DO_NOT_TRANSLATE.search('Test Profession [DNT]'))
        for name in ('Tailoring', 'Engineering', 'Dance'):
            self.assertFalse(content.DO_NOT_TRANSLATE.search(name), name)

    def test_forever_spells_stay(self):
        (status, _, _), ctx = self.result(1325756, classic_taught={1})   # Death Mark: new in Forever, not in the Classic Era client
        self.assertEqual(status, 'partial')


class Conversations(unittest.TestCase):
    """A recipe taught in a conversation: an NPC's or an object's menu choice casts a spell that teaches it."""

    # Knot Thimblejack (14338) opens menu 5667; its option 2 runs SmartAI that casts 22814, which teaches 22813.
    # The Tablet of Madness (object 180368) opens menu 6443, option 0 casts 24267 (teaches 24266).
    MENUS = [(14338, 5667)]
    OBJECTS = [(180368, 6443)]
    OPTIONS = [(5667, 0, 0), (5667, 2, 0), (6443, 0, 0), (7213, 0, 24401), (24401, 2, 0), (24401, 0, 7213)]

    def casts(self, smart, scripts=(), menus=None, options=None):
        return server.conversation_casts(self.MENUS if menus is None else menus, self.OBJECTS, self.OPTIONS if options is None else options, smart, scripts)

    def test_a_menu_choice_that_casts(self):
        smart = [('npc', 14338, 5667, 2, 22814), ('go', 180368, 6443, 0, 24267)]
        self.assertEqual(self.casts(smart), [('go', 180368, 24267), ('npc', 14338, 22814)])

    def test_a_choice_the_conversation_does_not_reach(self):
        self.assertEqual(self.casts([('npc', 14338, 9999, 2, 22814)]), [])            # another menu
        self.assertEqual(self.casts([('npc', 14338, 5667, 7, 22814)]), [])            # no such option
        self.assertEqual(self.casts([('npc', 1, 5667, 2, 22814)]), [])                # a creature that does not open it
        self.assertEqual(self.casts([('npc', 14338, 5667, 2, 0)]), [])                # no spell

    def test_a_menu_reached_through_another(self):
        # Omarion opens 7213, whose first option leads to 24401 (and back): the recipes sit in the second menu
        smart = [('npc', 16365, 24401, 2, 28261)]
        self.assertEqual(self.casts(smart, menus=[(16365, 7213)]), [('npc', 16365, 28261)])

    def test_the_cores_own_script(self):
        scripts = [('npc', 9037, 'boss_gloomrel'), ('npc', 14742, 'npc_engineering_tele_trinket'), ('npc', 14338, 'classic_npc_knot_thimblejack'),
                   ('npc', 1, 'npc_some_other_script')]
        self.assertEqual(self.casts([], scripts=scripts), [('npc', 9037, 14894), ('npc', 14338, 22814), ('npc', 14338, 22816),
                                                           ('npc', 14742, 23490), ('npc', 14742, 23491)])   # core fork PR 60 fixed them

    def test_the_cores_classic_scripts(self):
        # Omarion's script teaches his 13 recipes; the Field Repair Bot schematic, an object, teaches on use
        found = self.casts([], scripts=[('npc', 16365, 'classic_mob_craftsman_omarion'), ('go', 179552, 'classic_go_field_repair_bot_74A')])
        self.assertIn(('go', 179552, 22864), found)
        self.assertIn(('npc', 16365, 28261), found)   # Omarion: Classic's learn spells (core fork PR 60)
        self.assertEqual(len(found), 15)
        # a script name on the wrong kind of template teaches nothing
        self.assertEqual(self.casts([], scripts=[('npc', 179552, 'classic_go_field_repair_bot_74A')]), [])

    def test_a_choice_that_calls_a_timed_list(self):
        # Gloom'rel on Everlake: choice 1945/1 calls list 950000386, which casts 14894 (Learn Smelt Dark Iron)
        lists = {950000386: {14894}, 5: {1}, 6: {2}, 7: {3}}
        choices = [(0, 9037, 1945, 1, server.SMART_CALL_LIST, [950000386, 0, 0, 0, 0, 0]),
                   (0, 9037, 1945, 1, 72, [0] * 6),                                      # closing the window casts nothing
                   (0, 1, 10, 0, server.SMART_CALL_RANDOM_LIST, [5, 6, 0, 0, 0, 0]),    # either list may run
                   (0, 2, 20, 0, server.SMART_CALL_RANGE_LIST, [6, 7, 0, 0, 0, 0]),
                   (1, 180368, 6443, 0, 134, [24267, 0, 0, 0, 0, 0]),                    # a direct cast still counts
                   (0, 3, 30, 0, server.SMART_CALL_LIST, [999, 0, 0, 0, 0, 0])]          # a list that casts nothing
        self.assertEqual(server.choice_spells(choices, lists), [(0, 1, 10, 0, 1), (0, 1, 10, 0, 2), (0, 2, 20, 0, 2), (0, 2, 20, 0, 3),
                                                                (0, 9037, 1945, 1, 14894), (1, 180368, 6443, 0, 24267)])

    def test_a_choice_that_links_on(self):
        # Gloom'rel on Everlake: row 5 (choice 1945/1) closes the window and links to row 6 (LINK), which calls the list
        def row(i, link, event, menu, option, action, p1=0):
            return {'source_type': 0, 'entryorguid': 9037, 'id': i, 'link': link, 'event_type': event, 'event_param1': menu,
                    'event_param2': option, 'action_type': action, 'action_param1': p1}
        rows = [row(5, 6, 62, 1945, 1, 72), row(6, 0, 61, 0, 0, 80, 950000386),
                row(7, 8, 62, 1945, 0, 72), row(8, 7, 61, 0, 0, 11, 1),          # a loop ends where it began
                row(9, 2, 62, 1945, 2, 72)]                                      # a link to a row that is no LINK
        choices = server.linked_choices(rows + [row(2, 0, 0, 0, 0, 11, 99)])
        self.assertIn((0, 9037, 1945, 1, 80, [950000386, 0, 0, 0, 0, 0]), choices)
        self.assertIn((0, 9037, 1945, 0, 11, [1, 0, 0, 0, 0, 0]), choices)
        self.assertNotIn(99, [c[5][0] for c in choices])
        self.assertEqual(server.choice_spells(choices, {950000386: {14894}}), [(0, 9037, 1945, 0, 1), (0, 9037, 1945, 1, 14894)])

    def test_a_spell_cast_is_not_learned(self):
        # a conversation that casts a buff does not teach the buff; one that casts a learn spell teaches its target
        ctx = world(conversation_casts=[('npc', 9037, 14894), ('npc', 9037, 777)], spell_teaches={(14894, 14891)}, spawned_npc={9037})
        results = evaluate({'spell': {14891: {'sub': 'profession'}, 777: {'sub': 'profession'}, 14894: {'sub': 'profession'}}}, ctx)
        self.assertEqual(results[('spell', 14891)][0], 'ok')
        self.assertEqual(results[('spell', 777)][0], 'partial')
        self.assertEqual(results[('spell', 14894)][0], 'partial')

    def test_the_rules_count_it_where_someone_stands(self):
        ctx = world(conversation_casts=[('npc', 14338, 22814), ('go', 180368, 24267)], spell_teaches={(22814, 22813), (24267, 24266)},
                    spawned_npc={14338})
        results = evaluate({'spell': {22813: {'sub': 'profession'}, 24266: {'sub': 'profession'}}, 'recipe': {22813: {}}}, ctx)
        self.assertEqual(results[('spell', 22813)][0], 'ok')
        learn = next(c for c in results[('spell', 22813)][2] if c['code'] == 'learn')
        self.assertEqual(learn['detail']['en'], 'taught in a conversation (NPC 14338)')
        self.assertEqual(results[('recipe', 22813)][0], 'ok')
        self.assertEqual(results[('spell', 24266)][0], 'partial')              # the tablet is not spawned
        ctx = world(conversation_casts=[('go', 180368, 24267)], spell_teaches={(24267, 24266)}, spawned_go={180368})
        self.assertEqual(evaluate({'spell': {24266: {'sub': 'profession'}}}, ctx)[('spell', 24266)][0], 'ok')

    def test_what_a_crafted_recipe_makes_becomes_obtainable(self):
        ctx = world(conversation_casts=[('npc', 14338, 22814)], spell_teaches={(22814, 22813)}, spawned_npc={14338}, creates={18258: {22813}})
        self.assertEqual(evaluate({'item': {18258: {}}}, ctx)[('item', 18258)][0], 'ok')

    def test_an_item_a_conversation_makes_is_obtainable(self):
        # the Spirit of Azuregos's last choice makes the player cast 25600, which creates the Magical Ledger 20949
        ctx = world(conversation_casts=[('npc', 15481, 25600)], spawned_npc={15481}, creates={20949: {25600}})
        result = evaluate({'item': {20949: {}}}, ctx)[('item', 20949)]
        self.assertEqual(result[0], 'ok')
        ctx = world(conversation_casts=[('npc', 15481, 25600)], creates={20949: {25600}})   # the spirit is not spawned
        self.assertNotEqual(evaluate({'item': {20949: {}}}, ctx)[('item', 20949)][0], 'ok')


class TreeSpells(unittest.TestCase):
    """The spells of the talent and perk trees (the Trait tables): a definition counts once it sits on a node."""

    def test_only_a_definition_placed_on_a_node(self):
        tables = {'TraitDefinition': [{'ID': 1, 'SpellID': 400574}, {'ID': 2, 'SpellID': 1326079}, {'ID': 3, 'SpellID': 0}, {'ID': 4, 'SpellID': 99}],
                  'TraitNodeEntry': [{'ID': 10, 'TraitDefinitionID': 1}, {'ID': 11, 'TraitDefinitionID': 2}, {'ID': 12, 'TraitDefinitionID': 3},
                                     {'ID': 13, 'TraitDefinitionID': 4}],
                  'TraitNode': [{'ID': 100}, {'ID': 101}],
                  'TraitNodeXTraitNodeEntry': [{'TraitNodeID': 100, 'TraitNodeEntryID': 10}, {'TraitNodeID': 101, 'TraitNodeEntryID': 11},
                                               {'TraitNodeID': 101, 'TraitNodeEntryID': 12}, {'TraitNodeID': 555, 'TraitNodeEntryID': 13},
                                               {'TraitNodeID': 100, 'TraitNodeEntryID': 77}]}
        self.assertEqual(server.tree_spells(lambda name: tables.get(name, [])), {400574, 1326079})

    def test_a_server_without_the_tables(self):
        self.assertEqual(server.tree_spells(lambda name: []), set())


class ZoneCreatures(unittest.TestCase):
    """A zone's creatures: counted inside the rectangle the zone's map draws (UiMapAssignment)."""

    ROWS = [{'AreaID': 12, 'MapID': 0, 'Region1X': -10254.0, 'Region1Y': -1935.0, 'Region2X': -7939.0, 'Region2Y': 1535.0},
            {'AreaID': 0, 'MapID': 0, 'Region1X': -20000.0, 'Region1Y': -20000.0, 'Region2X': 20000.0, 'Region2Y': 20000.0},   # a continent's map
            {'AreaID': 14, 'MapID': 1, 'Region1X': 500.0, 'Region1Y': 100.0, 'Region2X': -500.0, 'Region2Y': -100.0}]       # written the other way round

    def test_the_rectangles_come_from_the_games_own_table(self):
        found = server.zone_rectangles(self.ROWS)
        self.assertEqual([a for ui in found for a in ui['assignments']],
                         [{'area': 12, 'map': 0, 'region': (-10254.0, -1935.0, -7939.0, 1535.0)},
                          {'area': 14, 'map': 1, 'region': (-500.0, -100.0, 500.0, 100.0)}])

    def test_a_zone_with_hardly_any_creature_is_said(self):
        content = {'zone': {12: {'map': 0}, 14: {'map': 1}}}
        inside = [(0, -9000.0 + i, 0.0, 100 + i) for i in range(25)]
        ctx = world(ui_maps=server.zone_rectangles(self.ROWS), spawns=inside + [(1, 0.0, 0.0, 7), (0, 0.0, 0.0, 8)], map_tiles={0: 1, 1: 1},
                    graveyards={12, 14})
        results = evaluate(content, ctx)
        self.assertNotIn('spawns', failed(results[('zone', 12)]))    # 25 creatures inside
        self.assertIn('spawns', failed(results[('zone', 14)]))       # one creature in the whole zone
        # without the rectangles the check is not made at all (it used to never run)
        self.assertNotIn('spawns', failed(evaluate(content, world(spawns=inside, map_tiles={0: 1, 1: 1}, graveyards={12, 14}))[('zone', 14)]))


class ScriptCreates(unittest.TestCase):
    """An item the core's own script hands over when a spell players learn is cast (the healthstones)."""

    def setUp(self):
        # trainer 14 teaches Create Healthstone (Minor) 6201; the script makes Minor Healthstone 5512
        self.ctx = world(trainers=[(300, 14)], trainer_spells=[(14, 6201)])
        self.content = {'item': {5512: {}, 19004: {}}}

    def test_made_once_the_spell_is_trained(self):
        self.ctx['spawned_npc'] = {300}
        results = evaluate(self.content, self.ctx)
        self.assertEqual(results[('item', 5512)][0], 'ok')
        self.assertEqual(results[('item', 19004)][0], 'ok')   # the Improved Healthstone copy

    def test_not_while_nobody_trains_it(self):
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('item', 5512)]), ['source'])


class QuestTaughtRecipe(unittest.TestCase):
    """A recipe a quest's reward spell teaches: Research Access (97286) rewards 1302696, which teaches Study 1302508,
    which makes the Bundle of Scrolls 277651, which holds the scrolls."""

    def setUp(self):
        self.ctx = world(spawned_npc={100}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)], quests={10: quest_row(RewardSpell=60)},
                         quest_turn_in_text={10}, spell_teaches={(60, 61)}, creates={7: {61}})
        self.ctx['loot']['item'] = [(7, 0, 8, 0)]
        self.content = {'quest': {10: {}}, 'item': {7: {}, 8: {}}}

    def test_its_item_and_what_that_holds_are_obtainable(self):
        results = evaluate(self.content, self.ctx)
        self.assertEqual((results[('item', 7)][0], results[('item', 8)][0]), ('ok', 'ok'))

    def test_not_while_nobody_gives_the_quest(self):
        self.ctx['spawned_npc'] = set()
        self.assertEqual(failed(evaluate(self.content, self.ctx)[('item', 7)]), ['source'])


class SmartCredits(unittest.TestCase):
    """A credit marker a SmartAI script gives: the Tarantula Eggs of Alther's Mill (673101 on use: CALL_KILLEDMONSTER
    271912), Ott casting the credit spell 1282264 at whoever talks to him."""

    def rows(self, *extra):
        base = [{'entryorguid': 673101, 'source_type': 1, 'action_type': 33, 'action_param1': 271912, 'target_type': 7},
                {'entryorguid': 3539, 'source_type': 0, 'action_type': 11, 'action_param1': 1282264, 'target_type': 7}]
        return base + list(extra)

    def test_the_reader(self):
        got = server.smart_credits(self.rows(), {259966: {1282264}})
        self.assertEqual(got, {271912: {('go', 673101)}, 259966: {('npc', 3539)}})

    def test_a_cast_on_itself_credits_nobody(self):
        rows = [{'entryorguid': 255833, 'source_type': 0, 'action_type': 11, 'action_param1': 1269471, 'target_type': 1}]
        self.assertEqual(server.smart_credits(rows, {256634: {1269471}}), {})

    def test_a_follow_that_ends_in_a_credit_counts(self):
        # Ewe Wandered Off 96674: the Escaped Sheep 265962 follows its clicker; at Mirt 248419 the core gives 265988
        rows = [{'entryorguid': 265962, 'source_type': 0, 'action_type': 29, 'action_param1': 0, 'action_param2': 0,
                 'action_param3': 248419, 'action_param4': 265988, 'action_param5': 0, 'target_type': 7}]
        self.assertEqual(server.smart_credits(rows, {}), {265988: {('npc', 265962)}})
        rows[0]['action_param5'] = 1   # an event credit, not a kill
        self.assertEqual(server.smart_credits(rows, {}), {})
        rows[0].update(action_param5=0, action_param3=0)   # a plain follow
        self.assertEqual(server.smart_credits(rows, {}), {})

    def test_a_timed_list_counts_for_its_callers(self):
        rows = [{'entryorguid': 1229600, 'source_type': 9, 'action_type': 33, 'action_param1': 12297, 'target_type': 7},
                {'entryorguid': 12296, 'source_type': 0, 'action_type': 80, 'action_param1': 1229600, 'target_type': 1}]
        self.assertEqual(server.smart_credits(rows, {}), {12297: {('npc', 12296)}})

    def test_the_quest_counts_while_the_scripted_thing_is_there(self):
        ctx = world(spawned_npc={100}, spawned_go={673101}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)], quests={10: quest_row()},
                    quest_turn_in_text={10}, objectives=[(10, 0, 271912, 6)], smart_credits={271912: {('go', 673101)}})
        self.assertEqual(evaluate({'quest': {10: {}}}, ctx)[('quest', 10)][0], 'ok')
        ctx['spawned_go'] = set()
        self.assertEqual(failed(evaluate({'quest': {10: {}}}, ctx)[('quest', 10)]), ['objectives'])


    def test_a_credit_spell_a_spawned_creature_has_its_clicker_cast_counts(self):
        # Saving Our Own 93058: clicking a Gelkis Captive 253431 casts Break Chain 1263364, the credit 254825
        ctx = world(spawned_npc={100, 253431}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)], quests={10: quest_row()},
                    quest_turn_in_text={10}, objectives=[(10, 0, 254825, 5)], credit_spells={254825: {1263364}},
                    world_casts={1263364: {('npc', 253431)}})
        self.assertEqual(evaluate({'quest': {10: {}}}, ctx)[('quest', 10)][0], 'ok')
        ctx['spawned_npc'] = {100}
        self.assertEqual(failed(evaluate({'quest': {10: {}}}, ctx)[('quest', 10)]), ['objectives'])

    def test_the_spell_click_reader(self):
        rows = [{'npc_entry': 253431, 'spell_id': 1263364}]
        self.assertEqual(server.spellclick_casts(lambda sql: rows, lambda t: True), [(253431, 1263364)])
        self.assertEqual(server.spellclick_casts(lambda sql: rows, lambda t: False), [])

class ObjectCredits(unittest.TestCase):
    """A credit marker a world object's own spell gives when used: the Old Dinghy (652657, a goober casting 1294248,
    credit 273097), a Deadwood Cauldron casting Destroy (1283593) which triggers 1283583 (credit 260373)."""

    effects = [{'SpellID': 1283593, 'EffectTriggerSpell': 1283583}, {'SpellID': 1283583, 'EffectTriggerSpell': 0},
               {'SpellID': 1294248, 'EffectTriggerSpell': 0}, {'SpellID': 9, 'EffectTriggerSpell': 9}]

    def test_the_reader(self):
        got = server.object_credits([(652657, 1294248), (630780, 1283593), (1, 9)], {273097: {1294248}, 260373: {1283583}}, self.effects)
        self.assertEqual(got, {273097: {652657}, 260373: {630780}})

    def test_a_spell_that_gives_no_credit_counts_for_nothing(self):
        self.assertEqual(server.object_credits([(1, 9)], {273097: {1294248}}, self.effects), {})

    def test_the_quest_counts_while_the_object_is_spawned(self):
        ctx = world(spawned_npc={100}, spawned_go={652657}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)], quests={10: quest_row()},
                    quest_turn_in_text={10}, objectives=[(10, 0, 273097, 1)])
        ctx['object_credits'] = {273097: {652657}}
        self.assertEqual(evaluate({'quest': {10: {}}}, ctx)[('quest', 10)][0], 'ok')
        ctx['spawned_go'] = set()
        self.assertEqual(failed(evaluate({'quest': {10: {}}}, ctx)[('quest', 10)]), ['objectives'])


class TeachersOnly(unittest.TestCase):
    """An item whose only way in is a spell only items teach: the rules name those items for ft.output."""

    def test_named_when_only_items_teach(self):
        ctx = world(creates={7: {70}}, teaches={70: {8}})
        evaluate({'item': {7: {}, 8: {}}}, ctx)
        self.assertEqual(ctx['teachers_only'], {7: {8}})

    def test_a_trained_or_rewarded_spell_is_left_out(self):
        ctx = world(creates={7: {70}}, teaches={70: {8}}, trainers=[(300, 1)], trainer_spells=[(1, 70)])
        evaluate({'item': {7: {}, 8: {}}}, ctx)
        self.assertEqual(ctx['teachers_only'], {})   # a trainer has it, even one not spawned: the realm can teach it
        ctx = world(creates={7: {70}}, teaches={70: {8}}, quests={10: quest_row(RewardSpell=70)})
        evaluate({'item': {7: {}, 8: {}}, 'quest': {10: {}}}, ctx)
        self.assertEqual(ctx['teachers_only'], {})

    def test_nothing_teaches_it_at_all(self):
        ctx = world(creates={7: {70}})
        evaluate({'item': {7: {}}}, ctx)
        self.assertEqual(ctx['teachers_only'], {})   # no teacher to judge it by: it stays on the list


class UnusedCopies(unittest.TestCase):
    """Forever's second Portals Deck (235275, spell 1216291) beside the classic 19277 (spell 23680): both made from the
    same eight cards, the cards cast 23680. The copy is not a gap."""

    CARDS = frozenset({19276, 19278, 19279, 19280, 19281, 19282, 19283, 19284})

    def setUp(self):
        # creature 100 drops the Ace; using it casts 23680, which makes 19277; 1216291 makes 235275 and nothing casts it
        self.ctx = world(spawned_npc={100}, npc_loot=[(100, 900, 0, 0)], item_spells={19276: {23680}},
                         creates={19277: {23680}, 235275: {1216291}}, used_spells={23680: {19276}},
                         spell_reagents={23680: self.CARDS, 1216291: self.CARDS})
        self.ctx['loot']['creature'] = [(900, 0, 19276, 0)]
        self.items = {19276: {'name': 'Ace of Portals'}, 19277: {'name': 'Portals Deck'}, 235275: {'name': 'Portals Deck'}}

    def test_the_copy_is_no_gap(self):
        result = evaluate({'item': self.items}, self.ctx)
        self.assertEqual(result[('item', 19277)][0], 'ok')
        self.assertEqual(result[('item', 235275)][0], 'ok')
        self.assertIn('19277', result[('item', 235275)][2][1]['detail']['en'])
        self.assertEqual(self.ctx['unused_copies'], {235275: {19277}})

    def test_other_reagents_are_no_copy(self):
        self.ctx['spell_reagents'][1216291] = frozenset({1, 2})
        self.assertEqual(failed(evaluate({'item': self.items}, self.ctx)[('item', 235275)]), ['source'])

    def test_another_name_is_no_copy(self):
        self.items[235275] = {'name': 'Dunes Deck'}
        self.assertEqual(failed(evaluate({'item': self.items}, self.ctx)[('item', 235275)]), ['source'])

    def test_no_twin_players_get(self):
        self.ctx['spawned_npc'] = set()   # nobody drops the cards: neither deck is obtainable
        self.assertEqual(failed(evaluate({'item': self.items}, self.ctx)[('item', 235275)]), ['source'])

    def test_a_spell_something_casts_is_no_copy(self):
        self.ctx['used_spells'][1216291] = {555}   # some item casts it: its own gap, not a copy
        self.assertEqual(failed(evaluate({'item': self.items}, self.ctx)[('item', 235275)]), ['source'])


class ClosedLoops(unittest.TestCase):
    """The Warglaives of Azzinoth: the Twin Blades 18582 split into the Right 18583 (spell 22989, which triggers 22991
    for the Left 18584), the Right joins back (22990). Nothing gives any of them: a closed group."""

    def ctx(self, **over):
        ctx = world(creates={18583: {22989}, 18584: {22991}, 18582: {22990}}, item_spells={18582: {22989}, 18583: {22990}},
                    used_spells={22989: {18582}, 22991: {18582}, 22990: {18583}})
        ctx.update(over)
        return ctx

    def test_the_loop_is_closed(self):
        ctx = self.ctx()
        evaluate({'item': {18582: {}, 18583: {}, 18584: {}}}, ctx)
        self.assertEqual(ctx['closed_loops'], {18582, 18583, 18584})

    def test_a_way_in_opens_it(self):
        # a creature drops the Twin Blades: all three are made by use, none is a loop
        ctx = self.ctx(spawned_npc={100}, npc_loot=[(100, 900, 0, 0)])
        ctx['loot']['creature'] = [(900, 0, 18582, 0)]
        result = evaluate({'item': {18582: {}, 18583: {}, 18584: {}}}, ctx)
        self.assertEqual(ctx['closed_loops'], set())
        self.assertEqual(result[('item', 18584)][0], 'ok')

    def test_a_teacher_outside_the_group_is_no_loop(self):
        # item 8 (not in the group, nothing gives it) teaches what makes 7: 7 waits on 8, not on a loop
        ctx = world(creates={7: {70}}, teaches={70: {8}})
        evaluate({'item': {7: {}, 8: {}}}, ctx)
        self.assertEqual(ctx['closed_loops'], set())



class CoreGives(unittest.TestCase):
    """Items the world and the core's C++ hand over without a loot row: a spawned object's spell (the Windfury Cone),
    a scripted creature's cast (Jaina's Autograph), a spell script's casts (the Bending Shinbone), the battleground
    marks, a spell script's own AddItem (the well samples), Drain Soul's death item."""

    def test_an_objects_spell_and_a_creatures_script(self):
        ctx = world(spawned_go={403105}, spawned_npc={4968}, creates={206170: {412365}, 18642: {23122}, 9: {99}},
                    world_casts={412365: {('go', 403105)}, 23122: {('npc', 4968)}, 99: {('npc', 5)}})
        results = evaluate({'item': {206170: {}, 18642: {}, 9: {}}}, ctx)
        self.assertEqual(results[('item', 206170)][0], 'ok')
        self.assertEqual(results[('item', 18642)][0], 'ok')
        self.assertEqual(failed(results[('item', 9)]), ['source'])   # creature 5 is not in the world

    def test_a_conversations_cast_and_a_spawned_area_triggers_cast(self):
        # Trevan Rol's gossip casts 1280553 (his notes 267454); the spawned Well of Eternity trigger 42773 casts 1293359
        # (the Cleansed Heart 274163). ft.server reads area triggers only when spawned, so ('at', id) needs no spawn.
        ctx = world(spawned_npc={248840}, creates={267454: {1280553}, 274163: {1293359}},
                    world_casts={1280553: {('npc', 248840)}, 1293359: {('at', 42773)}})
        results = evaluate({'item': {267454: {}, 274163: {}}}, ctx)
        self.assertEqual(results[('item', 267454)][0], 'ok')
        self.assertEqual(results[('item', 274163)][0], 'ok')

    def test_the_server_follows_a_spell_scripts_casts(self):
        # item 7131 casts 8856, whose C++ script casts 8854 or 8855; 8855 creates 7134
        effects = [{'SpellID': 8855, 'Effect': 24, 'EffectTriggerSpell': 0, 'EffectItemType': 7134, 'EffectMiscValue1': 0}]
        used = server.used_spells({7131: {8856}}, effects, {8856: {8854, 8855}})
        self.assertEqual(used, {8856: {7131}, 8854: {7131}, 8855: {7131}})
        # a world object's own spell, keyed by ('go', entry)
        self.assertEqual(server.used_spells({('go', 1): {5}}, effects), {5: {('go', 1)}})

    def test_battleground_marks_need_the_battleground(self):
        ctx = world(battlegrounds={30})
        results = evaluate({'item': {20560: {}, 20558: {}}}, ctx)
        self.assertEqual(results[('item', 20560)][0], 'ok')
        self.assertEqual(failed(results[('item', 20558)]), ['source'])   # Warsong Gulch is not declared here

    def test_darkspear_islands_marks(self):
        # WoW Forever's battleground: the core gives its Mark of Honor at the end of a battle like the vanilla ones
        results = evaluate({'item': {274895: {}}}, world(battlegrounds={2997}))
        self.assertEqual(results[('item', 274895)][0], 'ok')
        self.assertEqual(failed(evaluate({'item': {274895: {}}}, world(battlegrounds={30}))[('item', 274895)]), ['source'])

    def test_a_spell_scripts_own_item(self):
        # the Well Testing Kit 254545 (a quest's start item, given here by a vendor) casts 1258773
        ctx = world(spawned_npc={100}, vendors=[(100, 254545)], item_spells={254545: {1258773}}, used_spells={1258773: {254545}})
        results = evaluate({'item': {254545: {}, 254546: {}, 254547: {}}}, ctx)
        self.assertEqual(results[('item', 254546)][0], 'ok')
        self.assertEqual(results[('item', 254547)][0], 'ok')

    def test_a_quest_started_by_a_made_item(self):
        # 3985 starts 8552; it comes from a creature's loot
        ctx = world(spawned_npc={100}, npc_loot=[(100, 900, 0, 0)], start_quest_item={8552: 3985}, q_end_npc=[(100, 8552)],
                    quests={8552: quest_row()}, quest_turn_in_text={8552})
        ctx['loot']['creature'] = [(900, 0, 3985, 0)]
        self.assertEqual(evaluate({'quest': {8552: {}}, 'item': {3985: {}}}, ctx)[('quest', 8552)][0], 'ok')


class WritsAndPouches(unittest.TestCase):
    """The Craftsman's Writ gaps of 2026-11-27: a Coin Pouch that opens empty, a camp vendor handing out what the
    other side's sells for Merchant's Favor, and the writ a sealed letter gives. (A writ destroyed on accept is a
    core fix since wow-trinitycore-everlake #172: the core keeps any starting item the quest needs.)"""

    def pouch(self, **over):
        ctx = world(spawned_npc={100}, vendors=[(100, 284586)], item_has_loot={284586}, **over)
        return evaluate({'item': {284586: {}}}, ctx)[('item', 284586)]

    def test_a_pouch_with_nothing_in_it(self):
        self.assertEqual(failed(self.pouch()), ['contents'])

    def test_a_pouch_with_money(self):
        self.assertEqual(failed(self.pouch(item_money={284586})), [])

    def test_a_pouch_with_loot(self):
        ctx = world(spawned_npc={100}, vendors=[(100, 284586)], item_has_loot={284586})
        ctx['loot']['item'] = [(284586, 0, 2589, 0)]
        self.assertEqual(failed(evaluate({'item': {284586: {}, 2589: {}}}, ctx)[('item', 284586)]), [])

    def test_a_vendor_that_lost_the_price(self):
        ctx = world(spawned_npc={100, 101}, vendors=[(100, 262764), (101, 262764)],
                    vendor_costs={262764: {(100, 0), (101, 11041)}})
        result = evaluate({'item': {262764: {}}}, ctx)[('item', 262764)]
        self.assertEqual(failed(result), ['price'])
        ctx = world(spawned_npc={100, 101}, vendors=[(100, 262764), (101, 262764)],
                    vendor_costs={262764: {(100, 11041), (101, 11041)}})
        self.assertEqual(failed(evaluate({'item': {262764: {}}}, ctx)[('item', 262764)]), [])

    def test_a_price_only_an_unspawned_vendor_asks(self):
        # Private's Tabard: Officer Areyn (spawned) sells it for gold; Issca (not spawned) lists it for honor
        ctx = world(spawned_npc={12805}, vendors=[(12805, 15196), (16766, 15196)],
                    vendor_costs={15196: {(12805, 0), (16766, 1007)}})
        self.assertEqual(failed(evaluate({'item': {15196: {}}}, ctx)[('item', 15196)]), [])

    def test_what_a_sealed_letter_gives_is_its_content_not_a_craft(self):
        # 248206 Sealed Craftsman's Writ is sold; using it casts 1247526, whose loot is the writ
        ctx = world(spawned_npc={100}, vendors=[(100, 248206)], item_spells={248206: {1247526}}, used_spells={1247526: {248206}},
                    known={kind: set() for kind in KINDS})
        ctx['loot']['spell'] = [(1247526, 0, 264121, 0)]
        result = evaluate({'item': {248206: {}, 264121: {}}}, ctx)[('item', 264121)]
        source = [c for c in result[2] if c['code'] == 'source'][0]
        self.assertEqual(source['detail']['en'], 'Container content')


class NotOnLive(unittest.TestCase):
    def test_a_quest_live_does_not_give(self):
        # 7704: nobody gives it; it is filed with the quests live does not give, so no import proposes a giver
        ctx = world(spawned_npc={100}, q_end_npc=[(100, 7704)], quests={7704: quest_row()}, quest_turn_in_text={7704})
        evaluate({'quest': {7704: {}}}, ctx)
        self.assertIn(7704, ctx['not_given_quests'])


if __name__ == '__main__':
    unittest.main()
