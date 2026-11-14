"""Writes tools/schema/db2-files.json: the file data id of each client table the tracker snapshots.

    python tools/make_db2_files.py [manifest.json]

Without an argument, WoWDBDefs' manifest is downloaded (github.com/wowdev/WoWDBDefs, manifest.json). A table's file
data id never changes, so this is only needed when tools/ft/content.py TABLES gets a new table.
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.sample.ini'))

from ft import content  # noqa: E402

MANIFEST = 'https://raw.githubusercontent.com/wowdev/WoWDBDefs/master/manifest.json'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema', 'db2-files.json')


def main(argv):
    if len(argv) > 1:
        with open(argv[1], encoding='utf-8') as handle:
            manifest = json.load(handle)
    else:
        with urllib.request.urlopen(MANIFEST, timeout=60) as response:
            manifest = json.load(response)
    by_name = {entry['tableName'].lower(): entry for entry in manifest}
    files, missing = {}, []
    for name in content.TABLES:
        entry = by_name.get(name.lower()) or {}
        if entry.get('db2FileDataID'):
            files[name] = int(entry['db2FileDataID'])
        else:
            missing.append(name)
    if missing:
        raise SystemExit('no file data id for: ' + ', '.join(missing))
    about = ("File data id of each client table the tracker snapshots (TABLES of tools/ft/content.py), from WoWDBDefs' "
             "manifest.json (github.com/wowdev/WoWDBDefs). tools/make_db2_files.py writes it again.")
    with open(OUT, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump({'about': about, 'files': files}, handle, indent=1)
        handle.write('\n')
    print(f'{len(files)} tables -> {OUT}')


if __name__ == '__main__':
    main(sys.argv)
