"""Writes tools/baseline/classic-era.json: the record IDs of the Classic Era client, as ID ranges.

    python tools/make_baseline.py [--build 1.15.9.70576]

The Forever client still carries everything the Classic Era client has, Season of Discovery included
(runes, Waylaid Supplies, Nightmare Incursions, Karazhan Crypts...). An ID above some cut-off is therefore
no sign of Forever content. "New in Forever" is what the Classic Era client does not have, which is also
how Wowhead labels it. Only IDs are stored, read from wago.tools' public DB2 exports; with no --build,
the latest wow_classic_era build wago.tools knows.
"""
import argparse
import csv
import datetime
import io
import json
import os
import urllib.request

TABLES = ['ItemSparse', 'SpellName', 'QuestV2', 'Map', 'DungeonEncounter', 'AreaTable', 'Achievement', 'TaxiNodes', 'Talent']
AGENT = {'User-Agent': 'ForeverTracker/1.1 (private server admin tool)'}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'baseline', 'classic-era.json')


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=300) as response:
        return response.read().decode('utf-8-sig')


def ranges(ids):
    out = []
    for i in sorted(ids):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--build', help='Classic Era build, e.g. 1.15.9.70576 (default: the latest)')
    args = parser.parse_args()
    build = args.build or json.loads(fetch('https://wago.tools/api/builds'))['wow_classic_era'][0]['version']
    tables = {}
    for name in TABLES:
        rows = csv.DictReader(io.StringIO(fetch(f'https://wago.tools/db2/{name}/csv?build={build}')))
        ids = {int(r['ID']) for r in rows}
        tables[name] = ranges(ids)
        print(f'{name}: {len(ids)} ids, {len(tables[name])} ranges')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as handle:
        json.dump({'product': 'wow_classic_era', 'build': build, 'source': 'wago.tools', 'date': datetime.date.today().isoformat(),
                   'tables': tables}, handle, separators=(',', ':'))
        handle.write('\n')
    print(f'{OUT}: {os.path.getsize(OUT) // 1024} KB')


if __name__ == '__main__':
    main()
