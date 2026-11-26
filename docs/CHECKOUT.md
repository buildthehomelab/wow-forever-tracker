# Checkout: the game's data at any step of the timeline

The changelog says what changed at every step: the original game, each build, each day's hotfixes. A **checkout**
turns one of those steps back into data your server can load, so a test realm can play the game as it was then.
This page covers the client's data (your server's `hotfixes` database). The world (spawns, loot, vendors, quests)
has its own history, the core's update files: `tracker.py world replay --at <step>` rebuilds it as of the step's day
in the build's scratch database ([WORLD-BUILD.md](WORLD-BUILD.md)), so the two can be paired.

```bash
python tools/tracker.py checkout list                 # the steps, as the timeline shows them
python tools/tracker.py checkout 70707 --fetch        # build 70707 (reads its other tables from Blizzard's CDN first)
python tools/tracker.py checkout 70938+1              # build 70938 with its hotfixes of the day of update 1
python tools/tracker.py checkout latest --out ptr.sql
```

On the website, **The Forge → Checkout** lists every step of the timeline. *Make* writes a step's file in the
background (with `--fetch`), one at a time, and shows the log; the file can then be downloaded from that page. A
step's changelog page links to it. Only administrators see the page and the files.

## What it writes

An SQL file (`data/checkout/hotfixes-<step>.sql` by default) and its manifest beside it (`.json`). Nothing is
written to a database: you load the file into the hotfixes database of a **test realm**, then restart its
worldserver. The rows are written for your server's build: `[server] build` (or `build_file`) in config.ini, else
the client build the realms accept (`auth.realmlist`), as the analysis takes it.

For each table the tracker reads (tools/schema/db2-files.json):

- the step's records, with the hotfixes that stood over them, are compared with the DB2 file your server loads
  (`[server] dbc`);
- a record that differs, or that your server's file lacks, becomes a row of the server's hotfix table (`item_sparse`,
  `spell_effect`, ...) with `VerifiedBuild` = your server's build, and a `hotfix_data` line with status 1: the server
  loads the row over its own file and sends it to the game clients that connect;
- a record your server's file has and the step does not gets a `hotfix_data` line with status 2: the server takes it
  out of its store and tells the clients to drop it;
- records that are the same are not written: the server's own file already says them.

The talent trees are among those tables. Classic 1.60 builds its talents from the trait system (`TraitTree`,
`TraitNode`, `TraitNodeEntry`, `TraitDefinition` and the tables that join them, `content.TRAIT_TABLES`), not from
`Talent` and `TalentTab`, so a tree Blizzard changes (a node's ranks, the spell behind a definition, and the `Curve` /
`CurvePoint` rows that give a definition its value at each rank) is in these. A
build stored before they were read lacks them: `--fetch` (the Forge's Checkout button) reads them from the CDN first.

All the lines are one push, numbered after every push the database holds before it runs. The file runs in one
transaction and **replaces** the tables it names: it empties them and their `hotfix_data` lines first, so what was
there before (rows the Forge applied, rows of the core's own update files, an earlier checkout) goes too. A table the
checkout leaves out (below) is emptied as well when your server keeps a hotfix table for it: your server's own file
then stands for it, and no earlier checkout's rows stay behind next to this step's. The file's first lines and the
manifest (`emptied`) name those tables. That is the point of a checkout: the realm's client data is the step's,
nothing else. Load it into a test realm's database, never into the live one. (It also means a left-out table loses
rows the core's own update files had added to it: an item that exists by hotfix alone keeps its item rows from the
step, but not, say, its appearance rows when `ItemModifiedAppearance` is left out.)

A game client keeps the hotfixes it was sent. After loading a checkout over another one, clear the client's `Cache`
folder: a record that went back to what your server's file says gets no line of its own, so a client that kept the
earlier checkout's version would keep it.

The values are exact: a float is written as the client stores it (the website rounds them to four decimals, a
checkout does not).

## What it cannot say

- **Another layout.** A table whose layout at that build is not the one of your server's file (or whose columns, as
  the tracker reads them, are not your server's hotfix table's) cannot be sent to a client of your server's build:
  it is left out, and the manifest and the log say why.
- **Content still encrypted.** When the step's file holds sections nobody can decrypt yet and your server's file
  holds fewer, the records your server has and the step does not are not removed: they may be in those sections. So is a table
  your server keeps no hotfix table for (`Spell`, `TalentTab`, `ItemSubClass`, `UiMapGroupMember` on TrinityCore),
  and `Creature`, whose columns the tracker names its own way.
- **Hotfixes before the tracker kept them.** Blizzard's hotfixes are known from the day the tracker kept their
  cache ([CLIENT.md](CLIENT.md)). For an earlier build, the records that exist by hotfix alone (thousands of items,
  Carving Knife among them) come from the earliest cache kept after it, as the changelog counts them: known since the
  first build. `--no-carry` leaves them out. A hotfix that changed a record the build's own table has is not known
  for that time: the table stands as the build shipped it.
- **The original game.** Its tables are another client's, in another layout: it is no step a checkout can write.
- **Other locales.** The English texts are written; the `_locale` tables are left as they are.

A build stored for the changelog alone holds the 25 tables the changelog compares. `--fetch` reads the others from
Blizzard's CDN first (about 40 MB for a build, once); without it those tables are left out and the manifest says so.

## The manifest

```json
{"step": "70707", "build": 70707, "hotfix": 0, "server_build": 70938, "file": "hotfixes-70707.sql",
 "tables": {"ItemSparse": {"hotfix_table": "item_sparse", "records": 24533, "rows": 5277, "removed": 40}},
 "skipped": {"Spell": "your server keeps no hotfix table for it", "Creature": "the tracker reads it with other columns ..."},
 "emptied": ["creature"], "carried": 5266}
```

`records`: what the step's table holds; `rows`: what differs from your server's file; `removed`: what your server's
file has and the step does not; `emptied`: the hotfix tables of left-out tables, emptied; `carry`: false with
`--no-carry`; `carried`: the records that exist by hotfix alone brought to a step without hotfixes of its own (0 for
a step that has its own: they come with its cache).

## Checked

On the original game plus 30 builds and two days of hotfixes, against a hotfixes database built from the core's own
schema and update files:

- `70938+1` writes 69 tables (12,623 records over a test server's files, 62 removed), `70938` (its first day's
  hotfixes) 12,541, each in under 30 seconds;
- `70707 --fetch` reads the build's other 49 tables from the CDN in under a minute, then writes 12,269 records and
  665 removals, 5,266 of the records being items that exist by hotfix alone;
- loaded one after the other, every row of each read back the same as the client says, field by field, and the
  second got a push of its own.
