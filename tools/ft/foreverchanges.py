"""ForeverMaster's pinned addon data as attributed reference records.

No Lua is executed. No spawn, trainer or observed-play claim is inferred from the
presence of an entry, and the only chance kept is the pack's own figure for a Classic
boss, named as that. Reference facts never generate world SQL. What the site's pages
state beyond the pack is read by foreverchanges_pages.
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
         'Trainers', 'Dungeons', 'Journal', 'World', 'Chains', 'Rewards', 'Talents')
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024


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


def download(url=URL):
    """The archive's bytes, one byte more than the limit at most (so that a file too large is refused, not cut)."""
    import urllib.request
    request = urllib.request.Request(url, headers={'User-Agent': 'ForeverTracker (source reference)'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(MAX_ARCHIVE + 1)


def fetch(pin, folder, fetch=None, log=lambda message: None):
    from .facts import SourceError
    if not re.fullmatch(r'[0-9a-f]{16}|[0-9a-f]{64}', pin):
        raise SourceError('expected an archive SHA-256 pin')
    path = Path(folder) / 'ForeverMaster.zip'
    if path.is_file():
        archive_data(path.read_bytes(), pin)
        return 0
    raw = (fetch or download)(URL)
    archive_data(raw, pin)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(raw)
    os.replace(temp, path)
    log('ForeverMaster archive verified: ' + hashlib.sha256(raw).hexdigest())
    return 1


STATUS = {'n': 'new', 'c': 'changed', '': ''}
# Items.lua's source letter, as the addon's tooltip words it.
ITEM_SOURCES = {'w': 'world drop', 'q': 'quest (Classic)', 'Q': 'quest (new)', 'C': 'crafted', 'm': 'creature', 'B': 'dungeon',
                'v': 'vendors', 'V': 'one vendor', 'R': 'rare creature', '': ''}
# Leveling.lua's source letter (the addon's Lib/Leveling.lua): where a recipe is learned.
RECIPE_SOURCES = {'t': 'trainer', 'v': 'vendor', 'r': 'reputation', 'd': 'drop', 'f': "merchant's favor", 'q': 'quest'}
LEVELING = 'learn yellow green grey creates count reagents source rod price fee teaching_item'.split()
TRAINER = 'name side map x y continent continent_x continent_y'.split()
MAX_PINS = 4                                           # a giver stands on every zone map whose rectangle covers it


def _number(text):
    """A whole number written as text, or None for an empty field. Anything else is not a number: ValueError."""
    text = str(text).strip()
    if text == '':
        return None
    if not (text.isascii() and text.isdecimal()):
        raise ValueError(f'not a number: {text!r}')
    return int(text)


def _reagents(text):
    """[[item, count], ...] of "785:2,2447"."""
    out = []
    for part in filter(None, text.split(',')):
        item, _, count = part.partition(':')
        out.append([_number(item), _number(count) or 1])
    return out


def _recipe_source(code):
    out = {'source': RECIPE_SOURCES.get(code[:1], code)}
    if code == 'vl':
        out['limited_stock'] = True
    if code in ('va', 'vh'):
        out['side'] = 'Alliance' if code == 'va' else 'Horde'
    return out


def _pins(world, skipped):
    """{quest: {giver name: {'name', 'title', 'side', 'pins': [[uiMap, x, y], ...]}}} of World.lua's quest giver layer.

    A record is "layer,x,y,name,title,kind[,side[,quests]]": the layer is a 1-based index into `layers`, the three
    words 0-based indexes into `words`, the quests ids joined by "/". Names only: the pack gives its givers no id."""
    layers, words, maps = world.get('layers', []), world.get('words', []), world.get('maps', {})
    givers = layers.index('givers') + 1 if 'givers' in layers else None
    out = collections.defaultdict(dict)
    for ui_map, text in (maps.items() if isinstance(maps, dict) and givers else ()):
        for record in filter(None, str(text).split(';')):
            fields = record.split(',')
            if not fields[0].isdecimal() or int(fields[0]) != givers or len(fields) < 8 or not fields[7]:
                continue
            try:
                name, title = (words[int(fields[i])] if fields[i] else '' for i in (3, 4))
                pin = [int(ui_map), float(fields[1]), float(fields[2])]
            except (ValueError, IndexError):
                skipped['world_pin'] += 1
                continue
            for quest in fields[7].split('/'):
                giver = out[quest].setdefault(name, {'name': name, 'title': title, 'side': fields[6], 'pins': []})
                if len(giver['pins']) < MAX_PINS:
                    giver['pins'].append(pin)
    return out


def read(folder, skipped=None, about=None):
    """The pack's records as reference facts, one per resource. `about`, when given, is filled with what is said once
    and not on every fact: the pack's own header, the archive's SHA-256 and what the pack holds that is no resource."""
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
    def rows(value):
        return value if isinstance(value, list) else []      # an empty Lua table reads as {}: no rows

    try:
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
            add('item', item, 'item_hint', dict(status=STATUS.get(parts[0], parts[0]), source_kind=ITEM_SOURCES.get(parts[1], parts[1]),
                                              hint=parts[2], explicitly_classic='in classic' in parts[2].lower()))
        for profession, recipes in table('recipes').items():
            for spell, text in recipes.items():
                parts = text.split('|')
                if len(parts) != 9:
                    raise SourceError(f'unsupported recipe record {spell}')
                learn, yellow, green, grey, creates, count, teaching_item = (_number(p) for p in parts[:7])
                recipe = dict(profession=profession, learn=learn, yellow=yellow, green=green, grey=grey, creates=creates, count=count or 1,
                              teaching_item=teaching_item, status=STATUS.get(parts[7], parts[7]), reagents=_reagents(parts[8]))
                for kind in ('recipe', 'spell'):
                    add(kind, spell, 'recipe', recipe)
                if creates:
                    add('item', creates, 'crafted_by', {'spell': int(spell), 'profession': profession})
                if teaching_item:
                    add('item', teaching_item, 'teaches_recipe', {'spell': int(spell), 'profession': profession})
        for profession, info in table('professions').items():
            for spell, rank in info.get('learn', {}).items():
                add('recipe', spell, 'profession_skill', {'profession': profession, 'rank': rank})
        for key, info in tables.items():
            match = re.fullmatch(r'ForeverMasterData.leveling\["([^"]+)"\]', key)
            for text in rows(info.get('recipes')) if match else ():
                values = text.split('|')
                if len(values) != len(LEVELING) + 1:
                    raise SourceError(f'unsupported leveling record {values[0]}')
                detail = dict(zip(LEVELING, values[1:]), profession=match[1])
                detail.update(_recipe_source(detail.pop('source')), reagents=_reagents(detail['reagents']))
                for name in ('learn', 'yellow', 'green', 'grey', 'creates', 'count', 'rod', 'price', 'fee', 'teaching_item'):
                    detail[name] = _number(detail[name])
                for name in ('rod', 'teaching_item'):        # 0 is the pack's "none"
                    detail[name] = detail[name] or None
                add('recipe', values[0], 'leveling', detail)
    except ValueError as error:                              # a field that should be a number is not one
        raise SourceError(f'unsupported ForeverMaster record: {error}') from error
    for class_name, spells in table('training').items():
        for spell in spells:
            for index, rank in enumerate(spell.get('ranks', [])):
                detail = {'class': class_name, 'name': spell.get('name'), 'level': rank[1],
                          'first_rank_from_talent': bool(spell.get('talent')) and index == 0}
                detail.update(fields(spell, 'status note races'))
                add('spell', rank[0], 'class_training', detail)
    for group in ('class', 'prof'):
        for category, trainers in table('trainers').get(group, {}).items():
            for trainer in trainers:
                add('npc', trainer[0], 'trainer_location', dict(zip(TRAINER, trainer[1:]), category=category))
    dungeon_maps = collections.defaultdict(list)
    for map_id, slugs in table('instances').items():
        for slug in slugs:
            dungeon_maps[slug].append(int(map_id))
    entrances = collections.defaultdict(list)
    for row in rows(table('entrances')):
        entrances[row[0]].append(dict(zip(('map', 'x', 'y', 'continent', 'continent_x', 'continent_y'), row[1:])))
    for dungeon in table('dungeons'):
        slug = dungeon['id']
        url = SITE + '/dungeons/' + slug
        overview = fields(dungeon, 'id name levels status faction zone drops req ilvl')
        overview['url'] = url
        if entrances[slug]:
            overview['entrances'] = entrances[slug]
        for map_id in dungeon_maps[slug]:
            add('dungeon', map_id, 'dungeon', overview)
        for boss in rows(dungeon.get('bosses')):
            items, chances = rows(boss.get('items')), rows(boss.get('chances'))
            for index, item in enumerate(items):
                hint = {'boss': boss.get('name'), 'dungeon': slug, 'url': url}
                hint.update(fields(boss, 'level kind'))
                if len(chances) == len(items):               # Classic bosses only: AtlasLootClassic's figure, the site says
                    hint['classic_chance'] = chances[index]
                add('item', item, 'boss_loot_hint', hint)
        for row in rows(dungeon.get('questItems')):
            detail = dict(fields(row, 'item quest title from'), dungeon=slug)
            add('item', row.get('item'), 'quest_item', detail)
            add('quest', row.get('quest'), 'quest_item', detail)
        quests = [(q.get('id'), q) for q in rows(dungeon.get('quests'))]
        steps = dungeon.get('steps')
        quests += list(steps.items()) if isinstance(steps, dict) else []
        for quest, row in quests:
            detail = fields(row, 'title level min side npc giver zone map x y to toMap toX toY starts xp prev next new')
            detail.update(dungeon=slug, url=url)
            add('quest', quest, 'dungeon_quest', detail)
    world = table('world')
    for quest, label in world.get('quests', {}).items():
        add('quest', quest, 'world_label', {'name': label[0], 'level': label[1] if len(label) > 1 else None})
    for quest, givers in _pins(world, skipped).items():
        for giver in givers.values():
            add('quest', quest, 'map_giver', giver)
    books = table('books')
    for row in rows(books.get('books')):
        detail = fields(row, 'quest item tier side spots')
        add('quest', row.get('quest'), 'library_book', detail)
        add('item', row.get('item'), 'library_book', detail)
    for row in rows(books.get('librarians')):
        add('npc', row.get('npc'), 'librarian', fields(row, 'name side uiMap x y'))
    for row in rows(table('sleepingBag').get('steps')):
        add('quest', row.get('quest'), 'sleeping_bag', fields(row, 'quest side spots'))
    rep = table('reputation')
    for item, row in rep.get('items', {}).items():
        vendor = rep.get('vendors', {}).get(row[0], {})
        add('item', item, 'reputation_reward', {'vendor': vendor, 'standing': row[1], 'price': row[2]})
        add('npc', vendor.get('npc'), 'reputation_vendor', {'item': int(item), 'standing': row[1], 'price': row[2]})
    if about is not None:
        # Build codes are not talent node IDs; inventory them without fabricating tracker entities.
        about.update(pack=pack, archive_sha256=hashlib.sha256(raw).hexdigest(), url=SITE + '/addon', confidence='compiled_reference',
                     inventory={'talent_presets': sum(len(v) for v in table('talents').values()), 'talent_classes': len(table('talents')),
                                'dungeons': len(table('dungeons')), 'recipe_categories': list(table('recipes'))})
    version = str(pack.get('version', ''))
    for (kind, entry), datasets in records.items():
        # Preserve multiple relationships but collapse identical records repeated between dungeon wings.
        deduped = {name: list({json.dumps(v, sort_keys=True): v for v in values}.values()) for name, values in datasets.items()}
        # What is the same for every record (the archive's hash, the pack's header) is `about`'s, and the pin's in
        # ft_world_sources: a record carries only the pack's version.
        yield Fact('reference', kind, entry, 0, build, 0, {'pack': version, 'datasets': deduped})
