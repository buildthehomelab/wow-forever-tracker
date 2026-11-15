"""python -m unittest discover -s tools/tests

The changelog build after build (ft.content.changelog): what a build changed against the one before is worked out
once and kept in its folder, a resource that exists by hotfix alone is not "added", and thirty builds are never held
in memory at once. No game files: a build's official content is a small dictionary.
"""
import json
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
        self.origin = None

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
        found = content.changelog(self.builds, read=read, own=lambda folder: int(os.path.basename(folder)) in self.own, origin=self.origin)
        self.more = found[5]
        return found[:5]

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

    # ---- the double check: the first build and every build's changes give the newest build
    def test_the_changes_add_up_to_the_newest_build(self):
        self.run_it()
        found = self.more['replay']
        self.assertEqual((found['from'], found['to'], found['steps'], found['ok'], found['problems']), (100, 300, 2, True, []))
        self.assertEqual(found['kinds']['item'], {'start': 2, 'added': 2, 'alone': 0, 'removed': 1, 'end': 3, 'now': 3})
        self.assertIn('give build 300 exactly (3 resources)', content.replay_lines(self.more)[-1])

    def test_also_with_what_exists_by_hotfix_alone(self):
        self.alone[300] = {('item', 4)}
        self.run_it()
        self.assertEqual(self.more['replay']['kinds']['item'], {'start': 2, 'added': 1, 'alone': 1, 'removed': 1, 'end': 3, 'now': 3})
        self.assertTrue(self.more['replay']['ok'])

    def kept_of(self, number):
        path = os.path.join(self.folder.name, str(number), content.KEPT)
        with open(path, encoding='utf-8') as handle:
            return path, json.load(handle)

    def test_a_step_that_lost_a_change_is_noticed(self):
        self.run_it()
        path, kept = self.kept_of(200)
        kept['changes'] = [change for change in kept['changes'] if change[1] != 3]   # the Helm was never "added"
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(kept, handle)
        self.run_it()
        found = self.more['replay']
        self.assertFalse(found['ok'])
        self.assertIn('item 3: the newest build has it and no build added it', found['problems'])
        self.assertIn('do NOT give build 300', content.replay_lines(self.more)[0])

    def test_and_a_resource_that_is_not_what_the_changes_say(self):
        self.run_it()
        path, kept = self.kept_of(200)
        kept['changes'] = [change for change in kept['changes'] if change[1] != 1]   # the Sword's new level was never noted
        kept['prints']['item'].pop('1')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(kept, handle)
        self.run_it()
        self.assertEqual((self.more['replay']['ok'], self.more['replay']['wrong']), (False, 1))
        self.assertIn("item 1: it is not what the builds' changes add up to", self.more['replay']['problems'])

    # ---- the original game as the start (ft.vanilla): the first build is compared with it
    def with_the_original_game(self, step):
        path = os.path.join(self.folder.name, '50')
        os.makedirs(os.path.join(path, 'enUS'))
        self.builds.insert(0, {'build': 50, 'dir': path, 'baseline': 'vanilla', 'version': '1.13.2.50'})
        self.asked = []

        def origin(base, chain, late, load, log):
            self.asked.append((base['build'], [b['build'] for b in chain], late))
            return step
        self.origin = origin

    def test_the_first_build_is_compared_with_the_original_game(self):
        self.with_the_original_game({'counts': {'item': 2}, 'ids': {'item': [1, 9]}, 'minor': [['item', 9]], 'hidden': {'ItemSparse': 3}, 'alone': [],
                                     'changes': [['item', 1, 'modified', {'ilvl': [0, 1]}, 'Sword'], ['item', 2, 'added', {}, 'Shield'], ['item', 9, 'removed', {}, 'Old Sword']]})
        _newest, changes, first_seen, changed_in, _hot = self.run_it()
        self.assertEqual(self.asked, [(50, [100, 200, 300], {})])
        self.assertEqual(changes[:3], [(100, 50, 'item', 1, 'modified', {'ilvl': [0, 1]}, 'Sword'), (100, 50, 'item', 2, 'added', {}, 'Shield'),
                                       (100, 50, 'item', 9, 'removed', {}, 'Old Sword')])
        self.assertEqual(len(changes), 7)   # and the builds after it as before
        self.assertEqual(first_seen, {('item', 1): 50, ('item', 2): 100, ('item', 3): 200, ('item', 4): 300})   # the Sword is the original game's
        self.assertEqual((changed_in[('item', 1)], changed_in[('item', 2)]), (200, 200))   # the last build that touched it
        self.assertEqual(self.builds[0]['counts'], {'item': 2})
        self.assertEqual(self.more['minor'], {(100, 'item', 9)})
        self.assertEqual(self.more['baseline'], {'build': 50, 'version': '1.13.2.50', 'first': 100, 'hidden': {'ItemSparse': 3}, 'alone': 0, 'compared': True})
        found = self.more['replay']
        self.assertEqual((found['from'], found['steps'], found['ok']), (50, 3, True))
        self.assertEqual(found['kinds']['item'], {'start': 2, 'added': 3, 'alone': 0, 'removed': 2, 'end': 3, 'now': 3})
        self.assertIn('the original game and the changes of 3 build(s) give build 300 exactly', content.replay_lines(self.more)[-1])

    def test_what_the_original_game_had_and_a_hotfix_carries_is_neither_removed_nor_added(self):
        # the Boots: the original game's, in no table of any build, carried by a hotfix build 300 is the first to have stored
        self.alone[300] = {('item', 4)}
        self.with_the_original_game({'counts': {'item': 2}, 'ids': {'item': [1, 4]}, 'alone': [['item', 4]],
                                     'changes': [['item', 2, 'added', {}, 'Shield'], ['item', 4, 'modified', {'ilvl': [9, 1]}, 'Boots']]})
        _newest, changes, first_seen, _changed, by_hotfix = self.run_it()
        self.assertEqual(self.asked[0][2], {300: {('item', 4)}})   # the step is told which resources to take from their hotfix
        self.assertEqual([(build, change) for build, _b, _k, entity, change, _f, _n in changes if entity == 4], [(100, 'modified')])
        self.assertEqual((first_seen[('item', 4)], by_hotfix), (50, {'item': 1}))
        self.assertTrue(self.more['replay']['ok'], self.more['replay']['problems'])
        self.assertEqual(self.more['replay']['kinds']['item'], {'start': 2, 'added': 2, 'alone': 0, 'removed': 1, 'end': 3, 'now': 3})

    def test_a_step_from_the_original_game_that_does_not_give_the_first_build_is_noticed(self):
        self.with_the_original_game({'counts': {'item': 1}, 'ids': {'item': [1]}, 'alone': [], 'changes': []})   # the Shield is never added
        self.run_it()
        self.assertFalse(self.more['replay']['ok'])
        self.assertIn('item 2: build 100 has it and the step from the original game does not give it', self.more['replay']['problems'])

    def test_the_original_game_alone_is_no_changelog(self):
        self.builds = [{'build': 50, 'dir': self.builds[0]['dir'], 'baseline': 'vanilla'}]
        self.official[self.builds[0]['dir']] = {'item': {1: item('Sword')}, '_meta': {}}
        self.run_it()
        self.assertIsNone(self.more['baseline'])


if __name__ == '__main__':
    unittest.main()
