"""python -m unittest discover -s tools/tests

The official client from Blizzard's CDN (ft.client, ft.cdn): which build is stored and when, what happens to the parts
of a table nobody can read yet, and when a stored build is read again. No network: the reader is a dictionary.
"""
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import cdn, client, content  # noqa: E402

KEY_A, KEY_B = 0x0DA4670DB36FB2A9, 0xDA0E7785727A0A65


def table(layout, sections=((0, b'\x01\x02\x03\x04'),), table_hash=0x11111111):
    """A file with a WDC5 header, as far as ft.client reads one: the two hashes and the section headers.
    sections: (tact key, the section's bytes)."""
    head = bytearray(client.SECTIONS_AT)
    head[:4] = b'WDC5'
    struct.pack_into('<II', head, 136 + 16, table_hash, layout)
    struct.pack_into('<I', head, 136 + 36 + 4 + 24, len(sections))
    offset = client.SECTIONS_AT + len(sections) * client.SECTION.size
    headers, body = b'', b''
    for key, data in sections:
        headers += client.SECTION.pack(key, offset + len(body), 1, 0, 0, 0, 0, 0, 0)
        body += data
    return bytes(head) + headers + body


def blte_file(chunks):
    """A stored file with a chunk table. chunks: (stored bytes, plain size)."""
    header = 12 + 24 * len(chunks)
    out = b'BLTE' + struct.pack('>I', header) + b'\x0f' + len(chunks).to_bytes(3, 'big')
    for stored, plain in chunks:
        out += struct.pack('>II', len(stored), plain) + bytes(16)
    return out + b''.join(stored for stored, _plain in chunks)


def encrypted_chunk(key_name, size):
    name = bytes.fromhex(key_name)[::-1]
    return b'E' + bytes([len(name)]) + name + bytes([4]) + bytes(4) + b'S' + bytes(size)


class Blte(unittest.TestCase):
    def setUp(self):
        self.stored = blte_file([(b'N' + b'head', 4), (b'Z' + zlib.compress(b'plain text'), 10), (encrypted_chunk('0DA4670DB36FB2A9', 6), 6), (b'N' + b'tail', 4)])

    def test_a_part_nobody_can_read_stops_the_file(self):
        with self.assertRaises(cdn.Encrypted):
            cdn.blte(self.stored)

    def test_or_takes_its_place_as_zeros(self):
        absent = []
        self.assertEqual(cdn.blte(self.stored, None, absent), b'head' + b'plain text' + bytes(6) + b'tail')
        self.assertEqual(absent, ['0DA4670DB36FB2A9'])

    def test_a_file_without_such_a_part_is_whole(self):
        absent = []
        self.assertEqual(cdn.blte(blte_file([(b'N' + b'all of it', 9)]), None, absent), b'all of it')
        self.assertEqual(absent, [])


class Sections(unittest.TestCase):
    def test_a_readable_keyed_section_is_marked_as_the_extractor_marks_it(self):
        data, hidden = client.mark_decrypted(table(1, [(0, b'open'), (KEY_A, b'now readable'), (KEY_B, bytes(12))]))
        keys = [client.SECTION.unpack_from(data, client.SECTIONS_AT + i * client.SECTION.size)[0] for i in range(3)]
        self.assertEqual(keys, [0, client.DECRYPTED, KEY_B])   # the open one untouched, the readable one marked, the zeros left
        self.assertEqual(hidden, 1)

    def test_a_file_that_is_no_table_is_left_alone(self):
        self.assertEqual(client.mark_decrypted(b'not a table'), (b'not a table', 0))

    def test_the_hashes_of_a_table(self):
        self.assertEqual(client.header(table(0xD43AFAC3, table_hash=0xBD84CD62)), ('BD84CD62', 'D43AFAC3'))
        self.assertIsNone(client.header(b'WDC5 too short'))


class Layouts(unittest.TestCase):
    SCHEMA = {'Map': {'layoutHash': 'D43AFAC3'}, 'SpellDuration': {'layoutHash': 'A931BD2B'}, 'Item': {'layoutHash': '00000001'}}

    def test_the_layout_the_schema_names_or_the_one_read_today(self):
        tables = {'Map': table(0xD43AFAC3), 'SpellDuration': table(0x4FDF0951)}
        # the schema's hash for SpellDuration is an older one; the newest snapshot has 4FDF0951 and is read fine
        self.assertEqual(client.layout_problems(tables, {'SpellDuration': '4FDF0951'}, self.SCHEMA), [])
        self.assertEqual([name for name, _why in client.layout_problems(tables, {}, self.SCHEMA)], ['SpellDuration'])

    def test_a_table_blizzard_changed_is_named(self):
        problems = client.layout_problems({'Item': table(0x99999999)}, {'Item': '00000001'}, self.SCHEMA)
        self.assertEqual(problems[0][0], 'Item')
        self.assertIn('99999999', problems[0][1])

    def test_what_is_no_table_or_has_no_schema(self):
        problems = dict(client.layout_problems({'Map': b'garbage', 'Unknown': table(1)}, {}, self.SCHEMA))
        self.assertEqual(problems, {'Map': 'not a WDC5 table', 'Unknown': 'no schema for this table'})


class Fetch(unittest.TestCase):
    """Two tables stand for the 74; the builds folder is a temporary one."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = (client.BUILDS, content.BUILDS, client.files, client.db2.SCHEMA)
        client.BUILDS = content.BUILDS = self.folder.name
        client.files = lambda: {'Map': 10, 'Item': 20}
        client.db2.SCHEMA = {'Map': {'layoutHash': '000000AA'}, 'Item': {'layoutHash': '000000BB'}}
        self.files = {10: table(0xAA), 20: table(0xBB)}
        self.absent = {}
        self.log = []

    def tearDown(self):
        client.BUILDS, content.BUILDS, client.files, client.db2.SCHEMA = self.saved
        self.folder.cleanup()

    def fetch(self, build, **more):
        live = {'build': build, 'version': f'1.60.1.{build}', 'config': 'abcdef0123456789'}
        return client.fetch(live=live, reader=lambda file_id: self.files[file_id], waiting=lambda: self.absent, log=self.log.append, **more)

    def info(self, build):
        with open(os.path.join(self.folder.name, str(build), 'build.json'), encoding='utf-8') as handle:
            return json.load(handle)

    def test_a_new_build_is_stored(self):
        result = self.fetch(70938)
        self.assertEqual(result['code'], client.FETCHED)
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder.name, '70938', 'enUS'))), ['Item.db2', 'Map.db2'])
        self.assertIn('Blizzard CDN', self.info(70938)['source'])
        self.assertEqual(client.newest_snapshot(), 70938)
        self.assertEqual([name for name in os.listdir(self.folder.name) if name.startswith('.')], [])   # no scratch folder left

    def test_the_same_build_is_not_read_twice(self):
        self.fetch(70938)
        self.assertEqual(self.fetch(70938)['code'], client.UP_TO_DATE)
        self.assertEqual(self.fetch(70862)['code'], client.UP_TO_DATE)   # nor an older one

    def test_a_build_whose_table_changed_layout_is_refused(self):
        self.fetch(70862)
        self.files[20] = table(0xCC)
        result = self.fetch(70938)
        self.assertEqual(result['code'], client.REFUSED)
        self.assertEqual([name for name, _why in result['problems']], ['Item'])
        self.assertFalse(os.path.isdir(os.path.join(self.folder.name, '70938')))
        self.assertEqual(client.newest_snapshot(), 70862)

    def test_a_table_missing_from_the_build_refuses_it(self):
        self.fetch(70862)
        del self.files[10]
        result = client.fetch(live={'build': 70938, 'version': '1.60.1.70938', 'config': ''}, log=self.log.append,
                              reader=lambda file_id: self.files[file_id])
        self.assertEqual((result['code'], result['problems'][0]), (client.REFUSED, ('Map', 'not in this build')))

    def test_what_could_not_be_read_is_remembered_by_key(self):
        self.files[20] = table(0xBB, [(0, b'open'), (KEY_A, bytes(8))])
        self.absent = {20: ['0DA4670DB36FB2A9']}
        result = self.fetch(70938)
        self.assertIn('still hidden', result['message'])
        self.assertEqual(self.info(70938)['waiting'], {'Item': ['0DA4670DB36FB2A9']})
        self.assertEqual(client.waiting_keys(70938), {'Item': ['0DA4670DB36FB2A9']})

    def test_a_stored_build_is_read_again_when_its_key_is_published(self):
        self.files[20] = table(0xBB, [(0, b'open'), (KEY_A, bytes(8))])
        self.absent = {20: ['0DA4670DB36FB2A9']}
        self.fetch(70938)
        self.assertEqual(self.fetch(70938, published=lambda: {'FFFFFFFFFFFFFFFF': b''})['code'], client.UP_TO_DATE)
        # the key comes out: the section is readable now
        self.files[20] = table(0xBB, [(0, b'open'), (KEY_A, b'unlocked')])
        self.absent = {}
        result = self.fetch(70938, published=lambda: {'0da4670db36fb2a9': b''})
        self.assertEqual(result['code'], client.FETCHED)
        self.assertEqual(self.info(70938)['waiting'], {})
        with open(os.path.join(self.folder.name, '70938', 'enUS', 'Item.db2'), 'rb') as handle:
            data = handle.read()
        self.assertEqual(client.SECTION.unpack_from(data, client.SECTIONS_AT + client.SECTION.size)[0], client.DECRYPTED)
        self.assertEqual(self.fetch(70938, published=lambda: {'0DA4670DB36FB2A9': b''})['code'], client.UP_TO_DATE)   # nothing left to wait for

    def test_a_build_read_again_keeps_the_day_it_was_first_seen(self):
        self.fetch(70938)
        path = os.path.join(self.folder.name, '70938', 'build.json')
        info = self.info(70938)
        info.update(date='2026-11-01', note='the patch notes')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(info, handle)
        self.fetch(70938, force=True)
        self.assertEqual((self.info(70938)['date'], self.info(70938)['note']), ('2026-11-01', 'the patch notes'))

    def test_a_snapshot_of_the_servers_own_copy_waits_for_nothing(self):
        os.makedirs(os.path.join(self.folder.name, '70862', 'enUS'))
        self.assertEqual(client.waiting_keys(70862), {})
        self.assertEqual(client.unlocked(70862, {'0DA4670DB36FB2A9'}), [])


class Shipped(unittest.TestCase):
    def test_every_snapshot_table_has_a_file_id(self):
        files = client.files()
        self.assertEqual(sorted(files), sorted(content.TABLES))
        self.assertEqual((files['Map'], files['ItemSparse']), (1349477, 1572924))


if __name__ == '__main__':
    unittest.main()
