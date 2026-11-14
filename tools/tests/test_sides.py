"""python -m unittest discover -s tools/tests

Whose side a creature is on (ft.sides): the server's faction against how each side's players saw the creature on the
live game. The faction templates are the client's own rows for those ids. No database: the rows are given.
"""
import collections
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import sides  # noqa: E402
import tracker  # noqa: E402

Fact = collections.namedtuple('Fact', 'kind subject_kind subject object build samples data')


def template(faction, group, friends, enemies, enemy_ids=(), friend_ids=()):
    row = {'Faction': faction, 'FactionGroup': group, 'FriendGroup': friends, 'EnemyGroup': enemies}
    row.update({f'Enemies{i}': (list(enemy_ids) + [0] * 8)[i - 1] for i in range(1, 9)})
    row.update({f'Friend{i}': (list(friend_ids) + [0] * 8)[i - 1] for i in range(1, 9)})
    return row


# as the client has them: Stormwind, Orgrimmar, Friendly, Monster, Creature, Booty Bay
TEMPLATES = {11: template(72, 3, 2, 12), 85: template(76, 5, 4, 10), 35: template(31, 0, 1, 0), 14: template(14, 8, 0, 1),
             7: template(7, 0, 0, 0), 120: template(21, 0, 0, 0), 99: template(900, 0, 0, 0, enemy_ids=[2])}
def reputation(name, index, *entries):
    """A Faction row; entries: (race mask, base) for its four reputation entries."""
    row = {'Name': name, 'ReputationIndex': index}
    for i in range(1, 5):
        mask, base = (list(entries) + [(0, 0)] * 4)[i - 1]
        row.update({f'ReputationRaceMask{i}1': mask, f'ReputationRaceMask{i}2': 0, f'ReputationClassMask{i}': 0, f'ReputationBase{i}': base})
    return row


# Stormwind: the Alliance's races start friendly, the Horde's at the bottom. The Gelkis: everyone starts neutral.
FACTIONS = {72: reputation('Stormwind', 19, (1, 3100), (2, -42000)), 76: reputation('Orgrimmar', 14, (2, 3100), (1, -42000)),
            31: reputation('Friendly', -1), 14: reputation('Monster', -1), 21: reputation('Booty Bay', 1, (3, 500)),
            92: reputation('Gelkis Clan Centaur', 2, (3, 2000)), 893: reputation('Revantusk Trolls', -1), 900: reputation('Sky Elf Camp', -1)}
TEMPLATES.update({132: template(92, 8, 0, 1), 1494: template(893, 4, 4, 2)})


def live(**entries):
    """recorded() for hand-made sightings: live(n1={'Alliance': [5]}, ...); 'served' as {'Horde': ['Merchant']}."""
    out = {}
    for key, told in entries.items():
        out[int(key[1:])] = {'name': '', 'seen': {side: set(told.get(side, [])) for side in sides.SIDES},
                             'served': {side: set(told.get('served', {}).get(side, [])) for side in sides.SIDES}}
    return out


def npc(faction, name='Somebody', npcflag=0):
    return {'name': name, 'faction': str(faction), 'npcflag': str(npcflag)}


def found(told, creatures, shown=None):
    rows, _counts = sides.compare(told, creatures, TEMPLATES, FACTIONS, shown)
    return [(entry, issue) for entry, _name, issue, _note in rows]


class Stance(unittest.TestCase):
    def test_the_factions_everybody_knows(self):
        self.assertEqual([sides.stance(TEMPLATES[t], side) for t in (11, 85, 35, 14, 7) for side in sides.SIDES],
                         ['friendly', 'hostile', 'hostile', 'friendly', 'friendly', 'friendly', 'hostile', 'hostile', 'neutral', 'neutral'])

    def test_a_faction_named_as_an_enemy(self):
        self.assertEqual((sides.stance(TEMPLATES[99], 'Horde'), sides.stance(TEMPLATES[99], 'Alliance')), ('hostile', 'neutral'))
        self.assertIsNone(sides.stance(None, 'Horde'))


class Recorded(unittest.TestCase):
    def test_reactions_and_services_of_the_live_game_only(self):
        facts = [Fact('seen', 'npc', 54, 0, 70938, 3, {'name': 'Corina Steele', 'reactions': {'Alliance': [5], 'Horde': 'x'}}),
                 Fact('seen', 'npc', 54, 0, 70888, 1, {'reactions': {'Alliance': [6, 99, True]}}),
                 Fact('seen', 'npc', 54, 0, 70532, 1, {'reactions': {'Horde': [1]}}),            # before the live game
                 Fact('talked', 'npc', 54, 0, 70938, 2, {'side': 'Alliance', 'interactions': ['Merchant']}),
                 Fact('talked', 'object', 60, 0, 70938, 2, {'side': 'Horde'})]
        told = sides.recorded(facts, 70755)
        self.assertEqual(list(told), [54])
        self.assertEqual((told[54]['name'], told[54]['seen'], told[54]['served']),
                         ('Corina Steele', {'Alliance': {5, 6}, 'Horde': set()}, {'Alliance': {'Merchant', 'talked'}, 'Horde': set()}))


class Faction(unittest.TestCase):
    def test_a_creature_that_attacks_the_players_it_served(self):
        # a Horde quest giver of the new starting zone, given the Alliance's generic faction on the server
        told = live(n1={'Horde': [5], 'served': {'Horde': ['QuestGiver']}})
        rows, _ = sides.compare(told, {1: npc(11, 'Camp Elder')}, TEMPLATES, FACTIONS)
        self.assertEqual([(r[0], r[2]) for r in rows], [(1, 'faction')])
        self.assertIn('Horde players saw it friendly and were served by it (QuestGiver) on live; on the server its faction 11 (Stormwind) attacks them', rows[0][3])

    def test_a_monster_that_is_everybodys_friend_on_the_server(self):
        self.assertEqual(found(live(n2={'Alliance': [2], 'Horde': [1, 2]}), {2: npc(35)}), [(2, 'faction')])

    def test_a_pet_and_a_summoned_demon_are_nobodys_finding(self):
        told = live(n1={'Horde': [5]}, n2={'Horde': [5]}, n3={'Horde': [5], 'served': {'Horde': ['QuestGiver']}})
        wolf, imp, friend = dict(npc(14), type='1'), dict(npc(14), spawned='0'), dict(npc(14), type='1')
        rows, counts = sides.compare(told, {1: wolf, 2: imp, 3: friend}, TEMPLATES, FACTIONS)
        self.assertEqual([(r[0], r[2]) for r in rows], [(3, 'faction')])   # a beast that gives a quest is no pet
        self.assertEqual(counts.get('not_spawned'), 1)

    def test_a_reputation_players_earn_says_nothing(self):
        # the Gelkis attack by default and befriend whoever earned it: one player's friendly centaur is no finding
        told = live(n1={'Horde': [5]}, n2={'Horde': [1]}, n3={'Alliance': [5, 6], 'Horde': [5]})
        rows, counts = sides.compare(told, {1: npc(132), 2: npc(120), 3: npc(11)}, TEMPLATES, FACTIONS)
        # ... but the Horde's standing with Stormwind is fixed at the bottom: a Stormwind NPC friendly to them is one
        self.assertEqual([(r[0], r[2]) for r in rows], [(3, 'faction')])
        self.assertEqual(counts.get('reputation_decides'), 2)
        self.assertEqual((sides.standing(FACTIONS[72], 'Horde'), sides.standing(FACTIONS[72], 'Alliance'), sides.standing(FACTIONS[31], 'Horde'),
                          sides.standing(FACTIONS[92], 'Horde')), (-42000, 3100, None, 2000))

    def test_what_agrees_is_not_listed(self):
        told = live(n1={'Alliance': [5, 6], 'Horde': [1]}, n2={'Alliance': [2]}, n3={'Horde': [4]}, n4={'Alliance': [5]})
        self.assertEqual(found(told, {1: npc(11), 2: npc(14), 3: npc(7), 4: npc(35)}), [])

    def test_neutral_against_friendly_is_no_contradiction(self):
        # it depends on the reputation the player who recorded it had earned
        self.assertEqual(found(live(n1={'Alliance': [4, 5], 'Horde': [6]}), {1: npc(120)}), [])
        self.assertEqual(found(live(n1={'Alliance': [3]}), {1: npc(35)}), [])   # unfriendly is not hostile

    def test_a_side_that_never_saw_it_says_nothing(self):
        self.assertEqual(found(live(n1={'Alliance': [5]}), {1: npc(11)}), [])   # hostile to the Horde on the server: nobody says otherwise

    def test_a_creature_or_a_faction_the_server_lacks(self):
        rows, counts = sides.compare(live(n1={'Horde': [5]}, n2={'Horde': [5]}), {2: npc(4242)}, TEMPLATES, FACTIONS)
        self.assertEqual((rows, counts), ([], {'compared': 1, 'no_template': 1}))


class ShownToOneSide(unittest.TestCase):
    def condition(self, team, group=0, negative=0, kind=6):
        return {'ElseGroup': str(group), 'ConditionTypeOrReference': str(kind), 'ConditionValue1': str(team), 'NegativeCondition': str(negative)}

    def test_the_side_a_set_of_conditions_lets_through(self):
        self.assertEqual(sides.team_of([self.condition(469)]), 'Alliance')
        self.assertEqual(sides.team_of([self.condition(469, negative=1)]), 'Horde')
        self.assertEqual(sides.team_of([self.condition(67, 0), self.condition(67, 1)]), 'Horde')
        self.assertIsNone(sides.team_of([self.condition(67, 0), self.condition(469, 1)]))             # either side, by two ways
        self.assertIsNone(sides.team_of([self.condition(67, 0), self.condition(8, 1, kind=8)]))       # a way that asks for no team
        self.assertIsNone(sides.team_of([]))

    def test_a_creature_with_a_spawn_anyone_sees_is_shown_to_everyone(self):
        phases = {170: 'Horde', ('group', 9): 'Alliance'}
        self.assertEqual(sides.shown_to([(170, 0, 0), (170, 0, 0)], phases, {}), 'Horde')
        self.assertEqual(sides.shown_to([(0, 9, 0)], phases, {}), 'Alliance')
        self.assertEqual(sides.shown_to([(0, 0, 44)], phases, {44: 'Horde'}), 'Horde')
        self.assertIsNone(sides.shown_to([(170, 0, 0), (0, 0, 0)], phases, {}))
        self.assertIsNone(sides.shown_to([(170, 0, 0), (0, 9, 0)], phases, {}))    # a spawn for each side
        self.assertEqual(sides.shown_to([(0, 0, 0)], phases, {}, 'Alliance'), 'Alliance')   # a condition on the creature itself

    def test_the_other_side_saw_it_on_live(self):
        told = live(n1={'Alliance': [5], 'Horde': [5]}, n2={'Horde': [5]}, n3={'served': {'Alliance': ['QuestGiver']}})
        creatures = {1: npc(35), 2: npc(35), 3: npc(35)}
        self.assertEqual(found(told, creatures, {1: 'Horde', 2: 'Horde', 3: 'Horde'}), [(1, 'sides'), (3, 'sides')])


class Discount(unittest.TestCase):
    def test_a_one_sided_vendor_whose_faction_has_no_reputation(self):
        told = live(n1={'Alliance': [5], 'served': {'Alliance': ['Merchant']}}, n2={'served': {'Alliance': ['Merchant']}},
                    n3={'served': {'Alliance': ['Merchant'], 'Horde': ['Merchant']}}, n4={'served': {'Alliance': ['QuestGiver']}})
        told.update(live(n5={'served': {'Horde': ['Merchant']}}))
        creatures = {1: npc(35, npcflag=128), 2: npc(11, npcflag=128), 3: npc(35, npcflag=128), 4: npc(35, npcflag=2), 5: npc(1494, npcflag=128)}
        rows, _ = sides.compare(told, creatures, TEMPLATES, FACTIONS)
        # 2 has Stormwind's reputation, 3 sells to both, 4 sells nothing, 5 is of a side's own faction that has no reputation on live either
        self.assertEqual([(r[0], r[2]) for r in rows], [(1, 'discount')])
        self.assertIn('faction 35 (Friendly) on the server is a general one without a reputation', rows[0][3])
        self.assertEqual(sides.compare(told, creatures, TEMPLATES)[0], [])   # without the faction table the check is not made


class Rows(unittest.TestCase):
    def test_one_row_per_creature(self):
        level = (639, 'Edwin VanCleef', 21, 21, 2, 22, 23, 1, 'Humanoid', 'rank', '')
        merged = tracker.merge_checks([level], [(639, 'Edwin VanCleef', 'faction', 'A'), (639, 'Edwin VanCleef', 'sides', 'B'), (54, 'Corina Steele', 'discount', 'C')])
        self.assertEqual(merged, [(54, 'Corina Steele', None, None, 0, None, None, 0, '', 'discount', 'C.'),
                                  (639, 'Edwin VanCleef', 21, 21, 2, 22, 23, 1, 'Humanoid', 'rank,faction,sides', 'A. B.')])
        self.assertEqual(tracker.merge_checks([level], []), [level])


if __name__ == '__main__':
    unittest.main()
