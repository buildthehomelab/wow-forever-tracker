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

**One card per source.** A card is built against the gaps and the server as they are at that moment, so a new card of
a source says everything its earlier ones said that is still true. Making one therefore forgets that source's earlier
cards nothing was ever applied from (also when the new one turns out empty: nothing is missing any more). A card you
applied, in whole or in part, stays, rolled back since or not; the history keeps every operation's SQL and rollback
whatever happens to its card.

## Running them

- The Forge › Imports: *Import EG Link*, *Import ForeverDB.net*, *Import Icy Veins*, *Import AtlasLoot*, *Import NorgannonDB*.
- `php tools/source-import.php norgannondb|eglink|foreverdb|icyveins|atlasloot`; `atlasloot --if-new` does nothing
  when the newest CurseForge file is the one imported last. One run of a source at a time: a second one says the
  import is already running and exits 3. `--log` writes the run's lines to `data/source-<source>.log`, the file the
  Imports page reads, instead of printing them.
- AtlasLoot by itself: the container checks CurseForge every `FT_ATLASLOOT_EVERY_HOURS` (6; `0` = never), 15 minutes
  after start and never while an analysis runs, and makes a card when a new version is out. Its last log line shows on
  the Imports page. The last three downloads stay in `data/atlasloot/`. A new analysis alone makes no new card: press
  *Import AtlasLoot* after one.
- Icy Veins runs in the background: several hours the first time (one lookup per gap item, quest and trainer, two a
  second). Its last log line shows on the Imports page, a new one every 20 lookups. Its
  answers are kept in `data/icyveins/` and asked again after 14 days (7 for "not found"): it is a young project and
  keeps growing. `[icyveins] max` (`FT_ICYVEINS_MAX`) caps the lookups of one run; the next run goes on.
  - **A restart** stops the run. The container goes on with it at its next start, from the cache, once MySQL answers
    and no analysis runs (`FT_ICYVEINS_RESUME=0`: only the button does). Without Docker, press the button again.
  - **When Icy Veins does not answer** (an outage, a block, no network), nothing is cached for that lookup and the run
    waits longer before each next one: 1, 2, 4 … 60 seconds. After 20 lookups in a row without an answer (about a
    quarter of an hour) it stops, makes no card, and its last log line says which lookup failed. Press the button
    again once Icy Veins answers: the run goes on from its cache.

Run the analysis again after applying an import: what it filled no longer counts as a gap, so the next import of
another source only brings what is still missing.
