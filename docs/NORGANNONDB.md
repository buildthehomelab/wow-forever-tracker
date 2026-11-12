# NorgannonDB import

The analysis says **what** your server lacks, measured against the official client and Wowhead's Forever database
(items Wowhead marks as Season of Discovery leftovers, or does not know, count as internal). It cannot say **where**
those things come from: drops, vendors, quest givers and trainers are server data that no client file holds.

[NorgannonDB](https://github.com/zmarotrix/NorgannonDB) (GPL-3.0) fills that in: an open WoW Forever database built
from QuestieDB, pfQuest, WoW Forever's own tables and what its players saw with the NorgannonDB Collector. The Forge
reads it from a pinned commit (downloaded into `data/norgannondb/<commit>/`, never bundled with the tracker) and turns
it into an **import** like a WowPacketParser file or ForeverScribe notes: preview, *Apply what is missing*, history,
rollback, and [export to a data repository](DATA-REPO.md).

## What it imports

Only what fills a gap of the **last analysis** (run it again first when the server changed):

| Rows | When |
|---|---|
| `npc_vendor` | items players cannot get (and not internal) that NorgannonDB says a creature sells. A count is a limited stock, restocked hourly. The price is the item's own, unless another vendor of the server sells it for items or currencies (then that `ExtendedCost`) |
| `creature_loot_template`, `gameobject_loot_template` | the same items, where NorgannonDB knows the drop **chance** (a chance of 0, "drops, unknown chance", is left out). Into the creature's own loot table (its `LootID` is filled where it is 0) or the chest's; an item the table already gives, references included, is left out |
| `creature_queststarter`, `gameobject_queststarter` / `..._questender` | quests the server has no giver (or no ender) for. Quests NorgannonDB hides (not obtainable) are left out |
| `trainer_spell` | spells NorgannonDB players saw a trainer teach (`training` for classes, `recipes[].trainers` for professions), at the trainers the server has for those creatures (`creature_trainer`), with their price, the ranks they need first and, for professions, the skill. A class spell needs a level: NorgannonDB's, else the one other trainers of the server ask; without one it is left out (a level of 0 would let anyone learn it) |

The import card lists what was left out and why (`loot_chance_unknown`, `trainer_not_on_server`, ...).

With `[forge] trainer_guess = 0` (`FT_FORGE_TRAINER_GUESS=0`) the Forge stops guessing trainer spells from the
client's skill lines (which offers talents, triggered effects and quest-taught specializations): trainer spells then
come from imports only.

## Running it

- The Forge › Imports › **Import NorgannonDB**, or `php tools/norgannon-import.php`.
- `[norgannondb] commit` (`FT_NORGANNONDB_COMMIT`) picks another NorgannonDB commit; empty is the one this tracker was
  tested with.

Rows exported from it to a data repository carry NorgannonDB's data: credit it there (GPL-3.0, with QuestieDB, pfQuest
and DungeonJournal as NorgannonDB's NOTICE lists).
