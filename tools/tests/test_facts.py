"""python -m unittest discover -s tools/tests

The last class needs a MySQL server: it runs when FT_TEST_CONFIG names a config.ini of a throwaway server (its
[database] tracker database is created and dropped), and is skipped otherwise.
"""
import collections
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import facts  # noqa: E402
from ft.facts import Fact  # noqa: E402

COMMIT = 'a' * 40
MANY = [{'instance': 0, 'worldX': float(i), 'worldY': 1.0} for i in range(55)]
BUILD = {
    'npcs': {'meta': {}, 'approached': {'47': {'name': 'Wanted poster'}},
             'npcs': {'240': {'name': 'Marshal Dughan', 'levels': [25], 'side': 'Alliance', 'interactions': ['QuestGiver'], 'sources': 3, 'windows': 9,
                              'positions': [{'instance': 0, 'worldX': -9465.5, 'worldY': 74.0, 'uiMap': 1429}],
                              'options': {'96270': {'name': 'I would like to buy from you.'}},
                              'offers': {'35': {'title': 'Further Concerns', 'level': 10, 'repeatable': False}, 'x': {}, '²': {}},
                              'takes': {'54': {'title': 'Report to Goldshire'}}},
                      '241': {'name': 'Seen by one player, window never counted', 'sources': 1, 'positions': MANY},
                      'npc:9': {'name': 'bad key'}, '242': ['not', 'a', 'record']},
             'objects': {'35': {'name': "Captain's Footlocker", 'sources': 1, 'windows': 0, 'offers': {'138': {}}}}},
    'creatures': {'creatures': {'474': {'name': 'Defias Rogue Wizard', 'levels': {'9': 4, '10': 1}, 'classifications': ['normal'], 'seen': 5, 'sources': 2,
                                        'rep': {'72': 5}, 'combatLog': {'entries': 3, 'levels': {'9': 3}, 'casts': {'133': 2}, 'positions': MANY}},
                                'ghost': 'not a record'}},
    'vendors': {'vendors': {'74': {'name': 'Kurran Steele', 'repairs': True, 'entries': {
        'item:1839': {'itemId': 1839, 'name': 'Rough Leather Belt', 'costs': {'5': 184}, 'stack': 1, 'sources': 2},
        'item:1839#2': {'itemId': 1839, 'name': 'Rough Leather Belt', 'costs': {'5': 900}, 'stack': 5, 'sources': 1},
        'item:10938': {'itemId': 10938, 'bartered': True, 'limited': True, 'stockMax': 2, 'stack': 1, 'sources': 1},
        'item:0': {'itemId': 0}}}, '75': {'name': 'No stock seen'}, '76': {'entries': ['odd']}}},
    'trainers': {'trainers': {'377': {'name': 'Priestess Josetta', 'trainerType': 0, 'tradeskill': False, 'services': {
        '17': {'spellId': 17, 'name': 'Power Word: Shield', 'costs': {'5': 100, '6': 90}, 'level': 6, 'rankText': 'Rank 1', 'skillRank': 0, 'sources': 1},
        'broken': {'name': 'no spell'}}}}},
    'loot': {'format': 3,
             'kills': {'npc:474': {'deaths': 14, 'unknown': 2, 'empty': 6}, 'npc:474|group': {'deaths': 5, 'unknown': 0, 'empty': 1},
                       'npc:474|quest|group': {'deaths': 2, 'unknown': 0, 'empty': 0}},
             'rolls': {'encounter:2732|threshold:2': {'items': {'272998': {'drops': 1}}}},
             'sources': {
                 # the source's chance is per kill, not drops over windows: it is kept, not worked out again
                 'npc:474': {'windows': 10, 'coins': 9, 'copper': 236, 'copperWindows': 9,
                             'items': {'2589': {'drops': 4, 'quantity': 6, 'chance': 0.2}, '1210': {'drops': 1, 'quantity': 1, 'chance': 0.05, 'quest': 76}}},
                 'npc:474|group': {'windows': 5, 'items': {'2589': {'drops': 1, 'quantity': 1, 'chance': 0.16}}},
                 'npc:474|quest|group': {'windows': 2, 'items': {'2589': {'drops': 2, 'quantity': 2, 'chance': 1.0}}},
                 'npc:474|spell:8613': {'windows': 3, 'items': {'2318': {'drops': 3, 'quantity': 3, 'chance': 1.0}}},
                 'npc:474|spell:8617': {'windows': 4, 'items': {'2319': {'drops': 1, 'quantity': 1, 'chance': 0.25}}},
                 'npc:474|spell:8613|bountifulHarvest:2': {'windows': 1, 'items': {'2318': {'drops': 1, 'quantity': 4, 'chance': 1.0}}},
                 'object:2843|spell:6478': {'windows': 4, 'copper': 12, 'items': {'118': {'drops': 2, 'quantity': 2, 'chance': 0.5}}},
                 'object:2843|spell:6478|group': {'windows': 6, 'items': {'118': {'drops': 1, 'quantity': 1, 'chance': 0.17}}},
                 'item:20708': {'windows': 2, 'items': {'6358': {'drops': 2, 'quantity': 2, 'chance': 1.0}}},
                 'fishing:1413': {'windows': 55, 'items': {'6361': {'drops': 22, 'quantity': 22, 'chance': 0.4}}},
                 'npc:abc': {'windows': 1, 'items': {}}, 'mailbox:7': {'windows': 1, 'items': {'1': {'drops': 1}}},
                 'npc:475': {'windows': 1, 'items': {'x': {'drops': 1}, '9': 'odd'}}}},
    'quests.enUS': {'quests': {'91724': {'title': 'Delicate Instruments', 'level': 10, 'minLevel': 6, 'sources': 3,
                                         'description': "Line one.\r\nIt's 'quoted' \\ and é \U0001f600."}}},
    'creature_details.enUS': {'creatures': {'4578': {'name': 'Josephine Lister', 'displays': [{'displayId': 2664}], 'sources': 3}}},
    'object_details.enUS': {'objects': {'180006': {'name': 'Outhouse', 'type': 5, 'sources': 1}}},
    'objectives': {'quests': {'1014': {'1': {'type': 'item', 'required': 1, 'gains': 1, 'sources': 1, 'positions': MANY}, 'x': {}}, '1015': ['odd']},
                   'completed': {'2843': {}}},
    'turn_ins': {'quests': {'1109': [{'xp': 6950, 'money': 0, 'sources': 2}, 'junk', {'xp': 7000, 'sources': 1}], '1110': 'junk'}, 'withLegacy': {}},
    'game_rules': {'rules': {'1': 2}},
}


def tree(folder, builds=('1.60.1.70862',), content=BUILD):
    for build in builds:
        os.makedirs(os.path.join(folder, build))
        for dataset, body in content.items():
            with open(os.path.join(folder, build, dataset + '.json'), 'w', encoding='utf-8') as handle:
                json.dump(body, handle)


class EgLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        tree(cls.folder.name)
        os.makedirs(os.path.join(cls.folder.name, 'not-a-build'))
        os.makedirs(os.path.join(cls.folder.name, '1.60.1.70862\n'))
        with open(os.path.join(cls.folder.name, '1.60.1.70862', 'flights.json'), 'w') as handle:
            handle.write('{broken: a dataset nothing reads may be anything')
        cls.skipped = collections.Counter()
        cls.facts = list(facts.eglink(cls.folder.name, cls.skipped))
        cls.by = {(f.kind, f.subject_kind, f.subject, f.object): f for f in cls.facts}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_every_fact_is_storable_on_its_build_and_none_hides_another(self):
        self.assertEqual(len(self.by), len(self.facts))
        for fact in self.facts:
            self.assertIsNotNone(facts.check(fact), fact)
            self.assertEqual(fact.build, 70862)
        self.assertEqual(collections.Counter(f.kind for f in self.facts), {
            'talked': 3, 'gives': 2, 'takes': 1, 'seen': 1, 'sells': 2, 'teaches': 1, 'drops': 4, 'gathers': 2, 'fishes': 1, 'coins': 2,
            'quest': 1, 'creature': 1, 'object': 1, 'objective': 1, 'turn_in': 1})

    def test_who_gives_and_takes_a_quest(self):
        self.assertEqual(self.by[('gives', 'npc', 240, 35)], Fact('gives', 'npc', 240, 35, 70862, 3, {'title': 'Further Concerns', 'level': 10, 'repeatable': False}))
        self.assertEqual(self.by[('takes', 'npc', 240, 54)].data, {'title': 'Report to Goldshire'})
        self.assertEqual(self.by[('gives', 'object', 35, 138)], Fact('gives', 'object', 35, 138, 70862, 1, {}))
        self.assertNotIn(('talked', 'npc', 47, 0), self.by)          # "approached" is not a window a player opened

    def test_a_window_a_player_opened(self):
        talked = self.by[('talked', 'npc', 240, 0)]
        self.assertEqual((talked.samples, talked.data['levels'], talked.data['options']), (9, [25], {'96270': {'name': 'I would like to buy from you.'}}))
        self.assertNotIn('offers', talked.data)                      # its quests are facts of their own
        uncounted = self.by[('talked', 'npc', 241, 0)]
        self.assertEqual(uncounted.samples, 0)                       # no window counted: players are not windows
        self.assertEqual((len(uncounted.data['positions']), uncounted.data['positionsSeen']), (40, 55))

    def test_what_was_seen_in_the_world(self):
        seen = self.by[('seen', 'npc', 474, 0)]
        self.assertEqual((seen.samples, seen.data['levels'], seen.data['rep'], seen.data['combatLog']['casts']), (5, {'9': 4, '10': 1}, {'72': 5}, {'133': 2}))
        self.assertEqual((len(seen.data['combatLog']['positions']), seen.data['combatLog']['positionsSeen']), (40, 55))

    def test_what_a_vendor_sells_every_listing(self):
        belt = self.by[('sells', 'npc', 74, 1839)]
        self.assertEqual(belt.samples, 2)
        self.assertEqual([(l['costs'], l['stack']) for l in belt.data['listings']], [({'5': 184}, 1), ({'5': 900}, 5)])
        self.assertEqual(self.by[('sells', 'npc', 74, 10938)].data['listings'],
                         [{'itemId': 10938, 'bartered': True, 'limited': True, 'stockMax': 2, 'stack': 1, 'sources': 1}])

    def test_what_a_trainer_teaches(self):
        taught = self.by[('teaches', 'npc', 377, 17)]
        self.assertEqual(taught.samples, 1)
        self.assertEqual(taught.data, {'spellId': 17, 'name': 'Power Word: Shield', 'costs': {'5': 100, '6': 90}, 'level': 6, 'rankText': 'Rank 1',
                                       'skillRank': 0, 'sources': 1, 'trainerType': 0, 'tradeskill': False})

    def test_drops_keep_each_way_of_looting_with_the_source_s_numbers(self):
        linen = self.by[('drops', 'npc', 474, 2589)]
        self.assertEqual(linen.samples, 10)                          # the windows that show every item: a group's do not
        self.assertEqual(linen.data, {'ways': {
            'plain': {'drops': 4, 'quantity': 6, 'chance': 0.2, 'windows': 10, 'kills': 12, 'empty': 6},
            'group': {'drops': 1, 'quantity': 1, 'chance': 0.16, 'windows': 5, 'kills': 5, 'empty': 1},
            'quest|group': {'drops': 2, 'quantity': 2, 'chance': 1.0, 'windows': 2, 'kills': 2, 'empty': 0}}})
        self.assertEqual(self.by[('drops', 'npc', 474, 1210)].data['ways']['plain']['quest'], 76)

    def test_loot_through_a_spell_keeps_each_spell_apart(self):
        leather = self.by[('gathers', 'npc', 474, 2318)]
        self.assertEqual(leather.samples, 4)
        self.assertEqual(leather.data['ways'], {'spell:8613': {'drops': 3, 'quantity': 3, 'chance': 1.0, 'windows': 3},
                                                'spell:8613|bountifulHarvest:2': {'drops': 1, 'quantity': 4, 'chance': 1.0, 'windows': 1}})
        self.assertEqual(list(self.by[('gathers', 'npc', 474, 2319)].data['ways']), ['spell:8617'])       # another spell, another loot
        chest = self.by[('drops', 'object', 2843, 118)]
        self.assertEqual((chest.samples, sorted(chest.data['ways'])), (4, ['spell:6478', 'spell:6478|group']))
        self.assertEqual(self.by[('drops', 'item', 20708, 6358)].samples, 2)
        self.assertEqual(self.by[('fishes', 'uimap', 1413, 6361)].data['ways']['plain']['chance'], 0.4)

    def test_money(self):
        self.assertEqual(self.by[('coins', 'npc', 474, 0)], Fact('coins', 'npc', 474, 0, 70862, 10, {'ways': {
            'plain': {'coins': 9, 'copper': 236, 'copperWindows': 9, 'windows': 10, 'kills': 12, 'empty': 6}}}))
        self.assertEqual(self.by[('coins', 'object', 2843, 0)].data, {'ways': {'spell:6478': {'copper': 12, 'windows': 4}}})

    def test_records_as_the_server_sent_them(self):
        quest = self.by[('quest', 'quest', 91724, 0)]
        self.assertEqual((quest.samples, quest.data), (3, BUILD['quests.enUS']['quests']['91724']))
        self.assertEqual(self.by[('creature', 'npc', 4578, 0)].data['displays'], [{'displayId': 2664}])
        self.assertEqual(self.by[('object', 'object', 180006, 0)].data['type'], 5)

    def test_objectives_and_turn_ins(self):
        objective = self.by[('objective', 'quest', 1014, 1)]
        self.assertEqual((objective.samples, objective.data['required'], len(objective.data['positions']), objective.data['positionsSeen']), (1, 1, 40, 55))
        self.assertEqual(self.by[('turn_in', 'quest', 1109, 0)],
                         Fact('turn_in', 'quest', 1109, 0, 70862, 2, {'seen': [{'xp': 6950, 'money': 0, 'sources': 2}, {'xp': 7000, 'sources': 1}]}))

    def test_what_could_not_be_read_is_counted_not_guessed(self):
        self.assertEqual(dict(self.skipped), {'npcs': 4, 'creatures': 1, 'vendors': 1, 'trainers': 1, 'loot': 4, 'objectives': 2, 'turn_ins': 1})

    def test_builds_in_order_and_a_missing_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            tree(folder, ('1.60.1.70862', '1.60.1.70790', '1.60.1.9'), {'vendors': BUILD['vendors']})
            self.assertEqual([f.build for f in facts.eglink(folder)], [9, 9, 70790, 70790, 70862, 70862])
            self.assertEqual(list(facts.eglink(os.path.join(folder, 'nowhere'))), [])

    def test_a_broken_download_stops_the_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            tree(folder, content={'vendors': BUILD['vendors']})
            with open(os.path.join(folder, '1.60.1.70862', 'loot.json'), 'w') as handle:
                handle.write('{"sources": {"npc:474": {"windows": 10, "ite')
            with self.assertRaises(facts.SourceError) as broken:
                list(facts.eglink(folder))
            self.assertIn('loot.json', str(broken.exception))

    def test_ids(self):
        self.assertEqual([facts._id(v) for v in ('474', 474, '0', '-1', '4294967296', '²', '٣', ' 5', '5\n', 'abc', None)],
                         [474, 474, None, None, None, None, None, None, None, None, None])


def lua(module, body, more=''):
    return (f'local {module} = QuestieLoader:CreateModule("{module}")\nlocal QuestieDB = QuestieLoader:ImportModule("QuestieDB")\n\n'
            f'function {module}:Load()\n    local npcKeys = QuestieDB.npcKeys\n\n    return {{\n{body}\n    }}\nend\n{more}')


QUESTIE = {
    'foreverQuestFixes.lua': lua('ForeverQuestFixes', '[91758] = { [questKeys.preQuestSingle] = {91752}, },',
                                 # as QuestieDB writes what depends on the player: tables kept in locals, one of them returned
                                 'function ForeverQuestFixes:LoadDynamic()\n    local questKeys = QuestieDB.questKeys\n\n'
                                 '    local questFixesHorde = {\n        [92000] = { [questKeys.startedBy] = {{240}} },\n    }\n\n'
                                 '    local questFixesAlliance = {\n        [92000] = { [questKeys.startedBy] = {{241}}, [questKeys.questLevel] = 7 },\n    }\n\n'
                                 '    if UnitFactionGroup("Player") == "Horde" then\n        return questFixesHorde\n    else\n'
                                 '        return questFixesAlliance\n    end\nend\n'),
    'foreverNPCFixes.lua': lua('ForeverNpcFixes', '[384] = { -- Katie Hunter <Horse Breeder>\n'
                               '    [npcKeys.npcFlags] = npcFlags.VENDOR, -- base data adds a wrong innkeeper bit\n    [npcKeys.questStarts_remove] = {5},\n},'),
    'foreverObjectFixes.lua': lua('ForeverObjectFixes', ''),
    'foreverItemFixes.lua': lua('ForeverItemFixes', ''),
    'generated/foreverBaseQuest.lua': lua('ForeverBaseQuest', '[91758] = { -- Follow That Kobold! : https://example.invalid/quest=91758\n'
                                          '    [questKeys.startedBy] = {{197},nil,{12345}},\n'
                                          '    [questKeys.requiredRaces] = raceIDs.NIGHT_ELF + raceIDs.HUMAN,\n},'),
    'generated/foreverBaseNpc.lua': lua('ForeverBaseNpc', '[197] = { [npcKeys.questStarts_add] = {91758}, [npcKeys.minLevel] = 5, },\n'
                                        '[167] = { [npcKeys.questStarts] = {86776}, },'),
    'generated/foreverBaseObject.lua': lua('ForeverBaseObject', ''),
    'generated/foreverBaseItem.lua': lua('ForeverBaseItem', '[190232] = {\n    [itemKeys.vendors_add] = {74},\n    [itemKeys.startQuest] = 91758,\n'
                                         '    [itemKeys.itemDrops] = {20708},\n    [itemKeys.npcDrops] = {3782, "x", 1.5},\n},'),
    'traces/foreverQuestTraces.lua': lua('ForeverQuestTraces', '[91758] = {\n    [questKeys.name] = "Follow That Kobold!",\n'
                                         '    [questKeys.startedBy_add] = {{197}},\n    [questKeys.finishedBy_add] = {nil,{35}},\n},\n'
                                         '[465] = {\n    [questKeys.finishedBy_add] = {nil, {630696}},\n},'),
    'traces/foreverNpcTraces.lua': lua('ForeverNpcTraces', '[197] = {\n    [npcKeys.name] = "Marshal McBride",\n'
                                       '    [npcKeys.questStarts_add] = {91758,92479},\n    [npcKeys.questEnds_add] = {91752},\n'
                                       '    [npcKeys.spawns] = {[zoneIDs.ELWYNN_FOREST] = {{48.92,41.61}}},\n},\n["oops"] = { [npcKeys.questStarts_add] = {1} },'),
    'traces/foreverObjectTraces.lua': lua('ForeverObjectTraces', '[35] = { [objectKeys.questEnds_add] = {91758}, },'),
    'traces/foreverItemTraces.lua': lua('ForeverItemTraces', '[190232] = {\n    [itemKeys.name] = "Withered Scarf",\n'
                                        '    [itemKeys.npcDrops_add] = {3782,3784},\n    [itemKeys.objectDrops_add] = {386691},\n},'),
}


def questie_tree(folder, files=QUESTIE):
    for name, text in files.items():
        path = os.path.join(folder, 'src', 'corrections', 'Forever', name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)


class Questie(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        questie_tree(cls.folder.name)
        cls.skipped = collections.Counter()
        cls.facts = list(facts.questie(cls.folder.name, cls.skipped))
        cls.by = {(f.kind, f.subject_kind, f.subject, f.object): f for f in cls.facts}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def parts(self, *key):
        return self.by[key].data['parts']

    def test_the_file_list_is_the_twelve_forever_correction_files(self):
        self.assertEqual(sorted(facts.QUESTIE_FILES), sorted('src/corrections/Forever/' + name for name in QUESTIE))
        self.assertEqual(facts.QUESTIE_FILES['src/corrections/Forever/traces/foreverNpcTraces.lua'], ('npc', 'trace'))
        self.assertEqual(facts.QUESTIE_FILES['src/corrections/Forever/foreverNPCFixes.lua'], ('npc', 'fix'))
        self.assertEqual(facts.QUESTIE_FILES['src/corrections/Forever/generated/foreverBaseItem.lua'], ('item', 'generated'))

    def test_every_fact_is_storable_and_none_hides_another(self):
        self.assertEqual(len(self.by), len(self.facts))
        for fact in self.facts:
            self.assertIsNotNone(facts.check(fact), fact)
            self.assertEqual(fact.build, 0)                          # not tied to a client build
        self.assertEqual(collections.Counter(f.kind for f in self.facts), {'gives': 7, 'takes': 3, 'drops': 4, 'sells': 1, 'entry': 8})

    def test_who_gives_a_quest_and_which_part_said_so(self):
        # the quest's file and the NPC's file say the same thing: one fact, both fields, per part
        self.assertEqual(self.parts('gives', 'npc', 197, 91758), {'generated': ['quest.startedBy', 'npc.questStarts_add'],
                                                                  'trace': ['quest.startedBy_add', 'npc.questStarts_add']})
        self.assertEqual(self.by[('gives', 'npc', 197, 91758)].samples, 1)       # players recorded it
        self.assertEqual((self.parts('gives', 'npc', 197, 92479), self.by[('gives', 'npc', 197, 92479)].samples), ({'trace': ['npc.questStarts_add']}, 1))
        self.assertEqual((self.parts('gives', 'npc', 167, 86776), self.by[('gives', 'npc', 167, 86776)].samples), ({'generated': ['npc.questStarts']}, 0))
        self.assertEqual(self.parts('gives', 'item', 12345, 91758), {'generated': ['quest.startedBy']})      # third list: items
        self.assertEqual(self.parts('gives', 'item', 190232, 91758), {'generated': ['item.startQuest']})
        # what depends on the player keeps the table it stands in: one side's giver is not the other's
        self.assertEqual(self.parts('gives', 'npc', 240, 92000), {'dynamic:questFixesHorde': ['quest.startedBy']})
        self.assertEqual(self.parts('gives', 'npc', 241, 92000), {'dynamic:questFixesAlliance': ['quest.startedBy']})
        self.assertEqual(self.parts('entry', 'quest', 92000, 0), {'dynamic:questFixesHorde': {'startedBy': [[240]]},
                                                                  'dynamic:questFixesAlliance': {'startedBy': [[241]], 'questLevel': 7}})
        self.assertNotIn(('gives', 'npc', 384, 5), self.by)                      # a _remove correction states no fact

    def test_who_takes_a_quest(self):
        self.assertEqual(self.parts('takes', 'npc', 197, 91752), {'trace': ['npc.questEnds_add']})
        self.assertEqual(self.parts('takes', 'object', 35, 91758), {'trace': ['quest.finishedBy_add', 'object.questEnds_add']})    # second list: objects
        self.assertEqual(self.parts('takes', 'object', 630696, 465), {'trace': ['quest.finishedBy_add']})

    def test_what_drops_and_sells_an_item(self):
        self.assertEqual(self.parts('drops', 'npc', 3782, 190232), {'generated': ['item.npcDrops'], 'trace': ['item.npcDrops_add']})
        self.assertEqual(self.parts('drops', 'npc', 3784, 190232), {'trace': ['item.npcDrops_add']})
        self.assertEqual(self.parts('drops', 'object', 386691, 190232), {'trace': ['item.objectDrops_add']})
        self.assertEqual(self.parts('drops', 'item', 20708, 190232), {'generated': ['item.itemDrops']})
        self.assertEqual(self.parts('sells', 'npc', 74, 190232), {'generated': ['item.vendors_add']})

    def test_entries_keep_the_database_s_own_words(self):
        npc = self.parts('entry', 'npc', 197, 0)
        self.assertEqual(npc, {'generated': {'questStarts_add': [91758], 'minLevel': 5},
                               'trace': {'name': 'Marshal McBride', 'questStarts_add': [91758, 92479], 'questEnds_add': [91752],
                                         'spawns': {'ELWYNN_FOREST': [[48.92, 41.61]]}}})
        self.assertEqual(self.parts('entry', 'npc', 384, 0), {'fix': {'npcFlags': 'npcFlags.VENDOR', 'questStarts_remove': [5]}})
        quest = self.parts('entry', 'quest', 91758, 0)
        self.assertEqual(list(quest), ['fix', 'generated', 'trace'])
        self.assertEqual(quest['generated']['requiredRaces'], 'raceIDs.NIGHT_ELF+raceIDs.HUMAN')     # a name is kept as a name, not looked up
        self.assertEqual(quest['trace']['finishedBy_add'], [None, [35]])
        self.assertEqual((self.by[('entry', 'npc', 384, 0)].samples, self.by[('entry', 'npc', 197, 0)].samples), (0, 1))

    def test_what_is_not_an_id_is_counted(self):
        self.assertEqual(dict(self.skipped), {'foreverNpcTraces.lua': 1, 'foreverBaseItem.lua': 2})

    def test_a_file_missing_or_written_another_way_stops_the_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            questie_tree(folder, {k: v for k, v in QUESTIE.items() if k != 'traces/foreverItemTraces.lua'})
            with self.assertRaises(facts.SourceError) as missing:
                list(facts.questie(folder))
            self.assertIn('foreverItemTraces.lua', str(missing.exception))
        for broken in ('local t = 5\n', lua('ForeverNpcTraces', '[1] = { [npcKeys.name] = function() return 1 end },')):
            with tempfile.TemporaryDirectory() as folder:
                questie_tree(folder, dict(QUESTIE, **{'traces/foreverNpcTraces.lua': broken}))
                with self.assertRaises(facts.SourceError) as unknown:
                    list(facts.questie(folder))
                self.assertIn('foreverNpcTraces.lua', str(unknown.exception))

    def test_a_shape_it_does_not_know_is_counted_never_guessed(self):
        odd = lua('ForeverBaseQuest', '[1] = { [questKeys.startedBy] = {197} },\n'                       # a flat list: npcs? objects?
                                      '[2] = { [questKeys.startedBy] = {{5},{6},{7},{8}} },\n'            # a fourth list
                                      '[3] = { [questKeys.finishedBy] = 9 },\n'
                                      '[4] = { [questKeys.startedBy] = {{"12", 3.5, true, 13}} },\n'
                                      '[5] = { [questKeys.startedBy] = {}, [questKeys.finishedBy] = {nil,{}} },')
        with tempfile.TemporaryDirectory() as folder:
            questie_tree(folder, dict({name: lua('X', '') for name in QUESTIE}, **{'generated/foreverBaseQuest.lua': odd}))
            skipped = collections.Counter()
            found = [(f.kind, f.subject_kind, f.subject, f.object) for f in facts.questie(folder, skipped) if f.kind != 'entry']
        self.assertEqual(found, [('gives', 'npc', 13, 4)])
        self.assertEqual(dict(skipped), {'foreverBaseQuest.lua': 6})        # three shapes, three values that are not ids

    def test_only_the_tables_of_its_functions_are_read(self):
        with tempfile.TemporaryDirectory() as folder:
            text = 'Somewhere.else = {\n    [50] = { questStarts = {1} },\n}\n' + lua('ForeverNpcTraces', '[60] = { [npcKeys.questStarts_add] = {2} },')
            questie_tree(folder, dict({name: lua('X', '') for name in QUESTIE}, **{'traces/foreverNpcTraces.lua': text}))
            self.assertEqual([(f.kind, f.subject) for f in facts.questie(folder)], [('gives', 60), ('entry', 60)])

    def test_ids_that_happen_to_count_from_one_are_still_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            questie_tree(folder, dict(QUESTIE, **{'traces/foreverNpcTraces.lua': lua('ForeverNpcTraces', '[1] = { [npcKeys.questStarts_add] = {7} },\n'
                                                                                     '[2] = { [npcKeys.questEnds_add] = {7} },')}))
            found = {(f.kind, f.subject, f.object) for f in facts.questie(folder) if f.subject_kind == 'npc' and f.object == 7}
            self.assertEqual(found, {('gives', 1, 7), ('takes', 2, 7)})

    def test_fetch(self):
        asked = []

        def fetch(url):
            asked.append(url.replace(f'https://raw.githubusercontent.com/Questie/QuestieDB/{COMMIT}/', ''))
            return b'function X:Load()\n    return {}\nend\n'
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(facts.fetch_questie(COMMIT, folder, fetch), 12)
            self.assertEqual(asked, list(facts.QUESTIE_FILES))
            self.assertEqual(facts.fetch_questie(COMMIT, folder, fetch), 0)
            self.assertEqual(list(facts.questie(folder)), [])                # twelve empty files: nothing to say
        cut = QUESTIE['traces/foreverNpcTraces.lua'].encode()[:200]
        for body in (b'404: Not Found', b'<html><body>return to the home page</body></html>', cut, b'function X:Load()\n    return answer\nend\n'):
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(facts.SourceError) as refused:
                    facts.fetch_questie(COMMIT, folder, lambda url: body)
                self.assertIn('foreverQuestFixes.lua', str(refused.exception))                  # the file is named
                self.assertEqual([names for _root, _dirs, names in os.walk(folder) if names], [])      # and not kept

        def unreachable(url):
            raise OSError('no route')
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(facts.SourceError) as refused:
            facts.fetch_questie(COMMIT, folder, unreachable)
        self.assertIn('foreverQuestFixes.lua', str(refused.exception))
        for pin in ('master', '', None, 'a' * 40 + '\n'):
            with self.assertRaises(facts.SourceError):
                facts.fetch_questie(pin, '/nonexistent', fetch)


class Lua(unittest.TestCase):
    def test_values(self):
        from ft import luadata
        value = luadata.parse_value('{ "a\\"b", \'c\\\'d\', 12, -3.5, 0x10, true, false, nil, [[\nlong\n]], "caf\\195\\169", }')
        self.assertEqual(value, ['a"b', "c'd", 12, -3.5, 16, True, False, None, 'long\n', 'café'])     # a long string drops its first line break
        self.assertEqual(luadata.parse_value('{ [k.name] = "x", [5] = {1, 2}, plain = l10n("text"), sum = 1 + 2, ["Mr. Smith"] = k.A + k.B }'),
                         {'name': 'x', '5': [1, 2], 'plain': 'text', 'sum': 3, 'Mr. Smith': 'k.A+k.B'})
        self.assertEqual(luadata.parse_value('{ -- a comment with a } brace\n  1, --[[ and { another ]] 2 }'), [1, 2])

    def test_what_is_not_plain_data_is_refused_not_guessed(self):
        from ft import luadata
        for text in ('', '{1,', '{[k.a]=5-1}', '{1 2 3}', '{1+2*3}', '{4/2}', '{1..2}', '{ f = function() end }', '{ a = b and c }', '{1} {2}',
                     '{ "open', '{ [[open', '{' * 3):
            with self.assertRaises(ValueError, msg=text):
                luadata.parse_value(text)
        self.assertEqual(luadata.parse_value('{ a = 1 + 2, b = k.A + k.B, c = 2 + k.A }'), {'a': 3, 'b': 'k.A+k.B', 'c': '2+k.A'})

    def test_tables_of_a_file(self):
        from ft import luadata
        found = luadata.tables('X.data = [[return {\n[1] = {"a",nil,3},\n}]]\nlocal y = { 1, 2 }\nfunction M:Load()\n  return { [7] = { [k.a] = 1 } }\nend\n')
        self.assertEqual(found, {'X.data': [['a', None, 3]], 'y': [1, 2], 'M:Load': {'7': {'a': 1}}})    # keys 1..n in order are a list
        self.assertIn('_skipped', luadata.tables('function M:Load()\n  return { [1] = { [k.a] = function() end } }\nend\n'))

    def test_tables_a_function_keeps_in_locals(self):
        from ft import luadata
        found = luadata.tables('function M:LoadDynamic()\n    local keys = Q.keys\n    local horde = {\n        [7] = { [k.a] = 1 },\n    }\n'
                               '    local alliance = {\n        [7] = { [k.a] = 2, [k.name] = [[Foo]] },\n    }\n'
                               '    if f() then\n        return horde\n    end\n    return alliance\nend\n')
        self.assertEqual(found, {'M:LoadDynamic/horde': {'7': {'a': 1}}, 'M:LoadDynamic/alliance': {'7': {'a': 2, 'name': 'Foo'}}})

    def test_a_function_it_cannot_follow_is_reported(self):
        from ft import luadata
        two = luadata.tables('function M:Load()\n    if x then\n        return { [1] = {} }\n    end\n    return { [2] = {} }\nend\n')
        self.assertEqual(list(two), ['_skipped'])
        self.assertIn('returns 2 tables', two['_skipped'][0])
        self.assertIn('_skipped', luadata.tables('function M:Load()\n    return build()\nend\n'))
        commented = luadata.tables('function M:Load()\n    -- return { [1] = {} }\n    return { [2] = {} }\nend\n')
        self.assertEqual(commented, {'M:Load': {'2': {}}})
        self.assertEqual(luadata.tables('function M:Nothing()\n    doSomething()\nend\n'), {})


class Fetch(unittest.TestCase):
    INDEX = {'products': {'wowf': {'1.60.1.70862': {'vendors': {'records': 2}, 'loot': {'records': 1}, 'game_rules': {'records': 9}},
                                   '1.60.1.70790': {'vendors': {'records': 1}}, '../../etc': {'vendors': {}}, '1.60.1.1': 'odd',
                                   '1.60.1.70900\n': {'vendors': {}}},
                          'wow_classic_beta': {'1.60.1.70009': {'vendors': {'records': 5}}}}}

    def setUp(self):
        self.asked, self.body = [], b'{"vendors": {}}'

    def fetch(self, url):
        self.asked.append(url.replace(f'https://raw.githubusercontent.com/JIVESCORP/eg-link-output-wowf/{COMMIT}/data/', ''))
        return json.dumps(self.INDEX).encode() if url.endswith('index.json') else self.body

    def test_only_forever_builds_and_the_datasets_read(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(facts.fetch_eglink(COMMIT, folder, self.fetch), 3)
            self.assertEqual(self.asked, ['index.json', 'wowf/1.60.1.70790/vendors.json', 'wowf/1.60.1.70862/vendors.json', 'wowf/1.60.1.70862/loot.json'])
            self.assertEqual(sorted(os.listdir(folder)), ['1.60.1.70790', '1.60.1.70862'])
            self.assertEqual(sorted(os.listdir(os.path.join(folder, '1.60.1.70862'))), ['loot.json', 'vendors.json'])
            self.asked = []
            self.assertEqual(facts.fetch_eglink(COMMIT, folder, self.fetch), 0)          # what is there is not asked again
            self.assertEqual(self.asked, ['index.json'])

    def test_a_download_cut_short_is_not_kept(self):
        self.body = b'{"vendors": {"74": {"entr'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(facts.SourceError):
                facts.fetch_eglink(COMMIT, folder, self.fetch)
            self.assertEqual([names for _root, _dirs, names in os.walk(folder) if names], [])

    def test_what_goes_wrong_on_the_way_is_one_kind_of_error(self):
        import http.client

        def unreachable(url):
            raise OSError('no route')

        def cut(url):
            raise http.client.IncompleteRead(b'')
        for broken in (unreachable, cut, lambda url: b'not json'):
            with tempfile.TemporaryDirectory() as folder, self.assertRaises(facts.SourceError):
                facts.fetch_eglink(COMMIT, folder, broken)
        with tempfile.TemporaryDirectory() as folder:                # an index that lists nothing downloads nothing
            self.assertEqual(facts.fetch_eglink(COMMIT, folder, lambda url: b'[1, 2]'), 0)

    def test_a_pin_that_is_not_a_commit_is_refused(self):
        for pin in ('main', '', None, 'a' * 39, '../' + 'a' * 37, 'a' * 40 + '\n'):
            with self.assertRaises(facts.SourceError):
                facts.fetch_eglink(pin, '/nonexistent', self.fetch)
        self.assertEqual(self.asked, [])


class Storing(unittest.TestCase):
    def test_check(self):
        good = Fact('sells', 'npc', 74, 1839, 70862, 2, {})
        self.assertIs(facts.check(good), good)
        for bad in (good._replace(kind='steals'), good._replace(subject_kind='player'), good._replace(subject=0), good._replace(object=-1),
                    good._replace(build=2 ** 32), good._replace(samples=True), good._replace(subject='74')):
            self.assertIsNone(facts.check(bad), bad)

    def test_sql_value(self):
        self.assertEqual(facts.sql_value(5), '5')
        self.assertEqual(facts.sql_value("a'b\\c\nd\re\0f"), "'a\\'b\\\\c\\nd\\re\\0f'")

    def write(self, rows, **more):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'world', 'facts.sql')
            counts = facts.write_sql(path, 'eglink', COMMIT, 'CC-BY-4.0', 'public', iter(rows), **more)
            with open(path, 'rb') as handle:
                return counts, handle.read().decode('ascii')         # nothing but ASCII reaches the server

    def test_the_file_replaces_the_source_in_one_transaction(self):
        rows = [Fact('sells', 'npc', 74, 1839, 70862, 2, {'costs': {'5': 184}}), Fact('steals', 'npc', 1, 1, 1, 1, {}),
                Fact('quest', 'quest', 91724, 0, 70862, 3, {'description': "It's a \\ é \U0001f600 \ud83d\r\nline"}), Fact('gives', 'npc', 240, 35, 70862, 3, {})]
        skipped = collections.Counter(loot=4)
        counts, text = self.write(rows, skipped=skipped, now="'2026-11-13 06:00:00'", batch=2)
        self.assertEqual(counts, {'sells': 1, 'quest': 1, 'gives': 1})
        self.assertTrue(text.startswith("SET NAMES utf8mb4;\nSET SESSION sql_mode = 'STRICT_ALL_TABLES';\nCREATE TABLE IF NOT EXISTS ft_world_facts"))
        self.assertLess(text.index('START TRANSACTION'), text.index("DELETE FROM ft_world_facts WHERE source = 'eglink'"))
        self.assertLess(text.index('DELETE FROM'), text.index('INSERT INTO ft_world_facts'))
        self.assertTrue(text.endswith('COMMIT;\n'))
        self.assertEqual(text.count('INSERT INTO ft_world_facts'), 2)          # two batches of at most two
        self.assertIn("('eglink', 'sells', 'npc', 74, 1839, 70862, 2, '{\"costs\":{\"5\":184}}')", text)
        # JSON's own escapes survive the SQL string; a quote cannot end it; a lone surrogate cannot stop the writing
        self.assertIn("It\\'s a \\\\\\\\ \\\\u00e9 \\\\ud83d\\\\ude00 \\\\ud83d\\\\r\\\\nline", text)
        self.assertNotIn('steals', text)
        self.assertIn("'public', (SELECT COUNT(*) FROM ft_world_facts WHERE source = 'eglink'), 5, '2026-11-13 06:00:00')", text)   # 4 unread + 1 unfit

    def test_what_the_reader_left_out_is_known_only_once_it_has_read(self):
        skipped = collections.Counter()

        def reading():
            yield Fact('sells', 'npc', 74, 1839, 70862, 2, {})
            skipped['vendors'] += 3
        _counts, text = self.write(reading(), skipped=skipped)
        self.assertIn("WHERE source = 'eglink'), 3, NOW());", text)


class Unescape(unittest.TestCase):
    """tools/ft/sqlio.py reads what the mysql client prints in batch mode."""
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        path = os.path.join(cls.folder.name, 'config.ini')
        with open(path, 'w') as handle:
            handle.write('[database]\nuser = "x"\npassword = "y"\n')
        cls.before = os.environ.get('FOREVER_TRACKER_CONFIG')
        if 'ft.sqlio' not in sys.modules:
            os.environ['FOREVER_TRACKER_CONFIG'] = os.environ.get('FT_TEST_CONFIG') or path
        from ft import sqlio
        cls.sqlio = sqlio

    @classmethod
    def tearDownClass(cls):
        if cls.before is None:
            os.environ.pop('FOREVER_TRACKER_CONFIG', None)
        cls.folder.cleanup()

    def test_one_pass(self):
        un = self.sqlio._unescape
        self.assertIsNone(un('NULL'))
        self.assertEqual(un('a\\tb\\nc\\0d\\\\e'), 'a\tb\nc\0d\\e')
        self.assertEqual(un('\\\\n'), '\\n')                      # an escaped backslash, then an n: not a line break
        self.assertEqual(un('{"t":"a\\\\r\\\\nb \\\\u00e9"}'), '{"t":"a\\r\\nb \\u00e9"}')
        self.assertEqual(un('odd\\q'), 'odd\\q')


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server')
class OnMySQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['FOREVER_TRACKER_CONFIG'] = os.environ['FT_TEST_CONFIG']
        from ft import sqlio
        from ft.config import CONFIG
        cls.db, cls.name = sqlio, CONFIG.db('tracker')
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.name}`;\nCREATE DATABASE `{cls.name}` CHARACTER SET utf8mb4;\n', 'information_schema')
        cls.folder = tempfile.TemporaryDirectory()
        tree(os.path.join(cls.folder.name, 'eg'), ('1.60.1.70790', '1.60.1.70862'))
        cls.path = os.path.join(cls.folder.name, 'facts.sql')

    @classmethod
    def tearDownClass(cls):
        cls.db.execute(f'DROP DATABASE IF EXISTS `{cls.name}`;\n', 'information_schema')
        cls.folder.cleanup()

    def load(self, rows, pin=COMMIT, skipped=None):
        counts = facts.write_sql(self.path, 'eglink', pin, 'CC-BY-4.0', 'public', rows, skipped)
        self.db.execute_file(self.path, 'tracker')
        return counts

    def test_load_read_back_and_replace(self):
        self.assertEqual(facts.summary(self.db), ([], []))
        everything = list(facts.eglink(os.path.join(self.folder.name, 'eg')))
        counts = self.load(everything, skipped=collections.Counter(loot=7))
        sources, kinds = facts.summary(self.db)
        self.assertEqual([s[:6] for s in sources], [('eglink', COMMIT, 'CC-BY-4.0', 'public', len(everything), 7)])
        self.assertEqual({k[1]: k[2] for k in kinds}, counts)
        self.assertEqual({k[1]: k[4:] for k in kinds}['sells'], (70790, 70862))
        stored = self.db.query("SELECT samples, data FROM ft_world_facts WHERE kind = 'quest' AND subject = 91724 AND build = 70862", 'tracker')
        self.assertEqual(stored[0]['samples'], '3')
        self.assertEqual(json.loads(stored[0]['data']), BUILD['quests.enUS']['quests']['91724'])        # text, quotes, line breaks, an emoji
        ways = self.db.query("SELECT data FROM ft_world_facts WHERE kind = 'drops' AND subject = 474 AND object = 2589 AND build = 70790", 'tracker')
        self.assertEqual(json.loads(ways[0]['data'])['ways']['quest|group']['kills'], 2)
        # what the client escapes comes back as it was stored: a backslash before an n is not a line break
        self.assertEqual(self.db.query("SELECT 'a\\\\nb' x, 'tab\\there' y, 'line\\nbreak' z, NULL n", 'tracker'),
                         [{'x': 'a\\nb', 'y': 'tab\there', 'z': 'line\nbreak', 'n': None}])
        # a second load replaces the source's facts, and another source's are left alone
        self.db.execute("INSERT INTO ft_world_facts (source, kind, subject_kind, subject, object, build, samples, data) VALUES "
                        "('other', 'sells', 'npc', 1, 2, 3, 4, '{}');", 'tracker')
        self.load([Fact('sells', 'npc', 74, 1839, 70862, 2, {}), Fact('sells', 'npc', 74, 1839, 70862, 5, {'again': True})], pin='b' * 40)
        rows = self.db.query('SELECT source, samples, data FROM ft_world_facts ORDER BY source', 'tracker')
        self.assertEqual(rows, [{'source': 'eglink', 'samples': '5', 'data': '{"again":true}'}, {'source': 'other', 'samples': '4', 'data': '{}'}])
        self.assertEqual(facts.summary(self.db)[0][0][:6], ('eglink', 'b' * 40, 'CC-BY-4.0', 'public', 1, 0))


if __name__ == '__main__':
    unittest.main()
