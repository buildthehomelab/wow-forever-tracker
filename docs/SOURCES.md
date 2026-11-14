# Open data sources

Wowhead's Forever tooltips decide **what** WoW Forever has (the analysis). Where each thing comes from (who drops,
sells, teaches, gives or takes it) is server data no client file holds: these sources bring it, each as an **import
card** aimed at the last analysis' gaps (The Forge › Imports). Preview, *Apply what is missing* on your test realm,
roll back from the history, and [export to your data repository](DATA-REPO.md) once it works.

| Source | What it is | Licence | How it is read |
|---|---|---|---|
| [NorgannonDB](NORGANNONDB.md) | open Forever database: QuestieDB, pfQuest, DungeonJournal, cmangos classic-db and its players' Collector | GPL-3.0 | pinned commit, downloaded whole |
| [EG Link](https://github.com/JIVESCORP/eg-link-output-wowf) | what EG Link players' addons recorded on live Forever, per client build: vendor windows, loot with kill counts, trainer lists, who offers and takes quests | CC BY 4.0: credit *"Data from Efficient Games (https://efficient.games), licensed under CC BY 4.0."* | its newest commit, every Forever build |
| [ForeverDB.net](https://foreverdb.net) | its addon data: stock of vendors its players saw on Forever, boss loot measured on Forever, quest givers and enders its players recorded | GPL-3.0 with attribution: *"Data from ForeverDB.net"* | its manifest's version, each file checked by sha256 |
| [AtlasLoot Classic Forever](https://www.curseforge.com/wow/addons/atlasloot-forever) | the loot browser most Forever players run, updated almost daily: the boss (or chest) that drops each item, Forever's new dungeons included, with measured chances for Classic drops | GPL-2.0 | the newest Forever file on CurseForge (no public git repository), checked every few hours by the container |
| [Icy Veins](https://db.icy-veins.com/wow-forever) | what players' addons recorded on live Forever, one answer per item, quest and NPC | none stated: reference for your own server | asked about each gap, two requests a second, in the background |

Questie and DungeonJournal come in through NorgannonDB, which is built from them: a second Questie import would only
repeat its rows.

## The same rules for every source

- **Only the gaps**: drops and vendors for items players cannot get and that are not internal (Season of Discovery
  leftovers are internal; items Wowhead does not know yet stay in, they may be undiscovered); givers and enders for
  quests that have none; trainer spells a trainer of the server does not teach yet.
- **Vendors**: unlimited stock unless the source saw a limited one (then restocked hourly); the price is the item's own
  unless another vendor sells it for items or currencies (then that `ExtendedCost`). Stock paid with items or
  currencies the source saw is left out (no cost to give it).
- **Loot**: into the creature's own loot table (`LootID` filled where it is 0) or the chest's (`Data1`); a chance of 0
  (unknown) is left out; an item the table already gives, references included, is left out. EG Link drops count from
  10 looked corpses; skinning, pick pocketing and quest-tied loot are left out.
- **AtlasLoot**: only the files its `_Forever.toc` loads; a table that switches itself off before The Burning Crusade
  (`data-tbc.lua`) is not Forever's, nor are blocks wrapped for a later version, instances marked `IgnoreAsSource`
  and rows with a price (vendor stock). A boss without a creature number (Forever's new dungeons) or a chest is found
  by name on the map where the instance's other bosses are spawned: exactly one spawned creature, else exactly one
  spawned object; lists such as *Trash* or *Sets* match none and are left out. A list naming several creatures (the
  Guzzler, the Twin Emperors) splits at its heading rows: what sits under a creature's name goes to that creature;
  the rest goes to all of them only when the list's own name names them all (*Fel Steed / Shadow Charger*). A vendor
  (Lokhtos Darkbargainer) gets nothing: its list is its stock. The chance is AtlasLoot's measured one (`droprate.lua`,
  not for lists of several creatures), else the best a live Forever recording (EG Link, ForeverDB.net, Icy Veins'
  cache) measured for that creature or chest and item, else an even share of one drop over the list (counting at least
  three items, so 33 % at most): the card's name says how many at most; `[atlasloot] guess = 0`
  (`FT_ATLASLOOT_GUESS=0`) leaves those out.
- **NorgannonDB needs a second source for vendors and loot**: it mixes Classic databases with what its players saw, so
  alone it would bring Classic test vendors (unreleased mounts, the Panda Collar, soul shards for sale) and quest-only
  items. A NorgannonDB vendor or drop is kept only when EG Link, ForeverDB.net or Icy Veins (answers already fetched)
  saw the same creature or chest sell or drop the same item on live Forever, or (drops) AtlasLoot's last download
  lists the item under that creature; a giver or ender, when one of them saw the
  same creature or object give or take the same quest (NorgannonDB's quest numbers can be Season of Discovery's, which
  Forever reused for other quests). Run *Import Icy Veins* first: its answers count. Trainers keep NorgannonDB alone.
- **Quests an item starts** (ItemSparse `StartQuestID`) need no giver: no source adds one (the creature that drops the
  item, or the chest it lies in, would be wrong).
- **Quests**: only quests the server has no giver (or no ender) for; creatures and objects the server has.
- **Trainers**: at the trainers the server has for that creature (`creature_trainer`). A class spell needs a level:
  the source's, else the server's other trainers', else Wowhead's *"Requires level N"*. The ranks a spell needs: the
  source's, else the server's other trainers'; a higher rank with neither is left out (a talent's later rank would be
  sold to anyone). Professions keep their skill line and rank; a profession entry whose skill is unknown is left out.

Each card lists what was left out and why, and carries the source's licence in its name.

## Running them

- The Forge › Imports: *Import EG Link*, *Import ForeverDB.net*, *Import Icy Veins*, *Import AtlasLoot*, *Import NorgannonDB*.
- `php tools/source-import.php norgannondb|eglink|foreverdb|icyveins|atlasloot`; `atlasloot --if-new` does nothing
  when the newest CurseForge file is the one imported last.
- AtlasLoot by itself: the container checks CurseForge every `FT_ATLASLOOT_EVERY_HOURS` (6; `0` = never), 15 minutes
  after start and never while an analysis runs, and makes a card when a new version is out. Its last log line shows on
  the Imports page. The last three downloads stay in `data/atlasloot/`. A new analysis alone makes no new card: press
  *Import AtlasLoot* after one.
- Icy Veins runs in the background: several hours the first time (one lookup per gap item, quest and trainer, two a
  second). A restart stops it; press the button again and it goes on from its cache. Its last log line shows on the
  Imports page. Its
  answers are kept in `data/icyveins/` and asked again after 14 days (7 for "not found"): it is a young project and
  keeps growing. `[icyveins] max` (`FT_ICYVEINS_MAX`) caps the lookups of one run; the next run goes on.

Run the analysis again after applying an import: what it filled no longer counts as a gap, so the next import of
another source only brings what is still missing.

## ForeverChanges / ForeverMaster reference source

**The Forge → Imports → Refresh ForeverChanges** downloads the official addon ZIP,
checks its SHA-256, parses its Lua data without executing it, and replaces this
source's records in `ft_world_facts`. The Imports panel reports loaded records,
matching tracker resources and incomplete resources by category. Open a matching
resource to see the ForeverChanges panel, its build and archive provenance.
References are visible to administrators only. Existing sources are preserved.

This source uses the world source registry (`tools/world/layers.json`) and fact
store, with `reference` use and fact kind. It does not create an executable import
card, mark a resource available, change client metadata, participate as a live
recording, or generate server SQL. It is excluded from public data exports. The
addon is listed as All Rights Reserved; no addon files, guide prose or compiled
third-party tables are committed to this repository. Downloads stay in ignored
`data/foreverchanges/<archive hash>/` directories.

Included: item names and acquisition hints, recipe requirements/reagents/output
and teaching-item relationships, profession learning/leveling records (where a
recipe is learned, its price and its training fee), dungeon quests and
prerequisites, which quest a dungeon item is for, explicit instance-map mappings
and entrances, boss-item hints with the boss's level, training ranks, trainer
locations, library-book references, librarians and reputation rewards. Fields
are named and numbers are numbers (`{"learn": 25, "yellow": 65, "reagents":
[[785, 1]]}`), so a record reads without the addon's source beside it. Multiple
relationships are retained under the same resource ID. Classic labels are
preserved; absence of a Classic label is not treated as observation evidence.

What is the same for every record (the archive's SHA-256, the pack's header, the
inventory) is said once, in `data/foreverchanges/<archive hash>/summary.json`
and in the source's pin: a record carries only the pack's version. That makes a
load a third of the size it was (6.8 MB for the 0.7.8 pack instead of 19.4 MB).

The pack's talent data contains build presets, not talent node IDs: those are
counted in the inventory without fabricating talent entities. Dungeon slugs with
no explicit map mapping are not guessed into tracker dungeon IDs. Boss names do
not become creature IDs. A boss-item hint carries a chance only where the pack
gives one, as `classic_chance`: the pack has them for Classic bosses only, and
the site says they are AtlasLootClassic's figures, not what Forever players saw.
World quest name/level entries remain distinguishable from detailed dungeon
quest records.

**Whose word the pack's map is.** The quest givers of the pack's map layer come
as `map_giver` on a quest: a name, the line under it, a side and up to four map
pins, with no NPC id. The site's own map files name where that layer comes
from: QuestieDB for NPCs, cmangos classic-db for town services, and its map
says NPCs "stand where they stood in Classic". So the registry lists `questie`
and `cmangos` beside `atlasloot` and `blizzard` under the source's `also`: it is
never a second witness beside any of them.

### What the site's pages state beyond the pack

The website is broader than the downloadable pack. Its pages state what the pack
does not: a new quest's hand-in and progress text and who starts and ends it,
who sells an item and for how much, what drops an item and how often (with the
count behind a percentage: "88 in 288 kills"), and the map's NPCs by id. Much of
it is what the players of its addon recorded, which no other source here has.

```sh
# Read the pages into a folder, slowly. About 19,800 pages: most of a day the
# first time. It can be stopped and started again; nothing is asked for twice.
python3 tools/ft/foreverchanges_pages.py mirror

# What the folder holds, what is left, whether a reader is at work and when it ends. No network.
python3 tools/ft/foreverchanges_pages.py status

# A later visit: new pages, and again the ones last read more than 14 days ago, 2,000 at most.
python3 tools/ft/foreverchanges_pages.py update --limit 2000

# Only some of it: maps, dungeons, topics, quests, items.
python3 tools/ft/foreverchanges_pages.py mirror --only quests --limit 500

# Load what is kept as references (source foreverchanges-pages); --prepare writes the SQL only.
python3 tools/foreverchanges-import.py --pages
```

The folder is `ForeverTracker-data/foreverchanges-pages` in your home folder
unless `--out <folder>` or `FOREVERCHANGES_PAGES` names another: outside the
checkout on purpose, so that deleting the checkout or cloning it again does not
take a day's reading with it.

How it reads: `robots.txt` is fetched first and obeyed (the site closes `/api/`,
`/search`, `/spell/` and `/admin`); one request at a time with a pause of 2.5
seconds (2 at least), asked for compressed; only English pages; a 401, 403, 429
or 451, three failures in a row, or an answer that is not the page stops the
run, and nothing is retried around a refusal. One reader a folder: a second one
started on the same folder is refused before it asks the site anything. Of a
page only its `<main>` element is kept (`quest/<id>.html.gz`), about 6 KB a
page; the map's own data files are kept as they are (`map/<slug>/<file>.json`).
The order is the map's data files, the dungeons, the topic pages, Forever's own
quests and items, then Classic's quests and items.

#### Later visits

The site gives no cheap way to ask whether a page has changed (measured
2026-11-13): its quest and item lists date every page the same day, and a
request that names the copy you hold (`If-None-Match`) is answered with the
whole page again. Reading everything again would be the same day of requests,
so `update` reads again only what is worth it:

1. The three lists of pages. A page they newly name is read; one they no longer
   name is noted, and its kept copy stays.
2. What was last read more than `--older` days ago (14 unless given), in this
   order: the small files (map data, dungeons, topic pages: about 700 requests,
   and the map files that were not there are asked for again); Forever's own
   quests and items that still lack something (a quest without its hand-in
   text, or with nobody named who starts or ends it; an item no source is named
   for), which is where players' recordings arrive; the rest of Forever's own;
   Classic's. Oldest first within each.
3. A quest whose row in a map's `quest-givers.json` changed is read at once,
   due or not.

`--limit` bounds a visit and the next one goes on where the order left off, so
a weekly `update --limit 2000` (under two hours) keeps the folder current. A
newly read page replaces the kept copy; whether it *changed* is decided on what
it states (the quest's or item's record, a map file's content, a topic page's
words), not on its bytes: a new build of the site rewrites every page's markup
and none of its words.

Two files in the folder carry this. `pages.jsonl` has a line a reading (`f` the
kept file, `at` when the site was last asked, `s` 200 or 404, `since` when what
it states last changed, `want` while a page of Forever's own lacks something,
`out` once the site no longer lists it); the last line of a file counts.
`changes.jsonl` has a line for each thing a visit found: `at`, `what` (`new`,
`changed` or `gone`), `file`, `page`, and for a change the `fields` that
differ (`texts`, `start`, `end`, `sources`, ...). `status` shows the latest.

What a load holds, as `reference` facts of the source `foreverchanges-pages`:

| Resource | Dataset | States |
|---|---|---|
| quest | `quest_page` | level, side, class, money, XP, reputation, who starts and ends it (name, zone, coordinates, or the item that starts it), the hand-in text (`texts.complete`) and the progress text (`texts.progress`) when a player saw them, whether the page says players of its addon saw it. A Classic quest's own description is left out |
| quest | `map_givers` | who starts it **by id**, from the map's quest giver layer: an NPC or an object, its name, side and world coordinates. Starts only: the layer does not say who ends a quest |
| item | `item_page` | each source the page names: a vendor with zone, coordinates and price in copper; a creature or a dungeon boss with a rate. An item whose page names no source gives no record |
| npc | `map_npc` | name, the line under it, side, role (npc, vendor, trainer), world coordinates in whole yards, whether the site's players recorded it, and the layer's own `source` |
| npc | `map_creature` | a rare or an elite of the map: name, level range, where it stands |

**Names to ids.** A page names who starts and ends a quest and who sells or
drops an item by name. The map's data files name NPCs and objects by id (its
NPC layer, its rares and elites, its quest givers), so each name on a page is
looked up there:

- one thing carries the name: the entry gets `"kind": "npc", "id": 257008,
  "matched_by": "name"`;
- several do (an object such as "Wanted Poster"): the entry gets `"candidates"`,
  eight at most, and nothing is picked;
- none does: the entry stays a name.

Names are compared without regard to case, the kind of apostrophe and runs of
spaces. Among the people of the two continents' map files 3 names in 3,192
belong to more than one id, so a single match is rarely a coin toss; it is still
the site's word twice, not a second witness, and it does not show that nothing
else in the game is called the same. `summary.json` and the load's last line
say how many names found one id, several, or none.

Limits to know. An NPC the map files do not hold gets no id: a name is never
turned into an id by guessing. A page names no
build, so these records carry build 0 and the resource panel says so. A side of
`AH` on a row the site's players recorded means "not known". The player's name
inside a quest text is written `‹name›` by the site. The site has no licence and
its terms forbid republishing its compiled data: like the pack, these records
are shown to administrators, never written to a world, never exported.

CLI equivalents:

```sh
# Refresh official addon data into tracker reference tables only.
php tools/source-import.php foreverchanges

# Validate an already downloaded archive and prepare tracker SQL without loading.
python3 tools/foreverchanges-import.py --archive /path/to/ForeverMaster.zip --prepare

# Existing world commands are supported too (the archive must still match its pin).
python3 tools/tracker.py world pin foreverchanges
python3 tools/tracker.py world facts foreverchanges
```

The refresh worker is serialized. Malformed or changed archives fail before a DB
load; a failed load rolls back through the existing fact-store transaction.
Reference matches describe investigation leads, not a count of fixes completed.
