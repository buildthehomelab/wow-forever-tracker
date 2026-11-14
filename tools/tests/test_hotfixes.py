"""python -m unittest discover -s tools/tests

Blizzard's hotfixes over the official list (ft.hotfixes): reading the cache, reading one record with a table's
schema, and which word is the last one when a table, its hotfixes and an older build's hotfixes speak of the same row.
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import hotfixes  # noqa: E402

ITEM = 0x1111
# a table that keeps its ids apart: a name, a level, a price
META = {'index': -1, 'fieldCount': 3, 'fileFieldCount': 3,
        'fields': [{'type': 'string', 'array': 1, 'signed': True}, {'type': 'short', 'array': 1, 'signed': True}, {'type': 'float', 'array': 1, 'signed': True}]}
NAMES = ['ID', 'Name', 'Level', 'Price']


def cache(build, entries):
    """A hotfix cache. entries: (push, table hash, record id, status, record bytes)."""
    out = b'XFTH' + struct.pack('<II', 9, build) + bytes(32)
    for push, table, record, status, data in entries:
        out += hotfixes.ENTRY.pack(b'XFTH', 0, push, 0, table, record, len(data), status) + data
    return out


def item(name, level=1, price=1.5):
    return name.encode() + b'\0' + struct.pack('<hf', level, price)


class Table:
    """What overlay needs of an ft.db2.Table."""
    name, table_hash, meta = 'Item', ITEM, META
    columns = [(name, None) for name in NAMES]


class Cache(unittest.TestCase):
    def test_records_in_file_order(self):
        build, records = hotfixes.parse(cache(70938, [(5, ITEM, 1, 1, b'abc'), (6, ITEM, 2, 2, b'')]))
        self.assertEqual(build, 70938)
        self.assertEqual([(r.push, r.record, r.status, r.data) for r in records], [(5, 1, 1, b'abc'), (6, 2, 2, b'')])

    def test_what_is_no_whole_cache_is_refused(self):
        for blob in (b'', b'nope' + bytes(60), cache(1, [])[:20], cache(1, [(1, ITEM, 1, 1, b'abcdef')])[:-3],
                     b'XFTH' + struct.pack('<II', 8, 1) + bytes(32)):
            with self.assertRaises(hotfixes.CacheError):
                hotfixes.parse(blob)

    def test_the_later_push_is_the_last_word(self):
        _build, records = hotfixes.parse(cache(1, [(9, ITEM, 1, 1, b'new'), (3, ITEM, 1, 1, b'old'), (-1, ITEM, 2, 1, b'asked'), (4, ITEM, 2, 2, b''),
                                                    (7, ITEM, 3, 1, b'first'), (7, ITEM, 3, 1, b'second')]))
        latest = hotfixes.newest(records)[ITEM]
        self.assertEqual(latest[1].data, b'new')          # push 9 over push 3, whatever their order in the file
        self.assertEqual(latest[2].status, hotfixes.REMOVED)   # a push over an answer sent without one (-1)
        self.assertEqual(latest[3].data, b'second')       # the same push twice: the later in the file


class Decode(unittest.TestCase):
    def test_a_table_that_keeps_its_ids_apart(self):
        self.assertEqual(hotfixes.decode(item('Carving Knife', 5, 2.25), META, 2140, NAMES), {'ID': 2140, 'Name': 'Carving Knife', 'Level': 5, 'Price': 2.25})

    def test_an_id_among_the_fields_and_a_parent_last(self):
        meta = {'index': 0, 'fieldCount': 3, 'fileFieldCount': 2,
                'fields': [{'type': 'int', 'array': 1, 'signed': False}, {'type': 'byte', 'array': 2, 'signed': False}, {'type': 'int', 'array': 1, 'signed': False}]}
        row = hotfixes.decode(struct.pack('<IBBI', 77, 1, 2, 900), meta, 77, ['ID', 'A1', 'A2', 'SpellID'])
        self.assertEqual(row, {'ID': 77, 'A1': 1, 'A2': 2, 'SpellID': 900})

    def test_negative_numbers_as_the_table_reader_gives_them(self):
        meta = {'index': -1, 'fieldCount': 2, 'fileFieldCount': 2,
                'fields': [{'type': 'int', 'array': 1, 'signed': True}, {'type': 'long', 'array': 1, 'signed': True}]}
        row = hotfixes.decode(struct.pack('<iq', -5, -1), meta, 1, ['ID', 'Signed', 'Mask'])
        self.assertEqual((row['Signed'], row['Mask']), (-5, 2 ** 64 - 1))   # ft.db2 never takes a 64-bit value as negative

    def test_bytes_that_do_not_fit_the_layout_are_no_row(self):
        whole = item("Seer's Cape")
        self.assertIsNone(hotfixes.decode(whole + b'\x00', META, 1, NAMES))      # one byte too many
        self.assertIsNone(hotfixes.decode(whole[:-1], META, 1, NAMES))            # one too few
        self.assertIsNone(hotfixes.decode(b'no end of text', META, 1, NAMES))     # text that never ends

    def test_names_that_do_not_match_fall_back_to_numbered_columns(self):
        self.assertEqual(sorted(hotfixes.decode(item('x'), META, 9, ['ID', 'OnlyOne'])), ['ID', 'f0', 'f1', 'f2'])


class Overlay(unittest.TestCase):
    """builds/<build>/hotfixes.bin over a table's rows."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        hotfixes._loaded.clear(); hotfixes.STATS.clear(); hotfixes.ORIGIN.clear()
        self.rows = [{'ID': 1, 'Name': 'Worn Sword', 'Level': 1, 'Price': 1.5}, {'ID': 2, 'Name': 'Bent Staff', 'Level': 1, 'Price': 1.5},
                     {'ID': 3, 'Name': 'Old Shield', 'Level': 1, 'Price': 1.5}]

    def tearDown(self):
        self.folder.cleanup()
        hotfixes._loaded.clear(); hotfixes.STATS.clear(); hotfixes.ORIGIN.clear()

    def build(self, number, entries=None, cache_build=None):
        path = os.path.join(self.folder.name, str(number))
        os.makedirs(path, exist_ok=True)
        if entries is not None:
            with open(os.path.join(path, hotfixes.FILE), 'wb') as handle:
                handle.write(cache(cache_build or number, entries))
        return path

    def names(self, folder):
        return {row['ID']: row['Name'] for row in hotfixes.overlay(folder, Table, [dict(r) for r in self.rows])}

    def test_a_hotfix_stands_over_its_builds_table(self):
        folder = self.build(70938, [(5, ITEM, 1, 1, item('Sharp Sword', 2)), (5, ITEM, 2, 2, b''), (5, ITEM, 2140, 1, item('Carving Knife')),
                                    (5, ITEM, 3, 3, b''), (5, ITEM, 9, 4, b''), (5, ITEM, 8, 1, b'garbage'), (5, 0x9999, 1, 1, b'another table')])
        self.assertEqual(self.names(folder), {1: 'Sharp Sword', 3: 'Old Shield', 2140: 'Carving Knife'})
        self.assertEqual(hotfixes.STATS[folder]['Item'], [1, 1, 1, 1])     # added, changed, removed, not read
        self.assertIn('Item +1 ~1 -1 (!1 not read)', hotfixes.summary(folder))

    def test_a_record_that_says_what_the_table_says_changes_nothing(self):
        folder = self.build(70938, [(5, ITEM, 1, 1, item('Worn Sword'))])
        self.assertEqual(self.names(folder)[1], 'Worn Sword')
        self.assertEqual(hotfixes.summary(folder), '')

    def test_a_cache_of_another_build_in_the_folder_is_not_used(self):
        folder = self.build(70938, [(5, ITEM, 1, 1, item('From Elsewhere'))], cache_build=70862)
        self.assertEqual(self.names(folder)[1], 'Worn Sword')

    def test_no_cache_no_change(self):
        self.assertEqual(self.names(self.build(70938)), {1: 'Worn Sword', 2: 'Bent Staff', 3: 'Old Shield'})

    def test_a_newer_build_stands_over_an_older_builds_hotfixes(self):
        # build 70938 had hotfixes; 70950 has shipped and its own cache has not arrived yet
        self.build(70938, [(5, ITEM, 1, 1, item('Renamed By Old Hotfix')), (5, ITEM, 2, 2, b''), (5, ITEM, 2140, 1, item('Carving Knife'))])
        newer = self.build(70950)
        got = self.names(newer)
        self.assertEqual(got[1], 'Worn Sword')        # the new table has the row: it is the later word
        self.assertEqual(got[2], 'Bent Staff')        # and nothing the new table has is taken away
        self.assertEqual(got[2140], 'Carving Knife')  # a row only the hotfix knows stands until the new cache says otherwise
        self.assertIn('carried over from build 70938', hotfixes.summary(newer))

    def test_its_own_cache_then_says_everything(self):
        self.build(70938, [(5, ITEM, 2140, 1, item('Carving Knife'))])
        newer = self.build(70950, [(9, ITEM, 1, 1, item('Renamed In 70950'))])
        self.assertEqual(self.names(newer), {1: 'Renamed In 70950', 2: 'Bent Staff', 3: 'Old Shield'})   # 2140 is not carried over any more

    def test_an_older_build_never_gets_a_newer_builds_hotfixes(self):
        older = self.build(70862)
        self.build(70938, [(5, ITEM, 2140, 1, item('Carving Knife'))])
        self.assertNotIn(2140, self.names(older))


class Fetch(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.folder.name, '70938'))
        self.blob = cache(70938, [(5, ITEM, 1, 1, item('x'))])
        hotfixes._loaded.clear()

    def tearDown(self):
        self.folder.cleanup()

    def fetch(self, blob=None, builds=(70938,)):
        return hotfixes.fetch(self.folder.name, set(builds), get=lambda url: self.blob if blob is None else blob)

    def test_stored_with_the_snapshot_of_its_build(self):
        result = self.fetch()
        self.assertEqual((result['code'], result['build'], result['records']), (0, 70938, 1))
        self.assertTrue(os.path.isfile(os.path.join(self.folder.name, '70938', hotfixes.FILE)))
        self.assertEqual(self.fetch()['code'], 3)     # the same cache again: nothing to do

    def test_new_records_replace_the_stored_cache(self):
        self.fetch()
        self.assertEqual(self.fetch(cache(70938, [(5, ITEM, 1, 1, item('x')), (6, ITEM, 2, 1, item('y'))]))['code'], 0)

    def test_a_cache_of_a_build_without_a_snapshot_is_not_stored(self):
        result = self.fetch(cache(70950, []))
        self.assertEqual(result['code'], 2)
        self.assertIn('70950', result['message'])
        self.assertFalse(os.path.isdir(os.path.join(self.folder.name, '70950')))

    def test_what_is_no_cache_is_not_stored(self):
        self.assertEqual(self.fetch(b'<html>not found</html>')['code'], 2)
        self.assertFalse(os.path.isfile(os.path.join(self.folder.name, '70938', hotfixes.FILE)))


if __name__ == '__main__':
    unittest.main()
