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

## Tests

```bash
python -m unittest discover -s tools/tests
```

Standard library only, no database and no network: the registry's rules (a source without a licence is never public,
witness groups, the most restricted use wins) and every pin type against recorded answers.
