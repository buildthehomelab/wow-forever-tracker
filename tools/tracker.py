"""Forever Tracker analysis: official WoW Forever content vs. what your server provides.

    python tools/tracker.py snapshot --dbc <folder with frFR/enUS DB2> --build 70425 [--date 2026-10-18]
    python tools/tracker.py analyse [--wowhead]
    python tools/tracker.py locate [--refresh] [--limit N] [--offline]

`snapshot` copies the client DB2 tables the tracker needs for one official build into data/builds/<build>.
`analyse` reads every snapshot (official content and build-to-build changelog), the live server (its DB2
files, hotfixes and world databases, map files), evaluates the availability of every resource, computes
the in-game tooltips and the Forge fixes, and loads everything into the tracker database. It only reads
the game databases.

`locate` finds the creatures and world objects the server never spawned although the content needs them
(quest givers, objectives, vendors, trainers, loot, bosses) and where they stand, from the maps of Wowhead's
public Forever tooltips (cached in data/wowhead). The Forge spawns them.

--wowhead names the quests new in Forever that the server does not know, through Wowhead's public Forever
tooltip service (slow and polite, cached in data/wowhead-quests.json). It also asks about the new items, class and
profession spells and recipes the server lacks (cached in data/wowhead): the ones Wowhead marks as Season of
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

from ft import content as official_content, forge, locator, output, rules, server, sqlio, tooltips  # noqa: E402
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


def wowhead_names(quest_ids):
    cache_path = os.path.join(DATA, 'wowhead-quests.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.isfile(cache_path) else {}
    todo = [q for q in quest_ids if str(q) not in cache]
    log(f'wowhead: {len(todo)} quests to look up ({len(cache)} cached)')
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
            cache[str(quest)] = entry
        if index % 50 == 49:
            json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False)
            log(f'wowhead: {index + 1}/{len(todo)}')
    json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False)
    return cache


def wowhead_verdicts(content, results, baseline, ask):
    """{(kind, id): verdict} for the new items, spells and recipes the server lacks (see ft.wowhead.verdict).
    With ask, Wowhead is asked for the ones not cached yet (slow and polite); otherwise only the cache is read."""
    from ft.wowhead import Wowhead, verdict
    wanted = []
    for kind in ('item', 'spell', 'recipe'):
        for entity_id, entity in content.get(kind, {}).items():
            status = results.get((kind, entity_id), ('ok',))[0]
            if status == 'ok' or not baseline.is_new(kind, entity_id, entity):
                continue
            if kind == 'spell' and entity.get('sub') not in ('class', 'profession'):
                continue
            wanted.append((kind, entity_id))
    wh = Wowhead()
    out, asked = {}, 0
    todo = sum(1 for kind, i in wanted if wh.cached('item' if kind == 'item' else 'spell', i) is None)
    if ask:
        log(f'wowhead: {len(wanted)} items/spells to check, {todo} not cached yet')
    for kind, entity_id in wanted:
        target = 'item' if kind == 'item' else 'spell'
        data = wh.cached(target, entity_id)
        if data is None and ask:
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
    return out


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
        quest_names = json.load(open(os.path.join(DATA, 'wowhead-quests.json'), encoding='utf-8'))
    if not CONFIG.french():  # English only: French answers cached by an earlier run are left out
        quest_names = {quest: {key: value for key, value in entry.items() if key not in ('fr', 'text_fr')} for quest, entry in quest_names.items()}
    for index, change in enumerate(changes):
        if change[2] == 'quest' and not change[6]:
            qid = change[3]
            name = ctx['quest_fr'].get(qid) or (ctx['quests'].get(qid) or {}).get('LogTitle') or quest_names.get(str(qid), {}).get('fr') or ''
            changes[index] = change[:6] + (name,)
    results = rules.evaluate_all(content, ctx)
    wowhead = wowhead_verdicts(content, results, baseline, args.wowhead)
    log('tooltips')
    tips = tooltips.build(content, latest['dir'], quest_names, ctx)
    fixes = forge.generate(content, results, ctx, latest['dir'], latest['build'], wowhead)
    icons = {int(r['fileDataId']): r['name'] for r in sqlio.query('SELECT fileDataId, name FROM armory_icon')} if sqlio.has_table('armory_icon') else {}
    path = os.path.join(DATA, 'import.sql')
    output.write_sql(path, build_list, content, changes, results, first_seen, changed_in, icons, quest_names, ctx, server_build, tips, fixes, wowhead)
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
    args = parser.parse_args()
    if args.command == 'snapshot':
        snapshot(args)
    elif args.command == 'locate':
        locator.run(args)
    else:
        analyse(args)


if __name__ == '__main__':
    main()
