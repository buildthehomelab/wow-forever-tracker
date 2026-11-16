# Wowhead pages

Wowhead's tooltips tell the analysis **what** WoW Forever has. Its pages hold what the tooltips do not: which
creatures and chests drop an item and how often players saw it, who sells it, who starts and ends a quest. That is
server data no client file carries, and Wowhead is the most complete public copy of it.

A script cannot read those pages: Wowhead answers 403, and a headless browser gets the same before any page loads
(it says it is one). A real browser can, slowly. So the pages are read in your own browser tab, kept as facts only,
and the import reads that copy. **The tracker itself never asks Wowhead for a page**, and nothing here disguises a
crawler as something else.

| Piece | What it does |
|---|---|
| The Forge › Imports › *Wowhead pages* | *Download the crawler* (crawler.js with the pages this tracker wants next queued), *Download the full crawl* (the same, then the whole database: [below](#the-whole-database)), *Send wowhead-pages.jsonl* (into the cache, then an import card), *Import Wowhead pages* (a card from the cache as it is) |
| `tools/wowhead-pages/crawler.js` | runs in a browser tab on wowhead.com: learns how fast it may go, keeps what it read in the tab's storage, saves it as a file |
| `data/wowhead-pages/<shelf>.jsonl` | the pages read so far, one line a page, sorted by id: `item.jsonl` holds Forever's item pages, `classic-npc.jsonl` Classic's npc pages, `forever-list.jsonl` the list pages (one line a list query). Outside the repository: a copy of Wowhead's data is kept for your server, not republished with the code |
| `app/wowheadpages.php` | the queue, the merge, and the cache as an import card (also `php tools/source-import.php wowhead`) |
| `tools/wowhead_pages.py` | the same queue and merge from the command line (`todo`, `merge`, `stats`) |

## What is kept of a page

Every number, and nothing else. A page costs seconds of a slow crawl and its numbers a few kilobytes of disk, so all of
them are kept, also the ones no import reads yet (per-season and per-mode counts, an item's stats): a later import
reads the cache, it does not ask Wowhead again. Of each tab (*Dropped by*, *Sold by*, *Contained in*, ...) the rows
with all their numbers (up to 20,000 rows a tab); the Quick
Facts lines (`Level: 13`, `Start: [url=/forever/npc=253812]`) with the text of their links removed; the map pins.
Names, descriptions, quest text, comments, screenshots and guides are never kept: the crawler drops every text value
before it stores a row, `tools/wowhead_pages.py merge` refuses a row that still holds one, and a test checks both.
A page Wowhead does not have is kept as `"status": "missing"`, so that it is not asked again.

## Reading pages

1. The Forge › Imports › **Download the crawler**. The file holds the crawler and its queue: first the items other
   content waits for (a quest's objective, a recipe, a mount, a toy, a spell taught by an item), then the other gap
   items from id 190000 up (`[wowhead] crawl_min_item`; below it are the original game's, nearly all test items),
   then the quests without a giver or an ender. Pages the cache has are left out until they are due again
   (`[wowhead] refresh_days`).
2. Open `https://www.wowhead.com/forever` in a browser tab, open its developer console (F12), paste the file and
   press Enter. Leave the tab open.
3. `await WHC.status()` says how far it is, the pace it found and the hours left; `WHC.log()` lists its last pace
   changes, blocks and network errors. Closing or reloading the tab loses nothing: paste the file again and it goes
   on where it stopped (pages already read are not queued twice).
4. `await WHC.save()` downloads `wowhead-pages.jsonl`, at any time, also while it runs. `await WHC.saveNew()` downloads
   only the pages read since the last `saveNew()`: a long crawl sent in parts.
5. **Send wowhead-pages.jsonl** on the Imports page: the pages go into the cache (the newer answer of a page wins)
   and an import card is made from the whole cache. Download the crawler again later for the pages still wanted.

Without the website: `python tools/wowhead_pages.py todo <the To add list as CSV>` prints the queue as
`WHC.add(...)` lines and `python tools/wowhead_pages.py merge wowhead-pages.jsonl` fills the same cache.

## The whole database

*Download the full crawl* (or `await WHC.full()` in the tab) reads everything Wowhead holds that a server needs and
no client file carries, for WoW Forever and for WoW Classic:

1. **The lists.** `/forever/npcs`, `/objects`, `/quests`, `/items`, then the same of `/classic`. A list page shows at
   most 1,000 rows and says how many it found; filtered by an id range (`npcs?filter=37:37;2:4;1:20000`, ID ≥ 1 and
   ≤ 20000) it is whole when it found no more than it shows. A cut list is split into ranges of about 800 found ids and
   those are read first, until every list is whole: a few hundred pages name every id of both branches. Of a row every
   number is kept (level, quality, zones, `source` codes, an item's stats), never its name.
   The lists go ahead of whatever was queued.
2. **The pages they name**, after whatever was queued: every npc (drops with counts, sold items, quests it starts and
   ends, where it stands), every object (contents, quests), every quest, and of the items only those whose page says
   more than the npc, object and quest pages do (a `source` other than crafted, drop, quest and vendor: fishing,
   gathering, containers ...).
3. **Classic only where it helps Forever.** Of Classic, only the pages of ids Forever has too (Season of Discovery's
   ids Forever reused among them), and of those only when Forever's own page has no loot counts from at least 50
   looted corpses or opened chests: Classic's players saw the same creature drop far more often. A Classic page is
   kept on its own shelf, never mixed with Forever's.

Forever alone is about 15,600 npcs and 5,100 objects (Wowhead's counts, November 2026), so at one page every 10 to 20
seconds the whole database is days of crawling. The queue and what was read live in the tab's IndexedDB (a whole
crawl is more than localStorage holds); `WHC.status()` gives what is queued and read by kind. The tab must stay open
and, ideally, visible: a hidden tab's timers are slowed.

**What the import reads of it**: Forever's item, quest, npc and object pages (below), and Classic's npc and object
pages as a card of their own ([Classic's pages](#classics-pages)). The lists are kept in the cache for the imports
that will read them.

## Classic's pages

*Import Classic pages* (The Forge › Imports, or `php tools/source-import.php wowheadclassic`) makes a card of its own,
source *Wowhead Classic*, from the Classic pages the full crawl read. Classic's players looted the same creatures and
chests far more often than Forever's have so far, so their counts fill in where Forever's are too few:

- **Drops only**: an npc page's *Drops*, an object page's *Contains*, *Mining*, *Herbalism*, with the same counts as
  Forever's (at least 10 loots, seen at least twice). Vendors and quest givers are not taken: Forever moved them.
- **Only where Forever has no counted chance** for that creature or chest and item; where it has one, Forever's is
  taken and the Classic one is counted on the card.
- **Forever's item pages decide a world drop**, as they do for Forever's own npc pages: a creature's drop of a gap
  item waits for the item's Forever page.
- **Trust**: after every source recorded on Forever, before the original game's database. A Classic chance never
  changes a row Wowhead (Forever) or a live recording brought; it may measure again the rows it brought itself, and
  the original game's database's.

Each row's `Comment` is `Wowhead Classic <date>`.

## The pace

Wowhead does not publish its limit. Asking too much gets the address refused for about eight minutes (HTTP 405).
Measured blocks came at 4 pages a minute after nine minutes, and at 2.3 a minute after fourteen; heavy pages (a list
of 1,000 items is a megabyte) seem to count more. So the crawler learns the pace:

- It starts at one page every 30 seconds, give or take 15 %, and goes 8 % faster after each 15 clean pages, never
  faster than one every 8 seconds.
- A block makes it wait (8.5 minutes, twice that when the next answer is a block again, 34 at most) and go 1.6 times
  slower. It remembers the pace the block came at and stays 20 % slower than that. After 60 clean pages at that
  margin the memory fades by 5 %, so a limit that was only a busy hour is found again.
- A network error, a page that does not come within a minute, or a server error (5xx) is no block: the same page is
  asked again after 15 seconds, doubling to 10 minutes; the pace eases every third error in a row. It never stops
  by itself. Going back online cuts the wait short. A page it does not understand three times is kept as `odd`.
- `WHC.pace(seconds)` sets the pace by hand and it learns on from there; `WHC.pace(seconds, true)` also forgets the
  remembered block pace. The learned pace is kept in the tab between runs.

Every `fetch` of the crawler's tab to Wowhead itself waits in the same line as the crawler's pages (`pageRequests`
in `WHC.status()` counts them); requests of the page to other hosts pass untouched. Other tabs on Wowhead from the
same address share the limit: do not run two crawls at once, and do not browse Wowhead while one runs.

## The import

*Import Wowhead pages* makes an import card like every other source's ([SOURCES.md](SOURCES.md)): only the last
analysis' gaps, previewed, applied on your test realm, rolled back from the history, exported to your data
repository. From the pages it takes:

| Rows | From | When |
|---|---|---|
| `creature_loot_template` | an item page's *Dropped by* tab, an npc page's *Drops* | the item is a gap; players looted that creature at least 10 times and saw the item at least twice (the chance is drops over loots). Where both pages count the same drop, the one that counted more loots wins. An item 15 or more creatures drop, by its own page or by the npc pages read, is a world drop and is left out. A new row from an npc page alone waits for the item's own page (until every npc page is read, only it tells a world drop from a creature's own loot); a row an import brought is measured again without it |
| `gameobject_loot_template` | *Contained in (object)*, *Mined from*, *Gathered from*; an object page's *Contains*, *Mining*, *Herbalism* | the same counts (a chest's page gives its openings once, as the tab's total); the object is a chest on the server |
| `npc_vendor` | *Sold by*, an npc page's *Sells* | the price is money only (on an npc page: the first way to pay). Stock paid with a currency or with items is left out, unless another vendor of the server already sells the item for that cost |
| `creature_queststarter`, `gameobject_queststarter`, `..._questender` | a quest page's Quick Facts *Start* and *End*; an npc or object page's *Starts* and *Ends* | the quest has no giver (or no ender); the creature or object is on the server. By id, not by name |

The npc and object pages are read a line at a time (a whole crawl is tens of thousands of pages), and of their drops
and stock only the items worth a row are kept: the gaps, and the items of drop rows an import brought, which are
measured again (the cache itself keeps every row).

Not written, and counted on the card: an npc's skinning and pick pocketing loot (tables of their own); items Wowhead only knows as a quest reward, a craft, the content of another
item, or from skinning, pick pocketing and fishing; drops without counts.

**Rows the server already has** are measured again, as for the other sources: where a drop an import brought has
another chance on Wowhead now, the card proposes it (*Creature drop chances that moved*). Wowhead is the most trusted
source after the game client itself, so it may correct any import's row; it never changes a row no import brought.

Each loot row's `Comment` is `Wowhead <date of the newest page>`, which is how a later import knows whose row it is.

## Tests

- `node tools/tests/test_wowhead_crawl.mjs`: what the crawler keeps of a page, on a made-up page.
- `node tools/tests/test_wowhead_crawl.mjs` also covers the pace (speeding up, blocks, the fading memory, network
  errors) and the whole database: the three ways a list page is written, the splitting of a cut list, the pages a list
  names, when a Classic page is read, the queue keys.
- `python -m unittest tools/tests/test_wowhead_pages.py`: the cache and the to-do list.
- `php tools/tests/test_wowhead_pages.php`: the evidence and what is left out, the queue order, the merge and the crawler download.
