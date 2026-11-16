"""python -m unittest discover -s tools/tests

Written notes for the timeline (ft.notes): ForeverChanges' patch-notes pages, Blizzard's blue posts and its hotfix
posts read a day at a time, and the two put together by day (Blizzard's words first).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

from ft import notes  # noqa: E402

MARK = '<svg class="v2-mark is-{0}" role="img" aria-label="{1}"><title>{1}</title><path d=""></path></svg>'
PAGE = ('<ol class="bt-builds">'
        '<li id="hotfix-2026-11-12"><div class="bt-build-id"><h2><time dateTime="2026-11-12">November 12, 2026</time></h2></div>'
        '<div class="bt-build-body"><p>From <a href="https://us.forums.blizzard.com/en/wow/t/2403040/9">Blizzard’s notes</a>:</p>'
        '<section data-class="shaman"><h3><img src="x.jpg"/>Shaman</h3><ul class="pn-live-lines">'
        f'<li>{MARK.format("nerf", "Nerfs")}<span>Stormstrike deals 100% weapon damage (was 150%).</span></li>'
        f'<li>{MARK.format("buff", "Buffs")}<span>Windfury Weapon &amp; Totem both work.</span></li></ul></section></div></li>'
        '<li id="1.60.1.70888" class="is-announced"><div class="bt-build-id"><h2><time dateTime="2026-11-10">November 10, 2026</time></h2></div>'
        '<div class="bt-build-body"><p>The client of November 10.</p><details class="bt-note-class pn-fold"><summary><img/><span>Priest</span>'
        '<small>1 change</small></summary><div class="bt-note-body"><ul class="pn-lines">'
        f'<li>{MARK.format("change", "Changes")}<span class="pn-line"><a href="/spellbook/priest">Fear Ward</a>: <!-- -->castable in Shadowform.</span></li>'
        '</ul></div></details></div></li></ol><footer><li>not a note</li></footer>')

HOTFIX_POST = ('<h2><strong>Hotfixes</strong></h2><hr><p><strong>November 13, 2026</strong></p><p><strong>Classes</strong></p>'
               '<ul>\n<li><strong>Druid</strong>\n<ul>\n<li>Wild Growth heals more.</li>\n<li><strong>Feral</strong>\n<ul>\n<li>Pounce fixed.</li>\n</ul>\n</li>\n</ul>\n</li>\n</ul>'
               '<p><strong>Items</strong></p><ul>\n<li>Bad Hat lost its spell damage.</li>\n</ul>'
               '<p><strong>November 12, 2026</strong></p><p><strong>Quests</strong></p><ul>\n<li>A quest fixed.</li>\n</ul>')


class Pages(unittest.TestCase):
    def test_a_page_of_notes(self):
        found = notes.parse_page(PAGE)
        self.assertEqual([(n['id'], n['kind'], n['day'], n['build']) for n in found],
                         [('hotfix-2026-11-12', 'hotfix', '2026-11-12', None), ('1.60.1.70888', 'build', '2026-11-10', 70888)])
        self.assertEqual(found[0]['sections'], [{'name': 'Shaman', 'lines': [
            {'text': 'Stormstrike deals 100% weapon damage (was 150%).', 'mark': 'nerf'},
            {'text': 'Windfury Weapon & Totem both work.', 'mark': 'buff'}]}])
        self.assertEqual(found[0]['blizzard'], ['https://us.forums.blizzard.com/en/wow/t/2403040/9'])
        self.assertEqual(found[1]['summary'], ['The client of November 10.'])
        self.assertEqual(found[1]['sections'], [{'name': 'Priest', 'lines': [{'text': 'Fear Ward: castable in Shadowform.', 'mark': 'change'}]}])

    def test_every_page_until_one_is_missing(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        asked = []

        def get(url):
            asked.append(url)
            if url.endswith('feed.xml'):
                return ('<rss><channel><item><title>Hotfix, November 12, 2026</title><link>https://foreverchanges.pro/patch-notes#hotfix-2026-11-12</link>'
                        '<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate><description>Shaman changes.</description></item></channel></rss>')
            if url.endswith('/page/2'):
                raise urllib.error.HTTPError(url, 404, 'not found', None, None)
            return PAGE
        result = notes.fetch(folder, get=get, pause=0, log=lambda *_: None)
        self.assertEqual((result['code'], result['notes']), (0, 2))
        self.assertEqual(asked[-1], f'{notes.FOREVERCHANGES}/page/2')
        stored = notes.load(folder)
        self.assertEqual([n['id'] for n in stored], ['1.60.1.70888', 'hotfix-2026-11-12'])   # oldest first
        self.assertEqual(stored[1]['title'], 'Hotfix, November 12, 2026')
        self.assertEqual(notes.fetch(folder, get=get, pause=0, log=lambda *_: None)['code'], 3)


class Blizzard(unittest.TestCase):
    def test_a_hotfix_post_a_day_at_a_time(self):
        days = notes.post_days(HOTFIX_POST, '2026-11-14')
        self.assertEqual([d['day'] for d in days], ['2026-11-13', '2026-11-12'])
        self.assertEqual(days[0]['sections'], [
            {'name': 'Classes', 'lines': [{'text': 'Druid: Wild Growth heals more.', 'mark': ''}, {'text': 'Druid: Feral: Pounce fixed.', 'mark': ''}]},
            {'name': 'Items', 'lines': [{'text': 'Bad Hat lost its spell damage.', 'mark': ''}]}])

    def test_a_post_without_dates_is_of_its_own_day(self):
        days = notes.post_days('<p>We deployed a change to dungeon experience.</p>', '2026-11-15')
        self.assertEqual(days, [{'day': '2026-11-15', 'sections': [{'name': 'Notes', 'lines': [{'text': 'We deployed a change to dungeon experience.', 'mark': ''}]}]}])

    def forum(self, posts, full):
        def get(url):
            if url.endswith('/site.json'):
                return {'categories': [{'id': 346, 'slug': 'wow-forever'}, {'id': 352, 'slug': 'wow-forever-bug-report', 'parent_category_id': 346},
                                       {'id': 349, 'slug': 'wow-forever-beta-discussion', 'parent_category_id': 23}, {'id': 40, 'slug': 'general-discussion'}]}
            if '/groups/blizzard-tracker/posts.json' in url:
                return {'posts': [] if 'before_post_id' in url else posts}
            return full[int(url.rsplit('/', 1)[1].split('.')[0])]
        return get

    def test_the_blue_posts_of_the_games_forums_only(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        listed = [
            {'id': 3, 'created_at': '2026-11-14T01:54:00Z', 'category_id': 352, 'topic_title': 'WoW: Forever Hotfixes - November 13, 2026', 'topic_id': 9,
             'topic_slug': 'hotfixes', 'post_number': 10, 'username': 'Kaivax', 'user_title': 'Community Manager', 'excerpt': 'November 13'},
            {'id': 2, 'created_at': '2026-11-13T21:00:00Z', 'category_id': 40, 'topic_title': 'Retail news', 'topic_id': 8, 'post_number': 1, 'username': 'X'},
            {'id': 1, 'created_at': '2026-07-30T10:00:00Z', 'category_id': 349, 'topic_title': 'Beta soon', 'topic_id': 7, 'topic_slug': 'beta',
             'post_number': 1, 'username': 'Aggrend', 'excerpt': 'Soon&hellip;'}]
        full = {3: {'cooked': HOTFIX_POST, 'updated_at': '2026-11-14T02:00:00Z'}, 1: {'cooked': '<p>Soon.</p>'}}
        result = notes.fetch_blizzard(folder, get=self.forum(listed, full), pause=0, log=lambda *_: None, since='2026-07-01')
        self.assertEqual((result['code'], result['posts']), (0, 2))
        posts = notes.blue_posts(folder)
        self.assertEqual([(p['id'], p['hotfixes'], p['url']) for p in posts],
                         [(1, False, f'{notes.FORUM}/t/beta/7/1'), (3, True, f'{notes.FORUM}/t/hotfixes/9/10')])
        by_day = notes.days(folder)
        self.assertEqual([s['name'] for s in by_day['2026-11-13']['blizzard']['sections']], ['Classes', 'Items'])
        self.assertEqual(by_day['2026-11-14']['posts'], [3])
        # asked again: nothing new, and a hotfix post read again without a change is no news
        self.assertEqual(notes.fetch_blizzard(folder, get=self.forum(listed, full), pause=0, log=lambda *_: None, since='2026-07-01')['code'], 3)

    def test_a_line_blizzard_posted_twice_is_kept_once_and_foreverchanges_fills_the_gap(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        post = {'hotfixes': True, 'url': 'u', 'date': '2026-11-14T01:00:00Z', 'days': notes.post_days(HOTFIX_POST, '2026-11-14')}
        with open(os.path.join(folder, notes.BLUE_FILE), 'w', encoding='utf-8') as handle:
            json.dump({'posts': [dict(post, id=1), dict(post, id=2, url='v')]}, handle)
        with open(os.path.join(folder, notes.FILE), 'w', encoding='utf-8') as handle:
            json.dump({'notes': [{'id': 'hotfix-2026-11-08', 'kind': 'hotfix', 'day': '2026-11-08', 'sections': []}]}, handle)
        by_day = notes.days(folder)
        self.assertEqual(len(by_day['2026-11-13']['blizzard']['sections'][0]['lines']), 2)
        self.assertEqual(by_day['2026-11-13']['blizzard']['urls'], ['u', 'v'])
        self.assertEqual(by_day['2026-11-08']['foreverchanges'], 'hotfix-2026-11-08')


class IcyVeins(unittest.TestCase):
    QUOTED = ('<p>Blizzard posted hotfixes.</p><div class="blizzard-blue-post"><div class="d-flex"><a class="source-link" href="x">Source</a></div>'
              '<hr class="blizzard-line" /><h3></h3><div class="blizzard-blue-post-content">'
              '<p><strong>Classes</strong></p><ul>\n<li><strong>Druid</strong>\n<ul>\n<li>Wild Growth heals more.</li>\n</ul>\n</li>\n</ul>\n    </div>\n</div>'
              '<h2>What we think</h2><ul><li>An opinion of the site, not a note.</li></ul>')

    def test_the_day_a_title_names(self):
        self.assertEqual(notes._title_day('Class Changes: WoW Forever Hotfixes, November 13th', '2026-11-14T01:58:00'), '2026-11-13')
        self.assertEqual(notes._title_day('First Class Tuning Pass Coming to WoW Forever - November 10th', '2026-11-06T21:16:00'), '2026-11-06')
        self.assertEqual(notes._title_day('Dungeon Kill XP Is Back!', '2026-11-08T20:00:00'), '2026-11-08')

    def test_the_quoted_notes_of_the_hotfix_articles_only(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        articles = [
            {'id': 2, 'date_gmt': '2026-11-14T01:58:21', 'slug': 'hotfixes-november-13th', 'title': {'rendered': 'Class Changes: WoW Forever Hotfixes, November 13th'},
             'content': {'rendered': self.QUOTED}},
            {'id': 1, 'date_gmt': '2026-11-05T13:03:00', 'slug': 'launch', 'title': {'rendered': 'WoW Forever Launch Avoids the Usual Queue'}, 'content': {'rendered': '<p>Fun.</p>'}},
            {'id': 3, 'date_gmt': '2026-11-02T20:00:00', 'slug': 'dev-notes', 'title': {'rendered': 'Massive WoW Forever Development Notes'}, 'content': {'rendered': self.QUOTED}},
            {'id': 4, 'date_gmt': '2026-09-28T20:00:00', 'slug': 'weekly', 'title': {'rendered': 'Forever Class Changes, Midnight Patch Notes: WoW Weekly'}, 'content': {'rendered': self.QUOTED}}]

        def get(url):
            if '/categories?' in url:
                return [{'id': 2910, 'slug': 'wow-forever'}]
            self.assertIn('categories=2910', url)
            return articles if 'page=1&' in url else []
        result = notes.fetch_icyveins(folder, get=get, pause=0, log=lambda *_: None)
        self.assertEqual((result['code'], result['notes']), (0, 2))     # no round-up of the week
        stored = [n for n in notes.icyveins_notes(folder) if n['kind'] == 'hotfix']
        self.assertEqual([(n['id'], n['day'], n['url']) for n in stored], [(2, '2026-11-13', f'{notes.ICYVEINS_NEWS}/hotfixes-november-13th/')])
        self.assertEqual([n['id'] for n in notes.icyveins_notes(folder) if n['kind'] == 'build'], [3])   # a build's notes
        self.assertNotIn('2026-11-02', notes.days(folder))
        self.assertEqual(stored[0]['days'], [{'day': '2026-11-13', 'sections': [{'name': 'Classes', 'lines': [{'text': 'Druid: Wild Growth heals more.', 'mark': ''}]}]}])
        self.assertEqual(notes.days(folder)['2026-11-13']['icyveins'], [2])
        self.assertEqual(notes.fetch_icyveins(folder, get=get, pause=0, log=lambda *_: None)['code'], 3)


if __name__ == '__main__':
    unittest.main()
