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

from ft import export, facts, layers, npcs, quests, resolve  # noqa: E402
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

    def test_an_item_nobody_recorded_is_sold_as_the_world_s_other_vendors_sell_it(self):
        L = export.Listing
        self.assertEqual(export.elsewhere([L(2, True, True), L(3, True, True), L(4, True, False)], 1), ('', 2))        # two spawned vendors; a third that is not
        self.assertEqual(export.elsewhere([L(2, True, True), L(2, True, True)], 1), ('', 1))                           # one vendor listing it twice is one vendor
        nobody = 'no recording of the live game shows what it costs, and no other vendor players can reach sells it'
        self.assertEqual(export.elsewhere([], 1), (nobody, 0))
        self.assertEqual(export.elsewhere([L(1, True, True)], 1), (nobody, 0))                # its own row says nothing about how others sell it
        self.assertEqual(export.elsewhere([L(2, True, False)], 1), (nobody, 0))               # a vendor nobody can reach, or a leftover: not a vendor of the world
        other = 'no recording of the live game shows what it costs, and other vendors sell it for a currency, with a condition or in limited stock'
        self.assertEqual(export.elsewhere([L(2, True, True), L(3, False, True)], 1), (other, 0))
        self.assertEqual(export.elsewhere([L(2, True, True), L(3, False, False)], 1), (other, 0))     # even one that is not spawned: the item is not always plain
        self.assertEqual(export.elsewhere([L(2, True, True), L(1, False, True)], 1), ('', 1))

    def test_a_recording_that_may_not_give_a_row_can_still_speak_against_a_plain_one(self):
        limited, currency = [{'costs': {'5': 25}, 'limited': True}], [{'costItems': [{'currencyId': 515, 'amount': 50}]}]
        self.assertEqual(export.said_before([('other', 70450, limited)]), 'its stock is limited: the restock time is not known')
        self.assertEqual(export.said_before([('other', 70450, currency), ('other', 70500, MONEY)]), '')          # the newest of them
        self.assertEqual(export.said_before([('other', 70500, MONEY + MONEY)]), 'the vendor lists it more than once: one row cannot say that')
        self.assertEqual(export.said_before([('other', 70450, None)]), '')                  # unreadable, or without a price: it says nothing against
        self.assertEqual(export.said_before([('other', 70450, [{'stack': 1}])]), '')
        self.assertEqual(export.said_before([('public', LIVE, limited)]), '')               # a recording that counts is priced()'s to read
        self.assertEqual(export.priced([('other', 70450, MONEY)]), ('no recording of the live game shows what it costs', 'public'))


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
            ('quest', 200, 0): 'no record a row may be written from', ('npc', 9, 0): 'no record a row may be written from',
            ('gives', 9, 100): 'it waits for its NPC, which is held back', ('sells', 9, 900): 'it waits for its NPC, which is held back',
            ('gives', 1, 200): 'it waits for its quest, which is held back', ('takes', 60, 100): 'its object has no template',
            ('gives', 51, 100): 'its object is not of the quest giver kind', ('sells', 2, 901): 'no recording of the live game shows what it costs, and no other vendor players can reach sells it',
            ('sells', 3, 900): 'other vendors borrow its list: a row here would reach them too', ('gives', 5, 100): 'no writer for this kind of decision'})

    def test_nothing_hangs_on_a_row_the_world_holds_as_a_leftover(self):
        extra = dict(EXTRA, names={**WORLD_NAMES, ('quest', 101): 'REUSE', ('npc', 2): '[DNT] Bunny', ('object', 50): 'zzOLD Crate'})
        rows, held = export.plan([ready('gives', 'npc', 1, 101), ready('takes', 'npc', 2, 100), ready('sells', 'npc', 2, 900),
                                  ready('gives', 'object', 50, 100), ready('gives', 'npc', 1, 100)], WORLD, {(2, 900): [('public', LIVE, MONEY)]}, extra)
        self.assertEqual([row.key for row in rows], [(1, 100)])
        self.assertEqual([h.reason for h in held], ["the world's quest reads like a developer's leftover: for a person"]
                         + ["the world's NPC reads like a developer's leftover: for a person"] * 2
                         + ["the world's object reads like a developer's leftover: for a person"])

    def test_a_vendor_item_without_a_recording_follows_the_world_s_other_vendors(self):
        L = export.Listing
        extra = dict(EXTRA, sold={900: [L(2, True, True), L(7, True, True)], 901: [L(2, True, True), L(7, False, True)], 902: [L(1, True, True)]})
        decisions = [ready('sells', 'npc', 1, 900, rule='trusted-source'), ready('sells', 'npc', 1, 901), ready('sells', 'npc', 1, 902), ready('sells', 'npc', 2, 900),
                     ready('sells', 'npc', 3, 900), ready('sells', 'npc', 2, 901, allowed='private')]
        limited = [{'costs': {'5': 25}, 'limited': True}]
        rows, held = export.plan(decisions, WORLD, {(2, 900): [('public', LIVE, limited)], (2, 901): [('public', LIVE, MONEY)]}, extra)
        self.assertEqual([(row.key, row.allowed, row.data['sold']) for row in rows], [
            ((1, 900, 0, 1), 'public', "no recording: the world's other vendors of it (2) all sell it for money, in endless supply"),
            ((2, 901, 0, 1), 'private', 'a recording of the live game shows it sold for money, in endless supply')])
        self.assertEqual(export.described(rows[0]), {'sold': rows[0].data['sold']})
        self.assertEqual({(h.decision['subject'], h.decision['object']): h.reason for h in held}, {
            (1, 901): 'no recording of the live game shows what it costs, and other vendors sell it for a currency, with a condition or in limited stock',
            (1, 902): 'no recording of the live game shows what it costs, and no other vendor players can reach sells it',
            (2, 900): 'its stock is limited: the restock time is not known',          # a recording decides: the other vendors are not asked
            (3, 900): 'other vendors borrow its list: a row here would reach them too'})
        # a recording from before the live game cannot give the row, but it holds back what the other vendors would give
        currency = [{'costItems': [{'currencyId': 515, 'amount': 50}]}]
        rows, held = export.plan(decisions[:1], WORLD, {(1, 900): [('other', 70450, currency)]}, extra)
        self.assertEqual((rows, held[0].reason), ([], 'no recording of the live game shows what it costs, and an earlier recording says: '
                                                      'it costs items or a currency: the extended cost is not known'))
        self.assertEqual([row.key for row in export.plan(decisions[:1], WORLD, {(1, 900): [('other', 70450, MONEY)]}, extra)[0]], [(1, 900, 0, 1)])
        # a private recording alone makes a private row; where the world's vendors say the same, the row can be published
        rows, _held = export.plan([ready('sells', 'npc', 1, 900), ready('sells', 'npc', 1, 902)], WORLD,
                                  {(1, 900): [('private', LIVE, MONEY)], (1, 902): [('private', LIVE, MONEY)]}, extra)
        self.assertEqual([(row.key, row.allowed, row.data['sold'][:12]) for row in rows], [((1, 900, 0, 1), 'public', 'no recording'), ((1, 902, 0, 1), 'private', 'a recording ')])
        self.assertEqual(export.plan([ready('sells', 'npc', 1, 900)], WORLD, {(1, 900): [('private', LIVE, limited)]}, extra)[1][0].reason,
                         'its stock is limited: the restock time is not known')                # the private recording says it is not plain: nothing overrules it
        # a decision only a private source states stays private, whatever the price rests on
        self.assertEqual([row.allowed for row in export.plan([ready('sells', 'npc', 1, 900, allowed='private')], WORLD, {}, extra)[0]], ['private'])
        self.assertEqual(export.plan([ready('sells', 'npc', 1, 900)], WORLD, {}, {k: v for k, v in EXTRA.items() if k != 'sold'})[1][0].reason,
                         'no recording of the live game shows what it costs, and no other vendor players can reach sells it')

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

    def test_a_quest_brings_the_texts_a_recording_has(self):
        heard = lambda use, *wordings: {'use': use, 'source': 'eglink' if use == 'public' else 'icyveins', 'build': LIVE, 'wordings': list(wordings)}
        pair = [ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200), ready('quest', 'quest', 200, rule='record-seen-live')]
        row = lambda texts, **more: next(r for r in self.plan(pair, {200: known(texts=texts, **more)})[0] if r.table == 'quest_template')
        both = row({'complete': heard('public', 'Well done.\n\nHere.'), 'progress': heard('public', 'Not yet?'), 'accept': heard('public', 'Go.')})
        self.assertEqual(both.data['texts'], {'quest_offer_reward': 'Well done.$B$BHere.', 'quest_request_items': 'Not yet?'})     # the offer is the record's description
        self.assertEqual(export.described(both)['texts'], {'quest_offer_reward': 'eglink@70862', 'quest_request_items': 'eglink@70862'})
        self.assertEqual(both.data['sources'], {'eglink'})
        # two wordings are two answers: neither is taken; a text only a source without a licence recorded stays out of a row that may be published
        self.assertEqual(row({'complete': heard('public', 'To a mage.', 'To a warrior.'), 'progress': heard('private', 'Not yet?')}).data['texts'], {})
        private = row({'progress': heard('private', 'Not yet?')}, use='private')
        self.assertEqual((private.allowed, private.data['texts'], private.data['sources']), ('private', {'quest_request_items': 'Not yet?'}, {'icyveins'}))
        self.assertEqual(row(None).data['texts'], {})
        statements = ';\n'.join(export.body([both], 'f.sql'))
        self.assertIn("NOT EXISTS (SELECT 1 FROM `quest_offer_reward` c WHERE c.`ID` = p.`ID`)", statements)       # a text the world holds is left alone
        self.assertIn("INSERT INTO `quest_request_items` (`ID`, `CompletionText`, `VerifiedBuild`) SELECT p.`ID`, p.`CompletionText`, 0", statements)
        self.assertNotIn('quest_offer_reward', ';\n'.join(export.body([row(None)], 'f.sql')))

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
        self.assertEqual(held, {('gives', 9, 200): 'it waits for its NPC, which is held back',
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
                return self.entries if "kind = 'entry'" in sql else self.texts if "kind = 'text'" in sql else self.records
            texts = []
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
        said = lambda source, quest, build, **moments: {'source': source, 'subject': str(quest), 'build': str(build),
                                                        'data': json.dumps({m: [{'text': t} if isinstance(t, str) else t for t in lines] for m, lines in moments.items()})}
        stored = Stored([record('eglink', q, LIVE) for q in (300, 301, 302)], [])
        stored.texts = [
            said('eglink', 300, LIVE, complete=['Done.'], progress=['Yet?'], accept=[{'text': 'The cache.', 'template': 'questCache'}]),
            said('eglink', 300, LIVE + 9, complete=['Done.']), said('eglink', 300, 70450, complete=['Before the live game.']),
            said('icyveins', 300, LIVE + 20, complete=['What a private source saw.']), said('wowhead', 300, LIVE, complete=['A reference.']),
            said('eglink', 301, LIVE, complete=['To you, $r.']), said('eglink', 301, LIVE + 9, complete=['To you, skyborne.']),
            said('icyveins', 302, LIVE, progress=['Only here.']), said('eglink', 399, LIVE, complete=['No record of it.']),
            {'source': 'eglink', 'subject': '302', 'build': str(LIVE), 'data': '{broken'}, {'source': 'eglink', 'subject': '302', 'build': str(LIVE), 'data': json.dumps({'complete': 'junk', 'progress': ['junk', {'text': 5}]})}]
        heard = export.load_quests(stored, REGISTRY, range(300, 400))
        # a publishable source's wordings over every live build, under its newest recording; the cache's copy of the offer is not a window
        self.assertEqual(heard[300]['texts'], {'complete': {'use': 'public', 'source': 'eglink', 'build': LIVE + 9, 'wordings': ['Done.', 'Done.']},
                                               'progress': {'use': 'public', 'source': 'eglink', 'build': LIVE, 'wordings': ['Yet?']}})
        # two builds, two wordings: one of them is the recorder's guess, and nothing says which
        self.assertEqual(quests.said(heard[301]['texts']['complete']['wordings']), (None, '2 wordings were recorded'))
        self.assertEqual(heard[302]['texts'], {'progress': {'use': 'private', 'source': 'icyveins', 'build': LIVE, 'wordings': ['Only here.']}})
        self.assertNotIn(399, heard)
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


CREATURE = {'name': 'Rix Xizzix', 'title': 'Lost and Found', 'classification': 0, 'type': 7, 'unitClass': 1, 'movementInfoId': 1693, 'creatureDifficultyId': 9009,
            'flags': [134217728, 0, 0], 'hpMultiplier': 1.25, 'energyMultiplier': 1.0, 'displays': [{'displayId': 500, 'probability': 100.0, 'scale': 1.0}]}


def creature(record=None, use='public', **more):
    # a player talked to it (the recording gives no side), QuestieDB names the side and the level
    return dict({'use': use, 'source': 'eglink' if use == 'public' else 'icyveins', 'build': LIVE, 'record': record or CREATURE, 'stated': 'AH', 'side_source': 'questie',
                 'talked': '', 'seen_source': 'eglink', 'level': (45, 45, 'questie')}, **more)


class Npcs(unittest.TestCase):
    EXTRA = dict(EXTRA, model_info={500, 501})

    def plan(self, decisions, creatures, records=None, prices=None):
        rows, held = export.plan(decisions, WORLD, prices or {}, self.EXTRA, records, creatures)
        return rows, {(h.decision['kind'], h.decision['subject'], h.decision['object']): h.reason for h in held}

    def test_an_npc_comes_with_what_waits_for_it(self):
        objective = dict(RECORD, objectives=[{'id': 5001, 'typeId': 0, 'objectId': 9, 'storageIndex': 0, 'amount': 1}])
        rows, held = self.plan([ready('npc', 'npc', 9, rule='record-seen-live'), ready('gives', 'npc', 9, 100), ready('sells', 'npc', 9, 900),
                                ready('quest', 'quest', 200), ready('gives', 'npc', 9, 200), ready('takes', 'npc', 1, 200)],
                               {9: creature()}, {200: known(objective)}, {(9, 900): [('public', LIVE, MONEY)]})
        self.assertEqual(held, {})
        rows.sort(key=lambda row: (export.ORDER.index(row.table), row.key))            # as the file orders them
        self.assertEqual([(row.table, row.key) for row in rows], [
            ('creature_template', (9,)), ('quest_template', (200,)), ('creature_queststarter', (9, 100)), ('creature_queststarter', (9, 200)),
            ('creature_questender', (1, 200)), ('npc_vendor', (9, 900, 0, 1))])
        npc = rows[0]
        self.assertEqual((npc.comment, npc.allowed, npc.note), ('Rix Xizzix', 'public', 'record-seen-live: eglink@70862, questie:trace'))
        self.assertEqual((npc.data['side'], npc.data['side_how'], npc.data['side_from'], npc.data['level_from'], npc.data['sources'], npc.data['npc'].template['faction']),
                         ('AH', 'questie', 'questie', 'questie', {'eglink', 'questie'}, 35))
        self.assertEqual((rows[1].data['needs'], rows[2].comment), ([9], 'Rix Xizzix gives First Steps'))
        text = ';\n'.join(export.body(rows, 'f.sql'))
        self.assertLess(text.index('INSERT INTO `creature_template`'), text.index('INSERT INTO `quest_template`'))          # the NPC, then what needs it
        self.assertLess(text.index('INSERT INTO `quest_template`'), text.index('INSERT INTO `creature_queststarter`'))

    def test_what_keeps_an_npc_from_being_written(self):
        decisions = [ready('npc', 'npc', number) for number in (9, 10, 11, 12, 13, 14, 15, 16, 17, 18)] + [ready('gives', 'npc', 10, 100), ready('sells', 'npc', 11, 900)]
        _rows, held = self.plan(decisions, {
            10: creature(stated=None, talked=None), 11: creature(stated=None, talked=None, reactions={'Horde': [2]}), 12: creature(level=None),
            17: creature(talked=None), 18: creature(fought=True),
            13: creature(dict(CREATURE, unitClass=3)), 14: creature(dict(CREATURE, displays=[{'displayId': 500}, {'displayId': 777}])),
            15: creature(record=None), 16: {'use': 'public', 'source': 'eglink', 'build': LIVE, 'record': None}}, prices={(11, 900): [('public', LIVE, MONEY)]})
        self.assertEqual(held, {
            ('npc', 9, 0): 'no record a row may be written from', ('npc', 10, 0): 'nothing states whom it is friendly to',
            ('npc', 17, 0): 'only a list says whom it is friendly to: no player was seen talking to it',
            ('npc', 18, 0): 'players fought it: what a monster needs is not known',
            ('npc', 11, 0): 'it is not friendly to players: what a monster needs is not known', ('npc', 12, 0): 'nothing states its level',
            ('npc', 13, 0): 'its record cannot be written: unitClass is not a class a creature can have',
            ('npc', 14, 0): 'the world has no size for its model: creature_model_info (display 777)', ('npc', 16, 0): 'no record a row may be written from',
            ('gives', 10, 100): 'it waits for its NPC, which is held back', ('sells', 11, 900): 'it waits for its NPC, which is held back'})
        rows, _held = self.plan([ready('npc', 'npc', 15)], {15: creature()})
        self.assertEqual(len(rows), 1)                                          # (15 above was given the default record: written)
        seen = self.plan([ready('npc', 'npc', 9)], {9: creature(stated=None, talked=None, reactions={'Horde': [5]}, level=(3, 4, 'eglink'))})[0][0]
        self.assertEqual((seen.data['side'], seen.data['side_how'], seen.data['side_from'], seen.data['level_from'], seen.data['sources'], seen.data['npc'].template['faction']),
                         ('H', 'reactions', 'eglink', 'eglink', {'eglink'}, 83))
        talked = self.plan([ready('npc', 'npc', 9)], {9: creature(talked='Alliance')})[0][0]              # the recording's side comes before the list's
        self.assertEqual((talked.data['side'], talked.data['side_how'], talked.data['side_from'], talked.data['npc'].template['faction']), ('A', 'talked', 'eglink', 84))

    def test_what_hangs_on_an_npc_goes_where_it_goes_or_nowhere(self):
        objective = dict(RECORD, objectives=[{'id': 5001, 'typeId': 0, 'objectId': 9, 'storageIndex': 0, 'amount': 1}])
        decisions = [ready('npc', 'npc', 9), ready('gives', 'npc', 9, 100), ready('sells', 'npc', 9, 900), ready('quest', 'quest', 200),
                     ready('gives', 'npc', 1, 200), ready('takes', 'npc', 1, 200)]
        prices = {(9, 900): [('public', LIVE, MONEY)]}
        rows, _held = self.plan(decisions, {9: creature()}, {200: known(objective)}, prices)
        npc, others = rows[0], rows[1:]
        # the world refused the NPC: nothing that needs it is left, not even the quest that only has an objective on it
        kept, dropped = export.settle(others, WORLD)
        self.assertEqual((kept, sorted((row.table, why) for row, why in dropped)), ([], [
            ('creature_questender', 'it waits for its quest, which is held back'), ('creature_queststarter', 'it waits for its NPC, which is held back'),
            ('creature_queststarter', 'it waits for its quest, which is held back'), ('npc_vendor', 'it waits for its NPC, which is held back'),
            ('quest_template', 'an objective needs an NPC that is held back (NPC 9)')]))
        self.assertEqual(export.settle(others, WORLD, {('creature_template', (9,))}), (others, []))        # an earlier export carries the NPC
        self.assertEqual(export.settle(rows, WORLD), (rows, []))
        # an NPC from a record that may not be published: all of it is private
        rows, _held = self.plan(decisions, {9: creature(use='private')}, {200: known(objective)}, prices)
        self.assertEqual({row.allowed for row in rows}, {'private'})
        self.assertEqual(len(rows), 6)

    def test_the_npc_s_statements(self):
        rows, _held = self.plan([ready('npc', 'npc', 9), ready('npc', 'npc', 10)],
                                {9: creature(), 10: creature(dict(CREATURE, name="Bare O'Name", title=None, displays=[{'displayId': 500}, {'displayId': 501, 'scale': 0.5}]),
                                                             stated='A', level=(5, 6, 'questie'))})
        text = ';\n'.join(export.npc_block(rows, 'f.sql')) + ';\n'
        self.assertIn('CREATE TEMPORARY TABLE `everlake_build_npcs` (`n` INT NOT NULL PRIMARY KEY, `note` VARCHAR(255) NOT NULL, `missing` TINYINT NOT NULL DEFAULT 0) '
                      'SELECT `entry`, `KillCredit1`, `KillCredit2`, `name`, `subname`, `IconName`, `faction`, `Classification`, `type`, `family`, `movementId`, `unit_class`, '
                      '`BaseAttackTime`, `RangeAttackTime`, `unit_flags2` FROM `creature_template` WHERE 0;', text)
        self.assertIn("(1, 9, 0, 0, 'Rix Xizzix', 'Lost and Found', NULL, 35, 0, 7, 0, 1693, 1, 2000, 2000, 2048, 'seen-live: eglink@70862, questie:trace'), -- Rix Xizzix\n"
                      "(2, 10, 0, 0, 'Bare O''Name', NULL, NULL, 84, 0, 7, 0, 1693, 1, 2000, 2000, 2048, 'seen-live: eglink@70862, questie:trace') -- Bare O'Name\n;\n", text)
        for guard in ("NOT EXISTS (SELECT 1 FROM `creature_template` t WHERE t.`entry` = s.`entry`)",
                      "r.`tbl` IN ('creature_template', 'creature_template_difficulty', 'creature_template_model', 'creature_classic_level') AND r.`k1` = s.`entry`)",
                      "NOT EXISTS (SELECT 1 FROM `creature_template_difficulty` c WHERE c.`Entry` = s.`entry`)",
                      "NOT EXISTS (SELECT 1 FROM `creature_classic_level` c WHERE c.`entry` = s.`entry`)",
                      "UPDATE `everlake_build_models` p SET p.`unknown` = 1 WHERE NOT EXISTS (SELECT 1 FROM `creature_model_info` i WHERE i.`DisplayID` = p.`CreatureDisplayID`);",
                      "NOT EXISTS (SELECT 1 FROM `everlake_build_models` p WHERE p.`CreatureID` = s.`entry` AND p.`unknown` = 1)"):
            self.assertIn(guard, text)
        self.assertIn("(1, 9, 0, 500, 1.0, 100.0),\n(2, 10, 0, 500, 1, 1),\n(3, 10, 1, 501, 0.5, 1)\n;\n", text)
        self.assertIn("(1, 9, 0, 1.25, 1.0, 9009, 134217728, 0, 0),\n", text)
        self.assertIn("(1, 9, 45, 45),\n(2, 10, 5, 6)\n;\n", text)
        self.assertIn("INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`, `VerifiedBuild`) "
                      "SELECT p.`CreatureID`, p.`Idx`, p.`CreatureDisplayID`, p.`DisplayScale`, p.`Probability`, 0 FROM `everlake_build_models` p "
                      "JOIN `everlake_build_npcs` s ON s.`entry` = p.`CreatureID` WHERE s.`missing` = 1 ORDER BY p.`n`;", text)
        self.assertIn("SELECT 'creature_template_difficulty', p.`Entry`, p.`DifficultyID`, 'f.sql', s.`note`", text)
        self.assertEqual((text.count('CREATE TEMPORARY TABLE'), text.count('DROP TEMPORARY TABLE')), (4, 4))
        made = export.manifest('f.sql', 'x', 'public', rows, {}, {}, [])
        self.assertEqual(made['rows'][0], {'table': 'creature_template', 'key': [9], 'kind': 'npc', 'rule': 'seen-live', 'witnesses': ['eglink@70862', 'questie:trace'],
                                           'says': 'Rix Xizzix', 'record': 'eglink@70862', 'side': 'AH', 'side_from': 'questie: questie', 'faction': 35, 'level': [45, 45],
                                           'level_from': 'questie', 'models': 1, 'unread': []})
        self.assertEqual(made['left_to_defaults'], list(npcs.LEFT))
        self.assertEqual(export.counts(rows), '2 creature_template')

    def test_the_record_the_side_and_the_level_of_an_npc(self):
        class Stored:
            def __init__(self, rows, entries):
                self.rows, self.entries = rows, entries

            def query(self, sql, _database):
                return self.entries if "kind = 'entry'" in sql else self.rows
        fact = lambda source, kind, npc, build, data: {'source': source, 'kind': kind, 'subject': str(npc), 'build': str(build), 'data': json.dumps(data)}
        entry = lambda npc, parts, source='questie': {'source': source, 'subject': str(npc), 'data': json.dumps({'parts': parts})}
        found = export.load_npcs(Stored(
            [fact('eglink', 'creature', 9, 70450, {'name': 'beta'}), fact('eglink', 'creature', 9, LIVE, {'name': 'live'}), fact('icyveins', 'creature', 9, LIVE + 5, {'name': 'private'}),
             fact('eglink', 'seen', 9, LIVE, {'reactions': {'Horde': [5]}, 'levels': {'4': 2, '5': 1, '\u00b2': 1}}),
             fact('eglink', 'seen', 9, LIVE + 1, {'reactions': {'Horde': [6], 'Alliance': [2]}, 'levels': {'7': 1}}),
             fact('eglink', 'talked', 9, LIVE, {'side': 'Alliance', 'levels': [8]}), fact('eglink', 'talked', 9, LIVE + 1, {'side': 'Horde', 'interactions': ['QuestGiver']}),
             fact('eglink', 'seen', 9, 70450, {'reactions': {'Alliance': [8]}, 'deaths': 5}), fact('eglink', 'talked', 9, 70450, {'side': 'Alliance'}),      # before the live game
             fact('icyveins', 'seen', 9, LIVE, {'reactions': {'Alliance': [8], 'Horde': [3]}}),                    # may not give rows: it can only say "not a friend"
             fact('eglink', 'creature', 10, LIVE, {'name': 'ten'}), fact('eglink', 'talked', 10, LIVE, {'levels': [3]}),
             fact('eglink', 'creature', 11, LIVE, {'name': 'eleven'}), fact('eglink', 'seen', 11, LIVE, {'reactions': {'Horde': [5]}, 'deaths': 2}),
             fact('eglink', 'creature', 12, LIVE, {'name': 'twelve'}), fact('icyveins', 'seen', 12, LIVE, {'combatLog': {'entries': 1}, 'levels': {'9': 1}}),
             fact('eglink', 'seen', 13, LIVE, {'reactions': {'Horde': [5]}}), fact('wowhead', 'creature', 14, LIVE, {'name': 'a reference'}),
             fact('eglink', 'creature', 15, LIVE, {'name': 'odd', 'displays': 5})],
            [entry(10, {'generated': {'friendlyToFaction': 'A', 'minLevel': 5, 'maxLevel': 6}, 'trace': {'minLevel': 7, 'maxLevel': 7}, 'fix': {'friendlyToFaction': 'AH'}}),
             entry(11, {'generated': {'friendlyToFaction': 'A', 'minLevel': 5, 'maxLevel': 6}, 'fix': {'friendlyToFaction': {}, 'minLevel': 9, 'maxLevel': 3}}),
             entry(12, {'generated': {'minLevel': 5, 'maxLevel': 6}}, 'icyveins')]), REGISTRY, range(9, 20))
        self.assertEqual(sorted(found), [9, 10, 11, 12, 15])                        # a sighting or a reference's record alone is no record to write from
        self.assertEqual((found[9]['record'], found[9]['use'], found[9]['build']), ({'name': 'live'}, 'public', LIVE))
        self.assertEqual((found[9]['reactions'], found[9]['seen_source'], found[9]['level']), ({'Horde': [5, 6], 'Alliance': [2]}, 'eglink', (4, 8, 'eglink')))
        self.assertEqual((found[9]['talked'], found[9]['fought'], found[9]['against']), ('Horde', False, ['H']))      # the newest recording's side
        self.assertEqual((found[10]['stated'], found[10]['side_source'], found[10]['level'], found[10]['talked']), ('AH', 'questie', (7, 7, 'questie'), ''))       # the later part replaces
        self.assertEqual((found[11]['stated'], found[11]['level'], found[11]['fought'], 'talked' in found[11]), ({}, None, True, False))      # also with nothing
        # a private source's entry and levels are not read, but what it saw of a fight still holds the NPC back
        self.assertEqual((found[12].get('stated'), found[12].get('level'), found[12]['fought']), (None, None, True))
        self.assertEqual(export.load_model_info(Stored([{'DisplayID': '500'}], []), 'world', {**found, 16: creature()}), {500})      # junk displays are passed over


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

    def test_how_the_world_s_vendors_list_an_item(self):
        self.db.execute("""
INSERT INTO creature VALUES (1, 2), (2, 2), (3, 6), (4, 7), (5, 3);
INSERT INTO creature_template VALUES (6, '[DNT] Test Vendor', 128), (7, 'Greeter', 2), (8, 'Never Placed', 128), (10, NULL, 128);
INSERT INTO npc_vendor (entry, slot, item, maxcount, incrtime, PlayerConditionID, BonusListIDs) VALUES
  (6, 1, 800, 0, 0, 0, NULL), (7, 1, 800, 0, 0, 0, ''), (8, 1, 800, 0, 0, 0, NULL), (4, 1, 801, 2, 7200, 0, NULL), (6, 2, 801, 0, 0, 9, NULL), (8, 2, 801, 0, 0, 0, '5'),
  (77, 1, 800, 0, 0, 0, NULL), (10, 1, 800, 0, 0, 0, NULL), (2, 8, 802, 0, 0, 0, NULL), (4, 2, 802, 0, 0, 0, NULL);
INSERT INTO npc_vendor (entry, slot, item, type) VALUES (2, 9, 900, 2);
CREATE TABLE game_event_npc_vendor (eventEntry tinyint, guid bigint unsigned, slot smallint, item int unsigned, maxcount int unsigned NOT NULL DEFAULT 0,
  incrtime int unsigned NOT NULL DEFAULT 0, ExtendedCost int unsigned NOT NULL DEFAULT 0, type tinyint unsigned NOT NULL DEFAULT 1, BonusListIDs mediumtext,
  PlayerConditionID int unsigned NOT NULL DEFAULT 0, IgnoreFiltering tinyint unsigned NOT NULL DEFAULT 0);
INSERT INTO game_event_npc_vendor (eventEntry, guid, slot, item, ExtendedCost) VALUES (1, 5, 1, 802, 44), (1, 5, 2, 800, 0);
""", self.WORLD_DB)
        asked = [{'kind': 'sells', 'subject_kind': 'npc', 'subject': 1, 'object': item} for item in (800, 801, 802, 900, 900, 950)] + [
            {'kind': 'gives', 'subject_kind': 'npc', 'subject': 1, 'object': 100}]
        sold = export.load_extra(self.db, self.WORLD_DB, asked)['sold']
        L = export.Listing
        # Bert is spawned and a vendor. Not vendors players can reach: one that reads like a leftover, a greeter without the vendor flag,
        # one never placed, one without a template, one without a name, and Cora, who sells it during an event only
        self.assertEqual(sorted(sold[800]), [L(2, True, True), L(3, True, False), L(6, True, False), L(7, True, False), L(8, True, False), L(10, True, False), L(77, True, False)])
        # limited stock, a condition, a bonus list: none of them plain
        self.assertEqual(sorted(sold[801]), [L(2, True, True), L(4, False, False), L(6, False, False), L(8, False, False)])
        self.assertEqual(sorted(sold[802]), [L(2, True, True), L(3, False, False), L(4, True, False)])          # for a currency during the event; Dora is not placed
        self.assertEqual(sold[900], [L(2, False, True)])                # for an extended cost; the currency row of the same number is not an item
        self.assertNotIn(950, sold)
        self.assertEqual(export.elsewhere(sold[800], 1), ('', 1))
        self.assertEqual(export.elsewhere(sold[802], 1)[1], 0)

        # the row goes in on the replayed world like any other, and what an export added is not the world's own word afterwards
        rows, held = export.plan([ready('sells', 'npc', 1, 800, rule='trusted-source')], self.world(), {}, export.load_extra(self.db, self.WORLD_DB, asked))
        self.assertEqual((held, rows[0].data), ([], {'sold': "no recording: the world's other vendors of it (1) all sell it for money, in endless supply"}))
        file = '2026_11_13_950_world_everlake_build.sql'
        self.assertEqual(export.trial(self.db, self.WORLD_DB, [(file, rows)]), {file: {('npc_vendor', (1, 800, 0, 1))}})
        self.db.execute(export.LEDGER_DDL + ";\nINSERT INTO everlake_import_rows (tbl, k1, k2, k3, k4, file, note) VALUES ('npc_vendor', 2, 800, 0, 1, 'earlier.sql', '')",
                        self.WORLD_DB)
        again = export.load_extra(self.db, self.WORLD_DB, asked)['sold']
        self.assertNotIn(L(2, True, True), again[800])                  # Bert's row was an export's: the rule does not rest on it
        self.assertEqual(export.elsewhere(again[800], 1)[1], 0)
        self.assertIn(L(2, True, True), again[801])

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
            ('gives', 9, 100): 'it waits for its NPC, which is held back', ('quest', 200, 0): 'no record a row may be written from',
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
                             Fact('quest', 'quest', 201, 0, LIVE, 1, clash), Fact('quest', 'quest', 202, 0, 70450, 1, RECORD),
                             Fact('text', 'quest', 200, 0, 70450, 1, {'complete': [{'text': 'Said before the live game.'}]}),
                             Fact('text', 'quest', 200, 0, LIVE, 2, {'complete': [{'text': "You've done it, $N.\n\nIt's 'over'."}],
                                                                    'progress': [{'text': 'Are they gone?'}, {'text': 'Are they gone yet?'}],
                                                                    'accept': [{'text': 'They dig too deep.', 'template': 'questCache'}]})],
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
CREATE TABLE quest_offer_reward (ID int unsigned PRIMARY KEY, Emote1 smallint NOT NULL DEFAULT 0, EmoteDelay1 int unsigned NOT NULL DEFAULT 0, RewardText mediumtext,
  VerifiedBuild int NOT NULL DEFAULT 99);
CREATE TABLE quest_request_items (ID int unsigned PRIMARY KEY, EmoteOnComplete smallint unsigned NOT NULL DEFAULT 0, CompletionText mediumtext, VerifiedBuild int NOT NULL DEFAULT 99);
INSERT INTO quest_request_items (ID, CompletionText) VALUES (203, 'What the world says already.');
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
                # the hand-in text of the live game's recording, its line breaks as $B; two wordings of the progress text: none
                self.assertEqual(self.table('SELECT ID, Emote1, RewardText, VerifiedBuild FROM quest_offer_reward'), [('200', '0', "You've done it, $N.$B$BIt's 'over'.", '0')])
                self.assertEqual(self.table('SELECT ID FROM quest_request_items'), [('203',)])
                self.assertEqual(self.table('SELECT id, quest FROM creature_queststarter'), [('1', '200')])
                self.assertEqual(self.table('SELECT id, quest FROM creature_questender'), [('2', '200')])
                self.assertEqual(self.table('SELECT entry, npcflag FROM creature_template ORDER BY entry'), [('1', '2'), ('2', '2'), ('3', '0')])
                self.assertEqual(self.table('SELECT tbl, k1, k2, note FROM everlake_import_rows ORDER BY tbl, k1, k2'), [
                    ('creature_questender', '2', '200', 'seen-live: eglink@70862'), ('creature_queststarter', '1', '200', 'seen-live: eglink@70862'),
                    ('quest_classic_level', '200', '0', 'record-seen-live: eglink@70862'), ('quest_classic_money', '200', '0', 'record-seen-live: eglink@70862'),
                    ('quest_objectives', '5001', '0', 'record-seen-live: eglink@70862'), ('quest_objectives', '5002', '0', 'record-seen-live: eglink@70862'),
                    ('quest_offer_reward', '200', '0', 'record-seen-live: eglink@70862'),
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

            # a text the world holds already is left alone, and the quest still goes in, with the text the world lacks
            heard = lambda text: {'use': 'public', 'source': 'eglink', 'build': LIVE, 'wordings': [text]}
            other = dict(RECORD, title='Second', objectives=[{'id': 6001, 'typeId': 0, 'objectId': 3, 'storageIndex': 0, 'amount': 1}])
            row, why = export.quest_row(ready('quest', 'quest', 203, rule='record-seen-live'),
                                        known(other, texts={'complete': heard('Thanks.'), 'progress': heard('Not what the world says.')}), world)
            self.assertEqual(why, '')
            file = '2026_11_15_950_world_everlake_build.sql'
            self.assertEqual(export.trial(self.db, self.WORLD_DB, [(file, [row])]), {file: {
                ('quest_template', (203,)), ('quest_objectives', (6001,)), ('quest_classic_level', (203,)), ('quest_template_classic_level', (203, 2)),
                ('quest_classic_money', (203,)), ('quest_reward_display_spell', (203, 0)), ('quest_offer_reward', (203,))}})
            for _run in (1, 2):
                self.db.execute(';\n'.join(export.body([row], file)) + ';\n', self.WORLD_DB)
                self.assertEqual(self.table('SELECT ID, RewardText, VerifiedBuild FROM quest_offer_reward ORDER BY ID'),
                                 [('200', "You've done it, $N.$B$BIt's 'over'.", '0'), ('203', 'Thanks.', '0')])
                self.assertEqual(self.table('SELECT ID, CompletionText, VerifiedBuild FROM quest_request_items'), [('203', 'What the world says already.', '99')])
                self.assertEqual(self.table("SELECT tbl, k1 FROM everlake_import_rows WHERE k1 = 203 AND tbl IN ('quest_offer_reward', 'quest_request_items')"),
                                 [('quest_offer_reward', '203')])                              # only what the file added is recorded as its own


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server to run')
class NpcsOnMySQL(unittest.TestCase):
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
        add = lambda kind, subject, other=0: Decision(kind, 'npc', subject, other, 'add', 'record-seen-live' if kind == 'npc' else 'seen-live', 'public', '', [], [], [eg])
        decisions = [add('npc', 9), add('gives', 9, 100), add('sells', 9, 900),      # friendly to both (QuestieDB), level from QuestieDB
                     add('npc', 8), add('takes', 8, 100),                            # the world cannot show its model
                     add('npc', 7),                                                  # players saw it hostile
                     add('npc', 5),                                                  # only a list calls it friendly
                     add('npc', 6), add('gives', 6, 100)]                            # friendly to the Horde players who saw it, at levels 3 to 4
        path = os.path.join(cls.folder.name, 'decisions.sql')
        resolve.write_sql(path, decisions, {})
        sqlio.execute_file(path, 'tracker')
        stored = {'eglink': [Fact('creature', 'npc', 9, 0, LIVE, 2, CREATURE), Fact('creature', 'npc', 8, 0, LIVE, 1, dict(CREATURE, name='No Size', displays=[{'displayId': 777}])),
                             Fact('talked', 'npc', 9, 0, LIVE, 1, {'interactions': ['QuestGiver', 'Merchant'], 'levels': [45]}),          # no side recorded: QuestieDB names it
                             Fact('talked', 'npc', 8, 0, LIVE, 1, {'side': 'Alliance', 'levels': [5]}),
                             Fact('creature', 'npc', 5, 0, LIVE, 1, dict(CREATURE, name='Listed Only')),
                             Fact('creature', 'npc', 7, 0, LIVE, 1, dict(CREATURE, name='Gnoll')), Fact('seen', 'npc', 7, 0, LIVE, 1, {'reactions': {'Alliance': [2]}, 'levels': {'9': 1}}),
                             Fact('creature', 'npc', 6, 0, LIVE, 1, dict(CREATURE, name='Grunt', title=None, displays=[{'displayId': 500, 'scale': 1.0}, {'displayId': 501, 'scale': 0.5}])),
                             Fact('seen', 'npc', 6, 0, LIVE, 1, {'reactions': {'Horde': [5]}, 'levels': {'3': 1, '4': 2}}),
                             Fact('sells', 'npc', 9, 900, LIVE, 1, {'listings': [{'itemId': 900, 'name': 'Bread', 'costs': {'5': 25}}]})],
                  'questie': [Fact('entry', 'npc', 9, 0, 0, 0, {'parts': {'generated': {'friendlyToFaction': 'AH', 'minLevel': 45, 'maxLevel': 45}}}),
                              Fact('entry', 'npc', 5, 0, 0, 0, {'parts': {'generated': {'friendlyToFaction': 'AH', 'minLevel': 60, 'maxLevel': 60}}}),
                              Fact('entry', 'npc', 8, 0, 0, 0, {'parts': {'generated': {'friendlyToFaction': 'A', 'minLevel': 5, 'maxLevel': 5}}})]}
        for source, rows in stored.items():
            path = os.path.join(cls.folder.name, source + '.sql')
            facts.write_sql(path, source, source[0] * 40, REGISTRY.source(source)['licence'], REGISTRY.source(source)['use'], rows)
            sqlio.execute_file(path, 'tracker')
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\nCREATE DATABASE `{cls.WORLD_DB}` CHARACTER SET utf8mb4;\n', 'information_schema')
        sqlio.execute("""
CREATE TABLE ft_replay_files (id int PRIMARY KEY, name varchar(255), source varchar(64), sha256 char(64), state varchar(16), error text);
INSERT INTO ft_replay_files VALUES (1, 'a.sql', 'core', '', 'applied', NULL);
CREATE TABLE quest_template (ID int unsigned PRIMARY KEY, LogTitle text); INSERT INTO quest_template VALUES (100, 'First Steps');
CREATE TABLE creature_template (entry int unsigned NOT NULL DEFAULT 0, KillCredit1 int unsigned NOT NULL DEFAULT 0, KillCredit2 int unsigned NOT NULL DEFAULT 0, name mediumtext,
  subname mediumtext, IconName varchar(64), faction smallint unsigned NOT NULL DEFAULT 0, npcflag bigint unsigned NOT NULL DEFAULT 0, speed_run float NOT NULL DEFAULT 1.14286,
  Classification tinyint unsigned NOT NULL DEFAULT 0, BaseAttackTime int unsigned NOT NULL DEFAULT 0, RangeAttackTime int unsigned NOT NULL DEFAULT 0,
  unit_class tinyint unsigned NOT NULL DEFAULT 0, unit_flags2 int unsigned NOT NULL DEFAULT 0, family int NOT NULL DEFAULT 0, type tinyint unsigned NOT NULL DEFAULT 0,
  movementId int unsigned NOT NULL DEFAULT 0, VerifiedBuild int NOT NULL DEFAULT 99, PRIMARY KEY (entry));
INSERT INTO creature_template (entry, name) VALUES (1, 'Anna');
CREATE TABLE creature_template_difficulty (Entry int unsigned NOT NULL, DifficultyID int NOT NULL DEFAULT 0, HealthModifier float NOT NULL DEFAULT 1, ManaModifier float NOT NULL DEFAULT 1,
  DamageModifier float NOT NULL DEFAULT 1, CreatureDifficultyID int NOT NULL DEFAULT 0, TypeFlags int unsigned NOT NULL DEFAULT 0, TypeFlags2 int unsigned NOT NULL DEFAULT 0,
  TypeFlags3 int unsigned NOT NULL DEFAULT 0, VerifiedBuild int NOT NULL DEFAULT 99, PRIMARY KEY (Entry, DifficultyID));
CREATE TABLE creature_template_model (CreatureID int unsigned NOT NULL, Idx int unsigned NOT NULL DEFAULT 0, CreatureDisplayID int unsigned NOT NULL, DisplayScale float NOT NULL DEFAULT 1,
  Probability float NOT NULL DEFAULT 0, VerifiedBuild int NOT NULL DEFAULT 99, PRIMARY KEY (CreatureID, Idx));
CREATE TABLE creature_classic_level (entry int unsigned NOT NULL PRIMARY KEY, level_min tinyint unsigned NOT NULL, level_max tinyint unsigned NOT NULL);
CREATE TABLE creature_model_info (DisplayID int unsigned NOT NULL PRIMARY KEY, BoundingRadius float NOT NULL DEFAULT 0, CombatReach float NOT NULL DEFAULT 0);
INSERT INTO creature_model_info VALUES (500, 0.389, 1.5), (501, 0.306, 1.5);
CREATE TABLE creature (guid int PRIMARY KEY, id int); CREATE TABLE gameobject (guid int PRIMARY KEY, id int);
CREATE TABLE gameobject_template (entry int unsigned PRIMARY KEY, name text, type tinyint unsigned NOT NULL);
CREATE TABLE creature_queststarter (id int unsigned, quest int unsigned, VerifiedBuild int NOT NULL DEFAULT 0, PRIMARY KEY (id, quest));
CREATE TABLE creature_questender LIKE creature_queststarter;
CREATE TABLE gameobject_queststarter LIKE creature_queststarter;
CREATE TABLE gameobject_questender LIKE creature_queststarter;
CREATE TABLE npc_vendor (entry int unsigned NOT NULL, slot smallint NOT NULL DEFAULT 0, item int NOT NULL, maxcount int unsigned NOT NULL DEFAULT 0,
  incrtime int unsigned NOT NULL DEFAULT 0, ExtendedCost int unsigned NOT NULL DEFAULT 0, type tinyint unsigned NOT NULL DEFAULT 1, BonusListIDs mediumtext,
  PlayerConditionID int unsigned NOT NULL DEFAULT 0, IgnoreFiltering tinyint unsigned NOT NULL DEFAULT 0, VerifiedBuild int DEFAULT 0, PRIMARY KEY (entry, item, ExtendedCost, type));
""", cls.WORLD_DB)

    @classmethod
    def tearDownClass(cls):
        cls.db.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nDROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\n', 'information_schema')
        cls.folder.cleanup()

    def table(self, sql):
        return [tuple(row.values()) for row in self.db.query(sql, self.WORLD_DB)]

    def test_an_npc_goes_in_whole_once_and_what_waits_for_it_with_it(self):
        with tempfile.TemporaryDirectory() as out:
            folders = {'public': os.path.join(out, 'public'), 'private': os.path.join(out, 'private')}
            result = export.export(self.db, self.WORLD_DB, self.db, REGISTRY, resolve.load_world(self.db, self.WORLD_DB), folders, '2026-11-13')
            path, rows = result['files']['public']
            self.assertEqual([(row.table, row.key) for row in rows], [('creature_template', (6,)), ('creature_template', (9,)), ('creature_queststarter', (6, 100)),
                                                                      ('creature_queststarter', (9, 100)), ('npc_vendor', (9, 900, 0, 1))])
            self.assertEqual({(h.decision['kind'], h.decision['subject'], h.decision['object']): h.reason for h in result['held']}, {
                ('npc', 8, 0): 'the world has no size for its model: creature_model_info (display 777)', ('takes', 8, 100): 'it waits for its NPC, which is held back',
                ('npc', 7, 0): 'it is not friendly to players: what a monster needs is not known',
                ('npc', 5, 0): 'only a list says whom it is friendly to: no player was seen talking to it'})
            self.assertEqual(self.table('SELECT entry FROM creature_template'), [('1',)])              # the trial left nothing
            with open(os.path.join(folders['public'], 'build', os.path.basename(path)[:-4] + '.json'), encoding='utf-8') as handle:
                manifest = json.load(handle)
            self.assertEqual([(r['key'], r['side'], r['side_from'], r['faction'], r['level'], r['level_from']) for r in manifest['rows'][:2]],
                             [([6], 'H', 'eglink: reactions', 83, [3, 4], 'eglink'), ([9], 'AH', 'questie: questie', 35, [45, 45], 'questie')])
            self.assertEqual(manifest['left_to_defaults'], list(npcs.LEFT))
            for _run in (1, 2):
                self.db.execute_file(path, self.WORLD_DB)
                self.assertEqual(self.table('SELECT entry, name, subname, IconName, faction, npcflag, Classification, type, unit_class, movementId, BaseAttackTime, '
                                            'RangeAttackTime, unit_flags2, speed_run, VerifiedBuild FROM creature_template WHERE entry <> 1 ORDER BY entry'), [
                    # the quest pair and the vendor item set the flags: quest giver for both, vendor for Rix
                    ('6', 'Grunt', None, None, '83', '2', '0', '7', '1', '1693', '2000', '2000', '2048', '1.14286', '0'),
                    ('9', 'Rix Xizzix', 'Lost and Found', None, '35', '130', '0', '7', '1', '1693', '2000', '2000', '2048', '1.14286', '0')])
                self.assertEqual(self.table('SELECT Entry, DifficultyID, HealthModifier, ManaModifier, DamageModifier, CreatureDifficultyID, TypeFlags, VerifiedBuild '
                                            'FROM creature_template_difficulty ORDER BY Entry'),
                                 [('6', '0', '1.25', '1', '1', '9009', '134217728', '0'), ('9', '0', '1.25', '1', '1', '9009', '134217728', '0')])
                self.assertEqual(self.table('SELECT CreatureID, Idx, CreatureDisplayID, DisplayScale, Probability, VerifiedBuild FROM creature_template_model ORDER BY CreatureID, Idx'),
                                 [('6', '0', '500', '1', '1', '0'), ('6', '1', '501', '0.5', '1', '0'), ('9', '0', '500', '1', '100', '0')])
                self.assertEqual(self.table('SELECT * FROM creature_classic_level ORDER BY entry'), [('6', '3', '4'), ('9', '45', '45')])
                self.assertEqual(self.table('SELECT id, quest FROM creature_queststarter ORDER BY id'), [('6', '100'), ('9', '100')])
                self.assertEqual(self.table('SELECT entry, slot, item FROM npc_vendor'), [('9', '1', '900')])
                self.assertEqual(self.table("SELECT tbl, k1, k2 FROM everlake_import_rows WHERE tbl LIKE 'creature_template%' OR tbl = 'creature_classic_level' ORDER BY tbl, k1, k2"), [
                    ('creature_classic_level', '6', '0'), ('creature_classic_level', '9', '0'), ('creature_template', '6', '0'), ('creature_template', '9', '0'),
                    ('creature_template_difficulty', '6', '0'), ('creature_template_difficulty', '9', '0'),
                    ('creature_template_model', '6', '0'), ('creature_template_model', '6', '1'), ('creature_template_model', '9', '0')])
            # the world loses the size of a model: the NPC that shows it is refused by the file itself, and its pair with it
            self.db.execute('DELETE FROM creature_template WHERE entry IN (6, 9); DELETE FROM creature_template_difficulty; DELETE FROM creature_template_model; '
                            'DELETE FROM creature_classic_level; DELETE FROM creature_queststarter; DELETE FROM npc_vendor; DELETE FROM everlake_import_rows; '
                            'DELETE FROM creature_model_info WHERE DisplayID = 501', self.WORLD_DB)
            self.db.execute_file(path, self.WORLD_DB)
            self.assertEqual(self.table('SELECT entry FROM creature_template ORDER BY entry'), [('1',), ('9',)])
            self.assertEqual(self.table('SELECT id, quest FROM creature_queststarter'), [('9', '100')])
            self.assertEqual(self.table('SELECT CreatureID FROM creature_template_model'), [('9',)])
            # and what a file added stays out once its owners remove it
            self.db.execute('DELETE FROM creature_template WHERE entry = 9; DELETE FROM creature_template_difficulty; DELETE FROM creature_template_model; '
                            'DELETE FROM creature_classic_level; DELETE FROM creature_queststarter; DELETE FROM npc_vendor', self.WORLD_DB)
            self.db.execute_file(path, self.WORLD_DB)
            self.assertEqual(self.table('SELECT entry FROM creature_template'), [('1',)])
            self.assertEqual(self.table('SELECT COUNT(*) FROM creature_queststarter'), [('0',)])


if __name__ == '__main__':
    unittest.main()
