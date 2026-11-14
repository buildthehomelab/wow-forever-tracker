"""The page reader, on pages written here in the site's shape: nothing of the site is in the tests, and no network."""
import collections
import gzip
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft import facts, foreverchanges_pages as fp

ROBOTS = b'User-agent: BadBot\nDisallow: /\n\nUser-Agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nDisallow: /search\n'
B = fp.BASE


def sitemap(*paths):
    return ('<urlset>' + ''.join(f'<url><loc>{B}{p}</loc></url>' for p in paths) + '</urlset>').encode()


SITE = {
    '/robots.txt': ROBOTS,
    '/sitemap.xml': sitemap('/', '/fr', '/fr/rares', '/rares', '/bis/mage', '/dungeons', '/dungeons/fixture-keep', '/map', '/map/east',
                            '/map/east/zone', '/quests/zone', '/professions/alchemy', '/Bad_Slug', '/a/b/c'),
    '/quest/sitemap.xml': sitemap('/quest/5/old-quest', '/quest/90001/new-quest', '/fr/quest/5/old-quest', '/quest/x/bad'),
    '/item/sitemap.xml': sitemap('/item/7/old-item', '/item/250001/new-item'),
}

QUEST = '''<html><head><title>Fixture quest</title></head><body><nav>site-header</nav><main><div class="qp-work">
<nav class="qp-crumbs"><a href="/quests">Quests</a><span>&rsaquo;</span><span>Fixture Zone</span></nav>
<header class="qp-head"><h1>Fixture Quest</h1><p class="qp-lede">A level 12 quest for the Horde, from level 8.</p>
<p class="qp-known qp-known-forever"><b class="qp-new">New in Forever.</b> Partly read from what players of our addon saw in game.</p></header>
<div class="qp-grid"><article class="qp-sheet"><h2>Quest Objectives</h2><p>Bring 3 fixtures.</p>
<ul class="qp-need"><li class="qp-need-item"><a class="qp-item" href="/item/250001/new-item" data-tip="250001"><span class="qp-item-name q1">New Item</span></a></li><li>Fixture slain: 0/3</li></ul>
<h2>Description</h2><p>First &amp; second.</p><p>Third.</p>
<h2>Rewards</h2><a class="qp-item" href="/item/7/old-item" data-tip="7"><span class="qp-item-name">Old Item</span></a>
<p class="qp-gains"><span>Money:</span> <span class="qp-money"><span class="qp-coin">4</span><span class="qp-sr">1 gold, 4 silver, 2 copper</span></span><span>Experience:</span> <b>875</b></p>
<ul class="qp-rep"><li>+50 reputation with Fixtures</li></ul>
<div class="qp-more"><details><summary>When you come back</summary><p>Have you got them?</p></details>
<details><summary>When you hand it in</summary><p>Thanks, &lsaquo;name&rsaquo;.</p><p>Go on.</p></details></div></article>
<aside class="qp-side"><figure class="qp-map"><div class="qp-map-frame"><img src="/quests/maps/1420.webp" alt=""/>
<span class="qp-dot" style="left:1%;top:2%"></span><span class="qp-dot" style="left:3%;top:4%"></span></div></figure>
<dl class="qp-facts"><dt>Start</dt><dd><span>Giver One<span class="qp-coord">Fixture Zone<!-- --> 21.8<!-- -->, <!-- -->45.3</span></span></dd>
<dt>End</dt><dd><span>Ender Two<span class="qp-coord">Other Zone 77.1, 52.9</span></span></dd>
<dt>Level</dt><dd>12, requires level 8</dd><dt>Side</dt><dd>Horde</dd><dt>Class</dt><dd>Mage</dd><dt>Quest ID</dt><dd>90001</dd></dl></aside></div></div></main><footer>site-footer</footer></body></html>'''

ITEM = '''<html><head><title>Fixture item</title></head><body><main><h1>Fixture Item</h1><p>Common, item level 10, item 250001.</p><p>New in Forever: no such id.</p>
<section class="it-from" aria-labelledby="h-from"><h2 id="h-from">Where it comes from</h2>
<div class="it-from-group"><h3>Sold by a vendor</h3><ul><li><b>Seller One</b><span>Fixture Zone<!-- --> (<!-- -->22.4<!-- -->, <!-- -->48.0<!-- -->)</span><em>9s 1c</em></li>
<li><b>&lt;b&gt;Seller&lt;/b&gt;</b><span>Capital</span><em>1g 2s</em></li></ul></div>
<div class="it-from-group"><h3>Dungeon drop</h3><ul><li><a href="/dungeons/fixture-keep#boss">Boss One</a><span>Fixture Keep</span><em title="Seen in game: 88 in 288 kills">31%</em></li></ul></div>
<div class="it-from-group"><h3>Creature drop</h3><ul><li><b>Mob One</b><span>Fixture Zone</span><em>7.7%</em></li><li><b>Mob Two</b><span>Fixture Zone</span><em>5 in 41 kills</em></li></ul></div></section>
<section class="it-from it-near"><h2>What else Boss One drops</h2><ul><li><a href="/item/7/old-item">Old Item</a><span>Wrist</span><em>item level 18</em></li></ul></section></main></body></html>'''

NPCS = {'source': 'QuestieDB', 'npcs': [[54, 'Smith', 'Weaponsmith', 'A', -9465, 94, 'vendor'], [198, 'Mage', 'Mage Trainer', 'A', -8852, -188, 'trainer', 'mage'],
                                        [250777, 'Seller One', '', 'AH', -10450, -2799, 'vendor', '', 'addon'], [54, 'Smith', 'Weaponsmith', 'A', -9000, 90, 'vendor'],
                                        ['x', 'broken'], [0, 'Zero', '', 'A', 1, 1, 'npc']]}


GIVERS = {'source': 'QuestieDB', 'quests': {'90001': ['Fixture Quest', 12, 1]},
          'givers': [['n300', 'Giver One', 'Captain', 'H', 100, -200, [90001, 5]], ['n300', 'Giver One', 'Captain', 'H', 100, -200, [90001]],
                     ['o400', 'Wanted Poster', '', '', 1, 2, [5]], ['o401', 'Wanted Poster', '', '', 3, 4, [6]], ['x9', 'Broken', '', '', 0, 0, [1]]]}
MOBS = {'source': 'QuestieDB', 'mobs': [[500, 'Mob One', 10, 11, 4, [[4521, 661], [4522, 662]]], ['bad']]}


class Site:
    """Answers like the site, and notes what was asked."""
    def __init__(self, pages=None):
        self.pages = dict(SITE, **{'/quest/90001/new-quest': QUEST.encode(), '/quest/5/old-quest': QUEST.replace('90001', '5').encode(),
                                   '/item/250001/new-item': ITEM.encode(), '/item/7/old-item': ITEM.encode(), '/rares': b'<main><h1>Rares</h1></main>',
                                   '/dungeons/fixture-keep': b'<main><h1>Keep</h1></main>', '/quests/zone': b'<main>zone</main>',
                                   '/professions/alchemy': b'<main>alchemy</main>', '/map/east/npcs.json': json.dumps(NPCS).encode(),
                                   '/map/east/quest-givers.json': json.dumps(GIVERS).encode(), '/map/east/creatures.json': json.dumps(MOBS).encode()})
        self.pages.update(pages or {})
        self.asked, self.naps = [], []

    def get(self, path):
        self.asked.append(path)
        answer = self.pages.get(path)
        if isinstance(answer, int):
            return answer, 'text/html', b''
        if answer is None:
            return 404, 'text/html', b'not found'
        return 200, 'application/json' if path.endswith('.json') else 'text/html', answer

    def run(self, folder, **options):
        return fp.mirror(folder, get=self.get, sleep=self.naps.append, log=lambda message: None, **options)


class Plan(unittest.TestCase):
    def test_robots_names_what_is_closed_to_everyone(self):
        closed = fp.disallowed(ROBOTS.decode())
        self.assertEqual(closed, ['/admin', '/api/', '/search'])                    # another reader's group is not ours
        self.assertFalse(fp.allowed('/api/x', closed))
        self.assertFalse(fp.allowed('/search?q=1', closed))
        self.assertTrue(fp.allowed('/quest/5/old-quest', closed))

    def test_the_plan_is_english_world_pages_new_ids_first(self):
        rows = fp.plan(*(SITE[p].decode() for p in ('/sitemap.xml', '/quest/sitemap.xml', '/item/sitemap.xml')))
        paths = [row[1] for row in rows]
        self.assertEqual(paths[:len(fp.MAP_FILES)], [f'/map/east/{name}.json' for name in fp.MAP_FILES])     # a map's data files, not its pages
        self.assertEqual(paths[len(fp.MAP_FILES):], ['/dungeons/fixture-keep', '/rares', '/quests/zone', '/professions/alchemy',
                                                     '/quest/90001/new-quest', '/item/250001/new-item', '/quest/5/old-quest', '/item/7/old-item'])     # Forever's own of both kinds first
        self.assertEqual([fp.own(row[2]) for row in rows[-4:]], [True, True, False, False])
        self.assertEqual(len({row[2] for row in rows}), len(rows))                  # one file per page
        self.assertFalse(any('..' in row[2] or row[2].startswith('/') for row in rows))


class Mirror(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = self.temp.name

    def test_it_reads_robots_first_keeps_the_main_part_and_does_not_ask_twice(self):
        site = Site()
        result = site.run(self.folder, pause=3)
        self.assertEqual(site.asked[:4], ['/robots.txt', '/sitemap.xml', '/quest/sitemap.xml', '/item/sitemap.xml'])
        self.assertEqual(result['kept'], 11)                                        # three map files and eight pages
        self.assertEqual(result['missing'], len(fp.MAP_FILES) - 3)                  # the map's other files do not exist
        self.assertEqual(site.naps, [3] * (len(site.asked) - 1))                    # a pause between any two requests
        kept = gzip.decompress((Path(self.folder) / 'quest/90001.html.gz').read_bytes()).decode()
        self.assertIn('<title>Fixture quest</title>', kept)
        self.assertNotIn('site-', kept)                                             # the site's frame is not kept
        again = Site()
        result = again.run(self.folder, pause=3)
        self.assertEqual(again.asked, ['/robots.txt', '/sitemap.xml', '/quest/sitemap.xml', '/item/sitemap.xml'])    # nor a page that was missing
        self.assertEqual((result['read'], result['left']), (0, 0))

    def test_a_refusal_stops_the_run_and_nothing_is_retried_around_it(self):
        for status in (401, 403, 429, 451):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                site = Site({'/rares': status})
                with self.assertRaises(fp.Refused):
                    site.run(folder, only=('topics',))
                self.assertEqual(site.asked.count('/rares'), 1)
                self.assertEqual(site.asked[-1], '/rares')                          # the pages after it are not asked

    def test_a_page_that_is_not_the_page_stops_the_run(self):
        for pages in ({'/rares': b'<html><body>Checking your browser</body></html>'}, {'/map/east/npcs.json': b'<html>check</html>'},
                      {'/robots.txt': 500}, {'/robots.txt': 404}, {'/item/sitemap.xml': b'<html>no list</html>'}):
            with self.subTest(pages=list(pages)), tempfile.TemporaryDirectory() as folder, self.assertRaises(fp.Refused):
                Site(pages).run(folder)

    def test_a_path_robots_closes_is_never_asked(self):
        site = Site({'/robots.txt': ROBOTS + b'Disallow: /quest/\n'})
        with self.assertRaises(fp.Refused):
            site.run(self.folder)
        self.assertFalse(any(path.startswith('/quest/') for path in site.asked))

    def test_a_server_error_is_tried_three_times_then_the_run_stops(self):
        site = Site({'/rares': 503})
        with self.assertRaises(fp.Refused):
            site.run(self.folder, only=('topics',))
        self.assertEqual(site.asked.count('/rares'), 3)

    def test_one_reader_a_folder(self):
        held = fp.lock(self.folder)
        try:
            site = Site()
            with self.assertRaises(fp.Refused):
                site.run(self.folder)
            self.assertEqual(site.asked, [])                                        # refused before the site is asked anything
        finally:
            held.close()
        self.assertEqual(Site().run(self.folder, only=('topics',), limit=1)['read'], 1)     # free again once the first has ended

    def test_only_and_limit(self):
        site = Site()
        result = site.run(self.folder, only=('quests',), limit=1)
        self.assertEqual(site.asked[4:], ['/quest/90001/new-quest'])
        self.assertEqual((result['read'], result['left']), (1, 1))


DAY = 86400
BARE = QUEST.replace('<details><summary>When you hand it in</summary><p>Thanks, &lsaquo;name&rsaquo;.</p><p>Go on.</p></details>', '')
NEW_QUEST, OLD_QUEST, NEW_ITEM, OLD_ITEM = '/quest/90001/new-quest', '/quest/5/old-quest', '/item/250001/new-item', '/item/7/old-item'


class Update(unittest.TestCase):
    """The later visits: what is read again, in which order, and what is noted."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = self.temp.name
        self.now = 1_800_000_000

    def visit(self, pages=None, days=0, **options):
        self.now += days * DAY
        site = Site(pages)
        return site, site.run(self.folder, clock=lambda: self.now, **options)

    def changes(self):
        path = Path(self.folder) / fp.CHANGES
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_a_page_read_lately_is_not_read_again_and_an_unchanged_one_is_noted_as_nothing(self):
        self.visit()
        site, result = self.visit(days=3, refresh=14)
        self.assertEqual((len(site.asked), result['read']), (4, 0))                 # the lists, and nothing else
        site, result = self.visit(days=20, refresh=14)
        self.assertEqual(result['read'], 8 + len(fp.MAP_FILES))                     # every page, and the map files that were not there
        self.assertEqual((result['same'], result['changed'], result['new'], result['gone']), (11, 0, 0, 0))
        self.assertEqual(self.changes(), [])

    def test_what_changed_is_named_by_the_records_field_and_a_new_wrapping_is_no_change(self):
        self.visit({NEW_QUEST: BARE.encode()})
        self.assertTrue(fp.state(self.folder)['quest/90001.html.gz']['want'])       # Forever's own, no hand-in text yet
        self.assertNotIn('want', fp.state(self.folder)['quest/5.html.gz'])          # Classic's page is never "lacking"
        wrapped = ITEM.replace('<section class="it-from"', '<section data-build="2" class="it-from"').encode()
        _site, result = self.visit({NEW_ITEM: wrapped}, days=20, refresh=14)        # the quest has its text now, the item only new markup
        self.assertEqual((result['changed'], result['same']), (1, 10))
        self.assertEqual([(c['what'], c['file'], c['fields']) for c in self.changes()], [('changed', 'quest/90001.html.gz', ['texts'])])
        self.assertEqual(self.changes()[0]['page'], B + NEW_QUEST)
        self.assertNotIn('want', fp.state(self.folder)['quest/90001.html.gz'])
        self.assertIn(b'data-build="2"', gzip.decompress((Path(self.folder) / 'item/250001.html.gz').read_bytes()))     # the kept copy is the latest

    def test_the_order_of_an_update_small_files_then_what_lacks_then_forevers_own_then_classics(self):
        self.visit({NEW_ITEM: ITEM.split('<section')[0].encode() + b'</main>'})    # an item no source is named for
        site, result = self.visit(days=20, refresh=14, only=('topics', 'quests', 'items'))
        self.assertEqual(site.asked[4:], ['/rares', '/quests/zone', '/professions/alchemy', NEW_ITEM, NEW_QUEST, OLD_QUEST, OLD_ITEM])
        site, result = self.visit(days=20, refresh=14, only=('quests', 'items'), limit=1)
        self.assertEqual((site.asked[4:], result['left']), ([NEW_QUEST], 3))        # a visit can be bounded: the rest waits for the next

    def test_a_page_the_lists_newly_name_is_read_and_one_they_drop_is_noted_once(self):
        self.visit()
        more = {'/quest/sitemap.xml': sitemap(NEW_QUEST, '/quest/90002/newer-quest'), '/quest/90002/newer-quest': QUEST.replace('90001', '90002').encode()}
        site, result = self.visit(more, days=1, refresh=14)
        self.assertEqual((site.asked[4:], result['new'], result['gone']), (['/quest/90002/newer-quest'], 1, 1))
        self.assertEqual([(c['what'], c['file']) for c in self.changes()], [('gone', 'quest/5.html.gz'), ('new', 'quest/90002.html.gz')])
        self.assertTrue((Path(self.folder) / 'quest/5.html.gz').exists())           # what the site once stated stays
        _site, result = self.visit(more, days=1, refresh=14)
        self.assertEqual((result['gone'], len(self.changes())), (0, 2))

    def test_a_kept_page_the_site_no_longer_has_and_a_file_that_was_not_there_before(self):
        self.visit()
        rares = json.dumps({'source': 'x', 'mobs': []}).encode()
        _site, result = self.visit({'/rares': 404, '/map/east/rares.json': rares}, days=20, refresh=14)
        self.assertEqual((result['gone'], result['new']), (1, 1))
        self.assertEqual(sorted((c['what'], c['file']) for c in self.changes()), [('gone', 'page/rares.html.gz'), ('new', 'map/east/rares.json')])
        self.assertTrue((Path(self.folder) / 'page/rares.html.gz').exists())

    def test_a_quest_whose_map_row_changed_is_read_at_once_though_it_is_not_due(self):
        self.visit()
        self.visit(days=10, refresh=14, only=('quests',))                           # nothing due yet
        self.visit(days=5, refresh=14, only=('maps',))                              # the map files were read on day 15: only the quests are due later
        moved = dict(GIVERS, givers=[['n300', 'Giver One', 'Captain', 'H', 150, -200, [90001]]] + GIVERS['givers'][1:])
        self.now += 15 * DAY                                                        # maps 15 days old, quests 30
        site = Site({'/map/east/quest-givers.json': json.dumps(moved).encode()})
        result = site.run(self.folder, clock=lambda: self.now, refresh=14, only=('maps', 'quests'), limit=4)
        self.assertEqual(site.asked[4:], ['/map/east/npcs.json', '/map/east/quest-givers.json', OLD_QUEST, NEW_QUEST])     # both quests of the row, before the other map files
        self.assertIn(('changed', 'map/east/quest-givers.json', ['givers']), [(c['what'], c['file'], c.get('fields')) for c in self.changes()])
        self.assertEqual(result['left'], len(fp.MAP_FILES) - 2)                     # the other map files

    def test_a_plain_mirror_never_reads_a_kept_page_again(self):
        self.visit()
        site, result = self.visit({NEW_QUEST: BARE.encode()}, days=400)
        self.assertEqual((len(site.asked), result['read']), (4, 0))

    def test_a_folder_without_its_notes_takes_the_files_dates_and_a_cut_line_is_passed_over(self):
        self.now = time.time()                                                      # the files' own dates are the real clock's
        self.visit()
        notes = Path(self.folder) / fp.STATE
        notes.write_text(notes.read_text(encoding='utf-8').splitlines()[0] + '\n{"f": "quest/5.html.gz", "at": "20', encoding='utf-8')
        self.assertEqual(len(fp.state(self.folder)), 1)
        site, result = self.visit(days=1, refresh=14)                               # the kept files are a second old: none is due
        self.assertEqual(result['kept'], 0)
        self.assertEqual(result['missing'], len(fp.MAP_FILES) - 3)                  # only what nothing says was ever asked

    def test_status_says_what_is_here_what_is_left_and_what_is_due_without_asking_the_site(self):
        self.assertEqual(fp.status(self.folder)['groups'], [])
        self.visit({NEW_QUEST: BARE.encode()}, only=('maps', 'quests'))
        found = fp.status(self.folder, older=14, clock=lambda: self.now + 20 * DAY)
        rows = {group['name']: group for group in found['groups']}
        self.assertEqual((rows['map data files']['listed'], rows['map data files']['kept'], rows['map data files']['not there'], rows['map data files']['left']),
                         (len(fp.MAP_FILES), 3, len(fp.MAP_FILES) - 3, 0))
        self.assertEqual((rows["Forever's own quests"]['kept'], rows["Forever's own quests"]['lacking'], rows["Classic's quests"]['kept']), (1, 1, 1))
        self.assertEqual((rows["Forever's own items"]['left'], rows["Classic's items"]['left'], rows['topic pages']['left']), (1, 1, 3))
        self.assertEqual((found['left'], found['due'], found['reader']), (6, len(fp.MAP_FILES) + 2, False))
        said = []
        fp.report(found, said.append)
        self.assertIn('6 pages left', ' '.join(said))
        held = fp.lock(self.folder)
        try:
            self.assertTrue(fp.status(self.folder)['reader'])
        finally:
            held.close()


class Pages(unittest.TestCase):
    def test_a_quest_page(self):
        q = fp.quest(QUEST)
        self.assertEqual((q['id'], q['title'], q['level'], q['min_level'], q['side'], q['class']), (90001, 'Fixture Quest', 12, 8, 'Horde', 'Mage'))
        self.assertTrue(q['new'] and q['seen_by_players'])
        self.assertEqual(q['category'], ['Fixture Zone'])
        self.assertEqual(q['objectives'], 'Bring 3 fixtures.')
        self.assertEqual(q['description'], 'First & second.\n\nThird.')
        self.assertEqual(q['texts'], {'progress': 'Have you got them?', 'complete': 'Thanks, ‹name›.\n\nGo on.'})
        self.assertEqual(q['start'], [{'name': 'Giver One', 'zone': 'Fixture Zone', 'x': 21.8, 'y': 45.3}])
        self.assertEqual(q['end'], [{'name': 'Ender Two', 'zone': 'Other Zone', 'x': 77.1, 'y': 52.9}])
        self.assertEqual((q['money'], q['xp'], q['reputation']), (10402, 875, ['+50 reputation with Fixtures']))
        self.assertEqual(q['needs'], [{'item': 250001, 'name': 'New Item'}])
        self.assertEqual(q['counts'], ['Fixture slain: 0/3'])
        self.assertEqual(q['reward_items'], [{'item': 7, 'name': 'Old Item'}])
        self.assertEqual((q['ui_map'], q['objective_spots']), (1420, 2))
        self.assertIsNone(fp.quest('<main><h1>Not a quest</h1></main>'))

    def test_an_item_that_starts_a_quest_is_not_an_npc(self):
        page = QUEST.replace('<span>Giver One<span class="qp-coord">Fixture Zone<!-- --> 21.8<!-- -->, <!-- -->45.3</span></span>', '<span>an item: Old Letter</span>')
        self.assertEqual(fp.quest(page)['start'], [{'item': 'Old Letter'}])

    def test_an_item_page(self):
        i = fp.item(ITEM)
        self.assertEqual((i['id'], i['name'], i['new']), (250001, 'Fixture Item', True))
        self.assertEqual(i['sources'], [
            {'how': 'Sold by a vendor', 'name': 'Seller One', 'place': 'Fixture Zone', 'x': 22.4, 'y': 48.0, 'price': 901},
            {'how': 'Sold by a vendor', 'name': '<b>Seller</b>', 'place': 'Capital', 'price': 10200},
            {'how': 'Dungeon drop', 'name': 'Boss One', 'link': '/dungeons/fixture-keep#boss', 'place': 'Fixture Keep', 'rate': {'percent': 31.0, 'drops': 88, 'kills': 288}},
            {'how': 'Creature drop', 'name': 'Mob One', 'place': 'Fixture Zone', 'rate': {'percent': 7.7}},
            {'how': 'Creature drop', 'name': 'Mob Two', 'place': 'Fixture Zone', 'rate': {'drops': 5, 'kills': 41}}])     # "what else it drops" is no source
        self.assertEqual(fp.item('<main><h1>Bare</h1><p>item 9.</p></main>')['sources'], [])
        self.assertIsNone(fp.item('<main><p>nothing</p></main>'))


class Facts(unittest.TestCase):
    def test_kept_pages_become_references_without_a_build(self):
        with tempfile.TemporaryDirectory() as folder:
            Site().run(folder)
            skipped = collections.Counter()
            records = list(fp.read(folder, skipped))
            by = {(r.subject_kind, r.subject): r for r in records}
            self.assertTrue(all(r.kind == 'reference' and r.build == 0 and r.samples == 0 and facts.check(r) for r in records))
            self.assertEqual(set(by), {('quest', 90001), ('quest', 5), ('quest', 6), ('item', 250001), ('item', 7), ('npc', 54), ('npc', 198),
                                       ('npc', 250777), ('npc', 500)})
            new = by['quest', 90001].data
            self.assertEqual(new['page'], B + '/quest/90001/new-quest')
            self.assertRegex(new['read'], r'^\d{4}-\d\d-\d\d$')
            self.assertEqual(new['datasets']['quest_page'][0]['texts']['progress'], 'Have you got them?')
            self.assertIn('description', new['datasets']['quest_page'][0])
            self.assertEqual(by['item', 250001].data['datasets']['item_page'][0]['sources'][0]['price'], 901)
            smith = by['npc', 54].data['datasets']['map_npc'][0]
            self.assertEqual(smith, {'name': 'Smith', 'title': 'Weaponsmith', 'side': 'A', 'role': 'vendor', 'kind': '', 'recorded_by_players': False,
                                     'spots': [['east', -9465, 94], ['east', -9000, 90]], 'layer_from': 'QuestieDB'})
            self.assertTrue(by['npc', 250777].data['datasets']['map_npc'][0]['recorded_by_players'])
            self.assertEqual(by['npc', 198].data['datasets']['map_npc'][0]['kind'], 'mage')
            self.assertEqual((skipped['map_npc'], skipped['map_giver'], skipped['map_creature']), (2, 1, 1))     # a row without an id is counted, once

    def test_who_starts_a_quest_comes_by_id_from_the_map_and_joins_the_quests_page(self):
        with tempfile.TemporaryDirectory() as folder:
            Site().run(folder)
            by = {(r.subject_kind, r.subject): r.data['datasets'] for r in fp.read(folder)}
            self.assertEqual(set(by['quest', 90001]), {'quest_page', 'map_givers'})         # one fact for the quest, both datasets
            self.assertEqual(by['quest', 90001]['map_givers'], [{'kind': 'npc', 'id': 300, 'name': 'Giver One', 'title': 'Captain', 'side': 'H',
                                                                 'spots': [['east', 100, -200]], 'layer_from': 'QuestieDB'}])
            self.assertEqual(by['quest', 6]['map_givers'][0]['kind'], 'object')            # a quest the mirror has no page of yet
            self.assertEqual(by['npc', 500]['map_creature'], [{'name': 'Mob One', 'levels': [10, 11], 'class': 4,
                                                               'spots': [['east', 4521, 661], ['east', 4522, 662]], 'layer_from': 'QuestieDB'}])

    def test_a_name_on_a_page_gets_the_one_id_the_map_knows_it_by(self):
        with tempfile.TemporaryDirectory() as folder:
            Site().run(folder)
            about = {}
            by = {(r.subject_kind, r.subject): r.data['datasets'] for r in fp.read(folder, about=about)}
            page = by['quest', 90001]['quest_page'][0]
            self.assertEqual(page['start'][0], {'name': 'Giver One', 'zone': 'Fixture Zone', 'x': 21.8, 'y': 45.3, 'kind': 'npc', 'id': 300,
                                             'matched_by': 'name', 'named_in': ['map']})
            self.assertEqual(page['end'][0], {'name': 'Ender Two', 'zone': 'Other Zone', 'x': 77.1, 'y': 52.9})      # nobody of that name: no id, no guess
            sources = {s['name']: s for s in by['item', 250001]['item_page'][0]['sources']}
            self.assertEqual((sources['Seller One']['id'], sources['Seller One']['matched_by']), (250777, 'name'))
            self.assertEqual(sources['Mob One']['id'], 500)
            self.assertNotIn('id', sources['Boss One'])
            self.assertEqual(about['names'], {'one id': 6, 'no id': 8})            # both quest pages and both item pages, name by name
            index = fp.name_index(folder, extra=[('npc', 9, 'Ender Two', 'world'), ('npc', 10, 'ender  two', 'facts'), ('npc', 300, 'Giver One', 'world')])
            self.assertEqual(fp.match(index, 'Wanted Poster'), {'candidates': [['object', 400], ['object', 401]]})   # two things, nothing picked
            self.assertEqual(fp.match(index, 'ENDER TWO'), {'candidates': [['npc', 9], ['npc', 10]]})
            self.assertEqual(fp.match(index, 'giver\u2019s'), {})
            self.assertEqual(fp.match(index, ' giver   one '), {'kind': 'npc', 'id': 300, 'matched_by': 'name', 'named_in': ['map', 'world']})
            self.assertEqual(fp.match(index, ''), {})

    def test_a_classic_quests_own_text_and_an_item_without_a_source_are_left_out(self):
        with tempfile.TemporaryDirectory() as folder:
            site = Site({'/quest/5/old-quest': QUEST.replace('90001', '5').replace('<b class="qp-new">New in Forever.</b>', '').encode(),
                         '/item/7/old-item': b'<main><h1>Old Item</h1><p>item 7.</p></main>'})
            site.run(folder)
            by = {(r.subject_kind, r.subject): r for r in fp.read(folder)}
            old = by['quest', 5].data['datasets']['quest_page'][0]
            self.assertNotIn('description', old)
            self.assertNotIn('objectives', old)
            self.assertIn('complete', old['texts'])                                 # what the server says at the hand-in is not in the client
            self.assertNotIn(('item', 7), by)

    def test_names_the_tracker_already_knows_by_id_widen_the_match(self):
        asked, said = [], []
        def query(sql, database):
            asked.append((database, sql))
            if 'creature_template' in sql:
                return [{'entry': '77', 'name': 'Ender Two'}, {'entry': '78', 'name': ''}]
            if 'gameobject_template' in sql:
                raise RuntimeError('no such table')
            return [{'subject_kind': 'npc', 'subject': '79', 'data': json.dumps({'name': 'Boss One'})},
                    {'subject_kind': 'npc', 'subject': '80', 'data': json.dumps({'parts': {'generated': {'name': 'Mob Two'}, 'fix': 'none'}})},
                    {'subject_kind': 'npc', 'subject': '81', 'data': 'not json'}]
        extra = fp.known_names(query, said.append)
        self.assertEqual(extra, [('npc', 77, 'Ender Two', 'world'), ('npc', 79, 'Boss One', 'facts'), ('npc', 80, 'Mob Two', 'facts')])
        self.assertEqual(len(said), 1)                                              # the table that could not be read is said, not fatal
        self.assertIn("NOT LIKE 'foreverchanges%'", asked[-1][1])                   # its own records never confirm its own names
        with tempfile.TemporaryDirectory() as folder:
            Site().run(folder)
            about = {}
            by = {(r.subject_kind, r.subject): r.data['datasets'] for r in fp.read(folder, about=about, extra=extra)}
            self.assertEqual(by['quest', 90001]['quest_page'][0]['end'][0]['id'], 77)
            self.assertEqual(by['quest', 90001]['quest_page'][0]['end'][0]['named_in'], ['world'])
            self.assertEqual(about['names'], {'one id': 12, 'no id': 2})


if __name__ == '__main__':
    unittest.main()
