# The world build

The analysis tells you what your server lacks. The world build is the other half: the tracker **makes** the world
data your server loads, from layers of sources, and keeps the reason behind every row. Its output is update files for
a [data repository](DATA-REPO.md); it never writes to a running server's databases.

This page describes the model and the parts that exist. The build is being added step by step: each section says what
is there today.

## Layers

A world database is not one source. It is a base with corrections stacked on it, and each kind of fact has a source
that knows it best. The layers, lowest first:

| Layer | What it is | Wins |
|---|---|---|
| Vanilla 1.12 | The 1.12 world databases (VMaNGOS, CMaNGOS classic-db) | Nothing by itself: it is the reference for Classic content Forever kept, and restores a vanilla row the base lost |
| Server world | Your core's release database and its update files, replayed in order | Everything no higher layer speaks about: spawns, movement, scripts |
| Season of Discovery era | Ids the Forever client carries over from the Classic Era client | Rows for those ids only |
| Blizzard's client and hotfixes | The client's own tables for each build, and the hotfixes Blizzard pushes | What exists, and every field the client holds: names, items, spells, maps |
| Live recordings | What players' addons recorded on live Forever | Server-held facts when witnessed: who gives and takes a quest, what a vendor sells and for how much, what a trainer teaches, what drops |
| Reviewed corrections | The Forge, on a test realm | A person's decision, with a reason |

A higher layer does not simply overwrite a lower one. It wins the kinds of fact it knows, by named rules:

- **What exists** is decided by the client's own tables. Wowhead names a thing and marks Season of Discovery
  leftovers; a thing Wowhead does not know stays in (Forever hides items until players find them).
- **A recording never deletes.** That nobody recorded a drop, a spawn or a vendor item is not evidence it is gone.
- **A server-held fact needs a witness**: one source that recorded it clearly on live, or two independent ones.
- **Close calls are not decided**: when sources disagree and none clearly wins, the row waits for a person.

## Sources, licences and witnesses

`tools/world/layers.json` lists every source with its layer, licence, credit line, **use** and **witness group**:

| Use | Meaning |
|---|---|
| `public` | Rows made from it may be published in a data repository, with its credit |
| `private` | Its values may only reach your own server. It still counts as a witness |
| `reference` | It never gives a row or a value: it confirms what another source says |

A source without a licence is never `public`. A row is published only when every source that set one of its values is
`public`; otherwise it goes to a private set you keep for your own server.

The **witness group** says whose observations the data really is. Two sources of one group are one witness, however
often they agree:

- Icy Veins holds EG Link's rows, so the two are one group;
- NorgannonDB is compiled from QuestieDB, pfQuest, cmangos classic-db and DungeonJournal, so it is no second witness
  beside any of them (a source compiled from several others lists their groups in `also`);
- DatabaseForever is the core's release database plus generated rows, so it is no second witness beside the core.

```bash
python tools/tracker.py world layers        # layers, sources, licences, witness groups, pinned versions
python tools/tracker.py world pin           # look up every source's newest version
python tools/tracker.py world pin eglink    # only some sources
```

`world pin` writes `data/world/layers.lock.json`: for each source the version the build reads (a commit, a release
file, a client build, a content hash) and the day it moved. A source that cannot be reached keeps its previous pin,
with the error beside it, and the command ends with an error naming it. The lock is what later steps of the build
read their versions from, so that an export can name the exact versions it was made from.

| Pin | Newest version of |
|---|---|
| `github-branch` | a branch's head commit |
| `github-release` | a release's file and its date (VMaNGOS and CMaNGOS publish their current world this way; the date counts because a file can be rebuilt under the same name) |
| `curseforge` | an addon's newest file (AtlasLoot Classic Forever) |
| `wago-build` | a product's newest client build on wago.tools (`wowf`, `wow_classic_era`) |
| `url` | a file's content (the public mirror of Blizzard's hotfix cache) |
| `replay` | the core's own files, read where you point the build |

## Replaying the server's world

The world a server runs is its release dump plus every update file, applied in the updater's order. `world replay`
does exactly that in a **scratch database**, and notes under which file each row was inserted, changed or deleted:

```bash
python tools/tracker.py world replay --dump TDB_full_world_<version>.sql --core <core checkout> --data <data repository>/sql/world
python tools/tracker.py world why creature_template 248415
python tools/tracker.py world why creature_loot_template 3 0 2589
```

- `--core` replays the core's `sql/updates/world` and `sql/custom/world`; `--data` a folder of your data repository's
  files; `--folder label=folder` any other folder. Files of all folders run in file-name order, as the core's updater
  runs them. A file the release already lists in its `updates` table is left out while its content still has the
  hash recorded there (of its bytes, or of its bytes as a Windows build reads them), or the release marks it
  archived, and runs again when it was changed since, as the updater would. The same name in two folders is an error (the updater would run only one).
- Each file runs in one transaction, as under the updater: when a statement fails, the row changes the file made so
  far are taken back (table changes such as `CREATE` or `ALTER` are not, there as here). A failing file stops the
  replay, as it would stop the worldserver. `--keep-going` records it and goes on.
- `world why <table> <key ...>` answers where a row comes from: the release, or the file that created it, then every
  file that changed or removed it. The key is the table's primary key (a unique index when it has none). Tables with
  neither, such as the loot tables, are followed by their main index and say so: rows that share those values are
  not told apart.

What the replay writes, inside the scratch database:

| Table | |
|---|---|
| `ft_replay_files` | Every file run: number, name, folder label, sha256, `applied` or `failed` with the error |
| `ft_replay_log` | One line per row change: table, key, insert / update / delete, file. An update that leaves a row byte for byte as it was is not a change; one that only changes a letter's case or accent is. Also what happened to a whole table: created or rebuilt (`R`), emptied with `TRUNCATE` (`T`), a column renamed or dropped (`A`) |
| `ft_replay_tables` | The key each table is followed by, and whether it is unique |
| `ft_row_origin` | Per row a file touched: the file that created it (empty: the release had it), the last file that changed it, how many files touched it, whether it is gone |

A row no file touched is the release's own. A row a file deletes and inserts again keeps its origin, whether the file
does it with `DELETE`, `TRUNCATE` or by dropping and creating the table: the rows about to go are noted before the
file runs, and the rows of a table it created are noted after.

### What keeps a file inside the scratch database

An update file is somebody else's SQL, and the replay runs hundreds of them. **The MySQL account is the protection**:
the replay refuses to start unless its account can write to the scratch database and nowhere else. Give the build an
account of its own (`[build]` in `config.ini`, `FT_BUILD_USER` and `FT_BUILD_PASSWORD` in Docker):

```sql
CREATE USER 'tracker_build'@'%' IDENTIFIED BY '...';
GRANT ALL ON `ft_world_build`.* TO 'tracker_build'@'%';
```

The check reads the account's own grants: any right other than reading, on any other database or on all of them, is
named and stops the replay. So does a role, active or only granted (what a role grants is not looked at), and an
account whose grants cannot be read at all. `--trust-account` skips the check; it is meant for a throwaway MySQL
server that holds nothing else. Not seen by the check: the right to run a stored routine of another database, and
proxy rights. Do not give the build's account either.

A server that writes a binary log only lets an administrator create triggers, unless it is told otherwise. The replay
says so before it starts; an administrator then runs, once (and sets it in the server's configuration to keep it):

```sql
SET GLOBAL log_bin_trust_function_creators = 1;
```

On top of that:

- the scratch database's name is `[build] database` (`FT_BUILD_DB`, default `ft_world_build`); the replay refuses a
  name that is one of your server's databases, and a database it did not create itself;
- files run in the client's binary mode, where its own commands (`source`, `system`, `\u` ...) are switched off;
- each file is read before it runs. `` `world`.`creature` `` (the core's default name) is pointed at the scratch
  database. A file that plainly selects a database (`USE`), creates or drops one, names another database the account
  can see, holds a client command, switches roles, or changes how the server reads quotes, is refused.

That reading catches mistakes early and says why; it is not what protects you, and it can be got around: SQL that a
file builds piece by piece at run time, a setting changed in a roundabout way, or a comment only some server versions
read as code, cannot all be seen beforehand. That is why the account must not be able to write elsewhere. It can also
refuse a harmless file, when one of the databases the account can see is named like a table or an alias the file uses
(`c`, `creature`), or when a quest text reads like SQL naming such a database. An account of its own sees only the
scratch database, so there is nothing to clash with.

The release dump must not select its own database (some dumps start with `CREATE DATABASE` and `USE`): the replay
says which line to remove. The owner a dump names for its views, triggers and routines (`DEFINER=...`) is left out
while loading: the build's account may not create them for another user, so they become its own.

Limits:

- The files run through the `mysql` client in its binary mode; the updater uses the same client without it, so a
  line break inside a text is kept byte for byte here. The updater's `sql/old` archive folders are not read (a fresh
  database does not need them), and a file renamed since the release runs again under its new name.
- A file that renames or drops a column of a table (or renames the table) is noted as that (`A`), and the row
  changes it makes in the same table are not followed: the columns the log follows are changing under them. A
  renamed table counts as new under its new name.
- A table rebuilt in a way the replay does not recognise (it knows `DROP TABLE`, `TRUNCATE`, `CREATE OR REPLACE
  TABLE`) is noted as rebuilt, and its rows then count as that file's.
- Rows a foreign key removes by cascade, and changes made by a stored routine a file only defines, are not seen.
- `world why` tells apart "the release's row" and "no such row" only for rows nothing touched.
- The hotfixes database is not replayed yet.

## Facts: what each source says

The layers above the server's world are not databases: they are claims. "This NPC offers that quest", "this vendor
sells that item for this much", "this is the quest's record as the server sent it". `world facts <source>` reads a
pinned source and stores its claims in one shape, in the tracker's own database:

```bash
python tools/tracker.py world pin eglink      # the version to read
python tools/tracker.py world facts eglink    # download what is missing, read it, replace that source's facts
python tools/tracker.py world facts           # what is stored: per source and kind
```

| Kind | About | Says |
|---|---|---|
| `gives`, `takes` | an NPC or object, and a quest | who offers a quest, who takes it back |
| `sells` | an NPC and an item | every way the vendor lists it: costs, stack, limited stock |
| `teaches` | an NPC and a spell | costs, level, skill line and rank |
| `drops` | an NPC, object or container, and an item | per way of looting (alone, in a group, on a quest, through which spell): drops, loot windows, kills, the source's own chance |
| `gathers`, `fishes` | an NPC through a spell (skinning, pick pocketing); the water of a map | the same |
| `coins` | an NPC, object or container | the money looted, per way of looting |
| `talked`, `seen` | an NPC or object | a player opened its window; it was seen or fought: levels, rank, reactions, where |
| `quest`, `creature`, `object` | one of them | its record as the server sent it to a client |
| `objective`, `turn_in` | a quest | an objective counted while doing it; what handing it in gave |
| `entry` | a quest, NPC, object or item | its entry in a database people keep by hand, in that database's own fields |

Each fact keeps its source, the client build it was recorded on, the source's own record, and how much stands behind
it, in the kind's own unit: loot windows that show every item (a group's window does not, so a drop only seen in
groups has none) for loot and money, windows opened for `talked`, sightings for `seen`, players for the others.
A source that counts nothing says 1 when players recorded the fact and 0 when it only states it.
Nothing is weighed or worked out at this point: the numbers are the source's, a drop seen once is stored like one
seen a thousand times, a beta build like a live one. Only a long list of positions is cut to 40, with the number
there were. The rules that weigh facts come next, and read only this table, so a new source is one reader and
nothing else.

Tables: `ft_world_facts` (source, kind, subject, object, build, samples, data) and `ft_world_sources` (the version
read, its licence and use, when, how many records could not be read). Loading a source replaces its facts in one
transaction; the analysis does not touch these tables.

Sources read so far:

| Source | Reads |
|---|---|
| `questie` | QuestieDB's twelve Forever correction files of the pinned commit. Its Forever data is the Classic database with converted coordinates, plus corrections; only the corrections say something about Forever, so only they are read, and each fact names the part that says it: `trace` (what players' QuestieTrace recordings showed on live Forever), `generated` (the reviewed delta QuestieDB generates for Forever; it is built from Wowhead's pages, so it is no second witness beside Wowhead), `fix` (a correction written by hand), `dynamic:<table>` (a hand correction that depends on the player, with the table it stands in: one faction's quest giver is not the other's). Who gives and takes a quest, what drops and sells an item, and each quest's, NPC's, object's and item's whole correction as an `entry`, kept whole. A name used as a value stays a name (`raceIDs.NIGHT_ELF+raceIDs.HUMAN`), one used as a key keeps its last part (`ELWYNN_FOREST`). A `_remove` correction and a plain empty list ("none") stay in the entry and state no fact; in QuestieDB a hand fix's plain list replaces the generated one, which only the entries show. Facts are not tied to a client build. A file that is missing, cut short, or written in a way the reader does not know (code where data should be, a function that returns two tables) stops the reading; a value of a shape it does not know is counted and left out, never guessed at. A thirteenth file added upstream is not noticed |
| `eglink` | Every WoW Forever build of the pinned commit: `npcs`, `creatures`, `vendors`, `trainers`, `loot`, `quests`, `creature_details`, `object_details`, `objectives`, `turn_ins`. Not read yet: boss loot rolls (`loot`'s `rolls`), flights, game rules, the texts and the hotfix caches. Downloads go to `data/eglink/<commit>/`, the folder the website's EG Link import also uses; a file that is not whole is not kept, and one found broken stops the reading |

## Rules: what the world should hold and does not

`world resolve` puts the two sides together: the replayed world is the base, the facts are claims, and a named rule
turns the claims about one thing into a decision. Nothing is written to any server: the decisions are stored in the
tracker's database, each with its reasons.

```bash
python tools/tracker.py world resolve                             # needs: world replay, world facts <source>
python tools/tracker.py world decisions                           # the summary of the last resolve
python tools/tracker.py world decisions quest --verdict add       # the quests ready to add, with giver, ender and witnesses
python tools/tracker.py world decisions gives --verdict review
```

| Verdict | Meaning |
|---|---|
| `add` | The world should hold it, and everything it needs is there |
| `hold` | The world should hold it, but something it needs is missing. `needs` names it: no giver known, an NPC without a template, a quest that is not in the world yet |
| `review` | The facts are not enough to decide: a person looks |

What the world already holds is not decided again (it is counted as *in the world*), and nothing is ever removed
because no source mentions it.

**Who gives a quest, who takes it, what a vendor sells**

| Rule | When | Verdict |
|---|---|---|
| `seen-live` | A recording on the live game states it: EG Link on a build of the live game, a QuestieTrace recording | `add` |
| `trusted-source` | No live recording, but a source the registry trusts by itself states it | `add` |
| `two-witnesses` | Neither, but two independent witnesses state it. The parts of one source are one witness, and so are sources of one witness group | `add` |
| `one-claim` | One witness's word, not recorded on live and not trusted by itself: a hand correction, a beta build | `review` |
| `reference-only` | Only sources that may never give a row state it | `review` |
| `removed-by-hand` | A source's own hand correction takes the claim back (QuestieDB's `_remove`) | `review` |
| `item-starts` | An item starts the quest: that is the item's own data, not followed here | `review` |

It needs its NPC or object to have a template in the world, and (for a quest) its quest to be there; an NPC that
exists and is not spawned is noted, not refused. A pair whose only missing piece is a quest that is itself ready to
add is ready too: it comes with its quest. A source that may never give a row can confirm a claim (count as the
second witness), never carry it.

What the world holds is read whole: a vendor's list with the lists it borrows from other vendors, and what an NPC
sells or gives only during a game event.

**A quest the world lacks**

| Rule | When | Verdict |
|---|---|---|
| `record-seen-live` | The server sent the quest's record to a client of the live game, and a source that may give rows recorded it: the quest exists | `add`, once a giver and an ender pass the rules above and have a template; else `hold`, with what is missing |
| `record-not-live` | Its record was only seen before the live game | `review` |
| `looks-internal` | Its name reads like a developer's leftover (`[DNT]`, `zzOLD`, `UNUSED`, `REUSE ME`) | `review` |

Whether a source is a live recording is the registry's word (`tools/world/layers.json`), and it is strict on purpose:
`live_from` is the first build of the live game; only a source marked `recorded` (its facts are recordings of play)
is live, and only for a fact from such a build; a source made of parts says which part is live and whose word each
part really is (QuestieDB: `trace` is live; `generated` is Wowhead's word; `fix` and `dynamic` are QuestieDB's own).
A registry without `live_from`, or with a part's `live` written as text, is refused rather than read as "everything
is live".

Which source is **trusted by itself** is also the registry's word (`trusted` on a source or on one of its parts): a
judgement about a source's record, written down where it can be read and changed. Today one is: QuestieDB's
`generated` list. It is Wowhead's data (the reference players have relied on since the game's early days), reviewed by
QuestieDB and shipped to Questie's users, and it is published under QuestieDB's licence, so its rows may be published. Wowhead read directly stays a reference: it confirms, it never gives a row. Trust is about
what a source states; that a trusted source does not list something still means nothing (new quests reach it late). A source
made of parts is trusted part by part, and a source that never gives a row cannot be marked trusted. One limit to
know: in QuestieDB a hand fix's plain list replaces the generated one, and that is not followed yet (only `_remove`
is), so a generated claim QuestieDB itself replaced would still be added; at the commit tested there is none.

Each decision also says whether it may be **published**: `public` when a source that may be published states it
(the row is then written from that source, whoever else witnessed it), `private` when only a source without a
licence does. A quest's record is stricter: it is `public` only when the live record itself comes from a source
that may be published, because the record's values are what gets written.

`world resolve` refuses to run on a replay that did not finish, or without facts: a world that stopped half way
would make everything look missing.

Tables: `ft_world_decisions` (kind, subject, object, verdict, rule, allowed, name, needs, notes, witnesses) and
`ft_world_resolved` (when, the summary). A resolve replaces them whole. Approving, rejecting and exporting decisions
come with the next step; so do drops, trainers, spawn positions and the fields of rows the world already has. Not
followed yet: a QuestieDB hand fix whose plain list replaces a generated one (only `_remove` is read), and a build
of a test realm later than `live_from` (it counts as live).

## Tests

```bash
python -m unittest discover -s tools/tests
```

Standard library only, no database and no network: the registry's rules (a source without a licence is never public,
witness groups, the most restricted use wins), every pin type against recorded answers, the replay's file guard,
order and trigger statements, and the facts read from a small copy of each source's files.

One class replays a small world on a real MySQL server, under an account it creates with rights on the scratch
database only, and checks every origin. It runs when `FT_TEST_CONFIG` names a `config.ini` of a **throwaway** server
whose user may create and drop databases and accounts, and is skipped otherwise. The database tests of the facts and of the rules also create and drop that server's `[database]
tracker` database: one more reason to point them at a throwaway server only:

```bash
FT_TEST_CONFIG=/path/to/test-config.ini python -m unittest discover -s tools/tests
```
