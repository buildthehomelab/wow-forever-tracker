"""Writes the analysis into the tracker database (ft_* tables), swapped atomically."""
import datetime
import json
import re

from . import sqlio
from .baseline import Baseline

INTERNAL_NAME = re.compile(r'^\s*\[|^\s*<|^\s*$|^zz|Test(?![a-z])|\btest\b|\b(OLD|TEST|Test|DEPRECATED|Deprecated|DEP|PH|DNT|QA|Unused|UNUSED|NYI|Monster|Monstre|PÉRIMÉ|NPC Equip|Template|Placeholder)\b|\(DNT\)|\(OLD\)|\bcopy\b')
# Flight paths a quest flies you along (TaxiNodes rows named "Quest Path 11512: ..."), not flight points.
QUEST_PATH = re.compile(r'^Quest Path \d+')
DATA_KEYS = ('ranks', 'spell', 'item', 'map', 'pos', 'creature', 'kind', 'teach', 'creates')
TABLES = ('ft_builds', 'ft_entities', 'ft_changes', 'ft_meta', 'ft_tooltips', 'ft_fixes')

SCHEMA_SQL = """
CREATE TABLE ft_builds_new (build INT PRIMARY KEY, version VARCHAR(32), released DATE NULL, note TEXT, source VARCHAR(255), is_server TINYINT NOT NULL DEFAULT 0, counts JSON) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_entities_new (type VARCHAR(16) NOT NULL, id INT NOT NULL, name VARCHAR(255) NOT NULL, name_en VARCHAR(255) NOT NULL DEFAULT '',
  sub VARCHAR(120) NOT NULL DEFAULT '', level INT NOT NULL DEFAULT 0, quality TINYINT NOT NULL DEFAULT -1, icon VARCHAR(96) NOT NULL DEFAULT '',
  internal TINYINT NOT NULL DEFAULT 0, is_new TINYINT NOT NULL DEFAULT 0, status ENUM('ok','partial','missing') NOT NULL, score TINYINT NOT NULL, checks JSON, data JSON,
  first_build INT NOT NULL, changed_build INT NOT NULL, phase TINYINT NOT NULL DEFAULT 0, PRIMARY KEY (type, id), KEY ix_status (type, status, internal, phase), KEY ix_name (name), KEY ix_name_en (name_en), KEY ix_changed (changed_build)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ft_changes_new (seq INT AUTO_INCREMENT PRIMARY KEY, build INT NOT NULL, prev_build INT NOT NULL, type VARCHAR(16) NOT NULL, id INT NOT NULL,
  kind ENUM('added','removed','modified') NOT NULL, name VARCHAR(255) NOT NULL DEFAULT '', fields JSON, KEY ix_build (build, type, kind), KEY ix_entity (type, id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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
            out.write(f"INSERT INTO ft_builds_new VALUES ({b['build']},{e(b['version'])},{e(b['date'])},{e(b['note'])},{e(b['source'])},{1 if b['build'] == server_build else 0},{e(dumps(b.get('counts', {})))});\n")
        baseline = Baseline()
        covered = covered_elsewhere(content)
        batch = Batch(out, 'ft_entities_new')
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
                internal = 1 if unknown_everywhere or (name and INTERNAL_NAME.search(name)) else 0
                if not name:
                    data['unnamed'] = True
                name = name or f'#{entity_id}'
            elif kind == 'spell':
                internal = 0 if entity['sub'] in ('class', 'profession', 'racial', 'talent', 'mount', 'pet', 'rune', 'petability') else 1
            elif kind == 'item':
                internal = 1 if INTERNAL_NAME.search(name_en or name) or not name else 0
            elif kind in ('achievement', 'taxi', 'zone', 'dungeon', 'boss'):
                internal = 1 if INTERNAL_NAME.search(name_en or name) or not name or entity.get('weak') else 0
                if kind == 'taxi' and QUEST_PATH.search(name_en or name):
                    internal = 1
                if kind in ('dungeon', 'boss') and baseline.season_map(entity_id if kind == 'dungeon' else int(entity.get('map') or 0)):
                    internal = 1  # a Season of Discovery instance (or one never opened) and its bosses: listed under Internal / test
                    data['season'] = True
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
        for build, previous, kind, entity_id, change, fields, name in changes:
            batch.add(f"(NULL,{build},{previous},{e(kind)},{entity_id},{e(change)},{e((name or '')[:250])},{e(dumps(fields))})")
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
                'schema': 3,
                # release phases in order (number = position + 1): ft_entities.phase holds the number, 0 = released
                'phases': list(phase_list),
                # quests an item starts (ItemSparse.StartQuestID): they need no giver, the imports leave them alone
                'item_quests': sorted(ctx.get('start_quest_item', {})) if ctx else []}
        for key, value in meta.items():
            out.write(f"INSERT INTO ft_meta_new VALUES ({e(key)},{e(dumps(value))});\n")
        # atomic swap
        for t in TABLES:
            out.write(f'CREATE TABLE IF NOT EXISTS {t} LIKE {t}_new;\n')
        out.write('RENAME TABLE ' + ', '.join(f'{t} TO {t}_old, {t}_new TO {t}' for t in TABLES) + ';\n')
        out.write('DROP TABLE ' + ', '.join(t + '_old' for t in TABLES) + ';\n')
