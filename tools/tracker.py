"""Forever Tracker analysis: official WoW Forever content vs. what your server provides.

    python tools/tracker.py snapshot --dbc <folder with frFR/enUS DB2> --build 70425 [--date 2026-10-18]
    python tools/tracker.py analyse [--wowhead]
    python tools/tracker.py locate [--refresh] [--limit N] [--offline]
    python tools/tracker.py world layers | pin [source ...]
    python tools/tracker.py world replay --dump <TDB_full_world.sql> --core <core checkout> [--data <folder>]
    python tools/tracker.py world why <table> <key> [<key> ...]
    python tools/tracker.py world facts [source]
    python tools/tracker.py world resolve
    python tools/tracker.py world decisions [quest|npc|gives|takes|sells] [--verdict add|hold|review] [--limit N]
    python tools/tracker.py world export [--out <data repository>] [--private-out <folder>] [--date YYYY-MM-DD] [--dry-run]

`snapshot` copies the client DB2 tables the tracker needs for one official build into data/builds/<build>.
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
import datetime
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ft import client, content as official_content, forge, locator, output, phases, rules, server, sqlio, tooltips, world  # noqa: E402
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
    json.dump(info, open(meta, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


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


def npc_checks(ask):
    """Compares the level and rank of the spawned creatures that matter most (quest givers, enders and targets, elites,
    rares, bosses) with Wowhead's Forever tooltips; writes ft_npc_checks (report only, nothing is changed)."""
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
            out.append((entry, r['name'] or '', lo, hi, rank, facts['min'], facts['max'], facts['rank'], facts['type'], ','.join(issues)))
    log('npc check: ' + (', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'nothing cached'))
    if wh.summary():
        log('wowhead creatures: ' + wh.summary())
    e = sqlio.escape
    path = os.path.join(DATA, 'npc-checks.sql')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('SET NAMES utf8mb4;\nDROP TABLE IF EXISTS ft_npc_checks;\n'
                'CREATE TABLE ft_npc_checks (entry INT NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL, level_min INT NULL, level_max INT NULL,'
                ' rank_id TINYINT NOT NULL, wh_min INT NULL, wh_max INT NULL, wh_rank TINYINT NOT NULL, wh_type VARCHAR(64) NOT NULL,'
                ' issues VARCHAR(32) NOT NULL, KEY ix_issues (issues)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n')
        for chunk in range(0, len(out), 500):
            f.write('INSERT INTO ft_npc_checks VALUES ' + ','.join('(' + ','.join(e(v) for v in row) + ')' for row in out[chunk:chunk + 500]) + ';\n')
    sqlio.execute_file(path, 'tracker')


def analyse(args):
    started = time.time()
    build_list = official_content.builds()
    if not build_list:
        sys.exit('No snapshot in data/builds. Run the snapshot command first.')
    server_build = CONFIG.server_build()
    if not server_build:
        # no build_file / build in config.ini: the client build the realms accept is the next best guess
        try:
            server_build = int(sqlio.column('SELECT MAX(gamebuild) FROM realmlist', 'auth')[0] or 0)
        except (RuntimeError, IndexError, ValueError, TypeError):
            server_build = 0
        if server_build:
            log(f'server build not set in config.ini ([server] build or build_file): using {server_build} from auth.realmlist')
        else:
            log('warning: server build unknown: set [server] build in config.ini')
    contents, changes, first_seen, changed_in = [], [], {}, {}
    previous = None
    for b in build_list:
        log(f"official content of build {b['build']}")
        current = official_content.official(b['dir'])
        b['counts'] = {kind: len(v) for kind, v in current.items() if not kind.startswith('_')}
        for kind, entities in current.items():
            if kind.startswith('_'):
                continue
            for entity_id in entities:
                first_seen.setdefault((kind, entity_id), b['build'])
        if previous is not None:
            for kind, entity_id, change, fields in official_content.diff_builds(previous, current):
                name = (current.get(kind, {}).get(entity_id) or previous.get(kind, {}).get(entity_id) or {}).get('name', '')
                changes.append((b['build'], build_list[build_list.index(b) - 1]['build'], kind, entity_id, change, fields, name))
                changed_in[(kind, entity_id)] = b['build']
        previous = current
        contents.append(current)
    content = contents[-1]
    latest = build_list[-1]
    log(f'{len(changes)} changes across {len(build_list)} builds')
    ctx = server.server_state()
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
    results = rules.evaluate_all(content, ctx)
    wowhead = wowhead_verdicts(content, results, baseline, args.wowhead)
    try:
        npc_checks(args.wowhead)
    except Exception as error:  # a report only: it never stops the analysis
        log(f'npc check failed, skipped: {error}')
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
    summary = {}
    for (kind, _id), (status, _s, _c) in results.items():
        summary.setdefault(kind, {}).setdefault(status, 0)
        summary[kind][status] += 1
    for kind, counts in sorted(summary.items()):
        log(f'{kind:12} ' + '  '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    log(f'done in {time.time() - started:.0f} s')


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
    elif args.command == 'locate':
        locator.run(args)
    elif args.command == 'client':
        client_status()
    elif args.command == 'fetch':
        result = client.fetch(force=args.force, keep_cache=args.keep_cache, log=log)
        log('client: ' + result['message'])
        sys.exit(result['code'])
    else:
        analyse(args)


if __name__ == '__main__':
    main()
