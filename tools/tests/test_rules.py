"""python -m unittest discover -s tools/tests

The availability rules (ft.rules.evaluate_all) on a world small enough to read: a handful of creatures, quests and
items built by hand. No database: the context is what ft.server would have read.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import rules  # noqa: E402

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

    def test_a_summoned_chest(self):
        ctx = world(go_loot=[(500, 3, 901)], summoned_go={500})
        ctx['loot']['gameobject'] = [(901, 0, 3, 0)]
        self.assertEqual(evaluate({'item': {3: {}}}, ctx)[('item', 3)][0], 'ok')


class Quests(unittest.TestCase):
    def setUp(self):
        self.ctx = world(spawned_npc={100}, q_start_npc=[(100, 10)], q_end_npc=[(100, 10)], quests={10: quest_row()}, quest_turn_in_text={10})

    def run_quest(self):
        return evaluate({'quest': {10: {}}}, self.ctx)[('quest', 10)]

    def test_a_complete_quest(self):
        self.assertEqual(self.run_quest()[0], 'ok')

    def test_no_quest_text(self):
        self.ctx['quests'][10]['HasText'] = 0
        result = self.run_quest()
        self.assertEqual((result[0], failed(result)), ('partial', ['texts']))
        self.assertGreaterEqual(result[1], 85)   # a doable quest without its words stays near the top

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


class FlightPoints(unittest.TestCase):
    def test_a_flight_an_npcs_script_starts(self):
        content = {'taxi': {62: {'pos': [7800.0, -2500.0, 490.0], 'map': 1}}}
        ctx = world(flight_spawns=[(1, 7450.0, -2490.0)])      # the ordinary flight master, 350 yards off
        self.assertEqual(failed(evaluate(content, ctx)[('taxi', 62)]), ['flightmaster'])
        ctx['script_taxi_nodes'] = {62}
        self.assertEqual(evaluate(content, ctx)[('taxi', 62)][0], 'ok')


if __name__ == '__main__':
    unittest.main()
