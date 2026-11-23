"""What the core's C++ does for spells, read once into tools/world/core_spells.json (tools/make_core_spells.py).

A dummy or script effect does nothing by itself: a SpellScript bound in spell_script_names runs it, or the core's
own code names the spell (`case 20375:`, `SPELL_MAGE_FIRE_POWER = 11124`). And an aura script that waits for a proc
runs only when the aura procs, which takes a spell_proc row or the client's proc flags.
"""
import json
import os
import re

FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'world', 'core_spells.json')
REVIEWED = os.path.join(os.path.dirname(FILE), 'reviewed_dummies.json')


def load(path=None):
    """{'spells': {spell id: file}, 'scripts': {script name: file}, 'proc_scripts': {script name},
    'periodic_scripts': {script name that makes an aura effect periodic itself},
    'trigger_auras': {aura type the core builds a default proc for}, 'commit': str}.
    Empty lists when the file is missing or unreadable: the analysis then says nothing about scripts (`known` False)."""
    out = {'spells': {}, 'scripts': {}, 'proc_scripts': set(), 'periodic_scripts': set(), 'trigger_auras': set(), 'commit': '', 'known': False}
    try:
        with open(path or FILE, encoding='utf-8') as handle:
            raw = json.load(handle)
        out['spells'] = {int(k): str(v) for k, v in (raw.get('spells') or {}).items()}
        out['scripts'] = {str(k): str(v) for k, v in (raw.get('scripts') or {}).items()}
        out['proc_scripts'] = {str(x) for x in raw.get('proc_scripts') or ()}
        out['periodic_scripts'] = {str(x) for x in raw.get('periodic_scripts') or ()}
        out['trigger_auras'] = {int(x) for x in raw.get('trigger_auras') or ()}
        out['commit'] = str(raw.get('commit') or '')
        out['known'] = bool(out['scripts'])
    except (OSError, ValueError, AttributeError, TypeError):
        return {'spells': {}, 'scripts': {}, 'proc_scripts': set(), 'periodic_scripts': set(), 'trigger_auras': set(), 'commit': '', 'known': False}
    return out


def reviewed(path=None):
    """{spell id: {'en', 'fr'}}: player spells whose dummy effect was checked by hand and needs no code
    (tools/world/reviewed_dummies.json). Empty when the file is missing or unreadable."""
    try:
        with open(path or REVIEWED, encoding='utf-8') as handle:
            raw = json.load(handle)
        return {int(k): {'en': str(v['en']), 'fr': str(v['fr'])} for k, v in (raw.get('spells') or {}).items()}
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        return {}


def spell_file(path):
    """Whether a file of core_spells.json's list handles spells as such (the game code, the spell and talent
    scripts) rather than a creature's or an instance's script (make_core_spells.spell_file)."""
    return path.startswith('game/') or '/Spells/' in path or bool(re.search(r'spell|talent|/world/', path, re.I))


def rank_chains(abilities):
    """{spell: next rank} from SkillLineAbility.SupercedesSpell, as the core's SpellMgr::LoadSpellRanks builds it."""
    return {r['SupercedesSpell']: r['Spell'] for r in abilities if r.get('SupercedesSpell') and r.get('Spell')}


def expand(spell_id, chains):
    """The spells a spell_script_names or spell_proc row covers: a negative id stands for that spell and every
    higher rank of it."""
    if spell_id >= 0:
        return [spell_id]
    out, spell = [], -spell_id
    while spell and spell not in out:
        out.append(spell)
        spell = chains.get(spell)
    return out
