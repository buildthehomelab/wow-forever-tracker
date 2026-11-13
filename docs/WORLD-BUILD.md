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

## Tests

```bash
python -m unittest discover -s tools/tests
```

Standard library only, no database and no network: the registry's rules (a source without a licence is never public,
witness groups, the most restricted use wins), every pin type against recorded answers, and the replay's file guard,
order and trigger statements.

One class replays a small world on a real MySQL server, under an account it creates with rights on the scratch
database only, and checks every origin. It runs when `FT_TEST_CONFIG` names a `config.ini` of a **throwaway** server
whose user may create and drop databases and accounts, and is skipped otherwise:

```bash
FT_TEST_CONFIG=/path/to/test-config.ini python -m unittest discover -s tools/tests
```
