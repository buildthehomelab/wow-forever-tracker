# Changelog

## Unreleased

- **The Chrome extension takes a new crawler every hour.** It loaded the tracker's crawler only when its tab had
  none, so a tab that crawled for days kept the queue and code it started with: the new order of the crawl did not
  reach it. Extension 1.1.0 reloads the tab for a new crawler once the one it runs is an hour old (and at once for one
  an earlier version loaded), only after the tracker answered. Download it again from The Forge › Crawl and reload it
  in `chrome://extensions`.

- **The crawl reads the items with no source before the creatures with missing data.** The items that only lacked a
  source were the crawler's tier 4, behind more than 2,000 creature pages of tier 3 (about a day of reading at its
  pace). They are now tier 3, what their pages name tier 4, and the server's creatures and objects whose data is
  missing tier 5. A crawl that is already running (the Chrome extension's) is put in the new order once, the next
  time it loads the crawler.

- **The VMaNGOS pack leaves out what players could never reach.** VMaNGOS keeps vendors that never spawn (the World
  Mount Vendor, test and "[UNUSED]" vendors), vendor lists no spawned NPC uses (old PvP rank gear) and quests Blizzard
  marked as never made ("<NYI>", "<TXT>", "<UNUSED>", "REUSE", test quests). classic-db leaves these out. Counted as
  ways the game gave an item out, they took 114 items and 24 mount spells out of *Internal / test* and put them in To
  add. The pack now drops them. Make the pack again and send it to put those back.

- **A card no longer puts back drop chances a better source set.** A card's values measured again (the `/* refresh */`
  lines) were weighed against who wrote each row only when the card was made, and applying them never kept their
  source. So a card made before a Wowhead apply put its own numbers back over Wowhead's, and any card could undo any
  other's. Those values are now weighed again when the card is built: a row a more trusted source (or an
  administrator) wrote since is held, and the source of each one applied is kept. The sources of rows refreshed
  before this are read back once from the History, the newest apply of a row winning.

- **Applied import cards fold away.** A card kept its place on the Imports page after it was applied, and the Imports
  badge counted every card ever made. Each card now records when it was last applied and when nothing on it was
  missing any more (an apply that wrote it all, or a preview or apply that found nothing to add). Those cards fold
  under "Applied: nothing left to add", and both Imports badges count only the cards with something left. Rolling one
  of a card's operations back puts it back on top. A table left unticked counts as declined; an apply of chosen items
  only, or one that held the spawns back, leaves the card open. Cards made before this are marked at their next
  preview or apply.

- **VMaNGOS is a source, just above the Classic database.** `tools/vmangos_pack.py` makes a pack from the world
  database of VMaNGOS' `db_latest` release (GPL-2.0), patch 1.12 only, in the Classic database pack's format; send it
  on the Imports page (a pack names its source). It answers the same questions (trainers, quest turn-in spells,
  conversation lines, drops and vendors of recipes, holiday spawns) and ranks after Wowhead Classic and before cmangos
  classic-db. Its holiday cards use the realm's own event numbers. The analysis reads both packs.

- **The fishing contest card uses the realm's crew event.** It linked Riggle Bassbait and his crew to event 62,
  which on the realm's calendar (VMaNGOS's) is an AQ War event; the realm's crew event is 40, which already has them.

- **A holiday's spawn is matched against its own holiday only.** A holiday card took any spawn of the same kind
  nearby for its own, so New Year's Eve found its fireworks over Booty Bay already standing: they were Midsummer's.
  A holiday's spawn now stands already only when the server's copy is there while the holiday runs (all year, or
  brought in by the same event), and moves only a spawn its own event brings in. The world data export asks the same.

- **Holiday cards stop adding second copies.** The realm's holiday spawns come from VMaNGOS, and the holiday cards
  from cmangos classic-db, which places the same NPC a few yards off: matched at 3 yards, the cards gave the realm a
  second Silas Darkmoon, Lunar Festival Elders and Love is in the Air perfume sellers. A spawn a card links to a game
  event now stands already when the server has one of its kind within 30 yards (an object within 10), and the server's
  stays where it is; the card's own spawns are still told apart at 3 yards, so a crowd stays whole. The world data
  export uses the same distances for an operation's holiday spawns.

- **Imports apply themselves.** A card is now applied as soon as an import makes it, from a button, an upload, a
  background run (Icy Veins, ForeverChanges) or Wowhead's quest enders, so the next analysis counts it without a
  click on Apply. The card's message says how many rows went in and the history number to roll them back. Spawn
  rows (and the rows keyed by their guid) go in only when the remote console says the worldserver is stopped;
  otherwise they wait on the card for its Apply button. `[imports] auto_apply = 0` (Docker: `FT_IMPORTS_AUTO_APPLY=0`)
  brings back the old way.

- **The newer word wins: every value, and spawns that moved.** An applied card now also replaces the values of rows
  the server already has (every column it gives, by primary key), and moves a spawn of the same kind standing within
  40 yards (`[imports] spawn_move_yards`) to where the card places it, keeping its guid. A row or spawn a more trusted
  source wrote stays as it is. The core's own rows now rank below every source (`[sources] change_core = 0` protects
  them), and a new ledger (`ft_row_origin`) remembers which source last wrote each row. Files imported by hand count as
  `sniff` (WowPacketParser) or `scribe` (ForeverScribe), after the Forever sources and before Classic's.

- **Season of Discovery items Forever kept: Wowhead Classic's item pages.** The Forever client still carries Season of
  Discovery's items, and Forever brought some of them back (the Tarnished Undermine Real), but Wowhead's Forever pages
  often know no source for them yet. For a gap item that is Season's (id 190000 and up, in the Classic Era client), the
  crawler now also reads its Classic item page, right after the Forever page and in the same tier, unless the Forever
  page names a drop, a chest or a vendor. The Wowhead Classic card takes their drops (Dropped by, Contained in), with
  Forever's counts still winning where Forever has them. A Season currency (an item with a *Currency for* tab) is no
  world drop however many bosses drop it: each boss gets a row, as Season of Discovery had it; other Season items many
  creatures drop stay out. Vendors are not taken from Classic: Forever cut those vendors' stock, and Forever's own npc
  pages give it (counted on the card). Stock paid with the Tarnished Undermine Real still has no row: neither the
  client nor its hotfixes (build 70938) hold an extended cost paid in it.

- **Crawl page: list pages and the last page received.** The Forge › Crawl also counts the list pages a whole
  crawl reads first (they were kept but not shown) and says when the last page came, so a crawl that stopped shows.

- **A Wowhead crawl that runs by itself: the Chrome extension.** The Forge › Crawl › *Download the Chrome extension*
  gives a zip with this tracker's address and a key of its own (made once, kept in `data/wowhead-extension.key`, so no
  setting). Loaded in Chrome, it keeps a pinned Wowhead tab, loads the crawler with the tracker's queue after every
  load (`GET api/wowhead-crawler`), opens the tab again after a close or a restart of Chrome (checked every 5
  minutes), and sends each batch to `api/wowhead-push`; no console, no tracker tab. Its popup shows the queue, the
  pace and what was sent, and pauses it. `api/wowhead-push` takes the extension's key as well as `[wowhead]
  push_token`. The crawler sends to the extension's script in its own tab when the extension loaded it.

- **ForeverChanges read from the site, regularly.** foreverchanges.pro was rebuilt and the data files the old pack
  was made from are gone, so the tracker now reads the site itself (`tools/foreverchanges_pull.py`): robots.txt
  obeyed, one request at a time with a pause that grows when the site asks, what the last analysis lacks first, up
  to 1,500 files a visit, then again what is older than two weeks. Every file is kept privately in `data/`, once,
  with its history; each visit's evidence is a snapshot, so its card can be made again from the database. New: the
  quest givers its map names by id, from the rows its players saw, become rows with no name to match, and the NPCs
  and pins of every map are read, not only the two continents'. The Imports page's *Read the site* starts a visit in
  the background, and the container visits every `FT_FOREVERCHANGES_EVERY_HOURS` (24). The `.fcpack` upload and
  `tools/foreverchanges_pack.py` are gone.

- **A checkout finds the server's build as the analysis does.** Without `[server] build` (or `build_file`) in
  config.ini, it takes the client build the realms accept (`auth.realmlist`), as the analysis already did, instead of
  stopping.
- **Checkout: the client's data at any step.** `tracker.py checkout <step>` writes the tables of a build or of a
  day's hotfixes (`70938+1`) as an SQL file for a test realm's hotfixes database: every record that differs from the
  server's DB2 files, removals as `hotfix_data` status 2, one push, exact floats, a manifest of what it holds and what
  it left out (docs/CHECKOUT.md). `--fetch` reads the tables an earlier build was stored without from Blizzard's CDN.
  On the website: The Forge → Checkout makes a step's file in the background and hands it out.
- **The world as of a day.** `world replay --until YYYY-MM-DD` (or `--at <step>`, the day of a step of the timeline)
  leaves out the update files named for a later day, to pair the world with a checkout of the same step.
- **A build read again keeps its hotfix history.** When a key comes out and a build is read again, its kept hotfix
  caches and their steps go over to the new copy (they were only kept for the newest cache).
- **Hotfixes as entries of their own.** Every hotfix cache that differs from the one before is kept, compressed,
  with its build (`data/builds/<build>/hotfixes/`). A build is compared as it stood with its first cache, and each
  later day's hotfixes are an entry of their own on the timeline and in the changelog: what they added, changed or
  removed (`/changes?build=…&hotfix=…`). The double check follows them too (docs/CLIENT.md). Database: `ft_builds.hotfix`
  and `ft_changes.hotfix` (schema 5); the site reads an older analysis as before until the next one runs.
- **The changelog starts at the original game.** Patch 1.12, as Blizzard published it again in 2019 (the client WoW
  Classic launched with), is stored as the build before the first beta, and the first beta build has a page of what it
  added, changed and does not have against it. An item's stats and a spell's effects are compared in a form both
  games have; what a hotfix alone carries is compared as its hotfix stands and never called absent; what the original
  game had and WoW: Forever does not is *Not in Forever* (taken out, or not released yet), not *removed*
  (docs/VANILLA.md). `tracker.py vanilla`, `[client] vanilla`, `FT_CLIENT_VANILLA`; the client check stores it by
  itself.
- **The double check.** At every analysis the chain is replayed: the first thing stored and every build's changes must
  give the newest build, resource for resource (ids from the start, content from the first build on). One line in the
  analysis log, a table on the first build's page.
- **A build's page reads every kind.** The first build against the original game is tens of thousands of lines: each
  kind is read on its own, a filtered kind has pages, and *CSV* gives every line the filters show as a file.
- **Tooltips: ranged weapons.** Bows, guns, thrown weapons and wands take their stats from the ranged column of the
  item level's budget, as the game does. They showed too much before (a wand's +3 Intellect as +4).

## 1.3.3 — 2026-10-20

- **Run again no longer stays disabled.** A background analysis or locator run now always ends with a marker, even when
  Python cannot start or stops early, and a run whose log has been silent for 10 minutes (PC asleep, website stopped) no
  longer counts as running. Before, the button could stay greyed out for up to 30 minutes.
- **ForeverScribe positions are used at once**: after an import that locates creatures, the locator runs by itself, and
  the Imports page links to Spawns, where the ones your server needs show as Ready (*seen in game*).

## 1.3.2 — 2026-10-20

- **ForeverScribe 1.2.0** works with the game's newer addon API (`C_MerchantFrame`, `C_Spell`, `C_CVar`) as well as the
  older one: on clients without the old calls, vendors and casts were not noted. A failing game call is now shown once in
  the chat and kept in the notes. Creatures you target or point at within about 10 yards are located too. `/scribe debug`.
- **ForeverForge 1.2.0**: outside, the window lists the dungeons and raids with creatures to place by hand and a **Go inside**
  button (to the instance's entrance teleport, or any creature already spawned there).

## 1.3.1 — 2026-10-20

- **ForeverScribe 1.1.0 collects only on the official realms.** A client connected to a private server (your own one
  included) uses another `portal` than `us`, `eu`, `kr`, `tw` or `cn`: nothing is noted there. `/scribe on` and
  `/scribe off` force it, `/scribe auto` goes back to that rule; the state shows at login and with `/scribe`.
- **No drop added twice**: an item a creature or chest already drops — directly or through `reference_loot_template`,
  at any depth — is left out of a ForeverScribe import (counted as *drops the server already has*).

## 1.3.0 — 2026-10-20

- **ForeverScribe** (`addon/ForeverScribe`): an addon for the game that notes, through the normal addon API, what
  vendors sell (stock limits, costs), what creatures and chests drop (counted per corpse, skinning and pick pocketing
  apart), who gives and takes quests, and where creatures stand. No character, realm or account name is kept.
- **The Forge › Imports** imports ForeverScribe files like SQL files: vendors, loot (chance = drops ÷ corpses looted),
  quest givers and enders, previewed and rolled back like any import. *Install into the game*, *Download the addon*,
  *Import new notes*.
- **Automatic import**: `ForeverTracker.exe` imports the game's new ForeverScribe notes every minute
  (`tools/collector-sync.php`); `[collector] auto_apply = 1` also applies them.
- **Locator**: creatures seen in game by ForeverScribe use those positions before Wowhead's.
- **Vendors**: the vendor search finds every creature, not only those flagged as vendors, and says when a creature
  does not exist on the server; selling items at a creature (by hand or from an import) adds the vendor flag it lacks,
  with its rollback.
- **Spawning on the server**: a point without a nearby spawn to borrow a height from takes the highest floor up to 40
  yards above the terrain, instead of the terrain itself (which lies under cities such as Stormwind).
- The launcher's French texts are compiled as UTF-8.

## 1.2.2 — 2026-10-20

- **Locator** (`tools/tracker.py locate`, `tools/ft/locator.py`): reads the positions of unspawned creatures and
  objects from the maps of Wowhead's public Forever tooltips.
- **The Forge › Imports** (`tools/wpp-import.php`, `data/imports/`): imports SQL files in WowPacketParser's format.
- Guide `docs/SPAWNS.md`, with a note on heights in places with several levels (Stormwind).

## 1.2.1 — 2026-10-20

- README (English and French) rewritten as a presentation of the whole solution: three-step installation from the
  release package, every feature, and how it works (analysis, Forge engine, positions, spawning, imports).
- Release package `ForeverTracker-<version>.zip`: unzip and double-click `ForeverTracker.exe`.

## 1.2.0 — 2026-10-20

- **Imports** (The Forge › Imports, `tools/wpp-import.php`): imports SQL files in WowPacketParser's format: spawns
  with their positions, new creatures and objects, loot, vendors, quests,
  quest givers and enders, gossip. Only `INSERT` rows are read; rows the server has are left out; spawns get new
  guids and a spawn already standing within 3 yards is left out with its addon; a creature whose `LootID` is 0 gets its
  loot table; unknown columns and tables are dropped; one transaction, exact rollback in the history.
- **Items tab**, first in the Forge: every item nobody can get, with the reason and its imported sources (drop, chest,
  vendor, quest reward), the filter *Found in an import*, and **Apply imported sources** for the selection.
- The Forge engine gains *fill* operations (set a column only where it is still 0, with its rollback), and tables without
  a primary key are matched on their first index.

## 1.1.1 — 2026-10-20

- **`ForeverTracker.exe`**: the launcher is now a real Windows program (with its icon), built from
  `tools/launcher/ForeverTracker.cs` by `build-exe.ps1` with the C# compiler Windows ships. It replaces the
  PowerShell launcher; `ForeverTracker.bat` starts it. `--check` prints what it finds.
- README: install in two minutes, what is new in 1.1, new screenshots (launcher, setup wizard, spawns, SQL preview).

## 1.1.0 — 2026-10-20

### Installation
- **Launcher** (`ForeverTracker.bat`, Windows): finds a PHP 8 with `mysqli` (writing an ini for portable PHP builds)
  and Python, starts and stops the website, opens the setup wizard on the first run, updates the data.
- **Setup wizard** (`/setup`): finds the server by its `worldserver.conf` (databases, data folder, remote console,
  `mysql` client), tests the databases and creates ForeverTracker's, finds the game client (`.build.info`), extracts
  its DB2 files with the core's `mapextractor` or uses the server's, creates the administrator, writes `config.ini`
  and runs the snapshot, the analysis and the locator with live progress. Local requests only before the first
  configuration, administrators afterwards.

### The Forge
- **No more "duplicate entry" errors.** Fixes are stored as operations (table, columns, rows, key columns). Applying
  merges the whole selection, inserts every row once, leaves out the rows that already exist on the server at that
  moment, and saves a rollback that deletes exactly the inserted rows. Applying twice, overlapping fixes (a spell that
  is both a class spell and a recipe, shared durations or triggered spells) and rows added by hand are all safe.
  Preview shows new, existing and shared rows.
- `tools/forge-check.php` (replaces `check_fixes.py`) dry-runs every fix with the website's own engine, all together
  and one by one.

### Locator and spawns
- **Locator** (`tools/tracker.py locate`, or *Run* in the Forge): finds the creatures and world objects the server
  knows but never spawned although quests (givers, enders, objectives), vendors, trainers, loot or dungeons need
  them, and their official positions from Wowhead's Forever tooltips (cached, polite), converted to world
  coordinates with the client's `UiMap` tables (a few yards outdoors).
- **The Forge › Spawns**: spawn them on the running server through the remote console (exact height, live,
  undoable), in the database (worldserver stopped), with the ForeverForge in-game addon, or as GM commands.
- **Core module** `core/forge_commands.cpp`: `.forge spawn npc|go`, `.forge delete`, `.forge height`,
  `.forge version`, usable from the console, the remote console and in game. The server computes the ground height
  from its maps and vmaps, buildings included.
- **ForeverForge addon** (`addon/ForeverForge`): `/forge` spawns the exported queue through TrinityCore's addon
  command channel, in place with the core module or by travelling with `.go xyz` without it; *Spawn here* for
  bosses and dungeon creatures.

### Other
- Background jobs run Python in UTF-8 mode, and JSON answers survive console-encoded logs.
- New `config.ini` sections: `[console]`, `[client]`, `[wowhead]`. Snapshots now store `UiMap`,
  `UiMapAssignment` and `UiMapGroupMember`.

## 1.0.1 — 2026-10-19

- The analysis stops with a clear message when `[server] root` / `dbc` do not lead to the server's `.db2` files,
  instead of reporting nearly everything as unknown to the core. When the configured folder has no DB2 file but a
  locale folder next to it does (`data/dbc/enUS` instead of `data/dbc/frFR`), that folder is used with a warning.
- When neither `[server] build` nor `build_file` is set, the server build is taken from `auth.realmlist`.
- Warnings when `[server] maps` or `vmaps` do not exist.
- Overview: clear messages when the server build is unknown or when most resources look unknown to the core,
  instead of "build 0".

## 1.0.0 — 2026-10-19

First public release.

- Official content of the WoW Forever client, read from its DB2 files with the layouts of your core: 13 resource
  types (dungeons and raids, bosses, zones, quests, items, spells, talents, recipes, mounts, pets, toys,
  achievements, flight points).
- Changelog of every stored client build, field by field, with Blizzard's patch notes.
- Availability checks against a TrinityCore-based server: core data, spawns, loot (with reference loot),
  vendors, trainers, quest givers and enders, objectives, instances, bosses and scripts, graveyards, flight masters.
- In-game tooltips for every resource, computed with the core's item formulas and a spell description renderer.
- The Forge: core data (hotfixes), trainers, vendors and instances, with SQL preview and download, transactions,
  history and rollback; `tools/check_fixes.py` dry-runs every fix.
- Work list by priority with CSV export, global search (`Ctrl K`), catalogues with filters.
- English and French interface and data, dark and light themes, phone layout.
- Administrators: game masters (Battle.net SRP6 login) or local accounts; can run inside another website.
