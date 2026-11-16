"""python -m unittest discover -s tools/tests

The cache of Wowhead pages (tools/wowhead_pages.py): only answers are kept, and no text; the newer answer of a page
wins; and the To add list is turned into the pages worth reading, the ones other content waits for first.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import wowhead_pages as wp  # noqa: E402


def page(kind, entity, fetched=100, status='ok', **more):
    return dict({'kind': kind, 'id': entity, 'v': 1, 'fetched': fetched, 'status': status}, **more)


class Clean(unittest.TestCase):
    def test_an_answer_is_kept_without_its_kind(self):
        record = wp.clean(page('item', 5, quick=['Level: 13'], tabs={'dropped-by': {'template': 'npc', 'rows': [{'id': 1, 'count': 2, 'outof': 30, 'react': [-1, None]}]}}, map={'33': [{'coords': [[1.5, 2]]}]}))
        self.assertEqual(record, {'id': 5, 'fetched': 100, 'v': 1, 'status': 'ok', 'quick': ['Level: 13'],
                                  'tabs': {'dropped-by': {'template': 'npc', 'rows': [{'id': 1, 'count': 2, 'outof': 30, 'react': [-1, None]}]}}, 'map': {'33': [{'coords': [[1.5, 2]]}]}})

    def test_text_never_enters_the_cache(self):
        record = wp.clean(page('item', 5, tabs={'sold-by': {'template': 'npc', 'rows': [{'id': 1, 'name': 'A vendor'}, {'id': 2, 'cost': [5]}]},
                                                 'bad tab!': {'rows': []}}, quick=['ok', 'x' * 301, 5, 'two\nlines'], series=['text']))
        self.assertEqual(record['tabs'], {'sold-by': {'template': 'npc', 'rows': [{'id': 2, 'cost': [5]}]}})
        self.assertEqual(record['quick'], ['ok'])
        self.assertNotIn('series', record)

    def test_every_number_of_a_row_is_kept(self):
        row = {'id': 818, 'count': 27, 'outof': 995, 'modes': {'0': {'count': 27}}, 'flags2': -5, 'envChange': {'labels': []}}
        record = wp.clean(page('npc', 5, tabs={'drops': {'template': 'item', 'rows': [row]}}))
        self.assertEqual(record['tabs']['drops']['rows'], [row])

    def test_no_answer_is_no_page(self):
        for bad in (page('item', 5, status='blocked'), page('item', 5, status='odd'), page('mount', 5), page('item', 0), page('item', True),
                    page('item', '5'), page('item', 5, fetched=0), page('item', 5, tabs='text'), 'text', None):
            self.assertIsNone(wp.clean(bad), bad)
        self.assertEqual(wp.clean(page('quest', 9, status='missing', tabs={'x': 1})), {'id': 9, 'fetched': 100, 'v': 1, 'status': 'missing'})


class Merge(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.folder.name, 'cache')

    def tearDown(self):
        self.folder.cleanup()

    def saved(self, name, records):
        path = os.path.join(self.folder.name, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(r if isinstance(r, str) else json.dumps(r) for r in records) + '\n')
        return path

    def test_the_newer_answer_wins_and_the_file_is_sorted(self):
        first = self.saved('a.jsonl', [page('item', 30, 100), page('item', 4, 100), page('quest', 7, 100), '{cut', page('item', 9, status='blocked')])
        self.assertEqual(wp.merge([first], self.cache), {'new': 3, 'newer': 0, 'older': 0, 'not_a_page': 2})
        second = self.saved('b.jsonl', [page('item', 30, 50, status='missing'), page('item', 4, 200, status='missing'), page('item', 12, 200)])
        self.assertEqual(wp.merge([second], self.cache), {'new': 1, 'newer': 1, 'older': 1, 'not_a_page': 0})
        with open(wp.path('item', self.cache), encoding='utf-8') as handle:
            lines = [json.loads(line) for line in handle]
        self.assertEqual([(r['id'], r['status']) for r in lines], [(4, 'missing'), (12, 'ok'), (30, 'ok')])
        self.assertEqual(sorted(os.listdir(self.cache)), ['item.jsonl', 'quest.jsonl'])   # no scratch file left
        self.assertEqual(wp.merge([second], self.cache)['older'], 3)                        # again: nothing changes

    def test_classic_pages_and_lists_go_on_shelves_of_their_own(self):
        listing = {'kind': 'list', 'query': 'npcs?filter=37:37;2:4;1:20000', 'fetched': 100, 'v': 2, 'status': 'ok', 'found': 2, 'truncated': False, 'cr': 37,
                   'rows': [{'id': 7, 'minlevel': 3}, {'id': 9, 'name': 'text'}, {'name': 'no id'}]}
        saved = self.saved('a.jsonl', [page('npc', 7, branch='classic', tabs={}), page('npc', 7), listing, dict(listing, branch='classic'),
                                       dict(listing, query='npcs?filter=1;1;"x"'), page('npc', 8, branch='retail')])
        self.assertEqual(wp.merge([saved], self.cache), {'new': 4, 'newer': 0, 'older': 0, 'not_a_page': 2})
        self.assertEqual(sorted(os.listdir(self.cache)), ['classic-list.jsonl', 'classic-npc.jsonl', 'forever-list.jsonl', 'npc.jsonl'])
        self.assertEqual(wp.load('classic-npc', self.cache)[7]['branch'], 'classic')
        kept = wp.load('forever-list', self.cache)['npcs?filter=37:37;2:4;1:20000']
        self.assertEqual(kept['rows'], [{'id': 7, 'minlevel': 3}])   # a row with text, or without an id, is dropped
        self.assertNotIn('branch', kept)
        self.assertIn('forever-list: 1 list pages, 1 npcs', wp.stats(self.cache))

    def test_stats(self):
        wp.merge([self.saved('a.jsonl', [page('item', 1, tabs={'sold-by': {'rows': [{'id': 2}]}, 'dropped-by': {'rows': []}}), page('item', 2, status='missing')])], self.cache)
        self.assertEqual(wp.stats(self.cache), ['item: 1 pages, 1 Wowhead does not have, newest 1970-01-01', '    sold-by                          1 pages'])
        self.assertEqual(wp.stats(os.path.join(self.folder.name, 'none')), ['the cache is empty'])


ROWS = [
    {'type': 'item', 'id': '250001', 'missing': 'Obtainable in game: No source: loot, vendor, quest, craft or shop.', 'phase': ''},
    {'type': 'item', 'id': '5559', 'missing': 'Obtainable in game: No source: loot, vendor, quest, craft or shop.', 'phase': ''},
    {'type': 'item', 'id': '250002', 'missing': 'Obtainable in game: No source: loot, vendor, quest, craft or shop.', 'phase': 'first-raids'},
    {'type': 'item', 'id': '250003', 'missing': 'Obtainable in game: Inactive source: recipe that cannot be learned', 'phase': ''},
    {'type': 'quest', 'id': '900', 'missing': 'Objectives achievable: item 270001 not obtainable; item 3000 not obtainable', 'phase': ''},
    {'type': 'quest', 'id': '901', 'missing': 'Quest giver: No quest giver (creature/gameobject_queststarter). | Quest ender: No quest ender.', 'phase': ''},
    {'type': 'quest', 'id': '902', 'missing': 'Quest giver: NPC 5 (not spawned)', 'phase': ''},
    {'type': 'quest', 'id': '903', 'missing': 'Quest giver: item 250001 (not obtainable)', 'phase': ''},
    {'type': 'quest', 'id': '904', 'missing': 'Quest text: no turn-in text', 'phase': ''},
    {'type': 'recipe', 'id': '400100', 'missing': 'Learnable: Recipe exists but cannot be obtained: 260001, 260002', 'phase': ''},
    {'type': 'recipe', 'id': '400101', 'missing': 'Learnable: Taught by item 260003, which players cannot get.', 'phase': ''},
    {'type': 'mount', 'id': '77', 'missing': 'Obtainable: Item exists but cannot be obtained: 8633', 'phase': ''},
    {'type': 'toy', 'id': '78', 'missing': 'Obtainable: Item 255000 has no source.', 'phase': ''},
    {'type': 'spell', 'id': '79', 'missing': 'Learnable: Taught by item 9126, 0, which players cannot get.', 'phase': ''},
    {'type': 'item', 'id': 'x', 'missing': 'No source', 'phase': ''},
]


class Todo(unittest.TestCase):
    def test_what_other_content_waits_for_comes_first(self):
        want = wp.wanted(ROWS, min_item=190000)
        self.assertEqual(want['item'], [3000, 8633, 9126, 250001, 255000, 260001, 260002, 260003, 270001])
        self.assertEqual(want['quest'], [901, 902, 903])
        # 5559 is an original-game item that only lacks a source: left out by the cut-off, in without it
        self.assertEqual(wp.wanted(ROWS, min_item=0)['item'][-1], 5559)
        self.assertEqual(wp.wanted(ROWS + [{'type': 'item', 'id': '250009', 'missing': 'No source', 'phase': ''}], 190000)['item'][-1], 250009)

    def test_a_page_in_the_cache_is_not_read_again_until_it_is_old(self):
        with tempfile.TemporaryDirectory() as folder:
            listing = os.path.join(folder, 'todo.csv')
            with open(listing, 'w', encoding='utf-8', newline='') as handle:
                handle.write('﻿type;id;name;name_en;status;score;new;missing;phase\n')
                for row in ROWS:
                    handle.write(f"{row['type']};{row['id']};\"n\";\"n\";partial;1;1;\"{row['missing']}\";{row['phase']}\n")
            cache = os.path.join(folder, 'cache')
            wp.save('item', {3000: {'id': 3000, 'fetched': 1000, 'status': 'ok'}, 250001: {'id': 250001, 'fetched': 86400 * 20, 'status': 'missing'}}, cache)
            now = 86400 * 21
            self.assertEqual(wp.todo(listing, ['item'], 190000, 0, cache, now), {'item': [8633, 9126, 255000, 260001, 260002, 260003, 270001]})
            self.assertEqual(wp.todo(listing, None, 190000, 7, cache, now), {'item': [3000, 8633, 9126, 255000, 260001, 260002, 260003, 270001], 'quest': [901, 902, 903]})


if __name__ == '__main__':
    unittest.main()
