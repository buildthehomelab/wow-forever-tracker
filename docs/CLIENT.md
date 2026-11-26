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
the 102 tables themselves are then a few seconds. The lookup files go to `data/cdn` and are removed once the build is
stored (`--keep-cache` keeps them). Every whole file is checked against its content key.

## Unreleased content: read again when it opens

Blizzard ships content before it opens, encrypted: a table then has sections under a key nobody has yet. The core's
extractor leaves those sections as zeros and marks the sections it could decrypt; the tracker's reader skips the
first and reads the second. A table read from the CDN is written the same way, so a snapshot from the CDN holds
exactly what one from the server's copy would.

A key comes out when its content opens. So a build already stored gains readable parts with time: `build.json`
keeps, by table, the keys the build is waiting for (`waiting`), and `fetch` reads the same build again as soon as one
of them is out. What was hidden then shows as new official content, and as a gap where the server lacks it.

A key is out when either says so:

- **Blizzard's own hotfixes.** Blizzard hands a key to every client in a hotfix (a `TactKey` record: the key's number
  and its 16 bytes). The tracker already stores the hotfixes (below), so the key is there the day the content opens.
  A table's hidden section names its key by name, a hotfix by number; the build's own table `TactKeyLookup` joins the
  two, and `build.json` keeps the numbers of the keys it waits for (`key_ids`). A snapshot stored before the tracker
  kept them learns them once, at the next check (the build is indexed for it, a few minutes).
- **Every region's hotfixes**, as wago.tools collects them from players' caches (its `TactKey` and `TactKeyLookup`
  tables of the product). The hotfix cache the tracker reads is the US one; a key can reach Europe, Korea, Taiwan or
  China, or one uploader, first. When wago cannot be read it adds nothing.
- **The list of published keys** (wowdev's TACTKeys), which names the same keys a little later. When it cannot be
  reached, the keys from the hotfixes are still checked.

New hotfixes are followed at once by one more look at the build, so a key that came with them opens it in the same
check. A build read again keeps its own hotfix cache.

## The builds before: the changelog back to the first beta

The changelog compares each stored build with the one before it. With only the builds the tracker happened to see,
it starts the day the tracker was installed. `history` fills in everything before:

```bash
python tools/tracker.py history
```

It stores every build that came before the newest snapshot and has none, oldest first, and the changelog then goes
back build by build to the first beta: each build has its own page, with what it added, changed and removed against
the one before.

| Step | From |
|---|---|
| Which builds there were | The version server names the live build only. The list of the earlier ones, with the two config files that name each on the CDN, is wago.tools' (`[client] build_list`) |
| Their files | Blizzard's CDN, as for the live build, and checked the same way: each table against its content key |
| Which products count | The live product, and those `[client] history` names with the versions that count: `wow_classic_beta:1.60.` by default, because WoW: Forever's beta was shipped under the Classic beta's name. `off`: no earlier builds |

**And before the first beta.** The first beta build is compared with the original game, patch 1.12, which `history`
stores once with the earlier builds: [docs/VANILLA.md](VANILLA.md). With it the whole chain is checked at every
analysis: the original game and every build's changes must give the newest build.

**Light on purpose.** The live build is indexed whole, a few hundred MB. For thirty earlier builds that would be
gigabytes, so an earlier build is read for its tables alone (`ft.cdn.Earlier`): the list of pages of its encoding
file and the few pages that hold the tables' keys (ranged requests), its root file, and the archive indexes, which
the builds share (about 125 MB, once). A build is then some 50 MB to download, most of it its root file, and a
quarter of a minute; thirty builds are six minutes or so. Only the 25 tables the changelog compares are stored, about
15 MB a build (`build.json`: `"tables": "changelog"`): the tooltips, the Forge and the map read the newest build
alone.

**What can keep a build out.**

- A table with another layout than the tracker reads: the build is not stored, the reason is kept in
  `data/builds/history.json`, and it is asked again when the schema changes or with `--again`.
- Blizzard takes old builds off its CDN with time, host by host. Each host is asked; a build no host has whole any
  more is said in the log and asked again at the next check.

**Read with today's keys.** Content that was encrypted when a beta build shipped and has opened since is read as it
is now: a beta build shows what it carried, not what players could see that day. What is still locked stays hidden
in every build, and shows as added in the newest build the day its key comes out.

**Hotfixes.** No earlier build has its hotfix cache (the mirror keeps the live one only). A resource that exists by
hotfix alone therefore counts as known since the first of the builds in a row without their hotfixes, the first
beta build once the history is stored, and is never listed as added (see *What it does not do yet*).

**Kept once worked out.** Reading a build's tables takes a quarter of a minute or more. Two stored builds do not
change, so what one changed against the other is kept in the newer one's folder (`changelog.json`) and read back at
the next analysis; only the newest build is read each time. It is worked out again when a build is read again, its
hotfixes change, or the tracker reads tables another way.

**A build that changed nothing.** Blizzard often ships a build that changes the program alone: of the thirty builds
from the first beta to 1.60.1.70938, sixteen have the tables of the build before, byte for byte. Such a build is not
read at all; its page says there was no data change. The first analysis after `history` works out the others once:
a few minutes more than usual.

## When a build is refused

A table is read with the layout the tracker's schema describes (`tools/schema/db2-schema.json`, generated from the
core). When Blizzard changes a table's layout, reading it the old way would give nonsense: `fetch` then stores
nothing and names the tables. A layout counts as known when it is the one the same table has in the newest other
snapshot (the one the tracker reads today), or the one the schema names. The way out is the core's: once it supports
the build, run `tools/make_db2_schema.py` against it and fetch again. `fetch` exits 0 when it stored a build, 3 when
there was nothing new and 2 when it refused one.

## In the container

Every `FT_CLIENT_EVERY_HOURS` (6; 0: never) the container runs `fetch`, `hotfixes` (below) and `history` (above), and
the analysis after them when one of them stored something. The first check after this is installed stores every
earlier build, and the analysis that follows works them out: a quarter of an hour or so more than usual, once. The Forge says when each was last asked and what it answered, under the analysis
(`data/client-check.json`; a server that could not be read is shown as such). The first check comes a minute after the start's own analysis is over, the next
ones every `FT_CLIENT_EVERY_HOURS`. The check itself is a few small requests. The log is `data/client.log`. The
container needs to reach `us.patch.battle.net:1119` and Blizzard's CDN hosts.

## Check now

**Check the client now**, in the Forge next to **Run again**, does the same at once, and so does:

```bash
python tools/tracker.py check
```

It asks for the live build, then for the hotfixes, then for the earlier builds that are missing, and runs the analysis
only when one of them brought something new
(`--always`: whatever they brought; `--wowhead`: as for `analyse`). With nothing new it says so and ends in a few
seconds. A server that does not answer is said in the log and passed over: what is stored stays. Started from the
Forge, its lines are in the analysis log on that page, and nothing else can be started until it is over.

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

### Every day's hotfixes, kept

The mirror keeps only the newest cache, and so did the tracker: what one day's hotfixes changed was gone the next day.
Now every cache that differs from the one before is also kept, compressed (about 1 MB each), in
`data/builds/<build>/hotfixes/`, listed oldest first in `index.json`; a cache stored before this is taken in as the
first one. The newest is still `hotfixes.bin`, and it is what the analysis reads.

The changelog gets a step for each kept cache:

- the build is compared with the build before as it stood with its **first** kept cache;
- each later cache is an entry of its own, dated the day it was downloaded: what it added, changed or removed against
  the cache before (`/changes?build=70938&hotfix=1`, a dashed card on the home page's timeline). A resource a later
  cache adds is listed as added that day, also when it exists by hotfix alone;
- a cache that changed nothing the tracker compares gets no entry (the double check still follows it);
- the game's first build after the original game has no such steps: the original game is compared with it as its
  newest hotfixes give it (docs/VANILLA.md). With only the original game and the live build stored, the hotfix
  entries therefore appear once a later build is stored; the caches are kept all the same.

Each step is worked out once and kept next to its cache (`<cache>.changelog.json`). The double check replays the
hotfix steps with the builds, so the original game plus every build and every day's hotfixes must give today's game.

### Hotfixes back to the beta, dated from the builds

Today's cache holds every hotfix Blizzard still sends, back to the beta: about 750 pushes over some 57,000 rows (and
one push per item for the 5,000 items that exist by hotfix alone). It says nothing of when each came, and its push
numbers are not in that order. The builds do: Blizzard writes a build's hotfixes into the next client it ships. With
every build since the beta stored, `ft/dating.py` dates each row of the cache by the build that carries its value after
the last build that did not:

| the row                                  | its window                                                 |
| ---------------------------------------- | ---------------------------------------------------------- |
| the same in every build                  | sent again, changes nothing: in every build's cache        |
| first carried by build B                 | a hotfix to the build before B, live until B shipped       |
| carried by no build yet                  | a hotfix to the newest build                               |
| a record no build has at all             | there by hotfix alone: in every build's cache, never "added" |

A build Blizzard shipped with the very tables of the one before (a program-only build) does not end a window: the
window belongs to the first build of such a run, and the builds of the run carry its hotfixes. Each build then gets
two caches, written from today's cache with its own number in the header: the build as it shipped, and the build as
its window left it. The second is a hotfix entry of the timeline; the next build is compared with it, so what that
build only baked in is not counted twice. The newest build gets the build as it shipped first, then the caches the
tracker downloaded itself.

The work (minutes: every row against every build's table) is done at the analysis when the cache or the builds
changed, and kept in the newest build's `hotfixes/dated.json`; new notes only re-date the windows.

What the builds cannot give: the day inside a window, and a value a hotfix had before a later hotfix replaced it with
no client built in between (the cache keeps the current value only). The days come from the written notes.

## Notes: what Blizzard wrote, and the changes made on the servers

`tracker.py notes` (also part of every client check) stores, in `data/notes/`:

- **Blizzard's blue posts** (`blizzard.json`): every post of Blizzard staff in WoW: Forever's forums since August 2026,
  from the forums' own JSON (the "Blizzard tracker" list, then each post's whole text, once). The hotfix posts are read
  a day at a time ("November 13, 2026", then its topics and lines); the other posts (maintenance, known issues, "Dungeon
  XP adjustment") are kept as they are posted. They tell of changes made on the servers, which no client file shows.
- **Icy Veins' hotfix news** (`icyveins.json`): its WoW: Forever articles about hotfixes, patch notes and development
  notes, from its WordPress JSON API (category `wow-forever`; the site's own pages sit behind a bot check). Only the
  blocks where it quotes Blizzard are read, a day at a time, dated by the day the title names. Used where Blizzard's
  forum has no notes for a day, and linked from every day it covers.
- **ForeverChanges' patch notes** (`foreverchanges.json`, https://foreverchanges.pro/patch-notes): a line for every build
  and every hotfix day since the beta. Used only where neither Blizzard nor Icy Veins has the day, to fill gaps until the tracker's own
  sources say as much; shown under its name, and it never changes a value of the official list.

A hotfix entry of the timeline covers the days of its window and is named after them ("Hotfixes of Nov 10–12"); its
page lists each day's notes: Blizzard's, else Icy Veins', else ForeverChanges'. A line that names something the entry changed in the client's data is
marked "In the client data", any other "Server side". A window that changed nothing in the client's data but has notes
still gets its entry ("Server-side changes only").

A step can be turned back into data a test realm loads: [CHECKOUT.md](CHECKOUT.md).

## What it does not do yet

- **The day of a hotfix inside its window, and replaced values.** See "Hotfixes back to the beta" above. A resource
  that exists by hotfix alone is in no build's tables, so nothing says when it appeared: it is not listed as added
  (the changelog says how many there are), and it counts as known since the first build.
- **Wowhead as notes.** It has no dated list of WoW: Forever's hotfixes to read today.
- **Other locales.** The enUS tables and the enUS cache are read; a French snapshot still comes from the server's own
  copy.
