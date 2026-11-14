"""ForeverMaster's pinned addon data as attributed reference records.

No Lua is executed. No spawn, trainer, loot probability or observed-play claim is
inferred from the presence of an entry. Reference facts never generate world SQL.
"""
import collections
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import zipfile

from . import luadata

URL = 'https://downloads.foreverchanges.pro/addon/latest/ForeverMaster.zip'
SITE = 'https://foreverchanges.pro'
FILES = ('Pack', 'Items', 'Search', 'Recipes', 'Professions', 'Leveling', 'Training',
         'Trainers', 'Dungeons', 'World', 'Chains', 'Rewards', 'Talents')
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
SKILLS = {'Alchemy': 171, 'Blacksmithing': 164, 'Cooking': 185, 'Enchanting': 333,
          'Engineering': 202, 'First Aid': 129, 'Fishing': 356, 'Herbalism': 182,
          'Leatherworking': 165, 'Mining': 186, 'Skinning': 393, 'Tailoring': 197}


def archive_data(raw, pin):
    from .facts import SourceError
    if not re.fullmatch(r'[0-9a-f]{16}|[0-9a-f]{64}', pin):
        raise SourceError('expected an archive SHA-256 pin')
    if len(raw) > MAX_ARCHIVE or not hashlib.sha256(raw).hexdigest().startswith(pin):
        raise SourceError('ForeverMaster archive differs from its pin; pin again before loading')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if sum(m.file_size for m in members) > MAX_EXPANDED:
                raise SourceError('ForeverMaster archive is too large')
            names = [m.filename for m in members]
            if len(names) != len(set(names)):
                raise SourceError('duplicate archive members')
            if any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n for n in names):
                raise SourceError('unsafe archive member')
            return {name: archive.read(f'ForeverMaster/Data/{name}.lua').decode('utf-8-sig') for name in FILES}
    except (zipfile.BadZipFile, KeyError, UnicodeError, RuntimeError) as error:
        raise SourceError(f'invalid ForeverMaster archive: {error}') from error


def fetch(pin, folder, fetch=None, log=lambda message: None):
    from .facts import SourceError
    if not re.fullmatch(r'[0-9a-f]{16}|[0-9a-f]{64}', pin):
        raise SourceError('expected an archive SHA-256 pin')
    path = Path(folder) / 'ForeverMaster.zip'
    if path.is_file():
        archive_data(path.read_bytes(), pin)
        return 0
    if fetch is None:
        import urllib.request
        def fetch(url):
            request = urllib.request.Request(url, headers={'User-Agent': 'ForeverTracker (source reference)'})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read(MAX_ARCHIVE + 1)
    raw = fetch(URL)
    archive_data(raw, pin)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(raw)
    os.replace(temp, path)
    log('ForeverMaster archive verified: ' + hashlib.sha256(raw).hexdigest())
    return 1


def read(folder, skipped=None):
    from .facts import Fact, SourceError, _id
    skipped = collections.Counter() if skipped is None else skipped
    path = Path(folder) / 'ForeverMaster.zip'
    try:
        raw = path.read_bytes()
        files = archive_data(raw, path.parent.name)
        tables = {}
        for name, text in files.items():
            parsed = luadata.tables(text)
            if parsed.get('_skipped'):
                raise SourceError(f'{name}: unsupported Lua table: {parsed["_skipped"]}')
            tables.update(parsed)
        pack = tables['ForeverMasterData.pack']
        version = re.fullmatch(r'\d+\.\d+\.\d+\.(\d+)', pack['build'])
        if not version:
            raise SourceError('missing or malformed pack build')
        build = int(version[1])
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise SourceError(f'cannot read ForeverMaster: {error}') from error
    records = collections.OrderedDict()
    def add(kind, entry, dataset, value):
        entry = _id(entry)
        if entry is None:
            skipped['invalid_id'] += 1
            return
        records.setdefault((kind, entry), collections.defaultdict(list))[dataset].append(value)
    def table(name):
        return tables.get('ForeverMasterData.' + name, {})
    def fields(row, keys):
        return {key: row[key] for key in keys.split() if key in row}

    names = re.fullmatch(r'.*?ForeverMasterData.names\s*=\s*\[==\[\s*(.*?)\s*\]==\]\s*', files['Search'], re.S)
    if not names:
        raise SourceError('unsupported item name index')
    item = 0
    for line in names[1].splitlines():
        delta, name = line.split(' ', 1)
        item += int(delta, 36)
        add('item', item, 'search_name', {'name': name})
    for item, text in table('items').items():
        parts = text.split('|', 2)
        if len(parts) != 3:
            raise SourceError(f'unsupported item record {item}')
        add('item', item, 'item_hint', dict(status=parts[0], source_kind=parts[1], hint=parts[2],
                                          explicitly_classic='in classic' in parts[2].lower()))
    recipe_keys = ('learn', 'yellow', 'green', 'grey', 'creates', 'count', 'teaching_item', 'status', 'reagents')
    for profession, recipes in table('recipes').items():
        for spell, text in recipes.items():
            parts = text.split('|')
            if len(parts) != 9:
                raise SourceError(f'unsupported recipe record {spell}')
            recipe = dict(zip(recipe_keys, parts), profession=profession)
            for kind in ('recipe', 'spell'):
                add(kind, spell, 'recipe', recipe)
            if _id(parts[4]):
                add('item', parts[4], 'crafted_by', {'spell': int(spell), 'profession': profession})
            if _id(parts[6]):
                add('item', parts[6], 'teaches_recipe', {'spell': int(spell), 'profession': profession})
    for profession, info in table('professions').items():
        for spell, rank in info.get('learn', {}).items():
            add('recipe', spell, 'profession_skill', {'profession': profession, 'rank': rank})
    for key, info in tables.items():
        match = re.fullmatch(r'ForeverMasterData.leveling\["([^"]+)"\]', key)
        if match:
            for text in info.get('recipes', []):
                values = text.split('|')
                add('recipe', values[0], 'leveling', {'profession': match[1], 'fields': values[1:]})
    for class_name, spells in table('training').items():
        for spell in spells:
            for index, rank in enumerate(spell.get('ranks', [])):
                add('spell', rank[0], 'class_training', {'class': class_name, 'name': spell.get('name'),
                    'level': rank[1], 'first_rank_from_talent': bool(spell.get('talent')) and index == 0})
    for group in ('class', 'prof'):
        for category, trainers in table('trainers').get(group, {}).items():
            for trainer in trainers:
                add('npc', trainer[0], 'trainer_location', {'category': category, 'fields': trainer[1:]})
    dungeon_maps = collections.defaultdict(list)
    for map_id, slugs in table('instances').items():
        for slug in slugs:
            dungeon_maps[slug].append(int(map_id))
    for dungeon in table('dungeons'):
        slug = dungeon['id']
        url = SITE + '/dungeons/' + slug
        overview = fields(dungeon, 'id name levels status faction zone drops')
        overview['url'] = url
        for map_id in dungeon_maps[slug]:
            add('dungeon', map_id, 'dungeon', overview)
        for boss in dungeon.get('bosses', []):
            for item in boss.get('items', []):
                add('item', item, 'boss_loot_hint', {'boss': boss.get('name'), 'dungeon': slug, 'url': url})
        quests = [(q.get('id'), q) for q in dungeon.get('quests', [])]
        quests += list(dungeon.get('steps', {}).items())
        for quest, row in quests:
            detail = fields(row, 'title level min side npc giver map x y to toMap toX toY starts xp prev next')
            detail.update(dungeon=slug, url=url)
            add('quest', quest, 'dungeon_quest', detail)
    for quest, label in table('world').get('quests', {}).items():
        add('quest', quest, 'world_label', {'name': label[0], 'level': label[1] if len(label) > 1 else None})
    for row in table('books').get('books', []):
        detail = fields(row, 'quest item tier side spots')
        add('quest', row.get('quest'), 'library_book', detail)
        add('item', row.get('item'), 'library_book', detail)
    for row in table('sleepingBag').get('steps', []):
        add('quest', row.get('quest'), 'sleeping_bag', fields(row, 'quest side spots'))
    rep = table('reputation')
    for item, row in rep.get('items', {}).items():
        vendor = rep.get('vendors', {}).get(row[0], {})
        add('item', item, 'reputation_reward', {'vendor': vendor, 'standing': row[1], 'price': row[2]})
    # Build codes are not talent node IDs; inventory them without fabricating tracker entities.
    inventory = {'talent_presets': sum(len(v) for v in table('talents').values()),
                 'talent_classes': len(table('talents')), 'dungeons': len(table('dungeons')),
                 'recipe_categories': list(table('recipes'))}
    provenance = {'pack': pack, 'archive_sha256': hashlib.sha256(raw).hexdigest(), 'url': SITE + '/addon',
                  'confidence': 'compiled_reference', 'inventory': inventory}
    for (kind, entry), datasets in records.items():
        # Preserve multiple relationships but collapse identical records repeated between dungeon wings.
        deduped = {name: list({json.dumps(v, sort_keys=True): v for v in values}.values()) for name, values in datasets.items()}
        yield Fact('reference', kind, entry, 0, build, 0, dict(provenance, datasets=deduped))
