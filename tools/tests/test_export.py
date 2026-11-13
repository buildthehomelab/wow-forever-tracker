"""python -m unittest discover -s tools/tests

The last class needs a MySQL server: it runs when FT_TEST_CONFIG names a config.ini of a throwaway server (its
[database] tracker database and a database of its own are created and dropped), and is skipped otherwise.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import export, facts, layers, quests, resolve  # noqa: E402
from ft.facts import Fact  # noqa: E402
from ft.resolve import Decision, Evidence  # noqa: E402

REGISTRY = layers.load()
LIVE = 70862
WORLD = {'quests': {100, 101}, 'npcs': {1, 2, 3}, 'objects': {50, 51}}
EXTRA = {'borrowed': {3}, 'quest_objects': {50}, 'names': {('npc', 1): 'Anna', ('quest', 100): 'First Steps', ('item', 900): 'Bread'}}
WORLD_NAMES = dict(EXTRA['names'])
MONEY = [{'itemId': 900, 'costs': {'5': 25}, 'stack': 1}]


def ready(kind, subject_kind, subject, other=0, allowed='public', rule='seen-live', witnesses=None):
    return {'kind': kind, 'subject_kind': subject_kind, 'subject': subject, 'object': other, 'allowed': allowed, 'rule': rule,
            'witnesses': witnesses or [{'source': 'eglink', 'part': '', 'build': LIVE, 'use': 'public'},
                                       {'source': 'questie', 'part': 'trace', 'build': 0, 'use': 'public'}]}


class Price(unittest.TestCase):
    def test_a_plain_row_needs_a_recording_that_says_money_and_endless(self):
        self.assertEqual(export.priced([('public', LIVE, MONEY)]), ('', 'public'))
        self.assertEqual(export.priced([]), ('no recording of the live game shows what it costs', 'public'))
        for listing, reason in (({'costItems': [{'currencyId': 515, 'amount': 50}]}, 'it costs items or a currency: the extended cost is not known'),
                                ({'bartered': {'?': {'4': 25}}}, 'it costs items or a currency: the extended cost is not known'),
                                ({'costs': {'5': 800}, 'limited': True, 'stockMax': 1}, 'its stock is limited: the restock time is not known'),
                                ({'stack': 1}, 'its recording shows no price'), ({'costs': {}}, 'its recording shows no price')):
            self.assertEqual(export.priced([('public', LIVE, [listing])])[0], reason, listing)
        self.assertEqual(export.priced([('public', LIVE, MONEY + MONEY)])[0], 'the vendor lists it more than once: one row cannot say that')
        for broken in (None, [], 'text', [None], {}):
            self.assertEqual(export.priced([('public', LIVE, broken)])[0], 'its recording cannot be read', broken)

    def test_the_newest_recording_decides_and_a_publishable_one_first(self):
        limited = [{'costs': {'5': 25}, 'limited': True}]
        self.assertEqual(export.priced([('public', LIVE, limited), ('public', LIVE + 5, MONEY)]), ('', 'public'))
        self.assertEqual(export.priced([('public', LIVE + 5, limited), ('public', LIVE, MONEY)])[0], 'its stock is limited: the restock time is not known')
        self.assertEqual(export.priced([('private', LIVE, limited), ('public', LIVE + 1, MONEY)]), ('', 'public'))
        # a newer recording that may not give the row can still hold it back: the newest word is that it is not plain
        self.assertEqual(export.priced([('private', LIVE + 9, limited), ('public', LIVE, MONEY)]),
                         ('its stock is limited: the restock time is not known', 'public'))
        self.assertEqual(export.priced([('private', LIVE + 9, MONEY), ('public', LIVE, limited)])[0], 'its stock is limited: the restock time is not known')
        self.assertEqual(export.priced([('private', LIVE, MONEY)]), ('', 'private'))


class Plan(unittest.TestCase):
    def plan(self, decisions, prices=None):
        rows, held = export.plan(decisions, WORLD, prices or {}, EXTRA)
        return rows, {(h.decision['kind'], h.decision['subject'], h.decision['object']): h.reason for h in held}

    def test_the_rows_of_what_can_be_written(self):
        rows, held = self.plan([ready('gives', 'npc', 1, 100), ready('takes', 'npc', 2, 100), ready('gives', 'object', 50, 101),
                                ready('takes', 'object', 50, 100), ready('sells', 'npc', 1, 900)], {(1, 900): [('public', LIVE, MONEY)]})
        self.assertEqual(held, {})
        self.assertEqual([(row.table, row.key) for row in rows], [
            ('creature_queststarter', (1, 100)), ('creature_questender', (2, 100)), ('gameobject_queststarter', (50, 101)),
            ('gameobject_questender', (50, 100)), ('npc_vendor', (1, 900, 0, 1))])
        self.assertEqual(rows[0].note, 'seen-live: eglink@70862, questie:trace')
        self.assertEqual([row.comment for row in rows], ['Anna gives First Steps', 'npc 2 takes First Steps', 'object 50 gives quest 101',
                                                         'object 50 takes First Steps', 'Anna sells Bread'])
        self.assertEqual(len(export.note(ready('gives', 'npc', 1, 100, witnesses=[{'source': 'x' * 300, 'part': '', 'build': 0}]))), 255)

    def test_a_file_that_may_be_published_names_only_sources_that_may_be(self):
        mixed = [{'source': 'eglink', 'part': '', 'build': LIVE, 'use': 'public'}, {'source': 'rxpguides', 'part': '', 'build': 0, 'use': 'private'},
                 {'source': 'wowhead', 'part': '', 'build': 0, 'use': 'reference'}, {'source': 'icyveins', 'part': '', 'build': LIVE, 'use': 'private'},
                 {'source': 'old', 'part': '', 'build': 0}]                     # stored before the use was kept: not known to be public
        prices = {(1, 900): [('public', LIVE, MONEY)], (2, 900): [('private', LIVE, MONEY)]}
        rows, _held = self.plan([ready('gives', 'npc', 1, 100, witnesses=mixed), ready('gives', 'npc', 2, 100, 'private', witnesses=mixed),
                                 ready('sells', 'npc', 1, 900, witnesses=mixed), ready('sells', 'npc', 2, 900, witnesses=mixed)], prices)
        self.assertEqual([(row.allowed, row.note) for row in rows], [
            ('public', 'seen-live: eglink@70862'), ('private', 'seen-live: eglink@70862, rxpguides, wowhead, icyveins@70862, old'),
            ('public', 'seen-live: eglink@70862'), ('private', 'seen-live: eglink@70862, rxpguides, wowhead, icyveins@70862, old')])
        made = export.manifest('f.sql', 'x', 'public', [rows[0], rows[2]], {}, {}, [])
        self.assertEqual({tuple(row['witnesses']) for row in made['rows']}, {('eglink@70862',)})
        public = export.text('f.sql', [rows[0], rows[2]], {'eglink': 'e' * 40}, [], 'x')
        for name in ('rxpguides', 'wowhead', 'icyveins', 'old'):
            self.assertNotIn(name, public)

    def test_what_is_held_back_and_why(self):
        _rows, held = self.plan([ready('quest', 'quest', 200), ready('npc', 'npc', 9), ready('gives', 'npc', 9, 100), ready('sells', 'npc', 9, 900),
                                 ready('gives', 'npc', 1, 200), ready('takes', 'object', 60, 100), ready('gives', 'object', 51, 100),
                                 ready('sells', 'npc', 2, 901), ready('sells', 'npc', 3, 900), ready('gives', 'item', 5, 100)],
                                {(3, 900): [('public', LIVE, MONEY)]})
        self.assertEqual(held, {
            ('quest', 200, 0): 'no record a row may be written from', ('npc', 9, 0): 'NPC templates are not written yet',
            ('gives', 9, 100): 'it waits for its NPC: NPC templates are not written yet', ('sells', 9, 900): 'it waits for its NPC: NPC templates are not written yet',
            ('gives', 1, 200): 'it waits for its quest, which is held back', ('takes', 60, 100): 'its object has no template',
            ('gives', 51, 100): 'its object is not of the quest giver kind', ('sells', 2, 901): 'no recording of the live game shows what it costs',
            ('sells', 3, 900): 'other vendors borrow its list: a row here would reach them too', ('gives', 5, 100): 'no writer for this kind of decision'})

    def test_nothing_hangs_on_a_row_the_world_holds_as_a_leftover(self):
        extra = dict(EXTRA, names={**WORLD_NAMES, ('quest', 101): 'REUSE', ('npc', 2): '[DNT] Bunny', ('object', 50): 'zzOLD Crate'})
        rows, held = export.plan([ready('gives', 'npc', 1, 101), ready('takes', 'npc', 2, 100), ready('sells', 'npc', 2, 900),
                                  ready('gives', 'object', 50, 100), ready('gives', 'npc', 1, 100)], WORLD, {(2, 900): [('public', LIVE, MONEY)]}, extra)
        self.assertEqual([row.key for row in rows], [(1, 100)])
        self.assertEqual([h.reason for h in held], ["the world's quest reads like a developer's leftover: for a person"]
                         + ["the world's NPC reads like a developer's leftover: for a person"] * 2
                         + ["the world's object reads like a developer's leftover: for a person"])

    def test_a_private_decision_or_a_private_price_makes_a_private_row(self):
        rows, _held = self.plan([ready('gives', 'npc', 1, 100, allowed='private'), ready('sells', 'npc', 1, 900), ready('sells', 'npc', 2, 900)],
                                {(1, 900): [('private', LIVE, MONEY)], (2, 900): [('public', LIVE, MONEY)]})
        self.assertEqual([(row.key, row.allowed) for row in rows], [((1, 100), 'private'), ((1, 900, 0, 1), 'private'), ((2, 900, 0, 1), 'public')])


RECORD = {'title': "Kobold's End", 'objectivesText': 'Slay 8 kobolds.', 'description': 'They dig too deep.\r\n\r\nStop them, $n\\$c.', 'flags': 8,
          'level': 7, 'minLevel': 5, 'questType': 2, 'raceMask': 'aa2aaaaa4e0ab3b2', 'zoneAreaId': 12,
          'objectives': [{'id': 5001, 'typeId': 0, 'objectId': 3, 'storageIndex': 0, 'amount': 8}, {'id': 5002, 'typeId': 2, 'objectId': 50, 'storageIndex': 1, 'amount': 1}],
          'rewards': {'money': 350, 'xpDifficulty': 4, 'xpMultiplier': 2.375, 'reputation': [{'factionId': 72, 'tier': 3}],
                      'displaySpells': [{'spellId': 635, 'type': 2}]}}


def known(record=None, use='public', **more):
    return dict({'use': use, 'source': 'eglink' if use == 'public' else 'icyveins', 'build': LIVE, 'record': record or RECORD}, **more)


class Quests(unittest.TestCase):
    def plan(self, decisions, records):
        rows, held = export.plan(decisions, WORLD, {}, EXTRA, records)
        return rows, {(h.decision['kind'], h.decision['subject'], h.decision['object']): h.reason for h in held}

    def test_a_quest_comes_with_its_giver_and_its_ender(self):
        rows, held = self.plan([ready('gives', 'npc', 1, 200), ready('takes', 'object', 50, 200), ready('quest', 'quest', 200, rule='record-seen-live'),
                                ready('gives', 'npc', 2, 100)], {200: known()})
        self.assertEqual(held, {})
        self.assertEqual([(row.table, row.key) for row in rows], [('quest_template', (200,)), ('creature_queststarter', (1, 200)),
                                                                  ('gameobject_questender', (50, 200)), ('creature_queststarter', (2, 100))])
        quest = rows[0]
        self.assertEqual((quest.comment, quest.allowed, quest.note), ("Kobold's End", 'public', 'record-seen-live: eglink@70862, questie:trace'))
        self.assertEqual((quest.data['record'], quest.data['sources'], quest.data['addon']), ('eglink@70862', {'eglink'}, None))
        self.assertEqual(rows[1].comment, "Anna gives Kobold's End")                 # the pair is named after the quest that comes with it

    def test_a_quest_nobody_can_start_or_end_yet_waits_and_its_pairs_with_it(self):
        _rows, held = self.plan([ready('quest', 'quest', 200), ready('gives', 'npc', 9, 200), ready('takes', 'npc', 2, 200),
                                 ready('quest', 'quest', 201), ready('gives', 'npc', 1, 201)], {200: known(), 201: known(dict(RECORD, objectives=[]))})
        self.assertEqual(held, {('gives', 9, 200): 'it waits for its NPC: NPC templates are not written yet',
                                ('quest', 200, 0): 'no giver of it can be written yet',
                                ('takes', 2, 200): 'it waits for its quest, which is held back',
                                ('quest', 201, 0): 'no ender of it can be written yet',
                                ('gives', 1, 201): 'it waits for its quest, which is held back'})
        world = dict(WORLD, gives={('npc', 3, 200)}, takes={('object', 50, 201)})          # the world's own pairs count: a row waits there for the quest
        rows, held = export.plan([ready('quest', 'quest', 200), ready('takes', 'npc', 2, 200), ready('quest', 'quest', 201), ready('gives', 'npc', 1, 201)],
                                 world, {}, EXTRA, {200: known(), 201: known(dict(RECORD, objectives=[]))})
        self.assertEqual((len(rows), held), (4, []))

    def test_what_keeps_a_quest_from_being_written(self):
        pairs = lambda quest: [ready('gives', 'npc', 1, quest), ready('takes', 'npc', 1, quest)]
        decisions = [d for quest in (200, 201, 202, 203, 204, 205) for d in [ready('quest', 'quest', quest)] + pairs(quest)]
        other = lambda *objectives: dict(RECORD, objectives=list(objectives))
        _rows, held = self.plan(decisions, {
            201: known(dict(RECORD, raceMask='everyone')), 202: known(other({'id': 6001, 'typeId': 0, 'objectId': 77, 'amount': 1})),
            203: known(other({'id': 6002, 'typeId': 2, 'objectId': 88, 'amount': 1})),
            204: known(other({'id': 7000, 'typeId': 1, 'objectId': 5, 'amount': 1})), 205: known(other({'id': 7000, 'typeId': 1, 'objectId': 6, 'amount': 1}))})
        self.assertEqual({key: reason for key, reason in held.items() if key[0] == 'quest'}, {
            ('quest', 200, 0): 'no record a row may be written from', ('quest', 201, 0): 'its record cannot be written: raceMask is not 64 bits written in hex',
            ('quest', 202, 0): 'an objective needs an NPC that has no template (NPC 77)', ('quest', 203, 0): 'an objective needs an object that has no template (object 88)',
            ('quest', 204, 0): "an objective id of its record is also another quest's", ('quest', 205, 0): "an objective id of its record is also another quest's"})
        self.assertEqual(export.grouped(held[('quest', 202, 0)]), 'an objective needs an NPC that has no template')
        self.assertEqual({reason for key, reason in held.items() if key[0] != 'quest'}, {'it waits for its quest, which is held back'})

    def test_what_may_be_published_never_needs_what_may_not(self):
        quest, gives, takes = ready('quest', 'quest', 200), ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200)
        sets = lambda decisions, records=None: [(row.table, row.allowed) for row in self.plan(decisions, records or {200: known()})[0]]
        # a quest written from a private record: its pairs go where it goes, and are named there
        rows, _held = self.plan([quest, gives, takes], {200: known(use='private')})
        self.assertEqual([(row.table, row.allowed) for row in rows], [('quest_template', 'private'), ('creature_queststarter', 'private'), ('creature_questender', 'private')])
        self.assertEqual(export.text('f.sql', [row for row in rows if row.allowed == 'public'] or rows[:0], {}, [], 'x').count("Kobold's End"), 0)
        # its only giver may not be published: the quest may not either, nor its ender
        self.assertEqual(sets([quest, dict(gives, allowed='private'), takes]),
                         [('quest_template', 'private'), ('creature_queststarter', 'private'), ('creature_questender', 'private')])
        # one giver of each kind: the quest and the public pair are published, the private pair is not
        self.assertEqual(sets([quest, dict(gives, allowed='private'), ready('gives', 'npc', 2, 200), takes]),
                         [('quest_template', 'public'), ('creature_queststarter', 'private'), ('creature_queststarter', 'public'), ('creature_questender', 'public')])
        # a giver that cannot be written at all is no giver (object 51 is a chest)
        _rows, held = self.plan([quest, ready('gives', 'object', 51, 200), takes], {200: known()})
        self.assertEqual(held[('quest', 200, 0)], 'no giver of it can be written yet')

    def test_rows_stand_together_or_not_at_all(self):
        rows, _held = self.plan([ready('quest', 'quest', 200), ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200), ready('gives', 'npc', 2, 100)], {200: known()})
        quest, giver, ender, other = rows
        self.assertEqual(export.settle(rows, WORLD), (rows, []))
        # the giver is gone (the world refused it, or an earlier export... lost it): the quest goes, and its ender with it; the pair of a quest in the world stays
        kept, dropped = export.settle([quest, ender, other], WORLD)
        self.assertEqual((kept, [(row.key, why) for row, why in dropped]), ([other], [((200,), 'no giver of it can be written yet'),
                                                                                  ((1, 200), 'it waits for its quest, which is held back')]))
        # an earlier export carries the giver: it reaches the world before this file
        self.assertEqual(export.settle([quest, ender], WORLD, {('creature_queststarter', (1, 200))}), ([quest, ender], []))
        # an earlier export carries the quest: its pairs can follow alone
        self.assertEqual(export.settle([giver, ender], WORLD, {('quest_template', (200,))}), ([giver, ender], []))
        self.assertEqual(len(export.settle([giver, ender], WORLD)[1]), 2)

    def test_whose_word_a_quest_s_row_is(self):
        both = [ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200)]
        row = lambda **more: self.plan([ready('quest', 'quest', 200)] + both, {200: known(**more)})[0][0]
        self.assertEqual(row(use='private').allowed, 'private')                      # the record's values come from a source that may not be published
        category = dict({k: v for k, v in RECORD.items() if k != 'zoneAreaId'}, categoryId=141)
        self.assertEqual(row(record=category).data['addon'], {'AllowableClasses': 2, 'PrevQuestID': 0})          # filed under Paladin
        self.assertEqual(row(record=category).data['sources'], {'eglink'})
        stated = row(record=category, classes=3, previous=100, addon_source='questie')
        self.assertEqual((stated.data['addon'], stated.data['sources'], stated.data['from_questiedb']),
                         ({'AllowableClasses': 3, 'PrevQuestID': 100}, {'eglink', 'questie'}, {'AllowableClasses': 3, 'PrevQuestID': 100}))
        unknown = row(previous=999, addon_source='questie')                           # the quest before it is not in the world: not written
        self.assertEqual((unknown.data['addon'], unknown.data['sources']), (None, {'eglink'}))

    def test_the_record_and_what_questiedb_adds(self):
        class Stored:
            def __init__(self, records, entries):
                self.records, self.entries = records, entries

            def query(self, sql, _database):
                return self.entries if "kind = 'entry'" in sql else self.records
        record = lambda source, quest, build, data=None: {'source': source, 'subject': str(quest), 'build': str(build), 'data': json.dumps(data or {'title': source})}
        entry = lambda quest, parts, source='questie': {'source': source, 'subject': str(quest), 'data': json.dumps({'parts': parts})}
        found = export.load_quests(Stored(
            [record('eglink', 200, 70450), record('eglink', 200, LIVE, {'title': 'newest'}), record('eglink', 200, LIVE - 50),
             record('icyveins', 200, LIVE + 9), record('icyveins', 201, LIVE), record('wowhead', 202, LIVE), record('nobody', 203, LIVE),
             record('eglink', 204, 70450), {'source': 'eglink', 'subject': '205', 'build': str(LIVE), 'data': '{broken'}] + [record('eglink', q, LIVE) for q in range(210, 216)],
            [entry(210, {'generated': {'requiredClasses': 3, 'preQuestSingle': [100]}}),
             entry(211, {'generated': {'requiredClasses': 3, 'preQuestSingle': [100]}, 'fix': {'requiredClasses': 2, 'preQuestSingle': [101]}}),
             # a hand fix that names the field replaces the generated value, also with nothing
             entry(212, {'generated': {'requiredClasses': 3, 'preQuestSingle': [100]}, 'fix': {'requiredClasses': 0, 'preQuestSingle': {}}}),
             entry(213, {'generated': {'requiredClasses': 3, 'preQuestSingle': [100]}, 'fix': {'requiredClasses': 'classIDs.PALADIN', 'preQuestSingle': [100, 101]}}),
             entry(214, {'trace': {'requiredClasses': 9}, 'fix': {'name': 'only a name'}}), entry(215, {'generated': {'requiredClasses': 3}}, 'icyveins'),
             entry(299, {'generated': {'requiredClasses': 3}})]), REGISTRY, range(200, 300))
        # the newest live record of a source that may be published; a private one only when no public source has any; never a reference's or a beta one
        self.assertEqual({q: (k['use'], k['source'], k['build']) for q, k in found.items() if q < 210},
                         {200: ('public', 'eglink', LIVE), 201: ('private', 'icyveins', LIVE), 205: ('public', 'eglink', LIVE)})
        self.assertEqual((found[200]['record'], found[205]['record']), ({'title': 'newest'}, None))
        self.assertEqual({q: (k.get('classes'), k.get('previous'), k.get('addon_source')) for q, k in found.items() if q >= 210}, {
            210: (3, 100, 'questie'), 211: (2, 101, 'questie'), 212: (0, 0, 'questie'), 213: (0, 0, 'questie'), 214: (None, None, None), 215: (None, None, None)})

    def test_a_text_is_kept_to_the_character(self):
        self.assertEqual(export.text_literal('plain'), "'plain'")
        self.assertEqual(export.text_literal(''), "''")
        self.assertEqual(export.text_literal("it's"), "'it''s'")
        self.assertEqual(export.text_literal('a\r\n\r\nb\\c\x00\td'), "CONCAT('a', CHAR(13, 10, 13, 10 USING utf8mb4), 'b', CHAR(92 USING utf8mb4), 'c', CHAR(9 USING utf8mb4), 'd')")
        self.assertEqual(export.text_literal('\n'), 'CONCAT(CHAR(10 USING utf8mb4))')
        self.assertEqual((export.value_literal(5), export.value_literal(2.375), export.value_literal(2 ** 64 - 1)), ('5', '2.375', '18446744073709551615'))
        with self.assertRaises(export.ExportError):
            export.value_literal(True)

    def test_the_quest_s_statements(self):
        rows, _held = self.plan([ready('quest', 'quest', 200), ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200)],
                                {200: known(dict(RECORD, categoryId=141, zoneAreaId=0))})
        text = ';\n'.join(export.body(rows, 'f.sql')) + ';\n'
        self.assertLess(text.index('INSERT INTO `quest_template`'), text.index('INSERT INTO `creature_queststarter`'))      # the quest first, then what hangs on it
        self.assertIn('CREATE TEMPORARY TABLE `everlake_build_quests` (`n` INT NOT NULL PRIMARY KEY, `note` VARCHAR(255) NOT NULL, `missing` TINYINT NOT NULL DEFAULT 0) '
                      'SELECT `ID`, `RewardItem1`, ', text)
        self.assertIn(" FROM `quest_template` WHERE 0;\n", text)
        self.assertIn("'Kobold''s End', 'Slay 8 kobolds.', CONCAT('They dig too deep.', CHAR(13, 10, 13, 10 USING utf8mb4), 'Stop them, $n', CHAR(92 USING utf8mb4), '$c.'), "
                      "'', '', 'seen-live: eglink@70862, questie:trace') -- Kobold's End\n;\n", text)
        self.assertIn(', 2.375, ', text)
        self.assertIn(', 12261800583900083122, 890, 878, -2, ', text)
        for guard in ("NOT EXISTS (SELECT 1 FROM `quest_template` t WHERE t.`ID` = s.`ID`)",
                      "NOT EXISTS (SELECT 1 FROM `quest_objectives` c WHERE c.`QuestID` = s.`ID`)", "NOT EXISTS (SELECT 1 FROM `quest_classic_level` c WHERE c.`ID` = s.`ID`)",
                      "NOT EXISTS (SELECT 1 FROM `quest_template_addon` c WHERE c.`ID` = s.`ID`)",
                      "r.`tbl` IN ('quest_template', 'quest_classic_level', 'quest_template_classic_level', 'quest_classic_money', 'quest_reward_display_spell', "
                      "'quest_template_addon') AND r.`k1` = s.`ID`)",
                      "UPDATE `everlake_build_objectives` p SET p.`taken` = 1 WHERE EXISTS (SELECT 1 FROM `quest_objectives` o WHERE o.`ID` = p.`ID`) "
                      "OR EXISTS (SELECT 1 FROM `everlake_import_rows` r WHERE r.`tbl` = 'quest_objectives' AND r.`k1` = p.`ID`);",
                      "NOT EXISTS (SELECT 1 FROM `everlake_build_objectives` p WHERE p.`QuestID` = s.`ID` AND p.`taken` = 1)"):
            self.assertIn(guard, text)
        self.assertIn("(1, 5001, 200, 0, 0, 0, 3, 8, 32, ''),\n(2, 5002, 200, 2, 1, 1, 50, 1, 32, '')\n;\n", text)
        self.assertIn("INSERT INTO `quest_objectives` (`ID`, `QuestID`, `Type`, `Order`, `StorageIndex`, `ObjectID`, `Amount`, `Flags`, `Description`, `VerifiedBuild`) "
                      "SELECT p.`ID`, p.`QuestID`, p.`Type`, p.`Order`, p.`StorageIndex`, p.`ObjectID`, p.`Amount`, p.`Flags`, p.`Description`, 0 "
                      "FROM `everlake_build_objectives` p JOIN `everlake_build_quests` s ON s.`ID` = p.`QuestID` WHERE s.`missing` = 1 ORDER BY p.`n`;", text)
        for values in ('(1, 200, 7, 5, 0)', '(1, 200, 2, 7)', '(1, 200, 350, 0)', '(1, 200, 0, 635, 0, 2)', '(1, 200, 2, 0)'):       # level, log level, money, spell, classes
            self.assertIn(values + '\n;\n', text)
        self.assertEqual(text.count("SELECT 'quest_template_classic_level', p.`ID`, p.`LevelType`, 'f.sql', s.`note`"), 1)
        self.assertEqual(text.count('DROP TEMPORARY TABLE'), 7 + 2)                  # every stage is gone again: the quests', five children's, the objectives', two pairs'
        # a quest without objectives, money, spells or classes brings only its levels
        bare, _held = self.plan([ready('quest', 'quest', 200), ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200)],
                                {200: known({'title': 'Bare', 'flags': 0, 'level': 1, 'minLevel': 1, 'questType': 0, 'raceMask': 'ff', 'rewards': {}})})
        text = ';\n'.join(export.quest_block(bare[:1], 'f.sql'))
        self.assertNotIn('everlake_build_objectives', text)
        self.assertEqual(text.count('CREATE TEMPORARY TABLE'), 3)
        made = export.manifest('f.sql', 'x', 'public', rows, {}, {}, [])
        self.assertEqual(made['rows'][0]['with'], {'quest_objectives': 2, 'quest_reward_display_spell': 1, 'quest_classic_money': 1, 'quest_template_addon': 1})
        self.assertEqual((made['rows'][0]['record'], made['rows'][0]['classes'], made['rows'][0]['unread'], made['left_to_defaults']),
                         ('eglink@70862', 2, [], list(quests.LEFT)))
        self.assertEqual(export.manifest('f.sql', 'x', 'public', rows[1:], {}, {}, [])['left_to_defaults'], [])
        self.assertEqual(export.counts(rows), '1 quest_template, 1 creature_queststarter, 1 creature_questender')


class File(unittest.TestCase):
    def rows(self):
        return export.plan([ready('gives', 'npc', 2, 100), ready('gives', 'npc', 1, 100), ready('takes', 'object', 50, 100),
                            ready('sells', 'npc', 1, 900), ready('sells', 'npc', 1, 880), ready('sells', 'npc', 2, 900)], WORLD,
                           {key: [('public', LIVE, MONEY)] for key in ((1, 900), (1, 880), (2, 900))}, EXTRA)[0]

    def test_the_file_s_name_and_order(self):
        public, private = export.file_name('2026-11-13', 950), export.file_name('2026-11-13', 950, True)
        self.assertEqual((public, private), ('2026_11_13_950_world_everlake_build.sql', '2026_11_13_950_world_everlake_build_private.sql'))
        self.assertLess(public, private)                       # the updater sorts by name: what may be published runs first
        self.assertLess('2026_11_13_900_world_everlake_forge_00001_spawn.sql', public)       # and both after the day's other files
        self.assertTrue(export.NAME.match(public) and export.NAME.match(private))

    def test_the_day_s_next_number_looks_at_both_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            one, two = os.path.join(folder, 'public'), os.path.join(folder, 'private')
            self.assertEqual(export.next_number([one, two], '2026-11-13'), 950)
            os.makedirs(os.path.join(one, 'sql', 'world'))
            os.makedirs(os.path.join(two, 'sql', 'world'))
            for where, name in ((one, '2026_11_13_950_world_everlake_build.sql'), (two, '2026_11_13_952_world_everlake_build_private.sql'),
                                (one, '2026_11_12_977_world_everlake_build.sql'), (one, '2026_11_13_99_world_everlake_other.sql')):
                open(os.path.join(where, 'sql', 'world', name), 'w').close()
            self.assertEqual(export.next_number([one, two], '2026-11-13'), 953)
            self.assertEqual(export.next_number([one, two], '2026-11-12'), 978)
            # the file moved on to the data repository, its manifest stayed: the number is still taken
            os.makedirs(os.path.join(two, 'build'))
            open(os.path.join(two, 'build', '2026_11_13_960_world_everlake_build_private.json'), 'w').close()
            open(os.path.join(two, 'build', '2026_11_13_970_notes.json'), 'w').close()
            self.assertEqual(export.next_number([one, two], '2026-11-13'), 961)
            open(os.path.join(one, 'sql', 'world', '2026_11_13_999_world_everlake_build.sql'), 'w').close()
            with self.assertRaisesRegex(export.ExportError, 'every number from 950 to 999 is used'):
                export.next_number([one, two], '2026-11-13')

    def test_a_date_is_written_one_way(self):
        for date in ('20261113', '2026-W46-5', '2026W465', '2026-1-5', '2026_11_13', '2026-11-13T00', '', '2026-11-13\n'):
            with self.assertRaisesRegex(export.ExportError, 'write the date as YYYY-MM-DD'):
                export.file_name(date, 950)
            with self.assertRaisesRegex(export.ExportError, 'write the date as YYYY-MM-DD'):
                export.next_number([], date)

    def test_a_string_reads_the_same_whatever_the_server_s_mode(self):
        self.assertEqual(export.literal("it's a \\ back\nslash\x00"), "'it''s a / back slash '")

    def test_the_text(self):
        rows = self.rows()
        text = export.text('f.sql', rows, {'eglink': 'e' * 40, 'questie': 'f' * 40}, REGISTRY.credits(['eglink', 'questie']), '3 update files, the newest z.sql')
        lines = text.split('\n')
        self.assertEqual(lines[0], '-- World build: 6 rows the server world lacks (2 creature_queststarter, 1 gameobject_questender, 3 npc_vendor)')
        self.assertIn('-- Sources (pins): eglink eeeeeeeeeeeeeeeeeeee, questie ffffffffffffffffffff', lines)
        self.assertIn('-- Data from Efficient Games (https://efficient.games), licensed under CC BY 4.0.', lines)
        self.assertNotIn('PRIVATE', text)
        self.assertIn('PRIVATE SET', export.text('f.sql', rows, {}, [], 'x', private=True))
        self.assertNotIn('from public WoW Forever data', export.text('f.sql', rows, {}, [], 'x', private=True))
        # a pin or a file name from outside cannot open a line of its own
        odd = export.text('f.sql', rows, {'eglink': 'e\nDROP TABLE x; --'}, [], 'z.sql\nDROP TABLE y')
        self.assertEqual([line[:3] for line in odd.split('\n') if 'DROP TABLE' in line], ['-- ', '-- '])
        self.assertEqual(text.count('START TRANSACTION;'), 1)
        self.assertTrue(text.endswith(';\nCOMMIT;\n'))
        # rows in key order whatever order they were decided in, each with its meaning; the statement ends after the last comment
        self.assertIn("(1, 1, 100, 'seen-live: eglink@70862, questie:trace'), -- Anna gives First Steps\n"
                      "(2, 2, 100, 'seen-live: eglink@70862, questie:trace') -- npc 2 gives First Steps\n;\n", text)
        # a vendor's items count on from its last slot, per vendor
        self.assertIn("(1, 1, 1, 880, ", text)
        self.assertIn("(2, 1, 2, 900, ", text)
        self.assertIn("(3, 2, 1, 900, ", text)
        self.assertIn("(SELECT COALESCE(MAX(v.`slot`), 0) FROM `npc_vendor` v WHERE v.`entry` = s.`entry`) + s.`seq`", text)
        for table in ('creature_queststarter', 'gameobject_questender', 'npc_vendor'):
            self.assertIn(f"r.`tbl` = '{table}'", text)                 # never again once a file added it
        self.assertIn('g.`type` = 2', text)
        self.assertNotIn('gameobject_template` c', text)
        self.assertEqual(text.count('`npcflag` | 2 '), 1)
        self.assertEqual(text.count('`npcflag` | 128 '), 1)

    def test_a_name_cannot_end_the_statement_or_the_line(self):
        row = export.Row('creature_queststarter', (1, 100), "it's; a note", 'Evil\n; DROP TABLE x; -- name' + 'x' * 400, 'public', ready('gives', 'npc', 1, 100))
        text = ';\n'.join(export.body([row], 'f.sql'))
        self.assertIn("(1, 1, 100, 'it''s; a note') -- " + ('Evil ; DROP TABLE x; -- name' + 'x' * 400)[:160] + '\n;\n', text)

    def test_the_manifest_and_what_earlier_exports_carry(self):
        rows = self.rows()
        held = [export.Held(ready('quest', 'quest', 200), 'quest rows are not written yet')] * 2
        made = export.manifest('f.sql', 'content', 'public', rows, {'eglink': 'e' * 40}, {'files': 3, 'newest': 'z.sql'}, held)
        self.assertEqual((made['file'], made['set'], made['sha1'], made['held_back']),
                         ('f.sql', 'public', '040f06fd774092478d450774f5ba30c5da78acc8', {'quest rows are not written yet': 2}))
        self.assertEqual(made['rows'][0], {'table': 'creature_queststarter', 'key': [1, 100], 'kind': 'gives', 'rule': 'seen-live',
                                           'witnesses': ['eglink@70862', 'questie:trace'], 'says': 'Anna gives First Steps'})
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(export.carried([folder]), {})
            os.makedirs(os.path.join(folder, 'build'))
            with open(os.path.join(folder, 'build', '2026_11_13_950_world_everlake_build.json'), 'w', encoding='utf-8') as handle:
                json.dump(made, handle)
            open(os.path.join(folder, 'build', 'notes.txt'), 'w').close()
            with open(os.path.join(folder, 'build', 'somebody-else.json'), 'w', encoding='utf-8') as handle:
                handle.write('[1, 2]')                                  # not a build file's manifest: not ours to read
            carried = export.carried([folder, os.path.join(folder, 'missing')])
            self.assertEqual(len(carried), 6)
            self.assertEqual(carried[('npc_vendor', (1, 900, 0, 1))], 'f.sql')
            with open(os.path.join(folder, 'build', '2026_11_13_951_world_everlake_build.json'), 'w', encoding='utf-8') as handle:
                handle.write('{"rows": 5}')
            with self.assertRaisesRegex(export.ExportError, '2026_11_13_951_world_everlake_build.json is not an export manifest'):
                export.carried([folder])


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server to run')
class OnMySQL(unittest.TestCase):
    WORLD_DB = 'ft_export_selftest'
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        os.environ['FOREVER_TRACKER_CONFIG'] = os.environ['FT_TEST_CONFIG']
        from ft import sqlio
        from ft.config import CONFIG
        cls.db, cls.tracker = sqlio, CONFIG.db('tracker')
        cls.folder = tempfile.TemporaryDirectory()
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nCREATE DATABASE `{cls.tracker}` CHARACTER SET utf8mb4;\n', 'information_schema')
        eg = Evidence('eglink', '', LIVE, 2, 'eglink', True, 'public')
        icy = Evidence('icyveins', '', LIVE, 1, 'eglink', True, 'private')
        pair = lambda kind, subject_kind, subject, other, allowed='public', who=eg: Decision(kind, subject_kind, subject, other, 'add', 'seen-live', allowed, '', [], [], [who])
        decisions = [pair('gives', 'npc', 1, 100), pair('gives', 'npc', 2, 100), pair('takes', 'npc', 2, 101), pair('gives', 'object', 50, 101),
                     pair('takes', 'object', 51, 101),                        # a chest: not of the quest giver kind
                     pair('gives', 'npc', 3, 100, 'private', icy),            # only a source without a licence states it
                     pair('sells', 'npc', 1, 900), pair('sells', 'npc', 1, 901), pair('sells', 'npc', 2, 900), pair('sells', 'npc', 2, 902),
                     pair('sells', 'npc', 4, 900),                            # another vendor borrows NPC 4's list
                     pair('sells', 'npc', 3, 903, 'public'),                  # its price is only in a private recording
                     pair('gives', 'npc', 9, 100),                            # NPC 9 has no template
                     Decision('quest', 'quest', 200, 0, 'add', 'record-seen-live', 'public', 'New', [], [], [eg]),
                     Decision('gives', 'npc', 1, 300, 'hold', 'seen-live', 'public', '', ['quest 300 is not in the world'], [], [eg])]
        path = os.path.join(cls.folder.name, 'decisions.sql')
        resolve.write_sql(path, decisions, {})
        sqlio.execute_file(path, 'tracker')
        money = lambda item, name: {'listings': [{'itemId': item, 'name': name, 'costs': {'5': 25}, 'stack': 1}]}
        stored = {'eglink': [Fact('sells', 'npc', 1, 900, LIVE, 1, money(900, 'Bread')), Fact('sells', 'npc', 1, 901, LIVE, 1, money(901, "Baker's Hat")),
                             Fact('sells', 'npc', 2, 900, LIVE, 1, money(900, 'Bread')), Fact('sells', 'npc', 4, 900, LIVE, 1, money(900, 'Bread')),
                             Fact('sells', 'npc', 2, 902, LIVE, 1, {'listings': [{'itemId': 902, 'costItems': [{'currencyId': 515, 'amount': 5}]}]}),
                             Fact('sells', 'npc', 2, 902, 70450, 1, money(902, 'Seen for money before the live game'))],
                  'icyveins': [Fact('sells', 'npc', 3, 903, LIVE, 1, money(903, 'Private price'))]}
        for source, rows in stored.items():
            path = os.path.join(cls.folder.name, source + '.sql')
            facts.write_sql(path, source, source[0] * 40, REGISTRY.source(source)['licence'], REGISTRY.source(source)['use'], rows)
            sqlio.execute_file(path, 'tracker')

    def setUp(self):
        self.db.execute(f'DROP DATABASE IF EXISTS `{self.WORLD_DB}`;\nCREATE DATABASE `{self.WORLD_DB}` CHARACTER SET utf8mb4;\n', 'information_schema')
        self.db.execute("""
CREATE TABLE ft_replay_files (id int PRIMARY KEY, name varchar(255), source varchar(64), sha256 char(64), state varchar(16), error text);
INSERT INTO ft_replay_files VALUES (1, 'a.sql', 'core', '', 'applied', NULL), (2, 'b.sql', 'core', '', 'applied', NULL);
CREATE TABLE quest_template (ID int unsigned PRIMARY KEY, LogTitle text); INSERT INTO quest_template VALUES (100, 'First Steps'), (101, 'Second');
CREATE TABLE creature_template (entry int unsigned PRIMARY KEY, name text, npcflag bigint unsigned NOT NULL DEFAULT 0);
INSERT INTO creature_template VALUES (1, 'Anna', 0), (2, 'Bert', 130), (3, 'Cora', 0), (4, 'Dora', 128), (5, 'Borrower', 128);
CREATE TABLE creature (guid int PRIMARY KEY, id int); CREATE TABLE gameobject (guid int PRIMARY KEY, id int);
CREATE TABLE gameobject_template (entry int unsigned PRIMARY KEY, name text, type tinyint unsigned NOT NULL);
INSERT INTO gameobject_template VALUES (50, 'Wanted Poster', 2), (51, 'Chest', 3);
CREATE TABLE creature_queststarter (id int unsigned, quest int unsigned, VerifiedBuild int NOT NULL DEFAULT 0, PRIMARY KEY (id, quest));
CREATE TABLE creature_questender LIKE creature_queststarter;
CREATE TABLE gameobject_queststarter LIKE creature_queststarter;
CREATE TABLE gameobject_questender LIKE creature_queststarter;
INSERT INTO creature_queststarter VALUES (2, 100, 70000);
CREATE TABLE npc_vendor (entry int unsigned NOT NULL, slot smallint NOT NULL DEFAULT 0, item int NOT NULL, maxcount int unsigned NOT NULL DEFAULT 0,
  incrtime int unsigned NOT NULL DEFAULT 0, ExtendedCost int unsigned NOT NULL DEFAULT 0, type tinyint unsigned NOT NULL DEFAULT 1, BonusListIDs mediumtext,
  PlayerConditionID int unsigned NOT NULL DEFAULT 0, IgnoreFiltering tinyint unsigned NOT NULL DEFAULT 0, VerifiedBuild int DEFAULT 0,
  PRIMARY KEY (entry, item, ExtendedCost, type));
INSERT INTO npc_vendor (entry, slot, item, ExtendedCost) VALUES (2, 1, 800, 0), (2, 7, 801, 0), (2, 3, 900, 44), (5, 1, -4, 0);
""", self.WORLD_DB)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.folders = {'public': os.path.join(self.out.name, 'public'), 'private': os.path.join(self.out.name, 'private')}

    @classmethod
    def tearDownClass(cls):
        cls.db.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nDROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\n', 'information_schema')
        cls.folder.cleanup()

    def world(self):
        return resolve.load_world(self.db, self.WORLD_DB)

    def state(self):
        q = lambda sql: [tuple(row.values()) for row in self.db.query(sql, self.WORLD_DB)]
        return {'starters': q('SELECT id, quest, VerifiedBuild FROM creature_queststarter ORDER BY id, quest'),
                'enders': q('SELECT id, quest FROM creature_questender ORDER BY id, quest'),
                'object starters': q('SELECT id, quest FROM gameobject_queststarter ORDER BY id, quest'),
                'object enders': q('SELECT id, quest FROM gameobject_questender ORDER BY id, quest'),
                'vendor': q('SELECT entry, slot, item, ExtendedCost, type, VerifiedBuild FROM npc_vendor ORDER BY entry, slot, item'),
                'flags': q('SELECT entry, npcflag FROM creature_template ORDER BY entry'),
                'ledger': q("SELECT tbl, k1, k2, k3, k4, file, note FROM everlake_import_rows ORDER BY tbl, k1, k2") if self.db.query(
                    "SHOW TABLES LIKE 'everlake_import_rows'", self.WORLD_DB) else None}

    def run_export(self, date='2026-11-13', write=True):
        return export.export(self.db, self.WORLD_DB, self.db, REGISTRY, self.world(), self.folders, date, write)

    def test_from_decisions_to_a_file_the_world_takes_once(self):
        before = self.state()
        self.assertIsNone(before['ledger'])
        result = self.run_export()
        self.assertEqual(self.state(), before)                          # the trial left nothing behind, not even the ledger
        self.assertEqual({kind: [(row.table, row.key) for row in rows] for kind, (_path, rows) in result['files'].items()}, {
            'public': [('creature_queststarter', (1, 100)), ('creature_questender', (2, 101)), ('gameobject_queststarter', (50, 101)),
                       ('npc_vendor', (1, 900, 0, 1)), ('npc_vendor', (1, 901, 0, 1))],
            'private': [('creature_queststarter', (3, 100)), ('npc_vendor', (3, 903, 0, 1))]})
        reasons = {(h.decision['kind'], h.decision['subject'], h.decision['object']): h.reason for h in result['held']}
        self.assertEqual(reasons, {
            ('takes', 51, 101): 'its object is not of the quest giver kind', ('sells', 2, 902): 'it costs items or a currency: the extended cost is not known',
            ('sells', 4, 900): 'other vendors borrow its list: a row here would reach them too',
            ('gives', 9, 100): 'it waits for its NPC: NPC templates are not written yet', ('quest', 200, 0): 'no record a row may be written from',
            # NPC 2 lists item 900 for an extended cost already: the world refused the plain row in the trial
            ('sells', 2, 900): export.REFUSED,
            ('gives', 2, 100): export.REFUSED})                       # a decision older than the world: Bert gives the quest by now
        self.assertEqual(len(result['refused']), 2)
        public, private = result['files']['public'][0], result['files']['private'][0]
        self.assertEqual((os.path.basename(public), os.path.basename(private)),
                         ('2026_11_13_950_world_everlake_build.sql', '2026_11_13_950_world_everlake_build_private.sql'))
        with open(public, encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn('-- Written against the replayed world: 2 update files, the newest b.sql.', text)
        self.assertIn("-- Anna sells Baker's Hat", text)
        self.assertNotIn('icyveins', text)
        with open(os.path.join(self.folders['public'], 'build', '2026_11_13_950_world_everlake_build.json'), encoding='utf-8') as handle:
            manifest = json.load(handle)
        self.assertEqual((manifest['sources'], manifest['world'], len(manifest['rows'])), ({'eglink': 'e' * 40}, {'files': 2, 'newest': 'b.sql'}, 5))
        self.assertEqual(manifest['sha1'], hashlib.sha1(text.encode('utf-8')).hexdigest())
        with open(private, encoding='utf-8') as handle:
            self.assertIn('PRIVATE SET', handle.read())

        # the updater's order: the public file, then the private one; then both again, as after a changed earlier file
        for path in (public, private):
            self.db.execute_file(path, self.WORLD_DB)
        once = self.state()
        self.assertEqual(once['starters'], [('1', '100', '0'), ('2', '100', '70000'), ('3', '100', '0')])
        self.assertEqual(once['enders'], [('2', '101')])
        self.assertEqual(once['object starters'], [('50', '101')])
        self.assertEqual(once['object enders'], [])
        self.assertEqual([row for row in once['vendor'] if row[0] in ('1', '3')],
                         [('1', '1', '900', '0', '1', '0'), ('1', '2', '901', '0', '1', '0'), ('3', '1', '903', '0', '1', '0')])
        # Anna got both flags, Bert had them, Cora got them from the private file, nobody else changed
        self.assertEqual(once['flags'], [('1', '130'), ('2', '130'), ('3', '130'), ('4', '128'), ('5', '128')])
        self.assertEqual([(row[0], row[1], row[2], row[5]) for row in once['ledger']], [
            ('creature_questender', '2', '101', os.path.basename(public)), ('creature_queststarter', '1', '100', os.path.basename(public)),
            ('creature_queststarter', '3', '100', os.path.basename(private)), ('gameobject_queststarter', '50', '101', os.path.basename(public)),
            ('npc_vendor', '1', '900', os.path.basename(public)), ('npc_vendor', '1', '901', os.path.basename(public)),
            ('npc_vendor', '3', '903', os.path.basename(private))])
        self.assertEqual(once['ledger'][0][6], 'seen-live: eglink@70862')
        for path in (public, private):
            self.db.execute_file(path, self.WORLD_DB)
        self.assertEqual(self.state(), once)

        # the same folders: the decisions an export carries are not written again, whatever the world holds
        self.db.execute('DELETE FROM creature_queststarter WHERE id = 1', self.WORLD_DB)
        again = self.run_export()
        self.assertEqual((again['files'], len(again['earlier'])), ({}, 7))            # all seven are carried already: Anna's pair is not offered again
        self.assertEqual(sorted(os.listdir(os.path.join(self.folders['public'], 'sql', 'world'))), ['2026_11_13_950_world_everlake_build.sql'])

        # other folders, as if the manifests were lost: the ledger still knows, and a row its owners took out stays out
        self.folders = {kind: path + '-2' for kind, path in self.folders.items()}
        with self.assertRaisesRegex(export.ExportError, 'the world already applied a file named 2026_11_13_950_world_everlake_build.sql'):
            self.run_export(write=False)
        lost = self.run_export('2026-11-14', write=False)
        self.assertEqual(lost['files'], {})
        # (the decisions here are older than the world: the rows the world holds by now are refused the same way)
        self.assertEqual(len(lost['refused']), 9)
        self.assertEqual(self.state()['starters'], [('2', '100', '70000'), ('3', '100', '0')])
        self.assertFalse(os.path.exists(self.folders['public']))

    def test_vendor_slots_count_on_from_the_vendor_s_last(self):
        self.db.execute('DELETE FROM npc_vendor WHERE entry = 2 AND item = 900', self.WORLD_DB)
        result = self.run_export()
        self.assertIn(('npc_vendor', (2, 900, 0, 1)), [(row.table, row.key) for row in result['files']['public'][1]])
        self.db.execute_file(result['files']['public'][0], self.WORLD_DB)
        self.assertEqual([row[:3] for row in self.state()['vendor'] if row[0] == '2'], [('2', '1', '800'), ('2', '7', '801'), ('2', '8', '900')])

    def test_a_dry_run_and_a_file_that_exists(self):
        result = self.run_export(write=False)
        self.assertEqual(len(result['files']['public'][1]), 5)
        self.assertFalse(os.path.exists(self.folders['public']))
        os.makedirs(os.path.join(self.folders['public'], 'sql', 'world'))
        self.run_export()
        os.remove(os.path.join(self.folders['public'], 'build', '2026_11_13_950_world_everlake_build.json'))
        os.remove(os.path.join(self.folders['private'], 'build', '2026_11_13_950_world_everlake_build_private.json'))
        # the manifests are gone, the files are not: the next export takes the next number, never a written file's
        self.assertEqual(os.path.basename(self.run_export()['files']['public'][0]), '2026_11_13_951_world_everlake_build.sql')
        # something in the way of a manifest: nothing is written, not even the file that had room
        os.makedirs(os.path.join(self.folders['private'], 'build', '2026_11_13_952_world_everlake_build_private.json'))
        with self.assertRaisesRegex(export.ExportError, 'everlake_build_private.json is not an export manifest'):
            self.run_export()
        self.assertEqual(sorted(os.listdir(os.path.join(self.folders['public'], 'sql', 'world'))),
                         ['2026_11_13_950_world_everlake_build.sql', '2026_11_13_951_world_everlake_build.sql'])

    def test_a_world_that_does_not_roll_back_is_noticed(self):
        self.db.execute('ALTER TABLE creature_questender ENGINE = MyISAM', self.WORLD_DB)
        with self.assertRaisesRegex(export.ExportError, 'THE TRIAL CHANGED THE REPLAYED WORLD \\(creature_questender 0 -> 1\\)'):
            self.run_export()
        self.assertFalse(os.path.exists(self.folders['public']))

    def test_a_world_that_breaks_the_file_stops_the_export(self):
        self.db.execute('ALTER TABLE creature_questender DROP COLUMN VerifiedBuild', self.WORLD_DB)
        with self.assertRaisesRegex(export.ExportError, 'the replayed world refuses the file'):
            self.run_export()
        self.assertFalse(os.path.exists(self.folders['public']))
        self.assertEqual(self.state()['starters'], [('2', '100', '70000')])           # and the rows before the broken one were rolled back


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server to run')
class QuestsOnMySQL(unittest.TestCase):
    WORLD_DB = 'ft_export_selftest'
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        os.environ['FOREVER_TRACKER_CONFIG'] = os.environ['FT_TEST_CONFIG']
        from ft import sqlio
        from ft.config import CONFIG
        cls.db, cls.tracker = sqlio, CONFIG.db('tracker')
        cls.folder = tempfile.TemporaryDirectory()
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nCREATE DATABASE `{cls.tracker}` CHARACTER SET utf8mb4;\n', 'information_schema')
        eg = Evidence('eglink', '', LIVE, 2, 'eglink', True, 'public')
        add = lambda kind, subject_kind, subject, other=0: Decision(kind, subject_kind, subject, other, 'add', 'record-seen-live' if kind == 'quest' else 'seen-live',
                                                                   'public', '', [], [], [eg])
        decisions = [add('quest', 'quest', 200), add('gives', 'npc', 1, 200), add('takes', 'npc', 2, 200),
                     add('quest', 'quest', 201), add('gives', 'npc', 1, 201), add('takes', 'npc', 1, 201),      # one of its objective ids is another quest's in the world
                     add('quest', 'quest', 202), add('gives', 'npc', 1, 202), add('takes', 'npc', 1, 202)]      # only a beta build recorded it
        path = os.path.join(cls.folder.name, 'decisions.sql')
        resolve.write_sql(path, decisions, {})
        sqlio.execute_file(path, 'tracker')
        clash = dict(RECORD, title='Clash', objectives=[{'id': 4000, 'typeId': 1, 'objectId': 5, 'storageIndex': 0, 'amount': 1}])
        stored = {'eglink': [Fact('quest', 'quest', 200, 0, 70450, 1, dict(RECORD, title='Before the live game')),
                             Fact('quest', 'quest', 200, 0, LIVE, 2, dict(RECORD, categoryId=141, zoneAreaId=0)),
                             Fact('quest', 'quest', 201, 0, LIVE, 1, clash), Fact('quest', 'quest', 202, 0, 70450, 1, RECORD)],
                  'questie': [Fact('entry', 'quest', 200, 0, 0, 0, {'parts': {'generated': {'requiredClasses': 3}, 'fix': {'preQuestSingle': [100], 'requiredClasses': 2}}})]}
        for source, rows in stored.items():
            path = os.path.join(cls.folder.name, source + '.sql')
            facts.write_sql(path, source, source[0] * 40, REGISTRY.source(source)['licence'], REGISTRY.source(source)['use'], rows)
            sqlio.execute_file(path, 'tracker')
        template = quests.rows(1, RECORD)[0].template
        kind = lambda column: ('mediumtext' if isinstance(template[column], str) else 'bigint unsigned NOT NULL DEFAULT 0' if column == 'AllowableRaces'
                               else 'float NOT NULL DEFAULT 1' if column == 'RewardXPMultiplier' else 'int NOT NULL DEFAULT 0')
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\nCREATE DATABASE `{cls.WORLD_DB}` CHARACTER SET utf8mb4;\n', 'information_schema')
        sqlio.execute(f"""
CREATE TABLE ft_replay_files (id int PRIMARY KEY, name varchar(255), source varchar(64), sha256 char(64), state varchar(16), error text);
INSERT INTO ft_replay_files VALUES (1, 'a.sql', 'core', '', 'applied', NULL);
CREATE TABLE quest_template ({', '.join(f'`{column}` {kind(column)}' for column in template)}, RewardBonusMoney int NOT NULL DEFAULT 7,
  PortraitGiverText mediumtext, VerifiedBuild int NOT NULL DEFAULT 99, PRIMARY KEY (ID));
INSERT INTO quest_template (ID, LogTitle) VALUES (100, 'First Steps');
CREATE TABLE quest_objectives (ID int unsigned PRIMARY KEY, QuestID int unsigned NOT NULL, Type tinyint unsigned NOT NULL, `Order` tinyint unsigned NOT NULL,
  StorageIndex tinyint NOT NULL, ObjectID int NOT NULL, Amount int NOT NULL, Flags int unsigned NOT NULL DEFAULT 0, Flags2 int unsigned NOT NULL DEFAULT 0,
  Description mediumtext, VerifiedBuild int NOT NULL DEFAULT 99);
INSERT INTO quest_objectives (ID, QuestID, Type, `Order`, StorageIndex, ObjectID, Amount) VALUES (4000, 100, 1, 0, 0, 5, 1);
CREATE TABLE quest_classic_level (ID int unsigned PRIMARY KEY, QuestLevel smallint, MinLevel tinyint unsigned, MaxLevel tinyint unsigned);
CREATE TABLE quest_template_classic_level (ID int unsigned PRIMARY KEY, LevelType int, QuestLevel int);
CREATE TABLE quest_classic_money (ID int unsigned PRIMARY KEY, RewardMoney int, RewardMoneyMaxLevel int unsigned);
CREATE TABLE quest_reward_display_spell (QuestID int unsigned, Idx int unsigned, SpellID int unsigned, PlayerConditionID int unsigned, Type int unsigned,
  VerifiedBuild int NOT NULL DEFAULT 99, PRIMARY KEY (QuestID, Idx));
CREATE TABLE quest_template_addon (ID int unsigned PRIMARY KEY, MaxLevel tinyint unsigned NOT NULL DEFAULT 0, AllowableClasses int unsigned NOT NULL DEFAULT 0,
  PrevQuestID int NOT NULL DEFAULT 0, ScriptName varchar(64) NOT NULL DEFAULT '');
CREATE TABLE creature_template (entry int unsigned PRIMARY KEY, name text, npcflag bigint unsigned NOT NULL DEFAULT 0);
INSERT INTO creature_template VALUES (1, 'Anna', 0), (2, 'Bert', 2), (3, 'Kobold', 0);
CREATE TABLE creature (guid int PRIMARY KEY, id int); CREATE TABLE gameobject (guid int PRIMARY KEY, id int);
CREATE TABLE gameobject_template (entry int unsigned PRIMARY KEY, name text, type tinyint unsigned NOT NULL); INSERT INTO gameobject_template VALUES (50, 'Crate', 3);
CREATE TABLE creature_queststarter (id int unsigned, quest int unsigned, VerifiedBuild int NOT NULL DEFAULT 0, PRIMARY KEY (id, quest));
CREATE TABLE creature_questender LIKE creature_queststarter;
CREATE TABLE gameobject_queststarter LIKE creature_queststarter;
CREATE TABLE gameobject_questender LIKE creature_queststarter;
CREATE TABLE npc_vendor (entry int unsigned NOT NULL, slot smallint NOT NULL DEFAULT 0, item int NOT NULL, ExtendedCost int unsigned NOT NULL DEFAULT 0,
  type tinyint unsigned NOT NULL DEFAULT 1, PRIMARY KEY (entry, item, ExtendedCost, type));
""", cls.WORLD_DB)

    @classmethod
    def tearDownClass(cls):
        cls.db.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nDROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\n', 'information_schema')
        cls.folder.cleanup()

    def table(self, sql):
        return [tuple(row.values()) for row in self.db.query(sql, self.WORLD_DB)]

    def test_a_quest_goes_in_whole_once(self):
        with tempfile.TemporaryDirectory() as out:
            folders = {'public': os.path.join(out, 'public'), 'private': os.path.join(out, 'private')}
            world = resolve.load_world(self.db, self.WORLD_DB)
            result = export.export(self.db, self.WORLD_DB, self.db, REGISTRY, world, folders, '2026-11-13')
            self.assertEqual(list(result['files']), ['public'])
            path, rows = result['files']['public']
            self.assertEqual([(row.table, row.key) for row in rows], [('quest_template', (200,)), ('creature_queststarter', (1, 200)), ('creature_questender', (2, 200))])
            reasons = {(h.decision['kind'], h.decision['subject'], h.decision['object']): h.reason for h in result['held']}
            self.assertEqual(reasons, {('quest', 201, 0): export.REFUSED, ('gives', 1, 201): export.REFUSED, ('takes', 1, 201): export.REFUSED,
                                       ('quest', 202, 0): 'no record a row may be written from',
                                       ('gives', 1, 202): 'it waits for its quest, which is held back', ('takes', 1, 202): 'it waits for its quest, which is held back'})
            self.assertEqual(self.table('SELECT ID FROM quest_template'), [('100',)])              # the trial left nothing
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('-- Sources (pins): eglink eeeeeeeeeeeeeeeeeeee, questie qqqqqqqqqqqqqqqqqqqq', text)        # QuestieDB's word is in the row: it is named
            self.assertNotIn('\r', text)                                                    # the file's own line ends are plain
            with open(os.path.join(folders['public'], 'build', os.path.basename(path)[:-4] + '.json'), encoding='utf-8') as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest['rows'][0]['from_questiedb'], {'AllowableClasses': 2, 'PrevQuestID': 100})       # the hand fix after the generated list
            self.assertEqual(manifest['left_to_defaults'], list(quests.LEFT))
            for _run in (1, 2):
                self.db.execute_file(path, self.WORLD_DB)
                row = self.db.query('SELECT *, HEX(QuestDescription) hex FROM quest_template WHERE ID = 200', self.WORLD_DB)[0]
                self.assertEqual((row['LogTitle'], row['QuestType'], row['QuestSortID'], row['Flags'], row['RewardXPDifficulty'], row['RewardXPMultiplier']),
                                 ("Kobold's End", '2', '-141', '8', '4', '2.375'))
                self.assertEqual((row['AllowableRaces'], row['RewardFactionID1'], row['RewardFactionValue1'], row['RewardFactionCapIn1'], row['RewardFactionCapIn5']),
                                 ('12261800583900083122', '72', '3', '7', '7'))
                self.assertEqual((row['AcceptedSoundKitID'], row['Expansion'], row['VerifiedBuild']), ('890', '-2', '0'))
                self.assertEqual((row['RewardBonusMoney'], row['PortraitGiverText'], row['AreaDescription']), ('7', None, ''))      # a column it does not name keeps the table's default
                self.assertEqual(bytes.fromhex(row['hex']).decode('utf-8'), 'They dig too deep.\r\n\r\nStop them, $n\\$c.')    # to the character
                self.assertEqual(self.table('SELECT ID, QuestID, Type, `Order`, StorageIndex, ObjectID, Amount, Flags, Description, VerifiedBuild FROM quest_objectives ORDER BY ID'),
                                 [('4000', '100', '1', '0', '0', '5', '1', '0', None, '99'), ('5001', '200', '0', '0', '0', '3', '8', '32', '', '0'),
                                  ('5002', '200', '2', '1', '1', '50', '1', '32', '', '0')])
                self.assertEqual(self.table('SELECT * FROM quest_classic_level'), [('200', '7', '5', '0')])
                self.assertEqual(self.table('SELECT * FROM quest_template_classic_level'), [('200', '2', '7')])
                self.assertEqual(self.table('SELECT * FROM quest_classic_money'), [('200', '350', '0')])
                self.assertEqual(self.table('SELECT * FROM quest_reward_display_spell'), [('200', '0', '635', '0', '2', '0')])
                self.assertEqual(self.table('SELECT ID, AllowableClasses, PrevQuestID, ScriptName FROM quest_template_addon'), [('200', '2', '100', '')])
                self.assertEqual(self.table('SELECT id, quest FROM creature_queststarter'), [('1', '200')])
                self.assertEqual(self.table('SELECT id, quest FROM creature_questender'), [('2', '200')])
                self.assertEqual(self.table('SELECT entry, npcflag FROM creature_template ORDER BY entry'), [('1', '2'), ('2', '2'), ('3', '0')])
                self.assertEqual(self.table('SELECT tbl, k1, k2, note FROM everlake_import_rows ORDER BY tbl, k1, k2'), [
                    ('creature_questender', '2', '200', 'seen-live: eglink@70862'), ('creature_queststarter', '1', '200', 'seen-live: eglink@70862'),
                    ('quest_classic_level', '200', '0', 'record-seen-live: eglink@70862'), ('quest_classic_money', '200', '0', 'record-seen-live: eglink@70862'),
                    ('quest_objectives', '5001', '0', 'record-seen-live: eglink@70862'), ('quest_objectives', '5002', '0', 'record-seen-live: eglink@70862'),
                    ('quest_reward_display_spell', '200', '0', 'record-seen-live: eglink@70862'), ('quest_template', '200', '0', 'record-seen-live: eglink@70862'),
                    ('quest_template_addon', '200', '0', 'record-seen-live: eglink@70862'), ('quest_template_classic_level', '200', '2', 'record-seen-live: eglink@70862')])
            # the owners take the quest out: no later file brings it back, nor any row of it
            self.db.execute('DELETE FROM quest_template WHERE ID = 200; DELETE FROM quest_objectives WHERE QuestID = 200; DELETE FROM quest_classic_level; '
                            'DELETE FROM quest_template_classic_level; DELETE FROM quest_classic_money; DELETE FROM quest_reward_display_spell; '
                            'DELETE FROM quest_template_addon; DELETE FROM creature_queststarter; DELETE FROM creature_questender', self.WORLD_DB)
            later = {kind: folder + '-later' for kind, folder in folders.items()}
            again = export.export(self.db, self.WORLD_DB, self.db, REGISTRY, resolve.load_world(self.db, self.WORLD_DB), later, '2026-11-14', write=False)
            self.assertEqual((again['files'], len(again['refused'])), ({}, 6))
            self.assertEqual(self.table('SELECT ID FROM quest_template'), [('100',)])


if __name__ == '__main__':
    unittest.main()
