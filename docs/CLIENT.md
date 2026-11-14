# The official client, from Blizzard's own servers

The tracker's official list is the client's own tables: what exists in the game is not a matter of opinion, and no
other source ranks above it (docs/SOURCES.md, *Rows the server already has*). Until now those tables were read from
the **server's extracted copy** only, and only when the realm moved to another build. So the tracker learned of a new
client build weeks after players' clients had it, and its changelog stayed empty.

`tracker.py fetch` asks Blizzard's servers directly, the way the game's launcher does. No game account and no
install are needed.

```bash
python tools/tracker.py client
```

```bash
python tools/tracker.py fetch
```

`client` prints the build that is live, the newest build the tracker holds and the build of the server's data.
`fetch` stores the live build when it is newer than the newest snapshot, as `data/builds/<build>/enUS` with a
`build.json` that says where it came from. The next analysis then compares the server with what players' clients
hold today: the changelog shows what Blizzard added, changed and removed, and resources of the new build that the
server lacks show as gaps before the server has moved to it.

## How it reads a build

| Step | From |
|---|---|
| Which build is live | Blizzard's version server, `us.patch.battle.net:1119/<product>/versions` (`[client] product`, `wowf` for WoW: Forever) |
| Where a table's bytes are | The build's own files on the CDN: build config, root, encoding, archive indexes (`tools/ft/cdn.py`) |
| Which file is which table | `tools/schema/db2-files.json`: each table's file data id, from WoWDBDefs' manifest (`tools/make_db2_files.py`) |

The first read of a build downloads its encoding file and archive indexes, about 315 MB, and takes a few minutes;
the 74 tables themselves are then a few seconds. The lookup files go to `data/cdn` and are removed once the build is
stored (`--keep-cache` keeps them). Every whole file is checked against its content key.

## Unreleased content: read again when it opens

Blizzard ships content before it opens, encrypted: a table then has sections under a key nobody has yet. The core's
extractor leaves those sections as zeros and marks the sections it could decrypt; the tracker's reader skips the
first and reads the second. A table read from the CDN is written the same way, so a snapshot from the CDN holds
exactly what one from the server's copy would.

A key comes out when its content opens. So a build already stored gains readable parts with time: `build.json`
keeps, by table, the keys the build is waiting for (`waiting`), and `fetch` reads the same build again as soon as one
of them is in the list of published keys (wowdev's TACTKeys). What was hidden then shows as new official content, and
as a gap where the server lacks it.

## When a build is refused

A table is read with the layout the tracker's schema describes (`tools/schema/db2-schema.json`, generated from the
core). When Blizzard changes a table's layout, reading it the old way would give nonsense: `fetch` then stores
nothing and names the tables. A layout counts as known when it is the one the same table has in the newest other
snapshot (the one the tracker reads today), or the one the schema names. The way out is the core's: once it supports
the build, run `tools/make_db2_schema.py` against it and fetch again. `fetch` exits 0 when it stored a build, 3 when
there was nothing new and 2 when it refused one.

## In the container

Every `FT_CLIENT_EVERY_HOURS` (6; 0: never) the container runs `fetch`, and the analysis after it when a build was
stored. The check itself is two small requests. The log is `data/client.log`. The container needs to reach
`us.patch.battle.net:1119` and Blizzard's CDN hosts.

## Hotfixes: the game as it is played today

Between two builds Blizzard changes the game's tables by hotfix: a record is added, replaced or removed, every client
gets it at login and keeps it in its hotfix cache (`DBCache.bin`). The cache of live WoW: Forever is mirrored
publicly and refreshed daily (`[client] hotfix_cache`; empty: that mirror). Without it the official list is the build
as it shipped. For WoW: Forever that leaves a great deal out: thousands of items are in no client table at all and
reach the client by hotfix only (Carving Knife, Rhahk'Zor's Hammer, the raids' loot).

```bash
python tools/tracker.py hotfixes
```

It downloads the cache and keeps it as `data/builds/<build>/hotfixes.bin`, with the snapshot of the build it was
written for. From then on that build's tables are read with the hotfixes over them: the analysis, the tooltips and
the Forge all see the game as it is today. The analysis log says, by table, how many rows were added, changed and
removed.

A cache record is one row of one table, written field after field with its text in place; it is read with the same
schema as the table. A record that does not end exactly where its bytes end was written for another layout: it is
left out and counted, never half believed. "Invalid" and "not public" records change nothing.

**The later word wins:**

| Two words on one row | Which stands |
|---|---|
| A build's table and a hotfix of that build | The hotfix: it came after the build |
| Two hotfixes | The later push |
| A newer build's table and an older build's hotfix | The table: the build came after the hotfix |

When a new build ships, its own cache is not on the mirror at once. Until it is, the hotfixes of the build before are
carried over for the rows the new tables do not have at all, and for nothing else: a row the new table has is the
table's, and nothing is taken away. Without that, the items that exist by hotfix alone would vanish from the list for
a day and come back. Once the new build's own cache arrives it says everything, and nothing is carried over.

A cache is never used for another build than the one in its header, and never for an older build.

## What it does not do yet

- **Keys from the hotfixes.** Blizzard hands out the keys of unreleased content by hotfix too; the stored build is read
  again when a key appears in the public list (wowdev's TACTKeys), which follows a little later.
- **Hotfixes in the changelog.** A hotfix changes the newest build's content in place: the changelog compares builds,
  so it shows a hotfix only as part of the difference between two builds.
- **Other locales.** The enUS tables and the enUS cache are read; a French snapshot still comes from the server's own
  copy.
- **An older build.** The version server names the live build only.
