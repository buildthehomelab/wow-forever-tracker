# Open data sources

Wowhead's Forever tooltips decide **what** WoW Forever has (the analysis). Where each thing comes from (who drops,
sells, teaches, gives or takes it) is server data no client file holds: these sources bring it, each as an **import
card** aimed at the last analysis' gaps (The Forge › Imports). Preview, *Apply what is missing* on your test realm,
roll back from the history, and [export to your data repository](DATA-REPO.md) once it works.

| Source | What it is | Licence | How it is read |
|---|---|---|---|
| [Wowhead's pages](WOWHEAD-PAGES.md) | Wowhead's WoW Forever database, page by page: the creatures and chests that drop an item and how often its players saw it, who sells it, who starts and ends a quest | none stated: ids and counts only, no text; credit it | from a copy in `data/wowhead-pages`, read slowly in your own browser tab (The Forge › Imports). The tracker never asks Wowhead for a page |
| [Wowhead Classic's pages](WOWHEAD-PAGES.md#classics-pages) | Wowhead's WoW Classic database, page by page: how often Classic's players saw a creature or chest drop an item, for creatures and chests Forever kept | none stated: ids and counts only, no text; credit it | from the same copy, read by the full crawl. Drops only, and only where Forever's pages count too few; trusted after every source recorded on Forever |
| [QuestieDB](https://github.com/Questie/QuestieDB) | the Questie addon's Forever database, curated, with what over a million of its players' sessions recorded on live Forever (QuestieTrace): which creatures drop an item and which chests hold it, for about 8,800 items. Ranks right after Wowhead and needs no second source; where Wowhead says otherwise, Wowhead wins | GPL-3.0: credit *"QuestieDB (https://github.com/Questie/QuestieDB)"* | the commit of its newest release, checked every few hours by the container. A row takes the server's chance for the item elsewhere, else (a quest item) `[questie] quest_chance` (40), quest-only |
| [NorgannonDB](NORGANNONDB.md) | open Forever database: QuestieDB, pfQuest, DungeonJournal, cmangos classic-db and its players' Collector | GPL-3.0 | pinned commit, downloaded whole |
| [EG Link](https://github.com/JIVESCORP/eg-link-output-wowf) | what EG Link players' addons recorded on live Forever, per client build: vendor windows, loot with kill counts, trainer lists, who offers and takes quests | CC BY 4.0: credit *"Data from Efficient Games (https://efficient.games), licensed under CC BY 4.0."* | its newest commit, every Forever build |
| [ForeverDB.net](https://foreverdb.net) | its addon data: stock of vendors its players saw on Forever, boss loot measured on Forever, quest givers and enders its players recorded | GPL-3.0 with attribution: *"Data from ForeverDB.net"* | its manifest's version, each file checked by sha256 |
| [AtlasLoot Classic Forever](https://www.curseforge.com/wow/addons/atlasloot-forever) | the loot browser most Forever players run, updated almost daily: the boss (or chest) that drops each item, Forever's new dungeons included, with measured chances for Classic drops | GPL-2.0 | the newest Forever file on CurseForge (no public git repository), checked every few hours by the container |
| [Icy Veins](https://db.icy-veins.com/wow-forever) | what players' addons recorded on live Forever: drops, skinning, pick pocketing, chests and nodes, vendors, trainers, quest givers and words, services, positions | none stated: reference for your own server | its whole database mirrored, gaps first, two requests a second, in the background |

| [ForeverChanges](https://foreverchanges.pro) | what its players' addon saw on live Forever, over a base of Classic's data: who gives and takes quests and where they stand (quest givers by id on its map), vendors, drops counted in kills | none; its terms ask not to republish its compiled data as your own: credit it, and decide for your own project. Since 2026-11-16 a row needs a second source (Wowhead, ForeverDB.net, EG Link): alone it is a hint | the whole site, the tracker's gaps first, read slowly in the background (robots.txt obeyed, one request at a time); every file kept privately in `data/` |
| [VMaNGOS](https://github.com/vmangos/core) | the world database of the 1.12 game, not of Forever, kept patch by patch (the pack takes 1.12): the same questions as cmangos classic-db, asked just before it | GPL-2.0 | from a file you send: a pack made from the `db-….zip` of its `db_latest` release, the tracker never downloads it |
| [cmangos classic-db](https://github.com/cmangos/classic-db) | the content database of the 1.12 game, not of Forever: who trained a recipe, which quest's turn-in cast it, who dropped or sold a recipe. Asked last, and only about what nobody can learn or get | GPL-3.0 | from a file you send: a pack made from the project's own dump, the tracker never downloads it |

What every run of a source said is kept in the tracker's own database, never in the repository: [SNAPSHOTS.md](SNAPSHOTS.md).
Every answer a source gave, whole, is a row of the [answers table](#the-answers-table) too.

Questie and DungeonJournal come in through NorgannonDB, which is built from them: a second Questie import would only
repeat its rows. The locator and the world build read QuestieDB's own Forever corrections (pinned by the commit of its
newest release): positions players recorded with QuestieTrace come before Wowhead's maps, hand-fixed positions after
them.

## The original game's database: the last word, from a file

Two databases of the 1.12 game answer the same questions from packs of one format: **VMaNGOS** first, then cmangos
**classic-db** (`[sources] trust`: `…, wowheadclassic, vmangos, classicdb`). A row a VMaNGOS card wrote is not changed by
a classic-db card; a VMaNGOS card may change a classic-db row.

`python tools/vmangos_pack.py db-13a411e.zip out.cdbpack` makes the VMaNGOS pack from the release zip of
[vmangos/core](https://github.com/vmangos/core/releases/tag/db_latest) (or from the `mangos.sql` inside it): about
450 kB, in 25 seconds. VMaNGOS keeps every row with the patches it belongs to; the pack keeps patch 1.12 only (the
newest version of a template up to 1.12, a loot, spawn or event row only when 1.12 is in its range, a trainer line or
spell by the 1.12.1 client build 5875), renames the columns to cmangos' and is made by the same code as the classic-db
pack. It leaves out what players could never reach, which VMaNGOS keeps and classic-db does not: vendors never spawned,
vendor lists no spawned creature uses, and quests whose title marks them as never made (`<NYI>`, `<TXT>`, `<UNUSED>`,
`REUSE`, test quests). Creatures that are summoned rather than spawned keep their loot. The pack also lists the creatures VMaNGOS never
spawns in any patch and those whose every spawn belongs to a world event (format 5): the locator keeps them out of
its ready spawns (docs/SPAWNS.md). Make the pack again to get them. Its holiday buttons (under *VMaNGOS*) use the realm's own event numbers, since the realm's calendar is VMaNGOS's;
apply a holiday's card from one database only. The analysis reads both packs: a spell either teaches counts as taught,
and an item is "given out nowhere" only when neither gives it out. Send either `.cdbpack` on the Imports page: the pack
names its source and is kept as that source's one pack (`data/vmangos/pack.cdbpack`, `data/classicdb/pack.cdbpack`).

What follows holds for both; the examples are classic-db's.

`python tools/classicdb_pack.py ClassicDB_1_12_1_z2815.sql.gz out.cdbpack` makes a pack from the full dump of
cmangos' classic-db (`Full_DB/` of its repository): about 170 kB of gzipped JSON with its trainer lines, the quests
whose turn-in shows or casts a spell, the spells a line of a creature's conversation casts, and (format 3) the
creatures, chests and vendors of the items that teach (recipes, items learned on use) with each creature's chance
worked out through loot groups and references, and the items the original game gave out nowhere. The dump is only read
as text.

- **Drops and vendors:** for an item players cannot get on the realm, the card proposes Classic's creatures and chests
  that dropped it and the vendors that sold it, through the same rules as every source (a creature the realm does not
  have, or a drop it already has, is left out and counted). An item more than 15 creatures dropped is a world drop: no
  place to put it, left out and counted.
- **Never given out:** an item no loot table of any kind, vendor, quest reward or spell gave out in the original game
  (removed mounts, promotional pets, plans and patterns never released) is listed under *Internal / test* when players
  cannot get it on the realm either, and so is a spell only such items teach. The analysis reads the pack: after
  sending a new one, run the analysis again.
- **Holiday spawns (format 4):** what the original game spawns only while an event runs, by event, with each spawn's
  place. A button per holiday under *Classic database* makes a card of its creatures and objects and the link of
  each to the realm's event (`game_event_creature` / `game_event_gameobject`), and the event itself where the realm
  lacks it (`CLASSICDB_HOLIDAYS` in `app/sources.php`). So far: the **Darkmoon Faire** (Elwynn Forest becomes event 4
  with Forever's holiday 263, Mulgore event 5 with holiday 264: the core reads their dates from the client; the
  building stages are left out, Forever's Faire has one stage) and the **Stranglethorn Fishing Extravaganza** (the
  realm's events 14, 15 and 40), and the yearly holidays under the realm's own events: Lunar Festival 7, Love is in
  the Air 8, Noblegarden 9 (the realm lacks it: made on Forever's holiday 181, 7 days), Children's Week 10, Midsummer 1, Harvest Festival 11 (33 in the original game), Hallow's
  End 12, Winter Veil 2, New Year's Eve 6. A card's preview says how many of its spawns already stand on the realm:
  the quickest way to see which holidays it lacks. Applying gives the spawns new guids and the links follow; a spawn whose creature
  already stands within 30 yards, or whose object within 10, all year or brought in by the same event, is left out with
  its links (another holiday's copy does not count: Midsummer and New Year's Eve both light fireworks over Booty Bay): the realm's holiday spawns come
  from another database (VMaNGOS), which places the same NPC a few yards off, and a closer match gave the realm a
  second Silas Darkmoon or Lunar Festival Elder. The card's own spawns are still told apart at 3 yards, so a crowd stays whole. The world data export numbers the spawns in its
  own range and writes each link with its spawn's new number, only where that spawn was added. Restart the
  worldserver after applying: events are read at start. Send the `.cdbpack` on the Imports page: it becomes the one pack the tracker keeps
(`data/classicdb/pack.cdbpack`) and a card is made at once; *Read the pack again* makes a new card after an analysis.

- **Only what nothing else answers.** The original game is not WoW: Forever. The pack is asked about profession
  recipes that exist in the Forever client and that nobody can learn on the server: no trainer, no quest, no
  obtainable item, no live recording. Where Forever kept the original recipe, the original teacher is the best word
  left. It is the last source in `[sources] trust`.
- **Not what Forever took away.** A recipe whose spell the server's data no longer holds, or that every skill line
  marks as never learned, is not asked: Forever replaced the old healing potions with new ones, and the original
  game would hand the old ones back to every alchemy trainer. They are counted on the card.
- **The spell that teaches.** Classic's trainers and quests name the teaching spell (10843 teaches Heavy Mageweave
  Bandage, 10841). The server's own learn effects say which recipe that is.
- **Trainers.** A trainer line becomes a `trainer_spell` row at the trainer the server has for that creature, with
  Classic's cost, skill and level, under the same rules as every other source.
- **A creature that is no trainer here.** Classic's doctors teach the last bandages and Henry Stern a tea; on a
  server where they stand in the world without a trainer list, the card makes them trainers: a list of its own
  (`trainer`, numbered 1,000,000 plus the creature's number, as the world data numbers such lists), the link to it
  (`creature_trainer`, the creature's own trainer, no menu option) and the spells. Applying the card adds the trainer
  flags to the creature (`npcflag` 16 and 64), as it adds the vendor flag; a rollback removes only the bits it added.
  A creature nobody spawned, or whose number is already another list's, is counted and left alone.
- **Quests.** A quest of the server that casts nothing at its turn-in gets the spell Classic cast
  (`quest_template.RewardSpell`). The operation fills: a quest that already casts a spell is left as it is and counted.
- **Conversations.** A recipe Classic teaches through a line of a creature's or an object's conversation (Knot
  Thimblejack's Gordok Ogre Suit, Omarion's frost resistance recipes, the Journal of Jandice Barov) becomes that line
  on the server, written as data: the line in the conversation the creature or object already opens (a menu of its
  own, numbered 1,000,000 plus a creature's number or 2,000,000 plus an object's, where it opens none), Classic's
  conditions on it (`conditions`, source type 15: skill, a quest done, a reputation rank or higher, a level or higher,
  a spell known or not; the lines on the way to it count too, so Omarion's "Revered" stays on every recipe), and
  SmartAI that makes the player cast the learn spell when the line is picked and closes the conversation. The
  creature or object is switched to SmartAI where it ran nothing, and a creature gets the gossip flag. A creature run
  by a core script, one whose conversation other creatures or objects open too, one that opens several
  conversations, or a line with a condition the server has no word for is left out and counted. A creature or object
  run by one of the core's own teaching scripts is counted apart: Knot Thimblejack's, the engineering transporters', Master
  Craftsman Omarion's and the Field Repair Bot schematic's teach (from core fork PR 60 on for the first three), and the
  analysis counts them as teachers too. The analysis follows a conversation choice into the SmartAI rows it links to and the timed action
  lists they call, which is how Gloom'rel teaches Smelt Dark Iron on Everlake; what those spells teach counts, not the
  spells cast themselves. Where the core has a script for a teacher that runs nothing (Gloom'rel's
  `boss_gloomrel`), the card names the script instead of writing SmartAI; a Gloom'rel who already runs SmartAI (his
  challenge, as on Everlake) gets the SmartAI line.
  The pack (`format` 2) carries these lines; a pack of the first format only counts them.

## ForeverChanges: names and places, from the site

The tracker reads foreverchanges.pro itself: *The Forge › Imports › Read the site*, and the container every
`FT_FOREVERCHANGES_EVERY_HOURS` (6; `0` = never). A visit (`tools/foreverchanges_pull.py pull`, run in the background
by `php tools/source-import.php foreverchanges`) reads up to `[foreverchanges] limit` files (3,000), then makes the
pack (`data/foreverchanges/pack.fcpack`) and the card from everything kept so far. A visit asks for the sitemaps, the
two continents' map files and the page of each quest or item the gaps name, then goes on through the rest of the
site (every other map's data files, quest page and item page: about 20,000 files in all), and reads a file again only
once it is older than two weeks. On 2026-11-16 the project decided to read only the gaps; on 2026-11-21 it reversed
that, because the tracker held too little of the site: now everything read goes into the pack, the card's snapshot
(`ft_source_facts`, source `foreverchanges`) and the answers table (`ft_source_answers`), where it can be queried; the card
itself still lists only what is about a gap.
`[foreverchanges] whole = 0` (`--gaps-only`) reads the gaps alone, as before. At 2.5 s a request the whole site is
about 14 hours of requests: at 3,000 files a visit and a visit every 6 hours, a first full pass takes two to three
days, and keeping it two weeks fresh takes about 1,400 requests a day. A visit writes the pack again every
`[foreverchanges] pack_every` files (500) as well as at its end: a visit a restart cuts short (a full visit is two
hours or more) still leaves what it read in the pack, and the next visit makes the card of that pack, its snapshot
and its answers first, before it reads anything. There is no upload any more: the site was rebuilt in November 2026 and the data files
the old pack was made from (`quests.jsonl`, `items.jsonl`, `tracker-pages/…`) are gone.

What the site holds (2026-11-15) and what is read of it (the gaps first, then the rest):

| What | On the site | Read into the card | Gap it fills |
|---|---|---|---|
| the map's data files of the two continents (`/map/<map>/<file>.json`) | 24 | quest givers **by id** (`quest-givers.json`, the rows its players saw), NPCs its players saw and rares, commerce NPCs and books (places for the locator) | quests without a giver; things nobody spawned |
| quest pages (`/quest/<id>/…`) | 5,729 (1,477 Forever's own) | who starts and ends it (name, zone, place), its side, whether players saw it, the hand-in and progress texts | quests without a giver or an ender, empty quest windows |
| item pages (`/item/<id>/…`) | 13,340 (6,158 Forever's own) | vendors, drops counted in kills | items players cannot get |
| the other maps' data files (dungeons, battlegrounds, cities: three files each of twelve) | 528 | after the gaps: NPCs its players saw, rares, commerce NPCs, books and quest givers by id of each map its manifest names | things nobody spawned; quests without a giver |
| dungeons and topic pages (rares, library books, hidden items …) | 207 | not read any more | |
| the rest of the map files (`services`, `nodes`, `creatures`, `pins`: inns, gathering nodes, flight paths, entrances) | in the above | kept, not read yet | |

**How it reads.** `robots.txt` first, and obeyed (the site closes `/api/`, `/search`, `/spell/`, `/admin`); a plain
request with the tracker's own user agent, asked for compressed; one at a time; English pages only. The pause
starts at `[foreverchanges] pause` (2.5 s) and moves with what the site says: a 429 or 503 doubles it and waits what
Retry-After asks (a minute at least), an answer slower than four seconds lengthens it, fifty quick answers in a row
ease it back. It is kept (`pacer.json`) for the next visit. A 401, 403 or 451, a Cloudflare challenge, or three
throttles or failures in a row stop the visit: nothing is retried around a refusal, and the card is made from what
was kept. Measured on 2026-11-15: about 290 requests at 2.5 s over four visits, no throttle (the pause grew to 2.8 s
once, for slow answers, and eased back).

**In what order.** First what the last analysis lacks: the continents' map files, then the quests without a giver
or an ender, the items other content waits for, then the other items players cannot get; then those of them read
longer than `[foreverchanges] older` days ago (14), oldest first. Then the rest of the site: the other maps' data
files, every other quest page, every other item page (by id), never read first; then those of them read longer than
`older` days ago, oldest first, so a full pass goes round evenly. A file the site did not have (404) is asked again
four times less often. A visit that stops at `limit` goes on where the order left off at the next one; a new gap
is read at the next visit, ahead of the rest. The dungeons and topic pages, Classic's pages and the other languages
are not asked for.

**What is kept, privately** (data/ is never committed): each file once in the content-named store
(`data/sources/blobs/`, as app/store.php keeps every source's files), linked at `data/foreverchanges/site/<path>`; of
a page its `<title>` and `<main>`, gzipped. `pages.jsonl` has a line a reading (the file, when, the status, its key):
the history of every file, since a changed file is a new key and the old one stays in the store. `parsed.jsonl`
remembers what each kept page states, so a page is parsed once. `python tools/foreverchanges_pull.py status` says
what is kept; `pack` makes the pack again with no network. Each card's evidence is kept as a snapshot
(docs/SNAPSHOTS.md): *Card* in *What the sources said* makes it again from the database after a new analysis.

**A second source, or a hint** (the project's decision of 2026-11-16). ForeverChanges stays a card source, but a row
it alone states never becomes a row: not on the card, so it is never applied to the test realm (cards apply
themselves) and never exported to the data repository. A row counts when the client and Blizzard's CDN, Wowhead,
ForeverDB.net or EG Link states it too: the same creature selling or dropping the same item, the same creature or
object giving or taking the same quest (the last snapshot of Wowhead, ForeverDB.net and EG Link), the same quest
window recorded (EG Link's quest texts, `world facts eglink`). The client holds none of these, so in practice it is
the other three. Everything else that is about a gap stays on the card as a hint (`hints`, 500 at most, and a count
per kind under what was left out): it points at the gap, for a person or another source to settle. A second source
that has no snapshot yet is named on the card. Made before this rule, and not removed: Forge operation 23 in the
data repository and one hand-written drop there (Lost One Cook, Recipe: Giant Scrambled Eggs).

- **Quest givers by id.** The map's `quest-givers.json` names who starts each quest by id (`n620` a creature, `o9000`
  an object) and marks the rows its players saw (`addon`). Those rows are taken as they are, with no name to match,
  when the server has a template of that id; one nobody spawned still gives the quest, and its place goes to the
  locator. The other rows are QuestieDB's, which the tracker reads itself: left out and counted.
- **A name, not a number.** The site says "Furmund, Orgrimmar, 50.9 65.3". The name is matched to the server's
  creature (or object) of that name that stands there: the place is turned into world coordinates with the client's
  own map tables, and the creature whose spawn is nearest is taken when it is within 80 yards and no other of that
  name is about as near. The only spawned creature of a name is taken up to 300 yards away (a patrol, a rough pin).
  Without a place, a zone tells two of a name apart when only one stands inside it.
- **Never guessed.** A name several creatures share with nothing to tell them apart, a name no creature has, and a
  creature of that name reported far from where it stands are each counted on the card and left out.
- **Somebody nobody spawned still gives the quest.** Players took the quest from them on live, so the server needs
  them. When exactly one template has the name and nobody spawned it, the giver, ender or vendor row is written for
  that template, and the place the report gives is kept for the locator: the analysis then shows the quest's giver as
  *not spawned*, and the Spawns page offers to place them where players met them. (The first versions refused the
  row, which left such a creature stuck: the server did not know it needed them, so nothing ever offered to place
  them.) With no spawn to compare the reported place with, the name alone decides, so two templates of one name,
  none spawned, are left out. A drop is still only taken from a creature that stands somewhere.
- **Only what is about Forever.** The site's base is Classic's data; it marks what its players saw. Taken: the giver
  and ender of a quest marked as seen by players, vendors, and drops counted in at least ten kills (the chance is
  drops over kills). Left out: a quest nobody saw, a drop given as a bare percentage (Classic's), a quest an item
  starts.
- **A drop is a creature's own when players saw it more than once, from few creatures.** The first card made on a
  whole world was nine tenths Waylaid Crates: world drops, each listed under some fifty creatures that happened to be
  killed when one fell, nearly always once. A drop seen once is a sighting, not a rate, and an item fifteen or more
  different creatures drop is nobody's own loot (it belongs to the world's shared tables, which no report
  describes). Both are left out and counted on the card.
- From there the rules are every source's: only the analysis' gaps, a vendor or drop the server already has is left
  out, and the card is previewed and applied like any other.

Two more things come out of the same visit:

- **Places for what nobody spawned.** The site's maps show NPCs by entry and world coordinates, and rares, commerce
  NPCs and library books by name. Those the server has a template of and no spawn for get their reported place
  (kept with the ForeverScribe positions, which the locator prefers to a looked-up one): press *Locate* on the Spawns
  page after a visit. Only NPCs the site's own addon saw are taken from its NPC list; the rest of that list is
  QuestieDB's, which the tracker reads itself. A pin's name must be exactly one template's.
  The same goes for the quest givers, enders and vendors of its quest and item lists: one that nobody spawned gets
  the place the report gives it, when exactly one template has its name. The first run with only the maps' pins placed nothing the content was waiting for: those NPCs stood
  already. The ones the content waits for are the quest givers.
- **Whose quest it is.** For the quests the site's players saw, the analysis looks at the quests the server keeps
  to one side (`quest_template.AllowableRaces`) and asks that this side be one players on live got the quest on. A
  quest kept to the wrong side fails a check of its own on its page (*Offered to the right side*). Nothing changes
  it by itself.
  A quest the server offers to every race is **not** a finding, whatever side the reports name: most quests are
  offered to every race, and it is their giver's faction that keeps the other side out. The live server itself
  answers "every race" for some 390 quests the site lists under one side, and the first version of this check, which
  compared the two directly, named about 300 quests wrongly. It also read the Horde's race mask as "everyone",
  because its top bit is set: the masks are now the ones the live server sends for each side.

- **What the NPC says at the turn-in.** For the quests players saw and that have no row for that window on the
  server (`quest_offer_reward`, `quest_request_items`). The site shows these texts as a player's client did, and
  marks what the server keeps as a placeholder: `‹name›`, `‹class›`, `‹race›` become `$N`, `$C`, `$R`, a line break
  `$B`, and the window's own list under the text ("Sealed Apprentice Crate (1)") is cut off. About one name in five
  is not marked: the recording player's own name stands there ("You have served well, Fuzzy."). So a text is left
  out when it has a capitalised word the site's own data does not know (its quest titles, NPC, zone and item names,
  and Classic's texts, where it marked every name itself), or names a class or a race in plain words. Where EG
  Link recorded the same window in one wording, that text is taken first: it keeps the server's own placeholders.
  Checked on the 448 texts both have: every one of the 18 the site wrote a name or a class into is left out, and
  360 of the 370 taken are the recording's text word for word (the other ten differ by a comma or a verb).

Not taken from the site, and why:

- **Boss loot of the dungeon pages.** The new items, which are the ones the server lacks, carry no drop chance there;
  AtlasLoot already says which boss drops them.
- **Gathering nodes.** Positions without a height; placing them is the locator's work, not an import's.
- **Its quest giver list by entry** and the services of its maps: they are QuestieDB's and Classic's, which the
  tracker reads from their own sources.

`tools/ft/reports.py` holds the matching; `python tools/tracker.py reports --pack <file> --out <file>` is what the
website runs.

## The same rules for every source

- **Only the gaps**: drops and vendors for items players cannot get and that are not internal (Season of Discovery
  leftovers are internal; items Wowhead does not know yet stay in, they may be undiscovered); givers and enders for
  quests that have none; trainer spells a trainer of the server does not teach yet.
- **Only what is released**: an item, quest or spell that waits for a [release phase](PHASES.md) that is not open yet
  (the *Later* badge) is no gap today, and a vendor, drop, giver or trainer for it would release it early. No source is
  asked about those, and the card's *Left out* line says how many gap items and quests that was. They come in with the
  first import made after their phase opens.
- **Vendors**: unlimited stock unless the source saw a limited one (then restocked hourly); the price is the item's own
  unless another vendor sells it for items or currencies (then that `ExtendedCost`). Stock paid with items or
  currencies the source saw is left out (no cost to give it).
- **Loot**: into the creature's own loot table (`LootID` filled where it is 0) or the chest's (`Data1`); a chance of 0
  (unknown) is left out; an item the table already gives, references included, is left out. EG Link drops count from
  10 looked corpses; skinning, pick pocketing and quest-tied loot are left out.
- **Wowhead's pages**: a drop counts from 10 loots of that creature or chest in which the item fell at least twice;
  an item 15 or more creatures drop is a world drop and is left out; vendor stock paid with a currency or with items
  is left out; a quest's giver and ender are taken by id from the page's Quick Facts. It needs no second source: it
  is the most trusted one after the client. [WOWHEAD-PAGES.md](WOWHEAD-PAGES.md) has the details.
- **AtlasLoot**: only the files its `_Forever.toc` loads; a table that switches itself off before The Burning Crusade
  (`data-tbc.lua`) is not Forever's, nor are blocks wrapped for a later version, instances marked `IgnoreAsSource`
  and rows with a price (vendor stock). A boss without a creature number (Forever's new dungeons) or a chest is found
  by name on the map where the instance's other bosses are spawned: exactly one spawned creature, else exactly one
  spawned object. A list no creature takes is kept as facts all the same (it never makes a server row by itself):
  `al_trash` (an instance's trash), `al_named` (a boss this server has not spawned yet, a chest it lacks, a shared list
  such as *All bosses* or *Class books*, and items of a several-creature list that fit none of them) and `al_reward`
  (a quest's rewards, matched to the server's quest by title, and by side when the list names one). A quest that
  rewards no item at all on the server gets that list as its rewards: up to six items as a choice, one item as
  `RewardItem1`; a quest that already rewards something is left as it is (Wowhead and Questie fill rewards through the
  quest refresh). A list naming several creatures (the
  Guzzler, the Twin Emperors) splits at its heading rows: what sits under a creature's name goes to that creature;
  the rest goes to all of them only when the list's own name names them all (*Fel Steed / Shadow Charger*). A vendor
  (Lokhtos Darkbargainer) gets nothing: its list is its stock. The chance is AtlasLoot's measured one (`droprate.lua`,
  not for lists of several creatures), else the best a live Forever recording (EG Link, ForeverDB.net, Icy Veins'
  cache) measured for that creature or chest and item, else an even share of one drop over the list (counting at least
  three items, so 33 % at most): the card's name says how many at most; `[atlasloot] guess = 0`
  (`FT_ATLASLOOT_GUESS=0`) leaves those out. The rest of what the Forever addon loads is kept as facts too, to compare
  with the other sources: `al_list` rows `[id, "module/table/list[/side]", module, table, list, side, price, faction,
  standing]` from Crafting (the id is the spell a profession makes, Forever's new recipes included), Factions and PvP
  (reputation rewards with their faction and standing), Collections (mounts, pets, tabards, holiday items) and the
  dungeons' vendor rows with a price; `al_rate` rows `[creature, item, chance]` are `droprate.lua` as it is.
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

**One card per source.** A card is built against the gaps and the server as they are at that moment, so a new card of
a source says everything its earlier ones said that is still true. Making one therefore forgets that source's earlier
cards nothing was ever applied from (also when the new one turns out empty: nothing is missing any more). A card you
applied, in whole or in part, stays, rolled back since or not; the history keeps every operation's SQL and rollback
whatever happens to its card.

## Rows the server already has

The sources keep growing: Icy Veins' players loot more corpses every day, EG Link adds a client build, and the game
is rebalanced. An import that only added what is missing would keep the first number it ever read. So an import also
compares the **drops the server already has** with what its source says now, and where a chance moved it proposes the
new one, as a line of its card: *Creature drop chances that moved*, *Chest drop chances that moved*. Tick or untick the
line like a table; nothing changes until the card is applied.

- **Whose rows.** The newer word wins unless a more trusted source wrote the row. Who wrote it: the tracker's own
  ledger (`ft_row_origin`, kept by every apply since it was added), else the source its `Comment` names
  (`Icy Veins 2026-11-14`), else the core. The core's own rows rank below every source, so any import that disagrees
  replaces them (`[sources] change_core = 0` protects them again). A row a more trusted source wrote is counted on the
  card and left alone.
- **Trust.** The game client and Blizzard's CDN come first, always: what the client's own tables or a hotfix hold is
  the game itself, and no import changes a row written from them. The other sources describe what the client does not
  carry (where things drop, who sells them, who gives a quest). `[sources] trust` orders those, most trusted first. By
  default: Wowhead, then Questie's data (it comes through NorgannonDB), then Icy Veins, then EG Link, ForeverDB.net and
  AtlasLoot, then what was counted on Classic (Wowhead Classic), and last the original game's database.
- **Moved.** By a tenth of what it was (`[sources] chance_tolerance`, percent) and by 0.05 points at least: a source
  that counted a few more corpses shifts every number a little, and each change is a line in a file.
- **Safe.** Each statement names the value it replaces (`... AND ABS(Chance - 7.75) < 0.005`): it changes nothing where
  the row moved on meanwhile, nothing more when it runs again, and the rollback is the same statement the other way
  round. *Data repo .sql* exports it as it is.
- **Which sources.** Icy Veins (it looks the items of imported drops up again, besides the gaps; its answers are kept
  for two weeks), EG Link and ForeverDB.net (their whole files are read anyway), and Wowhead's pages (every item page
  in the cache is compared, whether the item is still a gap or not). Not yet: NorgannonDB (it is asked about
  the gaps only), AtlasLoot (its measures are the other sources'), and a trainer's price or a vendor's stock (those tables do not say
  which import brought a row).

### Every value, and spawns that moved

A card does not only add the rows the server lacks. Every applied card (Apply, or by itself: `[imports] auto_apply`)
also compares the rows it carries with the ones the server already has, by their primary key, on every column it gives
but `VerifiedBuild` and `Comment`. Where the server's value differs, and the row's writer is not more trusted than the
card's source (*Whose rows* above), the card's value replaces it, with the same guarded statement and rollback as a drop
chance. A drop chance counts as different only past `[sources] chance_tolerance`.

Spawns: a creature or object the card places where none of its kind stands, with one of the same kind on the same map
within `[imports] spawn_move_yards` (40 by default, 0: never) that the card does not also place, is that spawn moved:
the nearest one gets the card's position and facing, keeping its guid (its addon, formation and pool rows stay). A
spawn a more trusted source placed is left where it is, and no second one is added beside it. Like every spawn, moves
are written only while the worldserver is stopped. A holiday's spawn (one the card links to a game event) with one of
its kind within 30 yards (an object within 10), there all year or brought in by the same event, is that one, which
stays where it is: the realm's holiday spawns come from VMaNGOS, and a holiday card from another database moves nothing
that close. A holiday's spawn only ever moves one its own event brings in, never another holiday's or one of all year.

A file imported by hand counts as the source `sniff` (WowPacketParser's format) or `scribe` (ForeverScribe's notes).
Both come after the Forever sources and before Classic's in the default order.

Applying the cards in the order they were made (which auto-apply does) is what makes the newest word the one that stays.

### Quests, read again from the live game

A quest the server has is never a gap, so no import looked at it again; and Blizzard keeps changing quests: a reward
is swapped, an amount is lowered, a text is rewritten. EG Link records each quest as the live server sent it to a
client (the client's quest cache), per client build. The EG Link import compares that record with the server's rows
and proposes what differs, as lines of its card (`quest_template.RewardItem1`, `quest_objectives.Amount`, ...).

- **The later word wins.** A row carries the client build it was recorded on (`VerifiedBuild`), the record the build
  it was seen on. A record is taken only from the live game, and only when it is from a later build than the row. A
  row from the same or a later build is the newer word and is left alone (*the row is the newer word*).
- **What is compared.** What a quest gives (items, choices, currencies, reputation, spell, XP difficulty and
  multiplier) and what it says (title, objectives text, description, area, completion log) in `quest_template`; an
  objective's amount and text in `quest_objectives`, by Forever's own objective id; the level a quest is offered from
  in `quest_classic_level`.
- **Only what says something else is a difference.** The first run on a whole world proposed 7,400 changes, and most
  were the same thing written another way. So:
  - *A recording never empties a value.* A record that names no reward item, no completion text or no faction is not
    proof there is none (rewards chosen by class or condition are not in the plain fields; not every text is kept).
    The row's value stays, and the card counts those quests.
  - *Reputation is compared as points.* A row gives it as a tier (`RewardFactionValue`, read in the client's
    `QuestFactionReward` table) or as points times a hundred (`RewardFactionOverride`); 75 points either way is no
    change. Without the server's copy of that table, a row written the other way is left alone and counted.
  - *Text is compared as it reads.* Line breaks (`$B`, a line feed), runs of spaces and the case of a placeholder
    (`$n`, `$N`) do not count; an amount the record writes as a placeholder (`$1oa Gnarlpine Fangs`) and the row as
    its number is the same text.
  - *Rewards are compared as a list, not slot by slot.* The same items, choices, currencies or reputations in another
    order are no change. Where the list really differs the slots take the record's; a record that names fewer than
    the row leaves the row as it is (filling one slot and not clearing another would give a reward twice).
  - *The end text stands in either column.* Older rows hold it in `QuestCompletionLog`, the record in
    `AreaDescription`.
  - *Not compared:* the money and the quest's own level. The server sends both for the player who asked (at the
    level cap the money is what is given instead of experience; a scaling quest shows the player's level).
- **What is never changed.** What decides how the server handles a quest: its type, flags, start item, time limit,
  zone, races, the quest after it. A server may hold those differently on purpose, and a wrong one breaks a quest
  instead of misstating a reward. They are compared and counted on the card (*differ from the recording*).
  Nothing is added either: an objective the server lacks is a quest's shape, not a value.
- **Safe, as above.** Each statement names the value it replaces and has its rollback; *Data repo .sql* exports it as
  it is. The comparison is the analysis' own code (`python tools/tracker.py refresh quests --eglink <commit> --out
  <file>`, `tools/ft/refresh.py`); the website accepts from it only those tables and columns.

`[sources] refresh = 0` turns it off: imports then only add.

## How old an answer may be

Answers are kept on disk so that a source is not asked the same thing at every run. They come due again by themselves:

| Source | An answer | "Does not know it" |
|---|---|---|
| Wowhead | about 30 days (`[wowhead] refresh_days`; each answer between three quarters and one and a quarter of it, by id, so that the answers of one run do not all come due on one day; 0: kept for good) | 7 days (`recheck_days`) |
| Icy Veins | 14 days | 7 days |
| EG Link, ForeverDB.net, AtlasLoot | their newest version is read at every import | |
| ForeverChanges | 14 days (`[foreverchanges] older`) | four times that |
| NorgannonDB | the pinned version (`[norgannondb] commit`) | |

Before this, an answer Wowhead had given was kept for good: a level it corrected, a spawn point it moved or a "may not
be in WoW: Forever" note it dropped never reached the tracker. When Wowhead cannot be reached, the answer on disk is
used. The analysis log says how many answers were asked again and how many came back different.

**Ask every source again** (The Forge > Imports) makes every answer kept so far count as due, whatever its age.
Nothing is asked at that moment and nothing is deleted: the next analysis asks Wowhead again, the next imports their
sources, and AtlasLoot's current version is read again. Those runs take as long as the very first ones did; one that is
cut short goes on from where it stopped, since what was asked since the button was pressed is not asked twice.

## The answers table

Every answer the tracker got from an outside source is also a row of `ft_source_answers` in the tracker's database:
everything the source said, not only the facts a card takes (those are in `ft_source_facts`,
[SNAPSHOTS.md](SNAPSHOTS.md)). It can be read with SQL (The Forge › Query, database *tracker*), and what a source
changed since is a query. The files under `data/` stay what the analysis and the imports read; the table follows them.

| Source | `feed` | One row is | From |
|---|---|---|---|
| Wowhead, Wowhead Classic | `tooltip`, `page` | a tooltip; a page the crawler read, the whole page too ([WOWHEAD-PAGES.md](WOWHEAD-PAGES.md#the-wowhead-rows)) | `data/wowhead/`, `data/wowhead-pages/` |
| Icy Veins | `api` | one API answer: the mirror's record as `data`, the whole answer (link metadata and tooltips too) as `whole` | `data/icyveins/<kind>/<id>.json.gz` |
| Icy Veins | `list` | a kind's list of ids | `data/icyveins/<kind>.ids.json` |
| ForeverChanges | `site` | the last reading of a page or a map file: a page's `data` is what it states (`parsed.jsonl`), its `whole` the page's text; a map file's `data` is the file | `data/foreverchanges/pages.jsonl`, `site/`, the blob store |
| QuestieDB, NorgannonDB, EG Link, ForeverDB.net | `file` | a record of a file of the version downloaded: an entry of a Lua table (`[25] = {...}`, NorgannonDB's `R(25, ...)`), a key of a JSON file (an EG Link creature's loot, a vendor), a whole small file | `data/<source>/<commit or release>/` |
| AtlasLoot | `file` | the same, of every file of the addon's zip | `data/atlasloot/<file id>.zip` |
| VMaNGOS, Classic database | `file` | the same, of the pack you sent | `data/<source>/pack.cdbpack` |

| Column | What it holds |
|---|---|
| `source`, `feed`, `branch`, `kind`, `ref` | the key. `source` is the source's name in `app/sources.php` (`wowhead`, `icyveins`, `questie`, `norgannondb`, `eglink`, `foreverdb`, `atlasloot`, `foreverchanges`, `vmangos`, `classicdb`). `branch`: Wowhead's `forever` or `classic`, Icy Veins' `wowf`, else empty. `kind`: the entity's kind, or a file's name without its extensions (`foreverItemDB`, `loot`, `NPCs`). `ref`: the id; a list's query; a file's path, then `#` and the record (`data/wowf/1.15.8.65424/loot.json#/sources/npc:448`, `items.lua#42`, `Data/NPCs.lua#ns.npcs/2299`) |
| `id`, `name` | the entity's id (NULL when there is none) and the name the answer gives |
| `status` | `found`; `missing` when the source does not know it (a 404); `gone` when a newer version of a downloaded source no longer holds that record |
| `version` | the version the answer is of: a commit, a release, a CurseForge file id, Wowhead's crawler record version, the blob key of a ForeverChanges reading |
| `data` | the answer, as JSON. A text record of a file is `{"text": ...}`; a small binary file `{"base64", "size"}` |
| `whole`, `whole_at` | the whole answer when `data` is less, and when it was read: Wowhead's whole page, Icy Veins' whole API answer, a ForeverChanges page's text. A later answer without one keeps the one held |
| `hash`, `whole_hash` | SHA-1 of `data` and of `whole` (keys sorted, the time left out). Icy Veins' `whole` has none: its link metadata is not compared |
| `fetched_at`, `first_seen`, `changed_at` | when the answer held was read (a version: when it was downloaded), when the tracker first had one, when what the source says last changed |
| `due_at` | when the source's own rules ask it again ([How old an answer may be](#how-old-an-answer-may-be)): Wowhead's, Icy Veins' (14 days, 7 for *does not know it*, a list after a day, at once after *ask every source again*), ForeverChanges' (`[foreverchanges] older`, 14 days; a page the site did not have four times later). NULL for a downloaded version: a new version is looked for as a whole, by its import |

`changed_at` moves only when the hash of `data` differs from the row's, or the status, or that of `whole` when both
answers carry one with a hash: an answer read again that says the same moves `fetched_at` alone, and an answer older
than the one held changes nothing. A large downloaded file is cut into records (of about 256 kB at most; what lies
between the entries is kept as `~rest` records), so that a new version moves `changed_at` of the records it changed
only, and what it dropped becomes `gone`.

    -- what changed this week, by source
    SELECT source, kind, COUNT(*) FROM ft_source_answers WHERE changed_at > first_seen AND changed_at >= NOW() - INTERVAL 7 DAY GROUP BY source, kind;
    -- everything every source says about one creature
    SELECT source, feed, ref, data FROM ft_source_answers WHERE id = 448 AND kind IN ('npc', 'loot', 'vendors', 'npcs', 'NPCs');
    -- Icy Veins' gossip recording of a creature
    SELECT JSON_EXTRACT(data, '$.relations.addon_gossip') FROM ft_source_answers WHERE source = 'icyveins' AND kind = 'npc' AND id = 448;
    -- what the newest QuestieDB release dropped
    SELECT ref, version, changed_at FROM ft_source_answers WHERE source = 'questie' AND status = 'gone' ORDER BY changed_at DESC;

**How rows come.** At once, when the answer reaches the tracker: a Wowhead page or tooltip, an Icy Veins answer or
list, a version an import downloaded (QuestieDB, NorgannonDB, EG Link, ForeverDB.net, AtlasLoot, a pack you sent),
the pages a ForeverChanges visit read. What the files already held is written by `php tools/source-answers.php
backfill`: the container runs it at every start, the analysis at its end. The first run reads everything (of a
downloaded source, the newest version kept: the older ones were superseded before the table); later runs only what
each source's files gained since (`data/source-answers.json` remembers where each stopped). `--all` reads everything
again; `backfill icyveins questie` only those sources. `php tools/source-answers.php count` counts the rows by
source, `changed [date]` what changed since.

The first version of the table, `ft_wowhead`, moves in by itself (its rows become `source = 'wowhead'`) and is
dropped.

## Running them

- The Forge › Imports: *Import Wowhead pages*, *Import EG Link*, *Import ForeverDB.net*, *Import Icy Veins*, *Import AtlasLoot*, *Import NorgannonDB*.
- `php tools/source-import.php <source> --from-database`: the card from the source's last run kept in the database, nothing asked ([SNAPSHOTS.md](SNAPSHOTS.md)).
- `php tools/source-import.php questie|norgannondb|eglink|foreverdb|icyveins|atlasloot|wowhead|wowheadclassic`; `atlasloot --if-new` does nothing
  when the newest CurseForge file is the one imported last, `questie --if-new` when QuestieDB's newest release is. One run of a source at a time: a second one says the
  import is already running and exits 3. `--log` writes the run's lines to `data/source-<source>.log`, the file the
  Imports page reads, instead of printing them.
- QuestieDB by itself: the container checks its newest release every `FT_QUESTIE_EVERY_HOURS` (6; `0` = never), 20
  minutes after start and never while an analysis runs, and makes a card when a new release is out.
- AtlasLoot by itself: the container checks CurseForge every `FT_ATLASLOOT_EVERY_HOURS` (6; `0` = never), 15 minutes
  after start and never while an analysis runs, and makes a card when a new version is out. Its last log line shows on
  the Imports page. Every download stays in `data/atlasloot/` (`[atlasloot] keep` limits how many). A new analysis alone makes no new card: press
  *Import AtlasLoot* after one.
- Icy Veins runs in the background and keeps a **mirror of its whole WoW Forever database**: every NPC, object,
  quest, item, zone, flight path and map it lists (about 67,000 answers, read from its list pages 200 at a time,
  from both ends: without an API key a list stops after 10,000 rows; items past both ends come from what the NPCs,
  objects and quests name),
  each kept whole (the entity, its children and every relation) in `data/icyveins/<kind>/<id>.json.gz`. The gaps are
  asked first (items players cannot get, quests without giver, ender or turn-in words, the server's trainers), then
  the rest. Two lookups a second: about nine hours the first time. Its last log line shows on the Imports page. Answers
  are asked again after 14 days (7 for "not found"): it is a young project and keeps growing. `[icyveins] max`
  (`FT_ICYVEINS_MAX`, 100,000) caps the lookups of one run; the next run goes on.
  - **What the card takes from the mirror:** NPC drops (`creature_loot_template`), what Skinning gives
    (`skinning_loot_template`) and Pick Pocket (`pickpocketing_loot_template`) — each recorded drop names the spell that
    looted it (Mining and Herb Gathering on a creature go to the skinning table too, as the core loots them), and
    before 2026-11-15 skinned leather went to the corpse table: such rows an earlier card applied stay where they are
    until removed by hand —, what chests, ore veins and herbs hold
    (`gameobject_loot_template`), quest-only drops (`QuestRequired = 1`), vendor stock, trainer lists, recipes with the skill rank they need (only from NPCs
    whose services say trainer: the recording gives bankers and innkeepers stray lists), quest givers and enders (from
    the quest's page, the NPC's and the object's), the turn-in words (`quest_offer_reward`, `quest_request_items`, for
    quests that have no row there), and the NPC services as `npcflag` bits the creature lacks (innkeeper, banker,
    flight master, spirit healer). Applying a skinning or pick-pocket row fills the creature's `SkinLootID` /
    `PickPocketLootID` where it is 0, as `LootID` already was.
  - **An early card** is made as soon as the gaps are all asked (minutes on a run that goes on from its mirror),
    from their answers alone: "Icy Veins <date> (gaps)". The full card at the end replaces it, unless something was
    applied from it.
  - **The locator** reads the positions players recorded (`addon_points`) for creatures and objects Wowhead cannot
    place: "seen by players (Icy Veins)".
  - **Kept, counted on the card, not written yet:** levels, the money a creature drops, what an NPC says (gossip),
    container contents (clams, lockboxes: no chance is recorded), flight routes, the zones' NPC lists, quest chains.
    They are in the mirror for the next feature to use. [ICYVEINS.md](ICYVEINS.md) lists everything the API holds.
  - **A restart** stops the run. The container goes on with it at its next start, from the cache, once MySQL answers
    and no analysis runs (`FT_ICYVEINS_RESUME=0`: only the button does). Without Docker, press the button again.
  - **When Icy Veins does not answer** (an outage, a block, no network), nothing is cached for that lookup and the run
    waits longer before each next one: 1, 2, 4 … 60 seconds. After 20 lookups in a row without an answer (about a
    quarter of an hour) it stops, makes no card, and its last log line says which lookup failed. Press the button
    again once Icy Veins answers: the run goes on from its cache.

A download is kept only when it came whole: its size is the one the server announced, and the file is what it should
be (JSON that reads, a NorgannonDB file whose last record and tables are closed, ForeverDB.net's checksum, AtlasLoot's
size). Otherwise nothing is kept, the import says why, and the next run downloads it again; a file an older version
kept cut short is noticed and fetched again too.

Run the analysis again after applying an import: what it filled no longer counts as a gap, so the next import of
another source only brings what is still missing.
