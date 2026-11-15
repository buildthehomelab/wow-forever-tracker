"""Makes a pack of what the original game's database says about who teaches a spell.

    python tools/classicdb_pack.py ClassicDB_1_12_1_z2815.sql.gz out.cdbpack

The source is the full dump of cmangos' classic-db (github.com/cmangos/classic-db, Full_DB/, GPL-3.0): the content
database of the 1.12 game. Only the dump is read, as text; nothing is run and no database is needed. The pack is a
few hundred kB of gzipped JSON holding three things:

    trainers   [npc, spell, cost, skill line, skill rank, level]   npc_trainer, and npc_trainer_template through the
                                                                   creatures that use each template
    quests     [quest, RewSpell, RewSpellCast]                     quests that show or cast a spell at the turn-in
    gossip     [npc, spell]                                        spells a line of a creature's conversation casts
                                                                   (how Classic teaches a recipe without a trainer
                                                                   window: Knot Thimblejack, the transporter gnomes)

and the names of the creatures, objects and quests it mentions.

    talk       [kind, entry, text, spell, terms]                  a line of a creature's ('npc') or a quest-giver
                                                                   object's ('go') conversation that casts a spell, with
                                                                   the conditions of every line on the way to it (terms()) The website's Imports page takes the pack (docs/SOURCES.md).
"""
import datetime
import gzip
import json
import re
import sys

WANTED = {'quest_template', 'npc_trainer', 'npc_trainer_template', 'creature_template', 'gameobject_template', 'gossip_menu_option',
          'dbscripts_on_gossip', 'conditions', 'db_version'}
CAST_SPELL = 15   # dbscripts command: datalong is the spell
GO_QUESTGIVER = 2   # gameobject_template.type whose data3 is its conversation menu
# Classic's conditions (cmangos `conditions`) that a conversation line can carry over, as plain terms:
#   ['skill', skill line, at least]  ['quest', quest rewarded]  ['rep', faction, at least rank]  ['level', at least]
#   ['knows', spell]  ['lacks', spell]
# Anything else (an item in the bags, a quest taken, OR, a flag) is not carried over: the line is left out and counted.
COND_AND, COND_NOT = -1, -3
COND_REP_MIN, COND_SKILL, COND_QUEST_DONE, COND_LEVEL, COND_SPELL = 5, 7, 8, 15, 17


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

    npcs = {npc for npc, *_ in trainers} | {npc for npc, _ in gossip} | {entry for kind, entry, *_ in talk if kind == 'npc'}
    asked = {quest for quest, *_ in quests}
    version = ''
    for row in tables['db_version']:
        version = str(row.get('version') or '')[:120]
    objects = {str(whole(g.get('entry'))): str(g.get('name') or '') for g in tables['gameobject_template'] if any(k == 'go' and e == whole(g.get('entry')) for k, e, *_ in talk)}
    return {'format': 2, 'talk': talk, 'talk_dropped': dropped, 'object_names': objects, 'source': 'cmangos classic-db', 'licence': 'GPL-3.0', 'version': version, 'made': today or datetime.date.today().isoformat(),
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
    print(f"{argv[2]}: {len(made['trainers'])} trainer lines, {len(made['quests'])} quests with a spell, {len(made['talk'])} conversation lines that cast a spell"
          f" ({made['talk_dropped']} left out: a condition not carried over) ({made['version']})")


if __name__ == '__main__':
    main(sys.argv)
