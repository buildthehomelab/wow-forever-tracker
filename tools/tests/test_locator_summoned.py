"""python -m unittest discover -s tools/tests

What the original game only summons or spawns for a world event (tools/classicdb_pack.py spawning(), pack format 5,
ft.classic) and the locator, which keeps such creatures out of its ready spawns. On 2026-11-17 it offered 19 of 21
ready spawns that the original game never puts in the world all year: the Abyssal Council of Silithus (summoned at
the Wind Stones), Rigger Gizelton (an escort), and the Scourge Invasion's creatures (an event).
"""
import gzip
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

import classicdb_pack  # noqa: E402
from ft import classic, locator  # noqa: E402

TEMPLAR, GIZELTON, SHADOW, SPECTRE, BAKER = 15209, 11626, 16422, 11560, 5193


def write(folder, name, pack):
    path = os.path.join(folder, name)
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        json.dump(pack, handle)
    return path


def pack_of(format_=5, **extra):
    made = {'format': format_, 'trainers': [], 'quests': [], 'gossip': [], 'holidays': {'17': {'name': 'Scourge Invasion', 'creatures': [], 'objects': []}}}
    made.update(extra)
    return made


class Spawning(unittest.TestCase):
    def test_never_spawned_and_event_only(self):
        never, only = classicdb_pack.spawning(
            {TEMPLAR, GIZELTON, SHADOW, BAKER, 7},
            [(1, [BAKER]), (2, [SHADOW]), (3, [SHADOW]), (4, [7, 0]), (5, [7])],
            [(2, 17), (3, 17), (4, 17)])
        self.assertEqual(never, [GIZELTON, TEMPLAR])
        self.assertEqual(only, {str(SHADOW): [17]}, 'a creature with one spawn outside any event is not event-only (7)')

    def test_a_negative_event_and_several_events(self):
        _never, only = classicdb_pack.spawning({1, 2}, [(1, [1]), (2, [2]), (3, [2])], [(1, -4), (2, 4), (3, 9)])
        self.assertEqual(only, {'2': [4, 9]}, 'a spawn an event removes stands the rest of the year')

    def test_a_classic_db_pack_says_it_too(self):
        tables = {name: [] for name in classicdb_pack.WANTED}
        tables['creature_template'] = [{'Entry': TEMPLAR}, {'Entry': SHADOW}, {'Entry': 600}, {'Entry': 601}]
        tables['creature'] = [{'guid': 1, 'id': SHADOW}, {'guid': 2, 'id': 0}]
        tables['creature_spawn_entry'] = [{'guid': 2, 'entry': 600}]
        tables['game_event_creature'] = [{'guid': 1, 'event': 17}]
        made = classicdb_pack.pack(tables, '2026-11-17')
        self.assertEqual((made['format'], made['never_spawned'], made['event_only']), (5, [601, TEMPLAR], {str(SHADOW): [17]}))


class Notes(unittest.TestCase):
    def test_load_and_tell_why(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder, 'pack.cdbpack', pack_of(never_spawned=[TEMPLAR, 'x', -1], event_only={str(SHADOW): [17], 'bad': [1], '5': ['x']}))
            said = classic.spawning(classic.load(path))
        self.assertEqual(said[0], {TEMPLAR})
        self.assertEqual(said[1], {SHADOW: [17]})
        self.assertIn('summoned in Classic', classic.not_spawned(TEMPLAR, said))
        self.assertEqual(classic.not_spawned(SHADOW, said), 'event 17 Scourge Invasion only in Classic')
        self.assertEqual(classic.not_spawned(BAKER, said), '', 'a creature it spawns, or one it does not know')

    def test_an_older_pack_does_not_say(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder, 'pack.cdbpack', pack_of(4))
            self.assertIsNone(classic.spawning(classic.load(path)))
        self.assertEqual(classic.not_spawned(TEMPLAR, None), '')


class Locator(unittest.TestCase):
    def test_the_first_pack_that_says(self):
        with tempfile.TemporaryDirectory() as folder:
            old = write(folder, 'old.cdbpack', pack_of(4))
            broken = os.path.join(folder, 'broken.cdbpack')
            with open(broken, 'w') as handle:
                handle.write('not gzip')
            new = write(folder, 'new.cdbpack', pack_of(never_spawned=[TEMPLAR]))
            said = locator.classic_spawning([os.path.join(folder, 'missing'), old, broken, new])
            self.assertEqual(said[0], {TEMPLAR})
            self.assertIsNone(locator.classic_spawning([old]))

    def test_summoned_and_event_candidates_are_told_apart(self):
        said = ({TEMPLAR, GIZELTON}, {SHADOW: [17], SPECTRE: [17]}, {17: 'Scourge Invasion'})
        found = {('npc', TEMPLAR): {}, ('npc', SHADOW): {}, ('npc', BAKER): {}, ('go', TEMPLAR): {}, ('npc', GIZELTON): {}}
        out = locator.summoned_in_classic(found, said)
        self.assertEqual(set(out), {('npc', TEMPLAR), ('npc', SHADOW), ('npc', GIZELTON)}, 'a world object of the same number is another thing')
        self.assertEqual(out[('npc', SHADOW)], 'event 17 Scourge Invasion only in Classic')


if __name__ == '__main__':
    unittest.main()
