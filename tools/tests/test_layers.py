"""python -m unittest discover -s tools/tests"""
import copy
import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import layers  # noqa: E402

NOW = datetime.datetime(2026, 11, 13, 5, 0, 0, tzinfo=datetime.timezone.utc)


def raw():
    with open(layers.REGISTRY, encoding='utf-8') as handle:
        return json.load(handle)


class RegistryFile(unittest.TestCase):
    def setUp(self):
        self.registry = layers.load()

    def test_shipped_registry_is_sound(self):
        self.assertEqual(layers.validate(raw()), [])

    def test_layer_order_is_lowest_first(self):
        keys = [layer['key'] for layer in self.registry.layers]
        self.assertEqual(keys, ['vanilla', 'base', 'season', 'client', 'live', 'corrections'])
        self.assertLess(self.registry.rank('vmangos'), self.registry.rank('core'))
        self.assertLess(self.registry.rank('core'), self.registry.rank('client'))
        self.assertLess(self.registry.rank('eglink'), self.registry.rank('forge'))

    def test_a_source_without_a_licence_is_never_public(self):
        for source in self.registry.sources.values():
            if source['licence'] in ('none', 'unknown'):
                self.assertNotEqual(source['use'], 'public', source['id'])

    def test_eg_link_and_icy_veins_are_one_witness(self):
        self.assertEqual(self.registry.witnesses(['eglink', 'icyveins']), 1)
        self.assertEqual(self.registry.witnesses(['eglink', 'foreverdb']), 2)

    def test_norgannondb_is_no_second_witness_beside_what_it_is_compiled_from(self):
        self.assertEqual(self.registry.witnesses(['questie', 'norgannondb']), 1)
        self.assertEqual(self.registry.witnesses(['norgannondb', 'cmangos']), 1)
        self.assertEqual(self.registry.witnesses(['norgannondb', 'dungeonjournal']), 1)
        self.assertEqual(self.registry.witnesses(['norgannondb', 'eglink']), 2)

    def test_sources_joined_through_a_third_are_one_witness(self):
        self.assertEqual(self.registry.witnesses(['questie', 'cmangos']), 2)
        self.assertEqual(self.registry.witnesses(['questie', 'cmangos', 'norgannondb']), 1)
        self.assertEqual(self.registry.witnesses(['cmangos', 'norgannondb', 'questie', 'eglink', 'icyveins']), 2)
        self.assertEqual(self.registry.witnesses([]), 0)

    def test_databaseforever_is_no_second_witness_beside_the_core(self):
        self.assertEqual(self.registry.witnesses(['core', 'databaseforever']), 1)

    def test_use_is_the_most_restricted_of_the_value_sources(self):
        self.assertEqual(self.registry.use(['eglink', 'questie']), 'public')
        self.assertEqual(self.registry.use(['eglink', 'icyveins']), 'private')
        self.assertEqual(self.registry.use(['icyveins', 'wowhead']), 'reference')
        self.assertTrue(self.registry.publishable(['eglink', 'foreverdb']))
        self.assertFalse(self.registry.publishable(['eglink', 'icyveins']))
        self.assertFalse(self.registry.publishable([]))

    def test_credits_follow_the_registry_order_once_each(self):
        credits = self.registry.credits(['questie', 'eglink', 'eglink', 'icyveins'])
        self.assertEqual(len(credits), 2)
        self.assertIn('Efficient Games', credits[0])
        self.assertIn('Questie', credits[1])

    def test_unknown_source_is_an_error(self):
        for ask in (self.registry.use, self.registry.witnesses, self.registry.credits):
            with self.assertRaises(KeyError):
                ask(['eglink', 'nobody'])


class Validation(unittest.TestCase):
    def broken(self, change):
        data = copy.deepcopy(raw())
        change(data)
        return layers.validate(data)

    def source(self, data, sid):
        return next(s for s in data['sources'] if s['id'] == sid)

    def test_public_needs_a_publishable_licence(self):
        problems = self.broken(lambda d: self.source(d, 'icyveins').update(use='public'))
        self.assertTrue(any('icyveins' in p and 'publishing' in p for p in problems), problems)

    def test_public_needs_a_credit_line(self):
        problems = self.broken(lambda d: self.source(d, 'eglink').pop('credit'))
        self.assertTrue(any('eglink' in p and 'credit' in p for p in problems), problems)

    def test_duplicate_unknown_layer_and_pin_type(self):
        self.assertTrue(any('twice' in p for p in self.broken(lambda d: d['sources'].append(copy.deepcopy(d['sources'][0])))))
        self.assertTrue(any('unknown layer' in p for p in self.broken(lambda d: self.source(d, 'eglink').update(layer='beta'))))
        self.assertTrue(any('pin type' in p for p in self.broken(lambda d: self.source(d, 'eglink').update(pin={'type': 'ftp'}))))

    def test_a_pin_needs_its_fields(self):
        problems = self.broken(lambda d: self.source(d, 'eglink').update(pin={'type': 'github-branch', 'repository': 'a/b'}))
        self.assertTrue(any('eglink' in p and 'needs repo' in p for p in problems), problems)

    def test_registry_refuses_to_load_when_unsound(self):
        data = raw()
        self.source(data, 'wowhead')['use'] = 'everything'
        with self.assertRaises(layers.RegistryError):
            layers.Registry(data)

    def test_a_malformed_registry_is_a_registry_error_not_a_crash(self):
        for change in (lambda d: d['layers'].append({'name': 'no key'}), lambda d: d['sources'].append('eglink'),
                       lambda d: self.source(d, 'eglink').update(pin='main'), lambda d: d.pop('layers')):
            data = raw()
            change(data)
            with self.assertRaises(layers.RegistryError):
                layers.Registry(data)
        with self.assertRaises(layers.RegistryError):
            layers.Registry([])


class Pins(unittest.TestCase):
    def answers(self, url):
        if url == 'https://api.github.com/repos/JIVESCORP/eg-link-output-wowf/commits/main':
            return {'sha': 'a' * 40, 'commit': {'committer': {'date': '2026-11-12T06:00:00Z'}}}
        if url == 'https://api.github.com/repos/vmangos/core/releases/tags/db_latest':
            return {'assets': [{'name': 'db-sqlite-1fb4909.zip', 'updated_at': '2026-11-11T23:41:00Z'},
                               {'name': 'db-1fb4909.zip', 'updated_at': '2026-11-11T23:40:00Z', 'size': 30511449,
                                'browser_download_url': 'https://example.invalid/db-1fb4909.zip'}]}
        if url == 'https://www.curseforge.com/api/v1/mods/1422985/files':
            return {'data': [{'id': 5, 'fileName': 'AtlasLoot-Classic-Forever-1.3.7.zip', 'dateCreated': '2026-11-12'},
                             {'id': 9, 'fileName': 'AtlasLoot-Classic-TBC-9.9.zip'},
                             {'id': 7, 'fileName': 'AtlasLoot-Classic-Forever-1.3.8.zip', 'dateCreated': '2026-11-13'}]}
        if url == 'https://wago.tools/api/builds':
            return {'wowf': [{'version': '1.60.1.70888'}, {'version': '1.60.1.70938', 'created_at': '2026-11-13 01:36:09'},
                             {'version': '1.60.1.9999'}], 'wow': [{'version': '12.0.0.99999'}]}
        raise OSError('unreachable ' + url)

    def digest(self, url):
        return 'c' * 64, 5300000

    def resolve(self, pin):
        return layers.resolve(pin, self.answers, self.digest)

    def test_github_branch(self):
        self.assertEqual(self.resolve({'type': 'github-branch', 'repo': 'JIVESCORP/eg-link-output-wowf', 'branch': 'main'}),
                         {'version': 'a' * 40, 'date': '2026-11-12T06:00:00Z'})

    def test_github_release_takes_the_asset_that_matches(self):
        found = self.resolve(layers.load().source('vmangos')['pin'])
        self.assertEqual((found['file'], found['version']), ('db-1fb4909.zip', 'db-1fb4909.zip@2026-11-11T23:40:00Z'))
        with self.assertRaises(LookupError):
            self.resolve({'type': 'github-release', 'repo': 'vmangos/core', 'tag': 'db_latest', 'asset': 'world.7z'})

    def test_a_release_file_rebuilt_under_the_same_name_moves_the_pin(self):
        registry, day = layers.load(), ['2026-11-12T14:05:00Z']

        def fetch(url):
            if 'cmangos' in url:
                return {'assets': [{'name': 'classic-world-db.zip', 'updated_at': day[0]}]}
            return self.answers(url)
        first = layers.pin_all(registry, only={'cmangos'}, fetch_json=fetch, fetch_digest=self.digest, now=NOW)
        day[0] = '2026-11-13T14:05:00Z'
        later = layers.pin_all(registry, first, only={'cmangos'}, fetch_json=fetch, fetch_digest=self.digest,
                               now=NOW + datetime.timedelta(days=1))
        self.assertEqual(layers.changed(first, later), ['cmangos'])
        self.assertEqual(later['sources']['cmangos']['pinned'], '2026-11-14T05:00:00Z')

    def test_curseforge_newest_forever_file_only(self):
        found = self.resolve({'type': 'curseforge', 'project': 1422985, 'name': 'AtlasLoot-Classic-Forever-'})
        self.assertEqual((found['version'], found['file']), ('7', 'AtlasLoot-Classic-Forever-1.3.8.zip'))

    def test_wago_newest_build_by_number_not_by_text(self):
        self.assertEqual(self.resolve({'type': 'wago-build', 'product': 'wowf'})['version'], '1.60.1.70938')
        self.assertEqual(layers._build_number('1.60.1.70938-ptr'), 70938)
        self.assertEqual(layers._build_number('1.60.1'), -1)
        with self.assertRaises(LookupError):
            layers.resolve({'type': 'wago-build', 'product': 'wowf'}, lambda url: {'wowf': [{'version': 'soon'}]})
        with self.assertRaises(LookupError):
            self.resolve({'type': 'wago-build', 'product': 'wow_none'})

    def test_url_is_pinned_by_its_content(self):
        found = self.resolve({'type': 'url', 'url': 'https://example.invalid/DBCache.bin'})
        self.assertEqual((found['version'], found['size']), ('c' * 16, 5300000))

    def test_nothing_to_look_up(self):
        self.assertIsNone(self.resolve({'type': 'none'}))
        self.assertIsNone(self.resolve({'type': 'replay'}))

    def test_shipped_pins_resolve_against_the_recorded_answers(self):
        registry = layers.load()
        for sid in ('eglink', 'vmangos', 'atlasloot', 'client'):
            self.assertTrue(self.resolve(registry.source(sid)['pin'])['version'], sid)

    def test_lock_keeps_the_previous_pin_of_an_unreachable_source(self):
        registry = layers.load()
        before = {'sources': {'questie': {'version': 'b' * 40, 'pinned': '2026-11-10T00:00:00Z'},
                              'eglink': {'version': 'old', 'pinned': '2026-11-10T00:00:00Z'}}}
        lock = layers.pin_all(registry, before, fetch_json=self.answers, fetch_digest=self.digest, now=NOW)
        self.assertEqual(lock['sources']['questie']['version'], 'b' * 40)        # Questie's address is not in answers()
        self.assertEqual(lock['sources']['questie']['pinned'], '2026-11-10T00:00:00Z')
        self.assertIn('unreachable', lock['sources']['questie']['error'])
        self.assertEqual(lock['sources']['eglink']['version'], 'a' * 40)
        self.assertEqual(lock['sources']['eglink']['pinned'], '2026-11-13T05:00:00Z')
        self.assertEqual(lock['sources']['icyveins']['use'], 'private')
        self.assertNotIn('version', lock['sources']['icyveins'])
        self.assertIn('eglink', layers.changed(before, lock))
        self.assertNotIn('questie', layers.changed(before, lock))

    def test_an_unchanged_version_keeps_its_first_pin_date(self):
        registry = layers.load()
        first = layers.pin_all(registry, fetch_json=self.answers, fetch_digest=self.digest, now=NOW)
        later = layers.pin_all(registry, first, fetch_json=self.answers, fetch_digest=self.digest,
                               now=NOW + datetime.timedelta(days=1))
        self.assertEqual(later['sources']['eglink']['pinned'], '2026-11-13T05:00:00Z')
        self.assertEqual(layers.changed(first, later), [])

    def test_only_limits_the_lookup(self):
        registry = layers.load()
        asked = []

        def fetch(url):
            asked.append(url)
            return self.answers(url)
        before = {'sources': {'questie': {'version': 'b' * 40, 'pinned': '2026-11-10T00:00:00Z', 'error': 'OSError: unreachable'},
                              'vmangos': {'version': 'db-0000000.zip@x', 'pinned': '2026-11-01T00:00:00Z'}}}
        lock = layers.pin_all(registry, before, only={'eglink'}, fetch_json=fetch, fetch_digest=self.digest, now=NOW)
        self.assertEqual(asked, ['https://api.github.com/repos/JIVESCORP/eg-link-output-wowf/commits/main'])
        self.assertEqual(lock['sources']['eglink']['version'], 'a' * 40)
        # the sources not asked keep their pins, and an error nobody retried stays noted
        self.assertEqual(lock['sources']['vmangos']['version'], 'db-0000000.zip@x')
        self.assertEqual(lock['sources']['questie']['version'], 'b' * 40)
        self.assertEqual(lock['sources']['questie']['error'], 'OSError: unreachable')
        self.assertEqual(set(lock['sources']), set(registry.sources))

    def test_a_source_with_nothing_to_pin_keeps_no_stale_version(self):
        registry = layers.load()
        before = {'sources': {'icyveins': {'version': 'old', 'sha256': 'd' * 64, 'pinned': '2026-11-01T00:00:00Z'}}}
        lock = layers.pin_all(registry, before, fetch_json=self.answers, fetch_digest=self.digest, now=NOW)
        self.assertEqual(lock['sources']['icyveins'], {'licence': 'none', 'use': 'private', 'group': 'eglink', 'layer': 'live'})

    def test_lock_round_trip(self):
        registry = layers.load()
        lock = layers.pin_all(registry, fetch_json=self.answers, fetch_digest=self.digest, now=NOW)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'world', 'layers.lock.json')
            self.assertEqual(layers.read_lock(path), {})
            layers.write_lock(path, lock)
            self.assertEqual(layers.read_lock(path), lock)
            here = os.getcwd()
            os.chdir(folder)
            try:
                layers.write_lock('lock.json', lock)            # a bare file name has no folder to make
                self.assertEqual(layers.read_lock('lock.json'), lock)
            finally:
                os.chdir(here)


if __name__ == '__main__':
    unittest.main()
