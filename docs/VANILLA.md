# The original game: where the changelog starts

The changelog went back, build by build, to the first beta build of WoW: Forever and stopped there. That build was
"the reference": nothing said what it had added to the game it was made from, what it had changed in it, or what it
had left out. The game it was made from is patch 1.12, and with it the changelog has a real start:

```
the original game (1.12)  →  first beta build  →  …every build…  →  today's build
```

The first beta build has a page like any other, with what it added, changed and does not have, against the original
game. And because every step is now there, the chain can be checked: the original game plus every build's changes
must give today's build (see *The double check*).

```bash
python tools/tracker.py vanilla
```

stores the original game once. The client check (`tracker.py check`, the container's own check, the Forge's *Check
the client now*) does it by itself, with the earlier builds.

## Which data stands for patch 1.12

**The client WoW Classic launched with in August 2019, build 1.13.2.31650.** It is patch 1.12, item for item and
spell for spell, published by Blizzard in the table format of today.

The 2006 client itself cannot serve. It has no item table and no quest table at all: the server sent those to the
client one by one, and every copy of them that exists today is somebody's reconstruction from recordings. Half of the
comparison would rest on that. The 2019 tables are Blizzard's own, and they are tables of the same kind as WoW:
Forever's, so a field means the same thing on both sides.

The tables are read as CSV from wago.tools' public exports (the source `tools/make_baseline.py` already reads) and
kept as they came in `data/builds/31650/enUS`. `build.json` says where they are from and marks the folder as the
original game (`"baseline": "vanilla"`). `[client] vanilla` names the build (`wow_classic:1.13.2.31650`); `off` leaves
the changelog starting at the first beta build, as before.

The original game has no mounts, pets, toys or achievements as tables: every one of them is an addition.

This is not the list behind the *New in Forever* tag. That one is the Classic Era client of today, Season of
Discovery included (`tools/baseline/classic-era.json`), because the question there is "what is new in Forever",
as Wowhead asks it. Here the question is "what changed since 1.12", and Season of Discovery's additions are changes.

## What is compared, and how

The tracker turns the 2019 tables into the rows its own reader gives for a build (the columns of
`tools/schema/db2-schema.json`, the same types), and reads the official content from them as from any build
(`ft.content.official`). Three things are written differently in the two games. Each is brought to a form both sides
have:

| What | Then | Today | Compared as |
|---|---|---|---|
| A spell effect's points | a base and a die: 13 and 9 sides, for 14 to 22 | the middle of the range, 18, and a variance | the middle of the range |
| An item's primary stats | the amount: +18 Strength | a share of the item level's stat budget | the amount, today's worked out as the tooltip does |
| An item's classes | a mask of the nine classes | -1 for everyone, and bits for classes the original game did not have | over the nine original classes |

One thing is left out: a flight point's flags. Then every node had the same value, today each one's side is in it.
The values mean different things, so they are not compared.

Everything else is compared as it is: names, quality, item level, required level, slot, binding, set, prices, text,
required skill, spell names, ranks, descriptions, effects, levels, recipes' skill ranks, talents' places and texts,
instances, bosses, zones, quest ids.

**Checked against the game.** The stat amounts were checked on the first beta build: of 12,590 items both games have
in their tables, the worked-out amounts equal the original ones for all but 426, and those 426 are real changes
(sampled against Wowhead's live tooltips: Tranquil Orb +8 → +9 Spirit, Thorium Helm gained +18 Stamina, Bloodband
Bracers lost its Stamina). The same check found that the tooltips took the wrong budget column for bows, guns, thrown
weapons and wands: WoW: Forever keeps the original game's ranged column for them. All 37 unchanged ranged weapons with
stats give the original amounts with it and none with any other; the tooltips use it now.

## "Not in Forever" is not "removed"

Against the original game the third count cannot be called *removed*. What the original game had and WoW: Forever's
data does not have is three different things, and the data cannot tell them apart:

- content Blizzard took out (unused spells, test items);
- content that is **not released yet**: the loot of the later raids is not in the client and not in its hotfixes.
  Most of the absent items are these (Pauldrons of Might, Ashkandi, Perdition's Blade);
- content the client carries **encrypted**: `build.json` of the first build knows how many records are still locked,
  and the page says so. An original resource among them reads as absent until its key is out.

So the page says *Not in Forever*, and a resource's own page says "the original game had it; WoW: Forever's data does
not: Blizzard took it out, or it is not released yet". When such a resource arrives later, the build that brings it
lists it as added.

Removed spells that nothing taught or used (no class, no profession, no talent, no item: creatures' spells and
leftovers) are kept off the page unless *Internal / test* is switched on, like every other internal resource.

## What exists by hotfix alone

Thousands of the original game's items are in no table of WoW: Forever. They reach the client by hotfix
(docs/CLIENT.md). The first beta build's tables do not have them, but nothing says the game ever lacked them, and the
first hotfix cache the tracker holds is of a later build.

Such a resource is **never called absent**. It is compared with the original game as its hotfix stands today, and
what differs is listed with the first build, where every other difference from the original game is. The page says
how many resources that is. One of them that the original game did *not* have is not called added either, here as in
every other build: nothing says when it appeared.

## The double check

At every analysis the chain is replayed (`ft.content.replay`):

1. start with what the original game has;
2. apply what each build is said to have added and removed, in order;
3. the result must be the newest build, resource for resource.

From the first build of WoW: Forever on, the content is followed too, not only the ids: each build keeps a
fingerprint of every resource it brought or changed, and a resource no build says it changed must still be what the
first build had.

The analysis log says the result in one line, and the page of the first thing stored (the original game's, or the
first build's without it) shows it by kind:

```
replay: the original game and the changes of 30 build(s) give build 70938 exactly (68349 resources)
```

When it does not add up, the log names the first resources that differ and the page shows them. That means a step is
missing, or a kept step is not what the builds say: the kept steps are worked out again when a build is read again
(`data/builds/<build>/changelog.json`; removing the file forces it).

What the replay proves: the changelog is complete and consistent, every resource of today's build is accounted for by
the original game or by the build that brought it. What it does not prove: that the tables were read right in the
first place. A column read wrong would be wrong the same way in every step.

## What it does not cover

The changelog compares what the **client** carries: what exists, and what it is. Where a creature stands, what it
drops, who sells an item and who gives a quest are not in any client build, the original game's included. Those come
from the server's database and the sources (docs/SOURCES.md), and their history is the world build's (docs/WORLD-BUILD.md),
not this one's.
