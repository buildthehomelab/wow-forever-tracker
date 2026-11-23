#!/usr/bin/env python3
"""Writes tools/world/core_spells.json: which spells the core's C++ handles by id, and which spell scripts it has.

A player spell whose effect is a dummy or a script effect does nothing unless something handles it: a SpellScript
bound in spell_script_names, or the core's own C++ naming the spell (`case 20375:` in a switch on a spell's id, a
`SPELL_PALADIN_SEAL_OF_COMMAND = 20375` constant a script casts or checks, a spell fix in SpellMgr). The analysis
reads this file to tell the two apart from a spell nothing handles.

Four lists:
  spells        spell id -> file, for every number the C++ names as a spell: a constant whose name says spell, aura
                or talent (`SPELL_X = 123`, `TALENT_X = 123`), a `case` label of a switch on a spell's id, a number a
                spell call takes (CastSpell, HasAura, GetSpellInfo, RemoveAurasDueToSpell...), a comparison with a
                spell's id (`->Id == 123`, `spellId == 123`), and every number of an `ApplySpellFix({ ... })` list.
                The file kept is a spell or talent script, or the game code, when one names it (corespells.spell_file).
                Comments and strings are skipped: a spell id written in a comment handles nothing. So are the core's
                type enums (SharedDefines.h, SpellAuraDefines.h...) and PlayerAI's lists of what a charmed player casts.
  scripts       spell script name -> file, for every script registered (RegisterSpellScript, ...WithArgs,
                RegisterSpellAndAuraScriptPair, the older SpellScriptLoader("name"), and `new loader("name", ...)` of a
                loader class that takes its name): a spell_script_names row
                naming anything else binds nothing.
  proc_scripts  the registered names among those whose aura script reacts to procs (DoCheckProc, OnProc,
                OnEffectProc, AfterProc...). Such a script only runs when the aura procs, which takes a spell_proc row
                or the client's proc flags (SpellAuraOptions.ProcTypeMask): without either it never runs.
  trigger_auras the aura types SpellMgr::GenerateDefaultSpellProcEntry builds a proc for from the client's proc
                flags (its isTriggerAura list, read from SpellMgr.cpp and SpellAuraDefines.h): a spell with client
                proc flags but none of these auras gets no proc without a spell_proc row.

    python tools/make_core_spells.py /path/to/TrinityCore [commit]     (reads src/server/game and src/server/scripts)

The list errs on the side of more spells: a number that is a spell somewhere else in the core (a creature's spell,
an unrelated constant) still counts, so a spell it lists may be handled for another purpose. Run it again when the
core moves to a commit with new scripts.
"""
import json
import os
import re
import subprocess
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'world', 'core_spells.json')

NUMBER = r'(\d{2,8})(?![\w.])'
# `SPELL_PALADIN_VINDICATION = 9452,` / `constexpr uint32 SPELL_X = 1;` / `TALENT_X = 1`
CONSTANT = re.compile(r'\b([A-Z0-9_]*(?:SPELL|AURA|TALENT)[A-Z0-9_]*)\s*=\s*' + NUMBER)
# a call that takes a spell id: CastSpell(target, 123, ...), HasAura(123), GetSpellInfo(123, ...), sSpellMgr->...(123)
SPELL_CALL = re.compile(r'\b(\w*(?:Spell|Aura|Cast|Cooldown)\w*)\s*\(([^;{}]*)\)')
CALL_NUMBER = re.compile(r'(?<![\w.])' + NUMBER)
# ->Id == 123, GetId() != 123, spellId == 123, m_spellInfo->Id == 123
COMPARE = re.compile(r'\b(?:Id|ID|GetId\(\)|spellId|SpellId|spell_id|spellID|triggerSpellId|auraId)\s*[!=]=\s*' + NUMBER)
SWITCH = re.compile(r'\bswitch\s*\(([^)]*\)?)\)')
CASE = re.compile(r'\bcase\s+' + NUMBER + r'\s*:')
SPELL_SWITCH = re.compile(r'(?i)spell|aura|\bid\b|->Id|GetId|Id\(\)')
FIX = re.compile(r'\bApplySpellFix\s*\(\s*\{([^{}]*)\}')

SCRIPT_CLASS = re.compile(r'\b(?:class|struct)\s+(\w+)\s*(?:final\s*)?:\s*public\s+(AuraScript|SpellScript)\b')
LOADER = re.compile(r'\bSpellScriptLoader\s*\(\s*"(\w+)"\s*\)')
# an old-style loader class that takes its name (`new spell_item_trigger_spell("spell_item_gnomish_battle_chicken", 1)`)
LOADER_CLASS = re.compile(r'\b(?:class|struct)\s+(\w+)\s*(?:final\s*)?:\s*public\s+SpellScriptLoader\b')
NEW_LOADER = re.compile(r'\bnew\s+(\w+)\s*\(\s*"(\w+)"')
TOP_LEVEL = re.compile(r'^(?:class|struct|void|enum|namespace)\b', re.M)
REGISTER = re.compile(r'\bRegister(SpellScript|SpellScriptWithArgs|SpellAndAuraScriptPair|SpellAndAuraScriptPairWithArgs)\s*\(([^;]*)\)\s*;')
# Files of the core's own type enums (SPELL_EFFECT_X = 116, SPELL_AURA_X = 42, ITEM_MOD_..._SPELL_... = 133), whose
# numbers are no spell ids, and PlayerAI's lists of what a charmed player casts, which handle nothing.
NOT_SPELLS = re.compile(r'(?:Defines|DBCEnums|ItemTemplate|DB2Structure|DB2Metadata)\.h$|^game/AI/PlayerAI/')
PROC_HOOK = re.compile(r'\b(DoCheckProc|DoCheckEffectProc|DoPrepareProc|OnProc|AfterProc|OnEffectProc|AfterEffectProc)\s*\+=')


def code_only(text):
    """The text with comments and string literals blanked (lengths and line breaks kept)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', text[i:j]))
            i = j
        elif c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            out.append(c + ' ' * (min(j, n) - i - 1) + (c if j < n else ''))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def spell_numbers(code):
    """The spell ids a file's code names."""
    found = {int(m.group(2)) for m in CONSTANT.finditer(code)}
    for m in SPELL_CALL.finditer(code):
        found |= {int(x) for x in CALL_NUMBER.findall(m.group(2))}
    found |= {int(x) for x in COMPARE.findall(code)}
    for m in FIX.finditer(code):
        found |= {int(x) for x in CALL_NUMBER.findall(m.group(1))}
    # a case label counts when the nearest switch above it is on a spell's id
    switches = [(m.start(), bool(SPELL_SWITCH.search(m.group(1)))) for m in SWITCH.finditer(code)]
    k, on_spell = 0, False
    for m in CASE.finditer(code):
        while k < len(switches) and switches[k][0] < m.start():
            on_spell = switches[k][1]
            k += 1
        if on_spell:
            found.add(int(m.group(1)))
    return {x for x in found if x >= 10}


def spell_file(rel):
    """Whether a file handles spells as such (the core's game code, the spell and talent scripts), rather than a
    creature's or an instance's script, whose spell constants are what that creature casts."""
    return rel.startswith('game/') or '/Spells/' in rel or bool(re.search(r'spell|talent|/world/', rel, re.I))


def scripts_of(code, raw):
    """({registered name}, {registered names whose aura script has a proc hook}) of one file."""
    starts = [(m.start(), m.group(1)) for m in SCRIPT_CLASS.finditer(code)] + [(m.start(), '"' + m.group(1)) for m in LOADER.finditer(raw)]
    starts.sort()
    proc_classes, loaders = set(), {}
    for k, (start, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(code)
        hooked = bool(PROC_HOOK.search(code, start, end))
        if name.startswith('"'):
            loaders[name[1:]] = hooked or loaders.get(name[1:], False)
        elif hooked:
            proc_classes.add(name)
    names, procs = set(loaders), {n for n, hooked in loaders.items() if hooked}
    # an old-style loader's own aura script sits in its own class, nested in the loader: the hook is found there
    for name in loaders:
        if name in proc_classes:
            procs.add(name)
    # loader classes and whether anything inside them (their nested aura script) hooks a proc, up to the next
    # top-level declaration
    loader_hooked = {}
    for m in LOADER_CLASS.finditer(code):
        end = TOP_LEVEL.search(code, m.end())
        loader_hooked[m.group(1)] = bool(PROC_HOOK.search(code, m.start(), end.start() if end else len(code)))
    for m in NEW_LOADER.finditer(raw):
        if m.group(1) in loader_hooked:
            names.add(m.group(2))
            if loader_hooked[m.group(1)]:
                procs.add(m.group(2))
    for m in REGISTER.finditer(raw):
        kind, args = m.group(1), [a.strip() for a in m.group(2).split(',')]
        if kind == 'SpellScript':
            classes, name = args[:1], args[0]
        elif kind == 'SpellScriptWithArgs':
            classes, name = args[:1], args[1].strip('"') if len(args) > 1 else args[0]
        elif kind == 'SpellAndAuraScriptPair':
            classes, name = args[:2], args[0]
        else:
            classes, name = args[:2], args[2].strip('"') if len(args) > 2 else args[0]
        names.add(name)
        if any(c in proc_classes for c in classes):
            procs.add(name)
    return names, procs


def scan(src):
    spells, scripts, procs = {}, {}, set()
    for folder in ('game', 'scripts'):
        root = os.path.join(src, folder)
        for path, _, files in sorted(os.walk(root)):
            for name in sorted(files):
                if not name.endswith(('.cpp', '.h')):
                    continue
                full = os.path.join(path, name)
                rel = os.path.relpath(full, src).replace(os.sep, '/')
                with open(full, encoding='utf-8', errors='replace') as handle:
                    raw = handle.read()
                code = code_only(raw)
                if not NOT_SPELLS.search(rel):
                    for spell in spell_numbers(code):
                        # the file kept is one that handles spells if any does (see spell_file)
                        if spell not in spells or (spell_file(rel) and not spell_file(spells[spell])):
                            spells[spell] = rel
                if folder == 'scripts':
                    registered, hooked = scripts_of(code, raw)
                    for script in registered:
                        scripts.setdefault(script, rel)
                    procs |= hooked
    return spells, scripts, procs


def trigger_auras(src):
    """The numbers of the aura types the core's default proc entries accept (isTriggerAura[SPELL_AURA_X] = true)."""
    try:
        with open(os.path.join(src, 'game', 'Spells', 'SpellMgr.cpp'), encoding='utf-8', errors='replace') as handle:
            names = set(re.findall(r'isTriggerAura\[(SPELL_AURA_\w+)\]\s*=\s*true', code_only(handle.read())))
        with open(os.path.join(src, 'game', 'Spells', 'Auras', 'SpellAuraDefines.h'), encoding='utf-8', errors='replace') as handle:
            values = {m.group(1): int(m.group(2)) for m in re.finditer(r'\b(SPELL_AURA_\w+)\s*=\s*(\d+)', code_only(handle.read()))}
    except OSError:
        return []
    return sorted(values[name] for name in names if name in values)


def commit(core):
    try:
        return subprocess.run(['git', '-C', core, 'rev-parse', '--short=10', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    core = argv[1]
    src = os.path.join(core, 'src', 'server')
    if not os.path.isdir(os.path.join(src, 'scripts')):
        raise SystemExit(f'{src}: not a TrinityCore source tree')
    spells, scripts, procs = scan(src)
    out = {'source': 'TrinityCore C++ (src/server/game, src/server/scripts): spell ids the code names, spell scripts it registers',
           'commit': argv[2] if len(argv) > 2 else commit(core),
           'spells': {str(k): spells[k] for k in sorted(spells)},
           'scripts': {k: scripts[k] for k in sorted(scripts)},
           'proc_scripts': sorted(procs),
           'trigger_auras': trigger_auras(src)}
    with open(OUT, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(out, handle, indent=0, sort_keys=False)
        handle.write('\n')
    print(f'{len(spells)} spell ids named by the C++, {len(scripts)} spell scripts registered ({len(procs)} with a proc hook) -> {OUT}')


if __name__ == '__main__':
    main(sys.argv)
