# Gathering what is still to come

A release phase that is not open yet ([PHASES.md](PHASES.md)) shows its quests, items, bosses and dungeons as
**Later**. Their world rows can wait until the phase opens. Their data should not: Wowhead's pages are read one every
10 to 30 seconds, a recording can disappear, and the day a raid opens is a bad day to start reading. So after each
analysis the tracker writes a **work list**: per phase, what each thing needs and which source already holds it. The
crawl and the Icy Veins import read what it names, so the data is fetched and kept before the phase opens.

The open game is on the list too, as **Open now**: the official quests the server has no record of, and the
creatures, objects and items that the server's own quests wait for.

## What is listed

| Thing | Listed when | What it needs | Sources read |
|---|---|---|---|
| Quest | Later and not done; or open and without a record on the server | its record, who gives it, who takes it, what it asks | EG Link (record, objectives, who offered and took it), QuestieDB (`startedBy` / `finishedBy` and the npc and object corrections), Icy Veins (`addon_givers`, start items, quest items), Wowhead's quest page (Quick Facts *Start* / *End*) and the *Starts* / *Ends* tabs of npc, object and item pages |
| Creature, object | a listed quest names it (giver, ender, objective), a listed item drops from it, Wowhead's lists place it in a later phase's instance, or an open quest's check says "not spawned"; and the server has no template or no spawn | a template and a place, a model | EG Link creature and object records and sightings, Icy Veins' entity and `addon_points`, Wowhead's page (map pins, model display ids) |
| Item | Later and not done; a listed quest asks for it or starts with it; an open quest's check says "not obtainable" | where it comes from | Icy Veins' `addon_dropped_by` / `addon_sold_by`, Wowhead's item page tabs |

A thing is **ready** when its sources hold enough to build its rows: a quest with a record (on the server or EG Link)
and a giver and an ender; a creature or object with a template (on the server, EG Link or Icy Veins) and a place (a
spawn, EG Link sightings, Icy Veins points or Wowhead pins); an item with a source. Nothing is guessed: a thing no
source names stays not ready.

Items Wowhead names no source for (the phase marked `wowhead_no_source`, *Not out yet*) are listed but not queued
again here: the crawl already reads their pages again as gaps (WOWHEAD-PAGES.md).

## Where it comes from and goes

- **The analysis** (`tools/ft/gather.py`, at the end of `tracker.py analyse`) reads the tracker's own results
  (`ft_entities`: what is not ok, with its phase), the world database (which quests, templates and spawns exist), and
  the sources' files the website keeps: EG Link's (`data/eglink/<commit>`) and QuestieDB's (`data/questie/<commit>`)
  of the commits their imports read last, the Wowhead page cache (`data/wowhead-pages`), the Icy Veins mirror
  (`data/icyveins`). It downloads the EG Link datasets (quest records, who offered and took them, creature and object
  records, sightings) and QuestieDB's quest, npc and object corrections of those same commits when they are not there
  yet. It writes `data/gather.json`. It never stops the analysis: a source it cannot read is logged and left out.
- **The Wowhead crawl** (WOWHEAD-PAGES.md) reads the pages the list names: the open game's in tier `gap`, a closed
  phase's in tier `later` (after the items that only lack a source, before the server's missing data), the earliest
  phase first. A phase that opened since the analysis counts as open. Pages the cache holds and that are not due again
  are left out; a creature's or object's page read before models were kept is read again.
- **Import Icy Veins** (ICYVEINS.md) asks the answers the list wants, right after the gaps and before the rest of its
  mirror.
- **The Forge › Later** (`admin/later`) shows the list per phase and kind, with what each source holds;
  `admin/later?format=json` gives the whole file, for the world-data branch made the day a phase opens.

The next analysis after a crawl or an import reads the new pages and answers, so the list follows them.

## Tests

- `python -m unittest tools/tests/test_gather.py`: the sources read into relations, the list and its pages.
- `php tools/tests/test_wowhead_pages.php`: the list's pages in the crawl's queue and tiers, and the Icy Veins ids.
