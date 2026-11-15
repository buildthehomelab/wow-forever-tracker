# Wowhead pages

Wowhead's tooltips tell the analysis **what** WoW Forever has. Its pages hold what the tooltips do not: which
creatures and chests drop an item and how often players saw it, who sells it, who starts and ends a quest. That is
server data no client file carries, and Wowhead is the most complete public copy of it.

A script cannot read those pages: Wowhead answers 403. A browser can, slowly. So the pages are read from a browser
tab, kept in the repository as facts only, and the import reads that copy. **The tracker itself never asks Wowhead for
a page.**

| Piece | What it does |
|---|---|
| `tools/wowhead-pages/crawler.js` | runs in a browser tab on wowhead.com: reads one page every 20 seconds or so, keeps what it read in the tab's storage, saves it as a file |
| `tools/wowhead_pages.py` | lists the pages worth reading (`todo`), puts what the crawler saved into the cache (`merge`), says what the cache holds (`stats`) |
| `tools/wowhead-pages/cache/<kind>.jsonl` | the pages read so far, one line a page, sorted by id |
| `app/wowheadpages.php` | turns the cache into an import card: The Forge › Imports › *Import Wowhead pages*, or `php tools/source-import.php wowhead` |

## What is kept of a page

Numbers only. Of each tab (*Dropped by*, *Sold by*, *Contained in*, ...) the rows with their ids and counts; the Quick
Facts lines (`Level: 13`, `Start: [url=/forever/npc=253812]`) with the text of their links removed; the map pins.
Names, descriptions, quest text, comments, screenshots and guides are never kept: the crawler drops every text value
before it stores a row, `tools/wowhead_pages.py merge` refuses a row that still holds one, and a test checks both.
A page Wowhead does not have is kept as `"status": "missing"`, so that it is not asked again.

## Reading pages

1. In The Forge › *To add*, press **Export CSV**. Then:

   ```
   python tools/wowhead_pages.py todo forever-tracker-todo.csv > todo.js
   ```

   It prints the pages that can close a gap and are not in the cache yet, as `await WHC.add('item', [...]);` lines:
   first the items other content waits for (a quest's objective, a recipe, a mount, a toy, a spell taught by an item),
   then the other items without a source, then the quests without a giver or an ender. Items of the original game
   that only lack a source are left out unless you pass `--min-item 0`: nearly all of them are test items and unused
   tomes that have no source on Wowhead either. `--limit 500` keeps a run short; `--max-age 30` reads a cached page
   again once it is that many days old.
2. Open `https://www.wowhead.com/forever` in a browser, open the developer console, and paste
   `tools/wowhead-pages/crawler.js`, then the lines of `todo.js`, then `WHC.start()`.
3. `await WHC.status()` says how far it is. Leave the tab open. Closing or reloading it loses nothing: paste the
   crawler again and it goes on by itself where it stopped.
4. `await WHC.save()` downloads `wowhead-pages.jsonl`. It can be pressed at any time, also while the crawl runs.
5. `python tools/wowhead_pages.py merge wowhead-pages.jsonl` puts the pages into the cache. Commit the cache: the
   next build of the tracker reads it.

Pages read since the last build can also be dropped into `data/wowhead-pages/<kind>.jsonl` (the same format): the
import reads both folders and takes the newer answer of each page.

## The pace

Wowhead blocks an address that asks too fast: every page then answers 405 for about eight minutes. The limit looks
like about 35 pages in ten minutes: crawls at 4 pages a minute were blocked after nine minutes whatever the spacing
between two pages, and one at 2.4 a minute was not. That is a reading of a handful of blocks, not a published limit,
and a block costs eight minutes, so the crawler errs on the slow side: one page every 20 to 23 seconds
(`WHC.pace(seconds)` changes the 20), a little under 3 pages a minute. 1,000 pages take six hours. When a block comes
anyway it waits eight and a half minutes, twice as long when the next answer is a block again (34 minutes at most),
and goes on with the same page. Ten requests in a row without any answer stop it.

Every `fetch` of the crawler's tab to Wowhead itself waits in the same line as the crawler's pages (`pageRequests`
in `WHC.status()` counts them). Requests of the page to other hosts pass untouched. Other tabs on Wowhead from the
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
- `python -m unittest tools/tests/test_wowhead_pages.py`: the cache and the to-do list.
- `php tools/tests/test_wowhead_pages.php`: the evidence, and what is left out.
