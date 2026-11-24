# Changelog

## Unreleased

- **The Wowhead import writes zones' fishing.** Fishing was counted and left out ("a zone's table: not written by this
  import"), so the realm's new zones had no fishing table and caught nothing (Mount Hyjal, the Riverglades). Their
  weighted catches had no source either (the lobsters and mightfish of Azshara, the salmon of Winterspring). An item
  page's *Fished in* tab and a zone page's *Fishing* tab now give `fishing_loot_template` rows under the zone, in one
  group, at the same counts as a drop. A zone with no table takes its page's whole table; one with a table takes the
  gap items. The crawl queues the page of every zone with no table and of every zone a gap item is fished in.

- **A dummy aura the realm already uses is not flagged.** The spell check counted every dummy aura as code nothing ran.
  Two kinds work without a script. One is an aura that conditions ask for: the Argent Dawn Commission's Scourgestones
  drop only while it is worn, through about 170 loot conditions. The other is a dummy aura that names a trigger spell
  and procs: the core casts that spell itself (Fist of Stone restoring mana). Both now pass, with the reason on the
  spell. The container analyses again once (marker 47).

- **A chest's personal loot counts as a source.** The analysis read only a chest's shared loot (`Data1`), but the core
  also fills `chestPersonalLoot` (`Data30`, each player's own) and `chestPushLoot` (`Data33`, straight into the bags).
  The supply cart at Ariden's Camp gives Recipe: Plated Armorfish through personal loot alone
  (wow-trinitycore-everlake#136), so the recipe stayed "no source". The locator's chest query reads them too. The
  website's source pages still read `Data1` only. The container analyses again once (marker 46).

- **Spells WoW: Forever made need a teacher of their own.** A spell nothing teaches passed as "the original game taught
  it nowhere either" whenever its id was below the cut-off for new spells, even when the original game never had it:
  Lacerate's ranks 1-3 (24118-24120) passed while no hunter trainer taught them (fixed in
  wow-trinitycore-everlake#135). A spell that neither patch 1.12 nor the Classic Era client has is now Forever's own,
  and the Classic database cannot speak for it. A seal's judgement still passes: the seal's dummy aura names it in its
  points (Seal of Fury 20163 names Judgement of Fury 20183), and the analysis now reads that as "spell 20163 casts it"
  when both are of one skill line. And a spell a quest taught in the original game passes when the realm has that
  quest and it now rewards something else: Badlands Reagent Run II (2501) teaches Greater Mender's Potion on Forever,
  not Restorative Potion. The container analyses again once (marker 45).

- **Talents the core handles without naming them pass.** Seal of Command's judgement is read from the core's
  `ClassicSealJudgements` table, which `tools/make_core_spells.py` now reads, along with any table whose name says
  spell, seal, aura, talent or judgement: 158 more spell ids, Seal of Command's five ranks among them.
  `tools/world/reviewed_dummies.json` lists dummies checked by hand that need no code, with the reason shown on the
  spell: Anger Management (aura 85 does the work), Improved Imp (a leftover of Improved Firebolt's value) and Improved
  Weapon Totems (baseline in Forever). The other six Incomplete talents get scripts in the core
  (wow-trinitycore-everlake#133). The container analyses again once (marker 44).

- **Forge: Always up.** A new page lists creatures that stand in the world all the time when a script or a holiday
  should bring them in only for a while (docs/SPAWNS.md, section 7). *Summoned, yet always up*: a script of the
  server summons the creature (SmartAI, a summon group, an event script, a summoning spell, the core's C++) and none
  of VMaNGOS, AzerothCore or TrinityCore 3.3.5 keeps it spawned; later creatures, which no reference can know, have a
  tab of their own. *Holiday, yet up all year*: the references spawn it only through events, and the server already
  gates some of its spawns or the event is a yearly holiday. On Everlake's test realm it found Unbagwa's gorillas,
  Ishamuhale, Echeyakee and the Undercity warlock scene standing for good. The spawn audit's reference packs now
  keep which creatures a world spawns only through events (format 3): they are downloaded again once.

- **Imports: a recorded turn-in text that calls the player by a class or a race is not taken.** A recording shows
  what one player's client printed, so where the game's text says `$c` or `$r` it holds that player's own class or
  race: Icy Veins' text for Swift as the Wind, a quest for trolls of any class, came in as "Spirits be with ya,
  rogue." Such a text is now left out and counted on the card (*text_names_class_or_race*). Only a word set off as an
  address counts ("…, rogue." or "Hunter, …"), so a class or race that is merely spoken of passes; and a quest kept to
  that one class (its sort or `AllowableClasses`) or that one race may say it ("Yes, rogue?" in a rogue quest). Of
  5,000 Icy Veins texts held today the rule sets 12 aside. ForeverChanges' texts already went through a stricter check.

- **Imports: a turn-in row without words gets its words.** A source's turn-in text (Icy Veins, ForeverChanges) was
  offered only for a quest with no `quest_offer_reward` / `quest_request_items` row at all: a quest whose row exists
  but holds no text (River Ends) was counted as known and never filled, so it stayed *no turn-in text* for good. Such a
  row is now filled through the Forge (only while the column is still empty; the rollback empties it again). A row
  that holds words is left as it is, as before.

- **Later phases: what a closed raid's quests hand out waits with the raid.** Three gaps in the phase rules left raid
  content on the launch work list while the realm keeps the raids closed. (1) A quest's `StartItem` counted as given by
  the quest even when that item is what starts it (Head of Onyxia, Head of Nefarian, Heart of Hakkar, Head of
  Ossirian, the Ancient Petrified Leaf): the item and its quest released each other. Such a quest no longer gives its
  own start item, so both wait with the raid the item drops in. (2) An item nothing gives, that only quests outside
  the official list reward (the old numbers of the Ahn'Qiraj and Naxxramas set turn-ins, Zul'Gurub's enchants), now
  waits with those quests when every one of them waits for a phase; such a quest still releases nothing. (3) A Proper
  String and The Fate of Ramaladni join *Later raids* by hand. The phases file changed, so the container analyses
  again once.

- **QuestieDB: a subtraction in its data no longer stops the import.** QuestieDB's Forever quest fixes now write
  `raceIDs.ALL_HORDE - raceIDs.UNDEAD` (Compendium of the Fallen). The Lua data reader knew only `+`, refused the
  whole file, and the analysis' *Later* step logged "QuestieDB not read". `a - b` now reads as `+` does: worked out for
  two numbers, else kept as the text `a-b`. All 13 Forever files at QuestieDB's current commit read.

- **The core's spells read again from core b1a2ea9935** (Karrz 0.1.39, the PTR's new core).
  `tools/world/core_spells.json` gains 13 spell scripts (4 more with a proc hook) and 36 spell ids net, among them
  Vindication, Remorseless Attacks, Improved Berserker Rage and Oath of Light, which the *script* check counted as
  handled by nothing, and item proc scripts (Fatal Wound, Pendulum of Doom, Toofbreak, the rend bonus). The container
  analyses again once (marker 42).

- **Spawn audit: three things it could not see.** Checked by hand, none of the six creatures it listed as below every
  reference was a gap. (1) A spawn a world event only removes was left out with the event spawns: Pyrewood Village's
  day guards (Watcher, Sentry, Elder) read as 0 spawns although all 45 stand except at night. Only what an event adds
  is left out now, on the server's side and in the references. (2) VMaNGOS keeps 40 spawns it never spawns
  (`spawn_flags` 2, disabled), such as 12 Water Spirits: they are no longer counted. (3) Fewer than a 3.3.5 core
  alone, where the 1.12 world never had the creature (Invisible Stalker, a later trigger), is not *below every
  reference* any more. The reference packs are made again (format 2) and the container analyses again once
  (marker 41). docs/SPAWNS.md.

- **Spawn audit: a creature a script picks at spawn is counted as each of them.** Blackwing Lair's world stores 200
  Corrupted Red Whelps and the instance script rolls one of the four colours when one spawns. The audit read the
  stored entry only: the red whelp as above every reference (134 up against 50) and the green, blue and bronze ones as
  missing. `tools/world/spawn_picks.json` now lists such spawns and the audit counts a row as a spot of each entry it
  may become, a share of one up for each, as it does for a spot that lists several creatures. The whelps read 33.5 up
  each, within the references (VMaNGOS 50, AzerothCore and TrinityCore 40). The container analyses again once
  (marker 40). docs/SPAWNS.md.

- **Procs: a script that runs the aura on a timer passes.** Poised (rogue 1328825, druid 1328829) failed the *Procs*
  check: its aura is a proc trigger with no `spell_proc` row and no client proc flags. Its script makes the aura
  periodic instead and gives the buff every second at full Energy out of combat, so it works and needs no proc; a
  `spell_proc` row would only wake the unused combat proc. `tools/make_core_spells.py` now records the scripts that
  make an effect periodic (`DoEffectCalcPeriodic`, `periodic_scripts`); such a script without a proc hook passes the
  check. The container analyses again once (marker 39).

- **Spawn audit: how many of each creature are up, against three other worlds.** *The Forge › Spawn audit* counts,
  per creature and map, its spots (where it can stand) and how many are up at one time (a pool shows only some of its
  spots), and sets them against VMaNGOS (patch 1.12), AzerothCore and TrinityCore 3.3.5. A creature with more up
  than every reference is listed first, with the spawns that stand where no reference has it: an import that laid a
  second spawn set over the first shows there (on the PTR's world, Young Wendigo: 14 against 5 in all three). The
  *Crowded* check could not see it, because its Classic witness is a list of points, not of what stands at once.
  More spots are not the fault; the fix is a pool that keeps the reference's number up. The references are downloaded
  once and kept as small packs in `data/spawnrefs`; the image gains `7zip` for TrinityCore's archive.
  `python tools/tracker.py spawn-audit` runs it alone. The container analyses again once (marker 38). docs/SPAWNS.md.

- **A player's spell that does nothing is Incomplete.** A talent, a class ability or an item's spell whose effect is a
  dummy or script effect only code runs used to pass with a weightless "to check" hint: Vindication, Improved
  Berserker Rage and Unsealed Wrath scored 100 while they did nothing on the server. The spell check now counts it
  (weight 2) when nothing handles it: no SpellScript bound in `spell_script_names` that the core registers, the
  core's C++ does not name the spell, and no SmartAI reacts to being hit by it. A new *Procs* check fails an aura that
  acts only when it procs (a proc-trigger aura, or a script that waits for a proc) with no `spell_proc` row and no
  client proc flags the core accepts. Creatures' and internal spells keep the hint. What the core's C++ does is read
  once by `tools/make_core_spells.py` into `tools/world/core_spells.json` (core 01783245fb); run it again when the
  core moves. On the PTR data: 120 player spells go from OK to Incomplete (15 talents, 4 class spells, 99 item
  spells), and 14 talents. The container analyses again once (marker 37). docs/ARCHITECTURE.md.

- **ForeverChanges: the transmog placeholders are never asked for.** The site refuses its item pages for the client's
  transmog placeholders (`transmog-ui-chest-item`, `transmog-ui-trim-head-item` ...) with 403. A refusal stops a
  visit, so each one cost a visit of its own (one every six hours) and nothing else was read meanwhile. They hold no
  vendor or drop. Any other refusal still stops the visit. docs/SOURCES.md.

- **ForeverChanges: a refused page no longer stops every visit.** A page the site refuses (401, 403, 451) still
  stops the visit, but it is noted first. It was not, so the next visit began with the same never-read page and
  stopped on it again: on 2026-11-22 one item page answered 403 and the visits after it read nothing new. It is asked
  again with the rest after two weeks; a page read before keeps what it said. docs/SOURCES.md.

- **ForeverChanges: a visit cut short still counts.** A visit writes the pack every 500 files
  (`[foreverchanges] pack_every`, `--pack-every`; 0: only at the end), not only when it ends. A visit is two hours or
  more now that it reads the whole site, and a restart (a redeploy) used to lose its card: its files were kept, but
  nothing reached the database until a later visit finished. The next visit now sees a pack no card was made of
  (`data/foreverchanges/carded` notes the pack each card was made from) and makes that card, its snapshot and its
  answers first. docs/SOURCES.md.

- **Crowded asks every live witness.** Extras › Crowded judged a creature's spots against Wowhead's map pins (and
  Classic's count) alone. Wowhead marks only what its visitors saw, so a well-filled zone looked crowded. It now
  takes the most spots any live witness shows there: Wowhead's pins, QuestieDB's Forever player traces and hand
  fixes, and EG Link's sightings (sightings within 10 yards merge: one mob is seen again and again). The note names
  each witness's count. The container analyses again once (marker 36).

- **ForeverChanges: the whole site, the gaps first.** A visit of foreverchanges.pro no longer stops at what the last
  analysis lacks: after the gaps it goes on through the other maps' data files, every other quest page and every
  other item page (about 20,000 files), the never-read first, then the oldest read. Everything read goes into the
  pack, the card's snapshot (`ft_source_facts`, source `foreverchanges`) and the answers table, so it can be queried.
  This reverses the decision of 2026-11-16 to read only the gaps. The pace and the rules do not change (robots.txt,
  one request at a time, the pacer, stop on a refusal); a visit reads up to 3,000 files (`[foreverchanges] limit`,
  was 1,500) and the container visits every 6 hours (`FT_FOREVERCHANGES_EVERY_HOURS`, was 24): a first full pass
  takes two to three days. `[foreverchanges] whole = 0` (`--gaps-only`) reads the gaps alone. docs/SOURCES.md.

- **Extras › Crowded counts spots, and asks Classic too.** A pool's member now counts as its share of the pool's
  spot (VMaNGOS random-entry spots are five rows of which one ever stands: the Bloodscalp trolls, Woodpaw gnolls,
  Plaguehounds), copies on one spot count once (a pack), and a creature is crowded only when it also passes the count
  Classic had, from QuestieDB's converted Classic base (`data/Forever/foreverNpcDB.lua`, downloaded once into the
  pinned QuestieDB folder; without it Wowhead judges alone, as before). Wowhead's map merges spots that stand close,
  so Classic zones' mobs ran two to ten times its marks and filled the tab: Prairie Wolf 116 where Wowhead marks 56
  and Classic had 118, Nethergarde Miner 151 / 15 / 130. On Everlake the tab goes from 171 to about 25, nearly all
  Forever-only creatures that imports placed. Next analysis. docs/FORGE.md.

- **Every source's answers in one table, whole.** The Wowhead table becomes the answers table, `ft_source_answers`,
  and every outside source now writes to it: Icy Veins (each API answer, the whole answer too: the mirror on disk
  keeps only the parts the cards read), ForeverChanges (each page or map file the visit read: what a page states and
  its text), and every file of the version an import downloads of QuestieDB, NorgannonDB, EG Link, ForeverDB.net and
  AtlasLoot, and of the VMaNGOS and Classic database packs you send. A large file is cut into records (an entry of a
  Lua table, a key of a JSON file: an EG Link creature's loot, a vendor), so that a new version moves `changed_at` of
  the records it changed only, and what it dropped becomes `gone`. Everything a source said can be read with SQL
  (The Forge › Query), not only the facts that reach `ft_source_facts`. `due_at` follows each source's own rules
  (Icy Veins 14 days, 7 for not known; ForeverChanges `[foreverchanges] older`; a downloaded version never by
  itself). Rows land as the answers come; `php tools/source-answers.php backfill` (replaces `tools/wowhead-db.php`;
  the container at start, the analysis at its end) writes what the files already hold, the newest version of each
  downloaded source the first time. `ft_wowhead`'s rows move in (`source = 'wowhead'`) and the old table is dropped.
  No new analysis. docs/SOURCES.md, *The answers table*.

- **Every Wowhead answer in a table, the whole page too.** The tracker's database has a new table, `ft_wowhead`: a
  row for every tooltip and every page the crawler read, with the answer, its name, when it was fetched, first seen
  and last changed, and when it is due to be read again. The crawler (record version 3) now also keeps the whole
  page: names, the page's text, Quick Facts with their links' text, every tab row whole, the map, the names its links
  give; the cache files keep the facts as before, the whole page goes to the table only. Comments and other user
  content are never kept. `changed_at` moves only when Wowhead's answer changed, so *what changed since* is a query
  (The Forge › Query). Pages due again by `[wowhead] refresh_days` / `recheck_days` go to the crawl's queue
  (`[wowhead] recheck_pages`, 300); the tracker still never asks Wowhead for a page. Tooltips of creatures and
  objects now keep their text. The container fills the table from the files at start (`php tools/source-answers.php
  backfill`); no new analysis. docs/WOWHEAD-PAGES.md.

- **Old twins are weighed by distance.** A name is no proof that one creature stands twice (chickens, credits and
  snakes share names across the world): Extras › Old twin now lists by guid only the spawns that stand within 15
  yards of a spawn of the live entry, on the same map, phase and world events, and *Removals as SQL* removes only
  those, checking the distance again when the file runs. Before, it removed every spawn of an entry whose live twin
  stood anywhere, Stratholme's 42 Mangled Cadavers included. The other spawns are listed by entry and left alone.
  The container analyses again once (marker 35).

- **Invented lists stand-ins, not Blizzard's decorations.** Wowhead lists only the objects players use: a campfire,
  a chair, a door or a holiday pumpkin is on none of its databases, so 3,550 of Everlake's 3,638 *invented* entries
  were Blizzard's own objects (about 17,000 spawns). Objects are no longer judged by Wowhead; creatures still are, and
  any entry from 1,000,000 up (the server's own ids) is listed as a stand-in to keep until its real entry is found.
  Invented entries are never in *Removals as SQL*.

- **Query: read-only SQL from The Forge.** A new page, The Forge › Query (and `POST api/query` for scripts in an
  administrator's browser), runs one statement that reads on the tracker's world, hotfixes or own database: SELECT,
  WITH, SHOW, EXPLAIN, DESCRIBE. It runs only as a MySQL account of its own whose grants are checked before every
  query (SELECT only, or nothing runs; `FT_DB_QUERY_USER`), on its own connection, in a read-only transaction that is
  rolled back, for at most 30 seconds and 5,000 rows. docs/FORGE.md.

- **Extras: what the server has that the live game does not.** A new page, The Forge › Extras, lists what imports
  brought in that live Forever never had: Classic creatures whose Forever remake is the one live uses (*old twin*),
  two spawns of one name on one spot (*stacked*), far more spawns than Wowhead's map marks (*crowded*), entries nothing
  outside the server knows (*invented*), and quest givers live players never saw give the quest. Witnesses: EG Link's
  recordings and Wowhead. *Removals as SQL* gives the sure removals as an update file to review. docs/FORGE.md.

- **What later phases need, gathered before they open.** After each analysis the tracker writes a work list
  (`data/gather.json`, The Forge › Later): per release phase not open yet, and for the open game, the quests with
  who gives and takes them and what they ask, the creatures and objects the server lacks with a template and a place,
  the items with where they come from, and which source (EG Link, QuestieDB, Icy Veins, Wowhead) already holds each.
  The analysis downloads the EG Link and QuestieDB files it needs; the Wowhead crawl reads the pages the list names
  (the open game's as gaps, the later phases' in a new tier `later`), and Import Icy Veins asks its answers before the
  rest of its mirror. The official quests the server has no record of, their creatures and objects and the items they
  ask for are now in the crawl's queue too. docs/GATHER.md.

- **Wowhead pages come due again in a long crawl.** A crawl's tab kept every page it read and skipped any it held, so
  in the Chrome extension's tab, which crawls for weeks, no page the tracker wanted again (`[wowhead] refresh_days`,
  `recheck_days`) was ever read twice. Each page the tracker queues now asks the tab to read it again when its own
  copy is over a day old. docs/WOWHEAD-PAGES.md.

- **The changelog opens on the newest entry.** With no build in the address, the Changelog page now opens on the
  newest entry with changes, a hotfix update included, as the overview's *Latest changes* link does. Before, it
  opened on the newest build that changed something itself, so a build with the same game data as the one before
  (1.60.1.70959 after 70938) sent readers back a build, past the hotfixes that came after it.

- **Keys from every region.** The client check also takes the decryption keys wago.tools saw handed out by hotfix in
  any region (its `TactKey` and `TactKeyLookup` tables), next to wowdev's TACTKeys list: a key that reaches Europe,
  Korea, Taiwan or China before the US hotfix cache, or before the list is updated by hand, opens the build's hidden
  tables at the next check. TACTKeys wins where both name a key; wago being down changes nothing. docs/CLIENT.md.

- **Spawn positions on the map.** The Spawns page shows where the locator would place a creature on the official
  zone map, so a wrong position is seen before it is spawned. Positions are drawn with the client's own UiMap tables
  (`data/ui-maps.json`, written by the analysis and the locator); the pictures come from wago.tools (`[client]
  map_images`) and are kept per build in `data/maps`. docs/SPAWNS.md, section 1.

- **The locator reads heights in the server's maps.** Every ready spawn point now gets its z from the server's maps
  and vmaps (`[server] maps` / `vmaps`), the nearest existing spawn's z picking the floor under a roof or a bridge,
  and records that it came from the terrain. The database spawn mode writes these points too, not only those with an
  existing spawn within 15 yards. Without the files the locator borrows the nearest spawn's z as before.
  docs/SPAWNS.md, section 1.

- **Heights without the game.** `tools/height.py` answers the ground height of spawn points (map and world x, y, or
  Wowhead's zone percentages) from the server's maps and vmaps, buildings and bridges included, as the worldserver
  computes it: no game client, no running server, no `.gps`. `--floors` lists every level under a point, a hint picks
  one, `--forge` answers as `.forge height` does. docs/SPAWNS.md, section 5.

- **QuestieDB is in *What the sources said*.** Each QuestieDB import now keeps what it said as a snapshot (every drop it
  names, without a chance), so it shows in the table with its facts and what changed since its last release, and its
  *Card* (and *Make every card from the database*) makes its card again without downloading anything.

- **QuestieDB's card reads cleanly.** Its credit line showed a raw `\u{2019}` where an apostrophe belongs, and two of its
  left-out reasons showed as bare keys (`questie_item_not_in_forever`, `questie_phase_not_open`).

- **The locator finds QuestieDB without a pin.** The container never runs `world pin`, so the locator read no QuestieDB
  position at all ("QuestieDB places 0 recorded"). Without a pin it now takes the commit of QuestieDB's newest release
  itself, or offline the newest one already downloaded.

- **QuestieDB's drops come in by themselves.** The Forge › Imports › *Import QuestieDB drops* (and the container, every
  `FT_QUESTIE_EVERY_HOURS`) reads QuestieDB's newest release: its Forever item database, corrected by hand and by what
  over a million of its players' sessions recorded on live Forever. About 8,800 items, 210,000 creature drops and 27,000
  chest drops. QuestieDB ranks right after Wowhead and needs no second source; it fills every creature or chest that
  does not drop the item yet, not only items nobody can get, and Wowhead's word replaces its rows where they disagree.
  QuestieDB has no drop chance: a row takes the server's chance for the item elsewhere, else (an item a quest asks
  for) `[questie] quest_chance` (40), dropping only for players on the quest; any other item without one is left out.

- **The locator places what players recorded with QuestieDB first.** QuestieDB's Forever corrections carry where its
  players' QuestieTrace recordings saw creatures and objects stand (about 2,100 of them, 56,000 points). The locator now
  takes those positions before Wowhead's maps, and QuestieDB's hand fixes (zones named as `zoneIDs.NAME`) where Wowhead
  has none, before Icy Veins. Its generated part is built from Wowhead and its converted Classic base says where
  things stood in Classic: neither is read for positions.

- **QuestieDB is pinned by its newest release.** `world pin questie` now takes the commit of QuestieDB's newest release
  (v1.1.2 on 2026-11-16) instead of its master branch, and reads its new quest chain recordings
  (`traces/foreverQuestRelationTraces.lua`: what comes before, after or instead of a quest).

- **An applied card is Applied, also when its source has a newer one.** The Imports page put every earlier card of a
  source in its own group, so cards with nothing left to add (most of them, now that cards apply themselves) sat
  apart from the applied ones. They now fold under Applied; the earlier group keeps only cards with something not
  applied, which the source's newest card offers.

- **The Crawl and Imports pages count Wowhead Classic's item pages.** The crawl reads the Classic page of each Season of
  Discovery item Forever kept with no source, but neither page counted them, so a crawl reading them looked stuck. The
  *Import Classic pages* button is also offered when only Classic item pages were read.

- **ForeverChanges needs a second source.** A row only ForeverChanges states is no longer put on its card, so it is
  never applied by itself nor exported: Wowhead, ForeverDB.net or EG Link (their last snapshots; EG Link's quest texts
  for turn-in and progress texts) must state the same thing. What is left is listed on the card as hints about the gaps.

- **ForeverChanges: only the gaps' pages.** A visit of foreverchanges.pro now asks for the sitemaps, the two
  continents' map files and the page of each quest or item the last analysis lacks, and nothing else: no more
  Forever's own pages outside the gaps, other maps, dungeons, topic pages or Classic's pages, and no rereading of
  them. Files an earlier visit kept stay in `data/` and still go into the card. Its cards are made as before.

- **ForeverDB.net is read into the world facts.** `python tools/tracker.py world facts foreverdb` reads what its
  players recorded on Forever (the vendors and trainers they saw, those vendors' stock, boss loot measured over kills,
  who gives and takes the quests they saw) and leaves its Classic rows out. Its pin is the version its manifest names
  (`world pin foreverdb`). It counts as a second witness beside EG Link or QuestieDB, never as a live recording alone.

- **The Chrome extension takes a new crawler every hour.** It loaded the tracker's crawler only when its tab had
  none, so a tab that crawled for days kept the queue and code it started with: the new order of the crawl did not
  reach it. Extension 1.1.0 reloads the tab for a new crawler once the one it runs is an hour old (and at once for one
  an earlier version loaded), only after the tracker answered. Download it again from The Forge › Crawl and reload it
  in `chrome://extensions`.

- **The crawl reads the items with no source before the creatures with missing data.** The items that only lacked a
  source were the crawler's tier 4, behind more than 2,000 creature pages of tier 3 (about a day of reading at its
  pace). They are now tier 3, what their pages name tier 4, and the server's creatures and objects whose data is
  missing tier 5. A crawl that is already running (the Chrome extension's) is put in the new order once, the next
  time it loads the crawler.

- **The VMaNGOS pack leaves out what players could never reach.** VMaNGOS keeps vendors that never spawn (the World
  Mount Vendor, test and "[UNUSED]" vendors), vendor lists no spawned NPC uses (old PvP rank gear) and quests Blizzard
  marked as never made ("<NYI>", "<TXT>", "<UNUSED>", "REUSE", test quests). classic-db leaves these out. Counted as
  ways the game gave an item out, they took 114 items and 24 mount spells out of *Internal / test* and put them in To
  add. The pack now drops them. Make the pack again and send it to put those back.

- **A card no longer puts back drop chances a better source set.** A card's values measured again (the `/* refresh */`
  lines) were weighed against who wrote each row only when the card was made, and applying them never kept their
  source. So a card made before a Wowhead apply put its own numbers back over Wowhead's, and any card could undo any
  other's. Those values are now weighed again when the card is built: a row a more trusted source (or an
  administrator) wrote since is held, and the source of each one applied is kept. The sources of rows refreshed
  before this are read back once from the History, the newest apply of a row winning.

- **Applied import cards fold away.** A card kept its place on the Imports page after it was applied, and the Imports
  badge counted every card ever made. Each card now records when it was last applied and when nothing on it was
  missing any more (an apply that wrote it all, or a preview or apply that found nothing to add). Those cards fold
  under "Applied: nothing left to add", and both Imports badges count only the cards with something left. Rolling one
  of a card's operations back puts it back on top. A table left unticked counts as declined; an apply of chosen items
  only, or one that held the spawns back, leaves the card open. Cards made before this are marked at their next
  preview or apply.

- **VMaNGOS is a source, just above the Classic database.** `tools/vmangos_pack.py` makes a pack from the world
  database of VMaNGOS' `db_latest` release (GPL-2.0), patch 1.12 only, in the Classic database pack's format; send it
  on the Imports page (a pack names its source). It answers the same questions (trainers, quest turn-in spells,
  conversation lines, drops and vendors of recipes, holiday spawns) and ranks after Wowhead Classic and before cmangos
  classic-db. Its holiday cards use the realm's own event numbers. The analysis reads both packs.

- **The fishing contest card uses the realm's crew event.** It linked Riggle Bassbait and his crew to event 62,
  which on the realm's calendar (VMaNGOS's) is an AQ War event; the realm's crew event is 40, which already has them.

- **A holiday's spawn is matched against its own holiday only.** A holiday card took any spawn of the same kind
  nearby for its own, so New Year's Eve found its fireworks over Booty Bay already standing: they were Midsummer's.
  A holiday's spawn now stands already only when the server's copy is there while the holiday runs (all year, or
  brought in by the same event), and moves only a spawn its own event brings in. The world data export asks the same.

- **Holiday cards stop adding second copies.** The realm's holiday spawns come from VMaNGOS, and the holiday cards
  from cmangos classic-db, which places the same NPC a few yards off: matched at 3 yards, the cards gave the realm a
  second Silas Darkmoon, Lunar Festival Elders and Love is in the Air perfume sellers. A spawn a card links to a game
  event now stands already when the server has one of its kind within 30 yards (an object within 10), and the server's
  stays where it is; the card's own spawns are still told apart at 3 yards, so a crowd stays whole. The world data
  export uses the same distances for an operation's holiday spawns.

- **Imports apply themselves.** A card is now applied as soon as an import makes it, from a button, an upload, a
  background run (Icy Veins, ForeverChanges) or Wowhead's quest enders, so the next analysis counts it without a
  click on Apply. The card's message says how many rows went in and the history number to roll them back. Spawn
  rows (and the rows keyed by their guid) go in only when the remote console says the worldserver is stopped;
  otherwise they wait on the card for its Apply button. `[imports] auto_apply = 0` (Docker: `FT_IMPORTS_AUTO_APPLY=0`)
  brings back the old way.

- **The newer word wins: every value, and spawns that moved.** An applied card now also replaces the values of rows
  the server already has (every column it gives, by primary key), and moves a spawn of the same kind standing within
  40 yards (`[imports] spawn_move_yards`) to where the card places it, keeping its guid. A row or spawn a more trusted
  source wrote stays as it is. The core's own rows now rank below every source (`[sources] change_core = 0` protects
  them), and a new ledger (`ft_row_origin`) remembers which source last wrote each row. Files imported by hand count as
  `sniff` (WowPacketParser) or `scribe` (ForeverScribe), after the Forever sources and before Classic's.

- **Season of Discovery items Forever kept: Wowhead Classic's item pages.** The Forever client still carries Season of
  Discovery's items, and Forever brought some of them back (the Tarnished Undermine Real), but Wowhead's Forever pages
  often know no source for them yet. For a gap item that is Season's (id 190000 and up, in the Classic Era client), the
  crawler now also reads its Classic item page, right after the Forever page and in the same tier, unless the Forever
  page names a drop, a chest or a vendor. The Wowhead Classic card takes their drops (Dropped by, Contained in), with
  Forever's counts still winning where Forever has them. A Season currency (an item with a *Currency for* tab) is no
  world drop however many bosses drop it: each boss gets a row, as Season of Discovery had it; other Season items many
  creatures drop stay out. Vendors are not taken from Classic: Forever cut those vendors' stock, and Forever's own npc
  pages give it (counted on the card). Stock paid with the Tarnished Undermine Real still has no row: neither the
  client nor its hotfixes (build 70938) hold an extended cost paid in it.

- **Crawl page: list pages and the last page received.** The Forge › Crawl also counts the list pages a whole
  crawl reads first (they were kept but not shown) and says when the last page came, so a crawl that stopped shows.

- **A Wowhead crawl that runs by itself: the Chrome extension.** The Forge › Crawl › *Download the Chrome extension*
  gives a zip with this tracker's address and a key of its own (made once, kept in `data/wowhead-extension.key`, so no
  setting). Loaded in Chrome, it keeps a pinned Wowhead tab, loads the crawler with the tracker's queue after every
  load (`GET api/wowhead-crawler`), opens the tab again after a close or a restart of Chrome (checked every 5
  minutes), and sends each batch to `api/wowhead-push`; no console, no tracker tab. Its popup shows the queue, the
  pace and what was sent, and pauses it. `api/wowhead-push` takes the extension's key as well as `[wowhead]
  push_token`. The crawler sends to the extension's script in its own tab when the extension loaded it.

- **ForeverChanges read from the site, regularly.** foreverchanges.pro was rebuilt and the data files the old pack
  was made from are gone, so the tracker now reads the site itself (`tools/foreverchanges_pull.py`): robots.txt
  obeyed, one request at a time with a pause that grows when the site asks, what the last analysis lacks first, up
  to 1,500 files a visit, then again what is older than two weeks. Every file is kept privately in `data/`, once,
  with its history; each visit's evidence is a snapshot, so its card can be made again from the database. New: the
  quest givers its map names by id, from the rows its players saw, become rows with no name to match, and the NPCs
  and pins of every map are read, not only the two continents'. The Imports page's *Read the site* starts a visit in
  the background, and the container visits every `FT_FOREVERCHANGES_EVERY_HOURS` (24). The `.fcpack` upload and
  `tools/foreverchanges_pack.py` are gone.

- **A checkout finds the server's build as the analysis does.** Without `[server] build` (or `build_file`) in
  config.ini, it takes the client build the realms accept (`auth.realmlist`), as the analysis already did, instead of
  stopping.
- **Checkout: the client's data at any step.** `tracker.py checkout <step>` writes the tables of a build or of a
  day's hotfixes (`70938+1`) as an SQL file for a test realm's hotfixes database: every record that differs from the
  server's DB2 files, removals as `hotfix_data` status 2, one push, exact floats, a manifest of what it holds and what
  it left out (docs/CHECKOUT.md). `--fetch` reads the tables an earlier build was stored without from Blizzard's CDN.
  On the website: The Forge → Checkout makes a step's file in the background and hands it out.
- **The world as of a day.** `world replay --until YYYY-MM-DD` (or `--at <step>`, the day of a step of the timeline)
  leaves out the update files named for a later day, to pair the world with a checkout of the same step.
- **A build read again keeps its hotfix history.** When a key comes out and a build is read again, its kept hotfix
  caches and their steps go over to the new copy (they were only kept for the newest cache).
- **Hotfixes as entries of their own.** Every hotfix cache that differs from the one before is kept, compressed,
  with its build (`data/builds/<build>/hotfixes/`). A build is compared as it stood with its first cache, and each
  later day's hotfixes are an entry of their own on the timeline and in the changelog: what they added, changed or
  removed (`/changes?build=…&hotfix=…`). The double check follows them too (docs/CLIENT.md). Database: `ft_builds.hotfix`
  and `ft_changes.hotfix` (schema 5); the site reads an older analysis as before until the next one runs.
- **The changelog starts at the original game.** Patch 1.12, as Blizzard published it again in 2019 (the client WoW
  Classic launched with), is stored as the build before the first beta, and the first beta build has a page of what it
  added, changed and does not have against it. An item's stats and a spell's effects are compared in a form both
  games have; what a hotfix alone carries is compared as its hotfix stands and never called absent; what the original
  game had and WoW: Forever does not is *Not in Forever* (taken out, or not released yet), not *removed*
  (docs/VANILLA.md). `tracker.py vanilla`, `[client] vanilla`, `FT_CLIENT_VANILLA`; the client check stores it by
  itself.
- **The double check.** At every analysis the chain is replayed: the first thing stored and every build's changes must
  give the newest build, resource for resource (ids from the start, content from the first build on). One line in the
  analysis log, a table on the first build's page.
- **A build's page reads every kind.** The first build against the original game is tens of thousands of lines: each
  kind is read on its own, a filtered kind has pages, and *CSV* gives every line the filters show as a file.
- **Tooltips: ranged weapons.** Bows, guns, thrown weapons and wands take their stats from the ranged column of the
  item level's budget, as the game does. They showed too much before (a wand's +3 Intellect as +4).

## 1.3.3 — 2026-10-20

- **Run again no longer stays disabled.** A background analysis or locator run now always ends with a marker, even when
  Python cannot start or stops early, and a run whose log has been silent for 10 minutes (PC asleep, website stopped) no
  longer counts as running. Before, the button could stay greyed out for up to 30 minutes.
- **ForeverScribe positions are used at once**: after an import that locates creatures, the locator runs by itself, and
  the Imports page links to Spawns, where the ones your server needs show as Ready (*seen in game*).

## 1.3.2 — 2026-10-20

- **ForeverScribe 1.2.0** works with the game's newer addon API (`C_MerchantFrame`, `C_Spell`, `C_CVar`) as well as the
  older one: on clients without the old calls, vendors and casts were not noted. A failing game call is now shown once in
  the chat and kept in the notes. Creatures you target or point at within about 10 yards are located too. `/scribe debug`.
- **ForeverForge 1.2.0**: outside, the window lists the dungeons and raids with creatures to place by hand and a **Go inside**
  button (to the instance's entrance teleport, or any creature already spawned there).

## 1.3.1 — 2026-10-20

- **ForeverScribe 1.1.0 collects only on the official realms.** A client connected to a private server (your own one
  included) uses another `portal` than `us`, `eu`, `kr`, `tw` or `cn`: nothing is noted there. `/scribe on` and
  `/scribe off` force it, `/scribe auto` goes back to that rule; the state shows at login and with `/scribe`.
- **No drop added twice**: an item a creature or chest already drops — directly or through `reference_loot_template`,
  at any depth — is left out of a ForeverScribe import (counted as *drops the server already has*).

## 1.3.0 — 2026-10-20

- **ForeverScribe** (`addon/ForeverScribe`): an addon for the game that notes, through the normal addon API, what
  vendors sell (stock limits, costs), what creatures and chests drop (counted per corpse, skinning and pick pocketing
  apart), who gives and takes quests, and where creatures stand. No character, realm or account name is kept.
- **The Forge › Imports** imports ForeverScribe files like SQL files: vendors, loot (chance = drops ÷ corpses looted),
  quest givers and enders, previewed and rolled back like any import. *Install into the game*, *Download the addon*,
  *Import new notes*.
- **Automatic import**: `ForeverTracker.exe` imports the game's new ForeverScribe notes every minute
  (`tools/collector-sync.php`); `[collector] auto_apply = 1` also applies them.
- **Locator**: creatures seen in game by ForeverScribe use those positions before Wowhead's.
- **Vendors**: the vendor search finds every creature, not only those flagged as vendors, and says when a creature
  does not exist on the server; selling items at a creature (by hand or from an import) adds the vendor flag it lacks,
  with its rollback.
- **Spawning on the server**: a point without a nearby spawn to borrow a height from takes the highest floor up to 40
  yards above the terrain, instead of the terrain itself (which lies under cities such as Stormwind).
- The launcher's French texts are compiled as UTF-8.

## 1.2.2 — 2026-10-20

- **Locator** (`tools/tracker.py locate`, `tools/ft/locator.py`): reads the positions of unspawned creatures and
  objects from the maps of Wowhead's public Forever tooltips.
- **The Forge › Imports** (`tools/wpp-import.php`, `data/imports/`): imports SQL files in WowPacketParser's format.
- Guide `docs/SPAWNS.md`, with a note on heights in places with several levels (Stormwind).

## 1.2.1 — 2026-10-20

- README (English and French) rewritten as a presentation of the whole solution: three-step installation from the
  release package, every feature, and how it works (analysis, Forge engine, positions, spawning, imports).
- Release package `ForeverTracker-<version>.zip`: unzip and double-click `ForeverTracker.exe`.

## 1.2.0 — 2026-10-20

- **Imports** (The Forge › Imports, `tools/wpp-import.php`): imports SQL files in WowPacketParser's format: spawns
  with their positions, new creatures and objects, loot, vendors, quests,
  quest givers and enders, gossip. Only `INSERT` rows are read; rows the server has are left out; spawns get new
  guids and a spawn already standing within 3 yards is left out with its addon; a creature whose `LootID` is 0 gets its
  loot table; unknown columns and tables are dropped; one transaction, exact rollback in the history.
- **Items tab**, first in the Forge: every item nobody can get, with the reason and its imported sources (drop, chest,
  vendor, quest reward), the filter *Found in an import*, and **Apply imported sources** for the selection.
- The Forge engine gains *fill* operations (set a column only where it is still 0, with its rollback), and tables without
  a primary key are matched on their first index.

## 1.1.1 — 2026-10-20

- **`ForeverTracker.exe`**: the launcher is now a real Windows program (with its icon), built from
  `tools/launcher/ForeverTracker.cs` by `build-exe.ps1` with the C# compiler Windows ships. It replaces the
  PowerShell launcher; `ForeverTracker.bat` starts it. `--check` prints what it finds.
- README: install in two minutes, what is new in 1.1, new screenshots (launcher, setup wizard, spawns, SQL preview).

## 1.1.0 — 2026-10-20

### Installation
- **Launcher** (`ForeverTracker.bat`, Windows): finds a PHP 8 with `mysqli` (writing an ini for portable PHP builds)
  and Python, starts and stops the website, opens the setup wizard on the first run, updates the data.
- **Setup wizard** (`/setup`): finds the server by its `worldserver.conf` (databases, data folder, remote console,
  `mysql` client), tests the databases and creates ForeverTracker's, finds the game client (`.build.info`), extracts
  its DB2 files with the core's `mapextractor` or uses the server's, creates the administrator, writes `config.ini`
  and runs the snapshot, the analysis and the locator with live progress. Local requests only before the first
  configuration, administrators afterwards.

### The Forge
- **No more "duplicate entry" errors.** Fixes are stored as operations (table, columns, rows, key columns). Applying
  merges the whole selection, inserts every row once, leaves out the rows that already exist on the server at that
  moment, and saves a rollback that deletes exactly the inserted rows. Applying twice, overlapping fixes (a spell that
  is both a class spell and a recipe, shared durations or triggered spells) and rows added by hand are all safe.
  Preview shows new, existing and shared rows.
- `tools/forge-check.php` (replaces `check_fixes.py`) dry-runs every fix with the website's own engine, all together
  and one by one.

### Locator and spawns
- **Locator** (`tools/tracker.py locate`, or *Run* in the Forge): finds the creatures and world objects the server
  knows but never spawned although quests (givers, enders, objectives), vendors, trainers, loot or dungeons need
  them, and their official positions from Wowhead's Forever tooltips (cached, polite), converted to world
  coordinates with the client's `UiMap` tables (a few yards outdoors).
- **The Forge › Spawns**: spawn them on the running server through the remote console (exact height, live,
  undoable), in the database (worldserver stopped), with the ForeverForge in-game addon, or as GM commands.
- **Core module** `core/forge_commands.cpp`: `.forge spawn npc|go`, `.forge delete`, `.forge height`,
  `.forge version`, usable from the console, the remote console and in game. The server computes the ground height
  from its maps and vmaps, buildings included.
- **ForeverForge addon** (`addon/ForeverForge`): `/forge` spawns the exported queue through TrinityCore's addon
  command channel, in place with the core module or by travelling with `.go xyz` without it; *Spawn here* for
  bosses and dungeon creatures.

### Other
- Background jobs run Python in UTF-8 mode, and JSON answers survive console-encoded logs.
- New `config.ini` sections: `[console]`, `[client]`, `[wowhead]`. Snapshots now store `UiMap`,
  `UiMapAssignment` and `UiMapGroupMember`.

## 1.0.1 — 2026-10-19

- The analysis stops with a clear message when `[server] root` / `dbc` do not lead to the server's `.db2` files,
  instead of reporting nearly everything as unknown to the core. When the configured folder has no DB2 file but a
  locale folder next to it does (`data/dbc/enUS` instead of `data/dbc/frFR`), that folder is used with a warning.
- When neither `[server] build` nor `build_file` is set, the server build is taken from `auth.realmlist`.
- Warnings when `[server] maps` or `vmaps` do not exist.
- Overview: clear messages when the server build is unknown or when most resources look unknown to the core,
  instead of "build 0".

## 1.0.0 — 2026-10-19

First public release.

- Official content of the WoW Forever client, read from its DB2 files with the layouts of your core: 13 resource
  types (dungeons and raids, bosses, zones, quests, items, spells, talents, recipes, mounts, pets, toys,
  achievements, flight points).
- Changelog of every stored client build, field by field, with Blizzard's patch notes.
- Availability checks against a TrinityCore-based server: core data, spawns, loot (with reference loot),
  vendors, trainers, quest givers and enders, objectives, instances, bosses and scripts, graveyards, flight masters.
- In-game tooltips for every resource, computed with the core's item formulas and a spell description renderer.
- The Forge: core data (hotfixes), trainers, vendors and instances, with SQL preview and download, transactions,
  history and rollback; `tools/check_fixes.py` dry-runs every fix.
- Work list by priority with CSV export, global search (`Ctrl K`), catalogues with filters.
- English and French interface and data, dark and light themes, phone layout.
- Administrators: game masters (Battle.net SRP6 login) or local accounts; can run inside another website.
