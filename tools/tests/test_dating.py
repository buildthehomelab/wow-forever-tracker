"""python -m unittest discover -s tools/tests

When each of Blizzard's hotfixes came (ft.dating): today's cache taken apart along the stored builds. A row is dated by
the first build that carries its value after the last build that did not; a program-only build does not end a window;
each build gets the cache it shipped with and the cache its window ended with.
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import dating, hotfixes  # noqa: E402
from test_hotfixes import ITEM, META, NAMES, cache, item  # noqa: E402


class FakeTable:
    """A table stored as JSON ({id: [name, level, price]}) in place of a .db2 file."""
    def __init__(self, path, name=None):
        with open(path, encoding='utf-8') as handle:
            self.rows = json.load(handle)
        self.name, self.table_hash, self.meta = name, ITEM, META
        self.columns = [(n, None) for n in NAMES]

    def __iter__(self):
        for record_id, (name, level, price) in self.rows.items():
            yield {'ID': int(record_id), 'Name': name, 'Level': level, 'Price': price}


class Dating(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.real = dating.db2.Table
        dating.db2.Table = FakeTable
        self.addCleanup(setattr, dating.db2, 'Table', self.real)
        dating._ID_CACHE.clear()
        hotfixes._loaded.clear()
        self.chain = []

    def build(self, number, day, rows):
        folder = os.path.join(self.folder, str(number))
        os.makedirs(os.path.join(folder, 'enUS'))
        with open(os.path.join(folder, 'enUS', 'Item.db2'), 'w', encoding='utf-8') as handle:
            json.dump({str(k): v for k, v in rows.items()}, handle)
        self.chain.append({'build': number, 'date': day, 'dir': folder})
        return folder

    def test_each_row_dated_by_the_build_that_first_carries_it(self):
        self.build(1, '2026-10-01', {1: ['Sword', 1, 1.5], 2: ['Shield', 1, 1.5], 3: ['Axe', 1, 1.5], 9: ['Gone', 1, 1.5]})
        self.build(2, '2026-10-10', {1: ['Sword', 1, 1.5], 2: ['Shield', 1, 1.5], 3: ['Axe', 1, 1.5], 9: ['Gone', 1, 1.5]})
        self.build(3, '2026-10-20', {1: ['Sword', 5, 1.5], 2: ['Shield', 1, 1.5], 3: ['Axe', 1, 1.5]})
        blob = cache(3, [(100, ITEM, 1, 1, item('Sword', 5)),      # carried by build 3: a hotfix to build 2
                         (101, ITEM, 2, 1, item('Shield', 1)),     # the same everywhere: sent again, base
                         (102, ITEM, 3, 1, item('Axe', 9)),        # in no build yet: a hotfix to the newest
                         (103, ITEM, 4, 1, item('Ghost', 1)),      # a record no build has: there by hotfix alone
                         (104, ITEM, 9, 2, b''),                   # a removal build 3 carries
                         (-1, ITEM, 5, 1, item('Key', 1))])        # sent with every connection
        found = dating.windows(self.chain, blob, log=lambda *_: None)
        self.assertEqual(found, {0: 2, 1: 'base', 2: 'newest', 3: 'base', 4: 2, 5: 'base'})

    def test_a_row_changed_back_and_forth_counts_from_its_last_change(self):
        self.build(1, '2026-10-01', {1: ['Sword', 5, 1.5]})
        self.build(2, '2026-10-10', {1: ['Sword', 1, 1.5]})
        self.build(3, '2026-10-20', {1: ['Sword', 5, 1.5]})
        self.build(4, '2026-10-30', {1: ['Sword', 5, 1.5]})
        found = dating.windows(self.chain, cache(4, [(7, ITEM, 1, 1, item('Sword', 5))]), log=lambda *_: None)
        self.assertEqual(found, {0: 2})

    def test_a_program_only_build_does_not_end_the_window(self):
        rows = {1: ['Sword', 1, 1.5]}
        self.build(1, '2026-10-01', {1: ['Sword', 0, 1.5]})
        self.build(2, '2026-10-10', rows)
        self.build(3, '2026-10-12', rows)                  # the same tables as build 2, byte for byte
        self.build(4, '2026-10-20', {1: ['Sword', 5, 1.5]})
        newest = self.chain[-1]['dir']
        with open(os.path.join(newest, hotfixes.FILE), 'wb') as handle:
            handle.write(cache(4, [(100, ITEM, 1, 1, item('Sword', 5))]))
        result = dating.rebuild(self.chain, ['2026-10-11', '2026-10-15'], log=lambda *_: None)
        self.assertEqual(result['code'], 0)
        self.assertEqual(result['windows'], {1: 0, 2: 1, 4: 0})     # build 2's window, not build 3's
        second = hotfixes.history_kept(self.chain[1]['dir'])
        self.assertEqual([e.get('rebuilt') for e in second], ['base', 'window'])
        self.assertEqual(second[1]['window'], {'from': '2026-10-10', 'until': '2026-10-19', 'days': ['2026-10-11', '2026-10-15'], 'rows': 1, 'next': 4})
        # the program-only build is live with build 2's hotfixes: it does not undo them
        twin = hotfixes.history_kept(self.chain[2]['dir'])
        self.assertEqual([e.get('rebuilt') for e in twin], ['carried'])
        build, records = hotfixes.parse(hotfixes._read(os.path.join(self.chain[2]['dir'], hotfixes.FILE)))
        self.assertEqual((build, [r.push for r in records]), (3, [100]))

    def test_each_build_gets_the_cache_it_shipped_with_and_the_one_its_window_ended_with(self):
        self.build(1, '2026-10-01', {1: ['Sword', 1, 1.5], 2: ['Shield', 1, 1.5]})
        self.build(2, '2026-10-10', {1: ['Sword', 5, 1.5], 2: ['Shield', 1, 1.5]})
        newest = self.chain[-1]['dir']
        blob = cache(2, [(100, ITEM, 1, 1, item('Sword', 5)), (101, ITEM, 2, 1, item('Shield', 3))])
        with open(os.path.join(newest, hotfixes.FILE), 'wb') as handle:
            handle.write(blob)
        hotfixes.keep(newest, blob, '2026-10-14', 2)          # the cache the tracker downloaded itself
        dating.rebuild(self.chain, [], log=lambda *_: None)
        first = hotfixes.history_kept(self.chain[0]['dir'])
        shipped = hotfixes.parse(hotfixes._read(os.path.join(self.chain[0]['dir'], hotfixes.HISTORY, first[0]['file'])))
        ended = hotfixes.parse(hotfixes._read(os.path.join(self.chain[0]['dir'], hotfixes.FILE)))
        self.assertEqual((shipped[0], [r.push for r in shipped[1]]), (1, []))
        self.assertEqual((ended[0], [r.push for r in ended[1]]), (1, [100]))   # not the hotfix still to come (101)
        # the newest build: the build as it shipped first, then the download, which carries the hotfixes since
        kept = hotfixes.history(newest)
        self.assertEqual([(e.get('rebuilt'), e['read']) for e in kept], [('base', '2026-10-10'), (None, '2026-10-14')])
        self.assertEqual(kept[1]['window']['rows'], 1)
        # nothing changed: nothing written again
        self.assertEqual(dating.rebuild(self.chain, [], log=lambda *_: None)['code'], 3)
        # new notes only re-date the windows: the rows' windows are read back
        said = []
        self.assertEqual(dating.rebuild(self.chain, ['2026-10-12'], log=said.append)['code'], 0)
        self.assertIn('hotfix windows: read back (same cache, same builds)', said)

    def test_the_header_names_the_build_the_cache_is_written_for(self):
        blob = cache(70938, [(1, ITEM, 1, 1, item('A')), (2, ITEM, 2, 1, item('B')), (3, ITEM, 3, 1, item('C'))])
        build, records = hotfixes.parse(dating.write_cache(blob, 70707, {0, 2}))
        self.assertEqual((build, [r.record for r in records]), (70707, [1, 3]))

    def test_window_days(self):
        b, after = {'date': '2026-11-10'}, {'date': '2026-11-13'}
        self.assertEqual(dating._days(b, after, ['2026-11-09', '2026-11-11', '2026-11-12', '2026-11-13']),
                         ('2026-11-10', '2026-11-12', ['2026-11-11', '2026-11-12']))
        self.assertEqual(dating._days(b, after, []), ('2026-11-10', '2026-11-12', []))
        same_day = {'date': '2026-11-07'}
        self.assertEqual(dating._days(same_day, {'date': '2026-11-07'}, []), ('2026-11-07', '2026-11-07', []))


if __name__ == '__main__':
    unittest.main()
