"""Makes a pack of what the original game's database says about who teaches a spell.

    python tools/classicdb_pack.py ClassicDB_1_12_1_z2815.sql.gz out.cdbpack

The source is the full dump of cmangos' classic-db (github.com/cmangos/classic-db, Full_DB/, GPL-3.0): the content
database of the 1.12 game. Only the dump is read, as text; nothing is run and no database is needed. The pack is a
few hundred kB of gzipped JSON holding:

    trainers   [npc, spell, cost, skill line, skill rank, level]   npc_trainer, and npc_trainer_template through the
                                                                   creatures that use each template
    quests     [quest, RewSpell, RewSpellCast]                     quests that show or cast a spell at the turn-in
    gossip     [npc, spell]                                        spells a line of a creature's conversation casts
                                                                   (how Classic teaches a recipe without a trainer
                                                                   window: Knot Thimblejack, the transporter gnomes)
    talk       [kind, entry, text, spell, terms]                  a line of a creature's ('npc') or a quest-giver
                                                                   object's ('go') conversation that casts a spell, with
                                                                   the conditions of every line on the way to it (terms())
    drops      [kind, entry, item, chance]                        a creature ('npc') or chest ('go') that drops an item
                                                                   that teaches (a recipe, an item learned on use), its
                                                                   chance in %, loot groups and references worked out;
                                                                   world drops (more than WORLD_DROP creatures) left out
    sells      [npc, item, stock]                                 a vendor of such an item (stock 0: no limit)
    world_drops [item]                                            such items left out of drops as world drops
    holidays   {event: {name, creatures, objects}}                what spawns only while an event runs (holidays(),
                                                                   format 4): the Darkmoon Faire, the fishing contest...
    never_given [item]                                            items the original game gave out nowhere (no loot,
                                                                   vendor, quest or spell): removed or never released

and the names of the creatures, objects and quests it mentions. The website's Imports page takes the pack
(docs/SOURCES.md).
"""
import datetime
import gzip
import json
import re
import sys

WANTED = {'quest_template', 'npc_trainer', 'npc_trainer_template', 'creature_template', 'gameobject_template', 'gossip_menu_option',
          'dbscripts_on_gossip', 'conditions', 'db_version', 'item_template', 'creature_loot_template', 'gameobject_loot_template',
          'reference_loot_template', 'npc_vendor', 'npc_vendor_template', 'item_loot_template', 'fishing_loot_template',
          'skinning_loot_template', 'pickpocketing_loot_template', 'disenchant_loot_template', 'mail_loot_template',
          'spell_loot_template', 'spell_template', 'game_event', 'game_event_creature', 'game_event_gameobject', 'creature', 'gameobject',
          'creature_spawn_entry', 'gameobject_spawn_entry'}
# Every table through which the original game gave an item out: its rows' `item` column (loot of any kind, vendors)
GIVING_TABLES = ('creature_loot_template', 'gameobject_loot_template', 'reference_loot_template', 'item_loot_template', 'fishing_loot_template',
                 'skinning_loot_template', 'pickpocketing_loot_template', 'disenchant_loot_template', 'mail_loot_template',
                 'spell_loot_template', 'npc_vendor', 'npc_vendor_template')
QUEST_ITEMS = tuple(f'RewItemId{i}' for i in range(1, 5)) + tuple(f'RewChoiceItemId{i}' for i in range(1, 7)) + ('SrcItemId',)
CREATE_ITEM = 24   # spell effect: the item EffectItemType
CAST_SPELL = 15   # dbscripts command: datalong is the spell
GO_QUESTGIVER = 2   # gameobject_template.type whose data3 is its conversation menu
# Classic's conditions (cmangos `conditions`) that a conversation line can carry over, as plain terms:
#   ['skill', skill line, at least]  ['quest', quest rewarded]  ['rep', faction, at least rank]  ['level', at least]
#   ['knows', spell]  ['lacks', spell]
# Anything else (an item in the bags, a quest taken, OR, a flag) is not carried over: the line is left out and counted.
COND_AND, COND_NOT = -1, -3
COND_REP_MIN, COND_SKILL, COND_QUEST_DONE, COND_LEVEL, COND_SPELL = 5, 7, 8, 15, 17
# Drops and vendors of the items that teach (item_template: class 9 Recipe, or a spell with trigger 6 LEARN_SPELL_ID)
ITEM_RECIPE, TRIGGER_LEARN = 9, 6
GO_CHEST = 3          # gameobject_template.type whose data1 is its loot
WORLD_DROP = 15       # an item more creatures drop is a world drop: left out, as the other sources do


def values(text):
    """The rows of one INSERT's VALUES list: numbers as numbers, strings unescaped, NULL as None."""
    i, n = 0, len(text)
    while i < n:
        if text[i] != '(':
            i += 1
            continue
        i += 1
        row = []
        while True:
            if text[i] == "'":
                j, buf = i + 1, []
                while True:
                    c = text[j]
                    if c == '\\':
                        buf.append(text[j + 1])
                        j += 2
                    elif c == "'":
                        if text[j + 1:j + 2] == "'":
                            buf.append("'")
                            j += 2
                        else:
                            break
                    else:
                        buf.append(c)
                        j += 1
                row.append(''.join(buf))
                i = j + 1
            else:
                j = i
                while text[j] not in ',)':
                    j += 1
                token = text[i:j].strip()
                if token.upper() == 'NULL':
                    row.append(None)
                else:
                    try:
                        row.append(int(token))
                    except ValueError:
                        row.append(float(token))
                i = j
            if text[i] == ',':
                i += 1
                continue
            i += 1   # the closing bracket
            break
        yield row


def read(lines):
    """{table: [row as {column: value}]} for the tables the pack is made from."""
    columns, rows, current = {}, {name: [] for name in WANTED}, None
    for line in lines:
        made = re.match(r'CREATE TABLE `(\w+)`', line)
        if made:
            current = made.group(1) if made.group(1) in WANTED else None
            if current:
                columns[current] = []
            continue
        if current:
            column = re.match(r'\s+`([^`]+)`', line)
            if column:
                columns[current].append(column.group(1))
                continue
            if line.startswith(')'):
                current = None
            continue
        insert = re.match(r'INSERT INTO `(\w+)` VALUES ', line)
        if insert and insert.group(1) in WANTED:
            names = columns.get(insert.group(1), [])
            rows[insert.group(1)].extend(dict(zip(names, row)) for row in values(line[insert.end():]))
    return rows


def whole(value):
    return int(value) if isinstance(value, (int, float)) and value == int(value) and value > 0 else 0


def terms(entry, conditions, negate=False, depth=0):
    """A Classic condition as a list of plain terms, or None when it holds something that is not carried over."""
    if not entry:
        return []
    c = conditions.get(entry)
    if not c or depth > 8 or whole(c.get('flags')) or c.get('flags') not in (0, None):
        return None
    kind, v1, v2 = c.get('type'), c.get('value1'), c.get('value2')
    if kind == COND_AND and not negate:
        left, right = terms(whole(v1), conditions, False, depth + 1), terms(whole(v2), conditions, False, depth + 1)
        return None if left is None or right is None else left + right
    if kind == COND_NOT:
        return terms(whole(v1), conditions, not negate, depth + 1)
    if kind == COND_SPELL and v2 in (0, 1):
        known = (v2 == 0) != negate
        return [['knows' if known else 'lacks', whole(v1)]]
    if negate:
        return None
    if kind == COND_SKILL and whole(v1):
        return [['skill', whole(v1), whole(v2)]]
    if kind == COND_QUEST_DONE and whole(v1):
        return [['quest', whole(v1)]]
    if kind == COND_REP_MIN and whole(v1) and isinstance(v2, int) and 0 <= v2 <= 7:
        return [['rep', whole(v1), v2]]
    if kind == COND_LEVEL and whole(v1) and v2 == 1:   # 1: the level or higher
        return [['level', whole(v1)]]
    return None


def conversations(tables, creatures, casts):
    """[[kind, entry, text, spell, terms]]: the lines of a creature's ('npc') or a quest-giver object's ('go')
    conversation whose script casts a spell, with the conditions of every line on the way to it. Returns
    (lines, how many lines were left out because a condition is not carried over)."""
    conditions = {whole(c.get('condition_entry')): c for c in tables['conditions'] if whole(c.get('condition_entry'))}
    by_menu = {}
    for option in tables['gossip_menu_option']:
        by_menu.setdefault(whole(option.get('menu_id')), []).append(option)
    roots = [('npc', entry, whole(c.get('GossipMenuId'))) for entry, c in creatures.items() if whole(c.get('GossipMenuId'))]
    roots += [('go', whole(g.get('entry')), whole(g.get('data3'))) for g in tables['gameobject_template']
              if g.get('type') == GO_QUESTGIVER and whole(g.get('entry')) and whole(g.get('data3'))]
    lines, dropped = set(), 0
    for kind, entry, root in roots:
        # every menu the conversation reaches, with the conditions of the lines that lead there
        todo, seen = [(root, [])], set()
        while todo:
            menu, path = todo.pop()
            if menu in seen or menu not in by_menu:
                continue
            seen.add(menu)
            for option in by_menu[menu]:
                own = terms(whole(option.get('condition_id')), conditions)
                if own is None:
                    if whole(option.get('action_script_id')) in casts:
                        dropped += 1
                    continue
                spells = casts.get(whole(option.get('action_script_id')), set())
                for spell in sorted(spells):
                    lines.add((kind, entry, str(option.get('option_text') or '').strip(), spell, json.dumps(path + own)))
                following = whole(option.get('action_menu_id'))
                if following and following != menu:
                    todo.append((following, path + own))
    return [[kind, entry, text, spell, json.loads(how)] for kind, entry, text, spell, how in sorted(lines)], dropped


def teaching_items(tables):
    """The items that teach a spell: recipes (class 9) and items whose spell is learned on use (trigger 6)."""
    out = set()
    for item in tables['item_template']:
        entry = whole(item.get('entry'))
        if entry and (item.get('class') == ITEM_RECIPE or any(item.get(f'spelltrigger_{i}') == TRIGGER_LEARN and whole(item.get(f'spellid_{i}')) for i in range(1, 6))):
            out.add(entry)
    return out


def loot_chances(rows, refs, entry, depth=0):
    """{item: chance in %} of one loot table, references followed. Within a group, rows without a chance share what the
    others leave; outside a group a row without a chance drops nothing. Quest-only rows (a negative chance) and rows with
    a condition are left out. rows / refs: {entry: [loot rows]} of the table and of reference_loot_template."""
    out = {}
    if depth > 4:
        return out
    groups = {}
    for row in rows.get(entry, ()):
        if whole(row.get('condition_id')) or (row.get('ChanceOrQuestChance') or 0) < 0:
            continue
        groups.setdefault(whole(row.get('groupid')), []).append(row)
    for group, members in groups.items():
        fixed = sum(float(r.get('ChanceOrQuestChance') or 0) for r in members)
        shared = [r for r in members if not r.get('ChanceOrQuestChance')]
        share = max(0.0, 100.0 - fixed) / len(shared) if group and shared else 0.0
        for row in members:
            chance = float(row.get('ChanceOrQuestChance') or 0) or share
            if chance <= 0:
                continue
            ref = row.get('mincountOrRef') or 0
            found = loot_chances(refs, refs, -ref, depth + 1) if ref < 0 else {whole(row.get('item')): 100.0}
            for item, inner in found.items():
                if item:
                    out[item] = min(100.0, out.get(item, 0.0) + chance * inner / 100.0)
    return out


def drops_and_sells(tables, creatures, items):
    """([[kind, entry, item, chance]], [[npc, item, stock]], [world drops]) for the given items: creatures' corpses
    ('npc') and chests ('go'), by the creature or chest, not by its loot table; vendors with their stock (0: no limit).
    An item more than WORLD_DROP creatures drop is a world drop and left out."""
    by_entry = lambda name: {e: rs for e, rs in _group(tables[name], 'entry').items()}
    creature_loot, object_loot, refs = by_entry('creature_loot_template'), by_entry('gameobject_loot_template'), by_entry('reference_loot_template')
    world = []
    drops, users = {}, {}
    for entry, creature in creatures.items():
        if whole(creature.get('LootId')):
            users.setdefault(whole(creature['LootId']), set()).add(entry)
    for loot, npcs in users.items():
        for item, chance in loot_chances(creature_loot, refs, loot).items():
            if item in items:
                for npc in npcs:
                    drops.setdefault(item, []).append(['npc', npc, item, round(chance, 2)])
    for g in tables['gameobject_template']:
        if g.get('type') == GO_CHEST and whole(g.get('data1')):
            for item, chance in loot_chances(object_loot, refs, whole(g['data1'])).items():
                if item in items:
                    drops.setdefault(item, []).append(['go', whole(g.get('entry')), item, round(chance, 2)])
    out = []
    for item, rows in drops.items():
        if sum(1 for r in rows if r[0] == 'npc') > WORLD_DROP:
            world.append(item)
            continue
        out += [r for r in rows if r[3] >= 0.01]
    templates = _group(tables['npc_vendor_template'], 'entry')
    sells = set()
    for row in tables['npc_vendor']:
        if whole(row.get('item')) in items and not whole(row.get('condition_id')) and whole(row.get('entry')) in creatures:
            sells.add((whole(row['entry']), whole(row['item']), whole(row.get('maxcount'))))
    for entry, creature in creatures.items():
        for row in templates.get(whole(creature.get('VendorTemplateId')), ()) if whole(creature.get('VendorTemplateId')) else ():
            if whole(row.get('item')) in items and not whole(row.get('condition_id')):
                sells.add((entry, whole(row['item']), whole(row.get('maxcount'))))
    return sorted(out), [list(s) for s in sorted(sells)], sorted(world)


def never_given(tables, items):
    """The given items the original game gave out nowhere: in no loot table of any kind, sold by nobody, rewarded or
    handed out by no quest, made by no spell. (Removed mounts, promotional pets, plans and patterns never released.)"""
    given = set()
    for name in GIVING_TABLES:
        given |= {whole(row.get('item')) for row in tables.get(name, ())}
    for quest in tables['quest_template']:
        given |= {whole(quest.get(column)) for column in QUEST_ITEMS}
    for spell in tables.get('spell_template', ()):
        for i in range(1, 4):
            if spell.get(f'Effect{i}') == CREATE_ITEM:
                given.add(whole(spell.get(f'EffectItemType{i}')))
    return sorted(set(items) - given)


def holidays(tables):
    """{event: {'name', 'creatures', 'objects', 'left'}}: what the original game spawns only while a holiday or another
    event runs, by its event, with each spawn's own place.
      creatures [guid, id, map, x, y, z, orientation, respawn seconds, wander distance, movement type]
      objects   [guid, id, map, x, y, z, orientation, rotation 0..3, respawn seconds]
    A negative event (a spawn the event removes) is not carried over and is counted in 'left'.
    A spawn of id 0 takes its id from *_spawn_entry, where cmangos lists the ones it picks from at random at each spawn
    (Noblegarden's eggs: four colours). TrinityCore has no such pick: each spawn keeps one of them for good, its guid
    choosing which, so the place keeps the original mix of colours. One with no list keeps 0 (the website leaves it out)."""
    picks = {'creature': {}, 'gameobject': {}}
    for kind in picks:
        for row in tables.get(kind + '_spawn_entry') or []:
            if whole(row.get('guid')) and whole(row.get('entry')):
                picks[kind].setdefault(whole(row['guid']), set()).add(whole(row['entry']))

    def entry(kind, row):
        found = whole(row.get('id'))
        choices = sorted(picks[kind].get(whole(row.get('guid')), ()))
        return found or (choices[whole(row['guid']) % len(choices)] if choices else 0)
    names = {whole(e.get('entry')): str(e.get('description') or '') for e in tables['game_event']}
    linked = {'creature': {}, 'gameobject': {}}
    left = {}
    for kind, table in (('creature', 'game_event_creature'), ('gameobject', 'game_event_gameobject')):
        for row in tables[table]:
            event = row.get('event') or 0
            if event < 0:
                left[-event] = left.get(-event, 0) + 1
            elif event > 0 and whole(row.get('guid')):
                linked[kind].setdefault(whole(row['guid']), set()).add(event)   # a spawn may belong to several events
    out = {}
    for r in tables['creature']:
        for event in sorted(linked['creature'].get(whole(r.get('guid')), ())):
            out.setdefault(event, {'name': names.get(event, ''), 'creatures': [], 'objects': []})['creatures'].append(
                [whole(r['guid']), entry('creature', r), int(r.get('map') or 0)] + [round(float(r.get(c) or 0), 4) for c in ('position_x', 'position_y', 'position_z', 'orientation')]
                + [whole(r.get('spawntimesecsmin')), round(float(r.get('spawndist') or 0), 2), int(r.get('MovementType') or 0)])
    for r in tables['gameobject']:
        for event in sorted(linked['gameobject'].get(whole(r.get('guid')), ())):
            out.setdefault(event, {'name': names.get(event, ''), 'creatures': [], 'objects': []})['objects'].append(
                [whole(r['guid']), entry('gameobject', r), int(r.get('map') or 0)]
                + [round(float(r.get(c) or 0), 6) for c in ('position_x', 'position_y', 'position_z', 'orientation', 'rotation0', 'rotation1', 'rotation2', 'rotation3')]
                + [int(r.get('spawntimesecsmin') or 0)])
    for event, n in left.items():
        out.setdefault(event, {'name': names.get(event, ''), 'creatures': [], 'objects': []})['left'] = n
    return {str(e): v for e, v in sorted(out.items())}


def _group(rows, key):
    out = {}
    for row in rows:
        out.setdefault(whole(row.get(key)), []).append(row)
    return out


def pack(tables, today=None):
    creatures = {whole(c.get('Entry')): c for c in tables['creature_template'] if whole(c.get('Entry'))}
    users = {}   # trainer template -> creatures
    for entry, creature in creatures.items():
        if whole(creature.get('TrainerTemplateId')):
            users.setdefault(whole(creature['TrainerTemplateId']), set()).add(entry)
    trainers = set()

    def taught(npc, row):
        if npc in creatures and whole(row.get('spell')):
            trainers.add((npc, whole(row['spell']), whole(row.get('spellcost')), whole(row.get('reqskill')), whole(row.get('reqskillvalue')), whole(row.get('reqlevel'))))
    for row in tables['npc_trainer']:
        taught(whole(row.get('entry')), row)
    for row in tables['npc_trainer_template']:
        for npc in users.get(whole(row.get('entry')), ()):
            taught(npc, row)

    quests = sorted((whole(q.get('entry')), whole(q.get('RewSpell')), whole(q.get('RewSpellCast'))) for q in tables['quest_template']
                    if whole(q.get('entry')) and (whole(q.get('RewSpell')) or whole(q.get('RewSpellCast'))))

    # a conversation: the creature's menu and every menu its options lead to; an option's script may cast a spell
    casts = {}
    for row in tables['dbscripts_on_gossip']:
        if row.get('command') == CAST_SPELL and whole(row.get('datalong')):
            casts.setdefault(whole(row.get('id')), set()).add(whole(row['datalong']))
    leads, scripts = {}, {}
    for option in tables['gossip_menu_option']:
        menu = whole(option.get('menu_id'))
        if whole(option.get('action_menu_id')):
            leads.setdefault(menu, set()).add(whole(option['action_menu_id']))
        if whole(option.get('action_script_id')) in casts:
            scripts.setdefault(menu, set()).update(casts[whole(option['action_script_id'])])
    gossip = set()
    for entry, creature in creatures.items():
        seen, todo = set(), [whole(creature.get('GossipMenuId'))]
        while todo:
            menu = todo.pop()
            if not menu or menu in seen:
                continue
            seen.add(menu)
            gossip.update((entry, spell) for spell in scripts.get(menu, ()))
            todo.extend(leads.get(menu, ()))

    talk, dropped = conversations(tables, creatures, casts)
    teaching = teaching_items(tables)
    drops, sells, world = drops_and_sells(tables, creatures, teaching)
    unsourced = never_given(tables, {whole(i.get('entry')) for i in tables['item_template']} - {0})
    events = holidays(tables)

    npcs = {npc for npc, *_ in trainers} | {npc for npc, _ in gossip} | {entry for kind, entry, *_ in talk if kind == 'npc'}
    npcs |= {entry for kind, entry, *_ in drops if kind == 'npc'} | {npc for npc, *_ in sells}
    asked = {quest for quest, *_ in quests}
    version = ''
    for row in tables['db_version']:
        version = str(row.get('version') or '')[:120]
    named_objects = {e for k, e, *_ in talk if k == 'go'} | {e for k, e, *_ in drops if k == 'go'}
    objects = {str(whole(g.get('entry'))): str(g.get('name') or '') for g in tables['gameobject_template'] if whole(g.get('entry')) in named_objects}
    return {'format': 4, 'holidays': events, 'talk': talk, 'talk_dropped': dropped, 'object_names': objects, 'drops': drops, 'sells': sells, 'world_drops': world, 'never_given': unsourced, 'source': 'cmangos classic-db', 'licence': 'GPL-3.0', 'version': version, 'made': today or datetime.date.today().isoformat(),
            'trainers': sorted(trainers), 'quests': quests, 'gossip': sorted(gossip),
            'npc_names': {str(npc): str(creatures[npc].get('Name') or '') for npc in sorted(npcs)},
            'quest_names': {str(whole(q.get('entry'))): str(q.get('Title') or '') for q in tables['quest_template'] if whole(q.get('entry')) in asked}}


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    opener = gzip.open if argv[1].endswith('.gz') else open
    with opener(argv[1], 'rt', encoding='utf-8', errors='replace') as handle:
        made = pack(read(handle))
    if not made['trainers'] and not made['quests']:
        sys.exit('no trainer and no quest found: is this the full dump of cmangos classic-db?')
    with gzip.open(argv[2], 'wt', encoding='utf-8') as out:
        json.dump(made, out, ensure_ascii=False, separators=(',', ':'))
    print(f"{argv[2]}: {len(made['drops'])} drops and {len(made['sells'])} vendor lines of items that teach "
          f"{sum(len(e['creatures']) + len(e['objects']) for e in made['holidays'].values())} spawns of {len(made['holidays'])} events, "
          f"({len(made['world_drops'])} world drops left out; {len(made['never_given'])} given out nowhere), "
          f"{len(made['trainers'])} trainer lines, {len(made['quests'])} quests with a spell, {len(made['talk'])} conversation lines that cast a spell"
          f" ({made['talk_dropped']} left out: a condition not carried over) ({made['version']})")


if __name__ == '__main__':
    main(sys.argv)
