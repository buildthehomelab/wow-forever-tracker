"""Gathering: what the content still to come needs, fetched and listed before it is built (docs/GATHER.md).

Each release phase not open yet (docs/PHASES.md) brings quests, items, creatures and objects the server may not have.
Their rows can wait until the phase opens; their data should not, because a source can lose it or take days to read
(Wowhead's pages come one every 10 to 30 seconds). So after each analysis this module lists, per phase, what each
thing needs and which sources already hold it, and names the pages and answers still to fetch:

- **quests**: the record (EG Link), who gives and takes it (QuestieDB, EG Link, Icy Veins, Wowhead's quest page), what
  its objectives ask (EG Link: creatures, objects, items);
- **creatures and objects** those quests name, and the ones a phase's items drop from, when the server has no template
  or no spawn: a template (EG Link's creature or object record, Icy Veins' entity) and a place (EG Link sightings, Icy
  Veins' addon points, Wowhead's map pins), a model (Wowhead's page);
- **items**: where they come from (Icy Veins' dropped by / sold by, Wowhead's item page tabs).

The open phase is listed too, as "now": the official quests the server has no record of or no giver or ender for, and
the creatures, objects and items that open quests wait for. Nothing is written into the world here and nothing is guessed: a thing no source
names stays without it.

What it fetches itself: the EG Link and QuestieDB files of the commits the website's imports already downloaded
(data/eglink/<commit>, data/questie/<commit>), the datasets those imports do not read. Wowhead's pages are read by the
browser crawl (app/wowheadpages.php queues `wowhead`), Icy Veins' answers by Import Icy Veins (app/icyveins.php asks
`icyveins` first). The result is data/gather.json, read by The Forge > Later (app/pages/admin/later.php).
"""
import collections
import json
import os
import re
import time

from . import facts, icyveins, phases as phase_rules, sqlio, summons
from .config import DATA
from .server import log

FILE = os.path.join(DATA, 'gather.json')
NOW = 'now'
# the EG Link datasets this reads: quest records and objectives, who offers and takes them, creatures seen, records
EGLINK_SETS = ('quests.enUS', 'npcs', 'creatures', 'creature_details.enUS', 'object_details.enUS')
# EG Link's objective types, as the kinds here
OBJECTIVE_KINDS = {'monster': 'npc', 'gameObject': 'object', 'object': 'object', 'item': 'item'}
QUICK_LINK = re.compile(r'/forever/(npc|object|item)=(\d+)')
CHECK_SPAWN = re.compile(r'\b(creature|object) (\d+) not spawned')
CHECK_ITEM = re.compile(r'\bitem (\d+) not obtainable')
# an item made by a spell nothing on the server casts: ft.rules names the spell(s) ('recipe that cannot be learned
# (spell 2838, 2840)'); their Wowhead pages say who casts them on live
CHECK_SPELL = re.compile(r'recipe that cannot be learned \(spell ([0-9, ]+)')
# the checks of a quest that ask for who gives or takes it: an open quest failing one is listed, so the crawl reads its
# Wowhead page and Import Icy Veins asks for it (a Craftsman's Writ with no ender, a quest whose giver nobody spawned)
GIVER_CHECKS = ('starter', 'ender')
# the tabs of a creature's, object's or item's Wowhead page that place it or say where an item comes from
ITEM_TABS = phase_rules.WOWHEAD_SOURCE_TABS
NAMED_MAX = 5           # what a thing is needed for: the first few, the rest counted


# ------------------------------------------------------------------ the sources, as plain dicts (no database)

def newest_commit(root):
    """The commit folder under `root` the website's import read last (the newest), or None."""
    names = [n for n in (os.listdir(root) if os.path.isdir(root) else []) if facts.COMMIT.fullmatch(n)]
    return max(names, key=lambda n: os.path.getmtime(os.path.join(root, n))) if names else None


def compact(record):
    """What this module reads of a kept page, the rest dropped (a whole crawl is tens of thousands of npc pages): its
    status, time and version, Quick Facts lines that name a start or an end, the rows' ids of the tabs read here, how
    many map pins, whether it has a model."""
    out = {k: record[k] for k in ('id', 'fetched', 'v', 'status') if k in record}
    quick = [line for line in record.get('quick') or [] if isinstance(line, str) and line.startswith(('Start:', 'End:'))]
    if quick:
        out['quick'] = quick
    tabs = {}
    for name, tab in (record.get('tabs') or {}).items() if isinstance(record.get('tabs'), dict) else ():
        rows = (tab or {}).get('rows') if isinstance(tab, dict) else None
        if rows and (name in ITEM_TABS or name in ('starts', 'ends')):
            tabs[name] = {'rows': [{'id': r['id']} for r in rows if isinstance(r, dict) and isinstance(r.get('id'), int)]}
    if tabs:
        out['tabs'] = tabs
    where = record.get('map')
    if isinstance(where, dict):
        out['map'] = {str(zone): [{'coords': [0] * sum(len(spot.get('coords') or []) for spot in spots if isinstance(spot, dict))}]
                      for zone, spots in where.items() if isinstance(spots, list)}
    if record.get('model'):
        out['model'] = True
    return out


def wowhead_pages(kinds, folders=None):
    """{kind: {id: record}}: the newest kept page of each id ('fetched' decides) of these kinds, across the folders,
    each as compact() keeps it."""
    out = {kind: {} for kind in kinds}
    for folder in folders if folders is not None else phase_rules.wowhead_page_folders():
        for kind in kinds:
            try:
                handle = open(os.path.join(folder, f'{kind}.jsonl'), encoding='utf-8')
            except OSError:
                continue
            with handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict) or not isinstance(record.get('id'), int):
                        continue
                    kept = out[kind].get(record['id'])
                    if kept is None or (record.get('fetched') or 0) >= (kept.get('fetched') or 0):
                        out[kind][record['id']] = compact(record)
    return out


def wowhead_listed(folders=None):
    """{('npc'|'object', id): [zone ids]} from Wowhead's Forever list pages (the rows' `location`)."""
    out = {}
    for folder in folders if folders is not None else phase_rules.wowhead_page_folders():
        try:
            handle = open(os.path.join(folder, 'forever-list.jsonl'), encoding='utf-8')
        except OSError:
            continue
        with handle:
            for line in handle:
                if '"location"' not in line:
                    continue
                try:
                    page = json.loads(line)
                except ValueError:
                    continue
                kind = {'npcs': 'npc', 'objects': 'object'}.get(str(page.get('query') or '').split('?')[0])
                for row in page.get('rows') or [] if kind else []:
                    zones = row.get('location') if isinstance(row, dict) else None
                    if isinstance(row.get('id'), int) and isinstance(zones, list):
                        out[(kind, row['id'])] = [z for z in zones if isinstance(z, int)]
    return out


class Sources:
    """What each source says, read once: relations {quest: {'gives'|'takes': {(kind, id): {source}}}}, quest records,
    objectives {quest: {(kind, id)}}, EG Link creature and object records and sightings, Wowhead pages, Icy Veins."""

    def __init__(self):
        self.relations = collections.defaultdict(lambda: {'gives': collections.defaultdict(set), 'takes': collections.defaultdict(set)})
        self.records = {}                       # quest -> source of its record
        self.objectives = collections.defaultdict(set)
        self.creature_records, self.object_records = set(), set()
        self.seen = collections.Counter()        # npc -> EG Link sightings with a position
        self.wowhead = {'quest': {}, 'npc': {}, 'object': {}, 'item': {}}
        self.listed = {}
        self.icy = icyveins.cached              # (kind, id) -> answer or None
        self.pins = {}

    def relate(self, quest, way, kind, entry, source):
        if kind == 'go':
            kind = 'object'
        if kind in ('npc', 'object', 'item') and entry:
            self.relations[quest][way][(kind, int(entry))].add(source)

    def read_eglink(self, records):
        for fact in records:
            if fact.kind == 'quest':
                self.records[fact.subject] = 'eglink'
                for objective in fact.data.get('objectives') or []:
                    kind = OBJECTIVE_KINDS.get(str(objective.get('type')))
                    if kind and isinstance(objective.get('objectId'), int) and objective['objectId'] > 0:
                        self.objectives[fact.subject].add((kind, objective['objectId']))
            elif fact.kind in ('gives', 'takes'):
                self.relate(fact.object, fact.kind, fact.subject_kind, fact.subject, 'eglink')
            elif fact.kind == 'creature':
                self.creature_records.add(fact.subject)
            elif fact.kind == 'object':
                self.object_records.add(fact.subject)
            elif fact.kind == 'seen' and fact.subject_kind == 'npc' and fact.data.get('positions'):
                self.seen[fact.subject] += len(fact.data['positions'])

    def read_questie(self, records):
        for fact in records:
            if fact.kind in ('gives', 'takes') and fact.subject_kind in ('npc', 'object', 'item'):
                self.relate(fact.object, fact.kind, fact.subject_kind, fact.subject, 'questie')

    def read_wowhead(self, pages, listed=None):
        self.wowhead.update({kind: pages.get(kind, {}) for kind in self.wowhead})
        self.listed = listed or {}
        for quest, page in self.wowhead['quest'].items():
            for line in page.get('quick') or []:
                way = 'gives' if line.startswith('Start:') else 'takes' if line.startswith('End:') else None
                for kind, entry in QUICK_LINK.findall(line) if way else ():
                    self.relate(quest, way, kind, int(entry), 'wowhead')
        for kind in ('npc', 'object', 'item'):
            for entry, page in self.wowhead[kind].items():
                for tab, way in (('starts', 'gives'), ('ends', 'takes')):
                    for row in ((page.get('tabs') or {}).get(tab) or {}).get('rows') or []:
                        if isinstance(row.get('id'), int):
                            self.relate(row['id'], way, kind, entry, 'wowhead')

    def icyveins_quest(self, quest):
        """Reads a quest's Icy Veins answer into the relations; True when the mirror has one."""
        data = self.icy('quest', quest)
        if not data or data.get('missing'):
            return False
        rel = data.get('relations') or {}
        for g in rel.get('addon_givers') or []:
            kind, entry = ('npc', g.get('npc_id')) if g.get('npc_id') else ('object', g.get('gameobject_id'))
            for way, flag in (('gives', 'starts'), ('takes', 'ends')):
                if g.get(flag) and entry:
                    self.relate(quest, way, kind, int(entry), 'icyveins')
        for x in rel.get('started_by_items') or []:
            if x.get('id'):
                self.relate(quest, 'gives', 'item', int(x['id']), 'icyveins')
        for x in rel.get('quest_items') or []:
            if x.get('id'):
                self.objectives[quest].add(('item', int(x['id'])))
        return True


# ------------------------------------------------------------------ the work list (pure: tested without a database)

def page_state(page):
    """'' not read, 'missing' Wowhead has no page, 'ok' read."""
    return '' if not page else 'missing' if page.get('status') == 'missing' else 'ok'


def icy_state(data):
    return '' if not data else 'missing' if data.get('missing') else 'ok'


def build(targets, server, src, phase_list):
    """The work list. targets: {phase key: {'quest': {id: entity}, 'item': {id: entity}, 'npc': {id: why},
    'object': {id: why}}}, an entity being {'name', 'status'}; server: {'quest', 'npc_template', 'npc_spawned',
    'object_template', 'object_spawned': sets}; src: Sources; phase_list: [{'key', 'name', 'opens'}] in release order
    (the open phase NOW comes first). Returns the dict written to data/gather.json without its header."""
    out_phases, wowhead, icy = [], {}, {}
    for phase in phase_list:
        key = phase['key']
        want = targets.get(key) or {}
        quests, items = [], []
        npcs, objects = {}, {}          # id -> [what it is needed for]

        def need(kind, entry, why):
            if kind == 'item':
                want.setdefault('item', {}).setdefault(entry, {'name': '', 'status': '', 'for': []})
                want['item'][entry].setdefault('for', []).append(why)
                return
            book, template, spawned = (npcs, server['npc_template'], server['npc_spawned']) if kind == 'npc' else \
                (objects, server['object_template'], server['object_spawned'])
            if entry in template and entry in spawned:
                return
            book.setdefault(entry, []).extend(why if isinstance(why, list) else [why])

        for kind in ('npc', 'object'):
            for entry, why in (want.get(kind) or {}).items():
                need(kind, entry, why)
        for quest, entity in sorted((want.get('quest') or {}).items()):
            icy_seen = src.icyveins_quest(quest)
            rel = src.relations.get(quest) or {'gives': {}, 'takes': {}}
            row = {'id': quest, 'name': entity.get('name', ''), 'status': entity.get('status', ''), 'server': quest in server['quest'],
                   'record': src.records.get(quest, ''), 'icyveins': 'ok' if icy_seen else '', 'wowhead': page_state(src.wowhead['quest'].get(quest))}
            for way in ('gives', 'takes'):
                row[way] = {f'{k}:{e}': sorted(s) for (k, e), s in sorted(rel[way].items())}
            row['objectives'] = [f'{k}:{e}' for k, e in sorted(src.objectives.get(quest, ()))]
            for k, e in list(rel['gives']) + list(rel['takes']) + sorted(src.objectives.get(quest, ())):
                need(k, e, f'quest:{quest}')
            row['ready'] = bool((row['server'] or row['record']) and row['gives'] and row['takes'])
            quests.append(row)
        for item, entity in sorted((want.get('item') or {}).items()):
            data = src.icy('item', item)
            rel = (data or {}).get('relations') or {}
            page = src.wowhead['item'].get(item)
            tabs = sorted(t for t in ITEM_TABS if (((page or {}).get('tabs') or {}).get(t) or {}).get('rows'))
            row = {'id': item, 'name': entity.get('name', ''), 'status': entity.get('status', ''), 'for': sorted(set(entity.get('for') or []))[:NAMED_MAX],
                   'icyveins': icy_state(data), 'icy_dropped_by': len(rel.get('addon_dropped_by') or []), 'icy_sold_by': len(rel.get('addon_sold_by') or []),
                   'wowhead': page_state(page), 'tabs': tabs}
            # the creatures and chests that drop it: their template and place are needed too
            for d in rel.get('addon_dropped_by') or []:
                if d.get('gameobject_id'):
                    need('object', int(d['gameobject_id']), f'item:{item}')
                elif d.get('npc_id'):
                    need('npc', int(d['npc_id']), f'item:{item}')
            for tab, kind in (('dropped-by', 'npc'), ('contained-in-object', 'object')):
                rows = (((page or {}).get('tabs') or {}).get(tab) or {}).get('rows') or []
                if len(rows) < 15:          # a world drop names every creature of a level range: not this item's own
                    for r in rows:
                        if isinstance(r.get('id'), int):
                            need(kind, r['id'], f'item:{item}')
            row['ready'] = bool(row['icy_dropped_by'] or row['icy_sold_by'] or tabs)
            items.append(row)

        def placed(kind, entry, why):
            icy_kind = 'npc' if kind == 'npc' else 'gameobject'
            data = src.icy(icy_kind, entry)
            points = len(((data or {}).get('relations') or {}).get('addon_points') or [])
            page = src.wowhead[kind].get(entry)
            pins = sum(len(spot.get('coords') or []) for spots in ((page or {}).get('map') or {}).values() if isinstance(spots, list)
                       for spot in spots if isinstance(spot, dict)) if isinstance((page or {}).get('map'), dict) else 0
            template = server['npc_template' if kind == 'npc' else 'object_template']
            record = entry in (src.creature_records if kind == 'npc' else src.object_records)
            seen = src.seen.get(entry, 0) if kind == 'npc' else 0
            row = {'id': entry, 'for': sorted(set(why))[:NAMED_MAX], 'needed_by': len(set(why)), 'template': entry in template,
                   'spawned': entry in server['npc_spawned' if kind == 'npc' else 'object_spawned'], 'eglink': record, 'eglink_seen': seen,
                   'icyveins': icy_state(data), 'icy_points': points, 'wowhead': page_state(page), 'pins': pins,
                   'model': bool((page or {}).get('model')), 'zones': src.listed.get((kind, entry), [])}
            row['ready'] = bool((row['template'] or record or row['icyveins'] == 'ok') and (row['spawned'] or seen or points or pins))
            return row

        npc_rows = [placed('npc', e, w) for e, w in sorted(npcs.items())]
        object_rows = [placed('object', e, w) for e, w in sorted(objects.items())]
        counts = {kind: {'all': len(rows), 'ready': sum(1 for r in rows if r['ready'])} for kind, rows in
                  (('quest', quests), ('item', items), ('npc', npc_rows), ('object', object_rows))}
        out_phases.append({'key': key, 'name': phase.get('name') or key, 'opens': phase.get('opens'), 'counts': counts,
                           'quests': quests, 'items': items, 'npcs': npc_rows, 'objects': object_rows})
        # the pages to read: the crawl skips those it holds and that are not due again (app/wowheadpages.php)
        wanted = {'quest': [r['id'] for r in quests if not r['server'] or not r['gives'] or not r['takes']],
                  'npc': [r['id'] for r in npc_rows], 'object': [r['id'] for r in object_rows],
                  'item': [r['id'] for r in items if not phase.get('wowhead_no_source')],
                  # the spells that make an item nothing here casts: their page names who casts them (ft.phases)
                  'spell': sorted(want.get('spell') or {})}
        wowhead[key] = {k: v for k, v in wanted.items() if v}
        for kind, rows in (('quest', quests), ('item', items), ('npc', npc_rows), ('gameobject', object_rows)):
            icy.setdefault(kind, [])
            icy[kind] += [r['id'] for r in rows if r['icyveins'] == '' and r['id'] not in icy[kind]]
    return {'phases': out_phases, 'wowhead': wowhead, 'icyveins': {k: v for k, v in icy.items() if v}}


# ------------------------------------------------------------------ the analysis' side: what each phase brings

def lacks_giver(checks):
    """Whether a quest's checks (ft_entities.checks, a JSON list of {'code', 'ok'}) fail on its giver or its ender."""
    try:
        listed = json.loads(checks) if checks else []
    except (TypeError, ValueError):
        return False
    if not isinstance(listed, list):
        return False
    return any(isinstance(c, dict) and c.get('code') in GIVER_CHECKS and c.get('ok') is False for c in listed)


def targets_from(rows, map_areas, listed):
    """{phase key: {'quest', 'item', 'npc', 'object'}} from ft_entities rows (type, id, name_en, status, phase key,
    checks text) of what is not ok, and the creatures and objects Wowhead's lists place in a phase's instances
    (map_areas: {phase key: {zone ids}}; listed: wowhead_listed())."""
    out = collections.defaultdict(lambda: {'quest': {}, 'item': {}, 'npc': {}, 'object': {}, 'spell': {}})
    for kind, entry, name, status, key, checks in rows:
        want = out[key]
        if kind == 'quest':
            if key != NOW or status == 'missing' or (status == 'partial' and lacks_giver(checks)):
                want['quest'][entry] = {'name': name, 'status': status}
            if status == 'partial':
                for what, other in CHECK_SPAWN.findall(checks or ''):
                    want['npc' if what == 'creature' else 'object'].setdefault(int(other), []).append(f'quest:{entry}')
                for other in CHECK_ITEM.findall(checks or ''):
                    want['item'].setdefault(int(other), {'name': '', 'status': '', 'for': []})['for'].append(f'quest:{entry}')
        elif kind == 'item' and key != NOW:
            want['item'].setdefault(entry, {'for': []}).update({'name': name, 'status': status})
        if kind == 'item' and status != 'ok':
            for listed in CHECK_SPELL.findall(checks or ''):
                for spell in re.findall(r'\d+', listed):
                    want['spell'].setdefault(int(spell), []).append(f'item:{entry}')
            # a caster Wowhead's spell page names and the realm has not spawned: its page places it
            for what, other in CHECK_SPAWN.findall(checks or ''):
                want['npc' if what == 'creature' else 'object'].setdefault(int(other), []).append(f'item:{entry}')
    for key, areas in map_areas.items():
        for (kind, entry), zones in listed.items():
            if areas & set(zones):
                out[key][kind].setdefault(entry, []).append('instance')
    return out


def run(content, phase_list, folders=None):
    """After the analysis was loaded: fetches the EG Link and QuestieDB datasets this needs, builds the work list and
    writes data/gather.json. Never stops the analysis: a source that cannot be read is said and left out."""
    started = time.time()
    keys = {n: p['key'] for n, p in enumerate(phase_list, 1)}
    rows = []
    # the open phase's items only when a spell nothing here casts makes them: their spell's page is wanted (CHECK_SPELL)
    for r in sqlio.query("SELECT type, id, name_en, status, phase, checks FROM ft_entities WHERE internal = 0 AND status <> 'ok' "
                         "AND (phase > 0 OR type = 'quest' OR (type = 'item' AND checks LIKE '%cannot be learned (spell %'))", 'tracker'):
        rows.append((r['type'], int(r['id']), r['name_en'] or '', r['status'], keys.get(int(r['phase'] or 0), NOW), r['checks'] or ''))
    src = Sources()
    said = {}
    eglink_root, questie_root = os.path.join(DATA, 'eglink'), os.path.join(DATA, 'questie')
    commit = newest_commit(eglink_root)
    if commit:
        folder = os.path.join(eglink_root, commit)
        try:
            facts.fetch_eglink(commit, folder, datasets=EGLINK_SETS)
        except facts.SourceError as error:
            log(f'later: {str(error).strip()}; the EG Link files already here are read')
        try:
            src.read_eglink(facts.eglink(folder, datasets=EGLINK_SETS))
            said['eglink'] = commit
        except facts.SourceError as error:
            log(f'later: EG Link not read ({str(error).strip()})')
    commit = newest_commit(questie_root)
    if commit:
        folder = os.path.join(questie_root, commit)
        try:
            facts.fetch_questie(commit, folder)
            src.read_questie(facts.questie(folder))
            said['questie'] = commit
        except facts.SourceError as error:
            log(f'later: QuestieDB not read ({str(error).strip()})')
    pages = wowhead_pages(('quest', 'npc', 'object', 'item'), folders)
    listed = wowhead_listed(folders)
    src.read_wowhead(pages, listed)
    said['wowhead_pages'] = sum(len(v) for v in pages.values())
    # the zones of each closed phase's instances, for the creatures Wowhead's lists place there
    map_phase = phase_rules.map_phases(phase_rules.load(), content) if phase_list else {}
    map_areas = collections.defaultdict(set)
    for map_id, number in map_phase.items():
        area = ((content.get('dungeon', {}).get(map_id) or {}).get('facts') or {}).get('area')
        if area and number in keys:
            map_areas[keys[number]].add(int(area))
    targets = targets_from(rows, map_areas, listed)
    ids = collections.defaultdict(set)
    for want in targets.values():
        for quest in want['quest']:
            ids['quest'].add(quest)
            for way in ('gives', 'takes'):
                for kind, entry in (src.relations.get(quest) or {}).get(way, {}):
                    ids[kind].add(entry)
            for kind, entry in src.objectives.get(quest, ()):
                ids[kind].add(entry)
        for kind in ('npc', 'object'):
            ids[kind] |= set(want[kind])
    # the items: the listed ones and those the listed quests start with or ask for (build() lists them too), whose
    # creatures and chests are looked up on the server like the rest
    for want in targets.values():
        for item in set(want['item']) | ids['item']:
            rel = (src.icy('item', item) or {}).get('relations') or {}
            for d in rel.get('addon_dropped_by') or []:
                if d.get('gameobject_id'):
                    ids['object'].add(int(d['gameobject_id']))
                elif d.get('npc_id'):
                    ids['npc'].add(int(d['npc_id']))
            page = src.wowhead['item'].get(item) or {}
            for tab, kind in (('dropped-by', 'npc'), ('contained-in-object', 'object')):
                ids[kind] |= {r['id'] for r in ((page.get('tabs') or {}).get(tab) or {}).get('rows') or [] if isinstance(r.get('id'), int)}
    server = {'quest': set(), 'npc_template': set(), 'npc_spawned': set(), 'object_template': set(), 'object_spawned': set()}
    for name, table, column, kind in (('quest', 'quest_template', 'ID', 'quest'), ('npc_template', 'creature_template', 'entry', 'npc'),
                                      ('npc_spawned', 'creature', 'id', 'npc'), ('object_template', 'gameobject_template', 'entry', 'object'),
                                      ('object_spawned', 'gameobject', 'id', 'object')):
        wanted = sorted(ids[kind])
        for start in range(0, len(wanted), 1000):
            chunk = ','.join(map(str, wanted[start:start + 1000]))
            server[name] |= {int(v) for v in sqlio.column(f'SELECT DISTINCT `{column}` FROM `{table}` WHERE `{column}` IN ({chunk})')}
    # what a script, a summon group or an event brings in needs no spawn row (Majordomo Executus and his Flamewakers,
    # Ragnaros, a raid boss's adds): counted as in the world, as the analysis and the locator count it (ft.summons)
    try:
        summoned_npc, summoned_go, _lists = summons.known()
        server['npc_spawned'] |= set(summoned_npc) & ids['npc']
        server['object_spawned'] |= set(summoned_go) & ids['object']
    except Exception as error:   # never stops the analysis: without it, summoned ones only show as unplaced
        log(f'later: summons not read ({error})')
    listing = [{'key': NOW, 'name': 'Open now', 'opens': None}] + [dict(p) for p in phase_list]
    result = build(targets, server, src, listing)
    result = {'made': int(time.time()), 'sources': said, **result}
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE + '.part', 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, separators=(',', ':'))
    os.replace(FILE + '.part', FILE)
    for phase in result['phases']:
        c = phase['counts']
        if any(v['all'] for v in c.values()):
            log(f"later {phase['key']}: " + ', '.join(f"{k} {v['ready']}/{v['all']} ready" for k, v in c.items() if v['all']))
    log(f"later: {sum(len(ids) for p in result['wowhead'].values() for ids in p.values())} Wowhead pages and "
        f"{sum(len(v) for v in result['icyveins'].values())} Icy Veins answers wanted, data/gather.json written in {time.time() - started:.0f} s")
    return result
