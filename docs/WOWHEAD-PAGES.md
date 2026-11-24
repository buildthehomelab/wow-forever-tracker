# Wowhead pages

Wowhead's tooltips tell the analysis **what** WoW Forever has. Its pages hold what the tooltips do not: which
creatures and chests drop an item and how often players saw it, who sells it, who starts and ends a quest. That is
server data no client file carries, and Wowhead is the most complete public copy of it.

A script cannot read those pages: Wowhead answers 403, and a headless browser gets the same before any page loads
(it says it is one). A real browser can, slowly. So the pages are read in your own browser tab; the import reads the
facts kept in the cache files, and the whole page goes to the tracker's [answers table](#the-wowhead-rows). **The tracker itself never asks Wowhead for a page**, and nothing here disguises a
crawler as something else.

| Piece | What it does |
|---|---|
| The Forge › Imports › *Wowhead pages* | *Download the crawler* (crawler.js with the pages this tracker wants next queued), *Download the full crawl* (the same, then the whole database: [below](#the-whole-database)), *Send wowhead-pages.jsonl* (into the cache, then an import card), *Import Wowhead pages* (a card from the cache as it is) |
| `tools/wowhead-pages/crawler.js` | runs in a browser tab on wowhead.com: learns how fast it may go, keeps what it read in the tab's storage, saves it as a file |
| `data/wowhead-pages/<shelf>.jsonl` | the pages read so far, one line a page, sorted by id: `item.jsonl` holds Forever's item pages, `classic-npc.jsonl` Classic's npc pages, `forever-list.jsonl` the list pages (one line a list query). Outside the repository: a copy of Wowhead's data is kept for your server, not republished with the code |
| `ft_source_answers` (tracker database) | every tooltip and page the tracker holds, the whole page too, with when it changed and when it is due again: [The Wowhead rows](#the-wowhead-rows) |
| `app/wowheadpages.php` | the queue, the merge, and the cache as an import card (also `php tools/source-import.php wowhead`) |
| `tools/wowhead_pages.py` | the same queue and merge from the command line (`todo`, `merge`, `stats`) |

## What is kept of a page

In the cache files, every number, and nothing else (the whole page is in the [answers table](#the-wowhead-rows)). A page costs seconds of a slow crawl and its numbers a few kilobytes of disk, so all of
them are kept, also the ones no import reads yet (per-season and per-mode counts, an item's stats): a later import
reads the cache, it does not ask Wowhead again. Of each tab (*Dropped by*, *Sold by*, *Contained in*, ...) the rows
with all their numbers (up to 20,000 rows a tab); the Quick
Facts lines (`Level: 13`, `Start: [url=/forever/npc=253812]`) with the text of their links removed; the map pins.
Names, descriptions and quest text are not in the cache files: the crawler keeps the facts with every text value
dropped, `tools/wowhead_pages.py merge` refuses a row that still holds one, and a test checks both. Since record
version 3 a crawler line also carries `full`, the whole page, which goes to the answers table only (its `text` holds a
quest's Description, Progress and Completion words: the Wowhead import fills a quest's missing turn-in text from it).
Since record version 5 `full.comments` keeps players' comments whole, `[{id, date, rating, body, replies?}]` (up to 200
a page, 8000 characters each; who wrote them is left out): what players report and Wowhead never fixed is often the
detail the page itself lacks. Comments stay in the answers table only, never in the cache files. Screenshots and videos
are never kept.
A page Wowhead does not have is kept as `"status": "missing"`, so that it is not asked again.
A creature's or object's page also keeps the model display ids its model viewer shows (`"model": [140708]`, record
version 2): a creature the server has no template for needs one.

## Reading pages

1. The Forge › Imports › **Download the crawler**. The file holds the crawler and its queue, each page with what it
   is worth ([What is read first](#what-is-read-first)): the quests without a giver or an ender and the items other
   content waits for (a quest's objective, a recipe, a mount, a toy, a spell taught by an item), then the server's
   creatures and objects whose data is missing, then the other gap items from id 190000 up (`[wowhead]
   crawl_min_item`; below it are the original game's, nearly all test items). Pages the cache has are left out until
   they are due again (`[wowhead] refresh_days`).
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

## The Chrome extension

A crawl that starts and goes on by itself, on a computer that stays on: `tools/wowhead-pages/extension/`.

1. The Forge › **Crawl** › *Download the Chrome extension*. The zip carries this tracker's address (the one the
   download was asked at) and a key of its own in `config.json`; the key is made the first time and kept in
   `data/wowhead-extension.key`, so the tracker needs no setting.
2. Unzip it where it can stay, then in Chrome: `chrome://extensions` › Developer mode › *Load unpacked* › the
   `wowhead-crawl` folder.
3. Stop any other crawl on the same address first (`WHC.stop()` in its tab, then close it): Wowhead counts them all.

The extension keeps one pinned Wowhead tab (Memory Saver may not put it to sleep). After every load of it, it asks the
tracker for the crawler with its queue (`GET api/wowhead-crawler`, the full crawl, as *Open Wowhead* hands it out)
and loads it into the page; the crawler goes on where it was (its queue and pace are in the tab's IndexedDB). Every 5
minutes it checks that the tab is there and has its crawler: a closed tab, a crash or a restart of Chrome is mended
then. A crawler loaded more than an hour ago is replaced: once the tracker has answered with a new one, the tab is
reloaded and takes it, so a crawl that runs for days follows the tracker's latest queue and crawler (an extension
before 1.1.0 kept the first crawler until the tab happened to reload). The crawler passes what it read to the extension's script in the same tab (`window.postMessage`, as a linked
crawl does to its opener), which sends it to `api/wowhead-push` with the key; the crawler forgets a batch only once the
tracker kept it. The icon's popup shows the queue, the pace, the last page and what was sent, and pauses the crawl;
a `!` on the icon means the tracker did not answer or refused.

Loaded from the repository instead of a download: copy `config.example.json` to `config.json` and fill it in (the
tracker's address, and its `[wowhead] push_token` or the key in `data/wowhead-extension.key`).

## A linked crawl

The Forge › **Crawl** keeps every page in the tracker as the crawl reads it: nothing to save and send by hand.

1. *Open Wowhead*: a tab opens on wowhead.com/forever with the crawler and its queue (the full crawl, your gaps first).
2. In that tab's console (F12), run `(0, eval)(JSON.parse(window.name).src)` once.
3. Keep both tabs open. Every 15 seconds the crawl sends what it read since (40 pages at most) to the Crawl tab,
   which keeps it (`wowhead_push`: added at the end of the cache's files, nothing rewritten) and answers; only then
   does the crawl forget it. The import cards (Wowhead, and Wowhead Classic once it has pages) are made again every
   `[wowhead] card_minutes` (30), or by *Make the cards now*. Applying one stays your click.

Why two tabs: Wowhead's page may not call this tracker (its policy turns every `http://` request into `https://`), but a
tab may pass messages to the tab that opened it. What the crawl reads while the Crawl tab is closed waits in the Wowhead
tab's storage (`outbox`) and is sent once a Crawl tab opened it again. The first link sends everything read before too.
`WHC.status().link` says how much is waiting.

**A normal browser only.** The page opens the Wowhead tab itself, from your click; that is how the two tabs know each
other. A browser that opens no window a page asks for (the Claude app's own browser pane does not, even after a click)
cannot link: there, read in a tab as before and send `WHC.saveNew()` files on the Imports page. On a computer left
running, a normal browser with the Crawl page open crawls and keeps by itself.

## Batches from a computer

Where the browser cannot link a crawl (the Claude app's browser pane), a script on the computer takes the pages to the
tracker instead:

1. Give the tracker a push key: `[wowhead] push_token` (16 characters or more; `FT_WOWHEAD_PUSH_TOKEN` in Docker).
   Without one the endpoint `api/wowhead-push` answers 403 to everyone.
2. In the crawl tab: `WHC.autoSave(15)`. Every 15 minutes what was read since is downloaded as
   `whc-batch-<time>-<n>.jsonl` (300 pages a file at most; the first time, everything read before too). It goes on after
   a reload; `WHC.autoSave(0)` stops it.
3. On the same computer: `WHC_TRACKER=http://<tracker> WHC_PUSH_TOKEN=<key> sh tools/wowhead-pages/push.sh ~/Downloads
   --watch 300` sends each file, and moves it to `~/Downloads/whc-sent/` once the tracker kept it. A file the tracker
   did not answer for stays and is sent at the next turn. The tracker answers as soon as the pages are kept, then makes
   the cards again when they are due.

## What is read first

Pages asked for by hand come before everything: `data/wowhead-wanted.json` (`{"npc": [247195, ...]}`; kinds npc,
object, item, quest), set with the admin call `POST api/imports {"action": "wowhead_wanted", "kind": "npc", "ids":
[...], "replace": false}`. That is for content no gap names yet, such as the creatures of a dungeon being built; the
next crawler load (the extension loads it after every page) reads them first (tier `wanted`, ahead of a whole crawl's list pages too), and a page read and not
due again leaves the list by itself. `{"action": "wowhead_pages_get", "kind": "npc", "ids": [...]}` returns the kept
pages of those ids.

A whole crawl is days of pages, so the queue is always in the order of what a page is worth to the server, most first
(the crawler's `TIERS`; `WHC.status()` counts the queue by tier):

| Tier | Pages | Why |
|---|---|---|
| 0 | the list pages | they name every other page, and are few |
| 1 `gap` | the items a quest, recipe, mount, toy or spell waits for; the quests without a giver or an ender; the official quests the server has no record of, the creatures and objects they name that the server lacks, and the items they ask for ([GATHER.md](GATHER.md)); the creatures and objects whose comments may name a quest's missing giver or ender, read right after the quests (`wowhead_comments_queue`: what comments on the quest's own page link to, and in its series the ender of the step before or the giver of the step after; pages held from before record v4 are read again) | each unblocks something players cannot do |
| 2 `named` | the creatures, vendors and chests a tier-1 page names (not a world drop's fifteen and more), who gives or takes such a quest | their own pages count better, and a new drop row from an npc page waits for the item's page |
| 3 `gapOther` | the items that only lack a source | each is an item players cannot get yet |
| 4 `namedOther` | what a tier-3 page names | |
| 4.5 `later` | what a release phase not open yet needs: its quests, the creatures and objects they name, its items ([GATHER.md](GATHER.md)) | read before the phase opens |
| 5 `missing` | the server's creatures and objects whose data is missing: vendors that sell nothing, trainers that teach nothing, chests that hold nothing, creatures without loot (the ones with no service first) | fills holes in what is already in the world |
| 6 | the rest of Forever | measures again what the server already has |
| 8 | Classic | only where Forever's counts are thin |

The Classic item page of a Season of Discovery item Forever kept goes in the tier of its Forever page, right after
it ([below](#season-of-discovery-items)).

*Download the crawler* hands each page its tier from the last analysis and the world database
(`wowhead_pages_queue`: the tracker's gaps, and `wowhead_pages_missing_data` for tier 5, only the ids Wowhead's Forever
lists name once they were read). In a crawl that already queued a page it moves up, never down; a page read is not
asked again. A crawl kept before 2026-11-16 (when tier 3 was the missing data) is put in this order once, the next
time its crawler loads. The tiers 2 and 4 are made by the crawler itself, as it reads the pages that name them.
`WHC.prioritize(['npc:7', 'object:2'], 'missing')` moves pages by hand.

**Pages come due again.** The tracker queues only pages it does not hold, or holds and wants again (older than
`[wowhead] refresh_days`, or a "no such page" older than `recheck_days`). A tab keeps every page it read, and
`prioritize` leaves out a page it holds, so each queued page carries `{again: 86400}`: a page the tab read more than a
day ago is read again (a younger copy is one still on its way to the tracker). Before 2026-11-20 the queue had no
`again` (only the Craftsman's Writs did), so a tab that crawled for weeks, as the Chrome extension's does, never read a
page twice and nothing the tracker held came due again in it.

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

## Players' comments

Comments on a Wowhead page often answer what the page itself does not: "turn it in to Rayan Dawnrisen", "starts at
...", "dropped by ...". Since record version 4 the crawler keeps what a page's comments **link to**, never their words:
each comment that links a creature, object, item or quest becomes `[rating, [[role, kind, id], ...]]`, where `kind` is 1
npc, 2 object, 3 item, 4 quest, and `role` is what the words just before (or right after) the link say it is: 1 starts
or gives it, 2 takes it (turned in), 3 drops it, 4 sells it, 0 only named. At most 50 comments a page, 20 links each.

*Import comments* (The Forge › Imports, or `php tools/source-import.php wowheadcomments`) makes a card of its own,
source *Wowhead comments*, also made with the other Wowhead cards after a crawl:

- **Quests without a giver or an ender**: the creature or object a quest page's comment says starts it or takes it,
  and the quests a creature's or object's page comment says it starts or takes.
- **Gap items**: the creature an item page's comment says sells it (for money), and the creatures or chests it says drop
  it, at the server's best chance of that item, or `[questie] quest_chance` for an item a quest asks for (quest only).
  A drop with neither is left on the card.
- **Voted down** (rating below 0): not taken, counted on the card.
- **Trust**: after every source but the original game's database: only what nothing else gives.

- **Names in the words** (record v5, `full.comments` in the answers table): a giver or ender a comment on the quest's
  own page names without linking it ("turn it in to Griniblix the Spectator", "starts from Sully McCleary"), for the
  quests that lack one. The name after the cue is matched to the server's spawned creatures and objects; it is taken
  when exactly one has it (of several, the only one that gives or takes quests), its longest form first. A comment
  voted down is not read. The gap quests' pages read before v5 are read again for their words.

Each row's `Comment` is `Wowhead comments <date>`. A Forever item or quest page read before version 4 counts as unread in
the crawl queue, so the gaps' pages are read once more for their comments.

## Season of Discovery items

The Forever client still carries every item Season of Discovery added, and Forever brought some back (the Tarnished
Undermine Real, item 226404, and the trinkets, belts and idols it buys). Wowhead's Forever pages often show no source
for them yet; its Classic pages, which hold Season of Discovery's data, do (the Undermine Real: 133 creatures).

- **Which items**: the gap items from id 190000 up that the Classic Era client has too (`tools/baseline/classic-era.json`,
  as `tools/ft/baseline.py` tells a Season addition). Those Wowhead's Forever tooltip marks "May not be in WoW: Forever"
  are internal, so no gap, and are never asked.
- **The queue**: `classic/item:<id>` for each, in the tier of its Forever page (`gap` or `gapOther`), unless the
  Forever page was read and names a drop, a chest or a vendor, or the Classic page is in the cache already.
- **The import** (the *Wowhead Classic* card): the Classic page's *Dropped by* and *Contained in* rows, with the same
  counts as any page (at least 10 loots, seen twice). Forever's own count wins where it has one. An item with a
  *Currency for* tab (it pays for other items) is no world drop: each creature that drops it gets a row of its own, as
  Season of Discovery had it; any other item fifteen or more creatures drop stays out.
- **Vendors**: never from Classic. Forever cut the Season vendors' stock (Wowhead's Forever guide lists 37 of the 194 items
  Classic's page says the Undermine Real buys), so only Forever's own npc pages give it, and stock paid with an item or a currency needs an extended
  cost the client knows. Neither the client nor its hotfixes (build 70938) hold one paid in the Undermine Real yet.

## Craftsman's Writs

A Craftsman's Writ is a tradable item that starts a crafting quest (the client's ItemSparse.StartQuestID). Wowhead's
Forever guide ([Craftsman's Writs](https://www.wowhead.com/forever/guide/professions/craftsmans-writs-overview-recipes-rewards))
calls them world drops that suit the zone and level, and sorts them in three tiers; as of November 2026 their item
pages show who starts the quest and what it asks for, but no *Dropped by* or *Contained in* tab, and no public loot
recording holds one. So the tracker keeps looking:

- **What a writ is**: the analysis records every item that starts a quest and whose English name is a Craftsman's
  Writ (`ft_meta.writ_items`, item => quest; 150 in Forever, 24 Argent Dawn ones of the original game), and the tier
  the client writes under a writ's name (ItemSparse.ItemNameDescriptionID: `ft_meta.writ_tiers`, 1 Journeyman,
  2 Expert, 3 Artisan). The client's tier comes first; the guide's is a second witness, shown where it differs.
- **The queue**: each writ's item page, and the guide, in tier `gap`, read again every `[wowhead] writ_days` (3).
  A crawl never reads a page twice by itself; for these the crawler is told to read a page again when its own copy
  is older than that (`WHC.prioritize(keys, 'gap', {again: seconds})`).
- **The guide**: of a guide page (`guide:<path>` in the queue, kept on the `forever-guide` shelf) only the items its
  tables link to are kept, each with the tier word of its row as a number (Journeyman 1, Expert 2, Artisan 3). The
  guide's zone list is where a writ is **handed in**, not where it drops, so it is not kept; its text never is.
- **The Forge › Writs** (`admin/writs`, linked from The Forge › Crawl) lists each writ with its tier, its quest and the sources its page names
  (creatures with their counts, chests, containers, vendors, the zones of its map pins). `?format=json` gives the same
  for a world-data file that turns real drops into `creature_loot_template` rows. A writ whose page names nothing has
  nothing there: nothing is guessed.

The import card leaves writs out like any item 15 or more creatures drop (a world drop); the Writs page is where such
a list shows.

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
| `skinning_loot_template`, `pickpocketing_loot_template` | *Skinned from*, *Pick pocketed from*; an npc page's *Skinning*, *Pickpocketing* | the same counts; the creature is on the server (a creature without a table of that kind gets one under its entry, and applying the card points its template to it) |
| `item_loot_template` | *Contained in (item)* | the same counts; the server already opens the container (it has rows of its own there: whether an item opens at all is the client's word) |
| `fishing_loot_template` | an item page's *Fished in* tab (a row a zone, its count of the zone's catches); a zone page's *Fishing* (its total the zone's catches) | the same counts, under the zone. A zone the server has no fishing table for (Mount Hyjal, the Riverglades) takes its page's whole table, a catch seen once included, as one group (a cast catches one thing), its chances scaled down to 100 when players' counts add up past it; a zone it has takes the gap items only, each a roll of its own (group 0), so the zone's group stays as it was. The crawl reads the page of every zone of the analysis with no table, and of every zone a gap item is fished in, in the administrator's tier |
| `npc_vendor` | *Sold by*, an npc page's *Sells* | money only (on an npc page: the first way to pay), or paid with currencies or items when one of the server's own ItemExtendedCost rows asks exactly that and nothing else (`tracker.py costs` reads them from `[server] dbc`; the lowest ID of a kind). A cost no row asks is left out and counted |
| `quest_template` reward slots | an item page's *Reward from* tab: each quest row names the item among its fixed rewards or its choices, with the count | the quest is on the server, its phase is open, it does not give the item yet; the item goes into the first empty slot of that kind (RewardItem1-4 with RewardAmount, RewardChoiceItemID1-6 with RewardChoiceItemQuantity) as a fill: a slot that holds an item is never replaced, and none free is counted |
| `creature_queststarter`, `gameobject_queststarter`, `..._questender` | a quest page's Quick Facts *Start* and *End*; an npc or object page's *Starts* and *Ends* | the quest has no giver (or no ender); the creature or object is on the server. By id, not by name |

The npc and object pages are read a line at a time (a whole crawl is tens of thousands of pages), and of their drops
and stock only the items worth a row are kept: the gaps, and the items of drop rows an import brought, which are
measured again (the cache itself keeps every row).

Not written, and counted on the card: items Wowhead only knows as crafted (the recipe is the gap), from disenchanting,
prospecting, milling or salvaging; quest rewards whose row says neither fixed nor
choice; drops without counts.

**Rows the server already has** are measured again, as for the other sources: where a drop an import brought has
another chance on Wowhead now, the card proposes it (*Creature drop chances that moved*). Wowhead is the most trusted
source after the game client itself, so it may correct any import's row; it never changes a row no import brought.
Only a corpse's and a chest's loot is measured again (every source): skinning, pick pocketing and container tables
are mostly a guaranteed item or a group rolled once, which a rate per item would empty, so they only get new rows.

Each loot row's `Comment` is `Wowhead <date of the newest page>`, which is how a later import knows whose row it is.

## The Wowhead rows

Every Wowhead answer the tracker holds is also a row of the tracker's answers table, `ft_source_answers`, with
`source = 'wowhead'` ([SOURCES.md, The answers table](SOURCES.md#the-answers-table): the columns, how rows come, the
other sources), so that it can be read with SQL (The Forge › Query, database *tracker*) and so that what changed on
Wowhead is a question SQL answers. The files stay what the analysis and the imports read; the table follows them.

| Column | Of a Wowhead answer |
|---|---|
| `feed` | `tooltip` (Wowhead's tooltip service, `data/wowhead/<kind>/<id>.json`) or `page` (the crawler) |
| `branch`, `kind`, `ref`, `id` | `forever` or `classic`; `npc`, `object`, `item`, `quest`, `spell`, ... or `list` / `guide`; the id as text, or a list's or guide's query; the id as a number (NULL for a list or guide) |
| `name` | the page's or the tooltip's name; a page without one of its own takes its tooltip's |
| `status` | `found`, or `missing` when Wowhead has no such page |
| `data` | the answer as the files keep it: the whole tooltip answer; a page's facts (numbers only) |
| `whole`, `whole_at` | the whole page as the crawler read it (record version 3 on), and when: `name`, `info` (g_pageInfo), `title`, `description`, `text` (a quest's description and completion, an item's notes), `quick` (Quick Facts with their links' text), `tabs` (every row whole, names and all), `map`, `links` (what the page's links name: `{type: {id: {name_enus, quality, ...}}}`). NULL for pages read by an older crawler; a later answer without it keeps the one held |
| `version` | the crawler's record version |
| `due_at` | when it is to be read again, by the rules every Wowhead answer follows: `[wowhead] refresh_days` (30) give or take a quarter by id, `recheck_days` (7) for `missing`, at once after *ask every source again*; NULL when `refresh_days` is 0 |

A creature's or object's tooltip text is left out of the hash (older answers were kept without it).

    -- what Wowhead changed this week
    SELECT kind, id, name, changed_at FROM ft_source_answers WHERE source = 'wowhead' AND changed_at > first_seen AND changed_at >= NOW() - INTERVAL 7 DAY;
    -- a creature's map pins and models
    SELECT JSON_EXTRACT(data, '$.map'), JSON_EXTRACT(data, '$.model') FROM ft_source_answers WHERE source = 'wowhead' AND feed = 'page' AND kind = 'npc' AND id = 1365;
    -- who drops an item, with the creatures' names
    SELECT JSON_EXTRACT(whole, '$.tabs."dropped-by".rows') FROM ft_source_answers WHERE source = 'wowhead' AND feed = 'page' AND kind = 'item' AND id = 216616;
    -- what is due again
    SELECT feed, kind, COUNT(*) FROM ft_source_answers WHERE source = 'wowhead' AND due_at <= NOW() GROUP BY feed, kind;

**How rows come.** A page lands the moment it reaches the tracker (a linked crawl, the extension's push, *Send
wowhead-pages.jsonl*); a tooltip the moment the website asks Wowhead, and the analysis' own tooltips at the end of
each analysis. What the files already held is written by `php tools/source-answers.php backfill` (at every start of
the container, and by the analysis): the tooltip files written since its last run and the page shelves that changed.

**What is due again.** Tooltips due again are asked by the analysis as before. Pages are never asked by the tracker:
Forever's npc, object, item and quest pages whose `due_at` passed go to the crawl's queue, oldest first, at most
`[wowhead] recheck_pages` (300) at a time, with the creatures and objects whose data is missing (tier `missing`); a
page already queued for more stays where it is. `php tools/source-answers.php due` lists them, `php
tools/source-answers.php changed [date]` counts what changed since.

## Tests

- `node tools/tests/test_wowhead_crawl.mjs`: what the crawler keeps of a page, on a made-up page.
- `node tools/tests/test_wowhead_crawl.mjs` also covers the pace (speeding up, blocks, the fading memory, network
  errors) and the whole database: the three ways a list page is written, the splitting of a cut list, the pages a list
  names, when a Classic page is read, the queue keys.
- `python -m unittest tools/tests/test_wowhead_pages.py`: the cache and the to-do list.
- `php tools/tests/test_wowhead_db.php`: Wowhead's rows of the answers table, hashes and due times; with
  `FT_TEST_MYSQL=host:port:root:password:db` also the upserts on a real MySQL (changed_at, an older answer, the whole
  page kept, the backfill). `php tools/tests/test_source_answers.php` does the same for the other sources.
- `php tools/tests/test_wowhead_pages.php`: the evidence and what is left out, the queue order, the merge, the crawler download and the extension's (its key, its zip, `api/wowhead-crawler`).
