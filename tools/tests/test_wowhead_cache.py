"""python -m unittest discover -s tools/tests

Wowhead's answers on disk (ft.wowhead): written whole or not at all, read back even when an older version left half
a file, "does not know it" asked again after a week, and no hammering when Wowhead stops answering.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import wowhead  # noqa: E402


class Files(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, 'deep', 'cache.json')

    def tearDown(self):
        self.folder.cleanup()

    def test_written_whole_and_read_back(self):
        wowhead.save_json(self.path, {'1': {'en': 'Élan'}})
        self.assertEqual(wowhead.load_json(self.path, {}), {'1': {'en': 'Élan'}})
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ['cache.json'])   # no scratch file left

    def test_half_a_file_reads_as_empty(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w', encoding='utf-8') as handle:
            handle.write('{"1": {"en": "Cut sho')
        self.assertEqual(wowhead.load_json(self.path, {}), {})
        self.assertEqual(wowhead.load_json(os.path.join(self.folder.name, 'none.json'), {}), {})

    def test_another_shape_reads_as_empty(self):
        wowhead.save_json(self.path, [1, 2])
        self.assertEqual(wowhead.load_json(self.path, {}), {})


class Client(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.client = wowhead.Wowhead(pause=0)
        self.client.folder = self.folder.name
        self.answers = []
        self.client._fetch = lambda kind, entity_id, locale: self.answers.pop(0) if self.answers else None

    def tearDown(self):
        self.folder.cleanup()

    def test_an_answer_is_kept_and_not_asked_again(self):
        self.answers = [{'name': 'Goli Krumn'}]
        self.assertEqual(self.client.get('npc', 1365)['name'], 'Goli Krumn')
        self.assertEqual(self.client.get('npc', 1365)['name'], 'Goli Krumn')   # from disk: no answer was left to give

    def test_does_not_know_it_is_asked_again_after_a_week(self):
        wowhead.save_json(self.client.path('item', 5), {'missing': True, 'fetched': int(time.time()) - 8 * 86400})
        self.answers = [{'name': 'Found Since'}]
        self.assertEqual(self.client.get('item', 5)['name'], 'Found Since')
        wowhead.save_json(self.client.path('item', 6), {'missing': True, 'fetched': int(time.time()) - 86400})
        self.answers = [{'name': 'Too Soon'}]
        self.assertTrue(self.client.get('item', 6)['missing'])

    def test_unreachable_keeps_the_old_answer(self):
        wowhead.save_json(self.client.path('item', 5), {'missing': True, 'fetched': 0})
        self.assertTrue(self.client.get('item', 5)['missing'])
        self.assertIsNone(self.client.get('item', 7))

    def test_it_stops_asking_when_nothing_answers(self):
        asked = []
        self.client._fetch = lambda kind, entity_id, locale: asked.append(entity_id)
        for entity_id in range(1, 40):
            self.client.get('item', entity_id)
        self.assertEqual(len(asked), wowhead.GIVE_UP_AFTER)
        self.assertTrue(self.client.gave_up)

    def test_one_answer_resets_the_count(self):
        answers = iter([None] * (wowhead.GIVE_UP_AFTER - 1) + [{'name': 'Back'}] + [None] * 3)
        self.client._fetch = lambda kind, entity_id, locale: next(answers)
        for entity_id in range(1, wowhead.GIVE_UP_AFTER + 4):
            self.client.get('item', entity_id)
        self.assertFalse(self.client.gave_up)



DAY = 86400


class Due(unittest.TestCase):
    """When an answer on disk is asked again (is_stale): by its age, by what it says, and after "ask every source again"."""

    def due(self, age_days, missing=False, entity_id=0, epoch=0, refresh=30, recheck=7):
        now = 1000 * DAY
        return wowhead.is_stale(now - age_days * DAY, missing, entity_id, now=now, epoch=epoch, refresh=refresh, recheck=recheck)

    def test_an_answer_is_believed_for_about_a_month(self):
        self.assertFalse(self.due(20, entity_id=1))
        self.assertTrue(self.due(40, entity_id=1))

    def test_answers_of_one_run_do_not_all_come_due_together(self):
        days = sorted(next(d for d in range(1, 60) if self.due(d, entity_id=i)) for i in range(1, 400))
        self.assertGreaterEqual(days[0], 22)      # never before three quarters of the time
        self.assertLessEqual(days[-1], 38)        # never after one and a quarter
        self.assertGreater(len(set(days)), 10)    # and spread over the days between

    def test_the_same_id_is_always_due_on_the_same_day(self):
        self.assertEqual(wowhead.spread(17253), wowhead.spread(17253))
        self.assertEqual((round(wowhead.spread(1), 4), round(wowhead.spread(2), 4)), (1.1305, 1.011))   # as app/wowhead.php

    def test_not_known_is_asked_again_after_a_week(self):
        self.assertFalse(self.due(6, missing=True))
        self.assertTrue(self.due(8, missing=True))

    def test_refresh_days_zero_keeps_answers_for_good(self):
        self.assertFalse(self.due(900, refresh=0))
        self.assertTrue(self.due(900, missing=True, refresh=0))   # "not known" still expires

    def test_ask_every_source_again(self):
        now = 1000 * DAY
        pressed = now - 3600
        self.assertTrue(wowhead.is_stale(now - 2 * 3600, False, 1, now=now, epoch=pressed, refresh=30, recheck=7))    # fetched before it
        self.assertFalse(wowhead.is_stale(now - 1800, False, 1, now=now, epoch=pressed, refresh=30, recheck=7))       # asked since


class Counted(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.client = wowhead.Wowhead(pause=0)
        self.client.folder = self.folder.name

    def tearDown(self):
        self.folder.cleanup()

    def test_an_answer_due_again_is_asked_and_a_change_is_counted(self):
        old = int(time.time()) - 60 * DAY
        wowhead.save_json(self.client.path('npc', 639), {'name': 'Edwin VanCleef', 'facts': {'level': 21, 'rank': 2}, 'fetched': old})
        wowhead.save_json(self.client.path('npc', 640), {'name': 'Unchanged', 'facts': {'level': 5, 'rank': 0}, 'fetched': old})
        answers = {639: {'name': 'Edwin VanCleef', 'tooltip': '<td>Level 21 Humanoid (Elite)</td>'}, 640: {'name': 'Unchanged', 'tooltip': '<td>Level 5 Humanoid</td>'}}
        self.client._fetch = lambda kind, entity_id, locale: dict(answers[entity_id])
        first = self.client.npc(639, True)
        self.client.npc(640, True)
        self.assertGreater(first['fetched'], old)
        self.assertEqual(self.client.reasked, 2)
        self.assertGreaterEqual(self.client.changed, 1)
        self.assertIn('asked again', self.client.summary())

    def test_a_fresh_answer_is_not_asked(self):
        wowhead.save_json(self.client.path('npc', 639), {'name': 'Edwin VanCleef', 'facts': {'level': 21}, 'fetched': int(time.time()) - DAY})
        self.client._fetch = lambda *a: self.fail('asked')
        self.assertEqual(self.client.npc(639, True)['name'], 'Edwin VanCleef')
        self.assertEqual(self.client.summary(), '')


if __name__ == '__main__':
    unittest.main()
