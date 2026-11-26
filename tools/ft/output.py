"""Writes the analysis into the tracker database (ft_* tables), swapped atomically."""
import datetime
import json
import re

from . import sqlio
from .baseline import NEW_FROM, Baseline
from .content import PLAYER_SPELLS

# Names of things players never see. Words that real names share are pinned to the shape a test name has: "Monster -
# Sword2H" is a weapon model, "Monster Omelet" is dinner; "Test Dungeon" and "QA Test" are tests, "Test of Faith" and
# "The Test of Righteousness" are quests; "Copy of X" is a leftover, "Signed copy of..." is a book; "Sword - Unused" is
# unused, the "Unused Scraping Vial" is a quest item; "REUSE ME" and "(Temp Disabled)" are slots Blizzard keeps for later.
INTERNAL_NAME = re.compile(
    r'^\s*\[|^\s*<|^\s*$|^zz'
    r'|\bTEST\b|\btest\b|^Test (?!of\b)|\(Test\)|\bTest (?:Item|Dungeon|Quest|Spell|NPC|Mount|Pet|Zone|Vendor|Realm|Character|Creature|Object)s?\b|Test\d|Test[A-Z]'
    r'|^Monster - |^Monstre - '
    r'|\b(OLD|Deprecated|DEPRECATED|DEP|PH|DNT|QA|UNUSED|NYI|PÉRIMÉ|NPC Equip|Template|Placeholder)\b|\(DNT\)|\(OLD\)|\(Unused\)|- Unused\b|\bUnused$'
    r'|^Copy of\b|\(copy\)|- copy\b|\bcopy$|\bNOT USED\b|\bNot Used\b|\bNo Longer in Use\b'
    r'|^REUSE ?(?:ME)?$|\(Temp(?:orarily)? Disabled\)|\bDND\b')
# Flight paths a quest flies you along (TaxiNodes rows named "Quest Path 11512: ..."), not flight points.
QUEST_PATH = re.compile(r'^Quest Path \d+')
DATA_KEYS = ('ranks', 'spell', 'item', 'map', 'pos', 'creature', 'kind', 'teach', 'creates')
TABLES = ('ft_builds', 'ft_entities', 'ft_changes', 'ft_meta', 'ft_tooltips', 'ft_fixes')


# Quests of the original game nothing ever gave: VMaNGOS (db-70e38cd, checked 2026-11-19) has their row but no giver,
# no start item and no object that starts them, and the realm has none either. A Strategic Alliance, Oops We Killed
# Them Again, the Alterac Valley "Speak with..." pair, Stonesplinter Trogg Disguise, the "Chow" test quest, To The
# Victor..., Vanquish the Invaders, Vimes's Report (1289, the copy 1288 replaced), Waskily Wabbits!, River Ends.
NEVER_GIVEN_QUESTS = {785, 1390, 7221, 7222, 912, 9065, 9556, 8290, 1289, 7961, 7790}


def summary(rows, closed):
    """{kind: ({status: count}, internal, later)} from ft_entities rows (type, status, internal, phase, n), counted as the
    website lists them: internal / test rows apart, and rows waiting for a phase not open yet (closed: the phase numbers)
    apart unless the server already provides them."""
    out = {}
    closed = {int(p) for p in closed}
    for row in rows:
        counts, internal, later = out.get(row['type'], ({}, 0, 0))
        n, status = int(row['n']), row['status']
        if int(row.get('internal') or 0):
            internal += n
        elif int(row.get('phase') or 0) in closed and status != 'ok':
            later += n
        else:
            counts[status] = counts.get(status, 0) + n
        out[row['type']] = (counts, internal, later)
    return out


# Items of the client's own systems, no content players get, checked by hand (2026-11-19): the transmog window's
# "Hidden" pieces and its UI models, the WoW Token and the Customer Service Package. Wowhead Forever's list pages name
# no source for any of them.
SYSTEM_ITEMS = {122270, 122284, 134110, 134111, 134112, 135510, 135522, 135548, 135549, 135550, 142503, 142504, 143539,
                158329, 168659, 168664, 168665, 172070}


def named_internal(name):
    """A placeholder or test name ([PH] Brown Prideclaw, NOT USED); an empty name says nothing either way."""
    return bool(name and INTERNAL_NAME.search(name))


# Craftsman's Writs: tradable items that start a crafting quest and drop in the world. Wowhead knows no creature that
# drops them yet, so the tracker keeps reading their pages (app/wowheadpages.php wowhead_pages_writs).
WRIT_NAME = re.compile(r"^Craftsman's Writ\b", re.I)


def writ_items(items):
    """{item id: quest id} of the Craftsman's Writs among the client's items (content['item']): an item that starts a
    quest (ItemSparse.StartQuestID) and whose English name is a Craftsman's Writ."""
    out = {}
    for item_id, item in items.items():
        quest = (item.get('facts') or {}).get('startquest') or 0
        if quest and WRIT_NAME.match(item.get('name_en') or item.get('name') or ''):
            out[int(item_id)] = int(quest)
    return dict(sorted(out.items()))


WRIT_TIERS = {'journeyman': 1, 'expert': 2, 'artisan': 3}


def writ_tiers(items):
    """{item id: 1 Journeyman, 2 Expert, 3 Artisan} of the writs whose tier the client writes under their name
    (ItemSparse.ItemNameDescriptionID; content keeps it as namedesc_en)."""
    return {i: WRIT_TIERS[items[i].get('namedesc_en', '').strip().lower()] for i in writ_items(items)
            if items[i].get('namedesc_en', '').strip().lower() in WRIT_TIERS}


def item_internal(item_id, items, wowhead):
    """True for a test item or a Season of Discovery leftover (as the item's own line is filed), False for an item of
    the game, None when the client has no such item."""
    item = items.get(item_id)
    if item is None:
        return None
    name = item.get('name_en') or item.get('name') or ''
    return bool(not name or INTERNAL_NAME.search(name) or (wowhead or {}).get(('item', item_id)) == 'season')


def filed_internal(item_id, content, results, ctx, wowhead):
    """True when an item's own line is filed under Internal / test: a test name or none, an item the original game gave
    out nowhere and nothing here gives, or one Wowhead marks as a Season of Discovery leftover. False for an item the
    official list does not have: a pattern gone from the client says nothing about its recipe (ft.output.leftover)."""
    item = content.get('item', {}).get(item_id)
    if item is None:
        return False
    name = item.get('name') or ''
    if INTERNAL_NAME.search(item.get('name_en') or name) or not name or item_id in SYSTEM_ITEMS:
        return True
    status = (results.get(('item', item_id)) or ('',))[0]
    if status != 'ok' and item_id < NEW_FROM['item'] and item_id in ((ctx or {}).get('classic_never_given') or ()):
        return True  # the original game gave it out nowhere (removed or never released) and nothing here does
    return (wowhead or {}).get(('item', item_id)) == 'season'


def leftover(kind, entity_id, entity, status, items, wowhead, baseline, trained=()):
    """A spell or recipe that only items teach, none of them part of the game: each is a test item or a Season of
    Discovery leftover. An item the client does not have at all counts the same way for a spell the Classic Era client
    gained after the original game (a Season of Discovery addition), and only for those: an original recipe whose
    unused pattern is gone is still taught some other way (the Naxxramas frost resistance sets, quest recipes), and a
    spell new in Forever whose item is not there yet is content still locked. Both stay on the list."""
    teach = entity.get('teach') or []
    if status == 'ok' or not teach or entity_id in trained:
        return False
    season = entity_id >= NEW_FROM.get(kind, 10 ** 9) and not baseline.is_new(kind, entity_id, entity)
    for item in teach:
        state = item_internal(int(item), items, wowhead)
        if state is False or (state is None and not season):
            return False
    return True


def unused_taxi(node_id, entity, baseline, dungeons):
    """A flight point no player flies from: a node inside a battleground (Alterac Valley's), or one the original game
    already had that neither faction can use (boats, zeppelins, script targets, Programmer Isle). Forever's own
    nodes carry no faction bit either, so only the Classic Era ones are judged by it."""
    if entity.get('map') in dungeons:
        return True
    flags = int((entity.get('facts') or {}).get('flags') or 0)
    return not flags & 3 and baseline.has('TaxiNodes', node_id) is True

SCHEMA_SQL = """
CREATE TABLE ft_builds_new (build INT NOT NULL, version VARCHAR(32), released DATE NULL, note TEXT, source VARCHAR(255), is_server TINYINT NOT NULL DEFAULT 0, counts JSON,
  hotfix SMALLINT NOT NULL DEFAULT 0, PRIMARY KEY (build, hotfix)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_entities_new (type VARCHAR(16) NOT NULL, id INT NOT NULL, name VARCHAR(255) NOT NULL, name_en VARCHAR(255) NOT NULL DEFAULT '',
  sub VARCHAR(120) NOT NULL DEFAULT '', level INT NOT NULL DEFAULT 0, quality TINYINT NOT NULL DEFAULT -1, icon VARCHAR(96) NOT NULL DEFAULT '',
  internal TINYINT NOT NULL DEFAULT 0, is_new TINYINT NOT NULL DEFAULT 0, status ENUM('ok','partial','missing') NOT NULL, score TINYINT NOT NULL, checks JSON, data JSON,
  first_build INT NOT NULL, changed_build INT NOT NULL, phase TINYINT NOT NULL DEFAULT 0, PRIMARY KEY (type, id), KEY ix_status (type, status, internal, phase), KEY ix_name (name), KEY ix_name_en (name_en), KEY ix_changed (changed_build)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_changes_new (seq INT AUTO_INCREMENT PRIMARY KEY, build INT NOT NULL, prev_build INT NOT NULL, type VARCHAR(16) NOT NULL, id INT NOT NULL,
  kind ENUM('added','removed','modified') NOT NULL, name VARCHAR(255) NOT NULL DEFAULT '', fields JSON, internal TINYINT NOT NULL DEFAULT 0,
  hotfix SMALLINT NOT NULL DEFAULT 0, KEY ix_build (build, hotfix, type, kind), KEY ix_entity (type, id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_meta_new (k VARCHAR(64) PRIMARY KEY, v JSON) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_tooltips_new (type VARCHAR(16) NOT NULL, id INT NOT NULL, tip JSON NOT NULL, PRIMARY KEY (type, id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_fixes_new (type VARCHAR(16) NOT NULL, id INT NOT NULL, kind VARCHAR(16) NOT NULL, db VARCHAR(16) NOT NULL, rows_count INT NOT NULL DEFAULT 0,
  needs VARCHAR(16) NOT NULL DEFAULT '', summary JSON, detail JSON, sql_apply MEDIUMTEXT NOT NULL, sql_rollback MEDIUMTEXT NOT NULL,
  PRIMARY KEY (type, id, kind), KEY ix_kind (kind)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ft_notes (build INT PRIMARY KEY, title VARCHAR(255) NOT NULL DEFAULT '', url VARCHAR(500) NOT NULL DEFAULT '', body MEDIUMTEXT, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


class Batch:
    def __init__(self, out, table, size=400):
        self.out, self.table, self.size, self.rows = out, table, size, []

    def add(self, row):
        self.rows.append(row)
        if len(self.rows) >= self.size:
            self.flush()

    def flush(self):
        if self.rows:
            self.out.write(f'INSERT INTO {self.table} VALUES ' + ',\n'.join(self.rows) + ';\n')
            self.rows = []


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)


def covered_elsewhere(content):
    """{(kind, id): 'type:id'} for the lines another line of the work list already covers: the spell of a recipe,
    mount or pet, and the item that teaches a recipe, mount or pet or is a toy. Fixing that other line fixes them."""
    covered = {}
    for kind in ('recipe', 'mount', 'pet', 'toy'):
        for entity_id, entity in content.get(kind, {}).items():
            owner = f'{kind}:{entity_id}'
            spell = entity_id if kind == 'recipe' else entity.get('spell')
            if spell:
                covered.setdefault(('spell', int(spell)), owner)
            for item in entity.get('teach') or []:
                covered.setdefault(('item', int(item)), owner)
            if entity.get('item'):
                covered.setdefault(('item', int(entity['item'])), owner)
    return covered


def write_sql(path, build_list, content, changes, results, first_seen, changed_in, icons, quest_names, ctx, server_build, tooltips, fixes, wowhead=None,
              phase_list=(), phase_of=None):
    """phase_list / phase_of: the release phases (ft.phases.run): a resource a later phase opens keeps its status and gets
    the phase's number; the website shows it as Later until that phase opens."""
    phase_of = phase_of or {}
    e = sqlio.escape
    with open(path, 'w', encoding='utf-8') as out:
        out.write('SET NAMES utf8mb4;\n')
        out.write('DROP TABLE IF EXISTS ' + ', '.join(t + '_new' for t in TABLES) + ';\n' + SCHEMA_SQL)
        for b in build_list:
            out.write(f"INSERT INTO ft_builds_new VALUES ({b['build']},{e(b['version'])},{e(b['date'])},{e(b['note'])},{e(b['source'])},{1 if b['build'] == server_build else 0},{e(dumps(b.get('counts', {})))},0);\n")
        # Blizzard's hotfixes after their build, one entry for each day a new cache changed something (ft.content.changelog)
        for h in (((ctx.get('changelog') or {}).get('hotfixes') or []) if ctx else []):
            note = f"{h.get('records', 0)} hotfix records"
            out.write(f"INSERT INTO ft_builds_new VALUES ({h['build']},{e(h['version'])},{e(h['date'])},{e(note)},'hotfix',0,{e(dumps(h.get('counts', {})))},{int(h['hotfix'])});\n")
        baseline = Baseline()
        covered = covered_elsewhere(content)
        granted = ctx.get('granted_spells', ())
        trained = {spell for _trainer, spell in ctx.get('trainer_spells', ())}
        batch = Batch(out, 'ft_entities_new')
        # The titles of the quests players can do: a copy nobody gives under the same title is an older number the
        # game moved on from (the Strange Water Globe starts Baron Aquanis 6922, not 909; the Arena Master trinket 7810)
        done_titles = {}
        for (kind, entity_id), (status, _score, _checks) in results.items():
            title = ((ctx or {}).get('quests', {}).get(entity_id) or {}).get('LogTitle') if kind == 'quest' and status == 'ok' else None
            if title:
                done_titles.setdefault(title, set()).add(entity_id)
        for (kind, entity_id), (status, score, checks) in results.items():
            entity = content[kind][entity_id]
            name = entity.get('name') or ''
            name_en = entity.get('name_en') or ''
            data = {}
            if kind == 'quest':
                row = ctx['quests'].get(entity_id)
                wh = quest_names.get(str(entity_id), {})
                name = ctx['quest_fr'].get(entity_id) or (row or {}).get('LogTitle') or wh.get('fr') or wh.get('en') or ''
                name_en = (row or {}).get('LogTitle') or wh.get('en') or ''
                level, minimum = ctx['quest_level'].get(entity_id, (0, 0))
                entity['level'] = level
                entity['sub'] = str(int((row or {}).get('QuestSortID') or 0))
                if wh.get('text_fr') or wh.get('text_en'):
                    data['text'] = wh.get('text_fr') or wh.get('text_en')
                data['min'] = minimum
            internal = 0
            if kind == 'quest':
                # Unnamed quests stay visible (they are what the server lacks) unless Wowhead does not know them either.
                looked_up = str(entity_id) in quest_names
                unknown_everywhere = not name and looked_up and not (quest_names[str(entity_id)].get('fr') or quest_names[str(entity_id)].get('en'))
                # An unnamed quest the Classic Era client already had (Season of Discovery, hidden tracking flags): Wowhead
                # is only asked about Forever's own quests, so no answer would ever hide it. No title is no quest players take.
                classic_unnamed = not name and not baseline.is_new(kind, entity_id, entity)
                internal = 1 if unknown_everywhere or classic_unnamed or (name and INTERNAL_NAME.search(name)) else 0
                # Wowhead's Forever item pages show players being rewarded by it: a real quest, whatever its name or
                # its lack of one says (84394 unnamed in the client; "Test Your Theory" 93045 is no test)
                if entity_id in ((ctx or {}).get('wowhead_reward_quests') or ()):
                    internal = 0
                # The server's own disables table switches it off and nothing gives it: a quest the core keeps out on
                # purpose (Rokar Bladeshadow, Da Foo, Kill 'Em With Sleep Deprivation), not content waiting for a fix.
                failed = {c['code'] for c in checks if not c['ok']}
                if {'enabled', 'starter'} <= failed:
                    internal = 1
                if 'starter' in failed and done_titles.get(name_en, set()) - {entity_id}:
                    internal = 1
                if 'starter' in failed and entity_id in NEVER_GIVEN_QUESTS:
                    internal = 1
                # started only by an item the client itself marks unused ("<UNUSED> Glyphic Rune")
                start_item = content.get('item', {}).get((ctx or {}).get('start_quest_item', {}).get(entity_id)) or {}
                if 'starter' in failed and named_internal(start_item.get('name_en') or start_item.get('name')):
                    internal = 1
                if not name:
                    data['unnamed'] = True
                name = name or f'#{entity_id}'
            elif kind == 'spell':
                internal = 0 if entity['sub'] in PLAYER_SPELLS else 1
                if entity_id in granted or leftover(kind, entity_id, entity, status, content.get('item', {}), wowhead, baseline, trained):
                    internal = 1  # what another ability does, or a spell only an item outside the game teaches: nothing to add
            elif kind == 'item':
                internal = 1 if filed_internal(entity_id, content, results, ctx, wowhead) else 0
                teachers = ((ctx or {}).get('teachers_only') or {}).get(entity_id)
                if status != 'ok' and not internal and teachers and all(filed_internal(t, content, results, ctx, wowhead) for t in teachers):
                    internal = 1  # made only by a spell that only test or Season of Discovery items teach or cast (ft.rules)
                if status != 'ok' and entity_id < NEW_FROM['item'] and entity_id in ((ctx or {}).get('closed_loops') or ()):
                    internal = 1  # an original item only other items of a closed group make, nothing giving any of them (ft.rules);
                    # Forever's own items stay listed: content still waiting for its source
            elif kind in ('achievement', 'taxi', 'zone', 'dungeon', 'boss'):
                internal = 1 if INTERNAL_NAME.search(name_en or name) or not name or entity.get('weak') else 0
                if kind == 'taxi' and (QUEST_PATH.search(name_en or name) or unused_taxi(entity_id, entity, baseline, content['dungeon'])):
                    internal = 1
                if kind == 'boss':
                    home = content['dungeon'].get(int(entity.get('map') or 0)) or {}
                    if named_internal(home.get('name_en') or home.get('name')):
                        internal = 1  # a boss of a test instance
                    if entity.get('shadow'):
                        # no boss of its own (ft.bosses.shadows): Season of Discovery's raid version, or the same fight again
                        internal = 1
                        data['encounter'] = entity['shadow']['reason']
                        if entity['shadow']['kept']:
                            data['same'] = entity['shadow']['kept']
                if kind in ('dungeon', 'boss') and baseline.season_map(entity_id if kind == 'dungeon' else int(entity.get('map') or 0)):
                    internal = 1  # a Season of Discovery instance (or one never opened) and its bosses: listed under Internal / test
                    data['season'] = True
            elif kind in ('mount', 'pet', 'toy', 'recipe'):
                internal = 1 if named_internal(name_en or name) else 0  # unnamed ones stay: content players have yet to discover
                spell = int(entity.get('spell') or 0) if kind in ('mount', 'pet') else 0
                if spell and status != 'ok' and (spell in granted or (spell in content.get('spell', {}) and leftover(
                        'spell', spell, content['spell'][spell], 'missing', content.get('item', {}), wowhead, baseline, trained))):
                    internal = 1  # its spell's line says nobody learns it here or in the original game (removed, promo, Season)
                if kind == 'recipe' and leftover(kind, entity_id, entity, status, content.get('item', {}), wowhead, baseline, trained):
                    internal = 1
                if kind == 'recipe' and status != 'ok' and (entity_id in granted or (entity_id in content.get('spell', {}) and leftover(
                        'spell', entity_id, content['spell'][entity_id], 'missing', content.get('item', {}), wowhead, baseline, trained)
                        or (wowhead or {}).get(('spell', entity_id)) == 'season')):
                    internal = 1  # its spell (the same id) is internal on the spell's line, for the same reasons: a Season of
                    #               Discovery addition, one the original game taught nowhere, or only items outside the game teach it
                if kind == 'recipe' and status != 'ok' and name in ('', f'#{entity_id}') and entity_id < NEW_FROM['recipe'] and entity_id not in content.get('spell', {}):
                    internal = 1  # a profession line of the original game whose spell Forever's client no longer has (the old
                    #               healing potions): Forever removed it
            verdict = (wowhead or {}).get((kind, entity_id))
            if verdict == 'season':
                internal = 1  # Wowhead marks it as a Season of Discovery leftover
            if verdict in ('unknown', 'season'):
                # 'unknown' stays visible: Forever keeps content encrypted for players to discover, Wowhead learns it later
                data['wowhead'] = verdict
            for key in DATA_KEYS:
                if entity.get(key):
                    data[key] = entity[key]
            if (kind, entity_id) in covered:
                data['dup'] = covered[(kind, entity_id)]  # the work list shows it once, on that other line
            icon = icons.get(entity.get('icon') or 0, '')
            batch.add(f"({e(kind)},{entity_id},{e(name[:250])},{e(name_en[:250])},{e(str(entity.get('sub', ''))[:120])},{int(entity.get('level') or 0)},"
                      f"{int(entity.get('quality', -1)) if kind == 'item' else -1},{e(icon)},{internal},{1 if baseline.is_new(kind, entity_id, entity) else 0},{e(status)},{score},"
                      f"{e(dumps(checks))},{e(dumps(data))},{first_seen.get((kind, entity_id), 0)},{changed_in.get((kind, entity_id), 0)},{phase_of.get((kind, entity_id), 0)})")
        batch.flush()
        batch = Batch(out, 'ft_changes_new')
        # a removed resource has no line of its own any more to say it was a test or an unused one: the change says it
        minor = ((ctx.get('changelog') or {}).get('minor') or set()) if ctx else set()
        for build, previous, kind, entity_id, change, fields, name in changes:
            internal = 1 if change == 'removed' and ((build, kind, entity_id) in minor or (kind != 'quest' and bool(name) and INTERNAL_NAME.search(name))) else 0
            batch.add(f"(NULL,{build},{previous},{e(kind)},{entity_id},{e(change)},{e((name or '')[:250])},{e(dumps(fields))},{internal},0)")
        # a hotfix entry is compared with its own build as it stood before (prev_build = the same build)
        for build, number, kind, entity_id, change, fields, name in (((ctx.get('changelog') or {}).get('hotfix_changes') or []) if ctx else []):
            internal = 1 if change == 'removed' and kind != 'quest' and bool(name) and INTERNAL_NAME.search(name) else 0
            batch.add(f"(NULL,{build},{build},{e(kind)},{entity_id},{e(change)},{e((name or '')[:250])},{e(dumps(fields))},{internal},{int(number)})")
        batch.flush()
        batch = Batch(out, 'ft_tooltips_new', 300)
        for (kind, entity_id), tip in tooltips.items():
            if (kind, entity_id) in results:
                batch.add(f'({e(kind)},{entity_id},{e(dumps(tip))})')
        batch.flush()
        batch = Batch(out, 'ft_fixes_new', 50)
        for kind, entity_id, fix_kind, db, rows, needs, summary, detail, apply, rollback in fixes:
            batch.add(f'({e(kind)},{entity_id},{e(fix_kind)},{e(db)},{rows},{e(needs)},{e(dumps(summary))},{e(dumps(detail))},{e(apply)},{e(rollback)})')
        batch.flush()
        meta = {'generated_at': datetime.datetime.now().isoformat(timespec='seconds'), 'server_build': server_build,
                'client_build': build_list[-1]['build'] if build_list else 0, 'hidden': content.get('_meta', {}).get('hidden', {}),
                'schema': 5,   # 4: ft_changes.internal; 5: ft_builds.hotfix + ft_changes.hotfix (hotfix entries)
                # release phases in order (number = position + 1): ft_entities.phase holds the number, 0 = released
                'phases': list(phase_list),
                # quests an item starts (ItemSparse.StartQuestID): they need no giver, the imports leave them alone
                'item_quests': sorted(ctx.get('start_quest_item', {})) if ctx else [],
                # quests only givers live replaced give or take (ft.rules): not given on WoW: Forever, no giver proposed
                'not_given_quests': sorted(ctx.get('not_given_quests', ())) if ctx else [],
                # the Craftsman's Writs: {item: the quest it starts} (writ_items), whose Wowhead pages the crawl follows
                'writ_items': {str(i): q for i, q in writ_items(content.get('item', {})).items()},
                # and their tier as the client writes it under the name (1 Journeyman, 2 Expert, 3 Artisan)
                'writ_tiers': {str(i): n for i, n in writ_tiers(content.get('item', {})).items()},
                # the days each hotfix entry covers (ft.dating): {'build:hotfix': {'from', 'until', 'days', 'rows', 'next'}}
                'hotfix_windows': {f"{h['build']}:{h['hotfix']}": h['window'] for h in (((ctx.get('changelog') or {}).get('hotfixes') or []) if ctx else []) if h.get('window')},
                # resources that exist by hotfix alone and that the changelog therefore does not call "added": {kind: count}
                'hotfix_only': (ctx.get('hotfix_only') or {}) if ctx else {},
                # the original game as the changelog's start (ft.vanilla): {'build', 'version', 'first', 'hidden', 'alone'}
                'baseline': ((ctx.get('changelog') or {}).get('baseline') if ctx else None) or {},
                # the double check: the first thing stored and every build's changes give the newest build (ft.content.replay)
                'replay': ((ctx.get('changelog') or {}).get('replay') if ctx else None) or {}}
        for key, value in meta.items():
            out.write(f"INSERT INTO ft_meta_new VALUES ({e(key)},{e(dumps(value))});\n")
        # atomic swap
        for t in TABLES:
            out.write(f'CREATE TABLE IF NOT EXISTS {t} LIKE {t}_new;\n')
        out.write('RENAME TABLE ' + ', '.join(f'{t} TO {t}_old, {t}_new TO {t}' for t in TABLES) + ';\n')
        out.write('DROP TABLE ' + ', '.join(t + '_old' for t in TABLES) + ';\n')
