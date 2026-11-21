"""Forever Tracker analysis: official WoW Forever content vs. what your server provides.

    python tools/tracker.py snapshot --dbc <folder with frFR/enUS DB2> --build 70425 [--date 2026-10-18]
    python tools/tracker.py analyse [--wowhead]
    python tools/tracker.py locate [--refresh] [--limit N] [--offline]
    python tools/tracker.py client | fetch | hotfixes | history | check
    python tools/tracker.py world layers | pin [source ...]
    python tools/tracker.py world replay --dump <TDB_full_world.sql> --core <core checkout> [--data <folder>]
    python tools/tracker.py world why <table> <key> [<key> ...]
    python tools/tracker.py world facts [source]
    python tools/tracker.py world resolve
    python tools/tracker.py world decisions [quest|npc|gives|takes|sells] [--verdict add|hold|review] [--limit N]
    python tools/tracker.py world export [--out <data repository>] [--private-out <folder>] [--date YYYY-MM-DD] [--dry-run]

`snapshot` copies the client DB2 tables the tracker needs for one official build into data/builds/<build>.
`fetch` stores the live build from Blizzard's CDN, `hotfixes` Blizzard's live hotfixes, `history` the builds that came
before (back to the first beta, for the changelog); `check` does the three and analyses when one brought something
(docs/CLIENT.md).
`analyse` reads every snapshot (official content and build-to-build changelog), the live server (its DB2
files, hotfixes and world databases, map files), evaluates the availability of every resource, computes
the in-game tooltips and the Forge fixes, and loads everything into the tracker database. It only reads
the game databases.

`locate` finds the creatures and world objects the server never spawned although the content needs them
(quest givers, objectives, vendors, trainers, loot, bosses) and where they stand, from the maps of Wowhead's
public Forever tooltips (cached in data/wowhead). The Forge spawns them.

`world` is the world build (docs/WORLD-BUILD.md): `layers` lists the layers and their sources, `pin` records the
newest version of each source in data/world/layers.lock.json, `replay` rebuilds the server's world (release dump plus
update files, in the updater's order) in the scratch database named by [build] database and records which file wrote
each row, and `why` answers where one row comes from. Only the scratch database is written. `facts <source>` reads
what a pinned source says (who gives a quest, what a vendor sells, what drops) into the tracker's own database.
`resolve` weighs those facts against the replayed world by named rules and stores what the world should hold and
does not, each decision with its witnesses; `decisions` lists them. `export` writes the decisions that are ready as an
update file for your data repository (and a second one for what may not be published), after trying it twice on the
replayed world inside a transaction it rolls back.

--wowhead names the quests new in Forever that the server does not know, through Wowhead's public Forever
tooltip service (slow and polite, cached in data/wowhead-quests.json). It also asks about every item players cannot get, the new class and
profession spells and recipes the server lacks, and compares the level and rank of quest-related, elite, rare and boss
creatures (The Forge > Checks), all cached in data/wowhead: the ones Wowhead marks as Season of
Discovery leftovers, or does not know, count as internal and are never offered at trainers. Quests Wowhead does not know either
are hidden: they are the game's invisible tracking quests.
"""
import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ft import client, content as official_content, dating, forge, geo, hotfixes, locator, notes, output, phases, rules, server, sqlio, tooltips, vanilla, world  # noqa: E402
from ft.wowhead import GIVE_UP_AFTER, is_stale, load_json, save_json  # noqa: E402
from ft.baseline import Baseline  # noqa: E402
from ft.config import BUILDS, CONFIG, DATA  # noqa: E402

log = server.log


def snapshot(args):
    for locale in ('frFR', 'enUS') if CONFIG.french() else ('enUS',):
        # <dbc>/frFR and <dbc>/enUS as mapextractor writes them, or a flat folder of the --locale given
        source = os.path.join(args.dbc, locale) if os.path.isdir(os.path.join(args.dbc, locale)) else (args.dbc if locale == args.locale and not any(
            os.path.isdir(os.path.join(args.dbc, other)) for other in ('frFR', 'enUS')) else None)
        if not source or not os.path.isdir(source):
            continue
        target = os.path.join(BUILDS, str(args.build), locale)
        os.makedirs(target, exist_ok=True)
        for name in official_content.TABLES:
            if os.path.isfile(os.path.join(source, name + '.db2')):
                shutil.copy2(os.path.join(source, name + '.db2'), target)
        log(f'build {args.build} {locale}: {len(os.listdir(target))} tables')
    meta = os.path.join(BUILDS, str(args.build), 'build.json')
    info = json.load(open(meta, encoding='utf-8-sig')) if os.path.isfile(meta) else {}
    info.update({'build': int(args.build), 'version': args.version or info.get('version') or f'1.60.1.{args.build}',
                 'source': args.source or info.get('source') or args.dbc, 'date': args.date or info.get('date') or datetime.date.today().isoformat()})
    if args.note:
        info['note'] = args.note
    info.pop('tables', None)   # every table is there now, also over a build stored for the changelog alone
    json.dump(info, open(meta, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


NOTES = os.path.join(DATA, 'notes')


def hotfix_note_days():
    """The days written notes name as hotfix days (Blizzard's hotfix posts, ForeverChanges): they date the windows."""
    return sorted(day for day, entry in notes.days(NOTES).items() if entry['blizzard']['sections'] or entry['icyveins'] or entry['foreverchanges'])


def fetch_notes():
    """Blizzard's blue posts, Icy Veins' hotfix articles, then ForeverChanges' notes (ft.notes), in the order they are
    trusted: {'code': 0 when one of them stored something new}."""
    results = [notes.fetch_blizzard(NOTES, log=log), notes.fetch_icyveins(NOTES, log=log), notes.fetch(NOTES, log=log)]
    return {'code': 0 if any(r['code'] == 0 for r in results) else 3, 'message': '; '.join(r['message'] for r in results)}


def notes_command(_args):
    result = fetch_notes()
    log(result['message'])


def client_check(args):
    """What the container does on its own every few hours, at once: the live build from the CDN when it is new (or a
    key it waited for is out), Blizzard's hotfixes, and the analysis when either brought something."""
    started = time.time()
    url = CONFIG.get('client', 'hotfix_cache') or hotfixes.MIRROR
    new = client.check(
        client.noted('client', lambda: client.fetch(log=client.calm(log))),
        client.noted('hotfixes', lambda: hotfixes.fetch(BUILDS, {b['build'] for b in official_content.builds()}, None if url == hotfixes.MIRROR else url)),
        log,
        # the builds before the newest snapshot, back to the first beta: once each (docs/CLIENT.md)
        client.noted('history', lambda: client.history(log=client.calm(log))),
        # what Blizzard wrote about its changes: dates the hotfixes, and tells of the changes made on the servers alone
        fetch_notes=client.noted('notes', fetch_notes))
    if not (new or args.always):
        log(f"nothing new on Blizzard's servers: the analysis was not run (check done in {time.time() - started:.0f} s)")
        return
    # the analysis in a process of its own: nothing this one has read of the builds is carried into it
    sys.stdout.flush()
    sys.exit(subprocess.call([sys.executable, '-X', 'utf8', '-u', os.path.abspath(__file__), 'analyse'] + (['--wowhead'] if args.wowhead else [])))


def extended_costs(args):
    """Writes the server's ItemExtendedCost rows by what they ask (ft.costs), for the website's import cards."""
    from ft import costs
    folder, configured = CONFIG.dbc_folder()
    if not folder:
        sys.exit(f'costs: no DB2 files in {configured or "[server] dbc"}')
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(costs.load(folder), handle, sort_keys=True)


def refresh_quests(args):
    """Compares the quests the server has with EG Link's newest recording of the live game and writes what differs,
    as changes for an import card (ft.refresh, docs/SOURCES.md). Called by the website's EG Link import."""
    from ft import facts, layers, refresh
    folder = os.path.join(DATA, 'eglink', args.eglink)
    wanted = ('quests.enUS',)
    try:
        facts.fetch_eglink(args.eglink, folder, datasets=wanted)
        records = refresh.newest_live(facts.eglink(folder, datasets=wanted), layers.load().live_from)
    except facts.SourceError as error:
        sys.exit(f'refresh: {str(error).strip()}')
    ids = sorted(records)

    def read(table, key, where='1'):
        out = {}
        if not sqlio.has_table(table):
            return None
        for start in range(0, len(ids), 500):
            for row in sqlio.query(f'SELECT * FROM `{table}` WHERE {where} AND `{key}` IN (' + ','.join(map(str, ids[start:start + 500])) + ')'):
                out[int(row['ID'])] = row
        return out
    rows = read('quest_template', 'ID') or {}
    # reputation tiers in points: the client's own table, from the server's copy (row 1: gains, row 2: losses)
    tiers = None
    try:
        table = {int(r['ID']): [int(r.get(f'Difficulty{i}') or 0) for i in range(1, 11)] for r in server.server_db2('QuestFactionReward')}
        tiers = {1: table[1], 2: table.get(2) or [-value for value in table[1]]} if 1 in table else None
    except (SystemExit, KeyError, ValueError, TypeError):
        pass
    if tiers is None:
        log("refresh: the server's QuestFactionReward.db2 could not be read: reputation written another way than the row is left alone")
    changes, left = refresh.quest_changes(records, rows, read('quest_objectives', 'QuestID'), read('quest_classic_level', 'ID'), tiers)
    result = {'changes': changes, 'left': left, 'records': len(records), 'quests': len(set(records) & set(rows))}
    with open(args.out + '.part', 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False)
    os.replace(args.out + '.part', args.out)
    log(f"refresh: {result['quests']} quests of the server have a recording of the live game; "
        f"{sum(len(op['rows']) for op in changes)} values differ in {len(changes)} columns ({', '.join(f'{n} {why}' for why, n in sorted(left.items())) or 'nothing left alone'})")


def client_status():
    """Prints what is live, what is stored and what the server runs, and whether a fetch would bring something."""
    state = client.status()
    live = state['live']
    print('live on Blizzard\'s servers:  ' + (f"{live['version']}" if 'version' in live else f"unknown ({live.get('error', '')})"))
    print(f"newest snapshot:            {state['snapshot'] or 'none'}")
    print(f"the server's client data:   {state['server'] or 'unknown'}")
    if 'build' in live and live['build'] > state['snapshot']:
        print('tracker.py fetch would store the live build.')


def wowhead_names(quest_ids):
    cache_path = os.path.join(DATA, 'wowhead-quests.json')
    cache = load_json(cache_path, {})
    # "Wowhead does not know it" hides an unnamed quest, so that answer is asked again after [wowhead] recheck_days
    # (an answer without a date is from before dates were kept): Wowhead learns a quest when players find it.
    # A name is believed for [wowhead] refresh_days, and everything is asked again after "ask every source again".
    unknown = lambda entry: not (entry.get('fr') or entry.get('en'))
    todo = [q for q in quest_ids if str(q) not in cache or is_stale(cache[str(q)].get('at', 0), unknown(cache[str(q)]), q)]
    log(f'wowhead: {len(todo)} quests to look up ({len(cache)} cached)')
    unreached = 0
    for index, quest in enumerate(todo):
        entry, failed = {}, False
        for locale, key in ((2, 'fr'), (0, 'en')) if CONFIG.french() else ((0, 'en'),):
            if key == 'en' and CONFIG.french() and not entry.get('fr'):
                break  # unknown to Wowhead in French: no need to ask again in English
            try:
                request = urllib.request.Request(f'https://nether.wowhead.com/forever/tooltip/quest/{quest}?locale={locale}',
                                                 headers={'User-Agent': 'ForeverTracker/1.0 (private server admin tool)'})
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.loads(response.read().decode('utf-8'))
                entry[key] = data.get('name', '')
                text = re.sub(r'<[^>]+>', ' ', data.get('tooltip', ''))
                entry.setdefault('text_' + key, re.sub(r'\s+', ' ', text).strip()[:400])
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    failed = True
                entry.setdefault(key, None)  # 404: Wowhead does not know it (the quest is then hidden)
            except Exception:
                failed = True
            time.sleep(0.35)
        if not failed:  # a network error is asked again next time instead of hiding the quest
            entry['at'] = int(time.time())
            cache[str(quest)] = entry
        unreached = unreached + 1 if failed else 0
        if unreached >= GIVE_UP_AFTER:
            log(f'wowhead: {unreached} quests in a row got no answer (down, or it has blocked this address): stopping the lookups, '
                f'{len(todo) - index - 1} left for the next run')
            break
        if index % 50 == 49:
            save_json(cache_path, cache)
            log(f'wowhead: {index + 1}/{len(todo)}')
    save_json(cache_path, cache)
    return cache


def wowhead_verdicts(content, results, baseline, ask):
    """{(kind, id): verdict} for the items players cannot get and the new spells and recipes the server lacks (see ft.wowhead.verdict).
    With ask, Wowhead is asked for the ones not cached yet (slow and polite); otherwise only the cache is read."""
    from ft.wowhead import Wowhead, verdict
    wanted = []
    for kind in ('item', 'spell', 'recipe'):
        for entity_id, entity in content.get(kind, {}).items():
            status = results.get((kind, entity_id), ('ok',))[0]
            # every item players cannot get: Season of Discovery items ship in the Classic Era client too, so "new" alone
            # would miss them; spells and recipes only when new (trainer candidates)
            if status == 'ok' or (kind != 'item' and not baseline.is_new(kind, entity_id, entity)):
                continue
            if kind == 'spell' and entity.get('sub') not in ('class', 'profession'):
                continue
            wanted.append((kind, entity_id))
    wh = Wowhead()
    out, asked = {}, 0
    todo = sum(1 for kind, i in wanted if (lambda d: d is None or wh.stale(d, i))(wh.cached('item' if kind == 'item' else 'spell', i)))
    if ask:
        log(f'wowhead: {len(wanted)} items/spells to check, {todo} to ask (not cached yet, or due again)')
    for kind, entity_id in wanted:
        target = 'item' if kind == 'item' else 'spell'
        data = wh.cached(target, entity_id)
        if ask and (data is None or wh.stale(data, entity_id)):
            data = wh.get(target, entity_id)
            asked += 1
            if asked % 200 == 0:
                log(f'wowhead: {asked}/{todo}')
        v = verdict(data)
        if v:
            out[(kind, entity_id)] = v
    counts = {}
    for v in out.values():
        counts[v] = counts.get(v, 0) + 1
    log('wowhead verdicts: ' + (', '.join(f'{k}={n}' for k, n in sorted(counts.items())) or 'none cached'))
    if wh.summary():
        log('wowhead items/spells: ' + wh.summary())
    return out


RANK_NAMES = {0: 'Normal', 1: 'Elite', 2: 'Rare Elite', 3: 'Boss', 4: 'Rare'}


def classic_facts(path=None):
    """(the spells the original game teaches anywhere, the items it gave out nowhere), from the packs of the original
    game's database the website keeps (data/vmangos/pack.cdbpack, data/classicdb/pack.cdbpack); (None, set()) without a
    pack, or with none that can be read. With both: a spell either teaches counts as taught, and an item is given out
    nowhere only when neither gives it out, so that one database's gap never hides what the other knows."""
    from ft import classic
    paths = [path] if path else [os.path.join(DATA, source, 'pack.cdbpack') for source in ('vmangos', 'classicdb')]
    taught, never = None, None
    for one in paths:
        if not os.path.isfile(one):
            continue
        try:
            pack = classic.load(one)
            spells, items = classic.taught(pack), set(pack.get('never_given') or ())
        except (OSError, ValueError, KeyError, TypeError) as error:
            log(f'original game pack {one} not read ({error})')
            continue
        taught = spells if taught is None else taught | spells
        never = items if never is None else never & items
    if taught is None:
        return None, set()
    return taught, never


def classic_teachers(args):
    """What a pack of the original game's database says about the profession recipes nobody can learn on the realm
    (ft.classic, docs/SOURCES.md): trainer lines, quests whose turn-in should cast a spell. Called by the website."""
    from ft import classic, phases as phase_rules
    from ft.content import EFFECT_LEARN_SPELL, PROFESSION_CATEGORIES
    try:
        pack = classic.load(args.pack)
    except (OSError, ValueError, EOFError) as error:
        sys.exit(f'classic: {args.pack} cannot be read ({error})')
    if not sqlio.has_table('ft_entities', 'tracker'):
        sys.exit('classic: no analysis yet (run it first)')
    lines = {r['ID'] for r in server.server_db2('SkillLine') if r['CategoryID'] in PROFESSION_CATEGORIES}
    line_of, acquire = {}, {}
    for ability in server.server_db2('SkillLineAbility'):
        acquire.setdefault(ability['Spell'], set()).add(ability['AcquireMethod'])
        if ability['SkillLine'] in lines:
            line_of.setdefault(ability['Spell'], ability['SkillLine'])
    known = {r['ID'] for r in server.server_db2('SpellName')}
    if sqlio.has_table('spell_name', 'hotfixes'):
        known |= {int(v) for v in sqlio.column('SELECT ID FROM spell_name', 'hotfixes')}
    waiting = phase_rules.closed(phase_rules.load(), CONFIG.get('phases', 'current'))
    later = ' AND phase NOT IN (' + ','.join(str(int(p)) for p in waiting) + ')' if waiting and sqlio.has_column('ft_entities', 'phase', 'tracker') else ''
    wanted = {}
    for row in sqlio.query("SELECT id, checks FROM ft_entities WHERE internal = 0 AND status <> 'ok' AND type IN ('spell', 'recipe')" + later, 'tracker'):
        spell = int(row['id'])
        if spell in line_of and any(c.get('code') == 'learn' and not c.get('ok') for c in json.loads(row['checks'] or '[]')):
            wanted[spell] = line_of[spell]
    gaps = len(wanted)
    wanted = classic.askable(wanted, known, acquire)   # not what Forever took away
    teachers = {}
    for effect in server.server_db2('SpellEffect'):
        if effect['Effect'] == EFFECT_LEARN_SPELL and effect['EffectTriggerSpell'] in wanted:
            teachers.setdefault(effect['EffectTriggerSpell'], set()).add(effect['SpellID'])
    for row in server.server_db2('SpellLearnSpell'):
        if row['LearnSpellID'] in wanted and row['SpellID']:
            teachers.setdefault(row['LearnSpellID'], set()).add(row['SpellID'])
    named = sorted({quest for quest, _shown, _cast in pack['quests']})
    quests = {}
    for start in range(0, len(named), 1000):
        for row in sqlio.query('SELECT ID, RewardSpell FROM quest_template WHERE ID IN (' + ','.join(map(str, named[start:start + 1000])) + ')'):
            quests[int(row['ID'])] = int(row['RewardSpell'] or 0)
    found = classic.evidence(pack, wanted, teachers, quests)
    item_gaps = {int(row['id']) for row in sqlio.query("SELECT id FROM ft_entities WHERE internal = 0 AND status <> 'ok' AND type = 'item'" + later, 'tracker')}
    drops, sells, item_left = classic.item_sources(pack, item_gaps)
    for why, n in item_left.items():
        found['left'][why] = found['left'].get(why, 0) + n
    if gaps > len(wanted):
        found['left']['classic_gone_from_forever'] = gaps - len(wanted)
    result = {'version': str(pack.get('version') or '')[:120], 'made': str(pack.get('made') or '')[:10], 'asked': len(wanted),
              'ev': {'train': found['train'], 'talk': found['talk'], 'drop': drops, 'sell': sells}, 'changes': found['changes'], 'gossip': found['gossip'],
              'names': {'npc': {k: str(v)[:100] for k, v in (pack.get('npc_names') or {}).items()},
                        'go': {k: str(v)[:100] for k, v in (pack.get('object_names') or {}).items()}},
              'left': found['left']}
    with open(args.out, 'w', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False)
    log(f"classic: {len(wanted)} recipes asked, {len(found['train'])} trainer lines, {sum(len(c['rows']) for c in found['changes'])} quests, "
        f"{len(found['talk'])} conversation lines, {len(drops)} drops and {len(sells)} vendor lines of items players cannot get, "
        f"{len(found['gossip'])} taught in a conversation of an older pack")


def player_reports(args):
    """Turns a ForeverChanges pack into the evidence the website's import card is made from (ft.reports,
    docs/SOURCES.md): its NPC names matched to the server's creatures by where they stand. Called by the website."""
    from ft import facts, geo as geography, layers, quests as quest_rows, reports
    try:
        pack = reports.load(args.pack)
    except (OSError, ValueError, EOFError, KeyError) as error:
        sys.exit(f'reports: {args.pack} cannot be read ({error})')
    names = sorted(reports.wanted_names(pack))

    def named(table, spawn_table):
        by_name, spawns = {}, {}
        for start in range(0, len(names), 400):
            chunk = ','.join(sqlio.escape(name) for name in names[start:start + 400])
            for row in sqlio.query(f'SELECT entry, name FROM `{table}` WHERE name IN ({chunk})'):
                by_name.setdefault((row['name'] or '').strip().lower(), []).append(int(row['entry']))
        entries = sorted({entry for found in by_name.values() for entry in found})
        for start in range(0, len(entries), 1000):
            for row in sqlio.query(f'SELECT id, map, position_x x, position_y y FROM `{spawn_table}` WHERE id IN (' + ','.join(map(str, entries[start:start + 1000])) + ')'):
                spawns.setdefault(int(row['id']), []).append((int(row['map']), float(row['x']), float(row['y'])))
        return by_name, spawns
    builds = official_content.builds()
    if not builds:
        sys.exit('reports: no client snapshot yet (run the analysis first)')
    geo = geography.Geo(builds[-1]['dir'])
    zones = {}
    for area in official_content.table(builds[-1]['dir'], 'AreaTable', 'enUS'):
        if not area.get('ParentAreaID'):
            zones.setdefault(str(area.get('AreaName') or '').strip().lower(), area['ID'])

    def ui_map(zone):
        area = zones.get(str(zone or '').strip().lower())
        maps = geo.zone_ui_maps(area) if area else []
        return maps[0] if maps else None

    def where(zone, x, y):
        found = ui_map(zone)
        return geo.to_world(found, float(x) / 100, float(y) / 100) if found else None

    def box(zone):
        area = zones.get(str(zone or '').strip().lower())
        for found in geo.zone_ui_maps(area) if area else []:
            for a in geo.assignments.get(found, []):
                if a['AreaID'] == area:
                    return (a['MapID'], min(a['Region1X'], a['Region2X']), min(a['Region1Y'], a['Region2Y']), max(a['Region1X'], a['Region2X']), max(a['Region1Y'], a['Region2Y']))
        return None
    try:
        ev, left = reports.evidence(pack, reports.Matcher(*named('creature_template', 'creature'), where, box),
                                    reports.Matcher(*named('gameobject_template', 'gameobject'), where, box))
    except ValueError as error:
        sys.exit(f'reports: {error}')
    # where the site's maps show NPCs, rares and books that nobody spawned here: places for the locator
    wanted = sorted({n['entry'] for n in pack.get('npcs') or [] if isinstance(n, dict) and n.get('seen') and isinstance(n.get('entry'), int)})
    known, standing = set(), set()
    for start in range(0, len(wanted), 1000):
        chunk = ','.join(map(str, wanted[start:start + 1000]))
        known |= {int(v) for v in sqlio.column(f'SELECT entry FROM creature_template WHERE entry IN ({chunk})')}
        standing |= {('npc', int(v)) for v in sqlio.column(f'SELECT DISTINCT id FROM creature WHERE id IN ({chunk})')}
    pin_names = sorted({str(p.get('name') or '').strip().lower() for p in pack.get('pins') or [] if isinstance(p, dict)} - {''})
    by_pin = {'npc': {}, 'go': {}}
    for kind, table, spawn_table in (('npc', 'creature_template', 'creature'), ('go', 'gameobject_template', 'gameobject')):
        for start in range(0, len(pin_names), 400):
            chunk = ','.join(sqlio.escape(name) for name in pin_names[start:start + 400])
            for row in sqlio.query(f'SELECT entry, name FROM `{table}` WHERE name IN ({chunk})'):
                by_pin[kind].setdefault((row['name'] or '').strip().lower(), []).append(int(row['entry']))
        entries = sorted({entry for found in by_pin[kind].values() for entry in found})
        for start in range(0, len(entries), 1000):
            standing |= {(kind, int(v)) for v in sqlio.column(f'SELECT DISTINCT id FROM `{spawn_table}` WHERE id IN (' + ','.join(map(str, entries[start:start + 1000])) + ')')}
    continent = {area['ID']: area.get('ContinentID') for area in official_content.table(builds[-1]['dir'], 'AreaTable', 'enUS')}
    spots, unplaced = reports.places(pack, known, standing, lambda kind, name: by_pin[kind].get(name, []), continent.get)
    left.update(unplaced)
    # and the quest givers, enders and vendors nobody spawned, where the reports place them
    have = {(kind, entry) for kind, entry, _name, _points in spots}
    spots += [row for row in ev.pop('place', []) if (row[0], row[1]) not in have]
    # the quest givers the site's map names by id: rows without a name to match (pack 'givers', from the site itself)
    by_id = {'npc': set(), 'go': set()}
    for giver in pack.get('givers') or []:
        if isinstance(giver, dict) and giver.get('seen') and giver.get('kind') in by_id and isinstance(giver.get('entry'), int):
            by_id[giver['kind']].add(giver['entry'])
    known_ids, standing_ids = set(), set()
    for kind, table, spawn_table in (('npc', 'creature_template', 'creature'), ('go', 'gameobject_template', 'gameobject')):
        entries = sorted(by_id[kind])
        for start in range(0, len(entries), 1000):
            chunk = ','.join(map(str, entries[start:start + 1000]))
            known_ids |= {(kind, int(v)) for v in sqlio.column(f'SELECT entry FROM `{table}` WHERE entry IN ({chunk})')}
            standing_ids |= {(kind, int(v)) for v in sqlio.column(f'SELECT DISTINCT id FROM `{spawn_table}` WHERE id IN ({chunk})')}
    given, given_spots, given_left = reports.givers(pack, known_ids, standing_ids)
    ev['start'] = [list(row) for row in sorted({tuple(row) for row in ev['start']} | {tuple(row) for row in given})]
    left.update(given_left)
    have = {(kind, entry) for kind, entry, _name, _points in spots}
    spots += [row for row in given_spots if (row[0], row[1]) not in have]
    # what the NPC says at the turn-in. EG Link's recording of the same window keeps the server's own placeholders:
    # where it has one wording, that is the text; the site's, with its marks turned back, is for the rest
    recorded = {}
    root = os.path.join(DATA, 'eglink')
    commits = [name for name in (os.listdir(root) if os.path.isdir(root) else []) if facts.COMMIT.fullmatch(name)]
    if commits:
        folder = os.path.join(root, max(commits, key=lambda name: os.path.getmtime(os.path.join(root, name))))
        try:
            facts.fetch_eglink(os.path.basename(folder), folder, datasets=('texts.enUS',))
        except facts.SourceError as error:
            log(f'reports: {str(error).strip()}; the texts already here are read')
        wordings = {}
        live_from = layers.load().live_from
        for fact in facts.eglink(folder, datasets=('texts.enUS',)):
            if fact.kind == 'text' and fact.build >= live_from:
                for moment in ('complete', 'progress'):
                    wordings.setdefault((fact.subject, moment), []).extend(line['text'] for line in fact.data.get(moment) or [])
        for (quest, moment), seen in wordings.items():
            text, _why = quest_rows.said(seen)
            if text:
                recorded.setdefault(quest, {})[moment] = text
    told, untold = reports.texts(pack, recorded)
    left.update(untold)
    result = {'ev': dict(ev, text=told), 'left': left, 'places': spots, 'retrieved': str(pack.get('retrieved') or '')[:10], 'quests': len(pack.get('quests') or []), 'items': len(pack.get('items') or [])}
    with open(args.out + '.part', 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False)
    os.replace(args.out + '.part', args.out)
    log('reports: ' + ', '.join(f'{len(rows)} {kind}' for kind, rows in ev.items()) + f', {len(spots)} places of things nobody spawned'
        + ' (' + (', '.join(f'{n} {why}' for why, n in sorted(left.items())) or 'nothing left out') + ')')


def merge_checks(rows, sided):
    """The rows of ft_npc_checks: the level and rank findings (11 columns each) with the side findings ((entry, name,
    issue, note)) added, one row per creature. A creature with only a side finding has no level, rank or Wowhead values."""
    by_entry = {row[0]: list(row) for row in rows}
    for entry, name, issue, note in sided:
        row = by_entry.setdefault(entry, [entry, name, None, None, 0, None, None, 0, '', '', ''])
        kinds = [kind for kind in row[9].split(',') if kind]
        if issue not in kinds:
            kinds.append(issue)
        row[9] = ','.join(kinds)
        row[10] = (row[10] + ' ' if row[10] else '') + note + '.'
    return [tuple(by_entry[entry]) for entry in sorted(by_entry)]


def eglink_recording(wanted, check):
    """The facts of EG Link's recording of the commit its import last read (data/eglink), only the datasets wanted,
    with the files fetched that are not here yet; None when no recording was ever read (the check is then not made)."""
    from ft import facts
    root = os.path.join(DATA, 'eglink')
    commits = [name for name in (os.listdir(root) if os.path.isdir(root) else []) if facts.COMMIT.fullmatch(name)]
    if not commits:
        log(f'{check}: no EG Link recording yet (Imports > Import EG Link reads one): not made')
        return None
    folder = os.path.join(root, max(commits, key=lambda name: os.path.getmtime(os.path.join(root, name))))
    try:
        facts.fetch_eglink(os.path.basename(folder), folder, datasets=wanted)
    except facts.SourceError as error:
        log(f'{check}: {str(error).strip()}; the files already here are read')
    return facts.eglink(folder, datasets=wanted)


def side_checks():
    """Compares whose side each creature is on with what players saw on the live game (ft.sides): [(entry, name,
    issue, note)]. The recordings are EG Link's, of the commit its import last read (data/eglink); without one the
    check is not made."""
    from ft import layers, sides
    recording = eglink_recording(('creatures', 'npcs'), 'side check')
    if recording is None:
        return []
    live = sides.recorded(recording, layers.load().live_from)
    ids = sorted(live)
    creatures = {}
    for start in range(0, len(ids), 1000):
        for row in sqlio.query('SELECT ct.entry, ct.name, ct.faction, ct.npcflag, ct.type, EXISTS (SELECT 1 FROM creature c WHERE c.id = ct.entry) spawned '
                               'FROM creature_template ct WHERE ct.entry IN (' + ','.join(map(str, ids[start:start + 1000])) + ')'):
            creatures[int(row['entry'])] = row
    templates = {int(r['ID']): r for r in server.server_db2('FactionTemplate')}
    factions = {int(r['ID']): r for r in server.server_db2('Faction')} or None
    try:
        shown = shown_to_one_side(sides, sorted(creatures))
    except (RuntimeError, KeyError, ValueError, TypeError) as error:
        log(f'side check: the phases and conditions could not be read ({str(error)[:120]}): who the server shows a creature to is not checked')
        shown = {}
    found, counts = sides.compare(live, creatures, templates, factions, shown)
    log('side check: ' + (', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'nothing to compare')
        + f' ({len(live)} creatures recorded on live, {len(shown)} shown to one side only on the server)')
    return found


def shown_to_one_side(sides, entries):
    """{entry: side} of the creatures the server shows to one side only: every spawn in a phase or a spawn group that
    a team condition closes to that side, or a visibility condition on the creature itself."""
    by_source = {}
    for row in sqlio.query('SELECT SourceTypeOrReferenceId t, SourceGroup g, SourceEntry e, ElseGroup, ConditionTypeOrReference, ConditionValue1, NegativeCondition '
                           'FROM conditions WHERE SourceTypeOrReferenceId IN (26, 32, 33)'):
        by_source.setdefault((int(row['t']), int(row['g']), int(row['e'])), []).append(row)
    phase_areas, group_side, entry_side = {}, {}, {}
    for (kind, group, entry), rows in by_source.items():
        side = sides.team_of(rows)
        if kind == 26:
            phase_areas.setdefault(group, []).append(side)        # a phase, per area it is given in
        elif kind == 33 and side:
            group_side[entry] = side
        elif kind == 32 and group == 5 and side:                  # 5: a creature
            entry_side[entry] = side
    phase_side = {phase: found[0] for phase, found in phase_areas.items() if found[0] and all(side == found[0] for side in found)}
    members = {}
    for row in server.server_db2('PhaseXPhaseGroup'):
        members.setdefault(int(row['PhaseGroupID']), []).append(int(row['PhaseID']))
    for group, phases in members.items():
        found = {phase_side.get(phase) for phase in phases}
        if len(found) == 1 and None not in found:
            phase_side[('group', group)] = found.pop()
    if not (phase_side or group_side or entry_side):
        return {}
    spawns = {}
    grouped = sqlio.has_table('spawn_group')
    for start in range(0, len(entries), 1000):
        chunk = ','.join(map(str, entries[start:start + 1000]))
        for row in sqlio.query('SELECT c.id, c.PhaseId, c.PhaseGroup, ' + ('COALESCE(g.groupId, 0)' if grouped else '0') + ' spawn_group FROM creature c '
                               + ('LEFT JOIN spawn_group g ON g.spawnType = 0 AND g.spawnId = c.guid ' if grouped else '') + f'WHERE c.id IN ({chunk})'):
            spawns.setdefault(int(row['id']), []).append((int(row['PhaseId'] or 0), int(row['PhaseGroup'] or 0), int(row['spawn_group'] or 0)))
    out = {}
    for entry in entries:
        side = sides.shown_to(spawns.get(entry, []), phase_side, group_side, entry_side.get(entry)) if entry in spawns or entry in entry_side else None
        if side:
            out[entry] = side
    return out


def npc_checks(ask):
    """Compares the level and rank of the spawned creatures that matter most (quest givers, enders and targets, elites,
    rares, bosses) with Wowhead's Forever tooltips, and every recorded creature's side with the live game (side_checks);
    writes ft_npc_checks (a report: nothing is changed by it)."""
    from ft.wowhead import Wowhead
    levels = sqlio.has_table('creature_classic_level')
    rows = sqlio.query(
        'SELECT ct.entry, ct.name, ct.Classification rank_id' + (', l.level_min lo, l.level_max hi' if levels else ', NULL lo, NULL hi') +
        ' FROM creature_template ct' + (' LEFT JOIN creature_classic_level l ON l.entry = ct.entry' if levels else '') +
        ' WHERE EXISTS (SELECT 1 FROM creature c WHERE c.id = ct.entry) AND (ct.Classification > 0'
        ' OR ct.entry IN (SELECT id FROM creature_queststarter) OR ct.entry IN (SELECT id FROM creature_questender)'
        ' OR ct.entry IN (SELECT ObjectID FROM quest_objectives WHERE Type = 0))')
    wh = Wowhead()
    due = lambda entry, d: d is None or wh.stale(d, entry) or ('facts' not in d and not d.get('missing'))
    todo = sum(1 for r in rows if due(int(r['entry']), wh.cached('npc', int(r['entry']))))
    if ask:
        log(f'wowhead: {len(rows)} creatures to compare, {todo} to ask (not cached yet, or due again)')
    out, asked, counts = [], 0, {}
    for r in rows:
        entry = int(r['entry'])
        cached = wh.cached('npc', entry)
        if ask and due(entry, cached):
            asked += 1
            if asked % 200 == 0:
                log(f'wowhead: {asked}/{todo} creatures')
        data = wh.npc(entry, ask)
        if not data:
            continue
        facts = data.get('facts')
        if data.get('missing') or not facts:
            counts['not_on_wowhead' if data.get('missing') else 'no_level_line'] = counts.get('not_on_wowhead' if data.get('missing') else 'no_level_line', 0) + 1
            continue
        lo, hi, rank = (int(r['lo']) if r['lo'] else None), (int(r['hi']) if r['hi'] else None), int(r['rank_id'] or 0)
        issues = []
        # a level differs only when the ranges do not meet: Wowhead's range spans every spawn and phase it saw
        # (61-62 against our 62 is the same creature), so a narrower server range inside it is not a finding
        if facts['min'] is not None and (lo is None or hi < facts['min'] or lo > facts['max']):
            issues.append('level')
        if rank != facts['rank']:
            issues.append('rank')
        counts['checked'] = counts.get('checked', 0) + 1
        for i in issues:
            counts[i] = counts.get(i, 0) + 1
        if issues:
            out.append((entry, r['name'] or '', lo, hi, rank, facts['min'], facts['max'], facts['rank'], facts['type'], ','.join(issues), ''))
    log('npc check: ' + (', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'nothing cached'))
    if wh.summary():
        log('wowhead creatures: ' + wh.summary())
    # whose side each creature is on, against the live game: its own rows, or a note on a row above
    try:
        sided = side_checks()
    except Exception as error:  # a report only: it never takes the level and rank checks with it
        log(f'side check failed, skipped: {error}')
        sided = []
    out = merge_checks(out, sided)
    e = sqlio.escape
    path = os.path.join(DATA, 'npc-checks.sql')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('SET NAMES utf8mb4;\nDROP TABLE IF EXISTS ft_npc_checks;\n'
                'CREATE TABLE ft_npc_checks (entry INT NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL, level_min INT NULL, level_max INT NULL,'
                ' rank_id TINYINT NOT NULL, wh_min INT NULL, wh_max INT NULL, wh_rank TINYINT NOT NULL, wh_type VARCHAR(64) NOT NULL,'
                ' issues VARCHAR(64) NOT NULL, note TEXT NOT NULL, KEY ix_issues (issues)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n')
        for chunk in range(0, len(out), 500):
            f.write('INSERT INTO ft_npc_checks VALUES ' + ','.join('(' + ','.join(e(v) for v in row) + ')' for row in out[chunk:chunk + 500]) + ';\n')
    sqlio.execute_file(path, 'tracker')


EXTRAS_ASKS = 3000   # Wowhead lookups one analysis may make for the extras (the rest waits for the next run)


def server_spawns(table_name, kind):
    """Every spawn of `creature` or `gameobject` as ft.extras.Spawn, with its template's name."""
    from ft.extras import Spawn
    template = 'creature_template' if table_name == 'creature' else 'gameobject_template'
    events = {}
    if sqlio.has_table(f'game_event_{table_name}'):
        for r in sqlio.query(f'SELECT guid, eventEntry FROM `game_event_{table_name}`'):
            events.setdefault(int(r['guid']), []).append(int(r['eventEntry']))
    return [Spawn(kind, int(r['guid']), int(r['id']), r['name'] or '', int(r['map']), float(r['x']), float(r['y']), float(r['z']),
                  int(r['PhaseId'] or 0), int(r['PhaseGroup'] or 0), tuple(events.get(int(r['guid']), ())))
            for r in sqlio.query(f'SELECT s.guid, s.id, t.name, s.map, s.position_x x, s.position_y y, s.position_z z, s.PhaseId, s.PhaseGroup '
                                 f'FROM `{table_name}` s JOIN `{template}` t ON t.entry = s.id')]


def world_extras(ask):
    """What the server's world holds that the live game does not (ft.extras): twins, stacked spawns, crowded
    creatures, invented entries and quest givers live never used. Writes ft_world_extras (a report: nothing is
    changed by it)."""
    from ft import extras, layers
    from ft.wowhead import Wowhead, verdict
    recording = eglink_recording(('npcs', 'creatures', 'creature_details.enUS', 'object_details.enUS'), 'extras')
    if recording is None:
        return
    live_from = layers.load().live_from
    live_npcs, known, live_pairs = {}, set(), set()
    for fact in recording:
        kind = 'go' if fact.subject_kind == 'object' else fact.subject_kind
        if kind not in ('npc', 'go'):
            continue
        known.add((kind, fact.subject))                      # any build, the beta's too: the entry is Blizzard's
        if fact.build < live_from:
            continue
        name = (fact.data.get('name') if isinstance(fact.data, dict) else '') or ''
        if kind == 'npc' and fact.kind in ('creature', 'seen', 'talked'):
            live_npcs[fact.subject] = live_npcs.get(fact.subject) or name
        if fact.kind in ('gives', 'takes'):
            live_pairs.add((kind, fact.subject, fact.object, fact.kind))
    # the client's own lists (short: Creature holds a few hundred rows; GameObjects is read only where its layout is known)
    known |= {('npc', int(r['ID'])) for r in server.server_db2('Creature') if 'ID' in r}
    known |= {('go', int(r['ID'])) for r in server.server_db2('GameObjects') if 'ID' in r}
    spawns = server_spawns('creature', 'npc') + server_spawns('gameobject', 'go')
    names = {(s.kind, s.entry): s.name for s in spawns}
    counts = {}
    for s in spawns:
        counts[(s.kind, s.entry)] = counts.get((s.kind, s.entry), 0) + 1
    pooled = {('npc' if int(r['type']) == 0 else 'go', int(r['spawnId'])) for r in sqlio.query('SELECT type, spawnId FROM pool_members WHERE type IN (0, 1)')} \
        if sqlio.has_table('pool_members') else set()
    found = []
    npc_counts = {entry: n for (kind, entry), n in counts.items() if kind == 'npc'}
    npc_names = {entry: name for (kind, entry), name in names.items() if kind == 'npc'}
    found += extras.twins(npc_counts, npc_names, live_npcs, spawns)
    found += extras.stacked(spawns, pooled, {('npc', entry) for entry in live_npcs} | {k for k in known if k[0] == 'go'})

    wh, asked = Wowhead(), [0]

    def lookup(kind, entry):
        page = 'npc' if kind == 'npc' else 'object'
        data = wh.cached(page, entry)
        if ask and asked[0] < EXTRAS_ASKS and (data is None or wh.stale(data, entry)):
            asked[0] += 1
            data = wh.get(page, entry)
        return data

    found += extras.invented(counts, names, known, lambda kind, entry: verdict(lookup(kind, entry)))
    # crowded: the creatures with more spawns than CROWD_SLACK, against the spots Wowhead's map marks
    builds = official_content.builds()
    if builds:
        from ft import geo as geography
        geo = geography.Geo(builds[-1]['dir'])
        by_place = {}
        for s in spawns:
            if s.kind == 'npc' and npc_counts[s.entry] > extras.CROWD_SLACK:
                by_place.setdefault((s.entry, s.map), []).append((s.x, s.y))
        points = {}
        for entry in sorted({entry for entry, _map in by_place}):
            where = (lookup('npc', entry) or {}).get('map') or {}
            for floor, coords in (where.get('coords') or {}).items():
                for px, py in coords:
                    w = geo.wowhead(where.get('zone'), int(floor), px, py)
                    if w:
                        points.setdefault(entry, {}).setdefault(w[0], []).append((w[1], w[2]))
        found += extras.crowded(by_place, points, npc_names)
    server_pairs = set()
    for table_name, kind, role in (('creature_queststarter', 'npc', 'gives'), ('creature_questender', 'npc', 'takes'),
                                   ('gameobject_queststarter', 'go', 'gives'), ('gameobject_questender', 'go', 'takes')):
        server_pairs |= {(kind, int(r['id']), int(r['quest']), role) for r in sqlio.query(f'SELECT id, quest FROM `{table_name}`')}
    found += extras.givers(server_pairs, live_pairs, names)
    tally = collections.Counter(f.issue for f in found)
    log('extras: ' + (', '.join(f'{issue}={tally[issue]}' for issue in extras.ISSUES if tally[issue]) or 'nothing found')
        + f' ({len(live_npcs)} creatures recorded on live, {asked[0]} asked to Wowhead)')
    e = sqlio.escape
    path = os.path.join(DATA, 'world-extras.sql')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('SET NAMES utf8mb4;\nDROP TABLE IF EXISTS ft_world_extras;\n'
                'CREATE TABLE ft_world_extras (id INT AUTO_INCREMENT PRIMARY KEY, issue VARCHAR(12) NOT NULL, kind VARCHAR(4) NOT NULL, entry INT NOT NULL,'
                ' name VARCHAR(255) NOT NULL, guid BIGINT NULL, map INT NULL, x FLOAT NULL, y FLOAT NULL, z FLOAT NULL, server INT NULL,'
                ' live VARCHAR(255) NOT NULL, note TEXT NOT NULL, KEY ix_issue (issue), KEY ix_entry (kind, entry)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n')
        rows = [f for f in found]
        for chunk in range(0, len(rows), 500):
            f.write('INSERT INTO ft_world_extras (issue, kind, entry, name, guid, map, x, y, z, server, live, note) VALUES '
                    + ','.join('(' + ','.join(e(v) for v in (x.issue, x.kind, x.entry, (x.name or '')[:250], x.guid, x.map, x.x, x.y, x.z, x.server,
                                                               ','.join(map(str, x.live))[:250], x.note)) + ')' for x in rows[chunk:chunk + 500]) + ';\n')
    sqlio.execute_file(path, 'tracker')


def known_server_build():
    """The build of the server's client data: [server] build_file or build in config.ini, else the client build the
    realms accept (auth.realmlist), the next best guess; 0 when neither is known."""
    server_build = CONFIG.server_build()
    if server_build:
        return server_build
    try:
        server_build = int(sqlio.column('SELECT MAX(gamebuild) FROM realmlist', 'auth')[0] or 0)
    except (RuntimeError, OSError, IndexError, ValueError, TypeError):
        return 0
    if server_build:
        log(f'server build not set in config.ini ([server] build or build_file): using {server_build} from auth.realmlist')
    return server_build


def analyse(args):
    started = time.time()
    build_list = official_content.builds()
    if not [b for b in build_list if not b.get('baseline')]:
        sys.exit('No snapshot in data/builds. Run the snapshot command first.')
    server_build = known_server_build()
    if not server_build:
        log('warning: server build unknown: set [server] build in config.ini')
    # Blizzard's hotfixes back to the beta: today's cache taken apart along the stored builds (ft.dating, docs/CLIENT.md)
    try:
        log(dating.rebuild(build_list, hotfix_note_days(), log)['message'])
    except (OSError, ValueError, hotfixes.CacheError) as error:
        log(f'hotfix windows not written ({error}): the hotfixes stand over the newest build only')
    content, changes, first_seen, changed_in, by_hotfix, more = official_content.changelog(build_list, log)
    build_list = more['builds']   # without an original game that could not be compared: the website would show it as a build
    latest = build_list[-1]
    log(f'{len(changes)} changes across {len(build_list)} builds' + (f", {len(more['hotfix_changes'])} in {len(more['hotfixes'])} hotfix update(s)" if more.get('hotfixes') else ''))
    for line in official_content.replay_lines(more):
        log(line)
    for b in build_list:
        if hotfixes.summary(b['dir']):
            log(f"hotfixes over build {b['build']}: " + hotfixes.summary(b['dir']))
    if by_hotfix:
        log('known by hotfix alone, not listed as added: ' + ', '.join(f'{kind}={n}' for kind, n in sorted(by_hotfix.items())))
    ctx = server.server_state()
    ctx['hotfix_only'] = by_hotfix
    ctx['changelog'] = more
    # Only the quests new in Forever: the Classic Era ones are known, and asking Wowhead about thousands more takes long.
    baseline = Baseline()
    unknown_quests = [q for q in content['quest'] if q not in ctx['quests'] and baseline.is_new('quest', q, {})]
    quest_names = {}
    if args.wowhead:
        quest_names = wowhead_names(unknown_quests)
    elif os.path.isfile(os.path.join(DATA, 'wowhead-quests.json')):
        quest_names = load_json(os.path.join(DATA, 'wowhead-quests.json'), {})
    if not CONFIG.french():  # English only: French answers cached by an earlier run are left out
        quest_names = {quest: {key: value for key, value in entry.items() if key not in ('fr', 'text_fr')} for quest, entry in quest_names.items()}
    for index, change in enumerate(changes):
        if change[2] == 'quest' and not change[6]:
            qid = change[3]
            name = ctx['quest_fr'].get(qid) or (ctx['quests'].get(qid) or {}).get('LogTitle') or quest_names.get(str(qid), {}).get('fr') or ''
            changes[index] = change[:6] + (name,)
    hotfix_changes = more.get('hotfix_changes') or []
    for index, change in enumerate(hotfix_changes):
        if change[2] == 'quest' and not change[6]:
            qid = change[3]
            name = ctx['quest_fr'].get(qid) or (ctx['quests'].get(qid) or {}).get('LogTitle') or quest_names.get(str(qid), {}).get('fr') or ''
            hotfix_changes[index] = change[:6] + (name,)
    ctx['season'] = baseline.season
    ctx['wowhead_reward_quests'] = phases.wowhead_reward_quests()   # quests Wowhead shows rewarding items: never Internal (ft.output)
    ctx['classic_taught'], ctx['classic_never_given'] = classic_facts()
    results = rules.evaluate_all(content, ctx)
    wowhead = wowhead_verdicts(content, results, baseline, args.wowhead)
    try:
        npc_checks(args.wowhead)
    except Exception as error:  # a report only: it never stops the analysis
        log(f'npc check failed, skipped: {error}')
    try:
        world_extras(args.wowhead)
    except Exception as error:  # a report only, like the checks
        log(f'extras check failed, skipped: {error}')
    try:   # the zone maps the Forge's Spawns page draws the locator's positions on (app/maps.php)
        if geo.write_export(latest['dir'], os.path.join(DATA, 'ui-maps.json'), latest['build']):
            log('zone maps written for the Spawns page')
    except (OSError, ValueError) as error:
        log(f'zone maps not written ({error})')
    log('tooltips')
    tips = tooltips.build(content, latest['dir'], quest_names, ctx)
    fixes = forge.generate(content, results, ctx, latest['dir'], latest['build'], wowhead)
    log('release phases')
    phase_list, phase_of = phases.run(content, ctx)
    icons = {int(r['fileDataId']): r['name'] for r in sqlio.query('SELECT fileDataId, name FROM armory_icon')} if sqlio.has_table('armory_icon') else {}
    path = os.path.join(DATA, 'import.sql')
    output.write_sql(path, build_list, content, changes, results, first_seen, changed_in, icons, quest_names, ctx, server_build, tips, fixes, wowhead,
                     phase_list, phase_of)
    log(f"loading {os.path.getsize(path) // 1024} KB into {CONFIG.db('tracker')}")
    sqlio.execute_file(path, 'tracker')
    # The counts the website shows: internal / test rows and rows of a phase not open yet are no gap players meet, so
    # they are counted apart (Season of Discovery bosses the client still lists were 41 of 44 "missing" bosses).
    rows = sqlio.query('SELECT type, status, internal, phase, COUNT(*) n FROM ft_entities GROUP BY type, status, internal, phase', 'tracker')
    summary = output.summary(rows, phases.closed(phase_list, CONFIG.get('phases', 'current')))
    for kind, (counts, internal, later) in sorted(summary.items()):
        aside = '  '.join(f'{k}={v}' for k, v in (('internal', internal), ('later', later)) if v)
        log(f'{kind:12} ' + '  '.join(f'{k}={v}' for k, v in sorted(counts.items())) + (f'  (not counted: {aside})' if aside else ''))
    # what the content still to come needs, listed and fetched now (docs/GATHER.md): a report, it never stops the analysis
    try:
        from ft import gather
        gather.run(content, phase_list)
    except Exception as error:
        log(f'later: the work list was not made ({type(error).__name__}: {str(error)[:200]})')
    answers_table()
    log(f'done in {time.time() - started:.0f} s')


def answers_table():
    """The outside sources' answers this run asked for (Wowhead's tooltips above all), into the tracker's table
    ft_source_answers (app/sourceanswers.php): PHP's backfill reads what each source's files gained since its last run.
    Without PHP (a Windows install without it) the container's next start or the next push does it; it never stops the
    analysis."""
    php = shutil.which('php')
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'source-answers.php')
    if not php or not os.path.isfile(script):
        return
    try:
        result = subprocess.run([php, script, 'backfill'], capture_output=True, timeout=3600)
        said = result.stdout.decode('utf-8', 'replace').strip().splitlines()
        log('answers table: ' + (said[-1] if said and result.returncode == 0 else result.stderr.decode('utf-8', 'replace').strip()[:200] or 'not written'))
    except (OSError, subprocess.SubprocessError) as error:
        log(f'answers table not written ({error})')


def checkout_cmd(args):
    """The client's data at a step of the timeline, as an SQL file for a hotfixes database (docs/CHECKOUT.md)."""
    from ft import checkout
    if args.step == 'list':
        for step in checkout.steps():
            print(f"{step['id']:>12}  {step['version']:<16} {step['date'] or '':<10}  " + (f"hotfixes of {step['cache_day']}" if step.get('cache_day') else 'no hotfixes kept')
                  + ('  (tables missing: --fetch reads them from the CDN)' if step['partial'] else ''))
        return
    try:
        step = checkout.find(args.step)
    except ValueError as error:
        sys.exit(str(error))
    server_build = known_server_build()
    if not server_build:
        sys.exit('server build unknown: set [server] build in config.ini, or let the tracker read auth.realmlist (the checkout writes rows for that build)')
    if args.fetch and step['partial']:
        # the client check reads builds into the same CDN folder: one at a time
        gate = client.alone_here('history.lock')
        if gate is None:
            sys.exit('checkout: a client check is reading builds from the CDN right now: try again when it is done')
        try:
            refused = client.complete(step['build'], set(checkout.tracked()), log=log)
        except (RuntimeError, OSError, LookupError, ValueError) as error:
            sys.exit(f'checkout: the other tables of build {step["build"]} could not be read from the CDN ({error}): nothing written')
        finally:
            gate.close()
        for name, why in sorted(refused.items()):
            log(f'checkout: {name} of build {step["build"]} could not be read: {why}')
        step = checkout.find(step['id'])   # stored now: no longer partial
    try:
        made = checkout.plan(step, carry=not args.no_carry, log=log)
    except (RuntimeError, OSError) as error:
        sys.exit(f'checkout: the hotfixes database could not be read ({error})')
    made['carry'] = not args.no_carry
    path = args.out or os.path.join(checkout.OUT, f"hotfixes-{step['id']}.sql")
    manifest = checkout.write(step, made, path, server_build)
    rows = sum(t['rows'] for t in manifest['tables'].values())
    removed = sum(t['removed'] for t in manifest['tables'].values())
    log(f"checkout {step['id']}: {len(manifest['tables'])} tables, {rows} records over your server's files, {removed} removed, "
        f"{len(manifest['skipped'])} tables left out -> {path}")
    for name, why in sorted(manifest['skipped'].items()):
        log(f'  left out: {name}: {why}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    snap = sub.add_parser('snapshot', help='store the DB2 of one official client build')
    snap.add_argument('--dbc', required=True, help='folder with the extracted DB2 (with frFR / enUS sub-folders)')
    snap.add_argument('--build', required=True, type=int)
    snap.add_argument('--locale', default='enUS', choices=('enUS', 'frFR'), help='locale of a flat --dbc folder (default enUS)')
    snap.add_argument('--version')
    snap.add_argument('--source')
    snap.add_argument('--date')
    snap.add_argument('--note')
    run = sub.add_parser('analyse', help='compare the official content with the server and load the website data')
    run.add_argument('--wowhead', action='store_true', help='name the unknown quests new in Forever, and check the new items and trainer spells the server lacks, through Wowhead tooltips')
    locate = sub.add_parser('locate', help='find unspawned creatures and objects the content needs and where they stand (after analyse)')
    locate.add_argument('--refresh', action='store_true', help='ask Wowhead again even for the resources already cached')
    locate.add_argument('--limit', type=int, default=0, help='ask Wowhead for at most N new resources this time')
    locate.add_argument('--offline', action='store_true', help='only use the Wowhead answers already cached')
    sub.add_parser('client', help='which client build is live, which the tracker holds and which the server runs')
    fetch = sub.add_parser('fetch', help="store the live client build's tables from Blizzard's CDN when it is newer than the newest snapshot")
    fetch.add_argument('--force', action='store_true', help='read the live build again even when it is already stored')
    fetch.add_argument('--keep-cache', action='store_true', help="keep the CDN lookup files of this build in data/cdn (several hundred MB)")
    sub.add_parser('notes', help="store Blizzard's blue posts (its hotfix notes and announcements), Icy Veins' hotfix articles and ForeverChanges' patch notes, for the timeline (docs/CLIENT.md)")
    sub.add_parser('hotfixes', help="store Blizzard's live hotfixes with the snapshot of their build (the public cache, [client] hotfix_cache)")
    again = sub.add_parser('refresh', help="what the newest recording of the live game would change in the server's quests (for the EG Link import card)")
    again.add_argument('what', choices=['quests'])
    again.add_argument('--eglink', required=True, metavar='COMMIT', help='the EG Link commit to read')
    again.add_argument('--out', required=True, metavar='FILE', help='where the changes are written, as JSON')
    costs_parser = sub.add_parser('costs', help="the server's ItemExtendedCost rows by what they ask, for vendor rows paid with currencies or items (the website's import cards)")
    costs_parser.add_argument('--out', required=True, metavar='FILE', help='where they are written, as JSON {key: ID}')
    told = sub.add_parser('reports', help="players' reports (a ForeverChanges pack) as evidence for the website's import card")
    told.add_argument('--pack', required=True, metavar='FILE', help='the pack tools/foreverchanges_pull.py made')
    told.add_argument('--out', required=True, metavar='FILE', help='where the evidence is written, as JSON')
    old_game = sub.add_parser('classic', help="the original game's teachers of recipes nobody can learn yet (a classic-db pack) as evidence for the website's import card")
    old_game.add_argument('--pack', required=True, metavar='FILE', help='the pack tools/classicdb_pack.py made')
    old_game.add_argument('--out', required=True, metavar='FILE', help='where the evidence is written, as JSON')
    old = sub.add_parser('vanilla', help="store the original game's tables (patch 1.12, as the client WoW Classic launched with) as the build before the first beta: the changelog then starts there (docs/VANILLA.md)")
    old.add_argument('--again', action='store_true', help='read them again although they are stored')
    past = sub.add_parser('history', help="store the builds that came before the newest snapshot (back to the first beta) from Blizzard's CDN, for the changelog")
    past.add_argument('--again', action='store_true', help='also ask for the builds that were refused before (another table layout)')
    past.add_argument('--limit', type=int, default=0, help='only the N newest of the builds that are missing')
    past.add_argument('--keep-cache', action='store_true', help='keep the CDN lookup files in data/cdn')
    check = sub.add_parser('check', help='fetch, hotfixes and history, then analyse when one of them brought something new')
    check.add_argument('--wowhead', action='store_true', help='as for analyse')
    check.add_argument('--always', action='store_true', help='analyse even when nothing was new')
    out = sub.add_parser('checkout', help="the client's data at a step of the timeline (a build, or a build's hotfix update: 70938+1) as an SQL file for a test realm's hotfixes database; 'list' names the steps (docs/CHECKOUT.md)")
    out.add_argument('step', help="'list', 'latest', a build (70450) or a hotfix update (70938+1)")
    out.add_argument('--out', help='the SQL file to write (data/checkout/hotfixes-<step>.sql); its manifest is written beside it (.json)')
    out.add_argument('--fetch', action='store_true', help="first read the tables a build stored for the changelog alone lacks from Blizzard's CDN")
    out.add_argument('--no-carry', action='store_true', help='leave out the records that exist by hotfix alone when the step has no hotfixes kept')
    world_parser = sub.add_parser('world', help='the world build: its layers and sources (docs/WORLD-BUILD.md)')
    world_sub = world_parser.add_subparsers(dest='world_command', required=True)
    world_sub.add_parser('layers', help='list the layers, their sources, licences and pinned versions')
    pin = world_sub.add_parser('pin', help='look up the newest version of every source and write data/world/layers.lock.json')
    pin.add_argument('sources', nargs='*', help='only these source ids (default: all)')
    rep = world_sub.add_parser('replay', help='rebuild the server world in the scratch database ([build] database) and record which file wrote each row')
    rep.add_argument('--dump', required=True, help="the core's release world dump (TDB_full_world_*.sql)")
    rep.add_argument('--core', help="a checkout of the core: its sql/updates/world and sql/custom/world are replayed")
    rep.add_argument('--data', help="a folder of update files from your data repository (its sql/world)")
    rep.add_argument('--folder', action='append', help='another folder of update files, as label=folder (repeatable)')
    rep.add_argument('--keep-going', action='store_true', help='record a failing file and go on (default: stop, as the updater does)')
    when = rep.add_mutually_exclusive_group()
    when.add_argument('--until', help="the world as it stood that day (YYYY-MM-DD): update files named for a later day are left out")
    when.add_argument('--at', help="the world as of a step of the timeline (70707, 70938+1: its day), to pair with `tracker.py checkout` of that step")
    rep.add_argument('--trust-account', action='store_true',
                     help='run although the MySQL account can write to other databases: only on a throwaway server that holds nothing else')
    fact = world_sub.add_parser('facts', help='read what a source says into the tracker database, or list what is stored')
    fact.add_argument('source', nargs='?', help='the source to read (eglink); without it: what is stored')
    world_sub.add_parser('resolve', help='weigh the facts against the replayed world and store what the world should hold and does not')
    dec = world_sub.add_parser('decisions', help='the last resolve: a summary, or the decisions of one kind')
    dec.add_argument('kind', nargs='?', choices=('quest', 'npc', 'gives', 'takes', 'sells'), help='list the decisions of this kind')
    dec.add_argument('--verdict', choices=('add', 'hold', 'review'))
    dec.add_argument('--limit', type=int, default=50)
    exp = world_sub.add_parser('export', help='write the decisions that are ready as update files for a data repository')
    exp.add_argument('--out', help='a checkout of the data repository: the file goes to its sql/world, its manifest to build/ (default data/world/export/public)')
    exp.add_argument('--private-out', help='the folder of the set that may not be published (default data/world/export/private)')
    exp.add_argument('--date', help='the date in the file name, YYYY-MM-DD (default today)')
    exp.add_argument('--dry-run', action='store_true', help='plan and try it on the replayed world, write nothing')
    why = world_sub.add_parser('why', help='where a row of the replayed world comes from')
    why.add_argument('table')
    why.add_argument('key', nargs='+', help="the row's key values, in the order of the table's key columns")
    args = parser.parse_args()
    if args.command == 'world':
        world.run(args)
    elif args.command == 'snapshot':
        snapshot(args)
    elif args.command == 'checkout':
        checkout_cmd(args)
    elif args.command == 'locate':
        locator.run(args)
    elif args.command == 'client':
        client_status()
    elif args.command == 'check':
        client_check(args)
    elif args.command == 'notes':
        notes_command(args)
    elif args.command == 'refresh':
        refresh_quests(args)
    elif args.command == 'costs':
        extended_costs(args)
    elif args.command == 'reports':
        player_reports(args)
    elif args.command == 'classic':
        classic_teachers(args)
    elif args.command == 'hotfixes':
        url = CONFIG.get('client', 'hotfix_cache') or hotfixes.MIRROR
        result = client.noted('hotfixes', lambda: hotfixes.fetch(BUILDS, {b['build'] for b in official_content.builds()}, None if url == hotfixes.MIRROR else url))()
        log('hotfixes: ' + result['message'])
        sys.exit(result['code'])
    elif args.command == 'history':
        try:
            result = client.noted('history', lambda: client.history(log=client.calm(log), again=args.again, limit=args.limit, keep_cache=args.keep_cache))()
        except (RuntimeError, OSError, LookupError, ValueError) as error:
            log(client.calm(str)(f'earlier builds: the list of builds could not be read ({error}): nothing stored'))
            sys.exit(2)
        log('earlier builds: ' + result['message'])
        sys.exit(result['code'])
    elif args.command == 'vanilla':
        if not client.newest_snapshot():
            sys.exit('vanilla: no snapshot of the game yet: store one first (fetch, or snapshot), the original game is what it is compared with')
        gate = client.alone_here('history.lock')   # the client check stores it too: one at a time
        if gate is None:
            sys.exit('vanilla: a client check is reading the earlier builds: it stores the original game itself')
        try:
            result = vanilla.fetch(log=client.calm(log), again=args.again)
        except (RuntimeError, OSError, LookupError, ValueError) as error:
            log(client.calm(str)(f'vanilla: the original game could not be read ({error}): nothing stored'))
            sys.exit(2)
        finally:
            gate.close()
        log('vanilla: ' + result['message'])
        sys.exit(result['code'])
    elif args.command == 'fetch':
        result = client.noted('client', lambda: client.fetch(force=args.force, keep_cache=args.keep_cache, log=log))()
        log('client: ' + result['message'])
        sys.exit(result['code'])
    else:
        analyse(args)


if __name__ == '__main__':
    main()
