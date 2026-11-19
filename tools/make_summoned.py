#!/usr/bin/env python3
"""Writes tools/world/summoned.json: what a TrinityCore C++ script brings into the world, and which creature an
instance script counts as which boss.

The database knows some summons (SmartAI, summon groups, summoning spells), but most dungeon events are C++:
`instance->SummonCreature(NPC_GANDLING, ...)`. Such a boss has no spawn row and never will, so without this list
the analysis calls it missing and the locator offers to spawn it for good.

Five lists:
  creatures   entry -> script, for every SummonCreature / DoSummon call with a known entry (also a script's own
              helper named Summon...Creature, every entry of an array the call picks from, and what an instance's
              GetCreatureEntry hook swaps a spawn for)
  objects     entry -> script, the same for SummonGameObject (a boss's chest)
  encounters  DungeonEncounter id -> creature entries, from the instance scripts' own tables: the encounter list
              `{ DATA_UROK_DOOMHOWL, {{ 271 }} }` joined to the creature of that boss (`{ NPC_X, DATA_X }`,
              `{ ENC_X, 7273 }`, or the constant of the same name, NPC_UROK_DOOMHOWL). It says which creature is the
              boss without comparing names, and it covers a boss the script creates from a variable.
  credits     entry -> script, for every KilledMonsterCredit / RewardPlayerAndGroupAtEvent call: a quest objective's
              marker the script credits (Arathi Basin's bases, 15001-15005), which no spawn stands for
  teleports   map id -> script, for every `TeleportTo(map, ...)` with a known map: an instance a script takes the
              player into (City of Dalaran's sewer grate) has an entrance no table shows.

    python tools/make_summoned.py /path/to/TrinityCore            (reads src/server/scripts)

A call's first argument counts when it is a number or a constant the scripts define with a number. Any argument of a
summoning call counts when it is a constant named as a creature (NPC_…) or object (GO_…): a script's helper that takes
the entry later (`SummonNPC(me, player, NPC_TEMPLAR_FIRE, SPELL_TEMPLAR_FIRE)`, `RAND(NPC_A, NPC_B)`). A field of a
table counts too (`SummonCreature(WavesInfo[i].CreatureId, ...)`, `for (SummonLocation const& s : AddLocations)
SummonCreature(s.entry, ...)`, `Row const& data = Rows[slot]; SummonCreature(data.Entry, ...)`): that field of every
row of the table, by the place of the field in the table's struct. Another variable (`SummonCreature(entry, ...)`) is
left out, so the list errs on the side of fewer entries. Run it again when the
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
# Any call that summons, to read every argument of: SummonNPC, SummonTemplar, DoSummon... but not what only looks at
# summons (GetSummonedCreature, JustSummoned, IsSummonedBy, SummonCreatureGroup: a database summon group)
ANY_CALL = re.compile(r'\b(\w*Summon\w*|DoSpawnCreature)\s*\(')
NOT_SUMMONING = re.compile(r'^(?:Get|Has|Is|Count|Find|Despawn|Remove|Un|Just|On|Handle)|Summoned|Summoner|Summons|Group|List')
OBJECT_PREFIXES = ('GO_', 'OBJECT_', 'GAMEOBJECT_')
# `Name[i].Field`, or `var.Field` / `var->Field` of a variable bound to a table's row
TABLE_FIELD = re.compile(r'^([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:\.|->)\s*([A-Za-z_]\w*)$')
# `Type const Name[] = {` and `std::array<Type, N> const Name = {`
TABLE = re.compile(r'\b(?:std::array\s*<\s*([A-Za-z_][\w:]*)\s*,[^>]*>|([A-Za-z_][\w:]*))\s+(?:const\s+|constexpr\s+)*([A-Za-z_]\w*)\s*(\[\s*\w*\s*\])?\s*=\s*\{')
STRUCT = re.compile(r'\b(?:struct|class)\s+([A-Za-z_]\w*)\s*(?::[^{;]*)?\{')
COMMENT = re.compile(r'//[^\n]*|/\*.*?\*/', re.S)
NAME = r'[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*'
# { DATA_X, {{ 271 }} }: a boss slot of the instance and its DungeonEncounter ids
ENCOUNTER = re.compile(r'\{\s*(' + NAME + r')\s*,\s*\{\s*\{\s*([\d,\s]+?)\s*\}\s*\}\s*\}')
# { 1, {{ 3499 }} }: the same with a numbered slot, and { 1, 261811 }: that slot's creature
ENCOUNTER_NUMBERED = re.compile(r'\{\s*(\d+)\s*,\s*\{\s*\{\s*([\d,\s]+?)\s*\}\s*\}\s*\}')
SLOT_ENTRY = re.compile(r'\{\s*(\d+)\s*,\s*(\d+)\s*\}')
# { NPC_X, DATA_X } or { ENC_X, 7273 } or { ENC_X, 7797, FLAGS }: two names or numbers at the start of a table row
PAIR = re.compile(r'\{\s*(' + NAME + r'|\d+)\s*,\s*(' + NAME + r'|\d+)\s*(?:,[^{}]*)?\}')
SLOT_PREFIX = re.compile(r'^(?:DATA|BOSS|TYPE|ENCOUNTER|ENC|[A-Z0-9]+_ENC)_')
CREATURE_PREFIXES = ('NPC_', 'ENTRY_', 'BOSS_', 'CREATURE_', 'MOB_')
MIN_ENTRY = 100   # below that a number is a slot of the instance, not a creature
# Calls that give a player the kill credit of a creature given as their first argument: a battleground's capture, a
# script's event. Such a creature is a quest objective's marker that no spawn ever stands for.
CREDIT = re.compile(r'\b(KilledMonsterCredit|RewardPlayerAndGroupAtEvent)\s*\(')


def read(path):
    with open(path, encoding='utf-8', errors='replace') as handle:
        return COMMENT.sub('', handle.read())


def named(token, prefixes):
    """A constant named as one of the prefixes says: NPC_X, or a script's own CLASSIC_BWL_NPC_X."""
    short = token.rsplit('::', 1)[-1]
    if re.search(r'SPELL|SOUND|SAY_|EMOTE|EVENT_|ACTION_|DATA_|POINT_|PATH_|MODEL_|DISPLAY_|TEXT_', short):
        return False   # a spell, text or event of the creature, not the creature
    return short.startswith(prefixes) or any('_' + p in short for p in prefixes)


def closing(text, start):
    """The index just past the bracket that closes the one at text[start] ('(' or '{')."""
    pairs = {'(': ')', '{': '}', '[': ']'}
    stack, i = [], start
    while i < len(text):
        c = text[i]
        if c in pairs:
            stack.append(pairs[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
        i += 1
    return len(text)


def split_top(text):
    """The parts of a list split at its commas outside brackets."""
    parts, depth, current = [], 0, ''
    for c in text:
        if c in '({[':
            depth += 1
        elif c in ')}]':
            depth -= 1
        if c == ',' and depth == 0:
            parts.append(current.strip())
            current = ''
        else:
            current += c
    if current.strip():
        parts.append(current.strip())
    return parts


def fields(body):
    """The data members of a struct body, in order (methods, nested types and access labels left out)."""
    flat, depth = '', 0
    for c in body:
        if c == '{':
            depth += 1
            flat += ' ' if depth > 1 else ''
            continue
        if c == '}':
            depth -= 1
            flat += ';' if depth == 0 else ''
            continue
        if depth == 0:
            flat += c
    out = []
    for statement in flat.split(';'):
        statement = re.sub(r'\b(?:public|private|protected)\s*:', '', statement).strip()
        if not statement or '(' in statement or re.match(r'(?:static|using|typedef|friend|enum|struct|class|template)\b', statement):
            continue
        parts = split_top(re.sub(r'\[[^\]]*\]', '', statement))
        for n, part in enumerate(parts):
            part = part.split('=')[0].strip()
            names = re.findall(r'[A-Za-z_]\w*', part)
            if names:
                out.append(names[-1] if n == 0 else names[0])
    return out


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

    structs, tables = {}, {}   # name -> fields; (scope, name) -> (struct name or '', [rows as parts])
    for path, text in texts.items():
        for m in STRUCT.finditer(text):
            structs.setdefault(m.group(1), fields(text[m.end():closing(text, m.end() - 1) - 1]))
        for m in TABLE.finditer(text):
            kind, name = (m.group(1) or m.group(2)).rsplit('::', 1)[-1], m.group(3)
            body = text[m.end():closing(text, m.end() - 1) - 1].strip()
            if m.group(1) and body.startswith('{') and closing(body, 0) == len(body):
                body = body[1:-1]   # std::array<T, N> x = {{ ... }}: the inner list
            rows = [split_top(part[1:-1]) for part in split_top(body) if part.startswith('{') and part.endswith('}')]
            if rows:
                for scope in (path, os.path.dirname(path), None):
                    tables.setdefault((scope, name), (kind, rows, body))

    def table_field(path, text, at, token):
        """The tokens a call's first argument stands for when it reads a field of a table's rows, else []."""
        m = TABLE_FIELD.match(token.strip())
        if not m:
            return []
        name, field = m.groups()
        found = tables.get((path, name)) or tables.get((os.path.dirname(path), name)) or tables.get((None, name))
        kind = None
        if not found:   # a variable bound to a row: `for (Row const& s : Table)`, `Row const& data = Table[i]`
            before = text[:at]
            binds = list(re.finditer(r'for\s*\(\s*([^;:()]*?)\b' + name + r'\s*:\s*([A-Za-z_][\w:]*)\s*\)', before))
            binds += list(re.finditer(r'([A-Za-z_][\w:<>\s]*?)[&*\s]\s*' + name + r'\s*=\s*&?\s*([A-Za-z_]\w*)\s*\[', before))
            if not binds:
                return []
            bind = max(binds, key=lambda b: b.start())
            table_name = bind.group(2).rsplit('::', 1)[-1]
            found = tables.get((path, table_name)) or tables.get((os.path.dirname(path), table_name)) or tables.get((None, table_name))
            kind = next((w for w in re.findall(r'[A-Za-z_]\w*', bind.group(1)) if w in structs), None)
        if not found:
            return []
        struct, rows, body = found
        names = structs.get(kind or struct)
        if names and field in names:
            index = names.index(field)
            return [row[index] for row in rows if index < len(row)]
        # a struct not found: the constants of the table named as creatures
        return [t for t in re.findall(r'[A-Za-z_]\w*', body) if named(t, CREATURE_PREFIXES)]

    creatures, objects = {}, {}
    for path in sorted(texts):
        script = os.path.relpath(path, scripts).replace(os.sep, '/')
        text = texts[path]
        for call, token, after in CALL.findall(text):
            helper = call not in CREATURE_CALLS + OBJECT_CALLS
            if helper and NOT_SUMMONING.search(call):
                continue   # SummonCreatureGroup(id): a summon group of the database (read from creature_summon_groups);
                           # GetSummonedCreatureByEntry(id): a look-up of one already there
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
        # every argument of a summoning call: constants named as creatures or objects, a field of a table
        for m in ANY_CALL.finditer(text):
            call = m.group(1)
            if NOT_SUMMONING.search(call) or text[:m.start()].rstrip().endswith(('void', 'bool', '::')):
                continue
            args = text[m.end():closing(text, m.end() - 1) - 1]
            is_object = call in OBJECT_CALLS or 'GameObject' in call
            parts = split_top(args)
            tokens = table_field(path, text, m.start(), parts[0]) if parts else []
            for t in tokens:
                entry = resolve(path, t) if re.fullmatch(r'[A-Za-z_][\w:]*|\d+', t) else None
                if entry and entry >= MIN_ENTRY:
                    (objects if is_object else creatures).setdefault(entry, script)
            for t in re.findall(r'\b[A-Za-z_][\w:]*', args):
                if named(t, OBJECT_PREFIXES if is_object else CREATURE_PREFIXES):
                    entry = resolve(path, t)
                    if entry and entry >= MIN_ENTRY:
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
    # A script that numbers its boss slots (`{ 1, {{ 3499 }} }`) names each boss's creature in a table of the same
    # file, `{ 1, 261811 }`: two numbers alone, the slot then the entry. Read in that file only, since a number says
    # far less than a name; an encounter of two creatures (Tor'Rel and Izha'Rel) has two such rows.
    for path, text in texts.items():
        numbered = {}
        for slot, ids in ENCOUNTER_NUMBERED.findall(text):
            found = {int(x) for x in re.findall(r'\d+', ids)} - {0}
            if found and int(slot) < MIN_ENTRY:
                numbered.setdefault(int(slot), set()).update(found)
        if not numbered:
            continue
        for slot, entry in SLOT_ENTRY.findall(text):
            slot, entry = int(slot), int(entry)
            if slot in numbered and entry >= MIN_ENTRY:
                for encounter in numbered[slot]:
                    encounters.setdefault(encounter, set()).add(entry)
    credits = {}
    for path in sorted(texts):
        script = os.path.relpath(path, scripts).replace(os.sep, '/')
        text = texts[path]
        for m in CREDIT.finditer(text):
            if text[:m.start()].rstrip().endswith(('void', 'bool', '::')):
                continue   # the function's own definition
            parts = split_top(text[m.end():closing(text, m.end() - 1) - 1])
            if not parts:
                continue
            first = parts[0].strip()
            tokens = table_field(path, text, m.start(), first) or ([first] if re.fullmatch(r'[A-Za-z_][\w:]*|\d+', first) else [])
            for t in tokens:
                entry = resolve(path, t.strip()) if re.fullmatch(r'[A-Za-z_][\w:]*|\d+', t.strip()) else None
                if entry and entry >= MIN_ENTRY:
                    credits.setdefault(entry, script)
    return creatures, objects, encounters, credits


TELEPORT = re.compile(r'\bTeleportTo\s*\(\s*([A-Za-z_][\w:]*|\d+)\s*,')


def teleports(scripts):
    """{map id: script} for every TeleportTo(map, x, y, ...) whose map is a number or a constant the scripts define
    with one value (in the file, else its folder, else anywhere). A map given by a variable is left out."""
    texts = {}
    for folder, _dirs, files in os.walk(scripts):
        for name in files:
            if name.endswith(('.cpp', '.h')):
                path = os.path.join(folder, name)
                texts[path] = read(path)
    by_file, by_folder, everywhere = {}, {}, {}
    for path, text in texts.items():
        for name, value in CONSTANT.findall(text):
            by_file.setdefault(path, {}).setdefault(name, set()).add(int(value))
            by_folder.setdefault(os.path.dirname(path), {}).setdefault(name, set()).add(int(value))
            everywhere.setdefault(name, set()).add(int(value))
    out = {}
    for path in sorted(texts):
        script = os.path.relpath(path, scripts).replace(os.sep, '/')
        for token in TELEPORT.findall(texts[path]):
            if token.isdigit():
                out.setdefault(int(token), script)
                continue
            name = token.rsplit('::', 1)[-1]
            for scope in (by_file.get(path, {}), by_folder.get(os.path.dirname(path), {}), everywhere):
                values = scope.get(name)
                if values:
                    if len(values) == 1:
                        out.setdefault(next(iter(values)), script)
                    break
    return out


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
    creatures, objects, encounters, credits = scan(scripts)
    maps = teleports(scripts)
    out = {'source': 'TrinityCore C++ scripts (src/server/scripts): entries a script summons',
           'commit': argv[2] if len(argv) > 2 else commit(core),
           'creatures': {str(k): creatures[k] for k in sorted(creatures)},
           'objects': {str(k): objects[k] for k in sorted(objects)},
           'encounters': {str(k): sorted(encounters[k]) for k in sorted(encounters)},
           'credits': {str(k): credits[k] for k in sorted(credits)},
           'teleports': {str(k): maps[k] for k in sorted(maps)}}
    with open(OUT, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(out, handle, indent=0, sort_keys=False)
        handle.write('\n')
    print(f'{len(creatures)} creatures and {len(objects)} world objects summoned by scripts, {len(encounters)} boss encounters tied to a creature, '
          f'{len(credits)} creatures whose kill credit a script gives, {len(maps)} maps scripts teleport into -> {OUT}')


if __name__ == '__main__':
    main(sys.argv)
