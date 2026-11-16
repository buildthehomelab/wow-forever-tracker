# What the sources said

Every import turns its source into the same evidence: who drops, sells, teaches, gives or takes what. Each run now
keeps that evidence in the tracker's own database, so what a source said is never thrown away after one card:

| Table | Holds |
|---|---|
| `ft_source_snapshots` | one row a run of a source: its version (a commit, a file, a date), when it ran, how many facts it said, and how many of them were new, changed or gone since its run before |
| `ft_source_facts` | one row a fact (`drop`, `sell`, `start`, `end`, `train`): the creature or object (`kind`, `entity`), the item, quest or spell (`target`), the value (a drop's chance, a vendor's stock, a trainer's cost) and the rest of the source's row (`extra`), with the first and the last snapshot that said it |

A fact said again with the same value is carried on (its `last_snapshot` moves); a new value is a new row, the old one
ending at the run before. So the database holds the whole history of every source without a copy per run, and
`WHERE source = 'icyveins' AND first_snapshot = <its last run>` is what Icy Veins added last time.

**Private by design.** The facts live in your tracker's database, as the raw copies of the sources live in `data/`:
neither is ever in the repository. Whoever wants them runs the tracker against the sources. Only the rows a card
exports to a data repository ([DATA-REPO.md](DATA-REPO.md)) are published.

## On the Imports page

*What the sources said* lists each source's last run against the one before: its facts, how many are new, changed and
gone, and the first of them.

## Gaps only

Some imports ask their source only about the gaps (`scope` = `gaps`): NorgannonDB, the original game's database, and
Wowhead's and Wowhead Classic's pages (of their npc and object pages, only the drops worth a row). What such a run did
not say is not gone, only not asked: its facts are carried on, and the page shows no *Gone* for it. The other sources
are read whole (`scope` = `all`).

## Not yet

- The import cards are still made from the sources, not from these tables.
- A source's raw copy in `data/` is still kept as each importer keeps it (some only the files they read).
