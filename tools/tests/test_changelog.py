"""python -m unittest discover -s tools/tests

The changelog build after build (ft.content.changelog): what a build changed against the one before is worked out
once and kept in its folder, a resource that exists by hotfix alone is not "added", and thirty builds are never held
in memory at once. No game files: a build's official content is a small dictionary.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import content  # noqa: E402


def item(name, level=1):
    return {'name': name, 'facts': {'name': name, 'ilvl': level}}


class Changelog(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.builds, self.official, self.read, self.own = [], {}, [], set()
        saved = content.hotfix_only
        self.addCleanup(lambda: setattr(content, 'hotfix_only', saved))
        self.alone = {}
        content.hotfix_only = lambda folder: self.alone.get(int(os.path.basename(folder)), set())
        self.build(100, {1: item('Sword'), 2: item('Shield')})
        self.build(200, {1: item('Sword', 5), 3: item('Helm')})
        self.build(300, {1: item('Sword', 5), 3: item('Helm'), 4: item('Boots')})

    def build(self, number, items):
        path = os.path.join(self.folder.name, str(number))
        os.makedirs(os.path.join(path, 'enUS'))
        with open(os.path.join(path, 'enUS', 'ItemSparse.db2'), 'wb') as handle:
            handle.write(b'table of build %d' % number)
        self.builds.append({'build': number, 'dir': path})
        self.official[path] = {'item': items, '_meta': {}}

    def run_it(self):
        self.read.clear()

        def read(folder):
            self.read.append(int(os.path.basename(folder)))
            return self.official[folder]
        return content.changelog(self.builds, read=read, own=lambda folder: int(os.path.basename(folder)) in self.own)

    def test_every_build_against_the_one_before(self):
        newest, changes, first_seen, changed_in, by_hotfix = self.run_it()
        self.assertIs(newest, self.official[self.builds[-1]['dir']])
        self.assertEqual([(build, before, kind, entity, change, name) for build, before, kind, entity, change, _fields, name in sorted(changes, key=lambda c: (c[0], c[3]))],
                         [(200, 100, 'item', 1, 'modified', 'Sword'), (200, 100, 'item', 2, 'removed', 'Shield'), (200, 100, 'item', 3, 'added', 'Helm'),
                          (300, 200, 'item', 4, 'added', 'Boots')])
        self.assertEqual(next(fields for _b, _p, _k, entity, _c, fields, _n in changes if entity == 1), {'ilvl': [1, 5]})
        self.assertEqual(first_seen, {('item', 1): 100, ('item', 2): 100, ('item', 3): 200, ('item', 4): 300})
        self.assertEqual(changed_in, {('item', 1): 200, ('item', 2): 200, ('item', 3): 200, ('item', 4): 300})
        self.assertEqual([b['counts'] for b in self.builds], [{'item': 2}, {'item': 2}, {'item': 3}])
        self.assertEqual(by_hotfix, {})

    def test_it_is_worked_out_once(self):
        first = self.run_it()
        self.assertEqual(sorted(set(self.read)), [100, 200, 300])
        again = self.run_it()
        self.assertEqual(self.read, [300])   # only the newest build is read: the analysis needs its content
        self.assertEqual(again[1:], first[1:])
        self.assertEqual([b['counts'] for b in self.builds], [{'item': 2}, {'item': 2}, {'item': 3}])

    def test_a_build_that_changed_is_worked_out_again_with_the_one_after(self):
        self.run_it()
        path = os.path.join(self.builds[1]['dir'], 'enUS', 'ItemSparse.db2')
        with open(path, 'wb') as handle:
            handle.write(b'read again from the CDN: a key came out')
        self.official[self.builds[1]['dir']]['item'][7] = item('Cloak')
        _newest, changes, first_seen, _changed, _hot = self.run_it()
        self.assertEqual(sorted(set(self.read)), [100, 200, 300])
        self.assertIn((200, 100, 'item', 7, 'added', {}, 'Cloak'), changes)
        self.assertIn((300, 200, 'item', 7, 'removed', {}, 'Cloak'), changes)
        self.assertEqual(first_seen[('item', 7)], 200)

    def test_a_build_between_two_stored_ones(self):
        self.run_it()
        self.build(150, {1: item('Sword'), 2: item('Shield'), 3: item('Helm')})
        self.builds.sort(key=lambda b: b['build'])
        _newest, changes, first_seen, _changed, _hot = self.run_it()
        self.assertNotIn(300, self.read[:-1])   # 300 against 200 stands as it was kept
        self.assertEqual(sorted((build, entity, change) for build, _before, _kind, entity, change, _f, _n in changes),
                         [(150, 3, 'added'), (200, 1, 'modified'), (200, 2, 'removed'), (300, 4, 'added')])
        self.assertEqual(first_seen[('item', 3)], 150)

    def test_a_build_with_the_same_tables_is_not_read(self):
        # Blizzard often ships a build that changes the program alone
        self.build(250, self.official[self.builds[1]['dir']]['item'])
        with open(os.path.join(self.builds[-1]['dir'], 'enUS', 'ItemSparse.db2'), 'wb') as handle:
            handle.write(b'table of build 200')
        self.builds.sort(key=lambda b: b['build'])
        _newest, changes, first_seen, _changed, _hot = self.run_it()
        self.assertEqual(self.read, [100, 200, 300])   # 300 is compared with what 200 holds: 250 holds the same
        self.assertEqual([c for c in changes if c[0] == 250], [])
        self.assertEqual(self.builds[2]['counts'], self.builds[1]['counts'])
        self.assertIn((300, 250, 'item', 4, 'added', {}, 'Boots'), changes)   # the next build is compared with it all the same

    def test_what_exists_by_hotfix_alone_is_not_added(self):
        # Boots are in no table of build 300: a hotfix carries them, and no earlier build has its hotfixes stored
        self.alone[300] = {('item', 4)}
        _newest, changes, first_seen, changed_in, by_hotfix = self.run_it()
        self.assertNotIn(4, [entity for _b, _p, _k, entity, _c, _f, _n in changes])
        self.assertEqual((first_seen[('item', 4)], by_hotfix), (100, {'item': 1}))   # known since the first build without its hotfixes
        self.assertNotIn(('item', 4), changed_in)

    def test_unless_the_build_before_has_its_own_hotfixes(self):
        self.alone[300] = {('item', 4)}
        self.own = {200}
        _newest, changes, first_seen, _changed, by_hotfix = self.run_it()
        self.assertIn((300, 200, 'item', 4, 'added', {}, 'Boots'), changes)
        self.assertEqual((first_seen[('item', 4)], by_hotfix), (300, {}))
        # kept the same way either way: which builds have their hotfixes is asked at each run
        self.own = set()
        self.assertEqual(self.run_it()[4], {'item': 1})

    def test_two_builds_at_most_are_held(self):
        held, most = set(), []
        forget = content.forget
        self.addCleanup(lambda: setattr(content, 'forget', forget))
        content.forget = lambda folder: held.discard(folder)

        def read(folder):
            held.add(folder)
            most.append(len(held))
            return self.official[folder]
        for number in range(400, 900, 100):
            self.build(number, {1: item('Sword', number)})
        content.changelog(self.builds, read=read, own=lambda folder: False)
        self.assertEqual(max(most), 2)


if __name__ == '__main__':
    unittest.main()
