"""python -m unittest discover -s tools/tests

The last class needs a MySQL server: it runs when FT_TEST_CONFIG names a config.ini of a throwaway server (its
[database] tracker database and a database of its own are created and dropped), and is skipped otherwise.
"""
import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import facts, layers, resolve  # noqa: E402
from ft.facts import Fact  # noqa: E402
from ft.resolve import Evidence  # noqa: E402

REGISTRY = layers.load()
LIVE, BETA = 70862, 70450


def eg(build=LIVE, samples=2):
    return Evidence('eglink', '', build, samples, 'eglink', build >= REGISTRY.live_from, 'public')


def questie(part):
    group, live = REGISTRY.witness('questie', part)
    return Evidence('questie', part, 0, int(live), group, live, 'public', REGISTRY.trusted('questie', part))


UNTRUSTED = questie('generated')._replace(trusted=False)        # the same list, were the registry not to trust it


def other(source, live=False):
    about = REGISTRY.source(source)
    return Evidence(source, '', LIVE if live else 0, 1, about['group'], live, about['use'])


ICY = other('icyveins', live=True)
WORLD = {'quests': {100, 101}, 'npcs': {1, 2, 3, 4}, 'npcs_spawned': {1, 2}, 'objects': {50}, 'objects_spawned': set(),
         'gives': {('npc', 1, 100)}, 'takes': {('npc', 4, 100)}, 'sells': {('npc', 2, 900)}}


def weigh(*witnesses):
    return resolve.weigh(REGISTRY, list(witnesses))


class Witness(unittest.TestCase):
    def test_a_build_of_the_live_game_is_live_a_beta_build_is_not(self):
        self.assertEqual(REGISTRY.live_from, 70755)
        self.assertEqual(REGISTRY.witness('eglink', '', LIVE), ('eglink', True))
        self.assertEqual(REGISTRY.witness('eglink', '', 70755), ('eglink', True))
        self.assertEqual(REGISTRY.witness('eglink', '', BETA), ('eglink', False))
        self.assertEqual(REGISTRY.witness('eglink', '', 0), ('eglink', False))           # no build: not known to be live

    def test_only_a_source_that_records_play_is_ever_live(self):
        self.assertEqual(REGISTRY.witness('icyveins', '', LIVE), ('eglink', True))
        for source in ('vmangos', 'wowhead', 'atlasloot', 'norgannondb', 'databaseforever'):       # whatever build a fact of theirs carries
            self.assertFalse(REGISTRY.witness(source, '', LIVE)[1], source)

    def test_the_parts_of_questiedb_do_not_weigh_the_same(self):
        self.assertEqual(REGISTRY.witness('questie', 'trace'), ('questie', True))
        self.assertEqual(REGISTRY.witness('questie', 'generated'), ('wowhead', False))   # built from Wowhead's pages
        self.assertEqual(REGISTRY.witness('questie', 'fix'), ('questie', False))
        self.assertEqual(REGISTRY.witness('questie', 'dynamic:questFixesHorde'), ('questie', False))
        self.assertEqual(REGISTRY.witness('questie', 'unknown-part', LIVE), ('questie', False))    # a part nobody described is not live
        self.assertEqual(REGISTRY.witness('questie', '', LIVE), ('questie', False))                # nor is the source without a part

    def test_a_registry_that_would_make_everything_live_is_refused(self):
        with open(layers.REGISTRY, encoding='utf-8') as handle:
            raw = json.load(handle)

        def problems(change):
            data = copy.deepcopy(raw)
            change(data)
            return layers.validate(data)
        source = lambda data, sid: next(s for s in data['sources'] if s['id'] == sid)
        self.assertEqual(problems(lambda d: None), [])
        for broken in (lambda d: d.pop('live_from'), lambda d: d.update(live_from=0), lambda d: d.update(live_from=-5), lambda d: d.update(live_from='70755'),
                       lambda d: d.update(live_from=True)):
            self.assertTrue(any('live_from' in p for p in problems(broken)))
        self.assertTrue(any('live is true or false' in p for p in problems(lambda d: source(d, 'questie')['parts']['fix'].update(live='false'))))
        self.assertTrue(any('without ":"' in p for p in problems(lambda d: source(d, 'questie')['parts'].update({'dynamic:x': {}}))))
        self.assertTrue(any('group is a name' in p for p in problems(lambda d: source(d, 'questie')['parts']['fix'].update(group=''))))
        self.assertTrue(any('recorded is true or false' in p for p in problems(lambda d: source(d, 'eglink').update(recorded='yes'))))
        self.assertTrue(any('trusted is true or false' in p for p in problems(lambda d: source(d, 'eglink').update(trusted='yes'))))
        self.assertTrue(any('trusted is true or false' in p for p in problems(lambda d: source(d, 'questie')['parts']['fix'].update(trusted=1))))

    def test_evidence_of_a_stored_fact(self):
        self.assertEqual(resolve.evidence(REGISTRY, 'eglink', LIVE, 3, {'title': 'x'}), [Evidence('eglink', '', LIVE, 3, 'eglink', True, 'public')])
        parts = {'parts': {'generated': ['quest.startedBy'], 'trace': ['npc.questStarts_add']}}
        self.assertEqual(resolve.evidence(REGISTRY, 'questie', 0, 1, parts), [questie('generated'), questie('trace')])
        self.assertEqual(resolve.evidence(REGISTRY, 'questie', 0, 0, {})[0].live, False)
        # only a source made of parts has parts: another source's record may hold a field of that name
        self.assertEqual(resolve.evidence(REGISTRY, 'eglink', LIVE, 3, {'parts': {'trace': []}}), [eg(LIVE, 3)])
        with self.assertRaises(KeyError):
            resolve.evidence(REGISTRY, 'nobody', 0, 0, {})


class Weigh(unittest.TestCase):
    def test_a_live_recording_is_enough(self):
        self.assertEqual(weigh(eg()), ('add', 'seen-live', 'public'))
        self.assertEqual(weigh(questie('trace')), ('add', 'seen-live', 'public'))
        self.assertEqual(weigh(eg(samples=0), questie('generated')), ('add', 'seen-live', 'public'))

    def test_a_source_the_registry_trusts_by_itself(self):
        self.assertTrue(REGISTRY.trusted('questie', 'generated'))       # Wowhead's data, reviewed and shipped by Questie
        for part in ('trace', 'fix', 'dynamic:questFixesHorde', 'no-such-part', ''):
            self.assertFalse(REGISTRY.trusted('questie', part), part)
        self.assertEqual([sid for sid in REGISTRY.sources if REGISTRY.trusted(sid)], [])               # no source as a whole
        self.assertEqual(weigh(questie('generated')), ('add', 'trusted-source', 'public'))
        self.assertEqual(weigh(questie('generated'), questie('fix')), ('add', 'trusted-source', 'public'))
        self.assertEqual(weigh(questie('generated'), eg()), ('add', 'seen-live', 'public'))             # a live recording is still the better reason
        trusted_reference = Evidence('wowhead', '', 0, 1, 'wowhead', False, 'reference', True)
        self.assertEqual(weigh(trusted_reference), ('review', 'reference-only', 'private'))            # trust does not make a reference give rows
        self.assertEqual(weigh(trusted_reference, UNTRUSTED), ('review', 'one-claim', 'public'))       # nor lend its trust to another's row
        trusted_private = Evidence('icyveins', '', 0, 1, 'eglink', False, 'private', True)
        self.assertEqual(weigh(trusted_private), ('add', 'trusted-source', 'private'))
        self.assertEqual(weigh(questie('generated'), eg(BETA)), ('add', 'trusted-source', 'public'))   # the first reason that holds is the one given

    def test_trust_is_given_part_by_part_and_fails_closed(self):
        with open(layers.REGISTRY, encoding='utf-8') as handle:
            raw = json.load(handle)
        questie_source = next(s for s in raw['sources'] if s['id'] == 'questie')
        questie_source['trusted'] = True                               # the whole source marked: its parts still speak for themselves
        questie_source['parts']['dynamic']['trusted'] = True
        registry = layers.Registry(raw)
        self.assertTrue(registry.trusted('questie', 'generated') and registry.trusted('questie', 'dynamic:questFixesHorde'))
        for part in ('trace', 'fix', 'a-part-added-upstream-later', ''):
            self.assertFalse(registry.trusted('questie', part), part)
        next(s for s in raw['sources'] if s['id'] == 'eglink')['trusted'] = True
        self.assertTrue(layers.Registry(raw).trusted('eglink'))        # a source without parts is trusted as a whole
        next(s for s in raw['sources'] if s['id'] == 'wowhead')['trusted'] = True
        self.assertTrue(any('never gives a row' in p for p in layers.validate(raw)))

    def test_two_independent_witnesses_without_a_live_recording(self):
        self.assertEqual(weigh(eg(BETA), UNTRUSTED), ('add', 'two-witnesses', 'public'))
        self.assertEqual(weigh(eg(BETA), questie('fix')), ('add', 'two-witnesses', 'public'))
        self.assertEqual(weigh(other('wowhead'), questie('fix')), ('add', 'two-witnesses', 'public'))      # a reference confirms; QuestieDB gives the row

    def test_one_source_is_one_witness_whatever_its_parts(self):
        self.assertEqual(weigh(questie('fix'), UNTRUSTED, questie('dynamic:questFixesAlliance')), ('review', 'one-claim', 'public'))
        self.assertEqual(weigh(questie('fix')), ('review', 'one-claim', 'public'))
        self.assertEqual(weigh(eg(BETA)), ('review', 'one-claim', 'public'))

    def test_sources_of_one_witness_group_are_one_witness(self):
        self.assertEqual(resolve.independent(REGISTRY, [other('norgannondb'), other('cmangos')]), 1)      # compiled from it
        self.assertEqual(weigh(other('norgannondb'), other('cmangos')), ('review', 'one-claim', 'public'))
        self.assertEqual(weigh(other('wowhead'), UNTRUSTED), ('review', 'one-claim', 'public'))             # the generated list is Wowhead's word
        self.assertEqual(weigh(eg(BETA), other('icyveins')), ('review', 'one-claim', 'public'))             # Icy Veins holds EG Link's rows
        self.assertEqual(resolve.independent(REGISTRY, [eg(), questie('trace'), other('norgannondb'), other('vmangos')]), 3)
        self.assertEqual(resolve.independent(REGISTRY, []), 0)

    def test_whether_it_may_be_published(self):
        self.assertEqual(weigh(ICY), ('add', 'seen-live', 'private'))                       # only a source without a licence states it
        self.assertEqual(weigh(ICY, questie('fix')), ('add', 'seen-live', 'public'))         # a publishable source states the same thing
        self.assertEqual(weigh(other('wowhead')), ('review', 'reference-only', 'private'))
        self.assertEqual(weigh(other('wowhead'), eg(BETA)), ('add', 'two-witnesses', 'public'))
        self.assertEqual(weigh(), ('review', 'reference-only', 'private'))

    def test_a_reference_can_confirm_but_not_be_the_live_recording(self):
        live_reference = Evidence('wowhead', '', LIVE, 1, 'wowhead', True, 'reference')
        self.assertEqual(weigh(live_reference), ('review', 'reference-only', 'private'))
        self.assertEqual(weigh(live_reference, UNTRUSTED), ('review', 'one-claim', 'public'))

    def test_strongest_keeps_one_witness_per_source_and_part(self):
        kept = resolve.strongest([eg(BETA, 9), eg(LIVE, 1), eg(70790, 4), questie('generated'), questie('generated'), questie('trace')])
        self.assertEqual(kept, [eg(LIVE, 1), questie('trace'), questie('generated')])         # live first; the newest build; each part kept


class Pairs(unittest.TestCase):
    def decide(self, kind, claims, removed=()):
        made, agreed = resolve.decide_pairs(REGISTRY, kind, claims, WORLD, removed)
        return {(d.subject_kind, d.subject, d.object): d for d in made}, agreed

    def test_what_the_world_holds_is_not_decided_again(self):
        self.assertEqual(self.decide('gives', {('npc', 1, 100): [eg()]}), ({}, 1))
        self.assertEqual(self.decide('takes', {('npc', 4, 100): [eg()]}), ({}, 1))
        made, agreed = self.decide('takes', {('npc', 1, 100): [eg()]})                      # the world has it as a giver, not as an ender
        self.assertEqual((list(made), agreed), ([('npc', 1, 100)], 0))

    def test_add_hold_review(self):
        made, agreed = self.decide('gives', {
            ('npc', 2, 100): [eg()],                           # seen live, quest and NPC there
            ('npc', 3, 101): [questie('trace')],               # the NPC is not spawned: still added, noted
            ('npc', 9, 100): [eg()],                           # no template
            ('npc', 2, 555): [eg()],                           # the quest is not in the world
            ('object', 50, 100): [questie('fix')],             # one claim
            ('object', 51, 100): [eg()],                       # an object without a template
            ('npc', 9, 556): [questie('fix')],                 # one claim and nothing there: for a person, not on hold
            ('npc', 4, 101): [questie('generated')],           # a trusted source by itself
            ('npc', 9, 101): [questie('generated')],           # trusted, but its NPC is not there
        })
        self.assertEqual(agreed, 0)
        self.assertEqual({k: (d.verdict, d.rule) for k, d in made.items()}, {
            ('npc', 2, 100): ('add', 'seen-live'), ('npc', 3, 101): ('add', 'seen-live'), ('npc', 9, 100): ('hold', 'seen-live'),
            ('npc', 2, 555): ('hold', 'seen-live'), ('object', 50, 100): ('review', 'one-claim'), ('object', 51, 100): ('hold', 'seen-live'),
            ('npc', 9, 556): ('review', 'one-claim'), ('npc', 4, 101): ('add', 'trusted-source'), ('npc', 9, 101): ('hold', 'trusted-source')})
        self.assertEqual(made[('npc', 9, 100)].needs, ['NPC 9 has no template'])
        self.assertEqual(made[('object', 51, 100)].needs, ['object 51 has no template'])
        self.assertEqual(made[('npc', 2, 555)].needs, ['quest 555 is not in the world'])
        self.assertEqual(made[('npc', 9, 556)].needs, ['NPC 9 has no template', 'quest 556 is not in the world'])
        self.assertEqual(made[('npc', 3, 101)].notes, ['NPC 3 is not spawned'])
        self.assertEqual(made[('object', 50, 100)].notes, ['object 50 is not spawned'])
        self.assertEqual(made[('npc', 2, 100)].witnesses, [eg()])

    def test_an_item_that_starts_a_quest_is_not_followed_here(self):
        made, _agreed = self.decide('gives', {('item', 777, 100): [eg(), questie('trace'), questie('generated')]})
        self.assertEqual((made[('item', 777, 100)].verdict, made[('item', 777, 100)].rule), ('review', 'item-starts'))

    def test_a_claim_a_hand_correction_takes_back_is_for_a_person(self):
        made, _agreed = self.decide('gives', {('npc', 2, 100): [questie('trace')], ('npc', 3, 100): [questie('trace')],
                                              ('npc', 4, 100): [questie('generated')]}, removed={('npc', 2, 100), ('npc', 4, 100)})
        self.assertEqual({k: (d.verdict, d.rule) for k, d in made.items()},       # even what a trusted list says
                         {('npc', 2, 100): ('review', 'removed-by-hand'), ('npc', 3, 100): ('add', 'seen-live'), ('npc', 4, 100): ('review', 'removed-by-hand')})

    def test_a_vendor_needs_no_quest(self):
        made, agreed = self.decide('sells', {('npc', 2, 900): [eg()], ('npc', 2, 901): [eg()], ('npc', 8, 901): [ICY]})
        self.assertEqual(agreed, 1)
        self.assertEqual({k: (d.verdict, d.allowed, d.needs) for k, d in made.items()},
                         {('npc', 2, 901): ('add', 'public', []), ('npc', 8, 901): ('hold', 'private', ['NPC 8 has no template'])})

    def test_what_a_remove_correction_takes_back(self):
        parts = {'fix': {'questStarts_remove': [5, 6, 'x'], 'questEnds_remove': [7], 'name': 'x'}, 'trace': {'questStarts_add': [8]}}
        self.assertEqual(sorted(resolve.taken_back('npc', 384, parts)), [('gives', ('npc', 384, 5)), ('gives', ('npc', 384, 6)), ('takes', ('npc', 384, 7))])
        quest = {'fix': {'startedBy_remove': [[1], None, [3]], 'finishedBy_remove': [None, [50]]}}
        self.assertEqual(sorted(resolve.taken_back('quest', 100, quest)),
                         [('gives', ('item', 3, 100)), ('gives', ('npc', 1, 100)), ('takes', ('object', 50, 100))])
        self.assertEqual(sorted(resolve.taken_back('item', 190232, {'fix': {'vendors_remove': [74], 'npcDrops_remove': [5]}})), [('sells', ('npc', 74, 190232))])
        self.assertEqual(list(resolve.taken_back('npc', 1, {'fix': {'questStarts_remove': 5}})), [])


class Quests(unittest.TestCase):
    def decide(self, records, gives, takes):
        return {d.subject: d for d in resolve.decide_quests(records, gives, takes, WORLD)}

    def test_a_quest_seen_on_live_with_its_giver_and_ender(self):
        made = self.decide({200: ('Follow That Kobold!', [eg(70790), eg(LIVE)]), 100: ('Already there', [eg()])},
                           {200: [('npc', 1, 'hold', 'public')]}, {200: [('npc', 9, 'hold', 'public'), ('npc', 3, 'hold', 'public')]})
        self.assertEqual(list(made), [200])
        quest = made[200]
        self.assertEqual((quest.verdict, quest.rule, quest.allowed, quest.name, quest.needs), ('add', 'record-seen-live', 'public', 'Follow That Kobold!', []))
        self.assertEqual(quest.notes, ['giver: npc 1', 'its ender is not spawned: npc 3', 'ender: npc 3'])      # npc 9 has no template: not the ender we use
        self.assertEqual(quest.witnesses, [eg(LIVE)])

    def test_what_a_quest_can_be_missing(self):
        records = {q: (f'Quest {q}', [eg()]) for q in (201, 202, 203, 204, 205, 206)}
        made = self.decide(records,
                           {202: [('npc', 1, 'review', 'public')], 203: [('npc', 9, 'hold', 'public')], 204: [('npc', 1, 'held', 'public')],
                            205: [('npc', 1, 'hold', 'private'), ('npc', 2, 'hold', 'private')], 206: [('item', 777, 'review', 'public')]},
                           {202: [('npc', 1, 'hold', 'public')], 203: [('npc', 1, 'add', 'public')], 205: [('object', 50, 'hold', 'public')],
                            206: [('npc', 1, 'hold', 'public')]})
        self.assertEqual({q: d.verdict for q, d in made.items()}, {201: 'hold', 202: 'hold', 203: 'hold', 204: 'hold', 205: 'add', 206: 'hold'})
        self.assertEqual(made[201].needs, ['no giver known', 'no ender known'])
        self.assertEqual(made[202].needs, ['its giver is one claim only: npc 1'])
        self.assertEqual(made[203].needs, ['its giver has no template: npc 9'])
        self.assertEqual(made[204].needs, ['no ender known'])
        self.assertEqual(made[206].needs, ['an item starts it (777): not followed here'])
        self.assertEqual(made[205].allowed, 'private')                 # every giver comes from a source that may not be published
        self.assertIn('its ender is not spawned: object 50', made[205].notes)

    def test_one_publishable_giver_is_enough_to_publish(self):
        made = self.decide({207: ('Mixed', [eg()])}, {207: [('npc', 1, 'hold', 'private'), ('npc', 2, 'hold', 'public')]}, {207: [('npc', 1, 'held', 'public')]})
        self.assertEqual((made[207].verdict, made[207].allowed), ('add', 'public'))

    def test_where_the_record_comes_from(self):
        ready = {300: [('npc', 1, 'hold', 'public')], 301: [('npc', 1, 'hold', 'public')], 302: [('npc', 1, 'hold', 'public')],
                 303: [('npc', 1, 'hold', 'public')]}
        made = self.decide({300: ('Beta quest', [eg(BETA)]), 301: ('Private record', [ICY]), 302: ('Private live, public beta', [ICY, eg(BETA)]),
                            303: ('Reference record', [Evidence('wowhead', '', LIVE, 1, 'wowhead', True, 'reference')])}, ready, ready)
        self.assertEqual({q: (d.verdict, d.rule, d.allowed) for q, d in made.items()}, {
            300: ('review', 'record-not-live', 'public'), 301: ('add', 'record-seen-live', 'private'),
            302: ('add', 'record-seen-live', 'private'),               # the live record is the private one: its values are what would be written
            303: ('review', 'record-not-live', 'private')})            # a reference never gives the row

    def test_a_developer_s_leftover_is_for_a_person(self):
        names = ['[Never used]', 'zzOLD UNUSED quest', 'REUSE ME', '[DNT] Tracking', '<TXT> placeholder', 'Kill Test Quest', 'The "Chow" Quest (123)aa TEST']
        ready = {q: [('npc', 1, 'hold', 'public')] for q in range(400, 400 + len(names))}
        made = self.decide({400 + i: (name, [eg()]) for i, name in enumerate(names)}, ready, ready)
        self.assertEqual({d.rule for d in made.values()}, {'looks-internal'})
        self.assertEqual({d.verdict for d in made.values()}, {'review'})
        fine = self.decide({q: (name, [eg()]) for q, name in ((500, 'Testing the Wells'), (501, 'Protest at the Gates'), (502, 'Unused Scraping Vial'))},
                           {q: [('npc', 1, 'hold', 'public')] for q in (500, 501, 502)}, {q: [('npc', 1, 'hold', 'public')] for q in (500, 501, 502)})
        self.assertEqual({q: d.rule for q, d in fine.items()}, {500: 'record-seen-live', 501: 'record-seen-live', 502: 'looks-internal'})


class Whole(unittest.TestCase):
    def test_resolve_ties_the_kinds_together(self):
        claims = {'gives': {('npc', 1, 200): [questie('trace')], ('npc', 2, 100): [eg()], ('npc', 9, 200): [eg()], ('npc', 1, 201): [eg()]},
                  'takes': {('npc', 2, 200): [eg(), questie('generated')]},
                  'sells': {('npc', 2, 900): [eg()]}}
        records = {200: ('New quest', [eg()]), 100: ('Old quest', [eg()]), 201: ('No ender', [eg()])}
        decisions, summary = resolve.resolve(REGISTRY, WORLD, claims, records)
        self.assertEqual(list(summary), ['gives', 'takes', 'sells', 'quest'])
        # the pairs of a quest that is ready come with it; a pair that also lacks its NPC, or whose quest is on hold, stays on hold
        self.assertEqual(summary, {'gives': {'add': 2, 'hold': 2, 'agreed': 0}, 'takes': {'add': 1, 'agreed': 0}, 'sells': {'agreed': 1},
                                   'quest': {'add': 1, 'hold': 1, 'agreed': 1}})
        by = {(d.kind, d.subject, d.object): d for d in decisions}
        self.assertEqual((by[('quest', 200, 0)].verdict, by[('quest', 200, 0)].notes), ('add', ['giver: npc 1', 'ender: npc 2']))
        self.assertEqual((by[('gives', 1, 200)].verdict, by[('gives', 1, 200)].needs, by[('gives', 1, 200)].notes), ('add', [], ['comes with quest 200']))
        self.assertEqual((by[('gives', 9, 200)].verdict, by[('gives', 9, 200)].needs), ('hold', ['NPC 9 has no template', 'quest 200 is not in the world']))
        self.assertEqual((by[('gives', 1, 201)].verdict, by[('quest', 201, 0)].needs), ('hold', ['no ender known']))

    def test_what_the_world_holds_counts_for_a_missing_quest(self):
        world = dict(WORLD, gives=WORLD['gives'] | {('npc', 1, 210)}, takes=WORLD['takes'] | {('object', 50, 210)})
        decisions, _summary = resolve.resolve(REGISTRY, world, {}, {210: ('Half there', [eg()])})
        self.assertEqual([(d.verdict, d.allowed, d.notes) for d in decisions],
                         [('add', 'public', ['giver: npc 1', 'its ender is not spawned: object 50', 'ender: object 50'])])

    def test_a_hand_correction_reaches_the_pair(self):
        claims = {'gives': {('npc', 2, 100): [questie('trace')]}}
        decisions, _summary = resolve.resolve(REGISTRY, WORLD, claims, {}, {'gives': {('npc', 2, 100)}})
        self.assertEqual(decisions[0].rule, 'removed-by-hand')

    def test_the_file_replaces_every_decision_in_one_transaction(self):
        decisions, summary = resolve.resolve(REGISTRY, WORLD, {'gives': {('npc', 2, 555): [eg()]}}, {200: ("It's é" + 'x' * 300, [eg()])})
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'decisions.sql')
            resolve.write_sql(path, decisions, summary, now="'2026-11-13 08:00:00'")
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
        self.assertLess(text.index('START TRANSACTION'), text.index('DELETE FROM ft_world_decisions;'))
        self.assertTrue(text.endswith('COMMIT;\n'))
        self.assertIn("('gives', 'npc', 2, 555, 'hold', 'seen-live', 'public', '', '[\"quest 555 is not in the world\"]', '[]', '[{", text)
        self.assertIn("'It\\'s é" + 'x' * 249 + "', ", text)                         # cut to the column's 255
        self.assertIn('"live":true', text)
        self.assertIn("VALUES (1, '2026-11-13 08:00:00', '[[\"gives\",{", text)           # the summary keeps its order


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server')
class OnMySQL(unittest.TestCase):
    WORLD_DB = 'ft_resolve_selftest'

    @classmethod
    def setUpClass(cls):
        os.environ['FOREVER_TRACKER_CONFIG'] = os.environ['FT_TEST_CONFIG']
        from ft import sqlio
        from ft.config import CONFIG
        cls.db, cls.tracker = sqlio, CONFIG.db('tracker')
        sqlio.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nCREATE DATABASE `{cls.tracker}` CHARACTER SET utf8mb4;\n'
                      f'DROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\nCREATE DATABASE `{cls.WORLD_DB}` CHARACTER SET utf8mb4;\n', 'information_schema')
        sqlio.execute("""
CREATE TABLE quest_template (ID int PRIMARY KEY); INSERT INTO quest_template VALUES (100), (101), (102);
CREATE TABLE creature_template (entry int PRIMARY KEY); INSERT INTO creature_template VALUES (1), (2), (3), (4);
CREATE TABLE creature (guid int PRIMARY KEY, id int); INSERT INTO creature VALUES (10, 1), (11, 1), (12, 2), (13, 4);
CREATE TABLE gameobject_template (entry int PRIMARY KEY); INSERT INTO gameobject_template VALUES (50);
CREATE TABLE gameobject (guid int PRIMARY KEY, id int);
CREATE TABLE creature_queststarter (id int, quest int); INSERT INTO creature_queststarter VALUES (1, 100);
CREATE TABLE creature_questender (id int, quest int); INSERT INTO creature_questender VALUES (1, 100);
CREATE TABLE gameobject_queststarter (id int, quest int); CREATE TABLE gameobject_questender (id int, quest int);
CREATE TABLE game_event_creature_quest (eventEntry int, id int, quest int); INSERT INTO game_event_creature_quest VALUES (7, 2, 102);
CREATE TABLE npc_vendor (entry int, item int, type int DEFAULT 1);
INSERT INTO npc_vendor VALUES (2, 900, 1), (2, 0, 1), (2, 77, 2), (3, -2, 1), (3, 903, 1), (2, -3, 1);
CREATE TABLE game_event_npc_vendor (eventEntry int, guid int, item int); INSERT INTO game_event_npc_vendor VALUES (7, 13, 904);
""", cls.WORLD_DB)
        cls.folder = tempfile.TemporaryDirectory()
        stored = {
            'eglink': [Fact('quest', 'quest', 200, 0, BETA, 1, {'title': 'Old name'}), Fact('quest', 'quest', 200, 0, LIVE, 3, {'title': "Kobold's énd"}),
                       Fact('quest', 'quest', 100, 0, LIVE, 3, {'title': 'There'}), Fact('quest', 'quest', 201, 0, LIVE, 1, {'level': 5}),
                       Fact('gives', 'npc', 1, 200, LIVE, 2, {}), Fact('gives', 'npc', 1, 100, LIVE, 2, {}), Fact('gives', 'npc', 2, 102, LIVE, 2, {}),
                       Fact('gives', 'npc', 2, 100, LIVE, 2, {}),
                       Fact('sells', 'npc', 2, 900, LIVE, 1, {'listings': []}), Fact('sells', 'npc', 2, 901, LIVE, 1, {'listings': []}),
                       Fact('sells', 'npc', 3, 900, LIVE, 1, {}), Fact('sells', 'npc', 2, 903, LIVE, 1, {}), Fact('sells', 'npc', 4, 904, LIVE, 1, {}),
                       Fact('sells', 'npc', 2, 77, LIVE, 1, {})],
            'questie': [Fact('takes', 'object', 50, 200, 0, 1, {'parts': {'trace': ['quest.finishedBy_add'], 'generated': ['quest.finishedBy']}}),
                        Fact('gives', 'npc', 3, 201, 0, 0, {'parts': {'fix': ['npc.questStarts']}}),
                        Fact('gives', 'npc', 4, 101, 0, 0, {'parts': {'generated': ['npc.questStarts']}}),
                        Fact('entry', 'npc', 2, 0, 0, 0, {'parts': {'fix': {'questStarts_remove': [100]}}}),
                        Fact('entry', 'npc', 3, 0, 0, 0, {'parts': {'fix': {'name': 'not a _remove field, only the text'}}})],
        }
        for source, rows in stored.items():
            path = os.path.join(cls.folder.name, source + '.sql')
            facts.write_sql(path, source, 'a' * 40, REGISTRY.source(source)['licence'], REGISTRY.source(source)['use'], rows)
            sqlio.execute_file(path, 'tracker')

    @classmethod
    def tearDownClass(cls):
        cls.db.execute(f'DROP DATABASE IF EXISTS `{cls.tracker}`;\nDROP DATABASE IF EXISTS `{cls.WORLD_DB}`;\n', 'information_schema')
        cls.folder.cleanup()

    def test_from_both_databases_to_stored_decisions(self):
        self.assertEqual(resolve.stored_summary(self.db), (None, {}))
        self.assertEqual(resolve.stored(self.db, 'quest'), ([], 0))                  # before the first resolve: nothing, not an error
        world = resolve.load_world(self.db, self.WORLD_DB)
        self.assertEqual((world['quests'], world['npcs_spawned']), ({100, 101, 102}, {1, 2, 4}))
        # a vendor's list with the lists it borrows (each way round), items only, and what is sold during an event
        self.assertEqual(world['sells'], {('npc', 2, 900), ('npc', 2, 903), ('npc', 3, 900), ('npc', 3, 903), ('npc', 4, 904)})
        self.assertIn(('npc', 2, 102), world['gives'])                               # given during a game event
        claims, records, removed = resolve.load_claims(self.db, REGISTRY)
        self.assertEqual(records[200][0], "Kobold's énd")                          # the newest build's title
        self.assertEqual(records[201][0], '')
        self.assertEqual(removed, {'gives': {('npc', 2, 100)}, 'takes': set(), 'sells': set()})
        decisions, summary = resolve.resolve(REGISTRY, world, claims, records, removed)
        path = os.path.join(self.folder.name, 'decisions.sql')
        resolve.write_sql(path, decisions, summary)
        self.db.execute_file(path, 'tracker')
        when, stored_summary = resolve.stored_summary(self.db)
        self.assertTrue(when)
        self.assertEqual(list(stored_summary), ['gives', 'takes', 'sells', 'quest'])
        self.assertEqual(stored_summary, {'gives': {'add': 2, 'review': 2, 'agreed': 2}, 'takes': {'add': 1, 'agreed': 0},
                                          'sells': {'add': 2, 'agreed': 4}, 'quest': {'add': 1, 'hold': 1, 'agreed': 1}})
        rows, total = resolve.stored(self.db, 'quest')
        quests = {row['subject']: row for row in rows}
        self.assertEqual(total, 2)
        self.assertEqual((quests[200]['verdict'], quests[200]['name'], quests[200]['allowed']), ('add', "Kobold's énd", 'public'))
        self.assertEqual(quests[200]['notes'], ['giver: npc 1', 'its ender is not spawned: object 50', 'ender: object 50'])
        self.assertEqual([(w['source'], w['build'], w['live']) for w in quests[200]['witnesses']], [('eglink', LIVE, True)])
        self.assertEqual((quests[201]['verdict'], quests[201]['needs']), ('hold', ['its giver is one claim only: npc 3', 'no ender known']))
        self.assertEqual([row['object'] for row in resolve.stored(self.db, 'sells', 'add')[0]], [77, 901])       # 77 is a currency row in the world, not an item
        self.assertEqual(resolve.stored(self.db, 'sells', 'review'), ([], 0))
        self.assertEqual(resolve.stored(self.db, 'sells', limit=1)[1], 2)
        self.assertEqual(len(resolve.stored(self.db, 'sells', limit=-3)[0]), 1)
        gives = {(row['subject'], row['object']): (row['verdict'], row['rule']) for row in resolve.stored(self.db, 'gives')[0]}
        self.assertEqual(gives, {(1, 200): ('add', 'seen-live'), (2, 100): ('review', 'removed-by-hand'), (3, 201): ('review', 'one-claim'),
                                 (4, 101): ('add', 'trusted-source')})
        trusted = next(row for row in resolve.stored(self.db, 'gives', 'add')[0] if row['object'] == 101)
        self.assertEqual([(w['part'], w['trusted']) for w in trusted['witnesses']], [('generated', True)])
        ender = resolve.stored(self.db, 'takes')[0][0]
        self.assertEqual(sorted((w['part'], w['group'], w['live']) for w in ender['witnesses']), [('generated', 'wowhead', False), ('trace', 'questie', True)])
        self.assertEqual(ender['rule'], 'seen-live')
        self.assertEqual(ender['notes'], ['object 50 is not spawned', 'comes with quest 200'])
        # resolving again replaces what was there
        resolve.write_sql(path, [], {})
        self.db.execute_file(path, 'tracker')
        self.assertEqual(resolve.stored(self.db, 'quest'), ([], 0))


if __name__ == '__main__':
    unittest.main()
