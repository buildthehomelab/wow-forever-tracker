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
| The Forge › Imports › *Wowhead pages* | *Download the crawler* (crawler.js with the pages this tracker wants next queued), *Send wowhead-pages.jsonl* (into the cache, then an import card), *Import Wowhead pages* (a card from the cache as it is) |
| `tools/wowhead-pages/crawler.js` | runs in a browser tab on wowhead.com: learns how fast it may go, keeps what it read in the tab's storage, saves it as a file |
| `data/wowhead-pages/<kind>.jsonl` | the pages read so far, one line a page, sorted by id. Outside the repository: a copy of Wowhead's data is kept for your server, not republished with the code |
| `app/wowheadpages.php` | the queue, the merge, and the cache as an import card (also `php tools/source-import.php wowhead`) |
| `tools/wowhead_pages.py` | the same queue and merge from the command line (`todo`, `merge`, `stats`) |

## What is kept of a page

Numbers only. Of each tab (*Dropped by*, *Sold by*, *Contained in*, ...) the rows with their ids and counts; the Quick
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
4. `await WHC.save()` downloads `wowhead-pages.jsonl`, at any time, also while it runs.
5. **Send wowhead-pages.jsonl** on the Imports page: the pages go into the cache (the newer answer of a page wins)
   and an import card is made from the whole cache. Download the crawler again later for the pages still wanted.

Without the website: `python tools/wowhead_pages.py todo <the To add list as CSV>` prints the queue as
`WHC.add(...)` lines and `python tools/wowhead_pages.py merge wowhead-pages.jsonl` fills the same cache.

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
| `creature_loot_template` | an item page's *Dropped by* tab | the item is a gap; players looted that creature at least 10 times and saw the item at least twice (the chance is drops over loots). An item 15 or more creatures drop is a world drop and is left out |
| `gameobject_loot_template` | *Contained in (object)*, *Mined from*, *Gathered from* | the same counts; the object is a chest on the server |
| `npc_vendor` | *Sold by* | the price is money only. Stock paid with a currency or with items is left out, unless another vendor of the server already sells the item for that cost |
| `creature_queststarter`, `gameobject_queststarter`, `..._questender` | a quest page's Quick Facts *Start* and *End* | the quest has no giver (or no ender); the creature or object is on the server. By id, not by name |

Not written, and counted on the card: items Wowhead only knows as a quest reward, a craft, the content of another
item, or from skinning, pick pocketing and fishing; drops without counts.

**Rows the server already has** are measured again, as for the other sources: where a drop an import brought has
another chance on Wowhead now, the card proposes it (*Creature drop chances that moved*). Wowhead is the most trusted
source after the game client itself, so it may correct any import's row; it never changes a row no import brought.

Each loot row's `Comment` is `Wowhead <date of the newest page>`, which is how a later import knows whose row it is.

## Tests

- `node tools/tests/test_wowhead_crawl.mjs`: what the crawler keeps of a page, on a made-up page.
- `node tools/tests/test_wowhead_crawl.mjs` also covers the pace: speeding up, blocks, the fading memory, network errors.
- `python -m unittest tools/tests/test_wowhead_pages.py`: the cache and the to-do list.
- `php tools/tests/test_wowhead_pages.php`: the evidence and what is left out, the queue order, the merge and the crawler download.
