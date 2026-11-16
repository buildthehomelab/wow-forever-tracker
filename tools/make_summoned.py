#!/usr/bin/env python3
"""Writes tools/world/summoned.json: what a TrinityCore C++ script brings into the world, and which creature an
instance script counts as which boss.

The database knows some summons (SmartAI, summon groups, summoning spells), but most dungeon events are C++:
`instance->SummonCreature(NPC_GANDLING, ...)`. Such a boss has no spawn row and never will, so without this list
the analysis calls it missing and the locator offers to spawn it for good.

Three lists:
  creatures   entry -> script, for every SummonCreature / DoSummon call with a known entry (also a script's own
              helper named Summon...Creature, every entry of an array the call picks from, and what an instance's
              GetCreatureEntry hook swaps a spawn for)
  objects     entry -> script, the same for SummonGameObject (a boss's chest)
  encounters  DungeonEncounter id -> creature entries, from the instance scripts' own tables: the encounter list
              `{ DATA_UROK_DOOMHOWL, {{ 271 }} }` joined to the creature of that boss (`{ NPC_X, DATA_X }`,
              `{ ENC_X, 7273 }`, or the constant of the same name, NPC_UROK_DOOMHOWL). It says which creature is the
              boss without comparing names, and it covers a boss the script creates from a variable.

    python tools/make_summoned.py /path/to/TrinityCore            (reads src/server/scripts)

Only calls whose first argument is a number or a constant the scripts define with a number are kept; a variable
(`SummonCreature(entry, ...)`) is left out, so the list errs on the side of fewer entries. Run it again when the
core moves to a commit with new scripts.
"""
import json
import os
import re
import subprocess
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'world', 'summoned.json')

CONSTANT = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)\s*[,;}\n]')
# Calls that create a creature or a world object from an entry given as their first argument.
CREATURE_CALLS = ('SummonCreature', 'DoSummon', 'DoSummonFlyer', 'DoSpawnCreature', 'SummonTrigger')
OBJECT_CALLS = ('SummonGameObject', 'DoSummonGameObject')
# A script's own helper named so (`SummonRookeryCreature(NPC_SOLAKAR, ...)`) counts as such a call too. The first
# argument may pick from an array (`SummonCreature(BrdRingBoss[urand(0, 5)], ...)`): every entry of the array counts.
HELPER = r'\w*Summon\w*(?:Creature|GameObject)\w*'
CALL = re.compile(r'\b(' + '|'.join(CREATURE_CALLS + OBJECT_CALLS) + '|' + HELPER + r')\s*\(\s*([A-Za-z_][A-Za-z0-9_:]*|\d+)\s*(\[|[,)])')
# `uint32 const BrdRingBoss[] = { 9027, 9028, ... };`: a one-level array of numbers or constants
ARRAY = re.compile(r'\b([A-Za-z_]\w*)\s*\[\s*\w*\s*\]\s*=\s*\{([^{}]*)\}')
# An instance's GetCreatureEntry hook swaps a spawn's creature for another (a rare instead of its placeholder):
# every creature it returns comes into the world
ENTRY_HOOK = re.compile(r'\bGetCreatureEntry\s*\([^)]*\)[^{;]*\{')
COMMENT = re.compile(r'//[^\n]*|/\*.*?\*/', re.S)
NAME = r'[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*'
# { DATA_X, {{ 271 }} }: a boss slot of the instance and its DungeonEncounter ids
ENCOUNTER = re.compile(r'\{\s*(' + NAME + r')\s*,\s*\{\s*\{\s*([\d,\s]+?)\s*\}\s*\}\s*\}')
# { NPC_X, DATA_X } or { ENC_X, 7273 } or { ENC_X, 7797, FLAGS }: two names or numbers at the start of a table row
PAIR = re.compile(r'\{\s*(' + NAME + r'|\d+)\s*,\s*(' + NAME + r'|\d+)\s*(?:,[^{}]*)?\}')
SLOT_PREFIX = re.compile(r'^(?:DATA|BOSS|TYPE|ENCOUNTER|ENC|[A-Z0-9]+_ENC)_')
CREATURE_PREFIXES = ('NPC_', 'ENTRY_', 'BOSS_', 'CREATURE_', 'MOB_')
MIN_ENTRY = 100   # below that a number is a slot of the instance, not a creature


def read(path):
    with open(path, encoding='utf-8', errors='replace') as handle:
        return COMMENT.sub('', handle.read())


def scan(scripts):
    """({creature entry: script}, {object entry: script}) for every script file under `scripts`."""
    texts = {}
    for folder, _dirs, files in os.walk(scripts):
        for name in files:
            if name.endswith(('.cpp', '.h')):
                path = os.path.join(folder, name)
                texts[path] = read(path)
    by_file, by_folder, everywhere = {}, {}, {}
    for path, text in texts.items():
        for name, value in CONSTANT.findall(text):
            value = int(value)
            by_file.setdefault(path, {}).setdefault(name, set()).add(value)
            by_folder.setdefault(os.path.dirname(path), {}).setdefault(name, set()).add(value)
            everywhere.setdefault(name, set()).add(value)

    def resolve(path, token):
        """The entry a call's first argument stands for: a number, or a constant with one value in this file, else in
        this folder (an instance's header), else anywhere in the scripts. A name with several values is unknown."""
        if token.isdigit():
            return int(token)
        name = token.rsplit('::', 1)[-1]
        for scope in (by_file.get(path, {}), by_folder.get(os.path.dirname(path), {}), everywhere):
            values = scope.get(name)
            if values:
                return next(iter(values)) if len(values) == 1 else None
        return None

    arrays = {}   # (folder, name) -> [tokens], and (None, name) for a name used once anywhere
    for path, text in texts.items():
        for name, body in ARRAY.findall(text):
            tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_:]*|\d+', body)
            arrays.setdefault((path, name), tokens)
            arrays.setdefault((os.path.dirname(path), name), tokens)
            arrays.setdefault((None, name), tokens)

    creatures, objects = {}, {}
    for path in sorted(texts):
        script = os.path.relpath(path, scripts).replace(os.sep, '/')
        text = texts[path]
        for call, token, after in CALL.findall(text):
            helper = call not in CREATURE_CALLS + OBJECT_CALLS
            if helper and 'Group' in call:
                continue   # SummonCreatureGroup(id): a summon group of the database (read from creature_summon_groups)
            if after == '[':   # an array: every entry it holds
                name = token.rsplit('::', 1)[-1]
                tokens = arrays.get((path, name)) or arrays.get((os.path.dirname(path), name)) or arrays.get((None, name)) or []
            else:
                tokens = [token]
            is_object = call in OBJECT_CALLS or 'GameObject' in call
            for t in tokens:
                entry = resolve(path, t)
                # an array, or a script's own helper, with small numbers holds slots or indexes, not creatures
                if entry and (not (helper or after == '[') or entry >= MIN_ENTRY):
                    (objects if is_object else creatures).setdefault(entry, script)
        for hook in ENTRY_HOOK.finditer(text):
            depth, i = 1, hook.end()
            while depth and i < len(text):
                depth += {'{': 1, '}': -1}.get(text[i], 0)
                i += 1
            for token in re.findall(r'\breturn\s+([A-Za-z_][A-Za-z0-9_:]*|\d+)\s*;', text[hook.end():i]):
                entry = resolve(path, token)
                if entry and entry >= MIN_ENTRY:
                    creatures.setdefault(entry, script)

    def creature_entry(path, token):
        """The creature a table cell names, or None: a number, or a constant named as a creature (a door table pairs a
        world object with the boss slot in the same shape)."""
        short = token.rsplit('::', 1)[-1]
        if not token.isdigit() and not short.startswith(CREATURE_PREFIXES):
            return None
        entry = resolve(path, token)
        return entry if entry and entry >= MIN_ENTRY else None

    # An instance's files share its boss slots (the header declares them): one folder, one instance.
    slots = {}   # folder -> {slot name: encounter ids}
    for path, text in texts.items():
        for slot, ids in ENCOUNTER.findall(text):
            found = {int(x) for x in re.findall(r'\d+', ids)} - {0}
            if found:
                slots.setdefault(os.path.dirname(path), {}).setdefault(slot.rsplit('::', 1)[-1], set()).update(found)
    encounters = {}
    for folder, names in slots.items():
        bound = {}   # slot name -> creature entries
        for path, text in texts.items():
            if os.path.dirname(path) != folder:
                continue
            for left, right in PAIR.findall(text):
                left_name, right_name = left.rsplit('::', 1)[-1], right.rsplit('::', 1)[-1]
                if left_name in names and right_name not in names:
                    slot, entry = left_name, creature_entry(path, right)
                elif right_name in names and left_name not in names:
                    slot, entry = right_name, creature_entry(path, left)
                else:
                    continue
                if entry:
                    bound.setdefault(slot, set()).add(entry)
        for slot, ids in names.items():
            entries = bound.get(slot, set())
            if not entries:   # no table names the creature: the constant of the same name (NPC_UROK_DOOMHOWL)
                suffix = SLOT_PREFIX.sub('', slot)
                for prefix in CREATURE_PREFIXES:
                    values = by_folder.get(folder, {}).get(prefix + suffix, set())
                    entries |= {v for v in values if v >= MIN_ENTRY} if len(values) == 1 else set()
            for encounter in ids:
                if entries:
                    encounters.setdefault(encounter, set()).update(entries)
    return creatures, objects, encounters


def commit(core):
    try:
        return subprocess.run(['git', '-C', core, 'rev-parse', '--short=10', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    core = argv[1]
    scripts = os.path.join(core, 'src', 'server', 'scripts')
    if not os.path.isdir(scripts):
        raise SystemExit(f'{scripts}: not a TrinityCore source tree')
    creatures, objects, encounters = scan(scripts)
    out = {'source': 'TrinityCore C++ scripts (src/server/scripts): entries a script summons',
           'commit': argv[2] if len(argv) > 2 else commit(core),
           'creatures': {str(k): creatures[k] for k in sorted(creatures)},
           'objects': {str(k): objects[k] for k in sorted(objects)},
           'encounters': {str(k): sorted(encounters[k]) for k in sorted(encounters)}}
    with open(OUT, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(out, handle, indent=0, sort_keys=False)
        handle.write('\n')
    print(f'{len(creatures)} creatures and {len(objects)} world objects summoned by scripts, {len(encounters)} boss encounters tied to a creature -> {OUT}')


if __name__ == '__main__':
    main(sys.argv)
