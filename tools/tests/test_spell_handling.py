"""python -m unittest discover -s tools/tests

A player's spell that exists but does nothing: a dummy or script effect nothing runs (no SpellScript bound, the core's
C++ does not name it), or an aura that waits for a proc it never gets (no spell_proc row, no client proc flags).
Also tools/make_core_spells.py, which reads those facts from the core's source.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

import make_core_spells  # noqa: E402
from ft import corespells  # noqa: E402
from ft import rules  # noqa: E402
from test_rules import KINDS, evaluate, failed, world  # noqa: E402

DUMMY = [(0, 6, 4, 0, 0)]            # apply aura: SPELL_AURA_DUMMY
PROC = [(0, 6, 42, 0, 9999)]         # apply aura: SPELL_AURA_PROC_TRIGGER_SPELL, triggers 9999
PLAIN = [(0, 2, 0, 10, 0)]           # school damage


def core(spells=(), scripts=(), procs=(), periodic=()):
    return {'known': True, 'commit': 'abc', 'spells': {s: 'scripts/Spells/x.cpp' for s in spells},
            'scripts': {s: 'scripts/x.cpp' for s in scripts}, 'proc_scripts': set(procs), 'periodic_scripts': set(periodic)}


def spell(effects, sub='talent'):
    return {'spell': {9452: {'sub': sub, 'facts': {'effects': effects}}}}


class ScriptCheck(unittest.TestCase):
    def test_a_talent_nothing_handles_is_partial(self):
        result = evaluate(spell(DUMMY), world(core_spells=core(), client_procs=set()))[('spell', 9452)]
        self.assertEqual(result[0], 'partial')
        self.assertEqual(failed(result), ['script'])
        self.assertIn('Nothing handles', next(c for c in result[2] if c['code'] == 'script')['detail']['en'])

    def test_a_bound_script_the_core_registers_handles_it(self):
        ctx = world(core_spells=core(scripts={'spell_pal_vindication'}), client_procs=set(),
                    spell_scripts={9452: {'spell_pal_vindication'}}, scripted_spells={9452})
        self.assertEqual(evaluate(spell(DUMMY), ctx)[('spell', 9452)][0], 'ok')

    def test_a_bound_script_the_core_lacks_handles_nothing(self):
        ctx = world(core_spells=core(), client_procs=set(), spell_scripts={9452: {'spell_gone'}}, scripted_spells={9452})
        result = evaluate(spell(DUMMY), ctx)[('spell', 9452)]
        self.assertEqual(failed(result), ['script'])
        self.assertIn('spell_gone', result[2][-1]['detail']['en'])

    def test_the_cores_cpp_naming_it_handles_it(self):
        self.assertEqual(evaluate(spell(DUMMY), world(core_spells=core(spells={9452}), client_procs=set()))[('spell', 9452)][0], 'ok')

    def test_a_dummy_checked_by_hand_is_handled_with_its_reason(self):
        # Anger Management: the dummies are tooltip numbers, aura 85 does the work (tools/world/reviewed_dummies.json)
        reason = {'en': 'Checked by hand: tooltip numbers.', 'fr': 'Vérifié à la main.'}
        ctx = world(core_spells=core(), client_procs=set(), reviewed_dummies={9452: reason})
        result = evaluate(spell(DUMMY), ctx)[('spell', 9452)]
        self.assertEqual(result[0], 'ok')
        self.assertEqual(next(c for c in result[2] if c['code'] == 'script')['detail'], reason)

    def test_a_dummy_aura_conditions_read_is_handled(self):
        # Argent Dawn Commission 17670: the Scourgestones' loot conditions ask for its aura
        ctx = world(core_spells=core(), client_procs=set(), aura_conditions={9452: 170})
        result = evaluate(spell(DUMMY), ctx)[('spell', 9452)]
        self.assertEqual(result[0], 'ok')
        self.assertIn('Conditions read its aura (170', next(c for c in result[2] if c['code'] == 'script')['detail']['en'])

    def test_a_dummy_aura_whose_trigger_the_core_casts_on_proc_is_handled(self):
        # Fist of Stone 1294794: a dummy aura that names 21951; the core casts it when the aura procs
        with_trigger = [(0, 6, 4, 3, 21951)]
        ctx = world(core_spells=core(), client_procs=set(), spell_procs={9452})
        result = evaluate(spell(with_trigger), ctx)[('spell', 9452)]
        self.assertEqual(result[0], 'ok')
        self.assertIn('21951', next(c for c in result[2] if c['code'] == 'script')['detail']['en'])
        # no proc, or a dummy aura with nothing to trigger: still nothing runs it
        self.assertEqual(failed(evaluate(spell(with_trigger), world(core_spells=core(), client_procs=set()))[('spell', 9452)]), ['script'])
        self.assertEqual(failed(evaluate(spell(DUMMY), world(core_spells=core(), client_procs=set(), spell_procs={9452}))[('spell', 9452)]), ['script'])
        # a dummy effect beside it still needs code
        self.assertEqual(failed(evaluate(spell(with_trigger + [(1, 3, 0, 0, 0)]), ctx)[('spell', 9452)]), ['script'])

    def test_the_shipped_reviewed_list_reads(self):
        found = corespells.reviewed()
        self.assertIn(12296, found)
        self.assertTrue(all(v['en'] and v['fr'] for v in found.values()))

    def test_a_creature_scripts_constant_does_not_handle_a_learned_spell(self):
        # Remorseless Attacks 14144 is also The Beast's SPELL_FIREBLAST in a Blackrock Spire script
        ctx = world(core_spells={**core(), 'spells': {9452: 'scripts/Custom/Classic/instances/blackrock_spire/classic_boss_the_beast.cpp'}}, client_procs=set())
        self.assertEqual(failed(evaluate(spell(DUMMY), ctx)[('spell', 9452)]), ['script'])
        ctx['core_spells']['spells'] = {9452: 'scripts/Custom/Classic/world/talents/classic_talents_paladin.cpp'}
        self.assertEqual(evaluate(spell(DUMMY), ctx)[('spell', 9452)][0], 'ok')

    def test_a_creatures_spell_stays_a_hint(self):
        result = evaluate(spell(DUMMY, sub='other'), world(core_spells=core(), client_procs=set()))[('spell', 9452)]
        self.assertEqual(result[0], 'ok')
        self.assertEqual([c['w'] for c in result[2] if c['code'] == 'script'], [0])

    def test_without_the_core_file_it_stays_a_hint(self):
        result = evaluate(spell(DUMMY), world())[('spell', 9452)]
        self.assertEqual(result[0], 'ok')

    def test_a_spell_an_obtainable_item_casts_counts(self):
        content = {'item': {1: {}}, 'spell': {9452: {'sub': 'item', 'facts': {'effects': DUMMY}}}}
        ctx = world(core_spells=core(), client_procs=set(), item_spells={1: {9452}}, shop_items={1})
        result = evaluate(content, ctx)
        self.assertEqual(result[('item', 1)][0], 'ok')
        self.assertEqual(failed(result[('spell', 9452)]), ['script'])
        # the same spell on an item nobody can get is no player's
        ctx['shop_items'] = set()
        self.assertEqual(evaluate(content, ctx)[('spell', 9452)][0], 'ok')

    def test_a_plain_spell_needs_no_script(self):
        self.assertEqual(evaluate(spell(PLAIN), world(core_spells=core(), client_procs=set()))[('spell', 9452)][0], 'ok')

    def test_a_proc_aura_with_nothing_to_trigger_needs_a_script(self):
        effects = [(0, 6, 42, 0, 0)]
        result = evaluate(spell(effects), world(core_spells=core(), client_procs={9452}))[('spell', 9452)]
        self.assertEqual(failed(result), ['script'])


class WhatCounts(unittest.TestCase):
    def taught(self, effects, **entity):
        content = {'spell': {9452: {'sub': 'class', 'facts': {'effects': effects}, **entity}}}
        return evaluate(content, world(core_spells=core(), client_procs=set(), trainer_spells=[(7, 9452)], trainers=[(200, 7)], spawned_npc={200}))[('spell', 9452)]

    def test_an_ability_whose_every_effect_needs_code_counts(self):
        self.assertEqual(failed(self.taught(DUMMY)), ['script'])

    def test_a_dummy_beside_a_real_effect_stays_a_hint(self):
        # a teleport's script effect beside the teleport itself
        result = self.taught([(0, 252, 0, 0, 0), (1, 77, 0, 0, 0)])
        self.assertEqual(result[0], 'ok')
        self.assertEqual([c['w'] for c in result[2] if c['code'] == 'script'], [0])

    def test_a_passive_marker_needs_nothing(self):
        # Horse Riding: a passive spell whose one effect is a dummy effect, no aura
        self.assertEqual(self.taught([(0, 3, 0, 0, 0)], passive=True)[0], 'ok')
        # a passive dummy aura is a talent-like mechanic: it counts
        self.assertEqual(failed(self.taught(DUMMY, passive=True)), ['script'])

    def test_a_talents_dummy_beside_a_real_effect_counts(self):
        effects = [(0, 6, 85, 0, 0), (1, 6, 4, 0, 0)]    # Anger Management: power regen plus dummies
        result = evaluate(spell(effects), world(core_spells=core(), client_procs=set()))[('spell', 9452)]
        self.assertEqual(failed(result), ['script'])

    def test_a_smartai_reacting_to_the_spell_handles_it(self):
        content = {'item': {1: {}}, 'spell': {9452: {'sub': 'item', 'facts': {'effects': [(0, 3, 0, 0, 0)]}}}}
        ctx = world(core_spells=core(), client_procs=set(), item_spells={1: {9452}}, shop_items={1})
        self.assertEqual(failed(evaluate(content, ctx)[('spell', 9452)]), ['script'])
        ctx['smart_spellhit'] = {9452}
        self.assertEqual(evaluate(content, ctx)[('spell', 9452)][0], 'ok')

    def test_a_spell_the_server_lacks_gains_nothing(self):
        # an item's proc spell the server's SpellName.db2 lacks: missing, and a spell_proc row lifts nothing
        content = {**{k: {} for k in KINDS}, 'item': {1: {}}, 'spell': {9452: {'sub': 'item', 'facts': {'effects': PROC}}}}
        ctx = world(core_spells=core(), client_procs=set(), spell_procs={9452}, item_spells={1: {9452}}, shop_items={1})
        ctx['known']['item'] = {1}
        result = rules.evaluate_all(content, ctx)[('spell', 9452)]
        self.assertEqual(result[0], 'missing')
        self.assertEqual([c['code'] for c in result[2]], ['core'])


class ProcCheck(unittest.TestCase):
    def test_a_proc_aura_without_proc_data_never_procs(self):
        result = evaluate(spell(PROC), world(core_spells=core(), client_procs=set(), spell_procs=set()))[('spell', 9452)]
        self.assertEqual(failed(result), ['proc'])
        self.assertIn('Never procs', result[2][-1]['detail']['en'])

    def test_a_spell_proc_row_or_client_flags_make_it_proc(self):
        self.assertEqual(evaluate(spell(PROC), world(core_spells=core(), client_procs=set(), spell_procs={9452}))[('spell', 9452)][0], 'ok')
        self.assertEqual(evaluate(spell(PROC), world(core_spells=core(), client_procs={9452}))[('spell', 9452)][0], 'ok')

    def test_a_script_waiting_for_a_proc_needs_proc_data(self):
        # Unsealed Wrath: a dummy aura, its script has OnProc, but no spell_proc row and no client flags
        ctx = world(core_spells=core(scripts={'unsealed'}, procs={'unsealed'}), client_procs=set(),
                    spell_scripts={9452: {'unsealed'}}, scripted_spells={9452})
        result = evaluate(spell(DUMMY), ctx)[('spell', 9452)]
        self.assertEqual(failed(result), ['proc'])
        self.assertIn('unsealed', result[2][-1]['detail']['en'])

    def test_client_flags_on_an_aura_the_core_ignores_do_not_proc(self):
        # Unsealed Wrath's own case: ProcTypeMask 4 on a modifier aura (108), which the core builds no proc for
        effects = [(0, 6, 108, 0, 0)]
        ctx = world(core_spells={**core(scripts={'unsealed'}, procs={'unsealed'}), 'trigger_auras': {4, 42}}, client_procs={9452},
                    spell_scripts={9452: {'unsealed'}}, scripted_spells={9452})
        result = evaluate(spell(effects), ctx)[('spell', 9452)]
        self.assertEqual(failed(result), ['proc'])
        self.assertIn('ignored', result[2][-1]['detail']['en'])
        # on a dummy aura the same flags make it proc
        self.assertEqual(evaluate(spell(DUMMY), ctx)[('spell', 9452)][0], 'ok')

    def test_a_script_that_makes_the_aura_periodic_needs_no_proc(self):
        # Poised: a proc aura with no proc data, whose script gives the buff every second instead
        ctx = world(core_spells=core(scripts={'poised'}, periodic={'poised'}), client_procs=set(), spell_procs=set(),
                    spell_scripts={9452: {'poised'}}, scripted_spells={9452})
        result = evaluate(spell(PROC), ctx)[('spell', 9452)]
        self.assertEqual(result[0], 'ok')
        self.assertIn('timer', next(c for c in result[2] if c['code'] == 'proc')['detail']['en'])
        # a script that also waits for a proc still needs proc data
        ctx['core_spells']['proc_scripts'] = {'poised'}
        self.assertEqual(failed(evaluate(spell(PROC), ctx)[('spell', 9452)]), ['proc'])


class TalentScript(unittest.TestCase):
    def test_a_talent_rank_nothing_handles_counts(self):
        content = {'talent': {1: {'ranks': [9452]}}, **spell(DUMMY)}
        result = evaluate(content, world(core_spells=core(), client_procs=set()))[('talent', 1)]
        self.assertEqual(failed(result), ['talent_script'])
        self.assertEqual(result[0], 'partial')


class Ranks(unittest.TestCase):
    def test_a_negative_id_covers_every_higher_rank(self):
        chains = corespells.rank_chains([{'SupercedesSpell': 1, 'Spell': 2}, {'SupercedesSpell': 2, 'Spell': 3}, {'SupercedesSpell': 0, 'Spell': 1}])
        self.assertEqual(corespells.expand(-1, chains), [1, 2, 3])
        self.assertEqual(corespells.expand(-2, chains), [2, 3])
        self.assertEqual(corespells.expand(5, chains), [5])


class CoreScan(unittest.TestCase):
    def scan(self, files):
        with tempfile.TemporaryDirectory() as root:
            for rel, text in files.items():
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as handle:
                    handle.write(text)
            return make_core_spells.scan(root)

    def test_what_the_cpp_names_as_a_spell(self):
        spells, scripts, procs, periodic = self.scan({
            'game/Spells/SpellMgr.cpp': 'void f() { switch (spellInfo->Id) { case 20375: break; } switch (eventId) { case 30: break; }\n'
                                        'ApplySpellFix({ 11111, 22222 }, [](SpellInfo*){});\n'
                                        '// 33333 only in a comment\n if (aura->GetId() == 44444) {} me->CastSpell(me, 55555, true); Timer = 15000; }',
            'game/Miscellaneous/SharedDefines.h': 'enum { SPELL_EFFECT_DUMMY = 3, SPELL_FAILED_X = 116 };',
            'game/AI/PlayerAI/PlayerAI.cpp': 'enum { SPELL_SEAL = 66666 };',
            'game/Spells/SpellInfo.cpp': 'static std::unordered_map<uint32, uint32> const ClassicSealJudgements =\n{\n    { 20915, 20962 }, // Seal of Command\n};\n'
                                         'static Position const Spots[] = { { 1234.5f, 99999.0f } };',
            'scripts/Spells/spell_x.cpp': 'enum { SPELL_MAGE_FIRE_POWER = 11124 };\n'
                                          'class spell_a : public AuraScript { void Register() override { OnProc += AuraProcFn(spell_a::P); } };\n'
                                          'class spell_b : public SpellScript { void Register() override { OnEffectHit += X; } };\n'
                                          'class spell_c : public AuraScript { void Register() override { DoEffectCalcPeriodic += AuraEffectCalcPeriodicFn(spell_c::P, EFFECT_0, SPELL_AURA_PROC_TRIGGER_SPELL); } };\n'
                                          'void Add() { RegisterSpellScript(spell_a); RegisterSpellScriptWithArgs(spell_b, "spell_b_named", 1); RegisterSpellScriptWithArgs(spell_c, "spell_c_rog", 7); }',
            'scripts/Spells/spell_old.cpp': 'class spell_trigger : public SpellScriptLoader {\n public: spell_trigger(char const* n, uint32 s) : SpellScriptLoader(n) { }\n'
                                            ' class spell_trigger_AuraScript : public AuraScript { void Register() override { OnEffectProc += X; } };\n};\n'
                                            'void AddSC_old() { new spell_trigger("spell_item_chicken", 23133); }',
        })
        self.assertEqual(set(spells), {20375, 11111, 22222, 44444, 55555, 11124, 20915, 20962})
        self.assertEqual(spells[11124], 'scripts/Spells/spell_x.cpp')
        self.assertEqual(set(scripts), {'spell_a', 'spell_b_named', 'spell_c_rog', 'spell_item_chicken'})
        self.assertEqual(procs, {'spell_a', 'spell_item_chicken'})
        self.assertEqual(periodic, {'spell_c_rog'})


if __name__ == '__main__':
    unittest.main()
