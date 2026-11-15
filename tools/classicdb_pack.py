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

and the names of the creatures and quests it mentions. The website's Imports page takes the pack (docs/SOURCES.md).
"""
import datetime
import gzip
import json
import re
import sys

WANTED = {'quest_template', 'npc_trainer', 'npc_trainer_template', 'creature_template', 'gossip_menu_option', 'dbscripts_on_gossip', 'db_version'}
CAST_SPELL = 15   # dbscripts command: datalong is the spell


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

    npcs = {npc for npc, *_ in trainers} | {npc for npc, _ in gossip}
    asked = {quest for quest, *_ in quests}
    version = ''
    for row in tables['db_version']:
        version = str(row.get('version') or '')[:120]
    return {'format': 1, 'source': 'cmangos classic-db', 'licence': 'GPL-3.0', 'version': version, 'made': today or datetime.date.today().isoformat(),
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
    print(f"{argv[2]}: {len(made['trainers'])} trainer lines, {len(made['quests'])} quests with a spell, {len(made['gossip'])} conversation lines that cast a spell ({made['version']})")


if __name__ == '__main__':
    main(sys.argv)
