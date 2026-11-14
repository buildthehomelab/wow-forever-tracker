"""Release phases: content the official client already carries but the game has not opened yet.

tools/phases/forever.json (or [phases] file) lists the phases in release order. A phase names what it opens: instances
(by English name or map id) and, when the instance alone is not enough, creatures, objects, quests and items. The rest
follows from the server's data:

- an instance's bosses, and the creatures and objects spawned only inside tagged instances (or, not spawned yet,
  named like one of their bosses or placed there by the locator);
- an item whose every source is tagged: creature loot, vendors, chests, quest rewards, containers, crafts;
- a quest whose givers (starting item included) or enders are all tagged, or one of whose objectives is; a quest sorted
  under a tagged instance too, unless both a giver and an ender stand in the open world;
- a spell, recipe, mount or pet only taught by tagged items or quests; a toy by its item.

A source of the open world (a trainer, fishing, a vendor outside...) keeps the thing released: the tracker would rather
show a gap too many than hide one. Each tagged resource gets the phase's number (1 for the first phase); 0 is
released content. Whether a phase is open is decided by the website (its date, or [phases] current), so a phase
opening needs no new analysis.
"""
import datetime
import json
import os
import re

from . import sqlio
from .config import CONFIG, PROJECT
from .server import log

DEFAULT = os.path.join(PROJECT, 'tools', 'phases', 'forever.json')
KINDS = ('maps', 'npcs', 'objects', 'quests', 'items')


def normal(name):
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def path():
    """The phase file: [phases] file of config.ini (relative to the project), 'none' for no phases."""
    value = CONFIG.get('phases', 'file')
    if value.lower() == 'none':
        return None
    if not value:
        return DEFAULT
    return value if os.path.isabs(value) else os.path.join(PROJECT, value)


def load(file=None):
    """[{'key', 'name', 'opens', 'source', 'maps', 'npcs', ...}] in release order; [] without a file."""
    file = file if file is not None else path()
    if not file or not os.path.isfile(file):
        if file and file != DEFAULT:
            log(f'phases: {file} not found, no release phases')
        return []
    with open(file, encoding='utf-8-sig') as handle:
        phases = json.load(handle).get('phases', [])
    seen = set()
    for index, phase in enumerate(phases):
        key = str(phase.get('key') or f'phase-{index + 1}')
        if key in seen:
            raise SystemExit(f'phases: key "{key}" twice in {file}')
        seen.add(key)
        phase['key'] = key
        opens = phase.get('opens')
        if opens:
            datetime.date.fromisoformat(opens)  # a typo stops the analysis rather than opening a phase on the wrong day
        for kind in KINDS:
            values = phase.get(kind) or []
            if not isinstance(values, list):
                raise SystemExit(f'phases: "{kind}" of {key} must be a list')
            if kind in ('objects', 'quests', 'items') and any(not str(v).isdigit() for v in values):
                raise SystemExit(f'phases: "{kind}" of {key} takes ids only')
            phase[kind] = values
    return phases


def closed(phases, current='', today=None):
    """Numbers (from 1) of the phases not open yet, by the website's rule (closed_phases() in app/bootstrap.php):
    [phases] current decides when set ("all", "none", or a key or number that opens it and every phase before it);
    otherwise each phase opens on its own date, and one without a date stays closed."""
    current = str(current or '').strip().lower()
    keys = [str(p.get('key', '')).lower() for p in phases]
    up_to = None
    if current == 'all':
        up_to = len(phases)
    elif current in ('none', 'false', 'off', 'no'):
        up_to = 0
    elif current.isdigit():
        up_to = min(int(current), len(phases))
    elif current in keys:
        up_to = keys.index(current) + 1
    today = today or datetime.date.today().isoformat()
    return [n for n, p in enumerate(phases, 1) if not (n <= up_to if up_to is not None else bool(p.get('opens')) and str(p['opens']) <= today)]


def world_facts(phases, content):
    """What the server's databases add (kept apart so tests can pass their own): creature names for the name matches,
    where objects stand, and where the locator placed the creatures and objects not spawned yet."""
    wanted = set()
    tagged_maps = set(map_phases(phases, content))
    for boss in content.get('boss', {}).values():
        if boss.get('map') in tagged_maps:
            wanted.add(boss.get('name_en') or boss.get('name') or '')
    for phase in phases:
        wanted |= {v for v in phase['npcs'] if isinstance(v, str)}
    wanted.discard('')
    names = {}
    if wanted:
        listed = ','.join(sqlio.escape(n) for n in sorted(wanted))
        names = {int(r['entry']): r['name'] for r in sqlio.query(f'SELECT entry, name FROM creature_template WHERE name IN ({listed})')}
    go_maps = [(int(r['id']), int(r['map'])) for r in sqlio.query('SELECT DISTINCT id, map FROM gameobject')]
    located = []
    if sqlio.has_table('ft_spawns', 'tracker'):
        located = [(r['kind'], int(r['entry']), int(r['map'])) for r in sqlio.query('SELECT kind, entry, map FROM ft_spawns WHERE map IS NOT NULL', 'tracker')]
    return {'npc_names': names, 'go_maps': go_maps, 'located': located}


def map_phases(phases, content):
    """{map id: phase number} of the tagged instances (the first phase that names a map wins)."""
    by_name = {}
    for map_id, dungeon in content.get('dungeon', {}).items():
        for name in (dungeon.get('name_en'), dungeon.get('name')):
            if name:
                by_name.setdefault(normal(name), set()).add(map_id)
    out = {}
    for number, phase in enumerate(phases, 1):
        for value in phase['maps']:
            ids = {int(value)} if isinstance(value, int) or str(value).isdigit() else by_name.get(normal(value), set())
            for map_id in ids:
                out.setdefault(map_id, number)
    return out


def unmatched_maps(phases, content):
    """The names in the phase file no instance of the client carries (encrypted, renamed, or a typo)."""
    known = {normal(d.get(k)) for d in content.get('dungeon', {}).values() for k in ('name_en', 'name')}
    return [(phase['key'], value) for phase in phases for value in phase['maps'] if isinstance(value, str) and not value.isdigit() and normal(value) not in known]


def assign(content, ctx, phases, facts):
    """{(type, id): phase number} for the official resources a later phase opens (released ones are left out)."""
    if not phases:
        return {}
    map_phase = map_phases(phases, content)

    def spawn_phases(pairs):
        """{entry: phase} for entries spawned only on tagged maps (the lowest phase of their maps)."""
        lowest = {}
        for entry, map_id in pairs:
            lowest[entry] = min(lowest.get(entry, 10 ** 6), map_phase.get(map_id, 0))
        return {entry: p for entry, p in lowest.items() if p}

    npc_pairs = [(npc['id'], map_id) for map_id, npcs in ctx.get('npc_maps', {}).items() for npc in npcs]
    npc_phase = spawn_phases(npc_pairs)
    spawned_npc = {npc for npc, _ in npc_pairs}
    go_phase = spawn_phases(facts.get('go_maps', []))
    spawned_go = {go for go, _ in facts.get('go_maps', [])}
    for kind, entry, map_id in facts.get('located', []):
        target, spawned = (npc_phase, spawned_npc) if kind == 'npc' else (go_phase, spawned_go)
        if entry not in spawned and map_phase.get(map_id):
            target[entry] = min(target.get(entry, 10 ** 6), map_phase[map_id])
    boss_phase = {}
    for boss in content.get('boss', {}).values():
        p = map_phase.get(boss.get('map'))
        if p:
            name = normal(boss.get('name_en') or boss.get('name'))
            boss_phase[name] = min(boss_phase.get(name, p), p)
    npc_by_name = {}
    for entry, name in facts.get('npc_names', {}).items():
        npc_by_name.setdefault(normal(name), set()).add(entry)
        if entry not in spawned_npc and normal(name) in boss_phase:
            npc_phase[entry] = min(npc_phase.get(entry, 10 ** 6), boss_phase[normal(name)])

    fixed = {kind: {} for kind in ('npc', 'go', 'quest', 'item')}
    for number, phase in enumerate(phases, 1):
        for value in phase['npcs']:
            for entry in ({int(value)} if isinstance(value, int) or str(value).isdigit() else npc_by_name.get(normal(value), set())):
                fixed['npc'].setdefault(entry, number)
        for kind, field in (('go', 'objects'), ('quest', 'quests'), ('item', 'items')):
            for value in phase[field]:
                fixed[kind].setdefault(int(value), number)
    npc_phase.update(fixed['npc'])
    go_phase.update(fixed['go'])

    # ---- item sources: ('npc', id), ('go', id), ('item', container), ('spell', id), ('quest', id); () = the open world
    loot = ctx.get('loot', {})
    references = {}
    for entry, kind, item, ref in loot.get('reference', []):
        references.setdefault(entry, []).append((kind, item, ref))
    expanded = {}

    def expand(rows):
        out, stack, seen = set(), list(rows), set()
        while stack:
            kind, item, ref = stack.pop()
            if ref:
                if ref in seen:
                    continue
                seen.add(ref)
                if ref in expanded:
                    out |= expanded[ref]
                else:
                    stack.extend(references.get(ref, []))
            elif kind == 0 and item:
                out.add(item)
        return out

    def grouped(name):
        rows = {}
        for entry, kind, item, ref in loot.get(name, []):
            rows.setdefault(entry, []).append((kind, item, ref))
        return {entry: expand(r) for entry, r in rows.items()}

    for ref in references:
        expanded[ref] = expand([(1, ref, ref)])
    tables = {name: grouped(name) for name in ('creature', 'pickpocketing', 'skinning', 'gameobject', 'item', 'spell')}
    sources = {}

    def add(items, source):
        for item in items:
            sources.setdefault(item, set()).add(source)

    for npc, loot_id, pick, skin in ctx.get('npc_loot', []):
        for name, entry in (('creature', loot_id), ('pickpocketing', pick), ('skinning', skin)):
            if entry:
                add(tables[name].get(entry, ()), ('npc', npc))
    for go, _type, data in ctx.get('go_loot', []):
        if data:
            add(tables['gameobject'].get(data, ()), ('go', go))
    for npc, item in ctx.get('vendors', ()):
        add([item], ('npc', npc))
    for npc, item in ctx.get('quest_items_npc', ()):
        add([item], ('npc', npc))
    for go, item in ctx.get('quest_items_go', ()):
        add([item], ('go', go))
    world = ()
    for name in ('fishing', 'mail', 'disenchant', 'prospecting', 'milling'):
        for items in grouped(name).values():
            add(items, world)
    add(ctx.get('shop_items', ()), world)
    for container, items in tables['item'].items():
        add(items, ('item', container))
    for spell, items in tables['spell'].items():
        add(items, ('spell', spell))
    for item, spells in ctx.get('creates', {}).items():
        for spell in spells:
            add([item], ('spell', spell))
    # Only the quests the official client has: the world database also holds quests of other versions of the game,
    # and a reward of one of those would release an item nobody can earn that way (the analysis' rules count the
    # same quests).
    official = content.get('quest') or {}
    quests = {quest: row for quest, row in ctx.get('quests', {}).items() if not official or quest in official}
    for quest, row in quests.items():
        rewards = {int(row.get(f'RewardItem{i}') or 0) for i in range(1, 5)} | {int(row.get(f'RewardChoiceItemID{i}') or 0) for i in range(1, 7)}
        add((rewards | {int(row.get('StartItem') or 0)}) - {0}, ('quest', quest))   # StartItem: handed over on accept

    # ---- spell sources: trainers and automatic learning are the open world
    spell_sources = {}
    for spell in {s for _, s in ctx.get('trainer_spells', ())} | ctx.get('auto_learn', set()) | ctx.get('create_spells', set()):
        spell_sources.setdefault(spell, set()).add(world)
    for spell, items in ctx.get('teaches', {}).items():
        for item in items:
            spell_sources.setdefault(spell, set()).add(('item', item))
    for quest, row in quests.items():
        shown = {int(row.get(key) or 0) for key in ('RewardSpell', 'RewardDisplaySpell1', 'RewardDisplaySpell2', 'RewardDisplaySpell3')}
        for spell in (shown | ctx.get('quest_display_spells', {}).get(quest, set())) - {0}:
            spell_sources.setdefault(spell, set()).add(('quest', quest))
    for source, target in ctx.get('learn_chain', ()):
        spell_sources.setdefault(target, set()).add(('spell', source))

    # ---- quests: where they are sorted, who gives and ends them, what they ask
    area_phase = {}
    for map_id, dungeon in content.get('dungeon', {}).items():
        area = (dungeon.get('facts') or {}).get('area')
        if area and map_phase.get(map_id):
            area_phase[int(area)] = map_phase[map_id]
    starters, enders, objectives = {}, {}, {}
    for npc, quest in ctx.get('q_start_npc', ()):
        starters.setdefault(quest, set()).add(('npc', npc))
    for go, quest in ctx.get('q_start_go', ()):
        starters.setdefault(quest, set()).add(('go', go))
    for quest, item in ctx.get('start_quest_item', {}).items():
        starters.setdefault(quest, set()).add(('item', item))
    for npc, quest in ctx.get('q_end_npc', ()):
        enders.setdefault(quest, set()).add(('npc', npc))
    for go, quest in ctx.get('q_end_go', ()):
        enders.setdefault(quest, set()).add(('go', go))
    for quest, kind, obj, _amount in ctx.get('objectives', ()):
        source = {0: 'npc', 1: 'item', 2: 'go'}.get(kind)
        if source and obj:
            objectives.setdefault(quest, set()).add((source, obj))

    item_phase, quest_phase, spell_phase = dict(fixed['item']), dict(fixed['quest']), {}
    phase_of = {'npc': npc_phase, 'go': go_phase, 'item': item_phase, 'quest': quest_phase, 'spell': spell_phase}

    def lowest(found):
        """The lowest phase of a set of sources (0 as soon as one is released); 0 for no source at all."""
        best = None
        for source in found:
            p = phase_of[source[0]].get(source[1], 0) if source else 0
            if not p:
                return 0
            best = p if best is None else min(best, p)
        return best or 0

    # A fixed point from below: every value only rises, so this ends; a loop of sources stays released.
    for _round in range(20):
        changed = 0
        for item, found in sources.items():
            if item in fixed['item']:
                continue
            p = lowest(found)
            if p != item_phase.get(item, 0):
                item_phase[item] = p
                changed += 1
        for quest, row in quests.items():
            if quest in fixed['quest']:
                continue
            start, end = starters.get(quest, ()), enders.get(quest, ())
            start_p, end_p = lowest(start), lowest(end)
            # the sort area alone does not close a quest players can pick up and hand in outside (an attunement sorted
            # under its raid): it counts only when a giver or an ender is missing or tagged
            area_p = 0 if start and end and not start_p and not end_p else area_phase.get(int(row.get('QuestSortID') or 0), 0)
            p = max(area_p, start_p, end_p, max((phase_of[s[0]].get(s[1], 0) for s in objectives.get(quest, ())), default=0))
            if p != quest_phase.get(quest, 0):
                quest_phase[quest] = p
                changed += 1
        for spell, found in spell_sources.items():
            p = lowest(found)
            if p != spell_phase.get(spell, 0):
                spell_phase[spell] = p
                changed += 1
        if not changed:
            break
    else:
        log('phases: still changing after 20 rounds, some resources may stay untagged')

    # An item with no source at all says nothing about when it opens, and would count as a gap of today. When
    # every item of the same name that does have a source waits for a phase, it waits with them: Forever's own copy
    # of Sulfuras (a new id, no loot row yet) is no more a launch gap than the original.
    named = {}
    for item, entity in content.get('item', {}).items():
        name = normal(entity.get('name_en') or entity.get('name'))
        if name and item in sources:
            named.setdefault(name, []).append(item_phase.get(item, 0))
    for item, entity in content.get('item', {}).items():
        if item not in sources and item not in fixed['item']:
            twins = named.get(normal(entity.get('name_en') or entity.get('name')), [])
            if twins and all(twins):
                item_phase[item] = min(twins)

    out = {}

    def put(kind, entity_id, p):
        if p:
            out[(kind, entity_id)] = p

    for map_id in content.get('dungeon', {}):
        put('dungeon', map_id, map_phase.get(map_id, 0))
    for boss_id, boss in content.get('boss', {}).items():
        put('boss', boss_id, map_phase.get(boss.get('map'), 0))
    for quest in content.get('quest', {}):
        put('quest', quest, quest_phase.get(quest, 0))
    for item in content.get('item', {}):
        put('item', item, item_phase.get(item, 0))
    for kind in ('spell', 'recipe'):
        for spell in content.get(kind, {}):
            put(kind, spell, spell_phase.get(spell, 0))
    for kind in ('mount', 'pet'):
        for entity_id, entity in content.get(kind, {}).items():
            put(kind, entity_id, spell_phase.get(int(entity.get('spell') or 0), 0))
    for toy_id, toy in content.get('toy', {}).items():
        put('toy', toy_id, item_phase.get(int(toy.get('item') or 0), 0))
    return out


def run(content, ctx):
    """(phase list for ft_meta, {(type, id): phase number}) for the analysis; logs what it tagged."""
    phases = load()
    if not phases:
        return [], {}
    for key, value in unmatched_maps(phases, content):
        log(f'phases: no instance named "{value}" in the client ({key}): encrypted, renamed or a typo')
    tagged = assign(content, ctx, phases, world_facts(phases, content))
    counts = {}
    for (kind, _id), number in tagged.items():
        counts.setdefault(phases[number - 1]['key'], {}).setdefault(kind, 0)
        counts[phases[number - 1]['key']][kind] += 1
    for phase in phases:
        found = counts.get(phase['key'], {})
        log(f"phase {phase['key']} ({phase.get('opens') or 'no date'}): " + (', '.join(f'{k}={v}' for k, v in sorted(found.items())) or 'nothing tagged'))
    listing = [{'key': p['key'], 'name': p.get('name') or p['key'], 'opens': p.get('opens'), 'source': p.get('source', ''),
                'counts': counts.get(p['key'], {})} for p in phases]
    return listing, tagged
