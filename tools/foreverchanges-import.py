#!/usr/bin/env python3
"""Refresh ForeverChanges references; --prepare validates without loading the DB.

Optional --archive reads an already downloaded official ForeverMaster ZIP.
Only tracker fact tables are written; no world database or Forge fixes change.
"""
import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

from ft import facts, foreverchanges, layers
from ft.config import DATA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.archive:
        raw = args.archive.read_bytes()
    else:
        request = urllib.request.Request(foreverchanges.URL, headers={'User-Agent': 'ForeverTracker (source reference)'})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(foreverchanges.MAX_ARCHIVE + 1)
    digest = hashlib.sha256(raw).hexdigest()
    pin = digest[:16]
    folder = Path(DATA) / 'foreverchanges' / pin
    foreverchanges.fetch(pin, folder, fetch=lambda _: raw, log=print)
    skipped = collections.Counter()
    records = list(foreverchanges.read(folder, skipped))
    if not records:
        raise facts.SourceError('no ForeverChanges references found')
    source = layers.load().source('foreverchanges')
    sql = Path(DATA) / 'world/facts-foreverchanges.sql'
    counts = facts.write_sql(str(sql), 'foreverchanges', pin, source['licence'], source['use'], records, skipped)
    summary = {'pin': pin, 'sha256': digest, 'pack': records[0].data['pack'],
               'counts': dict(collections.Counter(r.subject_kind for r in records)),
               'facts': sum(counts.values()), 'left_out': dict(skipped),
               'inventory': records[0].data['inventory'], 'prepared_only': args.prepare}
    if not args.prepare:
        from ft import sqlio
        sqlio.execute_file(str(sql), 'tracker')
        lock_path = str(Path(DATA) / 'world/layers.lock.json')
        lock = layers.read_lock(lock_path)
        lock.setdefault('sources', {})['foreverchanges'] = {'version': pin, 'sha256': digest, 'size': len(raw)}
        lock['written'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        layers.write_lock(lock_path, lock)
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(('Prepared' if args.prepare else 'Loaded') + f' {len(records)} ForeverChanges references; pack {summary["pack"]["version"]}, build {summary["pack"]["build"]}.')


if __name__ == '__main__':
    try:
        main()
    except (facts.SourceError, OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f'ForeverChanges refresh failed: {error}')
