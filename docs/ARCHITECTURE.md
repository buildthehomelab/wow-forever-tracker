# How it works

```
official client ──mapextractor──► data/builds/<build>/<locale>/*.db2      (tools/tracker.py snapshot)
                                              │
server DB2, world, hotfixes, auth, maps ──────┤
                                              ▼
                               tools/tracker.py analyse
                   content.py · server.py · rules.py · tooltips.py · forge.py
                                              │
                              ft_* tables of the tracker database
                                              │
                         public/index.php ──► app/ (pages, API, Forge)
```

## Analysis (`tools/`)

| File | |
|---|---|
| `tracker.py` | Command line: `snapshot`, `analyse` |
| `ft/db2.py` | WDC5 reader: dense and sparse records, bit-packed, pallet and common data, copy tables, relationship columns, encrypted sections (counted, skipped) |
| `schema/db2-schema.json` | Column names and layouts of every DB2 table, generated from the core's `DB2Metadata.h` / `DB2LoadInfo.h` by `make_db2_schema.py` |
| `ft/content.py` | Official content of one build (13 resource types) and build-to-build diffs |
| `ft/server.py` | What the server provides: its DB2 files, hotfix rows, spawns, loot, vendors, trainers, quests, instances, map files |
| `ft/rules.py` | Availability checks of every resource, with English and French details |
| `ft/summons.py`, `world/summoned.json` | What is in the game without a spawn row: the database's summons, and the core's C++ scripts read once by `make_summoned.py` |
| `ft/bosses.py` | Which client encounters are a boss of their own, and how each is found on the server |
| `ft/tooltips.py`, `ft/spelltext.py` | In-game tooltips, with the core's item formulas and a renderer for spell description templates |
| `ft/forge.py` | Fixes: SQL to apply and to roll back |
| `ft/output.py` | Writes everything into the tracker database, swapping the tables atomically |
| `ft/sqlio.py` | Database access through the `mysql` command-line client (no Python driver) |

Item values follow the core: stats come from `RandPropPoints` and `StatPercentEditor`, armor from
`ItemArmorQuality`, `ItemArmorTotal` and `ArmorLocation`, weapon damage from the `ItemDamage*` tables. On the
reference server, 1,709 of 1,714 compared items match the core's own item export exactly (the other
five differ by one or two points on a stat, most likely server-side overrides).

An item is *obtainable* when one of its sources is active: loot of a spawned creature or object (through reference
loot), pickpocketing, skinning, fishing, a spawned vendor, the shop, a container that is obtainable, the reward of
a quest that can be done (its reward, or the item its giver hands over on accept), or a craft that can be learned.
Quests, items and crafts depend on each other, so the analysis repeats until nothing changes.

*Spawned* includes what something brings in without a spawn row: Reginald Windsor walks into Stormwind when his quest
calls him, and Darkmaster Gandling appears when his six lieutenants are dead. The world database knows part of it (a
SmartAI summon, a summon group, an event script, a summoning spell); the core's C++ scripts know the rest, and
`tools/make_summoned.py /path/to/core` reads them into `tools/world/summoned.json`: the entries a `SummonCreature` or
`SummonGameObject` call names, and which creature each instance script counts as which boss encounter. Run it again
when the core moves to a commit with new scripts (the file records the commit it was read from). A summoned creature
counts for its loot, its stock, its quests and kill objectives, never as a trainer, and the locator does not offer
to spawn it.

A quest also has a *Quest text* check: the giver's text (description or objectives) for a quest taken from a giver,
and the turn-in text (`quest_offer_reward`, or `quest_request_items` for a quest that asks for items) for one handed
in to someone. It weighs little: a quest that can be done without its words reads Incomplete near 90%, not missing.

## The world build (`tools/ft/layers.py`, `tools/ft/replay.py`, `tools/ft/facts.py`, `tools/ft/luadata.py`, `tools/ft/resolve.py`, `tools/ft/export.py`, `tools/ft/quests.py`, `tools/ft/npcs.py`, `tools/ft/world.py`)

| File | |
|---|---|
| `tools/world/layers.json` | The layers and every source: layer, licence, credit, use (`public`, `private`, `reference`), witness group, how its newest version is found |
| `ft/layers.py` | Reads and checks that registry; counts independent witnesses; says whether a row may be published; looks up and locks each source's version. No configuration, no database: tested alone (`tools/tests`) |
| `ft/replay.py` | Rebuilds the server's world in a scratch database (release dump, then update files in the updater's order) with triggers that log every row change under the file being applied; `why()` reads a row's origin back. Refuses an account that can write outside the scratch database, and reads each file before it runs |
| `ft/facts.py` | What each source says, in one shape (`gives`, `sells`, `drops`, `quest` ...): one reader per source (EG Link, QuestieDB, RestedXP guides), the statements that replace a source's facts in `ft_world_facts`, a summary. No configuration, no database |
| `ft/luadata.py` | Reads the Lua data files addons ship as plain values: tables, strings, numbers; a name stays a name, a table that holds code is not read |
| `ft/resolve.py` | The rules: weighs the facts against the replayed world (`seen-live`, `trusted-source`, `two-witnesses`, `one-claim`, `removed-by-hand`, `item-starts`, `record-seen-live`, `record-not-live`, `looks-internal`, `only-claimed`) and stores what the world should hold and does not in `ft_world_decisions`, each decision with its rule, its witnesses and what it still needs. An NPC the world lacks is a decision too: ready only with a record of it from the live game, and what waits for a ready NPC comes with it |
| `ft/export.py` | The export: writes the decisions that are ready as an update file for the data repository (and a second one for what may not be published), each row guarded, recorded in the server's ledger and listed in a manifest; tries the file twice on the replayed world inside a transaction it rolls back before writing it |
| `ft/quests.py` | A quest's rows from the record the server sent to a client: the measured column mapping, what is a constant, what is left to the table's default. No database |
| `ft/npcs.py` | An NPC's template rows from the record the server sent to a client; its level from a source that states it; its faction a stand-in by the side it is friendly to. No database |
| `ft/world.py` | The `world` commands of `tracker.py` |

See [WORLD-BUILD.md](WORLD-BUILD.md).

## Tables

| Table | |
|---|---|
| `ft_builds` | Tracked client builds |
| `ft_entities` | One row per resource: names, status, score, checks (JSON), data (JSON) |
| `ft_changes` | Changelog rows |
| `ft_tooltips` | Tooltip data per resource (JSON) |
| `ft_fixes` | Forge fixes with their SQL |
| `ft_meta` | Analysis date, builds |
| `ft_notes` | Blizzard's patch notes (kept across analyses) |
| `ft_forge_log` | Forge history (kept across analyses) |

## Website (`app/`, `public/`)

Plain PHP, no framework and no build step. `public/index.php` routes every address; pages live in `app/pages`,
JSON endpoints in `app/api` (`tooltip`, `search`, `forge`). `public/assets/js/tooltip.js` renders the tooltips from
their JSON data; `app.js` handles the command palette (`Ctrl K`), the filters and the Forge. Every text exists in
English and French (`t('English', 'Français')`).

## Locator, spawns and imports

| Part | Role |
|---|---|
| `tools/ft/locator.py` | Candidates (unspawned templates the content needs), Wowhead positions, clustering, height hints from the nearest spawns; writes `ft_spawns` (swapped atomically) |
| `tools/ft/wowhead.py` | Wowhead's Forever tooltip service: one request at a time, a pause, every answer cached in `data/wowhead/` |
| `tools/ft/geo.py` | Zone percentages (AreaTable zone, floor, x %, y %) to world positions with `UiMap`, `UiMapAssignment` and `UiMapGroupMember` |
| `app/imports.php`, `tools/wpp-import.php` | Imports of WowPacketParser SQL files: streaming statement reader, INSERT parser, guid remapping, merge as Forge operations (tables `ft_imports`, `ft_import_items`) |
| `app/spawns.php` | Spawn plans; the remote console client (RA); the four modes (server, database, addon, GM commands); the addon export |
| `core/forge_commands.cpp` | Worldserver module: `.forge spawn / delete / height / version` |
| `addon/ForeverForge` | In-game addon: runs the exported queue through TrinityCore's addon command channel; *Spawn here* in dungeons |
| `addon/ForeverScribe` | In-game addon: notes vendors, loot (per source GUID), quest givers and enders, and where the player stood near creatures, into its SavedVariables |
| `app/collector.php`, `tools/collector-sync.php` | ForeverScribe files: a reader of Lua SavedVariables, the notes turned into import tables (`npc_vendor`, loot, quest starters / enders), positions into `ft_collected` (read by the locator), the sync of changed files (`data/collector-state.json`) that the launcher runs every minute |

## The Forge engine

Fixes are stored in `ft_fixes.detail` as operations `{db, table, columns, match, rows[, hash]}`. `forge_build()`
(`app/forge.php`) merges the operations of a selection (rows unique on their `match` columns), `forge_plan()` asks the
databases which of those rows exist now and keeps the others, then writes the INSERT statements and a rollback that
deletes the inserted rows by primary key. Two operations change existing rows instead: `fill` sets a column where it is still 0 (a creature's `LootID`), `bits` ORs a flag into a column (the vendor flag of `npcflag`); their rollbacks undo exactly that. `forge_commit()` runs them in one transaction per database and records
the operation in `ft_forge_log`. The database spawn mode builds the same operations for `creature` / `gameobject`.

## Installation

| Part | Role |
|---|---|
| `ForeverTracker.exe` (`tools/launcher/ForeverTracker.cs`, built by `build-exe.ps1`) | Windows launcher: finds PHP (writes `data/php-launcher.ini` for portable builds) and Python, starts and stops PHP's built-in server, opens the wizard; `--check` prints what it finds |
| `app/setup.php`, `app/pages/setup.php`, `public/assets/js/setup.js` | Setup wizard (`/setup`): detection of servers (`worldserver.conf`) and clients (`.build.info`), database test, `config.ini` writer, background pipeline (extract, snapshot, analyse, locate) logged in `data/setup.log` |