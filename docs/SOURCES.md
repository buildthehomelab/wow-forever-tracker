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
- **Quests**: only quests the server has no giver (or no ender) for; creatures and objects the server has.
- **Trainers**: at the trainers the server has for that creature (`creature_trainer`). A class spell needs a level:
  the source's, else the server's other trainers', else Wowhead's *"Requires level N"*. The ranks a spell needs: the
  source's, else the server's other trainers'; a higher rank with neither is left out (a talent's later rank would be
  sold to anyone). Professions keep their skill line and rank; a profession entry whose skill is unknown is left out.

Each card lists what was left out and why, and carries the source's licence in its name.

## Running them

- The Forge › Imports: *Import EG Link*, *Import ForeverDB.net*, *Import Icy Veins*, *Import NorgannonDB*.
- `php tools/source-import.php norgannondb|eglink|foreverdb|icyveins`.
- Icy Veins runs in the background (about an hour the first time); its last log line shows on the Imports page. Its
  answers are kept in `data/icyveins/` and asked again after 14 days (7 for "not found"): it is a young project and
  keeps growing. `[icyveins] max` (`FT_ICYVEINS_MAX`) caps the lookups of one run; the next run goes on.

Run the analysis again after applying an import: what it filled no longer counts as a gap, so the next import of
another source only brings what is still missing.
