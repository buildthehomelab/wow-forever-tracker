#!/usr/bin/env python3
"""Reads foreverchanges.pro into the tracker's data folder, slowly, and makes the pack its import card is made from
(tools/ft/foreverchanges_site.py says how; docs/SOURCES.md, ForeverChanges).

    python tools/foreverchanges_pull.py pull [--wanted wanted.json] [--limit 3000] [--pause 2.5] [--older 14] [--gaps-only] [--data DIR]
    python tools/foreverchanges_pull.py pack [--data DIR] [--out pack.fcpack]
    python tools/foreverchanges_pull.py status [--data DIR]

`pull` is one visit: the site's sitemaps, then up to --limit files: first what the tracker lacks (the continents'
map files, then --wanted: the gaps the website writes, {"quests": [...], "items_first": [...], "items": [...]}), then
the rest of the site (every other map's files, quest page and item page; not with --gaps-only). In each of the two,
first what was never read, then what is older than --older days.
It writes the pack at the end. `pack` writes it again from what is kept, with no network. The website runs both
(The Forge > Imports > Read the site; the container every FT_FOREVERCHANGES_EVERY_HOURS).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ft import foreverchanges_site as site  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('pull', 'pack', 'status'):
        command = sub.add_parser(name)
        command.add_argument('--data', default=DATA)
        if name == 'pull':
            command.add_argument('--wanted')
            command.add_argument('--limit', type=int, default=3000)
            command.add_argument('--pause', type=float, default=2.5)
            command.add_argument('--older', type=int, default=14)
            command.add_argument('--gaps-only', action='store_true', help='read only what the gaps ask about, not the rest of the site')
        if name == 'pack':
            command.add_argument('--out')
    args = parser.parse_args(argv)
    say = lambda message: print(message, flush=True)
    if args.command == 'status':
        print(json.dumps(site.status(args.data), indent=1))
        return 0
    if args.command == 'pull':
        wanted = None
        if args.wanted:
            with open(args.wanted, encoding='utf-8') as handle:
                wanted = json.load(handle)
        if args.pause < 1:
            sys.exit('--pause: one request a second at most')
        done = site.pull(args.data, wanted, args.pause, max(0, args.limit), args.older, whole=not args.gaps_only, log=say)
        say(f"foreverchanges: {done.get('read', 0)} read ({done.get('new', 0)} new, {done.get('changed', 0)} changed, {done.get('missing', 0)} not there), "
            f"{done.get('left', 0)} left for the next visit ({done.get('left_gaps', 0)} of the gaps), one request every {done['pause']:.1f} s")
    content = site.write_pack(args.data, getattr(args, 'out', None))
    say(f"foreverchanges: pack of {len(content['quests'])} quests, {len(content['items'])} items with a source, {len(content['npcs'])} NPCs, "
        f"{len(content['pins'])} pins and {len(content['givers'])} quest givers by id ({sum(1 for g in content['givers'] if g['seen'])} seen by players), read {content['retrieved']}")
    return 2 if args.command == 'pull' and done.get('stopped') else 0


if __name__ == '__main__':
    sys.exit(main())
