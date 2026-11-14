#!/usr/bin/env python3
"""Refresh ForeverChanges references; --prepare validates without loading the DB.

Optional --archive reads an already downloaded official ForeverMaster ZIP.
--pages <folder> loads what the site's pages state instead (a folder kept by
`python tools/ft/foreverchanges_pages.py mirror`; default data/foreverchanges-pages
when the flag is given without a folder). No network is used for pages here.
Only tracker fact tables are written; no world database or Forge fixes change.
"""
import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
from ft import facts, foreverchanges, foreverchanges_pages, layers
from ft.config import DATA


PAGES = 'foreverchanges-pages'


def pages(folder, prepare):
    """Loads what the kept pages state as references of their own source: the pack's records stay as they are."""
    if not (folder / 'robots.txt').is_file():
        raise facts.SourceError(f'{folder} holds no kept pages: python tools/ft/foreverchanges_pages.py mirror --out {folder}')
    skipped, about, extra = collections.Counter(), {}, []
    if not prepare:                                           # the names your world and the other sources know by id
        from ft import sqlio
        extra = foreverchanges_pages.known_names(sqlio.query, log=print)
    records = list(foreverchanges_pages.read(str(folder), skipped, about, extra))
    if not records:
        raise facts.SourceError(f'no page of {folder} could be read')
    source = layers.load().source(PAGES)
    pin = max(r.data['read'] for r in records)                # pages have no version: the day the newest was read
    sql = Path(DATA) / f'world/facts-{PAGES}.sql'
    counts = facts.write_sql(str(sql), PAGES, pin, source['licence'], source['use'], records, skipped)
    if not prepare:
        sqlio.execute_file(str(sql), 'tracker')
    summary = {'read': pin, 'counts': dict(collections.Counter(r.subject_kind for r in records)), 'facts': sum(counts.values()),
               'left_out': dict(skipped), 'names': about.get('names', {}), 'prepared_only': prepare}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    names = about.get('names', {})
    print(('Prepared' if prepare else 'Loaded') + f' {len(records)} ForeverChanges page references, read up to {pin}. Names on pages: '
          f"{names.get('one id', 0)} with one id, {names.get('several ids', 0)} with several, {names.get('no id', 0)} with none.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--pages', nargs='?', type=Path, const=Path(DATA) / PAGES)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.pages:
        return pages(args.pages, args.prepare)
    raw = args.archive.read_bytes() if args.archive else foreverchanges.download()
    digest = hashlib.sha256(raw).hexdigest()
    pin = digest[:16]
    folder = Path(DATA) / 'foreverchanges' / pin
    foreverchanges.fetch(pin, folder, fetch=lambda _: raw, log=print)
    skipped, about = collections.Counter(), {}
    records = list(foreverchanges.read(folder, skipped, about))
    if not records:
        raise facts.SourceError('no ForeverChanges references found')
    source = layers.load().source('foreverchanges')
    sql = Path(DATA) / 'world/facts-foreverchanges.sql'
    counts = facts.write_sql(str(sql), 'foreverchanges', pin, source['licence'], source['use'], records, skipped)
    summary = {'pin': pin, 'sha256': digest, 'pack': about['pack'],
               'counts': dict(collections.Counter(r.subject_kind for r in records)),
               'facts': sum(counts.values()), 'left_out': dict(skipped),
               'inventory': about['inventory'], 'prepared_only': args.prepare}
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
