"""python -m unittest discover -s tools/tests"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import facts, questie  # noqa: E402

NPC_TRACES = """local ForeverNpcTraces = QuestieLoader:CreateModule("ForeverNpcTraces")
function ForeverNpcTraces:Load()
    local npcKeys = QuestieDB.npcKeys
    return {
        [6] = {
            [npcKeys.spawns] = {[12]={{41.5,62.25},{43,60}},[1519]={{-1,-1}}},
            [npcKeys.zoneID] = 12,
        },
        [7] = {
            [npcKeys.questStarts_add] = {33},
        },
    }
end
"""
NPC_FIXES = """local ForeverNPCFixes = QuestieLoader:CreateModule("ForeverNPCFixes")
function ForeverNPCFixes:Load()
    local npcKeys = QuestieDB.npcKeys
    return {
        [8] = {
            [npcKeys.spawns] = {{{10,20}}},
        },
        [219] = {
            [npcKeys.spawns] = {[zoneIDs.ARATHI_HIGHLANDS] = {{27,57.2}}, [zoneIDs.NOWHERE] = {{1,1}}},
        },
    }
end
"""
OBJECT_TRACES = """local ForeverObjectTraces = QuestieLoader:CreateModule("ForeverObjectTraces")
function ForeverObjectTraces:Load()
    local objectKeys = QuestieDB.objectKeys
    return {
        [35] = {
            [objectKeys.spawns] = {[12]={{50,50}}},
        },
    }
end
"""


class QuestieSpawns(unittest.TestCase):
    def test_trace_and_fix_points_by_kind(self):
        with tempfile.TemporaryDirectory() as folder:
            for path, body in ((f'{facts.QUESTIE_FOLDER}/traces/foreverNpcTraces.lua', NPC_TRACES),
                               (f'{facts.QUESTIE_FOLDER}/foreverNPCFixes.lua', NPC_FIXES),
                               (f'{facts.QUESTIE_FOLDER}/traces/foreverObjectTraces.lua', OBJECT_TRACES),
                               (f'{facts.QUESTIE_FOLDER}/generated/foreverBaseNpc.lua', NPC_TRACES.replace('[6]', '[9]')),
                               (questie.ZONES, 'constants.zoneIDs = {\n  -- Eastern Kingdoms\n  DUN_MOROGH = 1,\n  ARATHI_HIGHLANDS = 45,\n}\n')):
                os.makedirs(os.path.dirname(os.path.join(folder, path)), exist_ok=True)
                with open(os.path.join(folder, path), 'w', encoding='utf-8') as handle:
                    handle.write(body)
            found = questie.spawns(folder)
        # the instance mark (-1, -1) is no place; an NPC without spawns is left out
        self.assertEqual(found[('npc', 6)], {'trace': [(12, 41.5, 62.25), (12, 43.0, 60.0)]})
        self.assertNotIn(('npc', 7), found)
        # a table whose only zone is 1 reads as a list: zone 1
        self.assertEqual(found[('npc', 8)], {'fix': [(1, 10.0, 20.0)]})
        # a zone named in a hand fix is looked up in QuestieDB's zones.lua; one it does not name is left out
        self.assertEqual(found[('npc', 219)], {'fix': [(45, 27.0, 57.2)]})
        self.assertEqual(found[('go', 35)], {'trace': [(12, 50.0, 50.0)]})
        # the generated part is built from Wowhead's pages: not read
        self.assertNotIn(('npc', 9), found)

    def test_no_folder_no_spawns(self):
        self.assertEqual(questie.spawns(None), {})

    def test_quest_relation_traces_are_read(self):
        self.assertEqual(facts.QUESTIE_FILES[f'{facts.QUESTIE_FOLDER}/traces/foreverQuestRelationTraces.lua'], ('quest', 'trace'))


if __name__ == '__main__':
    unittest.main()
