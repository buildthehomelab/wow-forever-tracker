"""foreverchanges.pro read from the site (tools/ft/foreverchanges_site.py): the order, the pace, what is kept, what a
page states and the pack made of it. Nothing here asks the site: `get` is a fake. The pages are made up, in the
site's markup of 2026-11-15."""
import gzip
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ft import foreverchanges_site as site  # noqa: E402
from ft import reports  # noqa: E402

B = site.BASE

QUEST_SEEN = '''<html><head><title>A Test Quest</title></head><body><main><div class="qp-work"><h1>A Test Quest</h1>
<p class="qp-known qp-known-forever"><b class="qp-new">New in Forever.</b> Partly read from what players of our addon saw in game.</p>
<div class="qp-grid"><article class="qp-sheet"><h2>Quest Objectives</h2><p>Bring the thing.</p>
<div class="qp-more"><details><summary>When you come back</summary><p>Still out there?</p></details>
<details><summary>When you hand it in</summary><p>Well done, &lsaquo;name&rsaquo;.</p><p>Go well.</p></details></div></article>
<aside class="qp-side"><dl class="qp-facts"><dt><img src="/x.png"/>Start</dt><dd><span>Tester One<span class="qp-coord"> Mulgore 34.2, 22.4</span></span></dd>
<dt>End</dt><dd><span>an item: Odd Stone</span><span>Tester Two<span class="qp-coord"> Durotar 50.0, 60.5</span></span></dd>
<dt>Level</dt><dd>60, requires level 12</dd><dt>Side</dt><dd>Horde</dd><dt>Quest ID</dt><dd>99001</dd></dl></aside></div></div></main></body></html>'''

QUEST_CLASSIC = '''<html><body><main><div class="qp-work"><h1>Old Quest</h1>
<p class="qp-known">Unchanged in Forever as far as is known: the text, objectives and rewards below are Classic's.</p>
<dl class="qp-facts"><dt>Start</dt><dd><span>Old Giver<span class="qp-coord"> Ashenvale 73.8, 61.5</span></span></dd><dt>Quest ID</dt><dd>2</dd></dl>
</div></main></body></html>'''

ITEM = '''<html><head><title>Test Mote</title></head><body><main><h1>Test Mote</h1><p>Common, item 274000. New in Forever</p>
<section class="it-from"><h2>Where it comes from</h2>
<div class="it-from-group"><h3>Creature drop</h3><ul><li><b>Stone Brute</b><span>Mulgore (30.5, 40.1)</span><em title="Seen in game: 12 in 40 kills">30%</em></li>
<li><b>Creature drop</b><span></span><em title="Seen in game: 1 in 7 kills">1 in 7 kills</em></li></ul></div>
<div class="it-from-group"><h3>Sold by a vendor</h3><ul><li><b>Trader Tess</b><span>Durotar (50, 50)</span><em>1g 2s 3c</em></li></ul></div></section>
<section class="it-from"><h2>Quests</h2><div class="it-from-group"><h3>Asked for by</h3><ul><li><a href="/quest/1/x">X</a><span>Level 60</span></li></ul></div></section>
</main></body></html>'''

SITEMAP = ''.join(f'<url><loc>{B}{p}</loc></url>' for p in [
    '/', '/rares', '/library-books', '/fr/rares', '/talents/warrior', '/map', '/map/kalimdor', '/map/kalimdor/ashenvale', '/map/deadmines',
    '/dungeons/deadmines', '/quests/mulgore', '/spell/1/x', '/bad/../../etc'])
QUESTS = ''.join(f'<url><loc>{B}/quest/{n}/q{n}</loc></url>' for n in (2, 99001, 99002, 5000))
ITEMS = ''.join(f'<url><loc>{B}/item/{n}/i{n}</loc></url>' for n in (40, 274000, 280000, 6000))


def paths(steps):
    return [s[1] for s in steps]


class Order(unittest.TestCase):
    def test_robots(self):
        closed = site.disallowed('User-Agent: other\nDisallow: /x\n\nUser-Agent: *\nAllow: /\nDisallow: /api/\nDisallow: /spell/ # no\n')
        self.assertEqual(closed, ['/api/', '/spell/'])
        self.assertFalse(site.allowed('/spell/1/x', closed))
        self.assertTrue(site.allowed('/quest/1/x', closed))

    def test_gaps_only_reads_only_what_the_gaps_ask_about(self):
        steps = site.plan(SITEMAP, QUESTS, ITEMS, {'quests': [5000], 'items_first': [6000], 'items': [40]}, whole=False)
        order = paths(steps)
        self.assertEqual(order[:12], [f'/map/kalimdor/{name}.json' for name in site.MAP_FILES], 'the continents\' map files first')
        self.assertEqual(order[12:], ['/quest/5000/q5000', '/item/6000/i6000', '/item/40/i40'], 'then the gaps, in the order asked')
        for never in ('/quest/99001/q99001', '/quest/2/q2', '/item/274000/i274000', '/item/280000/i280000', '/map/deadmines/manifest.json',
                      '/dungeons/deadmines', '/rares', '/library-books', '/quests/mulgore', '/fr/rares', '/talents/warrior', '/map'):
            self.assertNotIn(never, order, 'no gap asks about it')
        self.assertFalse(any('..' in p for p in order))
        self.assertEqual(len(steps), len({s[2] for s in steps}))

    def test_whole_reads_the_rest_of_the_site_after_the_gaps(self):
        steps = site.plan(SITEMAP, QUESTS, ITEMS, {'quests': [5000], 'items_first': [6000], 'items': [40]}, whole=True)
        order = paths(steps)
        n = len(site.MAP_FILES)
        self.assertEqual(order[:n], [f'/map/kalimdor/{name}.json' for name in site.MAP_FILES])
        self.assertEqual(order[n:n + 3], ['/quest/5000/q5000', '/item/6000/i6000', '/item/40/i40'], 'the gaps before anything else')
        self.assertTrue(all(s[0] < site.REST for s in steps[:n + 3]) and all(s[0] >= site.REST for s in steps[n + 3:]))
        self.assertEqual(order[n + 3:2 * n + 3], [f'/map/deadmines/{name}.json' for name in site.MAP_FILES], 'then the other maps\' files')
        self.assertEqual(order[2 * n + 3:], ['/quest/2/q2', '/quest/99001/q99001', '/quest/99002/q99002', '/item/274000/i274000', '/item/280000/i280000'],
                         'then every other quest page, then every other item page, by id')
        for never in ('/dungeons/deadmines', '/rares', '/library-books', '/quests/mulgore', '/fr/rares', '/talents/warrior', '/map', '/spell/1/x'):
            self.assertNotIn(never, order, 'not a quest, an item or a map\'s data file')
        self.assertFalse(any('..' in p for p in order))
        self.assertEqual(len(steps), len({s[2] for s in steps}), 'a gap is not read twice')
        self.assertEqual(len(site.plan(SITEMAP, QUESTS, ITEMS, None, whole=True)), 2 * n + 8, 'without gaps: the whole site')

    def test_without_gaps_only_the_continents_map_files(self):
        self.assertEqual({s[1].split('/')[2] for s in site.plan(SITEMAP, QUESTS, ITEMS)}, {'kalimdor'})
        self.assertEqual(len(site.plan(SITEMAP, QUESTS, ITEMS, {})), len(site.MAP_FILES))

    def test_due_reads_the_new_first_then_the_old(self):
        steps = [(10, '/a', 'a'), (20, '/b', 'b'), (30, '/c', 'c'), (30, '/d', 'd')]
        day = 86400
        read = {'a': {'at': 100 * day, 's': 200}, 'c': {'at': 95 * day, 's': 200}, 'd': {'at': 90 * day, 's': 404}}
        self.assertEqual([s[2] for s in site.due(steps, read, 14, 101 * day)], ['b'])
        self.assertEqual([s[2] for s in site.due(steps, read, 14, 115 * day)], ['b', 'a', 'c'], 'a 404 waits four times as long')
        self.assertEqual([s[2] for s in site.due(steps, read, 14, 200 * day)], ['b', 'a', 'd', 'c'], 'oldest first within a tier')

    def test_due_reads_every_gap_before_the_rest(self):
        R = site.REST
        steps = [(10, '/a', 'a'), (20, '/b', 'b'), (R, '/m', 'm'), (R + 1, '/q', 'q'), (R + 2, '/i', 'i'), (R + 2, '/j', 'j')]
        day = 86400
        read = {'a': {'at': 80 * day, 's': 200}, 'b': {'at': 99 * day, 's': 200}, 'm': {'at': 85 * day, 's': 200},
                'q': {'at': 70 * day, 's': 200}, 'i': {'at': 75 * day, 's': 200}}
        self.assertEqual([s[2] for s in site.due(steps, read, 14, 100 * day)], ['a', 'j', 'q', 'i', 'm'],
                         'an old gap, then the rest never read, then the rest oldest read first, whatever its tier')
        self.assertEqual([s[2] for s in site.due(steps, {}, 14, 100 * day)], ['a', 'b', 'm', 'q', 'i', 'j'], 'never read: the plan\'s order')


class Pace(unittest.TestCase):
    def test_pacer(self):
        now = [0.0]
        slept = []
        pacer = site.Pacer(2.5, None, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
        pacer.wait()
        pacer.wait()
        self.assertEqual(slept, [2.5])
        self.assertEqual(pacer.throttled('300'), 300.0)
        self.assertEqual(pacer.pause, 5.0)
        self.assertEqual(pacer.throttled(None), 60.0, 'a minute at least')
        self.assertEqual(pacer.throttled('99999'), 3600.0)
        pacer.answered(10)
        self.assertEqual(pacer.pause, 25.0, 'a slow answer lengthens the pause')
        for _ in range(site.Pacer.EASE_AFTER):
            pacer.answered(0.2)
        self.assertEqual(pacer.pause, 22.5, 'quick answers ease it back')
        floor = site.Pacer(2.5, {'pause': 1.2})
        self.assertEqual(floor.pause, 2.5, 'never below the floor')
        self.assertEqual(site.Pacer(2.5, {'pause': 7}).pause, 7, 'a run starts where the last one ended')
        self.assertEqual(site.Pacer(0.1).floor, 1.0)


class Pull(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data = self.dir.name
        self.asked = []
        self.now = [1_800_000_000.0]
        self.pages = {
            '/robots.txt': (200, {}, b'User-agent: *\nDisallow: /spell/\n'),
            '/sitemap.xml': (200, {}, f'<url><loc>{B}/map/kalimdor</loc></url><url><loc>{B}/rares</loc></url>'.encode()),
            '/quest/sitemap.xml': (200, {}, f'<url><loc>{B}/quest/99001/q</loc></url>'.encode()),
            '/item/sitemap.xml': (200, {}, f'<url><loc>{B}/item/274000/i</loc></url>'.encode()),
            '/map/kalimdor/manifest.json': (200, {}, b'{"mapId": 1}'),
            '/map/kalimdor/npcs.json': (200, {}, json.dumps({'npcs': [[5, 'Tester One', '', 'H', 10.0, 20.0, 'npc', '', 'addon'], [6, 'Somebody', '', 'A', 1, 2, 'npc']]}).encode()),
            '/map/kalimdor/quest-givers.json': (200, {}, json.dumps({'givers': [['n5', 'Tester One', '', 'H', 10, 20, [99001], 'addon'], ['o77', 'Board', '', 'AH', 1, 2, [3]], ['x1', 'Bad', '', '', 1, 2, [4], 'addon']]}).encode()),
            '/map/kalimdor/rares.json': (200, {}, json.dumps({'pins': [{'name': 'Big One', 'x': 1.5, 'y': 2.5, 'faction': ''}]}).encode()),
            '/quest/99001/q': (200, {}, QUEST_SEEN.encode()),
            '/item/274000/i': (200, {}, ITEM.encode()),
            '/rares': (200, {}, b'<html><main><h1>Rares</h1></main></html>'),
        }

    def tearDown(self):
        self.dir.cleanup()

    def get(self, path):
        self.asked.append(path)
        answer = self.pages.get(path, (404, {}, b'<html>not here</html>'))
        return answer() if callable(answer) else answer

    def pull(self, **kw):
        lines = []
        out = site.pull(self.data, kw.pop('wanted', {'quests': [99001], 'items': [274000]}), kw.pop('pause', 1.0), kw.pop('limit', 100), whole=kw.pop('whole', True),
                        get=self.get, clock=lambda: self.now[0],
                        sleep=lambda s: self.now.__setitem__(0, self.now[0] + s), log=lines.append)
        return out, lines

    def test_a_visit_keeps_each_file_once_and_makes_the_pack(self):
        done, _ = self.pull()
        self.assertEqual(done['stopped'], '')
        self.assertEqual(self.asked[:4], ['/robots.txt', '/sitemap.xml', '/quest/sitemap.xml', '/item/sitemap.xml'])
        self.assertEqual(self.asked[4], '/map/kalimdor/manifest.json')
        read = site.readings(self.data)
        self.assertEqual(read['map/kalimdor/services.json']['s'], 404)
        kept = os.path.join(self.data, 'foreverchanges', 'site', 'quest', '99001.html.gz')
        with open(kept, 'rb') as handle:
            body = gzip.decompress(handle.read())
        self.assertTrue(body.startswith(b'<main') or b'<main' in body[:200], 'the page\'s <main> is kept')
        self.assertNotIn(b'<html>', body)
        blob = site.blob_path(self.data, read['quest/99001.html.gz']['key'])
        self.assertEqual(os.stat(blob).st_ino, os.stat(kept).st_ino, 'the kept file is a link to the one copy')
        # a second visit asks for nothing it has, until it is due again
        self.asked.clear()
        done, _ = self.pull()
        self.assertEqual(done.get('read', 0), 0)
        self.assertEqual(len(self.asked), 4)
        self.now[0] += 15 * 86400
        self.asked.clear()
        done, _ = self.pull()
        self.assertEqual(done['same'], 6, 'what was read again and did not change')
        self.assertNotIn('/rares', self.asked, 'a page no gap asks about is never read')
        self.assertEqual(self.asked.count('/map/kalimdor/manifest.json'), 1)
        self.assertNotIn('/map/kalimdor/services.json', self.asked, 'a 404 is asked again four times less often')

        content = site.write_pack(self.data)
        with zipfile.ZipFile(os.path.join(self.data, 'foreverchanges', 'pack.fcpack')) as archive:
            self.assertEqual(json.loads(archive.read('pack.json')), content)
        self.assertEqual(content['format'], reports.FORMAT)
        quest = content['quests'][0]
        self.assertEqual((quest['id'], quest['side'], quest['seen_by_players'], quest['level'], quest['min_level']), (99001, 'Horde', True, 60, 12))
        self.assertEqual(quest['start'], [{'name': 'Tester One', 'zone': 'Mulgore', 'x': 34.2, 'y': 22.4}])
        self.assertEqual(quest['end'], [{'item': 'Odd Stone'}, {'name': 'Tester Two', 'zone': 'Durotar', 'x': 50.0, 'y': 60.5}])
        self.assertEqual(quest['texts'], {'progress': 'Still out there?', 'complete': 'Well done, ‹name›.\n\nGo well.'})
        sources = content['items'][0]['sources']
        self.assertEqual([s['how'] for s in sources], ['Creature drop', 'Creature drop', 'Sold by a vendor'], 'quests that ask for it are no source')
        self.assertEqual(sources[0]['rate'], {'percent': 30.0, 'drops': 12, 'kills': 40})
        self.assertEqual(sources[2]['price'], 10203)
        self.assertEqual(content['npcs'][0], {'entry': 5, 'name': 'Tester One', 'side': 'H', 'map': 1, 'x': 10.0, 'y': 20.0, 'kind': 'npc', 'seen': True})
        self.assertFalse(content['npcs'][1]['seen'])
        self.assertEqual(content['pins'], [{'map': 1, 'kind': 'rare', 'name': 'Big One', 'x': 1.5, 'y': 2.5, 'side': ''}])
        self.assertEqual([(g['kind'], g['entry'], g['quests'], g['seen']) for g in content['givers']], [('npc', 5, [99001], True), ('go', 77, [3], False)])
        # each page is read once: the second pack takes what the first one read from parsed.jsonl
        with open(os.path.join(self.data, 'foreverchanges', 'parsed.jsonl'), encoding='utf-8') as handle:
            parsed = handle.read()
        self.assertEqual(site.pack(self.data), content)
        with open(os.path.join(self.data, 'foreverchanges', 'parsed.jsonl'), encoding='utf-8') as handle:
            self.assertEqual(handle.read(), parsed)

    def test_wanted_and_limit(self):
        self.pages['/quest/sitemap.xml'] = (200, {}, f'<url><loc>{B}/quest/99001/q</loc></url><url><loc>{B}/quest/5000/q</loc></url>'.encode())
        done, _ = self.pull(wanted={'quests': [5000, 99001]}, limit=13, whole=False)
        self.assertEqual(self.asked[-1], '/quest/5000/q', 'the gap quest right after the continent\'s twelve map files')
        self.assertEqual(done['left'], 1, 'the other gap quest, next visit; the item no gap asks about is not counted')

    def test_the_whole_site_after_the_gaps_and_all_of_it_in_the_pack(self):
        self.pages['/sitemap.xml'] = (200, {}, f'<url><loc>{B}/map/kalimdor</loc></url><url><loc>{B}/map/deadmines</loc></url>'.encode())
        self.pages['/quest/sitemap.xml'] = (200, {}, f'<url><loc>{B}/quest/99001/q</loc></url><url><loc>{B}/quest/2/q</loc></url>'.encode())
        self.pages['/item/sitemap.xml'] = (200, {}, f'<url><loc>{B}/item/274000/i</loc></url><url><loc>{B}/item/40/i</loc></url>'.encode())
        self.pages['/map/deadmines/manifest.json'] = (200, {}, b'{"mapId": 36}')
        self.pages['/map/deadmines/quest-givers.json'] = (200, {}, json.dumps({'givers': [['n639', 'Edwin', '', 'A', 1, 2, [373], 'addon']]}).encode())
        self.pages['/quest/2/q'] = (200, {}, QUEST_CLASSIC.encode())
        self.pages['/item/40/i'] = (200, {}, ITEM.replace('item 274000', 'item 40').encode())
        n = len(site.MAP_FILES)
        done, lines = self.pull(wanted={'items': [274000]}, limit=n + 1)
        self.assertEqual(self.asked[4:], [f'/map/kalimdor/{name}.json' for name in site.MAP_FILES] + ['/item/274000/i'], 'the gaps first')
        self.assertEqual((done['left'], done['left_gaps']), (n + 3, 0), 'the rest of the site, next visit')
        self.asked.clear()
        done, _ = self.pull(wanted={'items': [274000]}, limit=1000)
        self.assertEqual(self.asked[4:], [f'/map/deadmines/{name}.json' for name in site.MAP_FILES] + ['/quest/2/q', '/quest/99001/q', '/item/40/i'],
                         'then the other maps\' files, every other quest and every other item')
        self.assertEqual(done['left'], 0)
        content = site.write_pack(self.data)
        self.assertEqual(sorted(q['id'] for q in content['quests']), [2, 99001], 'what no gap asked about is in the pack too')
        self.assertEqual(sorted(i['id'] for i in content['items']), [40, 274000])
        self.assertIn(('npc', 639, 36, [373]), [(g['kind'], g['entry'], g['map'], g['quests']) for g in content['givers']], 'a dungeon\'s givers, on its own map')
        # a gap found later is read at the next visit, ahead of the rest that is due again
        self.now[0] += 15 * 86400
        self.pages['/quest/sitemap.xml'] = (200, {}, f'<url><loc>{B}/quest/99001/q</loc></url><url><loc>{B}/quest/2/q</loc></url><url><loc>{B}/quest/7/q</loc></url>'.encode())
        self.asked.clear()
        self.pull(wanted={'quests': [7], 'items': [274000]}, limit=1)
        self.assertEqual(self.asked[4:], ['/quest/7/q'], 'a new gap before anything due again')
        self.asked.clear()
        self.pull(wanted={'quests': [7], 'items': [274000]}, limit=1000)
        self.assertLess(self.asked.index('/item/274000/i'), self.asked.index('/map/deadmines/manifest.json'), 'the gaps due again before the rest')
        self.assertIn('/quest/2/q', self.asked, 'the rest is read again too')

    def test_the_pack_is_written_as_the_visit_goes(self):
        quests = ''.join(f'<url><loc>{B}/quest/{n}/q</loc></url>' for n in range(1, 6))
        self.pages['/quest/sitemap.xml'] = (200, {}, quests.encode())
        for n in range(1, 6):
            self.pages[f'/quest/{n}/q'] = (200, {}, QUEST_SEEN.replace('99001', str(n)).encode())
        pack = os.path.join(self.data, 'foreverchanges', 'pack.fcpack')
        written = []

        def get(path):
            written.append((path, reports.load(pack)['quests'] if os.path.exists(pack) else None))
            if path == '/quest/5/q':
                raise KeyboardInterrupt('a restart')
            return self.get(path)
        with self.assertRaises(KeyboardInterrupt):
            site.pull(self.data, {}, 1.0, 100, pack_every=3, get=get, clock=lambda: self.now[0], sleep=lambda s: self.now.__setitem__(0, self.now[0] + s), log=lambda m: None)
        quests = reports.load(pack)['quests']
        self.assertEqual(sorted(q['id'] for q in quests), [1, 2, 3], 'cut short at the 17th file (12 map files, 4 quests): the pack of the 15th holds quests 1 to 3')
        self.assertIsNone(written[0][1], 'no pack before the first 3 files')

    def test_no_pack_on_the_way_with_pack_every_0(self):
        site.pull(self.data, {'quests': [99001], 'items': [274000]}, 1.0, 100, pack_every=0, get=self.get, clock=lambda: self.now[0],
                  sleep=lambda s: self.now.__setitem__(0, self.now[0] + s), log=lambda m: None)
        self.assertFalse(os.path.exists(os.path.join(self.data, 'foreverchanges', 'pack.fcpack')), 'pull leaves the last pack to its caller')

    def test_closed_paths_are_never_asked(self):
        self.pages['/item/sitemap.xml'] = (200, {}, b'')
        self.pages['/robots.txt'] = (200, {}, b'User-agent: *\nDisallow: /quest/\n')
        self.pull()
        self.assertFalse(any(p.startswith('/quest/') for p in self.asked))

    def test_a_throttle_is_waited_out_and_the_pause_grows(self):
        answers = iter([(429, {'retry-after': '120'}, b''), (200, {}, QUEST_SEEN.encode())])
        self.pages['/quest/99001/q'] = lambda: next(answers)
        start = self.now[0]
        done, lines = self.pull()
        self.assertEqual(done['stopped'], '')
        self.assertEqual(self.asked.count('/quest/99001/q'), 2)
        self.assertGreaterEqual(self.now[0] - start, 120)
        self.assertEqual(done['pause'], 2.0)
        self.assertIn('429', lines[0])
        with open(os.path.join(self.data, 'foreverchanges', 'pacer.json')) as handle:
            self.assertEqual(json.load(handle)['throttles'], 1, 'kept for the next run')

    def test_three_throttles_stop_the_run(self):
        self.pages['/quest/99001/q'] = (503, {}, b'')
        done, _ = self.pull()
        self.assertIn('503 three times', done['stopped'])
        self.assertEqual(self.asked.count('/quest/99001/q'), 3)
        self.assertNotIn('/item/274000/i', self.asked, 'nothing after it')

    def test_a_refusal_stops_the_run_at_once(self):
        for answer in ((403, {}, b''), (200, {'cf-mitigated': 'challenge'}, b'<html>check</html>'), (200, {}, b'<html><title>Just a moment...</title></html>')):
            self.setUp()
            self.pages['/quest/99001/q'] = answer
            done, _ = self.pull()
            self.assertTrue(done['stopped'])
            self.assertEqual(self.asked.count('/quest/99001/q'), 1, 'nothing is retried around a refusal')
            noted = site.readings(self.data).get('quest/99001.html.gz')
            if answer[0] == 403:
                self.assertEqual((noted['s'], noted['refused']), (403, 403), 'a refused page is noted')
                self.assertNotIn('key', noted)
            else:
                self.assertIsNone(noted, 'a challenge is about the visitor, not the page')

    def test_the_next_run_begins_past_a_refused_page(self):
        self.pages['/quest/99001/q'] = (403, {}, b'')
        done, _ = self.pull()
        self.assertIn('403', done['stopped'])
        self.pages['/quest/99001/q'] = (200, {}, QUEST_SEEN.encode())
        self.asked.clear()
        done, _ = self.pull()
        self.assertEqual(done['stopped'], '')
        self.assertNotIn('/quest/99001/q', self.asked, 'not asked again before `older` days')
        self.now[0] += 15 * 86400
        self.asked.clear()
        done, _ = self.pull()
        self.assertIn('/quest/99001/q', self.asked, 'asked again with the rest after `older` days')

    def test_a_refused_page_read_before_keeps_what_it_said(self):
        self.pull()
        before = site.readings(self.data)['quest/99001.html.gz']
        self.assertIn('key', before)
        self.now[0] += 15 * 86400
        self.pages['/quest/99001/q'] = (403, {}, b'')
        self.asked.clear()
        done, _ = self.pull()
        self.assertIn('403', done['stopped'])
        after = site.readings(self.data)['quest/99001.html.gz']
        self.assertEqual((after['s'], after['key'], after['refused']), (200, before['key'], 403))
        self.assertGreater(after['at'], before['at'])

    def test_an_answer_that_is_not_the_page_stops_the_run(self):
        self.pages['/map/kalimdor/npcs.json'] = (200, {}, b'<html>soon</html>')
        done, _ = self.pull()
        self.assertIn('not the data file', done['stopped'])


class Pages(unittest.TestCase):
    def test_a_quest_nobody_saw(self):
        quest = site.quest(QUEST_CLASSIC)
        self.assertFalse(quest['seen_by_players'])
        self.assertEqual(quest['id'], 2)
        self.assertIsNone(site.quest('<main><h1>Not a quest</h1></main>'))

    def test_an_item_without_sources(self):
        item = site.item('<main><h1>Plain</h1><p>Common, item 41.</p></main>')
        self.assertEqual((item['id'], item['sources']), (41, []))


class Givers(unittest.TestCase):
    def test_by_id(self):
        pack = {'givers': [{'kind': 'npc', 'entry': 5, 'name': 'A', 'map': 1, 'x': 10, 'y': 20, 'quests': [7, 8], 'seen': True},
                           {'kind': 'npc', 'entry': 5, 'name': 'A', 'map': 1, 'x': 10, 'y': 20, 'quests': [7], 'seen': True},
                           {'kind': 'go', 'entry': 9, 'name': 'Board', 'map': 0, 'x': 1, 'y': 2, 'quests': [3], 'seen': True},
                           {'kind': 'npc', 'entry': 6, 'name': 'B', 'map': 1, 'x': 1, 'y': 1, 'quests': [4], 'seen': False},
                           {'kind': 'npc', 'entry': 404, 'name': 'C', 'map': 1, 'x': 1, 'y': 1, 'quests': [5], 'seen': True},
                           {'kind': 'npc', 'entry': True, 'quests': [1], 'seen': True}, 'x']}
        rows, places, left = reports.givers(pack, {('npc', 5), ('go', 9), ('npc', 6)}, {('go', 9)})
        self.assertEqual(rows, [['go', 9, 3], ['npc', 5, 7], ['npc', 5, 8]])
        self.assertEqual(places, [['npc', 5, 'A', [{'m': 1, 'x': 10.0, 'y': 20.0}]]], 'one nobody spawned gets a place for the locator')
        self.assertEqual(left, {'report_giver_not_seen': 1, 'report_giver_unknown_entry': 1})
        self.assertEqual(reports.givers({}, set(), set()), ([], [], {}))


if __name__ == '__main__':
    unittest.main()
