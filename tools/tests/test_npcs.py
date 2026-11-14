"""python -m unittest discover -s tools/tests"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import npcs  # noqa: E402

# a record as EG Link keeps it: what the client's creature cache holds
RECORD = {'name': 'Ormok', 'title': 'Rogue Trainer', 'cursor': 'trainer', 'classification': 1, 'type': 7, 'family': 0, 'unitClass': 4, 'movementInfoId': 1693,
          'creatureDifficultyId': 3328, 'flags': [134217728, 2, 0], 'hpMultiplier': 1.25, 'energyMultiplier': 1.0, 'proxyCreatureIds': [1746],
          'displays': [{'displayId': 1328, 'probability': 100.0, 'scale': 1.0}, {'displayId': 1329, 'probability': 50.0, 'scale': 0.9}],
          'totalProbability': 150.0, 'sources': 2, 'questItems': [5, 6]}


class Side(unittest.TestCase):
    def test_a_list_s_word_alone_is_not_enough(self):
        self.assertEqual(npcs.side('AH', None), ('', 'only a list says whom it is friendly to: no player was seen talking to it'))
        self.assertEqual(npcs.side('A', {'Horde': [4]})[0], '')
        self.assertEqual(npcs.side(None, None), ('', 'nothing states whom it is friendly to'))
        self.assertEqual(npcs.side('AH', {'Horde': [2]}), ('', 'it is not friendly to players: what a monster needs is not known'))

    def test_a_player_talked_to_it(self):
        self.assertEqual(npcs.side(None, None, 'Horde'), ('H', 'talked'))                    # the recording gives its side
        self.assertEqual(npcs.side('AH', None, 'Alliance'), ('A', 'talked'))                 # and that comes before a list
        self.assertEqual(npcs.side('AH', None, ''), ('AH', 'questie'))                       # no side recorded: the list names it
        self.assertEqual(npcs.side(None, {'Horde': [5]}, ''), ('H', 'reactions'))            # or the side that saw it friendly
        self.assertEqual(npcs.side(None, {'Horde': [4]}, ''), ('', 'players talked to it, but nothing states whose side it is on'))
        for unreadable in (None, 'B', {}, ['A'], 5):
            self.assertEqual(npcs.side(unreadable, None, ''), ('', 'players talked to it, but nothing states whose side it is on'), unreadable)
        # a side whose players saw it below neutral is never part of it, whoever says so
        self.assertEqual(npcs.side('AH', {'Horde': [2]}, ''), ('', 'sources disagree about whom it is friendly to'))
        self.assertEqual(npcs.side(None, {'Horde': [5, 3]}, 'Horde'), ('', 'sources disagree about whom it is friendly to'))
        self.assertEqual(npcs.side('AH', None, '', against=['A']), ('', 'sources disagree about whom it is friendly to'))
        self.assertEqual(npcs.side(None, {'Alliance': [2]}, 'Horde'), ('H', 'talked'))       # hostile to the other side: as an NPC of one side is

    def test_from_what_players_of_each_side_saw(self):
        self.assertEqual(npcs.side(None, {'Horde': [5, 6], 'Alliance': [5]}), ('AH', 'reactions'))
        self.assertEqual(npcs.side(None, {'Horde': [5], 'Alliance': [2]}), ('H', 'reactions'))
        self.assertEqual(npcs.side(None, {'Alliance': [5, 5]}), ('A', 'reactions'))                         # the other side never saw it: not said to be its friend
        self.assertEqual(npcs.side(None, {'Alliance': [4, 5]}), ('A', 'reactions'))
        # neutral alone says nothing (a deer is neutral), and friendly to one side is no word about the other
        self.assertEqual(npcs.side(None, {'Horde': [4, 4, 4]}), ('', 'nothing states whom it is friendly to'))
        self.assertEqual(npcs.side(None, {'Horde': [5], 'Alliance': [4]}), ('H', 'reactions'))
        self.assertEqual(npcs.side(None, {'Horde': [5, 3]}), ('', 'it is not friendly to players: what a monster needs is not known'))      # seen hostile once
        self.assertEqual(npcs.side(None, {'Horde': [5]}, against=['H']), ('', 'it is not friendly to players: what a monster needs is not known'))
        self.assertEqual(npcs.side(None, {'Horde': [2], 'Alliance': [1]})[0], '')
        for nothing in (None, {}, {'Neutral': [5]}, {'Horde': []}, {'Horde': [9]}, {'Horde': 'friendly'}, [5]):
            self.assertEqual(npcs.side(None, nothing), ('', 'nothing states whom it is friendly to'), nothing)

    def test_what_players_fought_is_no_friend(self):
        for more in ({}, {'talked': 'Horde'}, {'talked': ''}):
            self.assertEqual(npcs.side('AH', {'Horde': [8], 'Alliance': [8]}, fought=True, **more), ('', 'players fought it: what a monster needs is not known'))


class Rows(unittest.TestCase):
    def test_a_record_s_rows(self):
        npc, problems = npcs.rows(3328, RECORD, (30, 31), 'H')
        self.assertEqual(problems, [])
        self.assertEqual(list(npc.template.items()), [
            ('entry', 3328), ('KillCredit1', 1746), ('KillCredit2', 0), ('name', 'Ormok'), ('subname', 'Rogue Trainer'), ('IconName', 'trainer'), ('faction', 83),
            ('Classification', 1), ('type', 7), ('family', 0), ('movementId', 1693), ('unit_class', 4), ('BaseAttackTime', 2000), ('RangeAttackTime', 2000),
            ('unit_flags2', 2048)])
        self.assertEqual(list(npc.difficulty.values()), [3328, 0, 1.25, 1.0, 3328, 134217728, 2, 0])
        self.assertEqual([tuple(model.values()) for model in npc.models], [(3328, 0, 1328, 1.0, 100.0), (3328, 1, 1329, 0.9, 50.0)])
        self.assertEqual((npc.level, npc.unread), ((30, 31), ['questItems']))                 # carried, not written: named
        self.assertEqual([npcs.rows(1, RECORD, (1, 1), side)[0].template['faction'] for side in ('A', 'H', 'AH')], [84, 83, 35])

    def test_every_row_names_the_same_columns(self):
        bare, problems = npcs.rows(5, {'name': 'Bare', 'classification': 0, 'type': 7, 'unitClass': 1, 'displays': [{'displayId': 7}]}, (1, 1), 'AH')
        self.assertEqual(problems, [])
        self.assertEqual(list(bare.template), list(npcs.rows(3328, RECORD, (30, 31), 'H')[0].template))
        self.assertEqual((bare.template['subname'], bare.template['IconName'], bare.template['KillCredit1'], bare.template['movementId']), (None, None, 0, 0))
        self.assertEqual((list(bare.difficulty.values()), [tuple(m.values()) for m in bare.models]), ([5, 0, 1, 1, 0, 0, 0, 0], [(5, 0, 7, 1, 1)]))

    def test_a_record_that_cannot_be_written_says_why(self):
        def broken(level=(30, 30), side='H', **changes):
            record = copy.deepcopy(RECORD)
            for key, value in changes.items():
                if value is None:
                    record.pop(key, None)
                else:
                    record[key] = value
            return npcs.rows(1, record, level, side)[1]
        self.assertEqual(npcs.rows(1, None, (1, 1), 'A'), (None, ['its record is not a record']))
        self.assertEqual(broken(name=' '), ['it has no name the file can hold'])
        self.assertEqual(broken(name='half \ud83d'), ['it has no name the file can hold'])
        self.assertEqual(broken(title=5), ['title is not text the file can hold'])
        self.assertEqual(broken(unitClass=3), ['unitClass is not a class a creature can have'])
        self.assertEqual(broken(unitClass=True), ['unitClass is not a class a creature can have'])
        self.assertEqual(broken(unitClass=1.0), ['unitClass is not a class a creature can have'])
        self.assertEqual(broken(cursor='x' * 65), ['cursor is longer than the column'])
        self.assertEqual(broken(type=300), ['type is not a number the column takes'])
        self.assertEqual(broken(flags=[1, 2]), ['flags is not three numbers'])
        self.assertEqual(broken(hpMultiplier=-1), ['hpMultiplier, energyMultiplier or creatureDifficultyId is not a number the columns take'])
        self.assertEqual(broken(hpMultiplier=float('nan')), ['hpMultiplier, energyMultiplier or creatureDifficultyId is not a number the columns take'])
        self.assertEqual(broken(displays=[]), ['it has no model'])
        self.assertEqual(broken(displays=None), ['it has no model'])
        self.assertEqual(broken(displays=[{'displayId': 5, 'scale': 0}]), ['a model has no display id, or a scale or probability the columns do not take'])
        self.assertEqual(broken(proxyCreatureIds=[1, 2, 3]), ['proxyCreatureIds is not one or two creatures'])
        self.assertEqual(broken(side='N'), ['its side is not one of A, H, AH'])
        for level in (None, (0, 5), (6, 5), (1, 300), (1,), ('1', '2'), (True, 2)):
            self.assertEqual(broken(level=level), ['its level is not a range from 1 to 255'], level)


if __name__ == '__main__':
    unittest.main()
