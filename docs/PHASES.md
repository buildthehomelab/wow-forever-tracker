# Release phases

The official client carries content the game has not opened yet: the later raids sit in the client months before
their release. Without phases the tracker lists their bosses, loot and quests as missing, and the work list mixes
what players can't get today with what nobody can get yet.

A **release phase** groups that content. Until the phase opens, what it brings shows as **Later** instead of missing.
It stays out of the coverage figures and the work list, but you can still browse it.

## The phase list

`tools/phases/forever.json` lists WoW Forever's phases in release order:

```json
{
 "phases": [
  {"key": "first-raids", "name": "First raids", "opens": "2026-12-09", "maps": ["Onyxia's Lair", "Hyjal Summit", "Barrow Deeps"]},
  {"key": "later-raids", "name": "Later raids", "opens": null, "maps": ["Molten Core", "Blackwing Lair", "..."]}
 ]
}
```

| Field | Meaning |
|---|---|
| `key` | Short name, used by `[phases] current` |
| `name` | Shown on the badges and the overview |
| `opens` | The day the phase opens (`YYYY-MM-DD`), or `null` while no date is announced |
| `source` | Where the date or the list comes from (shown on hover) |
| `maps` | Instances, by English name or map id |
| `npcs` | Creatures, by id or English name (world bosses, event creatures outside an instance) |
| `objects`, `quests`, `items` | Ids, for what the rules below miss |

You only list the instances. The analysis works out the rest from the server's data:

- the instance's **bosses**, and the **creatures and objects** spawned only inside tagged instances. A creature not
  spawned yet counts if it has a boss's name, or if the locator placed it there.
- an **item** whose sources all belong to a phase: creature loot (reference tables included), vendors, chests,
  quest rewards, containers and crafts.
- a **quest** whose givers (its starting item included) or enders all belong to a phase, or one of whose objectives
  does. A quest sorted under a tagged instance belongs to its phase too, unless both a giver and an ender stand in the
  open world: an attunement sorted under its raid stays open.
- a **spell, recipe, mount or pet** that only tagged items or quests teach, and a **toy** through its item.

One source in the open world keeps a thing released: a trainer, fishing, a vendor outside, or a creature that also
stands outside. When a thing has sources in several phases, it opens with the earliest one. Anything the rules can't
place stays a normal gap. The tracker would rather show one gap too many than hide a real one.

The analysis log lists what each phase tagged. It also names any instance in the list that the client doesn't carry:
an encrypted map, a renamed one, or a typo.

An encrypted instance has no name to match, so list it by map id. The shipped file does that for map 3002: the client
has no Map row for it but two raid encounters on it, so it is one of the two new first raids.

Editing the list needs a new analysis (the Forge's *Run again*). With Docker, set `FT_PHASES_FILE` to use another
file. The container analyses again once at its next start whenever the list's contents change: another file, or a
new image that ships new dates.

## Which phases are open

The website decides this each time a page loads, so a phase opening needs no new analysis:

- by default, each phase opens on its own `opens` date. A phase with no date stays closed, without holding back
  the others.
- `[phases] current` in `config.ini` (`FT_PHASE` with Docker) overrides the dates for a realm that runs ahead of or
  behind the official game. It takes a phase key (`first-raids`: that phase and every one listed before it), a number
  (`1` = the first phase, `2` = the first two), `all` (every phase open, as before) or `none` (only launch content).

## Where it shows

- **Overview**: coverage counts only open content. A notice lists the gaps each later phase will bring.
- **To add**: lists open content by default. *Later phases* lists what the closed phases will bring, and
  *Everything* lists both. The CSV gets a `phase` column.
- **Catalogue**: a *Later* tile and status filter. The other filters count open content only.
- **Resource pages, tooltips, search**: a blue badge naming the phase, and a tag with its date.
- **The Forge, Items tab**: leaves later items out by default, because selling them at a vendor would release them
  early. The *Later phases* switch shows them.

A resource the server already provides keeps its *Available* status, even if its phase is closed.

## Instances Forever does not use

Some instances in the client will never open in WoW: Forever, so they get no phase. These are Season of Discovery's,
which the Classic Era client gained after the original game (The Tainted Scar, Karazhan Crypts, Scarlet Enclave...), and
the original game's unused Emerald Dream and Caverns of Time maps. The analysis lists them and their bosses under
*Internal / test*, like the items Wowhead marks as Season of Discovery ones. The rule is in `tools/ft/baseline.py`
(`season_map`): an instance above the original game's ids that is in the Classic Era client.

The same goes for boss rows that are no boss of their own (`tools/ft/bosses.py`): Season of Discovery's raid versions of
Blackfathom Deeps, Gnomeregan and the Sunken Temple, and a fight the client lists again in the same instance (the
lowest id is the one counted). A boss also counts as present when a script brings it in instead of a spawn row: a
summon group, a SmartAI summon or a summoning spell names its creature, or the creature has a C++ script in an
instance that has one. Its page then says "Not spawned: a script brings in creature N". Encounters named after an
event (The Seven, Ring of Law) are found by one of their creatures.

Also under *Internal / test*: a boss of a test instance, placeholder mounts, pets, toys and recipes (`[PH] ...`), and
flight points nobody flies from: boats, zeppelins and script targets of the original game (no faction can use them),
and a battleground's own nodes. Unnamed recipes stay visible: no name is no reason to hide them.
