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
| `github-latest-release` | the release a project marks as its latest, whatever its tag (a draft or a pre-release is not), and that release's file (Karrz tags each WoW Forever release anew: `v0.1.36`) |
| `curseforge` | an addon's newest file (AtlasLoot Classic Forever) |
| `wago-build` | a product's newest client build on wago.tools (`wowf`, `wow_classic_era`) |
| `url` | a file's content (the public mirror of Blizzard's hotfix cache) |
| `replay` | the core's own files, read where you point the build |

**A new release of the base.** The core's update files come from Karrz's WoW Forever releases, so `world pin`
watches them (`karrz`): when a release is out, the command says `moved: karrz` and the lock names its tag (it says so
too the first time, and when a release's file is rebuilt under the same tag). The pin
does not put the release into the world by itself. The replay reads the core you point it at, and a core that carries
changes of its own takes a release in through its own merge; once it has, replay again, resolve again, and the export
no longer offers what the release brought.

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
| `text` | a quest | what was said when it was offered, asked about and handed in: the wordings seen, the most seen first (twelve at most) |
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
| `rxpguides` | RestedXP's levelling guides (RXPGuides), the Forever guide files the addon's own list names, at the pinned commit. A guide is written by hand, step by step. A step that names exactly one NPC, by its id, and has the player accept or turn in a quest there states who gives or takes that quest: only those steps are read (`gives`, `takes`). Each fact keeps the steps that say it, ten at most: the guide, the NPC's name as written, where the step sends the player last, the step's filter and season tags, the line's own filter. A guide's own filter (a whole guide written for one faction) is not kept. Not read, because who gives the quest is then not stated: a step that names its NPC by name only or names several, and a step its authors switched off. Counted as left out: a step whose one target is something to click (an object, which the guide does not tell from an NPC) and a quest id that is not a plain number. A `.goto` is where the player should stand, not where something spawns. Steps about quests the Classic Era client already has, Season of Discovery included (`tools/baseline/classic-era.json`), are left out: most are the Classic guide's own lines carried over. Its licence is non-commercial and share-alike, so it is `private`: it counts as a witness and never gives a published row; and it is written, not recorded, so it is never a live recording by itself. A guide file that is cut short stops the reading |
| `questie` | QuestieDB's twelve Forever correction files of the pinned commit. Its Forever data is the Classic database with converted coordinates, plus corrections; only the corrections say something about Forever, so only they are read, and each fact names the part that says it: `trace` (what players' QuestieTrace recordings showed on live Forever), `generated` (the reviewed delta QuestieDB generates for Forever; it is built from Wowhead's pages, so it is no second witness beside Wowhead), `fix` (a correction written by hand), `dynamic:<table>` (a hand correction that depends on the player, with the table it stands in: one faction's quest giver is not the other's). Who gives and takes a quest, what drops and sells an item, and each quest's, NPC's, object's and item's whole correction as an `entry`, kept whole. A name used as a value stays a name (`raceIDs.NIGHT_ELF+raceIDs.HUMAN`), one used as a key keeps its last part (`ELWYNN_FOREST`). A `_remove` correction and a plain empty list ("none") stay in the entry and state no fact; in QuestieDB a hand fix's plain list replaces the generated one, which only the entries show. Facts are not tied to a client build. A file that is missing, cut short, or written in a way the reader does not know (code where data should be, a function that returns two tables) stops the reading; a value of a shape it does not know is counted and left out, never guessed at. A thirteenth file added upstream is not noticed |
| `eglink` | Every WoW Forever build of the pinned commit: `npcs`, `creatures`, `vendors`, `trainers`, `loot`, `quests`, `creature_details`, `object_details`, `objectives`, `turn_ins`, and the quest texts of `texts`. Not read yet: boss loot rolls (`loot`'s `rolls`), flights, game rules, the other texts (gossip, greetings, books) and the hotfix caches. Downloads go to `data/eglink/<commit>/`, the folder the website's EG Link import also uses; a file that is not whole is not kept, and one found broken stops the reading |

## Rules: what the world should hold and does not

`world resolve` puts the two sides together: the replayed world is the base, the facts are claims, and a named rule
turns the claims about one thing into a decision. Nothing is written to any server: the decisions are stored in the
tracker's database, each with its reasons.

```bash
python tools/tracker.py world resolve                             # needs: world replay, world facts <source>
python tools/tracker.py world decisions                           # the summary of the last resolve
python tools/tracker.py world decisions quest --verdict add       # the quests ready to add, with giver, ender and witnesses
python tools/tracker.py world decisions gives --verdict review
python tools/tracker.py world decisions npc --verdict hold           # NPCs sources name but nothing shows
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

**An NPC the world lacks**

| Rule | When | Verdict |
|---|---|---|
| `record-seen-live` | The server sent the NPC's record (name, title, kind, model) to a client of the live game, and a source that may give rows recorded it | `add`: its template can be written |
| the rules for pairs | No such record, but sources state it exists (QuestieDB's entry: name, level, title, where it stands) | `hold`: nothing says what it looks like; or `review` when their word is not enough |
| `looks-internal` | Its name reads like a developer's leftover, whatever recorded it | `review` |
| `only-claimed` | Nothing describes it: claims only name it | `review` |

A claim or a quest that only waits for an NPC that is ready comes with it, as a pair comes with its quest, and may be
published only if the NPC may. A claim that still waits for something else, or is for a person, only notes that its
NPC is ready. Each NPC decision notes what else is known of it and how many claims that pass a rule wait for it.

**A quest the world lacks**

| Rule | When | Verdict |
|---|---|---|
| `record-seen-live` | The server sent the quest's record to a client of the live game, and a source that may give rows recorded it: the quest exists | `add`, once a giver and an ender pass the rules above and have a template or are NPCs that are ready themselves; else `hold`, with what is missing |
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
`ft_world_resolved` (when, the summary). A resolve replaces them whole. Approving and rejecting decisions by hand
come later; so do drops, trainers, spawn positions and the fields of rows the world already has. Not
followed yet: a QuestieDB hand fix whose plain list replaces a generated one (only `_remove` is read), and a build
of a test realm later than `live_from` (it counts as live).

## Export: the decisions that are ready, as an update file

```bash
python tools/tracker.py world export --dry-run                       # plan it and try it, write nothing
python tools/tracker.py world export --out <checkout of your data repository> [--private-out <folder>]
```

`world export` writes the decisions with the verdict `add` as the kind of file the core's updater applies from
`sql/custom/world`:

| Written | Where |
|---|---|
| `YYYY_MM_DD_NNN_world_everlake_build.sql`: the rows that may be published | `<out>/sql/world/` (default `data/world/export/public`) |
| `YYYY_MM_DD_NNN_world_everlake_build_private.sql`: the rows only a source without a licence to publish states | `<private out>/sql/world/` (default `data/world/export/private`) |
| `<the file's name>.json`: which decision each row carries (rule, witnesses), the pins of its sources, the file's SHA-1, what was held back and why | `build/` of the same folder |

NNN starts at 950, so a build file runs after the day's other files (the Forge's exports use 900), and the public
file sorts before the private one of the same export: a private row may need a public one, never the other way
round. A number is used once a file or a manifest carries it. Nothing is committed or pushed: the files are yours to
review and commit.

A file that may be published names only sources that may be: a private or reference source that also witnessed a row
stays out of the file, its ledger note and its manifest.

**What a file may do**

- **Running it again changes nothing, and it never changes a row it did not add.** Each table's rows go through a
  temporary stage table; only the missing ones are inserted.
- **A row goes in only while the world is as the decision saw it**: its NPC or object and its quest exist, the
  vendor does not list the item at any price, nobody borrows the vendor's list, and no earlier file added the row
  before (a row the server's owners took out stays out).
- **Every row is recorded** in the server's ledger `everlake_import_rows`: table, key, file, and as its note the rule
  that passed it and the sources that state it (`seen-live: eglink@70938, questie:trace`). Rows carry
  `VerifiedBuild` 0: they are not a recording of the server. Each row also has its meaning beside it in the file
  (`-- Jason Mathers gives Bottles and Baubles`).
- **An NPC that gets its first quest or its first item also gets the flag** (quest giver, vendor) on its template, or
  players could not use the row. A spawn that overrides its template's flags is not touched.
- **A deployed file is never edited.** A later fix is a later export.

**Tried before it is written.** The file's statements run twice on the replayed world, inside a transaction that is
rolled back, so the scratch database stays what the replay made it. The first run must add every row and record it;
a row the world does not take is left out and reported; a second run that adds or removes a row or sets a flag, or
a statement the world refuses, stops the export and nothing is written. The tables are counted again after the
rollback: a world that kept anything (a table that does not roll back) is reported loudly. A file name the world's
ledger already knows is refused too: two different files of one name would make the updater run the second as a
changed first.

**What is written today, and what is held back**

| Decision | Written as | Held back when |
|---|---|---|
| an NPC the world lacks | `creature_template` and the NPC's own rows (below), from the record the server sent | no record a row may be written from; no player was seen to treat it as a friend (nothing states whom it is friendly to, or only a list does); players fought it, or a side saw it hostile (a monster); nothing states its level; the world has no size for its model (`creature_model_info`); the record does not fit the columns |
| a quest the world lacks | `quest_template` and the quest's own rows (below), from the record the server sent | no record a row may be written from; the record does not fit the columns; an objective needs an NPC or an object that has no template and is not written with it; nobody who could start or end it can be written yet |
| an NPC or object gives or takes a quest | `creature_queststarter`, `creature_questender`, `gameobject_queststarter`, `gameobject_questender` | its quest or its NPC is held back; the object is not of the quest giver kind; the world's own row for the quest, the NPC or the object reads like a developer's leftover (a quest still titled `REUSE`): that row needs a person first |
| a vendor sells an item | `npc_vendor`, a plain row: sold for money, in endless supply, in the next free slot | no recording of the live game shows the vendor's window with a money price for it, and the world's other vendors do not say how the item is sold either (below). Also: it costs items or a currency (the extended cost id is not known), its stock is limited (the restock time is not known), a newer recording says one of those even if it may not give the row itself, another vendor borrows this vendor's list |

In the file, what others need comes first: NPC templates, then quests, then the pairs and vendor items that hang on
them. What needs an NPC that is written with it (its quest pairs, its vendor items, a quest with an objective on it)
is left out when the NPC is, and private when the NPC is.

A quest is written with a giver and an ender or not at all, and a pair with its quest or not at all. What may be published never needs what may not: a quest whose
only giver (or ender) is private is private itself, and so is every pair of a private quest. The same is checked
again after the earlier exports' rows and the rows the trial refused are taken out.

**How a vendor item is sold.** A vendor row holds no price: the item's price is the client's. The row says whether
the item is sold for money or for something else (an extended cost) and whether its stock is limited, and a list
that only says "sold by" states neither. So:

1. A recording of the vendor's window on the live game decides, when there is one: the newest one.
2. With no recording, the world's own vendors are asked how they sell the item. The row is written when at least one
   other vendor that players can reach sells it (it is spawned, it has the vendor flag, its name does not read like
   a developer's leftover) and every other vendor that lists it, reachable or not, does so for money, in endless
   supply, without a condition or a bonus list. Nothing new is sold that way: the item can already be bought for
   money. A vendor that sells the item during an event only says how it is sold, not that it can be bought today;
   a row an earlier export added is not asked at all, so the rule never rests on what it wrote itself.
3. A recording that may not give a row (one from before the live game) can still speak against rule 2: if the
   newest of them shows the item for a currency, in limited stock or listed twice, the row is held back.
4. Otherwise it is held back: no other vendor players can reach sells it, or some sell it for a currency, with a
   condition or in limited stock.

Where only a source that may not be published recorded the window, the row is private, unless rule 2 gives the same
row: then it rests on the world's vendors and can be published.

How rule 2 was checked: on the replayed world's own rows, each taken out in turn. Of the 13,270 rows of reachable
vendors whose item every other vendor sells plainly, 13,252 are plain themselves (99.86 %): 17 have limited stock
and one an extended cost. With a single other reachable vendor it is 340 of 351 (96.9 %), with two or more 12,912 of
12,919. The manifest says for each vendor row which of the two it rests on, and how many other vendors (`sold`).

**An NPC's rows** (`tools/ft/npcs.py`). The record is what the client's creature cache holds: what the NPC looks like.
It is not all the server knows of it, and the writer is plain about what it adds and what it leaves out.

| Table | From |
|---|---|
| `creature_template` | the record: name, title, cursor, classification, type, family, class, movement id, the creatures it counts as. Constants of every NPC recorded on Forever: attack times 2000, `unit_flags2` 2048 |
| `creature_template.faction` | **a stand-in by side.** No source states an NPC's faction id. What is recorded is whom it is friendly to (below). The row gets that side's generic faction: 84 Alliance, 83 Horde, 35 both. Its quests and its goods then reach the players they should; whose guards defend it and whose reputation it is tied to is not known, and an NPC of one side is an enemy of the other |
| `creature_template_difficulty` | the record: health and mana modifier, difficulty id, type flags |
| `creature_template_model` | the record's models, scale and probability, in its order |
| `creature_classic_level` | a source that states the level: QuestieDB's entry, else the levels players saw it at |

**Whom an NPC is friendly to.** Only an NPC that players were seen to treat as a friend is written, never one a list
alone calls friendly (QuestieDB's list also names monsters):

- a player **talked to it** on the live game (opened its quest, goods or gossip window). Its side is the one the
  recording gives it; when it gives none, QuestieDB's `friendlyToFaction`; else the side that saw it friendly;
- or a side's players saw it **friendly** (a reaction above neutral) and never below neutral. Neutral alone says
  nothing: a deer is neutral. A side that never saw it is not said to be its friend;
- players **fought it** (a sighting with kills, experience or a combat log): no friend, whatever else is said;
- a side whose players saw it below neutral is never part of its side. A source that may not give rows can still
  say so.

A monster needs how hard it hits, its armour and its loot, and no source in the build states those. What the NPC
does is not written here either: the rows that give it a quest or an item set its quest giver or vendor flag. **No
spawn is written**: a template says what the NPC is, not where it stands; `tracker.py locate` and the Forge place
NPCs the content needs.

An NPC goes in whole or not at all: only while the world has no row of it in any of these tables, the world can show
every one of its models (it has their size in `creature_model_info`; the server does not create a creature whose
model has none), and no file added it before. The file itself checks the same when it runs, and holds a quest back
whose objective names an NPC or an object the world has no template of.

How it was checked: for the 600 NPCs the replayed world holds from a recording of build 70124 or later that EG Link
also recorded, name, title, classification, type, family and class agree on 97 to 100 %, the models on 597, the
health and mana modifiers on 593 and 600. For the faction there is nothing to agree with: among those NPCs the
generic faction is the world's own for 58 % of the ones friendly to both sides and for none of the one-sided ones
(the world gives those their own town's or tribe's faction), which is why it is called a stand-in and named in every
manifest row (`side`, `side_from`, `faction`).

**A quest's rows** (`tools/ft/quests.py`). The record is what the client's quest cache holds: the server's own answer
to "what is quest N", as EG Link recorded it on the live game. A field of a row is the record's value, a constant
every recorded Forever quest holds, or left to the table's default; nothing is guessed.

| Table | From the record |
|---|---|
| `quest_template` | type, info, flags (three), start item, next quest, reward spell, time limit; `QuestSortID` (the zone, or minus the category); XP difficulty and multiplier; `AllowableRaces` (64 bits); reward items (4), item drops (4), choice items (6), currencies (4); reputation (5): the faction, `RewardFactionValue` = the tier, the override; title, objectives text, description, area description, completion log |
| `quest_template`, constants | `RewardFactionCapIn` 7, `AcceptedSoundKitID` 890, `CompleteSoundKitID` 878, `Expansion` -2 |
| `quest_objectives` | Forever's own objective id, type, order, storage index, object, amount, description |
| `quest_classic_level`, `quest_template_classic_level` | the level it is offered from, and the level shown in the log (`LevelType` 2) |
| `quest_classic_money` | the money, exactly, when the record states any |
| `quest_reward_display_spell` | the spells shown as rewards, in the record's order |
| `quest_template_addon` | `AllowableClasses`: QuestieDB's word, else the class of a class category (a quest filed under "Paladin" is a paladin's); `PrevQuestID`: the one quest QuestieDB says comes before, when the world has it |
| `quest_offer_reward`, `quest_request_items` | what the NPC says when the quest is handed in, and while it is not done yet: the text a recording of the live game shows in that window, from a text fact (below) |

How it was checked: for the 463 quests the replayed world holds from a recording of build 70124 or later that EG Link
also recorded, the rows made here were compared with the world's, column by column. Each column agrees on 97 to
100 % of them, the objectives on 450 of 463, and where they differ the record is the newer word (a reward changed on
live after the world's recording). The class of a class category is the class the world's own row carries for 303 of
308 such quests.

A quest's text is kept to the character (line breaks and backslashes are written as `CHAR()`, so neither the server's
`sql_mode` nor a repository's line-end rules can change it). A quest goes in whole or not at all: only while the world
has no row of it in any of these tables, none of its objective ids is another quest's, and no file added it before.

**What the NPC says at the turn-in** is not in the record: it is what a player's client showed in the quest's window
(`text` facts). A text comes with its quest when the recordings of the live game have it in one wording, over every
build; two wordings are two answers (the NPC speaks otherwise to another class, the text changed, or the recorder
guessed a word on one of them), and none is taken. The manifest names the recording each text is from (`texts`). Line breaks are written as `$B`, as most of the world's own texts have them. A text only a source
without a licence recorded stays out of a row that may be published. A quest is not refused for a text the world
holds already: that text stays, and only what the file added is recorded as its own. A quest an earlier export
carries is not written again, so a text recorded after that export does not reach it yet.

How it was checked: for the quests the replayed world and EG Link both have a text of, EG Link's is the world's
(apart from line breaks and the case of `$N`) for 817 of 876 hand-in texts and 547 of 560 progress texts. Where
they differ, about a third are a word the recorder could not turn back into what the server holds: a race or class
name where the server has `$R` or `$C` (or the reverse), or one sex's word where the server has both
(`$Ghis:her;`). Such a text reads right for the player who recorded it and can read wrong for another.

What a quest's rows do not hold is left to the table's default or not written, and listed in every manifest
(`left_to_defaults`): the money columns of `quest_template` (the money is exact in `quest_classic_money` instead),
`RewardFactionFlags` and the other columns no record carries, the POI and portrait columns, an objective's own
`Flags` (32 for every objective: what four in five recorded Forever objectives hold), the rest of
`quest_template_addon`, the turn-in texts no recording has in one wording and their emotes, `quest_details`,
`quest_poi`, and the texts and rewards a record gives for a player condition. A field a record
carries that is not read is named per quest (`unread`), so nothing is dropped in silence. A record that does not fit
the columns (a reputation tier outside -9 to 9, a zone and a category at once, text the file cannot hold) holds its
quest back with the reason.

QuestieDB's hand fix is read after its generated list, and a fix that names a field replaces it, also with nothing:
a fix that says "no class" or "several quests before it" clears what the generated list said.

The summary names every reason with its count. A decision an earlier export in the same folders carries is not
written again, whatever the world holds by now: point `--out` at the data repository's checkout and its `build/`
folder is the record of what was exported. Once a file is merged there, the next `world replay --data` holds its
rows and the next `world resolve` no longer asks for them.

## Tests

```bash
python -m unittest discover -s tools/tests
```

Standard library only, no database and no network: the registry's rules (a source without a licence is never public,
witness groups, the most restricted use wins), every pin type against recorded answers, the replay's file guard,
order and trigger statements, and the facts read from a small copy of each source's files.

One class replays a small world on a real MySQL server, under an account it creates with rights on the scratch
database only, and checks every origin. It runs when `FT_TEST_CONFIG` names a `config.ini` of a **throwaway** server
whose user may create and drop databases and accounts, and is skipped otherwise. The database tests of the facts, of the rules and of the export also create and drop that server's `[database]
tracker` database: one more reason to point them at a throwaway server only:

```bash
FT_TEST_CONFIG=/path/to/test-config.ini python -m unittest discover -s tools/tests
```
