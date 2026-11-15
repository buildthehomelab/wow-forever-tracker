"""python -m unittest discover -s tools/tests

The official client from Blizzard's CDN (ft.client, ft.cdn): which build is stored and when, what happens to the parts
of a table nobody can read yet, and when a stored build is read again. No network: the reader is a dictionary.
"""
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import cdn, client, content, hotfixes  # noqa: E402

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

    def hotfix_cache(self, build, keys):
        """Stores a hotfix cache with the snapshot: TactKey records {key number: (status, bytes)}."""
        blob = b'XFTH' + struct.pack('<II', 9, build) + bytes(32)
        for number, (status, data) in keys.items():
            blob += hotfixes.ENTRY.pack(b'XFTH', 0, 5, 0, hotfixes.TACT_KEY, number, len(data), status) + data
        with open(os.path.join(self.folder.name, str(build), hotfixes.FILE), 'wb') as handle:
            handle.write(blob)
        hotfixes._loaded.clear()

    def waiting_build(self):
        """Build 70938 stored with one section of Item under KEY_A, which the build's own table numbers 8334."""
        self.numbers = client.key_numbers
        client.key_numbers = lambda data: {'0DA4670DB36FB2A9': 8334, 'DA0E7785727A0A65': 8335}
        self.addCleanup(lambda: setattr(client, 'key_numbers', self.numbers))
        self.files[client.KEY_LOOKUP_FILE] = b'the lookup table'
        self.files[20] = table(0xBB, [(0, b'open'), (KEY_A, bytes(8))])
        self.absent = {20: ['0DA4670DB36FB2A9']}
        self.fetch(70938)

    def test_the_numbers_of_the_keys_waited_for_are_kept(self):
        self.waiting_build()
        self.assertEqual(self.info(70938)['key_ids'], {'0DA4670DB36FB2A9': 8334})   # not the 200 others
        self.assertEqual(client.key_ids(70938), {'0DA4670DB36FB2A9': 8334})
        self.assertIsNone(client.key_ids(70862))   # a snapshot stored before they were kept

    def test_a_key_blizzard_hands_out_by_hotfix_opens_the_build(self):
        self.waiting_build()
        nobody = lambda: {}   # the published list does not have it yet
        key = bytes(range(16))
        # hotfixes that say nothing of the key: a record of another key, and one whose content is withheld
        self.hotfix_cache(70938, {8335: (1, key), 8334: (4, b'')})
        self.assertEqual(self.fetch(70938, published=nobody)['code'], client.UP_TO_DATE)
        self.hotfix_cache(70938, {8334: (1, key)})
        self.assertEqual(client.hotfix_keys(70938), {'0DA4670DB36FB2A9': key})
        self.files[20] = table(0xBB, [(0, b'open'), (KEY_A, b'unlocked')])
        self.absent = {}
        given = {}
        result = self.fetch(70938, published=nobody, use_keys=given.update)
        self.assertEqual(result['code'], client.FETCHED)
        self.assertEqual(given, {'0DA4670DB36FB2A9': key})   # the reader got the key to decrypt with
        self.assertEqual((self.info(70938)['waiting'], self.info(70938)['key_ids']), ({}, {}))
        # the build's hotfixes are still with it: the CDN does not give them back
        self.assertTrue(os.path.isfile(os.path.join(self.folder.name, '70938', hotfixes.FILE)))

    def test_the_published_list_being_down_does_not_hide_a_hotfix_key(self):
        self.waiting_build()
        self.hotfix_cache(70938, {8334: (1, bytes(16))})

        def down():
            raise RuntimeError('HTTP 503')
        self.files[20] = table(0xBB, [(0, b'open'), (KEY_A, b'unlocked')])
        self.absent = {}
        self.assertEqual(self.fetch(70938, published=down)['code'], client.FETCHED)

    def test_a_new_build_is_read_with_the_keys_already_handed_out(self):
        self.waiting_build()
        self.hotfix_cache(70938, {8334: (1, b'k' * 16)})
        given = {}
        self.fetch(70999, use_keys=given.update)
        self.assertEqual(given, {'0DA4670DB36FB2A9': b'k' * 16})

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


class Check(unittest.TestCase):
    """"Check the client now" and the container's own check: the build, then the hotfixes, then whether to analyse."""

    def run_check(self, build, hot):
        lines, asked = [], []

        def one(name, answer):
            def ask():
                asked.append(name)
                if isinstance(answer, Exception):
                    raise answer
                return {'code': answer, 'message': name + ' ' + str(answer)}
            return ask
        return client.check(one('build', build), one('hotfixes', hot), lines.append), lines, asked

    def test_nothing_new_is_no_reason_to_analyse(self):
        new, lines, asked = self.run_check(client.UP_TO_DATE, 3)
        self.assertFalse(new)
        self.assertEqual(asked, ['build', 'hotfixes'])   # the build first: its hotfixes need its snapshot
        self.assertEqual(lines, ['client: build 3', 'hotfixes: hotfixes 3'])

    def test_a_new_build_or_new_hotfixes_call_for_the_analysis(self):
        self.assertTrue(self.run_check(client.FETCHED, 3)[0])
        self.assertTrue(self.run_check(client.UP_TO_DATE, 0)[0])
        self.assertFalse(self.run_check(client.REFUSED, 2)[0])   # a refused build and an unusable cache store nothing

    def test_a_server_that_does_not_answer_does_not_stop_the_other(self):
        new, lines, asked = self.run_check(RuntimeError('HTTP Error 503: Service Unavailable'), 0)
        self.assertTrue(new)
        # new hotfixes may hand out a key the build waits for: the build is asked once more after them
        self.assertEqual(asked, ['build', 'hotfixes', 'build'])
        new, lines, asked = self.run_check(client.FETCHED, OSError('Traceback of a proxy'))
        self.assertTrue(new)

    def test_its_lines_never_read_as_a_crash(self):
        # the website takes "Error" or "Traceback" in the run's log for a run that died (app/forge.php, analysis_status)
        _, lines, _ = self.run_check(RuntimeError('HTTP Error 503'), OSError('Traceback'))
        self.assertEqual(len(lines), 2)
        self.assertFalse(any('Error' in line or 'Traceback' in line for line in lines), lines)
        said = []
        client.calm(said.append)('URLError: <urlopen error timed out>')
        self.assertEqual(said, ['URLerror: <urlopen error timed out>'])


class Notes(unittest.TestCase):
    """What the Forge shows of the last check: when each of Blizzard's servers was asked and what it said."""

    def test_the_last_answer_of_each_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'client-check.json')
            client.noted('client', lambda: {'code': client.UP_TO_DATE, 'message': 'nothing to fetch'}, path)()
            client.note('hotfixes', '98863 records stored', 0, path, now=1000)
            client.note('hotfixes', 'have not changed', 3, path, now=2000)
            with open(path, encoding='utf-8') as handle:
                state = json.load(handle)
            self.assertEqual(state['hotfixes'], {'at': 2000, 'code': 3, 'message': 'have not changed'})
            self.assertEqual((state['client']['code'], state['client']['message']), (client.UP_TO_DATE, 'nothing to fetch'))

    def test_a_server_that_does_not_answer_is_noted_and_still_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'client-check.json')

            def down():
                raise RuntimeError('HTTP 503')
            with self.assertRaises(RuntimeError):
                client.noted('client', down, path)()
            with open(path, encoding='utf-8') as handle:
                self.assertEqual(json.load(handle)['client']['code'], None)
            client.note('client', 'x', 0, os.path.join(folder, 'no', 'such', 'folder.json'))   # cannot be written: no error


def listed(*entries):
    """The public list as cdn.builds() returns it: (build, product, day)."""
    return lambda: [{'build': build, 'version': f'1.60.1.{build}', 'config': f'{build:032x}', 'cdn': f'{build + 1:032x}', 'date': day, 'product': product}
                    for build, product, day in entries]


class BuildList(unittest.TestCase):
    """Which builds came before: the public list, taken only in the shape it must have."""

    def rows(self):
        row = lambda version, day, config='a' * 32, **more: {'version': version, 'created_at': day + ' 01:02:03', 'build_config': config, 'cdn_config': 'c' * 32, 'is_bgdl': False, **more}
        return json.dumps({
            'wowf': [row('1.60.1.70938', '2026-11-13'), row('1.60.1.70245', '2026-10-13'), row('1.60.1.70900', '2026-11-11', is_bgdl=True)],
            'wow_classic_beta': [row('5.5.0.62071', '2025-07-18'), row('1.60.1.70245', '2026-10-06', 'b' * 32), row('1.60.1.69876', '2026-09-16'),
                                 row('1.60.1.69900', '2026-09-17', '../../etc/passwd'), row('1.60.1.x', '2026-09-17')],
            'wow': [row('12.0.0.70000', '2026-09-01')]}).encode()

    def test_the_products_builds_oldest_first(self):
        found = cdn.builds({'wowf': '', 'wow_classic_beta': '1.60.'}, fetch=lambda url: self.rows())
        self.assertEqual([b['build'] for b in found], [69876, 70245, 70938])   # no other game's beta, no background download
        self.assertEqual(found[0], {'build': 69876, 'version': '1.60.1.69876', 'config': 'a' * 32, 'cdn': 'c' * 32, 'date': '2026-09-16', 'product': 'wow_classic_beta'})

    def test_a_build_two_products_had_is_the_first_ones(self):
        found = {b['build']: b for b in cdn.builds({'wowf': '', 'wow_classic_beta': '1.60.'}, fetch=lambda url: self.rows())}
        self.assertEqual((found[70245]['product'], found[70245]['date'], found[70245]['config']), ('wow_classic_beta', '2026-10-06', 'b' * 32))

    def test_a_name_that_is_no_name_is_left_out(self):
        found = cdn.builds({'wow_classic_beta': ''}, fetch=lambda url: self.rows())
        self.assertNotIn(69900, [b['build'] for b in found])   # what goes into an address is 32 hex digits or nothing

    def test_what_the_setting_names(self):
        self.assertEqual(client.history_products('wowf', 'wow_classic_beta:1.60.'), {'wowf': '', 'wow_classic_beta': '1.60.'})
        self.assertEqual(client.history_products('wowf', ''), {'wowf': ''})
        self.assertIsNone(client.history_products('wowf', 'off'))


def stored_file(data):
    return blte_file([(b'N' + data, len(data))])


class FakeCdn:
    """A build on two hosts: its two config files, an encoding file in four chunks, a root file and an archive."""

    def __init__(self, tables, split=False):
        self.files, self.asked = {}, []
        ckeys = {fdid: hashlib.md5(data).digest() for fdid, data in tables.items()}
        ids = sorted(tables)
        root = b'TSFM' + struct.pack('<II', 100, 100) + struct.pack('<III', len(ids), 0, cdn.ENUS)
        root += b''.join(struct.pack('<i', fdid - (ids[i - 1] if i else -1) - 1) for i, fdid in enumerate(ids))
        root += b''.join(ckeys[fdid] for fdid in ids) + bytes(8 * len(ids))
        self.root = hashlib.md5(root).digest()
        plain = {self.root: root, **{ckeys[fdid]: tables[fdid] for fdid in ids}}
        archive, entries, pages = b'', [], []
        for ckey in sorted(plain):
            stored = stored_file(plain[ckey])
            ekey = hashlib.md5(stored).digest()
            entries.append((ekey, len(stored), len(archive)))
            archive += stored
            # one content key a page: the page is found by its first key
            pages.append((ckey, (bytes([1]) + len(plain[ckey]).to_bytes(5, 'big') + ckey + ekey).ljust(1024, b'\0')))
        block = b''.join(ekey + struct.pack('>II', size, offset) for ekey, size, offset in sorted(entries)).ljust(4096, b'\0')
        index = block + bytes(24) + bytes(8) + struct.pack('<8BI', 1, 0, 0, 4, 4, 4, 16, 8, len(entries)) + bytes(8)
        espec = b'z\0' * 40
        head = b'EN' + struct.pack('>BBBHHIIBI', 1, 16, 16, 1, 1, len(pages), 0, 0, len(espec))
        listing = b''.join(first + hashlib.md5(page).digest() for first, page in pages)
        body = b''.join(page for _first, page in pages)
        self.encoding = blte_file([(b'N' + head, len(head)), (b'Z' + zlib.compress(espec), len(espec)), (b'N' + listing, len(listing)), (b'N' + body, len(body))])
        self.pages_at = len(self.encoding) - len(body)
        first, second = ('old.example', 'new.example') if split else ('old.example', 'old.example')
        self.files[(second, 'config/' + 'b' * 32)] = ('root = %s\nencoding = %s %s\n' % (self.root.hex(), '0' * 32, 'e' * 32)).encode()
        self.files[(first, 'config/' + 'c' * 32)] = b'archives = ' + b'a' * 32 + b'\n'
        self.files[(first, 'data/' + 'e' * 32)] = self.encoding
        self.files[(first, 'data/' + 'a' * 32)] = archive
        self.files[(first, 'data/' + 'a' * 32 + '.index')] = index

    def get(self, url, headers=None, tries=5):
        if url.endswith('/cdns'):
            return b'Name!STRING:0|Path!STRING:0|Hosts!STRING:0\nus|tpr/wow|old.example new.example\n'
        host, _slash, rest = url[len('http://'):].partition('/')
        parts = rest.split('/')
        data = self.files.get((host, parts[2] + '/' + parts[5]))
        if data is None:
            raise cdn.Gone(url)
        if headers and 'Range' in headers:
            first, last = map(int, headers['Range'][len('bytes='):].split('-'))
            data = data[first:last + 1]
        self.asked.append((parts[2] + '/' + parts[5], len(data)))
        return data


class EarlierBuild(unittest.TestCase):
    """A build that is no longer live, read for a few files (ft.cdn.Earlier). No network: the CDN is a dictionary."""

    PIN = {'config': 'b' * 32, 'cdn': 'c' * 32, 'version': '1.60.1.69876'}
    TABLES = {10: b'the map table', 20: b'the item table' * 40, 45: b'a third'}

    def open(self, fake):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        saved = cdn.get, cdn.PAUSE
        self.addCleanup(lambda: (setattr(cdn, 'get', saved[0]), setattr(cdn, 'PAUSE', saved[1])))
        cdn.get, cdn.PAUSE = fake.get, 0
        return cdn.Earlier(self.folder.name, self.PIN, log=lambda text: None)

    def test_the_files_asked_for_are_read_and_checked(self):
        fake = FakeCdn(self.TABLES)
        build = self.open(fake)
        build.prepare([10, 20, 99])
        self.assertEqual(build.read(10), self.TABLES[10])
        self.assertEqual(build.read(20), self.TABLES[20])
        with self.assertRaises(KeyError):
            build.read(99)       # not in this build
        with self.assertRaises(KeyError):
            build.read(45)       # in the build, never asked for

    def test_the_encoding_file_is_never_read_whole(self):
        fake = FakeCdn(self.TABLES)
        build = self.open(fake)
        build.prepare([10])
        parts = [size for name, size in fake.asked if name == 'data/' + 'e' * 32]
        # its start, its list of pages, and of its four pages the two that hold the root file's key and the table's
        self.assertEqual(parts.count(1024), 2)
        self.assertEqual(max(parts[1:]), 1024)

    def test_a_page_that_is_not_what_its_checksum_says_stops_the_build(self):
        fake = FakeCdn(self.TABLES)
        name = ('old.example', 'data/' + 'e' * 32)
        fake.files[name] = fake.files[name][:fake.pages_at + 30] + b'\xff' + fake.files[name][fake.pages_at + 31:]
        with self.assertRaises(RuntimeError):
            self.open(fake).prepare([10, 20, 45])

    def test_a_file_one_host_no_longer_has_is_asked_of_the_next(self):
        build = self.open(FakeCdn(self.TABLES, split=True))   # the build config is on the second host only
        build.prepare([10])
        self.assertEqual(build.read(10), self.TABLES[10])

    def test_a_file_no_host_has_is_gone(self):
        fake = FakeCdn(self.TABLES)
        del fake.files[('old.example', 'config/' + 'c' * 32)]
        with self.assertRaises(cdn.Gone):
            self.open(fake)

    def test_an_index_names_only_the_keys_it_has(self):
        fake = FakeCdn(self.TABLES)
        index = fake.files[('old.example', 'data/' + 'a' * 32 + '.index')]
        every = {ekey: (size, offset) for ekey, size, offset in cdn.index_entries(index)}
        self.assertEqual(len(every), 4)
        self.assertEqual(cdn.index_find(index, set(every) | {bytes(16), b'\xff' * 16}), every)


class History(unittest.TestCase):
    """The builds before the newest snapshot, for the changelog (ft.client.history). Two compared tables and one the
    tooltips read stand for the 74."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = (client.BUILDS, content.BUILDS, client.files, client.db2.SCHEMA)
        client.BUILDS = content.BUILDS = self.folder.name
        client.files = lambda: {'Map': 10, 'Item': 20, 'ItemSet': 30}
        client.db2.SCHEMA = {'Map': {'layoutHash': '000000AA'}, 'Item': {'layoutHash': '000000BB'}, 'ItemSet': {'layoutHash': '000000DD'}}
        self.files = {10: table(0xAA), 20: table(0xBB), 30: table(0xDD)}
        self.by_build, self.opened, self.log = {}, [], []
        self.refusals = os.path.join(self.folder.name, 'history.json')
        live = {'build': 70938, 'version': '1.60.1.70938', 'config': 'abcdef0123456789'}
        client.fetch(live=live, reader=lambda file_id: self.files[file_id], waiting=dict, log=self.log.append)

    def tearDown(self):
        client.BUILDS, content.BUILDS, client.files, client.db2.SCHEMA = self.saved
        self.folder.cleanup()

    def opener(self, entry):
        self.opened.append(entry['build'])
        files = self.by_build.get(entry['build'], self.files)
        if isinstance(files, Exception):
            raise files
        return (lambda file_id: files[file_id]), dict, None

    def history(self, entries, **more):
        return client.history(product='wowf', listed=listed(*entries), opener=self.opener, log=self.log.append, path=self.refusals, **more)

    def info(self, build):
        with open(os.path.join(self.folder.name, str(build), 'build.json'), encoding='utf-8') as handle:
            return json.load(handle)

    LIST = [(69876, 'wow_classic_beta', '2026-09-16'), (70790, 'wowf', '2026-11-04'), (70938, 'wowf', '2026-11-13'), (71000, 'wowf', '2026-11-20')]

    def test_the_builds_before_the_newest_snapshot_are_stored(self):
        result = self.history(self.LIST)
        self.assertEqual((result['code'], result['stored']), (client.FETCHED, [69876, 70790]))   # not the one after: that is fetch's
        self.assertEqual(self.opened, [69876, 70790])
        self.assertEqual([b['build'] for b in content.builds()], [69876, 70790, 70938])
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder.name, '69876', 'enUS'))), ['Item.db2', 'Map.db2'])   # the compared tables only
        beta, live = self.info(69876), self.info(70790)
        self.assertEqual((beta['date'], beta['tables'], beta['note']), ('2026-09-16', 'changelog', 'Beta build.'))
        self.assertEqual((live['date'], live.get('note')), ('2026-11-04', None))
        self.assertIn('wow_classic_beta', beta['source'])

    def test_each_is_read_once(self):
        self.history(self.LIST)
        self.opened.clear()
        result = self.history(self.LIST)
        self.assertEqual((result['code'], result['stored'], self.opened), (client.UP_TO_DATE, [], []))

    def test_a_build_with_another_table_layout_is_not_stored_and_not_asked_again(self):
        self.by_build[70790] = {10: table(0xCC), 20: table(0xBB)}
        result = self.history(self.LIST)
        self.assertEqual((result['stored'], list(result['refused'])), ([69876], [70790]))
        self.assertIn('Map', result['refused'][70790])
        self.assertFalse(os.path.isdir(os.path.join(self.folder.name, '70790')))
        self.opened.clear()
        self.assertEqual(self.history(self.LIST)['code'], client.UP_TO_DATE)
        self.assertEqual(self.opened, [])
        del self.by_build[70790]                       # ... until it is asked for again
        self.assertEqual(self.history(self.LIST, again=True)['stored'], [70790])
        self.assertEqual(self.history(self.LIST)['refused'], {})

    def test_a_build_that_could_not_be_reached_is_tried_at_the_next_call(self):
        self.by_build[69876] = RuntimeError('timed out')
        result = self.history(self.LIST)
        self.assertEqual((result['stored'], list(result['failed'])), ([70790], [69876]))
        del self.by_build[69876]
        self.assertEqual(self.history(self.LIST)['stored'], [69876])

    def test_a_server_in_trouble_is_left_alone_after_three_builds(self):
        entries = [(build, 'wowf', '2026-10-01') for build in (70001, 70002, 70003, 70004)] + [(70938, 'wowf', '2026-11-13')]
        for build in (70001, 70002, 70003, 70004):
            self.by_build[build] = OSError('unreachable')
        self.history(entries)
        self.assertEqual(self.opened, [70001, 70002, 70003])
        self.opened.clear()
        for build in (70001, 70002, 70003):
            self.by_build[build] = cdn.Gone('403')   # a build taken off the CDN is an answer: the next one is still asked
        del self.by_build[70004]
        self.assertEqual(self.history(entries)['stored'], [70004])

    def test_a_stored_build_takes_the_day_the_list_says(self):
        self.assertNotEqual(self.info(70938)['date'], '2026-11-13')   # stored today
        result = self.history([(70938, 'wowf', '2026-11-13')])
        self.assertEqual((self.info(70938)['date'], result['code']), ('2026-11-13', client.FETCHED))
        self.assertEqual(self.history([(70938, 'wowf', '2026-11-13')])['code'], client.UP_TO_DATE)

    def test_the_live_build_is_still_checked_against_a_whole_snapshot(self):
        self.history(self.LIST)
        self.assertTrue(content.builds()[1]['partial'])
        self.assertEqual(client.snapshot_layouts(), {'Map': '000000AA', 'Item': '000000BB', 'ItemSet': '000000DD'})
        # the newest build read again: the witness for its layouts is not the changelog-only build before it
        files = dict(self.files)
        files[30] = table(0xEE)
        again = client.fetch(live={'build': 71000, 'version': '1.60.1.71000', 'config': 'ab'}, reader=lambda file_id: files[file_id], waiting=dict, log=self.log.append)
        self.assertEqual(again['code'], client.REFUSED)

    def test_one_run_at_a_time(self):
        held = client.alone_here('history.lock')
        try:
            result = self.history(self.LIST)
        finally:
            held.close()
        self.assertEqual((result['code'], result['stored'], self.opened), (client.UP_TO_DATE, [], []))
        self.assertEqual(self.history(self.LIST)['stored'], [69876, 70790])

    def test_switched_off(self):
        saved = client.history_products
        client.history_products = lambda product=None, setting=None: None
        try:
            self.assertEqual(self.history(self.LIST)['code'], client.UP_TO_DATE)
        finally:
            client.history_products = saved
        self.assertEqual(self.opened, [])

    def test_the_check_asks_for_them_last(self):
        asked = []
        one = lambda name, code: lambda: asked.append(name) or {'code': code, 'message': name}
        self.assertTrue(client.check(one('build', client.UP_TO_DATE), one('hotfixes', 3), self.log.append, one('history', client.FETCHED)))
        self.assertEqual(asked, ['build', 'hotfixes', 'history'])

        def down():
            raise RuntimeError('HTTP Error 503')
        lines = []
        self.assertFalse(client.check(one('build', client.UP_TO_DATE), one('hotfixes', 3), lines.append, down))
        self.assertFalse(any('Error' in line for line in lines), lines)


class Shipped(unittest.TestCase):
    def test_every_snapshot_table_has_a_file_id(self):
        files = client.files()
        self.assertEqual(sorted(files), sorted(content.TABLES))
        self.assertEqual((files['Map'], files['ItemSparse']), (1349477, 1572924))


if __name__ == '__main__':
    unittest.main()
