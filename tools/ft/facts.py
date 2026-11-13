"""Facts: what each source of the world build says, in one shape, kept in the tracker's database.

A fact is one claim of one source on one client build: "NPC 240 offers quest 35", "quest 91724 has this record",
"creature 474 was seen at levels 9 to 10". Sources keep their own files and words; a reader turns one source into
facts, and nothing after it needs to know the source's format:

    kind          subject            object   data (the source's own record, as it gave it)
    gives, takes  npc, object        quest    who offers a quest, who takes it back
    sells         npc                item     listings: every way the vendor lists the item (costs, stack, stock)
    teaches       npc                spell    costs, level, skill line and rank
    drops         npc, object, item  item     ways: per way of looting (alone, in a group, on a quest, through which
                                              spell): drops, loot windows, kills, the source's own chance
    gathers       npc                item     the same, when a spell did it (skinning, pick pocketing)
    fishes        uimap              item     the same, from the water of a map
    coins         npc, object, item  -        ways: the money looted
    talked        npc, object        -        a player opened its window: levels, side, what it offers, where it stood
    seen          npc                -        seen in the world or fought: levels, rank, reactions, where
    quest         quest              -        the quest's record as the server sent it to a client
    creature      npc                -        the creature's record as the server sent it
    object        object             -        the object's record as the server sent it
    objective     quest              index    an objective counted while a player did the quest
    turn_in       quest              -        what handing the quest in gave
    text          quest              -        what was said when the quest was offered (accept), asked about
                                              (progress) and handed in (complete): the wordings seen, the most
                                              seen first (MAX_WORDINGS of them at most)
    entry         quest, npc,        -        its entry in a database people keep by hand (QuestieDB's corrections), in
                  object, item                that database's own fields

`samples` is what stands behind the claim, in the kind's own unit: loot windows that show every item (not a
group's) for drops, gathers, fishes and coins; windows opened for talked; sightings for seen; players for the
others. Nothing is weighed or worked out here: the facts are the source's numbers, per build, and the rules read them
later. Only long lists of positions are cut to MAX_POSITIONS (the fact then says how many there were).

This module reads no configuration and no database, so it can be imported and tested alone.
"""
import collections
import http.client
import json
import os
import re
import urllib.request

from . import luadata

FACTS, SOURCES = 'ft_world_facts', 'ft_world_sources'
KINDS = ('gives', 'takes', 'sells', 'teaches', 'drops', 'gathers', 'fishes', 'coins', 'talked', 'seen', 'quest', 'creature', 'object',
         'objective', 'turn_in', 'text', 'entry')
SUBJECTS = ('npc', 'object', 'item', 'quest', 'uimap')
Fact = collections.namedtuple('Fact', 'kind subject_kind subject object build samples data')

SCHEMA = [
    f'CREATE TABLE IF NOT EXISTS {FACTS} (source VARCHAR(32) NOT NULL, kind VARCHAR(16) NOT NULL, subject_kind VARCHAR(8) NOT NULL, '
    'subject INT UNSIGNED NOT NULL, object INT UNSIGNED NOT NULL DEFAULT 0, build INT UNSIGNED NOT NULL DEFAULT 0, '
    'samples INT UNSIGNED NOT NULL DEFAULT 0, data MEDIUMTEXT NOT NULL, PRIMARY KEY (source, kind, subject_kind, subject, object, build), '
    'KEY by_subject (kind, subject_kind, subject), KEY by_object (kind, object)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    f'CREATE TABLE IF NOT EXISTS {SOURCES} (source VARCHAR(32) NOT NULL PRIMARY KEY, pin VARCHAR(120) NOT NULL, licence VARCHAR(40) NOT NULL, '
    'allowed VARCHAR(12) NOT NULL, facts INT NOT NULL, left_out INT NOT NULL, loaded_at DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
]
MAX_ID = 2 ** 32 - 1
MAX_POSITIONS = 40
USER_AGENT = 'ForeverTracker (world build)'


class SourceError(Exception):
    """A source's files cannot be fetched or read."""


def _id(value):
    """A game id as a number, or None when the text is not one."""
    text = str(value)
    return int(text) if text.isascii() and text.isdecimal() and 0 < int(text) <= MAX_ID else None


def _count(value):
    return max(0, min(int(value), MAX_ID)) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _dict(value):
    return value if isinstance(value, dict) else {}


def _records(dataset, name):
    return _dict(_dict(dataset).get(name)).items()


def _capped(record, without=()):
    """The source's record as it is, minus the keys read elsewhere, with a long list of positions cut short."""
    out = {key: value for key, value in record.items() if key not in without}
    where = out.get('positions')
    if isinstance(where, list) and len(where) > MAX_POSITIONS:
        out['positions'], out['positionsSeen'] = where[:MAX_POSITIONS], len(where)
    return out


# ------------------------------------------------------------------ EG Link
EGLINK_REPO = 'JIVESCORP/eg-link-output-wowf'
EGLINK_PRODUCT = 'wowf'
EGLINK_DATASETS = ('npcs', 'creatures', 'vendors', 'trainers', 'loot', 'quests.enUS', 'creature_details.enUS', 'object_details.enUS',
                   'objectives', 'turn_ins', 'texts.enUS')
VERSION = re.compile(r'\d+\.\d+\.\d+\.(\d+)')
COMMIT = re.compile(r'[0-9a-f]{40}')
LOOTED = {'npc': 'npc', 'object': 'object', 'item': 'item', 'fishing': 'uimap'}


def _eglink_npcs(build, dataset, skipped):
    for section, kind in (('npcs', 'npc'), ('objects', 'object')):
        for key, record in _records(dataset, section):
            subject = _id(key)
            if subject is None or not isinstance(record, dict):
                skipped['npcs'] += 1
                continue
            yield Fact('talked', kind, subject, 0, build, _count(record.get('windows')), _capped(record, ('offers', 'takes')))
            for relation, field in (('gives', 'offers'), ('takes', 'takes')):
                for quest_key, quest in _dict(record.get(field)).items():
                    quest_id = _id(quest_key)
                    if quest_id is None:
                        skipped['npcs'] += 1
                        continue
                    yield Fact(relation, kind, subject, quest_id, build, _count(record.get('sources')), _dict(quest))


def _eglink_creatures(build, dataset, skipped):
    for key, record in _records(dataset, 'creatures'):
        subject = _id(key)
        if subject is None or not isinstance(record, dict):
            skipped['creatures'] += 1
            continue
        data = _capped(record)
        if isinstance(data.get('combatLog'), dict):
            data['combatLog'] = _capped(data['combatLog'])
        yield Fact('seen', 'npc', subject, 0, build, _count(record.get('seen')), data)


def _eglink_vendors(build, dataset, skipped):
    for key, record in _records(dataset, 'vendors'):
        npc = _id(key)
        if npc is None or not isinstance(record, dict):
            skipped['vendors'] += 1
            continue
        listings = collections.OrderedDict()             # a vendor can list one item twice (two stacks, two prices)
        for entry in _dict(record.get('entries')).values():
            item = _id(entry.get('itemId')) if isinstance(entry, dict) else None
            if item is None:
                skipped['vendors'] += 1
                continue
            listings.setdefault(item, []).append(entry)
        for item, entries in listings.items():
            yield Fact('sells', 'npc', npc, item, build, max(_count(e.get('sources')) for e in entries), {'listings': entries})


def _eglink_trainers(build, dataset, skipped):
    for key, record in _records(dataset, 'trainers'):
        npc = _id(key)
        if npc is None or not isinstance(record, dict):
            skipped['trainers'] += 1
            continue
        about = {field: record[field] for field in ('trainerType', 'tradeskill') if field in record}
        for service in _dict(record.get('services')).values():
            spell = _id(service.get('spellId')) if isinstance(service, dict) else None
            if spell is None:
                skipped['trainers'] += 1
                continue
            yield Fact('teaches', 'npc', npc, spell, build, _count(service.get('sources')), dict(service, **about))


def _eglink_loot(build, dataset, skipped):
    """One fact per looted thing and item. EG Link keeps a loot record per way of looting ("npc:474", "npc:474|group",
    "npc:474|quest", "npc:474|spell:8613" ...): each stays apart under `ways`, by what follows the thing in the
    record's name ('plain' when nothing does), with the source's own numbers and its kill count for that way.
    `samples` adds the windows of the ways that show every item: a group's window does not."""
    kills = _dict(dataset.get('kills'))
    merged, money = collections.OrderedDict(), collections.OrderedDict()
    for key, record in _records(dataset, 'sources'):
        base, *modifiers = key.split('|')
        thing, _, raw = base.partition(':')
        subject = _id(raw)
        if thing not in LOOTED or subject is None or not isinstance(record, dict):
            skipped['loot'] += 1
            continue
        by_spell = any(m.startswith('spell:') for m in modifiers)
        kind = 'fishes' if thing == 'fishing' else ('gathers' if thing == 'npc' and by_spell else 'drops')
        way = '|'.join(modifiers) or 'plain'
        windows = _count(record.get('windows'))
        whole = 'group' not in modifiers
        # kills are counted per corpse, whatever spell looted it: "npc:474", "npc:474|quest", "npc:474|group" ...
        died = _dict(kills.get('|'.join([base] + [m for m in modifiers if m in ('quest', 'group')])))
        about = {'windows': windows}
        if died and not by_spell:
            about.update(kills=max(0, _count(died.get('deaths')) - _count(died.get('unknown'))), empty=_count(died.get('empty')))
        for item_key, drop in _dict(record.get('items')).items():
            item = _id(item_key)
            if item is None or not isinstance(drop, dict):
                skipped['loot'] += 1
                continue
            fact = merged.setdefault((kind, LOOTED[thing], subject, item), {'ways': {}, 'samples': 0})
            fact['ways'][way] = dict(drop, **about)
            fact['samples'] += windows if whole else 0
        if kind == 'drops' and any(field in record for field in ('coins', 'copper')):
            fact = money.setdefault((LOOTED[thing], subject), {'ways': {}, 'samples': 0})
            fact['ways'][way] = dict({f: record[f] for f in ('coins', 'copper', 'copperWindows') if f in record}, **about)
            fact['samples'] += windows if whole else 0
    for (kind, subject_kind, subject, item), fact in merged.items():
        yield Fact(kind, subject_kind, subject, item, build, fact['samples'], {'ways': fact['ways']})
    for (subject_kind, subject), fact in money.items():
        yield Fact('coins', subject_kind, subject, 0, build, fact['samples'], {'ways': fact['ways']})


def _eglink_records(kind, subject_kind, section, name):
    def emit(build, dataset, skipped):
        for key, record in _records(dataset, section):
            subject = _id(key)
            if subject is None or not isinstance(record, dict):
                skipped[name] += 1
                continue
            yield Fact(kind, subject_kind, subject, 0, build, _count(record.get('sources')), record)
    return emit


def _eglink_objectives(build, dataset, skipped):
    for key, objectives in _records(dataset, 'quests'):
        quest = _id(key)
        if quest is None or not isinstance(objectives, dict):
            skipped['objectives'] += 1
            continue
        for index, objective in objectives.items():
            if not (str(index).isascii() and str(index).isdecimal()) or not isinstance(objective, dict):
                skipped['objectives'] += 1
                continue
            yield Fact('objective', 'quest', quest, int(index), build, _count(objective.get('sources')), _capped(objective))


def _eglink_turn_ins(build, dataset, skipped):
    for key, seen in _records(dataset, 'quests'):
        quest = _id(key)
        if quest is None or not isinstance(seen, list):
            skipped['turn_ins'] += 1
            continue
        seen = [s for s in seen if isinstance(s, dict)]
        yield Fact('turn_in', 'quest', quest, 0, build, max([_count(s.get('sources')) for s in seen] or [0]), {'seen': seen})


TEXT_MOMENTS = ('accept', 'progress', 'complete')
MAX_WORDINGS = 12


def _eglink_texts(build, dataset, skipped):
    """What a quest's NPC said, per moment: [{'text', 'sources', 'times', 'template'}], the most seen first. `template`
    is 'questCache' for a text read from the client's quest cache and absent for one read in the quest's window."""
    for key, said in _records(dataset, 'quests'):
        quest = _id(key)
        if quest is None or not isinstance(said, dict):
            skipped['texts.enUS'] += 1
            continue
        data = {}
        for moment in TEXT_MOMENTS:
            lines = [line for line in said.get(moment) or [] if isinstance(line, dict) and isinstance(line.get('text'), str) and line['text'].strip()] \
                if isinstance(said.get(moment), list) else []
            lines.sort(key=lambda line: (-_count(line.get('times')), line['text']))
            if lines:
                data[moment] = [dict({'text': line['text'], 'sources': _count(line.get('sources')), 'times': _count(line.get('times'))},
                                     **({'template': str(line['template'])[:32]} if line.get('template') else {})) for line in lines[:MAX_WORDINGS]]
        if data:
            yield Fact('text', 'quest', quest, 0, build, max(line['sources'] for lines in data.values() for line in lines), data)


EGLINK_READERS = {
    'npcs': _eglink_npcs, 'creatures': _eglink_creatures, 'vendors': _eglink_vendors, 'trainers': _eglink_trainers, 'loot': _eglink_loot,
    'quests.enUS': _eglink_records('quest', 'quest', 'quests', 'quests.enUS'),
    'creature_details.enUS': _eglink_records('creature', 'npc', 'creatures', 'creature_details.enUS'),
    'object_details.enUS': _eglink_records('object', 'object', 'objects', 'object_details.enUS'),
    'objectives': _eglink_objectives, 'turn_ins': _eglink_turn_ins, 'texts.enUS': _eglink_texts,
}


def eglink(folder, skipped=None):
    """The facts of an EG Link download: `folder` holds one sub-folder per client build with its dataset files
    (<build>/<dataset>.json). `skipped` (a Counter) receives, per dataset, how many records could not be read.
    A file that is not JSON stops the reading (SourceError): it is a broken download, to delete and fetch again."""
    skipped = collections.Counter() if skipped is None else skipped
    builds = sorted((int(VERSION.fullmatch(name).group(1)), name) for name in os.listdir(folder) if VERSION.fullmatch(name)) if os.path.isdir(folder) else []
    for build, name in builds:
        for dataset, read in EGLINK_READERS.items():
            path = os.path.join(folder, name, dataset + '.json')
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding='utf-8') as handle:
                    content = json.load(handle)
            except (ValueError, OSError) as error:
                raise SourceError(f'{path} cannot be read ({error}): delete it and run again') from None
            yield from read(build, _dict(content), skipped)


def http_bytes(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_eglink(commit, folder, fetch=http_bytes, log=lambda message: None):
    """Downloads the datasets of every WoW Forever build of an EG Link commit into `folder` (<build>/<dataset>.json),
    skipping the files already there. Returns how many files it downloaded. The folder is the one the website's own
    EG Link import keeps, so each file is fetched once for both. A file is kept only once it is whole."""
    if not COMMIT.fullmatch(commit or ''):
        raise SourceError(f'EG Link is pinned by a commit, not {commit!r}')
    base = f'https://raw.githubusercontent.com/{EGLINK_REPO}/{commit}/data'
    try:
        builds = _dict(_dict(_dict(json.loads(fetch(f'{base}/index.json'))).get('products')).get(EGLINK_PRODUCT))
        downloaded = 0
        for build in sorted(builds):
            if not VERSION.fullmatch(build) or not isinstance(builds[build], dict):      # a name we did not expect never becomes a path
                continue
            for dataset in EGLINK_DATASETS:
                path = os.path.join(folder, build, dataset + '.json')
                if dataset not in builds[build] or os.path.isfile(path):
                    continue
                body = fetch(f'{base}/{EGLINK_PRODUCT}/{build}/{dataset}.json')
                json.loads(body)                                    # a download cut short is not kept
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + '.part', 'wb') as handle:
                    handle.write(body)
                os.replace(path + '.part', path)
                downloaded += 1
            log(f'EG Link {build}')
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise SourceError(f'EG Link could not be downloaded ({type(error).__name__}: {error})') from None
    return downloaded


# ------------------------------------------------------------------ QuestieDB
# QuestieDB's Forever data is the Classic database with its coordinates converted, plus corrections. Only the
# corrections say something about Forever, and each kind says it with another weight, so a fact names its part:
#   trace      what players' QuestieTrace recordings showed on live Forever
#   generated  the reviewed delta QuestieDB generates for Forever (new quests, NPCs, items; changed levels)
#   fix        a correction written by hand
#   dynamic:x  a hand correction that depends on the player: x is the table it stands in (questFixesHorde ...)
# The converted Classic base is not read: it is what Classic had, not what anybody saw in Forever.
QUESTIE_REPO = 'Questie/QuestieDB'
QUESTIE_FOLDER = 'src/corrections/Forever'
QUESTIE_FILES = collections.OrderedDict(
    (f'{QUESTIE_FOLDER}/{folder}forever{name}.lua', (entity, part))
    for part, folder, names in (('fix', '', ('QuestFixes', 'NPCFixes', 'ObjectFixes', 'ItemFixes')),
                                ('generated', 'generated/', ('BaseQuest', 'BaseNpc', 'BaseObject', 'BaseItem')),
                                ('trace', 'traces/', ('QuestTraces', 'NpcTraces', 'ObjectTraces', 'ItemTraces')))
    for name, entity in zip(names, ('quest', 'npc', 'object', 'item')))
# field (and field_add) of an entity: the facts it states, as (kind, the entity is the subject?, the other side's kind
# per position when the value is a list of lists, else the other side's kind)
QUESTIE_RELATIONS = {
    'quest': {'startedBy': ('gives', False, ('npc', 'object', 'item')), 'finishedBy': ('takes', False, ('npc', 'object'))},
    'npc': {'questStarts': ('gives', True, 'quest'), 'questEnds': ('takes', True, 'quest')},
    'object': {'questStarts': ('gives', True, 'quest'), 'questEnds': ('takes', True, 'quest')},
    'item': {'npcDrops': ('drops', False, 'npc'), 'objectDrops': ('drops', False, 'object'), 'itemDrops': ('drops', False, 'item'),
             'vendors': ('sells', False, 'npc'), 'startQuest': ('gives', True, 'quest')},
}


def _ids(value, skipped, name):
    """The ids of a Lua list of ids (or of one id). Only whole numbers are ids: anything else, and a value that is
    not a list, is counted and left out."""
    if isinstance(value, dict) and not value:        # {} reads as an empty table: no id
        return []
    if isinstance(value, dict):
        skipped[name] += 1
        return []
    out = []
    for one in (value if isinstance(value, list) else [value]):
        if one is None:
            continue
        if isinstance(one, int) and not isinstance(one, bool) and _id(one) is not None:
            out.append(one)
        else:
            skipped[name] += 1
    return out


def questie(folder, skipped=None):
    """The facts of a QuestieDB download (`folder` holds the repository's files under their own paths).

    Who gives and takes a quest, what drops and sells an item, each with the parts that say it and the field that
    said it ({'parts': {'trace': ['npc.questStarts_add'], 'generated': ['quest.startedBy']}}); and each entity's
    whole correction as an `entry` fact, in QuestieDB's own field names. `samples` is 1 when players' recordings
    (trace) state the fact, else 0. A fact is not tied to a client build (build 0). A `_remove` correction, and a
    plain empty list (which means "none"), stay in the entry and give no fact: nothing here says that something is
    not so. A plain list of a hand fix replaces the generated one in QuestieDB: rules that need that read the entries."""
    skipped = collections.Counter() if skipped is None else skipped
    relations, entries = collections.OrderedDict(), collections.OrderedDict()
    for path, (entity, part) in QUESTIE_FILES.items():
        name = os.path.basename(path)
        try:
            with open(os.path.join(folder, path), encoding='utf-8') as handle:
                tables = luadata.tables(handle.read())
        except (OSError, ValueError) as error:
            raise SourceError(f'{os.path.join(folder, path)} cannot be read ({error}): delete it and run again') from None
        # a table whose ids happen to be 1, 2, 3 ... comes back from the parser as a list
        found = {function: ({str(i): entry for i, entry in enumerate(table, 1)} if isinstance(table, list) else table)
                 for function, table in tables.items() if ':' in function and isinstance(table, (dict, list))}     # the tables of its functions
        if tables.get('_skipped') or not found:
            raise SourceError(f"{path} is not written the way this reader knows ({'; '.join(tables.get('_skipped') or ['no table found'])[:200]})")
        for function, table in found.items():
            said_by = part if 'Dynamic' not in function else 'dynamic:' + function.partition('/')[2] if '/' in function else 'dynamic'
            for key, entry in table.items():
                subject = _id(key)
                if subject is None or not isinstance(entry, dict):
                    skipped[name] += 1
                    continue
                entries.setdefault((entity, subject), {}).setdefault(said_by, {}).update(entry)
                for field, (kind, entity_is_subject, other) in QUESTIE_RELATIONS[entity].items():
                    for stated in (field, field + '_add'):
                        if entry.get(stated) is None:
                            continue
                        if isinstance(other, tuple):          # {creatures, objects, items}: a list per kind of thing
                            lists = [] if entry[stated] == {} else entry[stated] if isinstance(entry[stated], list) else None     # {}: none
                            if lists is None or len(lists) > len(other) or not all(ids is None or isinstance(ids, (list, dict)) for ids in lists):
                                skipped[name] += 1            # another shape than the one known: not guessed at
                                continue
                            pairs = [(other[i], one) for i, ids in enumerate(lists) for one in _ids(ids, skipped, name)]
                        else:
                            pairs = [(other, one) for one in _ids(entry[stated], skipped, name)]
                        for other_kind, other_id in pairs:
                            fact = (kind, entity, subject, other_id) if entity_is_subject else (kind, other_kind, other_id, subject)
                            said = relations.setdefault(fact, {}).setdefault(said_by, [])
                            if f'{entity}.{stated}' not in said:
                                said.append(f'{entity}.{stated}')
    for (kind, subject_kind, subject, other), parts in relations.items():
        yield Fact(kind, subject_kind, subject, other, 0, int('trace' in parts), {'parts': parts})
    for (entity, subject), parts in entries.items():
        yield Fact('entry', entity, subject, 0, 0, int('trace' in parts), {'parts': parts})


def fetch_questie(commit, folder, fetch=http_bytes, log=lambda message: None):
    """Downloads QuestieDB's Forever correction files of a commit into `folder`, under their own paths, skipping
    the ones already there. Returns how many it downloaded."""
    if not COMMIT.fullmatch(commit or ''):
        raise SourceError(f'QuestieDB is pinned by a commit, not {commit!r}')
    downloaded = 0
    try:
        for path in QUESTIE_FILES:
            target = os.path.join(folder, path)
            if os.path.isfile(target):
                continue
            try:
                body = fetch(f'https://raw.githubusercontent.com/{QUESTIE_REPO}/{commit}/{path}')
            except (OSError, http.client.HTTPException) as error:
                raise ValueError(f'{path}: {type(error).__name__}: {error}') from None
            read = luadata.tables(body.decode('utf-8', 'replace'))  # kept only when it reads: no error page, no cut download
            if read.get('_skipped') or not any(':' in function for function in read):
                raise ValueError(f"{path} does not read as a corrections file ({'; '.join(read.get('_skipped') or ['no table'])[:160]})")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target + '.part', 'wb') as handle:
                handle.write(body)
            os.replace(target + '.part', target)
            downloaded += 1
            log(f'QuestieDB {os.path.basename(path)}')
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise SourceError(f'QuestieDB could not be downloaded ({error})') from None
    return downloaded


# ------------------------------------------------------------------ RestedXP guides
# RXPGuides is a levelling guide written by hand: steps a player follows. A step that names one NPC by its id and
# has the player accept or turn in a quest there states who gives or takes that quest:
#     step
#         .goto 2521,42.07,23.49
#         .turnin 92460 >>Turn in Coming of Age
#         .target Rorian the Dayseeker::251361
#         .accept 92461 >>Accept Harmony in Balance
# Nothing else is read. A step that names its NPC by name only, or names several, states nothing a reader may use
# without guessing; a `.goto` is where the player should stand, not where something spawns. Steps about quests the
# Classic Era client already has are left out: most are the Classic guide's own lines carried over, not something
# written about Forever.
RXP_REPO = 'RestedXP/RXPGuides'
RXP_LIST = 'Guides/GuideList-forever.xml'
RXP_PATH = re.compile(r'Guides/forever/(?:[\w.+ -]+/)?[\w.+ -]+\.lua')
RXP_GUIDE = re.compile(r'RegisterGuide\(\s*\[(=*)\[(.*?)\]\1\]', re.S)
RXP_QUEST = re.compile(r'\.(accept|turnin)\s+(-?\d+)')
RXP_STEPS = 10
BASELINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'baseline', 'classic-era.json')


def classic_quests(path=BASELINE):
    """The quest ids of the Classic Era client, Season of Discovery included (tools/baseline/classic-era.json)."""
    try:
        with open(path, encoding='utf-8') as handle:
            ranges = json.load(handle)['tables']['QuestV2']
    except (OSError, ValueError, KeyError) as error:
        raise SourceError(f'{path} cannot be read ({type(error).__name__}: {error})') from None
    return {quest for first, last in ranges for quest in range(first, last + 1)}


def rxp_steps(text):
    """(guide name, [step lines]) of every step of every guide in a file. Comments are dropped, also after a line's
    own words. A file with a guide this reader cannot find the end of is refused (SourceError)."""
    blocks = list(RXP_GUIDE.finditer(text))
    if len(blocks) != text.count('RegisterGuide('):
        raise SourceError(f"{text.count('RegisterGuide(')} guides begin and {len(blocks)} can be read to their end")
    for block in blocks:
        name, step = '', None
        for raw in block.group(2).split('\n'):
            line = raw.split('--', 1)[0].strip()
            if not line:
                continue
            if step is None and line.startswith('#name '):
                name = line[6:].strip()
            if re.match(r'step\b', line):
                if step:
                    yield name, step
                step = [line]
            elif step is not None:
                step.append(line)
        if step:
            yield name, step


def rxpguides(folder, skipped=None, known=None):
    """The facts of a RestedXP guides download (`folder` holds the repository's Forever guide files under their own
    paths): `gives` and `takes`, from the steps that name exactly one NPC, by id, and accept or turn in a quest
    there. Each fact keeps the steps that state it (guide, the NPC's name as written, where the step sends the
    player last, the step's own filter and tags, the line's own filter), at most RXP_STEPS of them. `samples` is 0:
    a guide is written, not recorded. `known` is the set of quest ids the Classic Era client has (read from
    tools/baseline when not given): steps about those are not read.

    Not read, because who gives the quest is then not stated: a step that names several things or one by name only,
    a step the authors switched off (`step << skip`). Counted as left out: a step whose one target is something to
    click (`RXP_PICK_`: an object, which a `.target` line does not tell from an NPC), and a quest id that is not a
    plain number (`.turnin -123`)."""
    skipped = collections.Counter() if skipped is None else skipped
    known = classic_quests() if known is None else known
    root = os.path.join(folder, 'Guides', 'forever')
    files = sorted(os.path.join(base, name) for base, _dirs, names in os.walk(root) for name in names if name.endswith('.lua'))
    stated = collections.OrderedDict()
    for path in files:
        label = os.path.relpath(path, root).replace(os.sep, '/')
        try:
            with open(path, encoding='utf-8') as handle:
                steps = list(rxp_steps(handle.read()))
        except (OSError, ValueError) as error:
            raise SourceError(f'{path} cannot be read ({error}): delete it and run again') from None
        except SourceError as error:
            raise SourceError(f'{path}: {error}: delete it and run again') from None
        if not steps:
            raise SourceError(f'{path} holds no guide: delete it and run again')
        for guide, step in steps:
            targets = [re.split(r'\s', line, maxsplit=1)[1].split('<<')[0].strip() for line in step if re.match(r'\.target\s', line)]
            ids = {m.group(1) for m in (re.search(r'::(\d+)$', target) for target in targets) if m}
            quests = [(m.group(1), int(m.group(2)), line) for line in step for m in [RXP_QUEST.match(line)] if m]
            switched_off = '<<' in step[0] and 'skip' in step[0].split('<<', 1)[1].split()
            if not quests or not targets or switched_off:
                continue
            if len(ids) != 1 or any(not re.search(r'::\d+$', target) for target in targets):
                continue                                   # several things, or one named by name only: who is not stated
            only_id = next(iter(ids))
            if any(re.search(r'RXP_PICK_[^|]*::' + only_id + r'\b', line) for line in step):
                skipped[label] += 1                        # something to click: an object, not an NPC
                continue
            npc = _id(only_id)
            said = {'guide': f'{label}: {guide}' if guide else label, 'npc': targets[0].rsplit('::', 1)[0].lstrip('+').strip()}
            where = [re.split(r'\s', line, maxsplit=1)[1].split('<<')[0].strip() for line in step if re.match(r'\.goto\s', line)]
            if where:
                said['goto'] = where[-1]                   # the earlier ones are the way there
            if '<<' in step[0]:
                said['for'] = step[0].split('<<', 1)[1].strip()
            tags = [line for line in step if re.match(r'#(season|era|som|sod)\b', line)]
            if tags:
                said['tags'] = tags
            for action, quest, line in quests:
                if npc is None or _id(quest) is None:      # `.turnin -123` and the like: not a plain quest id
                    skipped[label] += 1
                    continue
                if quest in known:
                    continue
                entry = dict(said, **({'only': line.split('<<', 1)[1].strip()} if '<<' in line else {}))
                kept = stated.setdefault(('gives' if action == 'accept' else 'takes', npc, quest), [])
                if entry not in kept and len(kept) < RXP_STEPS:
                    kept.append(entry)
    for (kind, npc, quest), kept in stated.items():
        yield Fact(kind, 'npc', npc, quest, 0, 0, {'steps': kept})


def fetch_rxpguides(commit, folder, fetch=http_bytes, log=lambda message: None):
    """Downloads the Forever guide files of a RestedXP guides commit into `folder`, under their own paths, skipping
    the ones already there. The addon's own list (GuideList-forever.xml) says which they are. Returns how many it
    downloaded."""
    if not COMMIT.fullmatch(commit or ''):
        raise SourceError(f'the RestedXP guides are pinned by a commit, not {commit!r}')
    base = f'https://raw.githubusercontent.com/{RXP_REPO}/{commit}'
    downloaded = 0
    try:
        listing = fetch(f'{base}/{RXP_LIST}').decode('utf-8', 'replace')
        paths = sorted(set(re.findall(r'file="(Guides/forever/[^"]+)"', re.sub(r'<!--.*?-->', '', listing, flags=re.S))))
        if not paths:
            raise ValueError(f'{RXP_LIST} lists no Forever guide')
        for path in paths:
            if not RXP_PATH.fullmatch(path) or '..' in path:          # a name we did not expect never becomes a path
                raise ValueError(f'{RXP_LIST} lists a path this reader does not follow: {path[:80]}')
            target = os.path.join(folder, path)
            if os.path.isfile(target):
                continue
            try:
                body = fetch(f'{base}/{path}'.replace(' ', '%20'))
            except (OSError, http.client.HTTPException) as error:
                raise ValueError(f'{path}: {type(error).__name__}: {error}') from None
            if b'RegisterGuide' not in body or not body.rstrip().endswith(b']])'):      # every guide file ends its last guide so
                raise ValueError(f'{path} does not read as a guide file')
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target + '.part', 'wb') as handle:
                handle.write(body)
            os.replace(target + '.part', target)
            downloaded += 1
            log(f'RestedXP {os.path.basename(path)}')
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise SourceError(f'the RestedXP guides could not be downloaded ({error})') from None
    return downloaded


READERS = {'eglink': eglink, 'questie': questie, 'rxpguides': rxpguides}
FETCHERS = {'eglink': fetch_eglink, 'questie': fetch_questie, 'rxpguides': fetch_rxpguides}


# ------------------------------------------------------------------ storing
def sql_value(value):
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r').replace('\0', '\\0') + "'"


def check(fact):
    """A fact fit to store, or None."""
    if fact.kind not in KINDS or fact.subject_kind not in SUBJECTS:
        return None
    numbers = (fact.subject, fact.object, fact.build, fact.samples)
    if not all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= MAX_ID for n in numbers) or not fact.subject:
        return None
    return fact


def write_sql(path, source, pin, licence, allowed, facts, skipped=None, now='NOW()', batch=400):
    """Writes the statements that replace a source's facts with `facts`, all or nothing. Returns {kind: count}.

    `skipped` is the Counter the reader fills while `facts` is read: its total, plus the facts not fit to store, is
    recorded as left out. A fact repeated for the same key keeps its last copy. The text of a fact is written as
    ASCII JSON, and the file sets the session's sql_mode, so no character and no server setting can change how its
    strings end."""
    skipped = collections.Counter() if skipped is None else skipped
    counts, unfit = collections.Counter(), 0
    head = f'INSERT INTO {FACTS} (source, kind, subject_kind, subject, object, build, samples, data) VALUES\n'
    tail = '\nON DUPLICATE KEY UPDATE samples = VALUES(samples), data = VALUES(data);\n'
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='ascii', newline='\n') as out:
        out.write("SET NAMES utf8mb4;\nSET SESSION sql_mode = 'STRICT_ALL_TABLES';\n" + ';\n'.join(SCHEMA) + ';\nSTART TRANSACTION;\n')
        out.write(f'DELETE FROM {FACTS} WHERE source = {sql_value(source)};\n')
        rows = []
        for fact in facts:
            if check(fact) is None:
                unfit += 1
                continue
            counts[fact.kind] += 1
            data = json.dumps(fact.data, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
            rows.append('(' + ', '.join(sql_value(v) for v in (source, fact.kind, fact.subject_kind, fact.subject, fact.object, fact.build,
                                                                fact.samples, data)) + ')')
            if len(rows) >= batch:
                out.write(head + ',\n'.join(rows) + tail)
                rows = []
        if rows:
            out.write(head + ',\n'.join(rows) + tail)
        out.write(f'REPLACE INTO {SOURCES} (source, pin, licence, allowed, facts, left_out, loaded_at) VALUES ({sql_value(source)}, {sql_value(pin)}, '
                  f'{sql_value(licence)}, {sql_value(allowed)}, (SELECT COUNT(*) FROM {FACTS} WHERE source = {sql_value(source)}), '
                  f'{unfit + sum(skipped.values())}, {now});\n')
        out.write('COMMIT;\n')
    return dict(counts)


def summary(db, database='tracker'):
    """([(source, pin, licence, allowed, facts, left out, loaded at)], [(source, kind, facts, subjects, first build,
    last build)]) of what is stored; two empty lists before anything was loaded."""
    if not db.query(f"SHOW TABLES LIKE '{FACTS}'", database):
        return [], []
    sources = [(r['source'], r['pin'], r['licence'], r['allowed'], int(r['facts']), int(r['left_out']), r['loaded_at'])
               for r in db.query(f'SELECT * FROM {SOURCES} ORDER BY source', database)]
    kinds = [(r['source'], r['kind'], int(r['n']), int(r['s']), int(r['lo']), int(r['hi']))
             for r in db.query(f'SELECT source, kind, COUNT(*) n, COUNT(DISTINCT subject_kind, subject) s, MIN(build) lo, MAX(build) hi '
                               f'FROM {FACTS} GROUP BY source, kind ORDER BY source, kind', database)]
    return sources, kinds
