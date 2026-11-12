# Data repository export

Point the Forge at a test realm's databases, apply and test fixes there, then export the ones that work as **world
update files** for a data repository: the same kind of file the core's updater applies from `sql/custom/world/`. The
live realm then gets them the way it gets the rest of its world data, through a reviewed commit, never through the
Forge.

## Exporting

*History* (Forge › History):

- **Data repo .sql** on an applied operation downloads its file;
- **All applied, as data repo files** downloads every applied operation as a zip (`sql/world/<name>.sql`);
- `php tools/datarepo-export.php <operation id>|all <folder>` does the same from the command line (an existing file
  of the same name is left alone).

Rolled-back and failed operations are never exported.

## What a file holds

The rows the operation added, **as they are on the server now**. The export reads the operation's rollback (it names
exactly the rows the operation added) and selects those rows again, every column. A row corrected by hand after the
Forge added it is exported corrected; a row deleted since is left out.

- `hotfixes` rows are not exported: the files are world update files only.
- Flags and empty columns the operation set (a vendor flag) are exported as updates that only touch rows still
  lacking them.

Name: `YYYY_MM_DD_900_world_everlake_forge_<operation, 5 digits>_<kind>.sql`, the date the operation was applied.
NN 900 keeps Forge files after the other files of the same day; the operation number keeps them unique and in order.

## Rules the files follow

- **Running a file again changes nothing.** Each table's rows go through a temporary stage table; rows whose primary
  key already exists are dropped, then the rest are inserted.
- **Rows that need a parent are dropped when the parent is missing**: `trainer_spell` without its `trainer`,
  `npc_vendor`, `creature`, quest starters and enders without their template, `gameobject` without its template.
- **Spawns get fixed guids**, `910000000 + operation × 10000 + n`, never `MAX(guid) + 1`, so a file never depends on
  what other files or the core added before it. A spawn is skipped when the same creature or object already stands
  within 5 yards on the same map (the test realm's own copy included), or when its guid is taken.
- **Every added row is recorded** in `everlake_import_rows` (table, key, file, `Forge #<operation>`), when the table's
  key is at most four numbers.
- **A deployed file is never edited**: the updater would run it, and every later custom file, again. A later fix is a
  new operation and a new file.

## Before you commit

Check the data repository's open pull requests for the same rows: the files skip rows that already exist, so an
overlap cannot insert twice, but two pull requests for one fix waste a review.
