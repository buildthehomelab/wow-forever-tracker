"""The original game as the changelog's starting point (docs/VANILLA.md).

The changelog went back to the first beta build of WoW: Forever and stopped there: that build was "the reference", and
nothing said what it had added to, changed in or taken out of the game it was made from. The starting point is patch
1.12, and Blizzard published that game's data once more in the table format of today: the client WoW Classic launched
with in August 2019 (1.13.2.31650) is patch 1.12, item for item and spell for spell. It is stored as the build before
the first beta, and the first beta build is compared with it like any build with the one before.

The 2006 client itself cannot serve: it has no item and no quest table at all (the server sent those), so half of the
comparison would rest on somebody's reconstruction. The 2019 tables are Blizzard's own.

The tables are read as CSV from wago.tools (the same public exports tools/make_baseline.py reads), kept as they came
in data/builds/<build>/enUS, and turned into the rows the tracker's own table reader would give (the columns' names of
db2-schema.json, the same types). ft.content.official then reads them like any build.

Three things are written differently in the 2019 tables. They are brought to today's form where that is exact, and
compared in a form both sides have where it is not:

- a spell effect's points: then "base" and "die sides" (13 and 9: 14 to 22), today the middle of the range (18) with
  a variance. The middle is worked out (points()).
- an item's primary stats: then the amount itself (+18 Strength), today a share of the item level's budget. Both are
  compared as amounts: today's worked out as the tooltip does (amounts()).
- an item's class restriction: then a mask of the nine classes, today -1 for "everyone". Compared over the classes
  the original game had (classes()).
"""
import csv
import datetime
import json
import math
import os
import re
import shutil
import urllib.request

from . import content, db2
from .config import BUILDS, CONFIG

DEFAULT = 'wow_classic:1.13.2.31650'    # [client] vanilla, when config.ini does not say
EXPORT = 'https://wago.tools/db2/{table}/csv?build={version}'
AGENT = {'User-Agent': 'ForeverTracker/1.1 (private server admin tool)'}
NOTE = ('The original game: patch 1.12 as Blizzard published it again in 2019 (the client WoW Classic launched with). '
        'The first beta build of WoW: Forever is compared with it.')
# The original game has no such tables: every mount, pet, toy and achievement is an addition.
ABSENT = ('ItemXItemEffect', 'Mount', 'Toy', 'BattlePetSpecies', 'Achievement', 'Creature')
TABLES = [name for name in content.DIFF_TABLES if name not in ABSENT]
STORED, UP_TO_DATE = 0, 3               # as ft.client's FETCHED and UP_TO_DATE
DAYS = {'1.13.2.31650': '2019-08-26'}   # the day a build came out: WoW Classic opened that day
CLASSES = 0x5DF                         # warrior, paladin, hunter, rogue, priest, shaman, mage, warlock, druid
PRIMARY = {0: 'mana', 1: 'health', 3: 'agility', 4: 'strength', 5: 'intellect', 6: 'spirit', 7: 'stamina'}
# Which column of an item level's stat budget an equipment slot takes its share from (RandPropPoints: 1 head, chest,
# legs and two-hand weapons; 2 shoulders, waist, feet, hands and trinkets; 3 neck, wrists, fingers, cloak and
# off-hand; 4 one-hand weapons; 5 ranged weapons and relics). WoW: Forever
# keeps the original game's rule for bows, guns, thrown weapons and wands: the ranged column. Checked on the 37
# ranged weapons with stats that the game's first build left as the original game had them: all 37 give the original
# amounts with it, none with another column.
BUDGET_SLOT = {1: 0, 4: 0, 5: 0, 7: 0, 17: 0, 20: 0, 13: 3, 21: 3, 22: 3, 3: 1, 6: 1, 8: 1, 10: 1, 12: 1,
               2: 2, 9: 2, 11: 2, 14: 2, 16: 2, 23: 2, 15: 4, 25: 4, 26: 4, 28: 4}
BUDGET_QUALITY = {2: 'GoodF', 3: 'SuperiorF', 7: 'SuperiorF', 4: 'EpicF', 5: 'EpicF', 6: 'EpicF'}


def budget(row, budgets):
    """The stat budget an item's shares are taken from: by its level, quality and slot. row: its ItemSparse row;
    budgets: {item level: RandPropPoints row}. 0 when it has none."""
    slot, prefix, level = BUDGET_SLOT.get(row['InventoryType']), BUDGET_QUALITY.get(row['OverallQualityID']), budgets.get(row['ItemLevel'])
    return level[f'{prefix}{slot + 1}'] if prefix and slot is not None and level else 0
AXES = {'PosX': 'Pos_0', 'PosY': 'Pos_1', 'PosZ': 'Pos_2'}


def setting(value=None):
    """(product, version, build) of the client that stands for the original game; None when [client] vanilla is off."""
    value = CONFIG.get('client', 'vanilla', DEFAULT) if value is None else value
    if value.strip().lower() in ('off', 'no', 'none', '0', ''):
        return None
    product, _sep, version = value.strip().partition(':')
    if not re.fullmatch(r'[a-z_]+', product) or not re.fullmatch(r'\d+(\.\d+){3}', version):
        raise ValueError(f'[client] vanilla = {value!r}: expected product:version, like {DEFAULT}')
    return product, version, int(version.rsplit('.', 1)[-1])


def is_baseline(build):
    """A stored build that is the original game (an entry of ft.content.builds())."""
    return bool(build) and build.get('baseline') == 'vanilla'


# ---------------------------------------------------------------- the stored tables as the tracker's rows
def columns(name):
    """[(column, type)] of a table as ft.db2.Table gives its rows."""
    meta = db2.SCHEMA[name]
    flat = [('int')] if meta['index'] == -1 else []
    for field in meta['fields'][:meta['fileFieldCount']]:
        flat += [field['type']] * field['array']
    if meta['fieldCount'] > meta['fileFieldCount']:
        flat.append('int')
    names = meta['names'] or db2.EXTRA_NAMES.get(name)
    if not names or len(names) != len(flat):
        return []
    return list(zip(names, flat))


def plain(column):
    """A column's name without the marks the two spellings differ in: 'StatModifier_bonusStat_0' and
    'StatModifierBonusStat1' are the same column."""
    column = re.sub(r'_lang$', '', column)
    found = re.fullmatch(r'(.*)_(\d+)', column)
    if found:
        column = f'{found.group(1)}{int(found.group(2)) + 1}'
    return column.replace('_', '').lower()


def value(text, kind):
    if kind.startswith('string'):
        return text or ''
    if kind == 'float':
        return round(float(text or 0), 4)
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return int(float(text))


def rows(folder, name):
    """A stored table as the rows ft.db2.Table would give: the tracker's column names, the same types, 0 or '' where
    the 2019 table has no such column. [] when the table is not stored."""
    path = os.path.join(folder, 'enUS', name + '.csv')
    if name == 'ItemXItemEffect':
        # then, an item's effect named its item itself; today a table of its own joins the two
        return [{'ID': index, 'ItemEffectID': effect['ID'], 'ItemID': effect['ParentItemID']}
                for index, effect in enumerate(rows(folder, 'ItemEffect'), 1) if effect['ParentItemID']]
    if not os.path.isfile(path):
        return []
    wanted = columns(name)
    out = []
    with open(path, encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        have = {plain(column): column for column in reader.fieldnames or []}
        source = {column: have.get(plain(AXES.get(column, column))) for column, _kind in wanted}
        for record in reader:
            row = {column: value(record[source[column]], kind) if source[column] else value('', kind) for column, kind in wanted}
            if name == 'SpellEffect':
                row['EffectBasePoints'] = points(row['EffectBasePoints'], value(record.get('EffectDieSides', ''), 'float'))
            elif name == 'ItemSparse':
                row['amounts'] = {int(record[f'StatModifier_bonusStat_{i}']): int(record[f'StatModifier_bonusAmount_{i}']) for i in range(10)
                                  if record.get(f'StatModifier_bonusAmount_{i}') not in (None, '', '0')}
            elif name == 'ItemEffect':
                row['ParentItemID'] = value(record.get('ParentItemID', ''), 'int')
            out.append(row)
    return out


def points(base, sides):
    """A spell effect's points as today's tables write them: the middle of the range the original game rolled
    (base + 1 to base + sides)."""
    return round(float(base) + (sides + 1) / 2, 4) if sides >= 1 else round(float(base), 4)


def official(folder):
    """The original game's official content (as ft.content.official gives a build's), each item with its primary
    stats as amounts."""
    kept = {}

    def read(name):
        if name not in kept:
            kept[name] = rows(folder, name)
        return kept[name]
    out = content.official(folder, read)
    for row in read('ItemSparse'):
        if row['ID'] in out['item']:
            out['item'][row['ID']]['amounts'] = {stat: amount for stat, amount in row['amounts'].items() if stat in PRIMARY}
    return out


# ---------------------------------------------------------------- comparing the first beta build with it
def classes(mask):
    """An item's class restriction over the classes the original game had: 0 when every one of them may use it."""
    mask = int(mask or 0)
    return 0 if mask in (-1, 0) or mask & CLASSES == CLASSES else mask & CLASSES


def amounts(folder, budget_folder):
    """{item: {stat: amount}} of a build's items, primary stats only, worked out as the tooltip does: the share of the
    item level's budget. budget_folder: the folder of a build that has the budget table (the earlier builds are stored
    with the compared tables alone)."""
    budgets = {row['ID']: row for row in content.table(budget_folder, 'RandPropPoints', 'enUS')}
    out = {}
    for row in content.table(folder, 'ItemSparse', 'enUS'):
        share = budget(row, budgets)
        found = {}
        for i in range(1, 11):
            stat, percent = row[f'StatModifierBonusStat{i}'], row[f'StatPercentEditor{i}']
            if stat in PRIMARY and percent:
                amount = int(math.floor(percent * share * 0.0001 + 0.5))
                if amount:
                    found[stat] = found.get(stat, 0) + amount
        out[row['ID']] = found
    return out


def view(kind, entity, stats=None):
    """What of a resource both the original game's tables and today's say in a form that can be compared. stats: an
    item's primary stats as amounts ({stat: amount}), None when they cannot be worked out (then they are left out
    on both sides)."""
    facts = dict(entity.get('facts') or {})
    if kind == 'item':
        facts.pop('stats', None)
        facts['classes'] = classes(facts.get('classes'))
        if stats is not None:
            facts['stats'] = sorted([PRIMARY[int(stat)], amount] for stat, amount in stats.items())
    elif kind == 'taxi':
        # then 3 on every flight point, today each one's side and more: another meaning, nothing to compare
        facts.pop('flags', None)
    return facts


def compare(before, after, stats=None):
    """The first build against the original game: [(kind, id, change, fields)], as ft.content.diff_builds, over view().
    before: official(); after: {kind: {id: entity}} of the first build; stats: amounts() of the first build, or None."""
    changes = []
    for kind in after:
        if kind.startswith('_'):
            continue
        old, new = before.get(kind, {}), after[kind]
        changes += [(kind, entity_id, 'added', {}) for entity_id in new.keys() - old.keys()]
        changes += [(kind, entity_id, 'removed', {}) for entity_id in old.keys() - new.keys()]
        for entity_id in new.keys() & old.keys():
            there = stats is not None and kind == 'item'
            was = view(kind, old[entity_id], old[entity_id].get('amounts', {}) if there else None)
            now = view(kind, new[entity_id], stats.get(entity_id, {}) if there else None)
            fields = {key: [was.get(key), now.get(key)] for key in set(was) | set(now) if was.get(key) != now.get(key)}
            if fields:
                changes.append((kind, entity_id, 'modified', fields))
    return changes


def budget_folder(chain):
    """The folder of the oldest stored build that has the stat budget table; None when none has."""
    for build in chain:
        if os.path.isfile(os.path.join(build['dir'], 'enUS', 'RandPropPoints.db2')):
            return build['dir']
    return None


def step(base, chain, late, load, log=lambda text: None, read=None):
    """What the game's first build added to, changed in and removed from the original game, kept in the original
    game's folder: {'counts', 'ids', 'changes': [[kind, id, change, fields, name]], 'alone', 'minor', 'hidden',
    'compared'}.

    base: the original game's entry of ft.content.builds(); chain: the game's builds, oldest first; late: {build:
    {(kind, id)}} of the resources that exist by hotfix alone and count as known since the first build (thousands of
    the original game's items are in no table of WoW: Forever and reach the client by hotfix); load: a build -> its
    official content; read: a folder -> the original game's official content (for tests).

    Such a resource is compared as its hotfix stands, and never called removed: the first build's tables do not have
    it, but nothing says the game ever lacked it. One of them that the original game did not have is not called
    added either, here as in every build (ft.content.changelog).

    'alone': those of them the original game had; 'minor': the removed spells players never learned or used themselves
    (what an item or a creature cast, a trigger, a leftover: internal, as such a spell is in every build); 'hidden': how many records of the first
    build are still encrypted, by table (an original resource among them reads as removed until its key is out)."""
    first = chain[0]
    where = budget_folder(chain)
    sources = sorted(late)
    by_build = {build['build']: build for build in chain}
    budget_mark = ''
    if where:
        with open(os.path.join(where, 'enUS', 'RandPropPoints.db2'), 'rb') as handle:
            budget_mark = content.hashlib.sha1(handle.read()).hexdigest()[:12]
    mark = [content.code_mark(), content.signature(base), content.signature(first), budget_mark,
            [[build, content.signature(by_build[build]), len(late[build])] for build in sources]]
    found = content.kept_as(base, mark)
    if found is not None:
        return found
    log(f"the original game ({base.get('version') or base['build']}) against build {first['build']}")
    before = (read or official)(base['dir'])
    out = {'counts': {kind: len(entities) for kind, entities in before.items() if not kind.startswith('_')},
           'ids': {kind: sorted(entities) for kind, entities in before.items() if not kind.startswith('_')},
           'changes': [], 'alone': [], 'minor': [], 'hidden': {}, 'compared': True}
    if CONFIG.french() and os.path.isdir(os.path.join(first['dir'], 'frFR')):
        # names and texts would be French on one side and English on the other
        log(f"build {first['build']} is stored in French: it is not compared with the original game's English tables")
        out['compared'] = False
        return content.keep_as(base, mark, out)
    current = load(first)
    after = {kind: dict(entities) for kind, entities in current.items() if not kind.startswith('_')}
    stats = amounts(first['dir'], where) if where else None
    alone = set()
    for build in sources:
        there = load(by_build[build])
        their = amounts(by_build[build]['dir'], where) if where else {}
        for kind, entity_id in late[build]:
            if entity_id in there.get(kind, {}) and entity_id not in after.get(kind, {}):
                after.setdefault(kind, {})[entity_id] = there[kind][entity_id]
                alone.add((kind, entity_id))
                if kind == 'item' and stats is not None:
                    stats[entity_id] = their.get(entity_id, {})
    for kind, entity_id, change, fields in compare(before, after, stats):
        if change == 'added' and (kind, entity_id) in alone:
            continue
        entity = after.get(kind, {}).get(entity_id) or before.get(kind, {}).get(entity_id) or {}
        out['changes'].append([kind, entity_id, change, fields, entity.get('name', '')])
        if change == 'removed' and kind == 'spell' and entity.get('sub') not in content.PLAYER_SPELLS:
            out['minor'].append([kind, entity_id])
    out['alone'] = sorted([kind, entity_id] for kind, entity_id in alone if entity_id in before.get(kind, {}))
    out['hidden'] = dict((current.get('_meta') or {}).get('hidden') or {})
    return content.keep_as(base, mark, out)


# ---------------------------------------------------------------- storing it
def download(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=600) as response:
        return response.read()


CONFIGURED = object()


def fetch(log=print, get=None, again=False, choice=CONFIGURED, builds=None):
    """Stores the original game's tables once, as the build before the first beta: {'code': STORED | UP_TO_DATE,
    'build', 'message'}. A table that cannot be read stores nothing (asked again at the next check). get: url -> bytes;
    choice: as setting() gives it, None for "off"; builds: the folder of the builds (all three for tests)."""
    choice = setting() if choice is CONFIGURED else choice
    if choice is None:
        return {'code': UP_TO_DATE, 'build': 0, 'message': 'the original game is not asked for ([client] vanilla = off)'}
    product, version, build = choice
    builds = builds or BUILDS
    target = os.path.join(builds, str(build))
    if os.path.isfile(os.path.join(target, 'build.json')) and not again:
        return {'code': UP_TO_DATE, 'build': build, 'message': f'the original game ({version}) is stored'}
    log(f'vanilla: reading the original game\'s tables ({version}, {len(TABLES)} tables, once)')
    scratch = os.path.join(builds, f'.{build}.part')
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(os.path.join(scratch, 'enUS'))
    try:
        for name in TABLES:
            data = (get or download)(EXPORT.format(table=name, version=version))
            head = data[:4096].decode('utf-8-sig', 'replace').split('\n', 1)[0]
            if 'ID' not in [column.strip() for column in head.split(',')]:
                raise RuntimeError(f'{name}: not a table ({head[:80]!r})')
            with open(os.path.join(scratch, 'enUS', name + '.csv'), 'wb') as handle:
                handle.write(data)
        today = datetime.date.today().isoformat()
        info = {'build': build, 'version': version, 'date': DAYS.get(version) or today, 'read': today, 'note': NOTE,
                'source': f'wago.tools ({product} {version})', 'tables': 'changelog', 'baseline': 'vanilla', 'dated': 'list'}
        with open(os.path.join(scratch, 'build.json'), 'w', encoding='utf-8') as handle:
            json.dump(info, handle, ensure_ascii=False, indent=1)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(scratch, target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {'code': STORED, 'build': build, 'message': f'the original game ({version}): {len(TABLES)} tables stored (run the analysis)'}


