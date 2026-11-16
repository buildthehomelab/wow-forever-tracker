# What the sources said

Every import turns its source into the same evidence: who drops, sells, teaches, gives or takes what. Each run now
keeps that evidence in the tracker's own database, so what a source said is never thrown away after one card:

| Table | Holds |
|---|---|
| `ft_source_snapshots` | one row a run of a source: its version (a commit, a file, a date), when it ran, how many facts it said, and how many of them were new, changed or gone since its run before |
| `ft_source_facts` | one row a fact (`drop`, `sell`, `start`, `end`, `train`): the creature or object (`kind`, `entity`), the item, quest or spell (`target`), the value (a drop's chance, a vendor's stock, a trainer's cost) and the rest of the source's row (`extra`), with the first and the last snapshot that said it. What else a source gives is kept too, so that its card can be made again: Icy Veins' quest texts (`text`), its NPCs' services (`service`) and its quest-only drops (`quest_drop`), each row whole in `extra` |

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

## Cards from the database

A card can be made from a source's last snapshot instead of from the source: nothing is downloaded or asked, so it
takes seconds where Icy Veins takes hours, and it is made against the gaps and the server as they are now. After a new
analysis, *Make every card from the database* (The Forge › Imports, *What the sources said*) makes every source's card
again; each row's *Card* button makes one. From the command line: `php tools/source-import.php <source> --from-database`.

- Wowhead, Wowhead Classic, EG Link, ForeverDB.net, Icy Veins, AtlasLoot and NorgannonDB. ForeverChanges and the
  original game's database are read from a pack you sent, kept in `data/`: their *Read the pack again* asks nothing
  either.
- NorgannonDB's second sources (its vendors and drops need one) are EG Link's and ForeverDB.net's last snapshots, Icy
  Veins' cache and the last AtlasLoot download: nothing is downloaded for them either.
- EG Link's card also reads its quests again (`tools/tracker.py refresh quests`) from the recording of that commit
  in `data/eglink`, as the import does.
- A source asked about the gaps only (`scope` = `gaps`) knows only what those gaps asked: after an analysis that found
  new gaps, import it from the source again for them.

## Not yet

- A source's raw copy in `data/` is still kept as each importer keeps it (some only the files they read).
