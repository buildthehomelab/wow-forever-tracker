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


if __name__ == '__main__':
    unittest.main()
