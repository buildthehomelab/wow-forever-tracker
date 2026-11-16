"""python -m unittest discover -s tools/tests

The original game's database as the last source asked (tools/classicdb_pack.py, ft.classic): what its dump becomes in a
pack, and what a pack says about the recipes nobody can learn on the realm.
"""
import gzip
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import classicdb_pack  # noqa: E402
from ft import classic  # noqa: E402

DUMP = r"""
CREATE TABLE `creature_template` (
  `Entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `Name` char(100) NOT NULL DEFAULT '',
  `GossipMenuId` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `TrainerTemplateId` mediumint(8) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`Entry`)
) ENGINE=MyISAM;
INSERT INTO `creature_template` VALUES (12939,'Doctor Gustaf VanHowzen',5381,0),(8696,'Henry Stern',1443,0),(14338,'Knot Thimblejack',5667,0),(2836,'Brikk Keencraft',0,77),(16365,'Master Craftsman Omarion',7213,0),(5,'It\'s a \'name\', (with) brackets',0,0);
CREATE TABLE `npc_trainer` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spell` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spellcost` int(10) unsigned NOT NULL DEFAULT '0',
  `reqskill` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqskillvalue` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqlevel` tinyint(3) unsigned NOT NULL DEFAULT '0',
  UNIQUE KEY `entry_spell` (`entry`,`spell`)
) ENGINE=MyISAM;
INSERT INTO `npc_trainer` VALUES (12939,10843,100000,129,240,0),(12939,18631,125000,129,260,35),(999999,1,1,1,1,1);
CREATE TABLE `npc_trainer_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spell` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `spellcost` int(10) unsigned NOT NULL DEFAULT '0',
  `reqskill` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqskillvalue` smallint(5) unsigned NOT NULL DEFAULT '0',
  `reqlevel` tinyint(3) unsigned NOT NULL DEFAULT '0'
) ENGINE=MyISAM;
INSERT INTO `npc_trainer_template` VALUES (77,2020,10,164,0,5),(78,2021,10,164,0,5);
CREATE TABLE `quest_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `Title` text,
  `RewSpell` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `RewSpellCast` mediumint(8) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`entry`)
) ENGINE=MyISAM;
INSERT INTO `quest_template` VALUES (2203,'Badlands Reagent Run II',11452,11453),(2771,'A Good Head On Your Shoulders',9980,11203),(2,'No spell',0,0),(7647,'Judgment and Redemption',23214,0);
CREATE TABLE `gossip_menu_option` (
  `menu_id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `id` smallint(5) unsigned NOT NULL DEFAULT '0',
  `option_text` text,
  `action_menu_id` mediumint(8) NOT NULL DEFAULT '0',
  `action_script_id` mediumint(8) unsigned NOT NULL DEFAULT '0'
) ENGINE=MyISAM;
INSERT INTO `gossip_menu_option` VALUES (5667,0,'Please teach me how to make a Gordok Ogre Suit.',0,566701),(7213,0,'Tailoring',7214,0),(7214,0,'Glacial Gloves.',-1,244012),(7214,1,'Back',7213,0),(1443,0,'Tea?',0,144300);
CREATE TABLE `dbscripts_on_gossip` (
  `id` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `delay` int(10) unsigned NOT NULL DEFAULT '0',
  `command` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `datalong` mediumint(8) unsigned NOT NULL DEFAULT '0'
) ENGINE=MyISAM;
INSERT INTO `dbscripts_on_gossip` VALUES (566701,0,15,22814),(566701,0,0,2000000001),(244012,0,15,28212),(144300,0,15,13029),(5,0,15,7);
CREATE TABLE `db_version` (
  `version` varchar(120) DEFAULT NULL
) ENGINE=MyISAM;
INSERT INTO `db_version` VALUES ('Classic DB test dump');
CREATE TABLE `unrelated` (
  `entry` int
) ENGINE=MyISAM;
INSERT INTO `unrelated` VALUES (1),(2);
"""


def made():
    return classicdb_pack.pack(classicdb_pack.read(DUMP.splitlines(keepends=True)), today='2026-11-14')


class Pack(unittest.TestCase):
    def test_trainers_their_own_lines_and_a_shared_list(self):
        pack = made()
        self.assertEqual([tuple(t) for t in pack['trainers']], [(2836, 2020, 10, 164, 0, 5), (12939, 10843, 100000, 129, 240, 0), (12939, 18631, 125000, 129, 260, 35)])

    def test_quests_that_show_or_cast_a_spell(self):
        self.assertEqual([tuple(q) for q in made()['quests']], [(2203, 11452, 11453), (2771, 9980, 11203), (7647, 23214, 0)])

    def test_a_conversation_is_followed_through_its_menus(self):
        # Omarion's first menu only leads to the tailoring one, which goes back to the first: no loop, the cast is found
        self.assertEqual([tuple(g) for g in made()['gossip']], [(8696, 13029), (14338, 22814), (16365, 28212)])

    def test_names_only_of_what_it_mentions(self):
        pack = made()
        self.assertEqual(pack['npc_names']['14338'], 'Knot Thimblejack')
        self.assertNotIn('5', pack['npc_names'])
        self.assertEqual(pack['quest_names'], {'2203': 'Badlands Reagent Run II', '2771': 'A Good Head On Your Shoulders', '7647': 'Judgment and Redemption'})
        self.assertEqual((pack['version'], pack['made'], pack['licence']), ('Classic DB test dump', '2026-11-14', 'GPL-3.0'))

    def test_quotes_and_brackets_inside_a_name(self):
        rows = classicdb_pack.read(DUMP.splitlines(keepends=True))['creature_template']
        self.assertEqual(rows[-1]['Name'], "It's a 'name', (with) brackets")

    def test_the_file_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = os.path.join(folder, 'dump.sql.gz'), os.path.join(folder, 'out.cdbpack')
            with gzip.open(source, 'wt', encoding='utf-8') as handle:
                handle.write(DUMP)
            classicdb_pack.main(['classicdb_pack.py', source, target])
            self.assertEqual(classic.load(target)['gossip'], [[8696, 13029], [14338, 22814], [16365, 28212]])
            with gzip.open(target, 'wt', encoding='utf-8') as handle:
                json.dump({'format': 1, 'trainers': [[1, 2, 3]], 'quests': [], 'gossip': []}, handle)
            self.assertRaises(ValueError, classic.load, target)
            with gzip.open(target, 'wt', encoding='utf-8') as handle:
                json.dump({'format': 99}, handle)
            self.assertRaises(ValueError, classic.load, target)


class Evidence(unittest.TestCase):
    """The realm's learn effects say which recipe Classic's teaching spell is."""

    PACK = {'trainers': [[12939, 10843, 100000, 129, 240, 0], [12920, 10843, 100000, 129, 240, 0], [8696, 13029, 0, 0, 175, 0], [1, 555, 5, 0, 0, 10]],
            'quests': [[2203, 11452, 11453], [2501, 11452, 11453], [2771, 9980, 11203], [7647, 23214, 0]],
            'gossip': [[8696, 13029], [14338, 22814]]}
    TEACHERS = {10841: {10843}, 13028: {13029}, 11452: {11453}, 22813: {22814}, 9980: {11203}}

    def found(self, wanted, quests=None):
        return classic.evidence(self.PACK, wanted, self.TEACHERS, quests if quests is not None else {})

    def test_a_trainer_line_for_each_creature_that_teaches_it(self):
        found = self.found({10841: 129})
        self.assertEqual(found['train'], [[12920, 10841, 100000, 0, 129, 240, [], 1], [12939, 10841, 100000, 0, 129, 240, [], 1]])
        self.assertEqual((found['changes'], found['gossip'], found['left']), ([], [], {}))

    def test_the_skill_line_is_the_realms_when_classic_names_none(self):
        found = self.found({13028: 185})
        self.assertEqual(found['train'], [[8696, 13028, 0, 0, 185, 175, [], 1]])
        self.assertEqual(found['gossip'], [])   # Henry Stern also says it in a conversation: the trainer line is enough

    def test_a_quest_that_casts_nothing_on_the_realm_gets_classics_spell(self):
        found = self.found({11452: 171, 9980: 164}, {2203: 0, 2501: 0, 2771: 11203})
        self.assertEqual(found['changes'], [{'table': 'quest_template', 'columns': ['ID', 'RewardSpell'], 'match': ['ID'], 'set': 'RewardSpell',
                                             'rows': [[2203, 11453], [2501, 11453]]}])
        self.assertEqual(found['left'], {'classic_quest_casts_already': 1})

    def test_a_quest_the_realm_does_not_have(self):
        self.assertEqual(self.found({11452: 171}, {2203: 0})['left'], {'classic_quest_unknown': 1})

    def test_taught_in_a_conversation_is_counted_not_written(self):
        found = self.found({22813: 197})
        self.assertEqual((found['train'], found['changes'], found['gossip'], found['left']), ([], [], [(14338, 22813)], {'classic_conversation': 1}))

    def test_what_classic_does_not_know(self):
        self.assertEqual(self.found({1263078: 171})['left'], {'classic_silent': 1})

    def test_what_forever_took_away_is_not_asked(self):
        # the old healing potions: 2337 is gone from the server's spells, 3447 is there but every skill line says "never
        # learned"; Goldthorn Tea is learned the usual way, and a spell listed twice is kept when one line teaches it
        gaps = {2337: 171, 3447: 171, 13028: 185, 7181: 171}
        left = classic.askable(gaps, known={3447, 13028, 7181}, acquire={2337: {3}, 3447: {3}, 13028: {0}, 7181: {0, 3}})
        self.assertEqual(left, {13028: 185, 7181: 171})
        self.assertEqual(classic.askable(gaps, known=set(), acquire={}), {})
        self.assertEqual(classic.askable({13028: 185}, known={13028}, acquire={}), {13028: 185})   # no skill row read: asked

    def test_only_what_was_asked(self):
        self.assertEqual(self.found({}), {'train': [], 'changes': [], 'gossip': [], 'talk': [], 'left': {}})


class Conversations(unittest.TestCase):
    """The lines of a conversation that cast a spell, with Classic's conditions carried over as plain terms."""

    COND = [  # condition_entry, type, value1, value2, flags
        (1, 7, 197, 300), (2, 5, 529, 6), (3, -1, 2, 1), (4, 5, 529, 7), (5, 17, 28208, 1), (6, -1, 4, 5), (7, 17, 28205, 1),
        (8, 8, 5518, 0), (9, 7, 197, 275), (10, -1, 9, 11), (11, -1, 8, 12), (12, 17, 22813, 1),
        (13, 15, 40, 1), (14, 23, 18250, 1), (15, -2, 1, 9), (16, -3, 8, 0), (17, -3, 18, 0), (18, 17, 7, 0), (19, 15, 40, 0)]

    def tables(self, options, creatures=(), objects=()):
        conditions = [{'condition_entry': c[0], 'type': c[1], 'value1': c[2], 'value2': c[3], 'flags': 0} for c in self.COND]
        conditions.append({'condition_entry': 20, 'type': 7, 'value1': 197, 'value2': 1, 'flags': 1})
        return {'conditions': conditions, 'gameobject_template': list(objects),
                'gossip_menu_option': [{'menu_id': m, 'id': i, 'option_text': t, 'action_menu_id': a, 'action_script_id': sc, 'condition_id': c}
                                       for m, i, t, a, sc, c in options]}, {e: {'Entry': e, 'GossipMenuId': menu} for e, menu in creatures}

    def test_the_conditions_on_the_way_are_kept(self):
        # Omarion: the tailor line (Revered and skill 300) leads to the menu of recipes; the cloak also needs Exalted
        tables, creatures = self.tables([(24404, 3, 'I am a master tailor, Omarion.', 24401, 0, 3),
                                         (24401, 1, 'Glacial Cloak.', 24401, 244011, 6), (24401, 2, 'Glacial Gloves.', 24401, 244012, 7)],
                                        creatures=[(16365, 24404)])
        lines, dropped = classicdb_pack.conversations(tables, creatures, {244011: {28263}, 244012: {28261}})
        self.assertEqual(lines, [['npc', 16365, 'Glacial Cloak.', 28263, [['rep', 529, 6], ['skill', 197, 300], ['rep', 529, 7], ['lacks', 28208]]],
                                 ['npc', 16365, 'Glacial Gloves.', 28261, [['rep', 529, 6], ['skill', 197, 300], ['lacks', 28205]]]])
        self.assertEqual(dropped, 0)

    def test_an_object_that_gives_quests_has_its_menu_in_data3(self):
        tables, creatures = self.tables([(6799, 0, ' Decipher the pattern and learn its content.', -1, 6799, 0)],
                                        objects=[{'entry': 180794, 'type': 2, 'data3': 6799}, {'entry': 142344, 'type': 3, 'data3': 6799}])
        lines, _ = classicdb_pack.conversations(tables, creatures, {6799: {26095}})
        self.assertEqual(lines, [['go', 180794, 'Decipher the pattern and learn its content.', 26095, []]])   # a chest is no conversation

    def test_what_is_carried_over(self):
        terms = lambda entry: classicdb_pack.terms(entry, {c['condition_entry']: c for c in self.tables([])[0]['conditions']})
        self.assertEqual(terms(10), [['skill', 197, 275], ['quest', 5518], ['lacks', 22813]])
        self.assertEqual(terms(13), [['level', 40]])
        self.assertEqual(terms(16), None)                    # NOT a quest rewarded: not carried over
        self.assertEqual(terms(17), [['lacks', 7]])          # NOT knows a spell: lacks it
        self.assertEqual(terms(14), None)                    # an item in the bags
        self.assertEqual(terms(15), None)                    # OR
        self.assertEqual(terms(19), None)                    # exactly level 40
        self.assertEqual(terms(20), None)                    # a flag
        self.assertEqual(terms(0), [])

    def test_a_line_with_a_condition_not_carried_over_is_counted(self):
        tables, creatures = self.tables([(5667, 0, 'So, I found this shackle key...', 5668, 0, 14), (5667, 2, 'Please teach me', -1, 566701, 15)],
                                        creatures=[(14338, 5667)])
        self.assertEqual(classicdb_pack.conversations(tables, creatures, {566701: {22814}}), ([], 1))


class ConversationEvidence(unittest.TestCase):
    PACK = {'trainers': [[12939, 10843, 100000, 129, 240, 0]], 'quests': [], 'gossip': [],
            'talk': [['npc', 14338, 'Please teach me', 22814, [['skill', 197, 275], ['quest', 5518], ['lacks', 22813]]],
                     ['npc', 12939, 'Teach me', 10843, [['skill', 129, 240]]], ['go', 180794, 'Decipher', 26095, [['skill', 197, 280]]]]}

    def test_a_line_whose_spell_teaches_the_recipe(self):
        found = classic.evidence(self.PACK, {22813: 197, 26086: 197, 10841: 129}, {22813: {22814}, 26086: {26095}, 10841: {10843}}, {})
        self.assertEqual(found['talk'], [['go', 180794, 'Decipher', 26086, 26095, [['skill', 197, 280]]],
                                         ['npc', 14338, 'Please teach me', 22813, 22814, [['skill', 197, 275], ['quest', 5518], ['lacks', 22813]]]])
        self.assertEqual(found['left'], {})   # the doctor's line is not needed: Classic also has him as the trainer

    def test_the_shape_of_a_line(self):
        self.assertTrue(classic.spoken(['npc', 1, 'x', 2, [['rep', 529, 7]]]))
        for bad in (['npc', 1, 'x', 2, [['rep', 529]]], ['pc', 1, 'x', 2, []], ['npc', 0, 'x', 2, []], ['npc', 1, '', 2, []], ['npc', 1, 'x', 2, [['drop', 1]]],
                    ['npc', 1, 'x', 2], ['npc', 1, 'x', 2, [['skill', 197, -1]]]):
            self.assertFalse(classic.spoken(bad), bad)


class Taught(unittest.TestCase):
    def test_every_spell_the_original_game_teaches(self):
        pack = {'trainers': [[1, 10843, 0, 129, 0, 0]], 'quests': [[5, 0, 11522], [6, 3, 0]], 'gossip': [[2, 22814]],
                'talk': [['go', 179552, 'x', 22864, []]]}
        self.assertEqual(classic.taught(pack), {10843, 11522, 3, 22814, 22864})


if __name__ == '__main__':
    unittest.main()
