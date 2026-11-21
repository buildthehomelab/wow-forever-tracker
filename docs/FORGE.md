# The Forge

The Forge creates what your server lacks from the official client data. It is reserved to administrators.

![The Forge](screenshots/forge.png)

It has four parts:

- **Items**: every item players cannot get on your server, with the reason, and its sources when an imported file
  has them (drop, chest, vendor, quest reward). Apply the imported sources, or sell the item at a vendor you choose.
- **Fixes**: rows to add to the `hotfixes` and `world` databases (core data, trainers, instances). Below.
- **Spawns**: creatures and world objects the server knows but never spawned, placed at their official positions.
- **Imports**: world data files in WowPacketParser's SQL format, merged safely.

Spawns and imports are described in [SPAWNS.md](SPAWNS.md).

### Why most items have no source

Drops, vendor lists and quest rewards are server data: the game client never contains them, so the analysis can only
say that an item has no source on your server. Their sources come from the ForeverScribe addon's notes and imported world data files (WowPacketParser's
SQL format), or from your own choice (a vendor). An item whose source exists but is inactive (a creature or a vendor
that is not spawned, a recipe nobody teaches) is fixed from *Spawns* or *Trainers*.

## Fixes

| Tab | When it is offered | What it writes | Takes effect |
|---|---|---|---|
| Core data | An item, spell, recipe, talent, mount, pet, toy or achievement exists in the client but not in the server data | The official records into the `hotfixes` database (`item`, `item_sparse`, `spell_name`, `spell_effect`, `mount`, `achievement`, `criteria_tree`…), plus the records they depend on that the server lacks (item effects and their spells, appearances, durations, ranges, radiuses, categories, triggered spells). French texts go to the `_locale` tables. | Restart of the worldserver |
| Trainers | A class or profession spell is known to the core but nobody teaches it, and trainers of the same skill line are spawned | `trainer_spell` rows for those trainers: level (or skill rank) of the spell, previous rank as requirement, price from the spells around it | Restart of the worldserver |
| Items › Sell at the vendor | An item has no source (no loot, vendor, quest, craft or shop) | `npc_vendor` rows for the creature you choose (unlimited stock, no extended cost); the vendor flag (`npcflag` 128) is added when it lacks it. The search finds every creature by name or entry (the number of the Wowhead link) | `.reload npc_vendor` or restart |
| Items › Apply imported sources | An imported file has the item's loot, vendor or quest | Those rows, merged like an import | Restart |
| Instances | A dungeon or raid has no `instance_template` row | The row, with its parent map and no script | Restart |

Talents are never offered at trainers (every rank of a talent is bought with talent points), and a higher rank always
requires the rank before it, so a talent's later ranks only go to players who took the talent. Spell ids listed in
`[forge] trainer_skip_ids` are never offered either. Spells that Blizzard teaches with an item (recipes, books, runes) are not offered at trainers: sell or drop the
item instead (*Vendors*). Hunter pet abilities are learned by taming and pet training, never at trainers.

The *Push to clients* option of the *Core data* tab also adds `hotfix_data` rows, which send the records to
connected game clients. It is not needed when players use the official client of the same build.

## How a fix is applied (no "duplicate entry" errors)

The analysis does not store ready-made SQL. Each fix holds **operations**: a table, its columns, the rows to add, and
the columns that identify a row (`ID` for hotfix tables, `TrainerId` + `SpellId` for `trainer_spell`, `map` for
`instance_template`, `entry` + `item` + `ExtendedCost` + `type` for `npc_vendor`). When you preview or apply a
selection, the website:

1. **merges** the operations of every selected fix. Two fixes often need the same rows: a spell that is both a
   class spell and a recipe, two spells that share a duration, a range or a triggered spell. Each row is kept once;
2. **asks the server** which of those rows already exist, at that moment, and leaves them out. A row added by hand,
   by an earlier Forge operation or by a core update is never inserted twice. Hotfix records are matched by `ID`,
   whatever their `VerifiedBuild`;
3. inserts the remaining rows in **one transaction per database**: if a statement fails, nothing is kept;
4. saves a **rollback that deletes exactly the inserted rows**, by primary key.

So applying the same selection twice, selecting overlapping fixes, or applying after a change on the server is
safe: the second time the Forge answers that everything is already there. The preview says how many rows are new,
already present or shared by several fixes.

## Applying

1. Select fixes (filters: type, *New in Forever*, *Internal / test*, name or ID).
2. **Preview SQL** shows the exact statements and their rollback, computed against the live databases;
   **.sql** downloads them, to apply by hand.
3. **Apply** asks for a confirmation, then runs them as described above.
4. The operation, its SQL and its rollback are saved in the history (`ft_forge_log`) **before** the change is
   written, as *not confirmed*, then marked *applied* (or *failed*: nothing was kept). A change can therefore never
   be on the server without its rollback in the history.

A resource page lists its own fixes too, with *SQL* and *Apply* buttons.

## Rolling back

*History* lists every operation with its SQL. **Roll back** runs the saved rollback in a transaction: it deletes the
rows the operation inserted, and nothing else. Spawns made through the remote console are rolled back with
`.forge delete` (see [SPAWNS.md](SPAWNS.md)).

An operation still *not confirmed* after 10 minutes was interrupted: the website stopped, or lost its database, while
applying it, and nobody recorded whether the change was written. It does not count as applied (the lists do not grey
its fixes out, the data repository export leaves it out). Check the server with its SQL, then **Roll back**: the
rollback only removes what the operation would have added, so it is safe whether the change was written or not.

## Checking every fix

```bash
php tools/forge-check.php [hotfix|trainer|instance] [--each]
```

plans every fix with the website's own engine against the databases as they are now, applies them all as one
selection (what *select all* does), runs the rollback, checks that it removed exactly the inserted rows, and rolls
everything back. Nothing is kept. `--each` also checks every fix alone, so a failure names its fix. Use the same
PHP as the website (for example `php -c php.ini tools/forge-check.php`). Every table the Forge writes must be InnoDB.

## After applying

Restart the worldserver, then run the analysis again (*Run again* in the Forge) to refresh the statuses. Fixes
applied since the last analysis are greyed out in the lists.

## Wowhead as the reference

With Wowhead lookups on (`--wowhead`, `FT_WOWHEAD=1`; *Run again* too when `[wowhead] analyse = 1`), the analysis asks
Wowhead's public Forever tooltips about what the server lacks:

- **Items**: those Wowhead marks *"Added in Season of Discovery. May not be in WoW: Forever."* become internal. Those
  it does not know stay listed with a note: Forever keeps content encrypted for players to discover, and Wowhead learns
  it later. A "does not know it" answer is asked again after `[wowhead] recheck_days` (7).
- **Creatures** (*Checks*): the level and rank of spawned quest givers, enders and targets, elites, rares and bosses,
  compared with Wowhead's "Level 30 Humanoid (Normal)". A level counts as different only when the two
  ranges do not meet: Wowhead's range spans every spawn and phase it saw, so our 62 against its 61-62 is no finding.
  Tick a difference on the *Checks* page to give the creature Wowhead's value: the rank is
  `creature_template.Classification`, the level both ends of `creature_classic_level`. It goes through the Forge like
  any fix (SQL preview, one transaction, history, rollback, *Data repo .sql*). Nothing is ticked for you: Wowhead's
  tooltip is sometimes the wrong one (a level 1 that stands for "not known"). A level one side does not state (a
  boss's "??") cannot be taken.
- **Trainer levels**: NorgannonDB trainer rows without a level take the spell's "Requires level N".
- **Quest enders** (*Imports › Import Wowhead quest enders*): for quests without an ender, the NPC Wowhead's quest
  summary sends the player back to, when exactly one spawned creature has that name. An import card, reviewed before
  it is applied.

## Whose side a creature is on

A creature's faction decides whom it helps and whom it attacks, and whose reputation lowers a vendor's prices. No
client table holds it, so the analysis never compared it with anything. Players' recordings of the live game (EG
Link, the commit *Import EG Link* last read) do not state the faction either, but they state what follows from it:
how each side's players saw the creature (hated to exalted) and which side it served (a vendor's window, a quest, a
flight). The *Checks* page lists the spawned creatures where the server and the live game cannot both be right:

| Tab | The server says | The live game says |
|---|---|---|
| *Faction* | its faction attacks a side | players of that side saw it neutral or friendly, or were served by it |
| *Faction* | its faction is a side's friend | players of that side only ever saw it hostile |
| *Shown to one side* | only one side sees it (a phase or a spawn group behind a team condition, or a visibility condition) | players of the other side saw it or were served by it |
| *Vendor reputation* | a vendor's faction is a general one (the same to both sides, no reputation behind it), so no reputation discount applies | the recordings show it selling to one side only |

*Vendor reputation* is the weakest of the three: the other side may simply not have come by. A vendor of one side's own
faction that has no reputation (the Revantusk trolls) is not listed: that is Blizzard's choice, and it gives no
discount on live either.

What it leaves alone, on purpose:

- **Neutral against friendly.** That depends on the reputation the player who recorded it had earned.
- **A faction whose reputation players earn.** A Gelkis centaur is friendly to the player who earned it and hostile to
  the next one, so what one player saw says nothing (the first list on a whole world named six of them). Such a
  faction is compared only where a side's standing is fixed at the bottom, as the Horde's is with Stormwind.
- **A side that never recorded a creature.** Nobody of that side went there, or looked. So a creature the server
  shows to everyone that only one side should see (two versions of a starting zone, one per side) is **not** found
  this way: the recordings can show that a side saw something, never that it could not.
- **Creatures nobody spawned** (a warlock's demon, a totem: its side is its master's) and a beast players only saw
  friendly (somebody's pet), unless it also served them.

Nothing can be ticked: no source states which faction is the right one. The note names the server's faction and what
each side saw, which is usually enough to pick the right faction by hand. `tools/ft/sides.py` holds the rules. Without
an EG Link recording in `data/eglink` the check is not made, and the analysis log says so.

## What the server has that the live game does not (Extras)

Every other page looks for what is missing. *The Forge › Extras* looks the other way: rows an import brought in that
live Forever never had. Each finding needs a witness that something else stands in its place; that nobody recorded a
thing is never enough on its own. The analysis fills it (`tools/ft/extras.py`, table `ft_world_extras`); nothing is
changed from the page.

| Tab | The server has | The witness |
|---|---|---|
| *Old twin* | a creature the live server never sent a record of | the live server sent the record of another entry with the same name (EG Link, live builds). Usually the Classic copy of a creature Forever remade, as the Steelgrill's Depot mechanostriders 12363-14553 beside 267683-276736. A name proves nothing on its own (chickens, credits, snakes), so each spawn is weighed: one within 15 yards of a spawn of the live entry, on its map, in its phase and world events, is that creature twice and is listed by its guid; the entry's other spawns are listed together and left alone |
| *Stacked* | two spawns of one name on one spot (creatures 1 yard, objects 0.3), same phase, same world events, neither pooled | the spawn to keep: a live entry's, else the oldest guid |
| *Crowded* | far more spots of a creature (2x + 3) than ... | ... the live game shows around that place, and than Classic had (QuestieDB's converted Classic base, `data/Forever/foreverNpcDB.lua` of the pinned release). What live shows is the most spots any one witness gives: Wowhead's Forever map pins, QuestieDB's Forever player traces and hand fixes, EG Link's sightings (sightings within 10 yards are one spot: one mob is seen again and again). Wowhead merges spots that stand close, so a zone's mobs run two to ten times its marks; the note names every witness's count. Spots, not rows: copies on one spot (a pack) count once, and a pool member counts as its share of the pool's spot (a VMaNGOS random-entry spot is five rows of which one stands). On Everlake 2026-11-21 Wowhead and Classic alone took the tab from 171 to 6 |
| *Invented* | a creature, or any entry from 1,000,000 up | a creature: nothing else knows it (not in the client, in no EG Link recording, Wowhead (Forever) answers "not found"). An entry from 1,000,000 up is the server's own (Blizzard's ids stay below): a stand-in an import made where the real data was missing, listed so the real entry can be found. Objects below 1,000,000 are not judged: Wowhead lists only objects players use, not the chairs, lamps, doors and holiday props (on Everlake, 3,550 of 3,638 findings before this rule were such objects) |
| *Quest giver* | an NPC or object giving or taking a quest | live players saw only others give or take it (weaker: a second giver may not have been recorded) |

*Removals as SQL* writes the stacked copies and the old twins listed by guid (the ones within 15 yards of a live
spawn) as an update file to review. The file weighs each twin again when it runs: a spawn goes only while it still
holds its old entry and a spawn of the live entry still stands within 15 yards on its map. Twins whose live entry
stands elsewhere are not removed (the live game may well have both places); twins whose live entry the server does
not spawn need the spawn moved to the live entry instead, by hand. Nothing on the *Crowded*, *Invented* and *Quest
giver* tabs is ever in the file: an invented entry may be a real one Wowhead has not shown yet, and removing it would
leave a hole until its real data is in. Wowhead is asked at most 3,000 times per analysis for these (the rest waits for the next run); without an EG Link
recording in `data/eglink` the check is not made.

## Filling the gaps from open data

NorgannonDB, EG Link, ForeverDB.net and Icy Veins each become an import aimed at the analysis' gaps, under the same
rules: see [SOURCES.md](SOURCES.md).

## Filling the gaps from NorgannonDB

The Forge › Imports › *Import NorgannonDB* turns the open NorgannonDB database into an import aimed at the analysis'
gaps: drops and vendors for items players cannot get, givers and enders for quests that have none, and the spells its
players saw trainers teach. See [NORGANNONDB.md](NORGANNONDB.md).

## Taking a fix to another realm

Tested on a test realm and good for the live one? *History* exports any applied operation as a world update file for
a data repository, safe to run twice: see [DATA-REPO.md](DATA-REPO.md).

## Troubleshooting

| Message | Meaning |
|---|---|
| *N fix(es) come from an older analysis* | The fixes were computed by ForeverTracker 1.0. Run the analysis again. |
| *Everything selected is already on the server* | Nothing to do: the rows exist (applied before, or added by hand). |
| *Table x.y does not exist on this server* | Your core has no such hotfix table (older or newer core). Those rows are left out; the rest is applied. |
| A MySQL error during *Apply* | Nothing was kept (transaction). The error and the SQL are in the history; `forge-check.php --each` finds the fix. |

## Read-only SQL (Query)

*The Forge › Query* runs one statement on a database the tracker reads, for checks no page shows (how far a spawn
stands from another, which rows a file would touch). It offers the `world`, `hotfixes` and `tracker` databases of
config.ini's `[database]` section; Everlake's `world` is the test realm's.

Nothing can be written from it. Four locks, each enough alone:

1. **An account that may only read.** Queries never run as the tracker's own MySQL user (which writes the test
   realm's world for the Forge), only as `[database] query_user` / `query_password` (Docker: `FT_DB_QUERY_USER`,
   `FT_DB_QUERY_PASSWORD`). Before every query the page reads that account's grants back (`SHOW GRANTS`); anything
   but SELECT, SHOW VIEW or USAGE (a write right, a role, a proxy, GRANT OPTION) and it runs nothing. Without the
   account the page runs nothing either. Give it `GRANT SELECT ON <db>.*` on the databases it offers, nothing more.
2. **Only statements that read.** The first word, after any comments, must be SELECT, WITH, SHOW, EXPLAIN, DESCRIBE
   (DESC), TABLE or VALUES. Executable comments (`/*! ... */`), `INTO OUTFILE` / `INTO DUMPFILE` and locking reads
   (`FOR UPDATE`, `FOR SHARE`, `LOCK IN SHARE MODE`) are refused.
3. **A read-only transaction.** One statement, on its own connection, inside `START TRANSACTION READ ONLY`, rolled
   back after.
4. **Limits.** 30 seconds (`max_execution_time`) and at most 5,000 rows. Each query is written to the web server's
   error log.

In Docker, with `FT_DB_QUERY_USER` set and no `FT_DB_QUERY_PASSWORD`, the entrypoint makes the password from
`FT_DB_PASSWORD`: the first 64 characters of `sha256("query:" + FT_DB_PASSWORD)`, as Everlake's `tracker-setup.sh`
does when it creates the account, so no second secret is needed.

The same runs as `POST api/query` for an administrator's session: body `{"db": "world", "sql": "...", "format":
"json"}` (or `"text"` for a table as `mysql -t` prints it) and the header `X-CSRF-Token`, which the Query page holds
in its form's `data-csrf`.
