<?php
// Open data sources turned into imports aimed at the analysis' gaps. Each source only says what it saw (the evidence);
// source_tables() holds the server's rules once, for every source:
//
//   sell   [npc, item, stock]                        npc_vendor: for items players cannot get (not internal); stock
//                                                    > 0 is a limited stock restocked hourly; the price is the item's
//                                                    own unless another vendor sells it for items or currencies
//   drop   ['npc'|'go', id, item, chance %]          loot: the creature's own table (LootID filled where 0) or the
//                                                    chest's (Data1); chance 0 (unknown) is left out; an item the
//                                                    table already gives, references included, is left out
//   start  ['npc'|'go', id, quest]                   quest givers, for quests that have none
//   end    ['npc'|'go', id, quest]                   quest enders, for quests that have none
//   train  [npc, spell, cost, level, line, rank, needs|null, rank number]
//                                                    trainer_spell at the trainers the server has for that creature;
//                                                    a class spell's level: the source's, else the server's other
//                                                    trainers', else Wowhead's "Requires level N" (never 0); the ranks
//                                                    it needs: the source's, else the server's other trainers'; a
//                                                    higher rank with neither is left out (a talent's later rank
//                                                    would be sold to players who never took the talent)
//
// Sources: NorgannonDB (app/norgannon.php), AtlasLoot (app/atlasloot.php), Wowhead's pages (app/wowheadpages.php), EG Link,
// ForeverDB.net, Icy Veins (below).
// See docs/SOURCES.md.
require_once FT_APP . '/imports.php';
require_once FT_APP . '/collector.php';
require_once FT_APP . '/wowhead.php';

/** Profession names as trainers show them, to skill lines. */
const SOURCE_SKILLS = ['Alchemy' => 171, 'Blacksmithing' => 164, 'Enchanting' => 333, 'Engineering' => 202, 'Herbalism' => 182,
    'Leatherworking' => 165, 'Mining' => 186, 'Skinning' => 393, 'Tailoring' => 197, 'Cooking' => 185, 'First Aid' => 129,
    'Fishing' => 356, 'Jewelcrafting' => 755, 'Inscription' => 773, 'Lockpicking' => 633, 'Poisons' => 40, 'Riding' => 762];

const SOURCES = [
    'wowhead' => ['Wowhead', 'facts from the pages of wowhead.com/forever (ids and players’ counts, no text; no licence stated: credited)'],
    'norgannondb' => ['NorgannonDB', 'GPL-3.0 (with QuestieDB, pfQuest, DungeonJournal)'],
    'eglink' => ['EG Link', 'CC BY 4.0: "Data from Efficient Games (https://efficient.games), licensed under CC BY 4.0."'],
    'foreverdb' => ['ForeverDB.net', 'GPL-3.0 with attribution: "Data from ForeverDB.net"'],
    'icyveins' => ['Icy Veins', 'no licence stated: reference for your own server'],
    'atlasloot' => ['AtlasLoot Classic Forever', 'GPL-2.0 (CurseForge project 1422985)'],
    'foreverchanges' => ['ForeverChanges', 'players’ reports from foreverchanges.pro (no licence; credited, the project’s decision of 2026-11-14)'],
    'classicdb' => ['Classic database', 'cmangos classic-db, GPL-3.0: the original game, asked last'],
];

/**
 * The analysis' gaps: items players cannot get (not internal), official quests without giver / ender. What waits for
 * a release phase that is not open yet is no gap today (docs/PHASES.md): it is left out, and kept under 'later'
 * (items, quests, and the spells no trainer may teach yet) so that a card can say how much that was.
 */
function source_gaps(): array
{
    $ids = function (string $sql, string $database = 'tracker'): array { $out = []; foreach (rows($sql, [], $database) as $r) $out[(int)reset($r)] = true; return $out; };
    // a quest an item starts (the Ancient Petrified Leaf) has no giver on purpose: a source naming the creature that
    // drops the item, or the chest it lies in, as its giver would be wrong
    $byItem = array_fill_keys(array_map('intval', (array)(meta()['item_quests'] ?? [])), true);
    // the server's quest_template holds tens of thousands of quests WoW: Forever does not have (other versions of the
    // game): only the client's own quests are gaps worth a lookup
    $official = official_quests();
    $later = later_ids('item', 'quest', 'spell', 'recipe');   // a recipe's number is its spell's
    return source_gap_sets(
        $ids("SELECT id FROM ft_entities WHERE type = 'item' AND internal = 0 AND status <> 'ok'"),
        $ids('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_queststarter s WHERE s.quest = q.ID) AND NOT EXISTS (SELECT 1 FROM gameobject_queststarter g WHERE g.quest = q.ID)', 'world'),
        $ids('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_questender s WHERE s.quest = q.ID) AND NOT EXISTS (SELECT 1 FROM gameobject_questender g WHERE g.quest = q.ID)', 'world'),
        $byItem, $official, ['items' => $later['item'], 'quests' => $later['quest'], 'spells' => $later['spell'] + $later['recipe']]);
}

/**
 * The gap sets of source_gaps() from what the databases say, every argument as [id => true]: items players cannot
 * get, the server's quests without a giver and without an ender, the quests an item starts, the official quests, and
 * what waits for a release phase ($later: items, quests, spells).
 */
function source_gap_sets(array $items, array $noGiver, array $noEnder, array $byItem, array $official, array $later): array
{
    $noGiver = array_intersect_key(array_diff_key($noGiver, $byItem), $official);
    $noEnder = array_intersect_key($noEnder, $official);
    return [
        'items' => array_diff_key($items, $later['items']),
        'noGiver' => array_diff_key($noGiver, $later['quests']),
        'noEnder' => array_diff_key($noEnder, $later['quests']),
        'later' => ['items' => array_intersect_key($items, $later['items']), 'quests' => array_intersect_key($noGiver + $noEnder, $later['quests']), 'spells' => $later['spells']],
    ];
}

/** Creature entries of the server's trainers. */
function source_trainer_npcs(): array
{
    return array_map('intval', array_column(rows('SELECT DISTINCT CreatureID FROM creature_trainer', [], 'world'), 'CreatureID'));
}

/** The loot table each kind of drop goes to. */
const SOURCE_LOOT_TABLES = ['npc' => 'creature_loot_template', 'skin' => 'skinning_loot_template', 'pick' => 'pickpocketing_loot_template', 'go' => 'gameobject_loot_template'];
/** The creature_template_difficulty column that points a creature to each of its tables. */
const SOURCE_LOOT_COLUMNS = ['npc' => 'LootID', 'skin' => 'SkinLootID', 'pick' => 'PickPocketLootID'];

/**
 * The loot entries of these creatures and objects: [[kind => [id => entry, 0 when the creature has no table of that
 * kind yet]], [known => ['npc' => [id => true], 'go' => [id => true]]]]. An object has an entry only as a chest or a
 * gathering node (types 3 and 25, Data1).
 */
function source_loot_entries(array $npcs, array $objects): array
{
    $entryOf = ['npc' => [], 'skin' => [], 'pick' => [], 'go' => []]; $known = ['npc' => [], 'go' => []];
    foreach (array_chunk(array_values(array_unique(array_map('intval', $npcs))), 1000) as $chunk) {
        foreach (rows('SELECT Entry, LootID, SkinLootID, PickPocketLootID FROM creature_template_difficulty WHERE DifficultyID = 0 AND Entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) {
            $known['npc'][(int)$r['Entry']] = true;
            foreach (SOURCE_LOOT_COLUMNS as $kind => $column) $entryOf[$kind][(int)$r['Entry']] = (int)$r[$column];
        }
    }
    foreach (array_chunk(array_values(array_unique(array_map('intval', $objects))), 1000) as $chunk) {
        foreach (rows('SELECT entry, type, Data1 FROM gameobject_template WHERE entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) {
            $known['go'][(int)$r['entry']] = true;
            $entryOf['go'][(int)$r['entry']] = in_array((int)$r['type'], [3, 25], true) ? (int)$r['Data1'] : 0;
        }
    }
    return [$entryOf, $known];
}

/** The evidence as import tables, with the server's rules (see the top of this file). Returns [tables, left out]. */
function source_tables(array $ev, string $label, array $gaps): array
{
    $left = ['vendor_unknown' => 0, 'loot_chance_unknown' => 0, 'loot_known' => 0, 'loot_unknown_creature' => 0, 'object_no_loot' => 0,
             'quest_unknown' => 0, 'trainer_not_on_server' => 0, 'trainer_level_unknown' => 0, 'trainer_previous_rank_unknown' => 0, 'trainer_known' => 0,
             // the gap items and quests no source was asked about, because their release phase is not open yet
             'phase_not_open' => count($gaps['later']['items'] ?? []) + count($gaps['later']['quests'] ?? []), 'trainer_phase_not_open' => 0];
    $rows = [];
    $build = (int)(meta()['client_build'] ?? 0);
    $ids = function (string $sql, string $database = 'world'): array { $out = []; foreach (rows($sql, [], $database) as $r) $out[(int)reset($r)] = true; return $out; };
    $in = fn(array $list) => implode(',', array_map('intval', array_values(array_unique($list)))) ?: '0';

    // ---- vendors
    $sells = [];
    foreach ($ev['sell'] ?? [] as [$npc, $item, $stock]) if (isset($gaps['items'][(int)$item])) $sells[(int)$npc][(int)$item] = (int)$stock;
    $creatures = $ids('SELECT entry FROM creature_template WHERE entry IN (' . $in(array_keys($sells)) . ')');
    $sold = array_merge(...array_map('array_keys', array_values($sells)) ?: [[]]);
    $costs = [];
    foreach (rows('SELECT item, MIN(ExtendedCost) c FROM npc_vendor WHERE ExtendedCost > 0 AND item IN (' . $in($sold) . ') GROUP BY item', [], 'world') as $r) $costs[(int)$r['item']] = (int)$r['c'];
    foreach ($sells as $npc => $list) {
        if (!isset($creatures[$npc])) { $left['vendor_unknown'] += count($list); continue; }
        foreach ($list as $item => $stock) {
            $rows['npc_vendor'][] = ['entry' => $npc, 'slot' => 0, 'item' => $item, 'maxcount' => max(0, $stock), 'incrtime' => $stock > 0 ? 3600 : 0,
                'ExtendedCost' => $costs[$item] ?? 0, 'type' => 1, 'VerifiedBuild' => $build];
        }
    }

    // ---- loot: a corpse ('npc'), Skinning ('skin'), Pick Pocket ('pick'), a chest or a gathering node ('go')
    $drops = ['npc' => [], 'skin' => [], 'pick' => [], 'go' => []];
    foreach ($ev['drop'] ?? [] as [$kind, $id, $item, $chance]) {
        if (!isset($gaps['items'][(int)$item]) || !isset($drops[$kind])) continue;
        $old = $drops[$kind][(int)$id][(int)$item] ?? 0;
        $drops[$kind][(int)$id][(int)$item] = max($old, (float)$chance);   // a source seen in several builds: its best measure
    }
    [$entryOf, $known] = source_loot_entries(array_keys($drops['npc'] + $drops['skin'] + $drops['pick']), array_keys($drops['go']));
    $questItems = $ids('SELECT DISTINCT ObjectID FROM quest_objectives WHERE Type = 1');
    $gives = [];
    // a creature without a table of that kind is checked under its own entry (where its rows go); an object only as a chest or node
    foreach (SOURCE_LOOT_TABLES as $kind => $table) $gives[$table] = collector_loot_items($table, $kind === 'go' ? array_values(array_filter($entryOf[$kind]))
        : array_values(array_map(fn($id, $e) => $e ?: $id, array_keys($entryOf[$kind]), $entryOf[$kind])));
    foreach ($drops as $kind => $sources) {
        $table = SOURCE_LOOT_TABLES[$kind];
        foreach ($sources as $id => $list) {
            if (!isset($known[$kind === 'go' ? 'go' : 'npc'][$id])) { $left[$kind === 'go' ? 'object_no_loot' : 'loot_unknown_creature'] += count($list); continue; }
            if ($kind === 'go' && empty($entryOf['go'][$id])) { $left['object_no_loot'] += count($list); continue; }
            // a creature without a table of its own gets one under its entry: applying the card points the template to it
            $entry = $entryOf[$kind][$id] ?: $id;
            foreach ($list as $item => $chance) {
                if ($chance <= 0) { $left['loot_chance_unknown']++; continue; }
                if (isset($gives[$table][$entry][$item])) { $left['loot_known']++; continue; }
                $questOnly = isset($questItems[$item]) || isset($ev['quest_drop']["$kind:$id:$item"]);
                $rows[$table][] = ['Entry' => $entry, 'ItemType' => 0, 'Item' => $item, 'Chance' => round(min(100, max(0.01, $chance)), 2), 'QuestRequired' => $questOnly ? 1 : 0,
                    'LootMode' => 1, 'GroupId' => 0, 'MinCount' => 1, 'MaxCount' => 1, 'Comment' => mb_substr($label, 0, 60)];
            }
        }
    }

    // ---- quest givers and enders
    $who = ['npc' => [], 'go' => []];
    foreach (['start', 'end'] as $role) foreach ($ev[$role] ?? [] as [$kind, $id]) $who[$kind][] = (int)$id;
    $templates = ['npc' => $ids('SELECT entry FROM creature_template WHERE entry IN (' . $in($who['npc']) . ')'),
                  'go' => $ids('SELECT entry FROM gameobject_template WHERE entry IN (' . $in($who['go']) . ')')];
    $seen = [];
    foreach (['start' => ['queststarter', 'noGiver'], 'end' => ['questender', 'noEnder']] as $role => [$suffix, $gap]) {
        foreach ($ev[$role] ?? [] as [$kind, $id, $quest]) {
            if (!isset($gaps[$gap][(int)$quest]) || isset($seen["$role:$kind:$id:$quest"])) continue;
            $seen["$role:$kind:$id:$quest"] = true;
            if (!isset($templates[$kind][(int)$id])) { $left['quest_unknown']++; continue; }
            $rows[($kind === 'npc' ? 'creature_' : 'gameobject_') . $suffix][] = ['id' => (int)$id, 'quest' => (int)$quest, 'VerifiedBuild' => $build];
        }
    }

    // ---- trainers
    $teach = [];
    foreach ($ev['train'] ?? [] as $t) $teach[(int)$t[0]][(int)$t[1]] = $t;
    $trainerOf = [];
    foreach (array_chunk(array_keys($teach), 1000) as $chunk) {
        foreach (rows('SELECT CreatureID, TrainerID FROM creature_trainer WHERE CreatureID IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $trainerOf[(int)$r['CreatureID']][] = (int)$r['TrainerID'];
    }
    $taught = []; $levels = []; $needsOf = [];
    if ($teach) foreach (rows('SELECT TrainerId, SpellId, ReqLevel, ReqAbility1, ReqAbility2, ReqAbility3 FROM trainer_spell', [], 'world') as $r) {
        $taught[(int)$r['TrainerId'] . ':' . (int)$r['SpellId']] = true;
        if ((int)$r['ReqLevel'] > 0) $levels[(int)$r['SpellId']] = (int)$r['ReqLevel'];
        if ((int)$r['ReqAbility1'] > 0) $needsOf[(int)$r['SpellId']] = array_values(array_filter([(int)$r['ReqAbility1'], (int)$r['ReqAbility2'], (int)$r['ReqAbility3']]));
    }
    $done = [];
    foreach ($teach as $npc => $spells) {
        if (empty($trainerOf[$npc])) { $left['trainer_not_on_server'] += count($spells); continue; }
        foreach ($trainerOf[$npc] as $trainer) foreach ($spells as $spell => [, , $cost, $level, $line, $rank, $needs, $rankNo]) {
            if (isset($done["$trainer:$spell"])) continue;
            $done["$trainer:$spell"] = true;
            if (isset($taught["$trainer:$spell"])) { $left['trainer_known']++; continue; }
            if (isset($gaps['later']['spells'][$spell])) { $left['trainer_phase_not_open']++; continue; }   // a trainer would teach it before its phase
            if (!$line) { $level = (int)$level ?: ($levels[$spell] ?? 0) ?: ($levels[$spell] = wowhead_spell_level($spell)); if (!$level) { $left['trainer_level_unknown']++; continue; } }
            if ($needs === null) {
                $needs = $needsOf[$spell] ?? null;
                if ($needs === null) { if ((int)$rankNo > 1) { $left['trainer_previous_rank_unknown']++; continue; } $needs = []; }
            }
            $rows['trainer_spell'][] = ['TrainerId' => $trainer, 'SpellId' => $spell, 'MoneyCost' => (int)$cost, 'ReqSkillLine' => (int)$line, 'ReqSkillRank' => (int)$rank,
                'ReqAbility1' => $needs[0] ?? 0, 'ReqAbility2' => $needs[1] ?? 0, 'ReqAbility3' => $needs[2] ?? 0, 'ReqLevel' => (int)$level, 'VerifiedBuild' => $build];
        }
    }

    // ---- what the NPC says at the turn-in: 'text' => [quest, 'complete'|'progress', text]. A row for a quest that
    // has none in that table; a quest that has a row there, with words or without, is left as it is
    $windows = ['complete' => ['quest_offer_reward', 'RewardText'], 'progress' => ['quest_request_items', 'CompletionText']];
    $said = [];
    foreach ($ev['text'] ?? [] as [$quest, $moment, $text]) if (isset($windows[$moment]) && trim((string)$text) !== '') $said[$moment][(int)$quest] = (string)$text;
    foreach ($said as $moment => $list) {
        [$table, $column] = $windows[$moment];
        if (!table_exists($table, 'world')) continue;
        $quests = $ids('SELECT ID FROM quest_template WHERE ID IN (' . $in(array_keys($list)) . ')');
        $have = $ids("SELECT ID FROM `$table` WHERE ID IN (" . $in(array_keys($list)) . ')');
        foreach ($list as $quest => $text) {
            if (!isset($quests[$quest])) { $left['quest_unknown']++; continue; }
            if (isset($have[$quest])) { $left['text_known'] = ($left['text_known'] ?? 0) + 1; continue; }
            if (isset($gaps['later']['quests'][$quest])) continue;
            $rows[$table][] = ['ID' => $quest, $column => $text, 'VerifiedBuild' => 0];
        }
    }

    foreach ($ev['left'] ?? [] as $why => $n) $left[$why] = ($left[$why] ?? 0) + $n;
    $tables = [];
    foreach ($rows as $table => $records) {
        if (!$records || !table_exists($table, 'world')) continue;
        $columns = import_columns('world', $table);
        $use = array_values(array_intersect(array_keys($records[0]), $columns));
        $tables[$table] = ['db' => 'world', 'columns' => $use, 'groups' => [['columns' => $use, 'rows' => array_map(fn($r) => array_map(fn($c) => $r[$c], $use), $records)]]];
    }
    return [$tables, array_filter($left)];
}

// ------------------------------------------------------------------ rows the server already has, measured again
// The sources keep growing: Icy Veins' players loot more corpses every day, and Blizzard rebalances. An import that only
// adds what is missing would keep the first number it ever read. So each import also compares the drops the server
// already has with what the source says now, and proposes the new chance where it moved (docs/SOURCES.md).
//
// Whose row may be changed: one an import brought (its Comment names the source), by the same source or a more trusted
// one ([sources] trust). A row no import brought (the core's own data, a hand fix) and a row of a more trusted source
// are counted and left alone. Nothing is changed without the card being applied, and each change keeps its rollback.

/** How a source is named in a loot row's Comment or a ledger note. */
const SOURCE_MARKS = ['client' => 'Forever client', 'wowhead' => 'Wowhead', 'norgannondb' => 'NorgannonDB', 'icyveins' => 'Icy Veins', 'foreverchanges' => 'ForeverChanges', 'classicdb' => 'Classic database', 'eglink' => 'EG Link', 'foreverdb' => 'ForeverDB', 'atlasloot' => 'AtlasLoot'];
/** The sources, most trusted first, when [sources] trust says nothing. The game client and Blizzard's CDN come before
 *  everything: what the client's own tables or a hotfix hold is not a matter of opinion, and no import may change a row
 *  written from them ("client" is no importer; it is in the list so that nothing ranks above it). Then Wowhead, then
 *  Questie's data (it comes through NorgannonDB), then Icy Veins; the others after them. */
const SOURCE_TRUST = 'client,wowhead,norgannondb,icyveins,foreverchanges,eglink,foreverdb,atlasloot,classicdb';

/** The sources, most trusted first: [sources] trust, then any source it leaves out in the default order. */
function source_trust(?string $configured = null): array
{
    $configured ??= (string)config('sources', 'trust', '');
    $order = [];
    foreach (array_merge(explode(',', strtolower($configured)), explode(',', SOURCE_TRUST)) as $name) {
        $name = trim($name);
        if ($name === 'questie') $name = 'norgannondb';
        if ($name === 'cdn' || $name === 'gameclient') $name = 'client';
        if (isset(SOURCE_MARKS[$name]) && !in_array($name, $order, true)) $order[] = $name;
    }
    // wherever a configuration puts it, the client is first: it is the game itself, the others describe it
    return array_values(array_unique(array_merge(['client'], $order)));
}

/** The source a Comment or a note names first ("Icy Veins 2026-11-14" -> icyveins), or null: no import wrote it. */
function source_named(?string $text): ?string
{
    $found = null; $at = PHP_INT_MAX;
    foreach (SOURCE_MARKS as $source => $mark) {
        $i = stripos((string)$text, $mark);
        if ($i !== false && $i < $at) { $found = $source; $at = $i; }
    }
    return $found;
}

/** May $source change a row that $origin wrote? 'yes'; 'core' (no import wrote it); 'trusted' (a more trusted source did). */
function source_may_change(string $source, ?string $origin, ?array $trust = null): string
{
    if ($origin === null) return 'core';
    $trust ??= source_trust();
    $mine = array_search($source, $trust, true); $theirs = array_search($origin, $trust, true);
    if ($mine === false) return 'trusted';
    return $theirs === false || $mine <= $theirs ? 'yes' : 'trusted';
}

/** A drop chance moved enough to be worth a change: by $percent % of what it was, and by 0.05 points at least (a
 *  source that counts a few more corpses shifts every number a little, and each change is a line in a file). */
function source_chance_moved(float $old, float $new, float $percent = 10.0): bool
{
    $step = abs($new - $old);
    return $step >= 0.05 && $step >= $old * $percent / 100 - 1e-9;
}

/**
 * The drops a source would change. $measured: ["table:entry:item" => chance %] as the source says now; $current:
 * the same keys => ['Chance' => float, 'Comment' => string] as the server has them. Returns [[table => [[Entry, 0,
 * Item, new chance], …]], left out]: what did not move, and what moved but belongs to the core or a more trusted source.
 */
function source_drop_changes(string $source, array $measured, array $current, float $percent = 10.0, ?array $trust = null): array
{
    $rows = []; $left = ['drop_same' => 0, 'drop_differs_core' => 0, 'drop_differs_trusted' => 0];
    foreach ($measured as $key => $chance) {
        if (!isset($current[$key]) || $chance <= 0) continue;
        $new = round(min(100, max(0.01, (float)$chance)), 2);
        if (!source_chance_moved((float)$current[$key]['Chance'], $new, $percent)) { $left['drop_same']++; continue; }
        $may = source_may_change($source, source_named($current[$key]['Comment'] ?? ''), $trust);
        if ($may !== 'yes') { $left['drop_differs_' . $may]++; continue; }
        [$table, $entry, $item] = explode(':', $key);
        $rows[$table][] = [(int)$entry, 0, (int)$item, $new];
    }
    return [$rows, array_filter($left)];
}

/** The server's drop rows for the creatures and chests of the evidence, and the evidence keyed like them: [measured, current]. */
function source_drops_now(array $ev): array
{
    $drops = ['npc' => [], 'skin' => [], 'pick' => [], 'go' => []];
    foreach ($ev['drop'] ?? [] as $d) {
        [$kind, $id, $item, $chance] = $d;
        if (!empty($d[4]) || !isset($drops[$kind])) continue;   // an even share AtlasLoot guessed is no measure
        $drops[$kind][(int)$id][(int)$item] = max($drops[$kind][(int)$id][(int)$item] ?? 0, (float)$chance);
    }
    [$found, $known] = source_loot_entries(array_keys($drops['npc'] + $drops['skin'] + $drops['pick']), array_keys($drops['go']));
    $measured = []; $current = [];
    foreach (SOURCE_LOOT_TABLES as $kind => $table) {
        // a creature's table under its own entry when its template names none (an import made it so); an object only as a chest or node
        $entryOf = [];
        foreach ($found[$kind] as $id => $entry) if ($entry || $kind !== 'go') $entryOf[$id] = $entry ?: $id;
        foreach ($drops[$kind] as $id => $list) {
            if (!isset($entryOf[$id])) continue;
            foreach ($list as $item => $chance) $measured["$table:{$entryOf[$id]}:$item"] = max($measured["$table:{$entryOf[$id]}:$item"] ?? 0, $chance);
        }
        if (!table_exists($table, 'world')) continue;
        foreach (array_chunk(array_values(array_unique($entryOf)), 500) as $chunk) {
            foreach (rows("SELECT Entry, Item, Chance, Comment FROM `$table` WHERE ItemType = 0 AND Entry IN (" . implode(',', $chunk) . ')', [], 'world') as $r) {
                $key = "$table:" . (int)$r['Entry'] . ':' . (int)$r['Item'];
                if (isset($measured[$key])) $current[$key] = ['Chance' => (float)$r['Chance'], 'Comment' => (string)$r['Comment']];
            }
        }
    }
    return [$measured, $current];
}

/** What $source would change in rows the server already has, as Forge "set" operations, and what it left alone. */
function source_refresh(array $ev, string $source): array
{
    if (!filter_var(config('sources', 'refresh', '1'), FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE)) return [[], []];
    [$measured, $current] = source_drops_now($ev);
    [$rows, $left] = source_drop_changes($source, $measured, $current, (float)(config('sources', 'chance_tolerance', 10) ?: 10));
    $changes = [];
    foreach ($rows as $table => $list) {
        $changes[] = ['db' => 'world', 'table' => $table, 'columns' => ['Entry', 'ItemType', 'Item', 'Chance'], 'match' => ['Entry', 'ItemType', 'Item'], 'set' => 'Chance', 'rows' => $list];
    }
    return [$changes, $left];
}

/** What a quest refresh may set: [table => [key column, the columns it may change (a pattern)]]. The comparison is
 *  made by tools/ft/refresh.py; this is the website's own word on what it accepts from it. */
const SOURCE_QUEST_REFRESH = [
    'quest_template' => ['ID', '/^(Reward(Item|Amount|ChoiceItemID|ChoiceItemQuantity|FactionID|FactionValue|FactionOverride|CurrencyID|CurrencyQty)\d|RewardSpell|RewardXPDifficulty|RewardXPMultiplier|LogTitle|LogDescription|QuestDescription|AreaDescription|QuestCompletionLog)$/'],
    'quest_objectives' => ['ID', '/^(Amount|Description)$/'],
    'quest_classic_level' => ['ID', '/^MinLevel$/'],
];

/**
 * The "set" operations of a quest refresh as tools/tracker.py wrote them, checked: only the tables and columns of
 * SOURCE_QUEST_REFRESH, a whole-number key, a number or a text as the value. Anything else is dropped, never repaired.
 */
function source_quest_changes(array $result): array
{
    $changes = [];
    foreach ((array)($result['changes'] ?? []) as $op) {
        $table = (string)($op['table'] ?? ''); $set = (string)($op['set'] ?? '');
        [$key, $allowed] = SOURCE_QUEST_REFRESH[$table] ?? [null, null];
        if ($key === null || !preg_match($allowed, $set) || ($op['columns'] ?? null) !== [$key, $set] || ($op['match'] ?? null) !== [$key]) continue;
        $rows = [];
        foreach ((array)($op['rows'] ?? []) as $row) {
            if (!is_array($row) || count($row) !== 2 || !is_int($row[0]) || $row[0] <= 0 || !(is_int($row[1]) || is_float($row[1]) || is_string($row[1]))) continue;
            $rows[] = [$row[0], $row[1]];
        }
        if ($rows) $changes[] = ['db' => 'world', 'table' => $table, 'columns' => [$key, $set], 'match' => [$key], 'set' => $set, 'rows' => $rows];
    }
    return $changes;
}

/**
 * The quests the server already has, compared with EG Link's newest recording of the live game: [changes, left out].
 * The comparison is the analysis' own code (tools/tracker.py refresh quests, docs/SOURCES.md): a quest's record is
 * taken only when it is from a later client build than the server's row. When it cannot be run the card is made
 * without it and says so.
 */
function source_quest_refresh(string $commit): array
{
    if (!filter_var(config('sources', 'refresh', '1'), FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE) || !preg_match('/^[0-9a-f]{40}$/', $commit)) return [[], []];
    @mkdir(import_dir(), 0775, true);
    $out = import_dir() . '/quest-refresh-' . $commit . '.json';
    @unlink($out);
    $python = (string)config('tools', 'python', PHP_OS_FAMILY === 'Windows' ? 'python' : 'python3');
    $command = escapeshellarg($python) . ' -X utf8 ' . escapeshellarg(FT_ROOT . '/tools/tracker.py') . ' refresh quests --eglink ' . escapeshellarg($commit) . ' --out ' . escapeshellarg($out) . ' 2>&1';
    $lines = []; $code = 1;
    if (function_exists('exec')) @exec($command, $lines, $code);
    $result = $code === 0 && is_file($out) ? json_decode((string)file_get_contents($out), true) : null;
    @unlink($out);
    if (!is_array($result)) {
        error_log('Forever Tracker: the quest refresh could not be run: ' . mb_substr(implode(' | ', array_slice($lines, -3)), 0, 400));
        return [[], ['quest_refresh_failed' => 1]];
    }
    $left = [];
    foreach ((array)($result['left'] ?? []) as $why => $n) if (preg_match('/^quest_[a-z_]+$/', (string)$why) && (int)$n > 0) $left[(string)$why] = (int)$n;
    return [source_quest_changes($result), $left];
}

/** Items of the drops $source may change: the ones a source that asks item by item (Icy Veins) looks up again besides the gaps. */
function source_refresh_items(string $source): array
{
    if (!filter_var(config('sources', 'refresh', '1'), FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE)) return [];
    $trust = source_trust(); $items = [];
    foreach (SOURCE_MARKS as $origin => $mark) {
        if (source_may_change($source, $origin, $trust) !== 'yes') continue;
        foreach (SOURCE_LOOT_TABLES as $table) {
            if (!table_exists($table, 'world')) continue;
            foreach (rows("SELECT DISTINCT Item FROM `$table` WHERE ItemType = 0 AND Comment LIKE ?", ['%' . addcslashes($mark, '%_\\') . '%'], 'world') as $r) $items[(int)$r['Item']] = true;
        }
    }
    return $items;
}

/**
 * Keeps the vendors and drops of $ev that one of the live-Forever recordings ($witnesses: EG Link, ForeverDB.net, Icy
 * Veins; AtlasLoot for drops) also saw: the same creature (or chest) selling or dropping the same item. NorgannonDB mixes Classic databases
 * with what its players saw: without a second source it would bring Classic test vendors (unreleased mounts, the Panda
 * Collar, soul shards for sale) and quest-only items; its quest numbers can be Season of Discovery's, reused by Forever
 * for another quest (79363 is Silvia's Sword in Duskwood, not Bath'rah's). Givers and enders need the same creature or
 * object giving or taking the same quest. Trainers are kept (checked against the server's trainers and Wowhead).
 */
function source_witnessed(array $ev, array $witnesses): array
{
    $sold = $dropped = $quests = [];
    foreach ($witnesses as $w) {
        foreach ($w['sell'] ?? [] as [$npc, $item]) $sold["$npc:$item"] = true;
        foreach ($w['drop'] ?? [] as [$kind, $id, $item]) $dropped["$kind:$id:$item"] = true;
        foreach (['start', 'end'] as $role) foreach ($w[$role] ?? [] as [$kind, $id, $quest]) $quests["$role:$kind:$id:$quest"] = true;
    }
    foreach (['start', 'end'] as $role) {
        $before = count($ev[$role] ?? []);
        $ev[$role] = array_values(array_filter($ev[$role] ?? [], fn($q) => isset($quests["$role:$q[0]:$q[1]:$q[2]"])));
        $ev['left']["quest_{$role}_no_second_source"] = ($ev['left']["quest_{$role}_no_second_source"] ?? 0) + $before - count($ev[$role]);
    }
    $before = [count($ev['sell'] ?? []), count($ev['drop'] ?? [])];
    $ev['sell'] = array_values(array_filter($ev['sell'] ?? [], fn($s) => isset($sold["$s[0]:$s[1]"])));
    $ev['drop'] = array_values(array_filter($ev['drop'] ?? [], fn($d) => isset($dropped["$d[0]:$d[1]:$d[2]"])));
    $ev['left']['vendor_no_second_source'] = ($ev['left']['vendor_no_second_source'] ?? 0) + $before[0] - count($ev['sell']);
    $ev['left']['drop_no_second_source'] = ($ev['left']['drop_no_second_source'] ?? 0) + $before[1] - count($ev['drop']);
    return $ev;
}

/** A profession's skill line from the name a trainer shows ("Skinning", or the spell "Journeyman Skinning"); 0 when unknown. */
function source_skill_line(string $skill, string $spellName): int
{
    if (isset(SOURCE_SKILLS[$skill])) return SOURCE_SKILLS[$skill];
    foreach (SOURCE_SKILLS as $name => $line) if (preg_match('/^(Apprentice|Journeyman|Expert|Artisan|Master|Grand Master) ' . preg_quote($name, '/') . '$/', $spellName)) return $line;
    return 0;
}

/**
 * The cards a new card of $source replaces: that source's earlier cards (file "<source>@…") nothing was ever applied
 * from. $cards: [id => file] of ft_imports; $logs: the history's import operations (items, state of ft_forge_log).
 * A card an operation was applied from is kept, rolled back since or not (it may be applied in part, and the card
 * says what the rest is), and so is one whose apply is still being written; a failed apply wrote nothing. The history
 * keeps its own SQL and rollback: forgetting a card takes nothing from it.
 */
function source_stale_cards(string $source, array $cards, array $logs): array
{
    $used = [];
    foreach ($logs as $log) {
        if (($log['state'] ?? '') === 'failed') continue;
        $items = is_array($log['items'] ?? null) ? $log['items'] : (json_decode((string)($log['items'] ?? ''), true) ?: []);
        foreach ($items as $item) if (is_array($item) && ($item['type'] ?? '') === 'import') $used[(int)($item['id'] ?? 0)] = true;
    }
    $stale = [];
    foreach ($cards as $id => $file) if (str_starts_with((string)$file, $source . '@') && !isset($used[(int)$id])) $stale[] = (int)$id;
    return $stale;
}

/** Forgets the cards a new card of $source replaces (source_stale_cards); returns how many. */
function source_supersede(string $source): int
{
    import_schema();
    forge_schema();
    $cards = array_column(rows('SELECT id, file FROM ft_imports WHERE file LIKE ?', [addcslashes($source, '%_\\') . '@%']), 'file', 'id');
    if (!$cards) return 0;
    $stale = source_stale_cards($source, $cards, rows("SELECT items, state FROM ft_forge_log WHERE FIND_IN_SET('import', kind)"));
    foreach ($stale as $id) import_delete($id);
    return count($stale);
}

/** Saves tables as an import card (preview, apply, history, rollback, data repo export). */
function source_card(string $source, string $name, string $file, array $tables, array $left, array $changes = []): array
{
    import_schema();
    // every card is built against the gaps and the database as they are now, so the newest one of a source says all
    // its earlier ones said and is still true: without this each new AtlasLoot version and each click left one more
    // card for the same gap. Also when the new card would be empty: the old ones then offer what is no longer missing.
    $replaced = source_supersede($source);
    $replacedNote = $replaced ? ' ' . sprintf(t('%d earlier card(s) of this source that were never applied were replaced.', '%d carte(s) précédente(s) de cette source, jamais appliquée(s), ont été remplacée(s).'), $replaced) : '';
    if (!$tables && !$changes) return ['ok' => false, 'id' => 0, 'counts' => [], 'ignored' => $left, 'replaced' => $replaced,
        'message' => sprintf(t('%s has nothing this server lacks, and nothing it has moved.', '%s n’a rien qui manque à ce serveur, et rien de ce qu’il a n’a bougé.'), SOURCES[$source][0] ?? $source) . $replacedNote];
    $counts = []; foreach ($tables as $table => $entry) $counts[$table] = count($entry['groups'][0]['rows']);
    // values measured again: one line of the card each ("creature_loot_template.Chance"), ticked or not like a table
    $moved = 0;
    foreach ($changes as $op) { $counts[$op['table'] . '.' . $op['set']] = count($op['rows']); $moved += count($op['rows']); }
    $name .= ' · ' . (SOURCES[$source][1] ?? '');
    rows('INSERT INTO ft_imports (name, file, admin, counts, ignored) VALUES (?, ?, ?, ?, ?)', [$name, $file, (string)(admin()['name'] ?? 'cli'), json_encode($counts), json_encode($left)]);
    $id = (int)db()->insert_id;
    @mkdir(import_dir() . '/parsed', 0775, true);
    file_put_contents(import_dir() . "/parsed/$id.json", json_encode(['tables' => $tables, 'changes' => $changes], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE | JSON_PRESERVE_ZERO_FRACTION));
    import_index($id, $tables);
    return ['ok' => true, 'id' => $id, 'counts' => $counts, 'ignored' => $left, 'bad' => 0, 'statements' => 0, 'replaced' => $replaced, 'moved' => $moved,
            'message' => sprintf(t('%s: %s rows for what the server lacks.', '%s : %s lignes pour ce qui manque au serveur.'), $name, number(array_sum($counts) - $moved))
                . ($moved ? ' ' . sprintf(t('%s value(s) it measured again differ from the server’s.', '%s valeur(s) qu’il a mesurées à nouveau diffèrent de celles du serveur.'), number($moved)) : '') . $replacedNote];
}

/** GET with a user agent; [status, body, length]: the size the server announced for the body (Content-Length), null
 *  when it gave none. A connection that drops or times out half way still hands back what came: only the announced
 *  size, or the content itself (source_keep), tells a whole answer from a piece of one. */
function source_http(string $url, int $timeout = 60): array
{
    $context = stream_context_create(['http' => ['timeout' => $timeout, 'ignore_errors' => true,
        'header' => "User-Agent: ForeverTracker/1.1 (private server admin tool)\r\nAccept: application/json, */*\r\n"]]);
    $body = @file_get_contents($url, false, $context);
    [$status, $length] = source_http_head($http_response_header ?? []);
    return [$status, $body === false ? '' : $body, $length];
}

/** [status, announced body size or null] of the last answer in a list of response headers (redirects come first). */
function source_http_head(array $headers): array
{
    $status = 0; $length = null; $encoded = false;
    foreach ($headers as $h) {
        if (preg_match('#^HTTP/\S+ (\d+)#', $h, $m)) { $status = (int)$m[1]; $length = null; $encoded = false; }
        elseif (preg_match('/^Content-Length:\s*(\d+)\s*$/i', $h, $m)) $length = (int)$m[1];
        elseif (preg_match('/^Content-Encoding:\s*(?!identity)\S/i', $h)) $encoded = true;   // the size is then the packed one
    }
    return [$status, $encoded ? null : $length];
}

/**
 * Keeps a downloaded body as $path, when it came whole: its size is the one the server announced ($length, null when
 * it announced none) and $valid, when given, accepts the content. It is written beside the file and renamed into
 * place, so neither a download cut short nor a run killed while writing leaves a file that later passes for the real
 * one (a cut NorgannonDB file was kept for its commit for good; a cut EG Link file read as an empty list). Returns ''
 * or why it was not kept, which also goes to the error log.
 */
function source_keep(string $path, string $body, ?int $length = null, ?callable $valid = null): string
{
    if ($length !== null && strlen($body) !== $length) {
        $problem = sprintf(t('%s bytes came of the %s announced', '%s octets reçus sur les %s annoncés'), number(strlen($body)), number($length));
    } elseif ($valid !== null && !$valid($body)) {
        $problem = t('the content is cut short or not what was expected', 'le contenu est tronqué ou inattendu');
    } else {
        @mkdir(dirname($path), 0775, true);
        $part = $path . '.' . getmypid() . '.part';
        if (@file_put_contents($part, $body) === strlen($body) && @rename($part, $path)) return '';
        @unlink($part);
        $problem = t('the file cannot be written', 'le fichier ne peut pas être écrit');
    }
    error_log('Forever Tracker: download not kept (' . basename(dirname($path)) . '/' . basename($path) . '): ' . $problem);
    return $problem;
}

/** `ns.<name> = {...}` tables of a ForeverDB.net data file (only the named ones are parsed). */
function source_lua_assignments(string $text, array $names): array
{
    $out = [];
    preg_match_all('/^ns\.(\w+) = /m', $text, $m, PREG_OFFSET_CAPTURE);
    foreach ($m[1] as $i => [$name, $at]) {
        if (!in_array($name, $names, true)) continue;
        $end = $m[0][$i + 1][1] ?? strlen($text);
        $out[$name] = collector_lua(substr($text, $at, $end - $at));
    }
    return $out;
}

function source_check(): ?array
{
    if (!table_exists('ft_entities')) return ['ok' => false, 'message' => t('Run the analysis first: the import aims at its gaps.', 'Lancez d’abord l’analyse : l’import vise ses manques.')];
    @ini_set('memory_limit', '2048M');
    @set_time_limit(0);
    return null;
}

// ------------------------------------------------------------------ The original game's database, from a file
// cmangos' classic-db is the content of the 1.12 game, not of WoW: Forever. It is the last source asked, and only about
// profession recipes nobody can learn on this server: who trained them, which quest's turn-in cast them. The tracker
// reads a pack made from the project's own dump (tools/classicdb_pack.py), sent through the Imports page; it never
// downloads it. tools/tracker.py classic matches the pack to the gaps (ft.classic, docs/SOURCES.md).

function classicdb_pack(): string { return FT_ROOT . '/data/classicdb/pack.cdbpack'; }

/** The evidence tools/tracker.py made from a pack, checked: trainer lines of whole numbers with a skill line, the
 *  counted reasons that are its own. Anything else is dropped. */
function classicdb_evidence(array $result): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => [], 'left' => []];
    $count = fn($v) => is_int($v) && $v >= 0;
    foreach ((array)($result['ev']['train'] ?? []) as $r) {
        if (!is_array($r) || count($r) !== 8 || !is_int($r[0]) || $r[0] <= 0 || !is_int($r[1]) || $r[1] <= 0 || !$count($r[2]) || !$count($r[3])
            || !is_int($r[4]) || $r[4] <= 0 || !$count($r[5]) || $r[6] !== [] || $r[7] !== 1) continue;
        $ev['train'][] = [$r[0], $r[1], $r[2], $r[3], $r[4], $r[5], [], 1];
    }
    foreach ((array)($result['ev']['talk'] ?? []) as $r) if (($line = classicdb_talk_line($r)) !== null) $ev['talk'][] = $line;
    foreach ((array)($result['left'] ?? []) as $why => $n) if (preg_match('/^classic_[a-z_]+$/', (string)$why) && (int)$n > 0) $ev['left'][(string)$why] = (int)$n;
    return $ev;
}

/** A conversation line of the evidence, checked: ['npc'|'go', entry, text, recipe, spell it casts, terms]. */
function classicdb_talk_line($r): ?array
{
    $whole = fn($v) => is_int($v) && $v > 0;
    if (!is_array($r) || count($r) !== 6 || !in_array($r[0], ['npc', 'go'], true) || !$whole($r[1]) || !is_string($r[2]) || !$whole($r[3]) || !$whole($r[4]) || !is_array($r[5])) return null;
    $text = trim($r[2]);
    if ($text === '' || mb_strlen($text) > 500 || preg_match('/[\x00-\x1f\x7f]/u', $text)) return null;
    $width = ['skill' => 3, 'quest' => 2, 'rep' => 3, 'level' => 2, 'knows' => 2, 'lacks' => 2];
    foreach ($r[5] as $t) {
        if (!is_array($t) || !isset($t[0], $width[$t[0]]) || count($t) !== $width[$t[0]]) return null;
        foreach (array_slice($t, 1) as $v) if (!is_int($v) || $v < 0) return null;
        if ($t[0] === 'rep' && $t[2] > 7) return null;
    }
    return [$r[0], $r[1], $text, $r[3], $r[4], array_values($r[5])];
}

/** Conversation menus of their own, where a template has none: 1,000,000 plus a creature's number, 2,000,000 plus an object's. */
const CLASSICDB_MENU_BASE = ['npc' => 1000000, 'go' => 2000000];
/** The column holding an object's conversation menu, by its type (GameObjectTemplate::GetGossipMenuId of the core). */
const CLASSICDB_GO_MENU = [2 => 'Data3', 8 => 'Data10', 10 => 'Data19', 64 => 'Data2'];
/** The core's own scripts that teach a spell in their conversation (tools/ft/server.py CORE_TEACHERS): a creature
 *  without a script gets the script's name instead of SmartAI, which would only repeat part of what the script does. */
const CLASSICDB_CORE_TEACHERS = [14894 => 'boss_gloomrel'];
const CLASSICDB_AI = ['npc' => 'SmartAI', 'go' => 'SmartGameObjectAI'];

/** Classic's terms as rows of `conditions` for a menu option (source type 15). Returns null for a term it cannot write. */
function classicdb_conditions(array $terms, int $menu, int $option, string $comment): ?array
{
    $rows = [];
    foreach ($terms as $t) {
        switch ($t[0]) {
            case 'skill': [$type, $v1, $v2, $not] = [7, $t[1], $t[2], 0]; break;            // CONDITION_SKILL: at least that value
            case 'quest': [$type, $v1, $v2, $not] = [8, $t[1], 0, 0]; break;                 // CONDITION_QUESTREWARDED
            case 'rep':   [$type, $v1, $v2, $not] = [5, $t[1], array_sum(array_map(fn($rank) => 1 << $rank, range($t[2], 7))), 0]; break;   // a mask of the ranks: that one or higher
            case 'level': [$type, $v1, $v2, $not] = [27, $t[1], 3, 0]; break;                // CONDITION_LEVEL, COMP_TYPE_HIGH_EQ
            case 'knows': [$type, $v1, $v2, $not] = [25, $t[1], 0, 0]; break;                // CONDITION_SPELL
            case 'lacks': [$type, $v1, $v2, $not] = [25, $t[1], 0, 1]; break;
            default: return null;
        }
        $rows["$type:$v1:$v2:$not"] = ['SourceTypeOrReferenceId' => 15, 'SourceGroup' => $menu, 'SourceEntry' => $option, 'SourceId' => 0, 'ElseGroup' => 0,
            'ConditionTypeOrReference' => $type, 'ConditionTarget' => 0, 'ConditionValue1' => $v1, 'ConditionValue2' => $v2, 'ConditionValue3' => 0,
            'NegativeCondition' => $not, 'ErrorType' => 0, 'ErrorTextId' => 0, 'ScriptName' => '', 'Comment' => mb_substr($comment, 0, 255)];
    }
    return array_values($rows);
}

/**
 * The conversation lines that teach a recipe the server lacks, as rows: the line in the conversation the creature or
 * object already opens (or a menu of its own when it opens none), Classic's conditions on it, and SmartAI that casts
 * the spell when the line is picked and closes the conversation. Returns [rows by table, value changes, left out].
 * $state: by "kind:entry": known, spawned, script, ai, type (an object's), menus [menu ids], shared [menu => true],
 * options [menu => [OptionID => text]], smart (the highest SmartAI id), taken [menu => true] (numbers in use).
 */
function classicdb_talk_rows(array $talk, array $state, int $build, array $names = []): array
{
    $rows = []; $changes = []; $left = [];
    $count = function (string $why) use (&$left) { $left[$why] = ($left[$why] ?? 0) + 1; };
    $byTeacher = [];
    foreach ($talk as $line) $byTeacher[$line[0] . ':' . $line[1]][] = $line;
    foreach ($byTeacher as $key => $lines) {
        [$kind, $entry] = [$lines[0][0], $lines[0][1]];
        $s = $state[$key] ?? [];
        if (empty($s['known'])) { foreach ($lines as $_) $count('classic_talk_unknown'); continue; }
        if (empty($s['spawned'])) { foreach ($lines as $_) $count('classic_talk_not_spawned'); continue; }
        $script = (string)($s['script'] ?? ''); $ai = (string)($s['ai'] ?? '');
        // one of the core's own scripts: name it on a creature that has none
        $scripted = array_values(array_filter($lines, fn($l) => $kind === 'npc' && isset(CLASSICDB_CORE_TEACHERS[$l[4]])));
        if ($scripted) {
            $name = CLASSICDB_CORE_TEACHERS[$scripted[0][4]];
            if ($script === '' && $ai === '') $changes['creature_template.ScriptName'][] = [$entry, $name];
            else foreach ($scripted as $_) $count($script === $name ? 'classic_talk_known' : 'classic_talk_other_script');
            $lines = array_values(array_filter($lines, fn($l) => !isset(CLASSICDB_CORE_TEACHERS[$l[4]])));
            if (!$lines) continue;
        }
        if ($script !== '') { foreach ($lines as $_) $count('classic_talk_other_script'); continue; }   // a script's own AI: SmartAI would not run
        if ($ai !== '' && $ai !== CLASSICDB_AI[$kind]) { foreach ($lines as $_) $count('classic_talk_other_ai'); continue; }
        if ($kind === 'go' && !isset(CLASSICDB_GO_MENU[(int)($s['type'] ?? -1)])) { foreach ($lines as $_) $count('classic_talk_object_type'); continue; }
        // the menu the lines go into
        $menus = array_values(array_unique(array_map('intval', $s['menus'] ?? [])));
        if (count($menus) > 1) { foreach ($lines as $_) $count('classic_talk_several_menus'); continue; }
        if ($menus) {
            $menu = $menus[0];
            if (!empty($s['shared'][$menu])) { foreach ($lines as $_) $count('classic_talk_menu_shared'); continue; }   // another NPC or object opens it too
        } else {
            $menu = CLASSICDB_MENU_BASE[$kind] + $entry;
            if (!empty($s['taken'][$menu])) { foreach ($lines as $_) $count('classic_talk_menu_number_taken'); continue; }
            if ($kind === 'npc') $rows['creature_template_gossip'][] = ['CreatureID' => $entry, 'MenuID' => $menu, 'VerifiedBuild' => $build];
            else $changes['gameobject_template.' . CLASSICDB_GO_MENU[(int)$s['type']]][] = [$entry, $menu];
        }
        $options = $s['options'][$menu] ?? [];
        $said = array_map(fn($t) => mb_strtolower(trim((string)$t)), $options);
        $next = $options ? max(array_keys($options)) + 1 : 0;
        $smart = (int)($s['smart'] ?? -1) + 1;
        $wrote = false;
        foreach ($lines as [, , $text, $recipe, $cast, $terms]) {
            if (in_array(mb_strtolower($text), $said, true)) { $count('classic_talk_known'); continue; }
            $who = $names[$kind][(string)$entry] ?? '';
            $conditions = classicdb_conditions($terms, $menu, $next, trim("$who: learn $recipe (Classic database)"));
            if ($conditions === null) { $count('classic_talk_condition'); continue; }
            $rows['gossip_menu_option'][] = ['MenuID' => $menu, 'GossipOptionID' => 0, 'OptionID' => $next, 'OptionNpc' => 0, 'OptionText' => $text,
                'OptionBroadcastTextID' => 0, 'Language' => 0, 'Flags' => 0, 'ActionMenuID' => 0, 'ActionPoiID' => 0, 'BoxCoded' => 0, 'BoxMoney' => 0,
                'BoxText' => '', 'BoxBroadcastTextID' => 0, 'VerifiedBuild' => $build];
            foreach ($conditions as $c) $rows['conditions'][] = $c;
            foreach ([[134, $cast], [72, 0]] as [$action, $spell]) {   // INVOKER_CAST on the player, then CLOSE_GOSSIP
                $rows['smart_scripts'][] = ['entryorguid' => $entry, 'source_type' => $kind === 'npc' ? 0 : 1, 'id' => $smart++, 'link' => 0, 'Difficulties' => '',
                    'event_type' => 62, 'event_phase_mask' => 0, 'event_chance' => 100, 'event_flags' => 0, 'event_param1' => $menu, 'event_param2' => $next,
                    'event_param3' => 0, 'event_param4' => 0, 'event_param5' => 0, 'event_param_string' => '', 'action_type' => $action, 'action_param1' => $spell,
                    'action_param2' => 0, 'action_param3' => 0, 'action_param4' => 0, 'action_param5' => 0, 'action_param6' => 0, 'action_param7' => 0,
                    'action_param_string' => '', 'target_type' => 7, 'target_param1' => 0, 'target_param2' => 0, 'target_param3' => 0, 'target_param4' => 0,
                    'target_param_string' => '', 'target_x' => 0, 'target_y' => 0, 'target_z' => 0, 'target_o' => 0,
                    'comment' => mb_substr(trim("$who - On Gossip Option $next Selected - " . ($action === 134 ? "Invoker Cast $spell (learn $recipe)" : 'Close Gossip')), 0, 1000)];
            }
            $said[] = mb_strtolower($text);
            $next++; $wrote = true;
        }
        if (!$wrote) continue;
        if ($ai === '') $changes[($kind === 'npc' ? 'creature' : 'gameobject') . '_template.AIName'][] = [$entry, CLASSICDB_AI[$kind]];
        if ($kind === 'npc') $changes['creature_template.npcflag'][] = [$entry, 1];   // UNIT_NPC_FLAG_GOSSIP: a creature players can talk to
    }
    $ops = [];
    foreach ($changes as $what => $list) {
        [$table, $column] = explode('.', $what);
        $ops[] = ['db' => 'world', 'table' => $table, 'columns' => ['entry', $column], 'match' => ['entry'], 'set' => $column,
            ($column === 'npcflag' ? 'bits' : 'fill') => $column, 'rows' => $list];
    }
    return [$rows, $ops, $left];
}

/** What classicdb_talk_rows() needs to know about the creatures and objects of these lines, read from the world. */
function classicdb_talk_state(array $talk): array
{
    $state = [];
    $ids = ['npc' => [], 'go' => []];
    foreach ($talk as $line) $ids[$line[0]][$line[1]] = true;
    $in = fn(array $list) => implode(',', array_map('intval', $list)) ?: '0';
    $npcs = array_keys($ids['npc']); $gos = array_keys($ids['go']);
    $columns = array_unique(array_values(CLASSICDB_GO_MENU));
    if ($npcs) {
        foreach (rows('SELECT entry, ScriptName, AIName FROM creature_template WHERE entry IN (' . $in($npcs) . ')', [], 'world') as $r)
            $state['npc:' . (int)$r['entry']] = ['known' => true, 'script' => (string)$r['ScriptName'], 'ai' => (string)$r['AIName'], 'menus' => []];
        foreach (rows('SELECT DISTINCT id FROM creature WHERE id IN (' . $in($npcs) . ')', [], 'world') as $r) $state['npc:' . (int)$r['id']]['spawned'] = true;
        foreach (rows('SELECT CreatureID, MenuID FROM creature_template_gossip WHERE CreatureID IN (' . $in($npcs) . ')', [], 'world') as $r)
            $state['npc:' . (int)$r['CreatureID']]['menus'][] = (int)$r['MenuID'];
    }
    if ($gos) {
        foreach (rows('SELECT entry, type, ScriptName, AIName, ' . implode(', ', $columns) . ' FROM gameobject_template WHERE entry IN (' . $in($gos) . ')', [], 'world') as $r) {
            $column = CLASSICDB_GO_MENU[(int)$r['type']] ?? null;
            $state['go:' . (int)$r['entry']] = ['known' => true, 'type' => (int)$r['type'], 'script' => (string)$r['ScriptName'], 'ai' => (string)$r['AIName'],
                'menus' => $column && (int)$r[$column] > 0 ? [(int)$r[$column]] : []];
        }
        foreach (rows('SELECT DISTINCT id FROM gameobject WHERE id IN (' . $in($gos) . ')', [], 'world') as $r) $state['go:' . (int)$r['id']]['spawned'] = true;
    }
    // the menus in play: who else opens them, the lines they hold; the numbers a menu of its own would take
    $menus = []; $own = [];
    foreach ($state as $key => $s) {
        foreach ($s['menus'] ?? [] as $m) $menus[$m] = true;
        [$kind, $entry] = explode(':', $key);
        $own[CLASSICDB_MENU_BASE[$kind] + (int)$entry] = true;
    }
    $menuIds = array_keys($menus);
    if ($menuIds) {
        $users = [];
        foreach (rows('SELECT CreatureID, MenuID FROM creature_template_gossip WHERE MenuID IN (' . $in($menuIds) . ')', [], 'world') as $r) $users[(int)$r['MenuID']]['npc:' . (int)$r['CreatureID']] = true;
        foreach (CLASSICDB_GO_MENU as $type => $column) {
            foreach (rows("SELECT entry, $column m FROM gameobject_template WHERE type = $type AND $column IN (" . $in($menuIds) . ')', [], 'world') as $r) $users[(int)$r['m']]['go:' . (int)$r['entry']] = true;
        }
        foreach ($state as $key => &$s) foreach ($s['menus'] ?? [] as $m) if (count(array_diff_key($users[$m] ?? [], [$key => true])) > 0) $s['shared'][$m] = true;
        unset($s);
        $options = [];
        foreach (rows('SELECT MenuID, OptionID, OptionText FROM gossip_menu_option WHERE MenuID IN (' . $in($menuIds) . ')', [], 'world') as $r) $options[(int)$r['MenuID']][(int)$r['OptionID']] = (string)$r['OptionText'];
        foreach ($state as &$s) foreach ($s['menus'] ?? [] as $m) $s['options'][$m] = $options[$m] ?? [];
        unset($s);
    }
    if ($own) {
        $taken = [];
        foreach (['SELECT DISTINCT MenuID m FROM gossip_menu_option WHERE MenuID IN (%s)', 'SELECT DISTINCT MenuID m FROM creature_template_gossip WHERE MenuID IN (%s)',
                  'SELECT DISTINCT MenuID m FROM gossip_menu WHERE MenuID IN (%s)'] as $sql) {
            foreach (rows(sprintf($sql, $in(array_keys($own))), [], 'world') as $r) $taken[(int)$r['m']] = true;
        }
        foreach ($state as $key => &$s) { [$kind, $entry] = explode(':', $key); $n = CLASSICDB_MENU_BASE[$kind] + (int)$entry; if (isset($taken[$n])) $s['taken'][$n] = true; }
        unset($s);
    }
    foreach ($state as $key => &$s) {
        [$kind, $entry] = explode(':', $key);
        $s['smart'] = (int)(value('SELECT COALESCE(MAX(id), -1) FROM smart_scripts WHERE entryorguid = ? AND source_type = ?', [(int)$entry, $kind === 'npc' ? 0 : 1], 'world') ?? -1);
    }
    unset($s);
    return $state;
}

/** The quests whose turn-in should cast a spell: quest_template.RewardSpell only, and written only where the quest
 *  casts nothing yet (the operation fills, it never replaces). */
function classicdb_changes(array $result): array
{
    $changes = [];
    foreach (source_quest_changes($result) as $op) {
        if ($op['table'] !== 'quest_template' || $op['set'] !== 'RewardSpell') continue;
        $op['rows'] = array_values(array_filter($op['rows'], fn($row) => is_int($row[1]) && $row[1] > 0));
        if ($op['rows']) $changes[] = $op + ['fill' => 'RewardSpell'];
    }
    return $changes;
}

/** A trainer list of its own for a creature takes this number plus the creature's: the convention the world data follows. */
const CLASSICDB_TRAINER_BASE = 1000000;
const CLASSICDB_TRADESKILL = 2;   // trainer.Type

/**
 * The trainer lines whose creature is no trainer on this server. Where the creature exists and stands in the world,
 * it becomes one: a trainer list of its own, the link to it and its spells (applying the card adds the trainer flag,
 * as it adds the vendor flag). Returns [rows by table, left out, the lines of creatures that are trainers already].
 * $state: sets keyed by number: 'trainer' (creatures that have a list), 'known' (templates), 'spawned', 'taken'
 * (trainer lists that exist), 'later' (spells of a release phase that is not open).
 */
function classicdb_trainer_rows(array $train, array $state, int $build): array
{
    $rows = []; $left = []; $rest = [];
    $byNpc = [];
    foreach ($train as $line) $byNpc[$line[0]][] = $line;
    foreach ($byNpc as $npc => $lines) {
        if (isset($state['trainer'][$npc])) { array_push($rest, ...$lines); continue; }
        $lines = array_values(array_filter($lines, fn($line) => !isset($state['later'][$line[1]])));
        if (!$lines) continue;
        $n = count($lines);
        if (!isset($state['known'][$npc])) { $left['trainer_not_on_server'] = ($left['trainer_not_on_server'] ?? 0) + $n; continue; }
        if (!isset($state['spawned'][$npc])) { $left['classic_trainer_not_spawned'] = ($left['classic_trainer_not_spawned'] ?? 0) + $n; continue; }
        $id = CLASSICDB_TRAINER_BASE + $npc;
        if (isset($state['taken'][$id])) { $left['classic_trainer_number_taken'] = ($left['classic_trainer_number_taken'] ?? 0) + $n; continue; }
        $rows['trainer'][] = ['Id' => $id, 'Type' => CLASSICDB_TRADESKILL, 'Greeting' => '', 'VerifiedBuild' => $build];
        $rows['creature_trainer'][] = ['CreatureID' => $npc, 'TrainerID' => $id, 'MenuID' => 0, 'OptionID' => 0];
        foreach ($lines as [, $spell, $cost, $level, $line, $rank]) {
            $rows['trainer_spell'][] = ['TrainerId' => $id, 'SpellId' => $spell, 'MoneyCost' => $cost, 'ReqSkillLine' => $line, 'ReqSkillRank' => $rank,
                'ReqAbility1' => 0, 'ReqAbility2' => 0, 'ReqAbility3' => 0, 'ReqLevel' => $level, 'VerifiedBuild' => $build];
        }
    }
    return [$rows, $left, $rest];
}

/** What classicdb_trainer_rows() needs to know about the creatures of these trainer lines, read from the world. */
function classicdb_trainer_state(array $train, array $gaps): array
{
    $npcs = array_values(array_unique(array_map(fn($line) => (int)$line[0], $train)));
    $state = ['trainer' => [], 'known' => [], 'spawned' => [], 'taken' => [], 'later' => $gaps['later']['spells'] ?? []];
    $set = function (string $sql): array { $out = []; foreach (rows($sql, [], 'world') as $r) $out[(int)reset($r)] = true; return $out; };
    foreach (array_chunk($npcs, 1000) as $chunk) {
        $in = implode(',', $chunk);
        $state['trainer'] += $set("SELECT DISTINCT CreatureID FROM creature_trainer WHERE CreatureID IN ($in)");
        $state['known'] += $set("SELECT entry FROM creature_template WHERE entry IN ($in)");
        $state['spawned'] += $set("SELECT DISTINCT id FROM creature WHERE id IN ($in)");
        $state['taken'] += $set('SELECT Id FROM trainer WHERE Id IN (' . implode(',', array_map(fn($npc) => CLASSICDB_TRAINER_BASE + $npc, $chunk)) . ')');
    }
    return $state;
}

/** Rows by table in the shape of an import's tables, with the columns this server's tables have. */
function classicdb_tables(array $rows): array
{
    $tables = [];
    foreach ($rows as $table => $records) {
        if (!$records || !table_exists($table, 'world')) continue;
        $use = array_values(array_intersect(array_keys($records[0]), import_columns('world', $table)));
        $tables[$table] = ['db' => 'world', 'columns' => $use, 'groups' => [['columns' => $use, 'rows' => array_map(fn($r) => array_map(fn($c) => $r[$c], $use), $records)]]];
    }
    return $tables;
}

function classicdb_import(): array
{
    if ($e = source_check()) return $e;
    $pack = classicdb_pack();
    if (!is_file($pack)) return ['ok' => false, 'message' => t('No Classic database pack yet: make one with tools/classicdb_pack.py and send the .cdbpack file here.', 'Pas encore de paquet de la base Classic : créez-en un avec tools/classicdb_pack.py et envoyez ici le fichier .cdbpack.')];
    $out = dirname($pack) . '/evidence.json';
    @unlink($out);
    $python = (string)config('tools', 'python', PHP_OS_FAMILY === 'Windows' ? 'python' : 'python3');
    $command = escapeshellarg($python) . ' -X utf8 ' . escapeshellarg(FT_ROOT . '/tools/tracker.py') . ' classic --pack ' . escapeshellarg($pack) . ' --out ' . escapeshellarg($out) . ' 2>&1';
    $lines = []; $code = 1;
    if (function_exists('exec')) @exec($command, $lines, $code);
    $result = $code === 0 && is_file($out) ? json_decode((string)file_get_contents($out), true) : null;
    @unlink($out);
    if (!is_array($result)) {
        error_log('Forever Tracker: the Classic database pack could not be read: ' . mb_substr(implode(' | ', array_slice($lines, -3)), 0, 400));
        return ['ok' => false, 'message' => t('The Classic database pack could not be read (see the PHP error log). Is it a .cdbpack file made by tools/classicdb_pack.py, and has the analysis run?', 'Le paquet de la base Classic n’a pas pu être lu (voir le journal d’erreurs PHP). Est-ce un fichier .cdbpack créé par tools/classicdb_pack.py, et l’analyse a-t-elle tourné ?')];
    }
    $made = preg_match('/^\d{4}-\d{2}-\d{2}$/', (string)($result['made'] ?? '')) ? (string)$result['made'] : date('Y-m-d', (int)filemtime($pack));
    $label = 'Classic database ' . $made;
    $ev = classicdb_evidence($result);
    $gaps = source_gaps();
    // a creature Classic trains at that is no trainer here gets a list of its own; the others' lines go the usual way
    [$own, $ownLeft, $ev['train']] = classicdb_trainer_rows($ev['train'], classicdb_trainer_state($ev['train'], $gaps), (int)(meta()['client_build'] ?? 0));
    [$tables, $left] = source_tables($ev, $label, $gaps);
    foreach (classicdb_tables($own) as $table => $entry) {
        if (!isset($tables[$table])) { $tables[$table] = $entry; continue; }
        // trainer_spell of both kinds: the same columns in the same order, one list
        if ($tables[$table]['columns'] === $entry['columns']) $tables[$table]['groups'][0]['rows'] = array_merge($tables[$table]['groups'][0]['rows'], $entry['groups'][0]['rows']);
    }
    foreach ($ownLeft as $why => $n) $left[$why] = ($left[$why] ?? 0) + $n;
    // the conversation lines that teach a recipe: the line, its conditions and the SmartAI that casts the spell
    $talk = array_values(array_filter($ev['talk'] ?? [], fn($line) => !isset($gaps['later']['spells'][$line[3]])));
    $names = ['npc' => (array)($result['names']['npc'] ?? []), 'go' => (array)($result['names']['go'] ?? [])];
    [$spoken, $talkChanges, $talkLeft] = $talk ? classicdb_talk_rows($talk, classicdb_talk_state($talk), (int)(meta()['client_build'] ?? 0), $names) : [[], [], []];
    foreach (classicdb_tables($spoken) as $table => $entry) $tables[$table] = $entry;
    foreach ($talkLeft as $why => $n) $left[$why] = ($left[$why] ?? 0) + $n;
    return source_card('classicdb', $label, 'classicdb@' . $made, $tables, $left, array_merge(classicdb_changes($result), $talkChanges));
}

// ------------------------------------------------------------------ ForeverChanges (players' reports, from a file)
// foreverchanges.pro collects what its players' addon saw on live WoW Forever, over a base of Classic's data. The
// tracker never asks the site: it reads a pack made from a copy of it (tools/foreverchanges_pack.py), sent through
// this page. The site names NPCs and places them on a map; tools/tracker.py matches those to the server's creatures
// (ft.reports) and hands back the same evidence every other source gives.

function foreverchanges_pack(): string { return FT_ROOT . '/data/foreverchanges/pack.fcpack'; }

/** The evidence tools/tracker.py made from a pack, checked: every row whole numbers of the right shape, the kinds
 *  'npc' and 'go', a chance between 0 and 100. Anything else is dropped. */
function foreverchanges_evidence(array $result): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => []];
    $whole = fn($v) => is_int($v) && $v > 0;
    foreach (['start', 'end'] as $role) foreach ((array)($result['ev'][$role] ?? []) as $r) {
        if (is_array($r) && count($r) === 3 && in_array($r[0], ['npc', 'go'], true) && $whole($r[1]) && $whole($r[2])) $ev[$role][] = [$r[0], $r[1], $r[2]];
    }
    foreach ((array)($result['ev']['sell'] ?? []) as $r) if (is_array($r) && count($r) === 3 && $whole($r[0]) && $whole($r[1]) && is_int($r[2]) && $r[2] >= 0) $ev['sell'][] = [$r[0], $r[1], $r[2]];
    foreach ((array)($result['ev']['drop'] ?? []) as $r) {
        if (is_array($r) && count($r) === 4 && $r[0] === 'npc' && $whole($r[1]) && $whole($r[2]) && (is_int($r[3]) || is_float($r[3])) && $r[3] > 0 && $r[3] <= 100) $ev['drop'][] = ['npc', $r[1], $r[2], (float)$r[3]];
    }
    // what the NPC says: a quest, the window, and words a row can hold (no control characters but none are expected:
    // line breaks are written $B)
    foreach ((array)($result['ev']['text'] ?? []) as $r) {
        if (is_array($r) && count($r) === 3 && $whole($r[0]) && in_array($r[1], ['complete', 'progress'], true) && is_string($r[2])
            && trim($r[2]) !== '' && strlen($r[2]) <= 8000 && !preg_match('/[\x00-\x1f\x7f]|‹|›/u', $r[2])) $ev['text'][] = [$r[0], $r[1], $r[2]];
    }
    foreach ((array)($result['left'] ?? []) as $why => $n) if (preg_match('/^report_[a-z_]+$/', (string)$why) && (int)$n > 0) $ev['left'][(string)$why] = (int)$n;
    return $ev;
}

function foreverchanges_import(): array
{
    if ($e = source_check()) return $e;
    $pack = foreverchanges_pack();
    if (!is_file($pack)) return ['ok' => false, 'message' => t('No ForeverChanges pack yet: make one with tools/foreverchanges_pack.py and send the .fcpack file here.', 'Pas encore de paquet ForeverChanges : créez-en un avec tools/foreverchanges_pack.py et envoyez le fichier .fcpack ici.')];
    $out = dirname($pack) . '/evidence.json';
    @unlink($out);
    $python = (string)config('tools', 'python', PHP_OS_FAMILY === 'Windows' ? 'python' : 'python3');
    $command = escapeshellarg($python) . ' -X utf8 ' . escapeshellarg(FT_ROOT . '/tools/tracker.py') . ' reports --pack ' . escapeshellarg($pack) . ' --out ' . escapeshellarg($out) . ' 2>&1';
    $lines = []; $code = 1;
    if (function_exists('exec')) @exec($command, $lines, $code);
    $result = $code === 0 && is_file($out) ? json_decode((string)file_get_contents($out), true) : null;
    @unlink($out);
    if (!is_array($result)) {
        error_log('Forever Tracker: the ForeverChanges pack could not be read: ' . mb_substr(implode(' | ', array_slice($lines, -3)), 0, 400));
        return ['ok' => false, 'message' => t('The ForeverChanges pack could not be read (see the PHP error log). Is it a .fcpack file made by tools/foreverchanges_pack.py?', 'Le paquet ForeverChanges n’a pas pu être lu (voir le journal d’erreurs PHP). Est-ce un fichier .fcpack créé par tools/foreverchanges_pack.py ?')];
    }
    $retrieved = preg_match('/^\d{4}-\d{2}-\d{2}$/', (string)($result['retrieved'] ?? '')) ? (string)$result['retrieved'] : date('Y-m-d', (int)filemtime($pack));
    $label = 'ForeverChanges ' . $retrieved;
    [$tables, $left] = source_tables(foreverchanges_evidence($result), $label, source_gaps());
    // where its maps show NPCs, rares and books nobody spawned here: kept for the locator, which prefers a reported
    // place to a looked-up one (the Spawns page, after the next "Locate")
    $places = foreverchanges_places($result);
    if ($places) collector_positions($places);
    $card = source_card('foreverchanges', $label, 'foreverchanges@' . $retrieved, $tables, $left);
    if ($places) {
        $card['places'] = count($places);
        $card['message'] = trim(($card['message'] ?? '') . ' ' . sprintf(t('%d creature(s) or object(s) nobody spawned now have a reported place: run the locator (Spawns) to use them.', '%d créature(s) ou objet(s) que personne n’a placés ont maintenant un lieu signalé : lancez le localisateur (Placements) pour les utiliser.'), count($places)));
        $card['ok'] = true;   // the places are kept even when the card has nothing new
    }
    return $card;
}

/** The places tools/tracker.py found for things nobody spawned, checked: [['npc'|'go', entry, name, [['m' => map,
 *  'x' => x, 'y' => y], …]], …] as collector_positions() takes them. Anything of another shape is dropped. */
function foreverchanges_places(array $result): array
{
    $out = [];
    foreach ((array)($result['places'] ?? []) as $row) {
        if (!is_array($row) || count($row) !== 4 || !in_array($row[0], ['npc', 'go'], true) || !is_int($row[1]) || $row[1] <= 0 || !is_array($row[3])) continue;
        $points = [];
        foreach (array_slice($row[3], 0, 20) as $p) {
            if (!is_array($p) || !isset($p['m'], $p['x'], $p['y']) || !is_int($p['m']) || $p['m'] < 0 || !is_numeric($p['x']) || !is_numeric($p['y'])) continue;
            if (abs((float)$p['x']) > 20000 || abs((float)$p['y']) > 20000) continue;
            $points[] = ['m' => $p['m'], 'x' => round((float)$p['x'], 1), 'y' => round((float)$p['y'], 1)];
        }
        if ($points) $out[] = [$row[0], $row[1], mb_substr(trim(preg_replace('/[\x00-\x1f]+/', ' ', (string)$row[2])), 0, 190), $points];
    }
    return $out;
}

// ------------------------------------------------------------------ EG Link (CC BY 4.0)
// github.com/JIVESCORP/eg-link-output-wowf: what EG Link players' addons recorded on live WoW Forever, per client build:
// vendor windows, loot (chance per kill, with kill counts), trainer lists, who offers and takes each quest.
const EGLINK_REPO = 'JIVESCORP/eg-link-output-wowf';
const EGLINK_FILES = ['vendors', 'loot', 'trainers', 'npcs'];
const EGLINK_MIN_KILLS = 10;   // a creature's drops count from this many looked corpses

function eglink_import(): array
{
    if ($e = source_check()) return $e;
    $r = eglink_evidence();
    if (empty($r['ev'])) return $r;
    $label = 'EG Link ' . substr($r['commit'], 0, 8);
    [$tables, $left] = source_tables($r['ev'], $label, source_gaps());
    [$changes, $moved] = source_refresh($r['ev'], 'eglink');
    // the quests the server already has, read again from the newest recording of the live game
    [$questChanges, $questLeft] = source_quest_refresh($r['commit']);
    return source_card('eglink', $label, 'eglink@' . $r['commit'], $tables, $left + $moved + $questLeft, array_merge($changes, $questChanges));
}

/** What EG Link recorded: ['ev' => evidence, 'commit' => sha], or ['ok' => false, 'message']. */
function eglink_evidence(): array
{
    [$status, $body] = source_http('https://api.github.com/repos/' . EGLINK_REPO . '/commits/main');
    $commit = $status === 200 ? (string)(json_decode($body, true)['sha'] ?? '') : '';
    if (!preg_match('/^[0-9a-f]{40}$/', $commit)) return ['ok' => false, 'message' => t('Could not reach EG Link on GitHub.', 'EG Link est injoignable sur GitHub.')];
    [$status, $body] = source_http('https://api.github.com/repos/' . EGLINK_REPO . "/contents/data/wowf?ref=$commit");
    $builds = $status === 200 ? array_values(array_filter(array_column(json_decode($body, true) ?: [], 'name'), fn($n) => preg_match('/^\d+\.\d+\.\d+\.\d+$/', $n))) : [];
    if (!$builds) return ['ok' => false, 'message' => t('EG Link lists no WoW Forever build.', 'EG Link ne liste aucun build de WoW Forever.')];
    usort($builds, 'version_compare');
    $dir = FT_ROOT . "/data/eglink/$commit";
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => []];
    foreach ($builds as $b) {
        foreach (EGLINK_FILES as $f) {
            $path = "$dir/$b/$f.json";
            $d = is_file($path) ? json_decode((string)file_get_contents($path), true) : null;
            if (!is_array($d)) {
                // not downloaded yet, or kept cut short by an older version, which then read it as an empty list
                if (is_file($path)) { error_log("Forever Tracker: EG Link $b/$f.json is no JSON: downloaded again"); @unlink($path); }
                [$status, $body, $length] = source_http('https://raw.githubusercontent.com/' . EGLINK_REPO . "/$commit/data/wowf/$b/$f.json", 120);
                if ($status === 404) continue;
                $d = $status === 200 ? json_decode($body, true) : null;
                $problem = $status !== 200 ? ($status ? "HTTP $status" : t('no answer', 'pas de réponse')) : source_keep($path, $body, $length, fn() => is_array($d));
                if ($problem !== '') return ['ok' => false, 'message' => sprintf(t('Could not download EG Link %s/%s (%s).', 'Impossible de télécharger EG Link %s/%s (%s).'), $b, $f, $problem)];
            }
            if ($f === 'vendors') foreach ($d['vendors'] ?? $d as $npc => $v) {
                foreach ((array)($v['entries'] ?? []) as $e) {
                    if (empty($e['itemId']) || !empty($e['costItems'])) continue;   // paid with items or currencies: no cost to give it
                    $ev['sell'][] = [(int)$npc, (int)$e['itemId'], !empty($e['limited']) ? (int)($e['stockMax'] ?? 0) : 0];
                }
            }
            if ($f === 'loot') {
                $kills = $d['kills'] ?? [];
                foreach ((array)($d['sources'] ?? []) as $key => $s) {
                    if (preg_match('/^npc:(\d+)$/', $key, $m)) {
                        $k = $kills[$key] ?? [];
                        if ((int)($k['deaths'] ?? 0) - (int)($k['unknown'] ?? 0) < EGLINK_MIN_KILLS) continue;
                        [$kind, $id] = ['npc', (int)$m[1]];
                    } elseif (preg_match('/^object:(\d+)\|spell:\d+$/', $key, $m)) {
                        if ((int)($s['windows'] ?? 0) < EGLINK_MIN_KILLS) continue;
                        [$kind, $id] = ['go', (int)$m[1]];
                    } else continue;   // skinning, pick pocketing, quest-tied, group, talent-boosted, containers
                    foreach ((array)($s['items'] ?? []) as $item => $i) {
                        if (!empty($i['quest'])) continue;
                        $ev['drop'][] = [$kind, $id, (int)$item, 100 * (float)($i['chance'] ?? 0)];
                    }
                }
            }
            if ($f === 'trainers') foreach ($d['trainers'] ?? $d as $npc => $tr) {
                foreach ((array)($tr['services'] ?? []) as $spell => $s) {
                    if (empty($s['spellId'])) continue;
                    $cost = max(array_map('intval', array_values((array)($s['costs'] ?? [])) ?: [0]));
                    $rankNo = preg_match('/(\d+)/', (string)($s['rankText'] ?? ''), $m) ? (int)$m[1] : 0;
                    $line = 0;
                    if (!empty($s['profession']) || !empty($s['skill']) || (int)($tr['trainerType'] ?? 0) === 2) {
                        // a profession (or a recipe): its skill line and rank, never a class spell without a requirement
                        $line = source_skill_line((string)($s['skill'] ?? ''), (string)($s['name'] ?? ''));
                        if (!$line) { $ev['left']['trainer_skill_unknown'] = ($ev['left']['trainer_skill_unknown'] ?? 0) + 1; continue; }
                    }
                    $ev['train'][] = [(int)$npc, (int)$s['spellId'], $cost, (int)($s['level'] ?? 0), $line, (int)($s['skillRank'] ?? 0), $line ? [] : null, $rankNo];
                }
            }
            if ($f === 'npcs') foreach (['npcs' => 'npc', 'objects' => 'go'] as $list => $kind) {
                foreach ((array)($d[$list] ?? []) as $id => $n) {
                    foreach (array_keys((array)($n['offers'] ?? [])) as $q) $ev['start'][] = [$kind, (int)$id, (int)$q];
                    foreach (array_keys((array)($n['takes'] ?? [])) as $q) $ev['end'][] = [$kind, (int)$id, (int)$q];
                }
            }
        }
    }
    return ['ev' => $ev, 'commit' => $commit];
}

// ------------------------------------------------------------------ ForeverDB.net (GPL-3.0, attribution)
// foreverdb.net's addon data: vendor stock (only vendors its players saw on Forever), boss loot measured on Forever,
// quest givers and enders its players' Companion addons recorded.
const FOREVERDB = 'https://foreverdb.net/';
const FOREVERDB_FILES = ['Data/NPCs.lua', 'Data/Loot.lua', 'Data/QuestForever.lua'];

function foreverdb_import(): array
{
    if ($e = source_check()) return $e;
    $r = foreverdb_evidence();
    if (empty($r['ev'])) return $r;
    $label = 'ForeverDB.net ' . $r['version'];
    [$tables, $left] = source_tables($r['ev'], $label, source_gaps());
    [$changes, $moved] = source_refresh($r['ev'], 'foreverdb');
    return source_card('foreverdb', $label, 'foreverdb@' . $r['version'], $tables, $left + $moved, $changes);
}

/** What ForeverDB.net's players saw on Forever: ['ev' => evidence, 'version'], or ['ok' => false, 'message']. */
function foreverdb_evidence(): array
{
    [$status, $body] = source_http(FOREVERDB . 'downloads/addon-manifest.json');
    $listing = $status === 200 ? json_decode($body, true) : null;
    $version = (string)($listing['data']['version'] ?? '');
    if (!$listing || !preg_match('/^[\w.\-]+$/', $version)) return ['ok' => false, 'message' => t('Could not reach ForeverDB.net.', 'ForeverDB.net est injoignable.')];
    $dir = FT_ROOT . "/data/foreverdb/$version";
    $text = [];
    foreach ($listing['data']['files'] as $f) {
        if (!in_array($f['path'], FOREVERDB_FILES, true)) continue;
        $path = "$dir/" . basename($f['path']);
        if (!is_file($path) || hash_file('sha256', $path) !== $f['sha256']) {
            [$status, $body] = source_http(FOREVERDB . $f['url'], 120);
            // its checksum says the file is whole; source_keep() writes it beside itself and renames it
            if ($status !== 200 || hash('sha256', $body) !== $f['sha256'] || source_keep($path, $body) !== '') return ['ok' => false, 'message' => sprintf(t('ForeverDB.net %s did not download cleanly.', 'ForeverDB.net %s ne s’est pas téléchargé correctement.'), $f['path'])];
        }
        $text[basename($f['path'], '.lua')] = (string)file_get_contents($path);
    }
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => []];
    // vendors: [npc] = {name, title, map, x, y, side, seen in Forever}; [item] = {npc, copper, stack, limited, ...}
    $npcs = source_lua_assignments($text['NPCs'] ?? '', ['npcs', 'sold']);
    foreach ((array)($npcs['sold'] ?? []) as $item => $list) {
        $list = array_values((array)$list);
        for ($i = 0; $i + 3 < count($list); $i += 4) {
            $npc = (int)$list[$i];
            if ((int)(array_values((array)($npcs['npcs'][$npc] ?? []))[6] ?? 0) !== 1) continue;   // Classic stock, not seen on Forever
            $ev['sell'][] = [$npc, (int)$item, (int)$list[$i + 3] > 0 ? (int)$list[$i + 3] : 0];
        }
    }
    // boss loot: "item:pct:src[:h[:kills[:seen]]]", src f = seen in Forever, c = Classic data
    $loot = source_lua_assignments($text['Loot'] ?? '', ['lootDB']);
    foreach ((array)($loot['lootDB']['inst'] ?? []) as $inst) foreach ((array)($inst['bosses'] ?? []) as $boss) {
        if (!is_numeric($boss['npc'] ?? null)) continue;
        foreach (explode(';', (string)($boss['loot'] ?? '')) as $part) {
            $f = explode(':', $part);
            if (count($f) >= 3 && ctype_digit($f[0]) && $f[2] === 'f') $ev['drop'][] = ['npc', (int)$boss['npc'], (int)$f[0], (float)$f[1]];
        }
    }
    // quests: "title|level|min level|objective|starts|ends|players who saw it|..."; starts/ends n<creature> / o<object>
    $quests = source_lua_assignments($text['QuestForever'] ?? '', ['qfQuests']);
    foreach ((array)($quests['qfQuests'] ?? []) as $quest => $line) {
        $f = explode('|', (string)$line);
        if ((int)($f[6] ?? 0) < 1) continue;   // no player saw it
        foreach ([4 => 'start', 5 => 'end'] as $at => $role) {
            preg_match_all('/([no])(\d+)/', (string)($f[$at] ?? ''), $m, PREG_SET_ORDER);
            foreach ($m as [, $k, $id]) $ev[$role][] = [$k === 'n' ? 'npc' : 'go', (int)$id, (int)$quest];
        }
    }
    return ['ev' => $ev, 'version' => $version];
}

// ------------------------------------------------------------------ background runs (long imports)
function source_log(string $source): string { return FT_ROOT . "/data/source-$source.log"; }
function source_lock_file(string $source): string { return FT_ROOT . "/data/source-$source.running"; }
/** Left by an Icy Veins run while it is in flight (tools/source-import.php): still there after a restart, the
 *  container goes on with the run (docker/entrypoint.sh). */
function source_resume_file(string $source): string { return FT_ROOT . "/data/source-$source.resume"; }

/**
 * The lock of a source's import: an exclusive flock on data/source-<source>.running, kept for as long as the run
 * lasts. The system lets it go when the process ends, however it ends (a restart, a crash), so no lock is ever left
 * behind, and two starts at the same moment cannot both get it: a file that only "exists" was checked by the website
 * and created later by the run, and two clicks gave two runs. The file itself stays in place (removing a lock file
 * another process is opening is how two runs come to hold "the" lock). Returns the open file to keep, null when
 * another run holds it, false when the file cannot be opened at all (the data folder is not writable); $tries > 1
 * asks again every 0.2 s (source_running() holds the lock for an instant to ask).
 */
function source_lock(string $source, int $tries = 1, ?string $path = null)
{
    $path ??= source_lock_file($source);
    // "e": closed in any program this one starts, which would otherwise carry the lock on after the run. A file made
    // by another user (a run started as root in the container) is opened for reading: that is enough to lock it.
    $new = !is_file($path);
    $handle = @fopen($path, 'ce') ?: @fopen($path, 're');
    if (!$handle) return false;
    if ($new) @chmod($path, 0666);
    for ($i = 1; ; $i++) {
        if (flock($handle, LOCK_EX | LOCK_NB)) return $handle;
        if ($i >= $tries) break;
        usleep(200000);
    }
    fclose($handle);
    return null;
}

function source_unlock($handle): void
{
    if (!is_resource($handle)) return;
    flock($handle, LOCK_UN);
    fclose($handle);
}

/** A run of this source holds its lock right now. */
function source_running(string $source, ?string $path = null): bool
{
    $path ??= source_lock_file($source);
    if (!is_file($path)) return false;
    $handle = source_lock($source, 1, $path);
    if ($handle === null) return true;
    source_unlock($handle);
    return false;
}

/** Starts tools/source-import.php <source> in the background (Icy Veins takes hours the first time). */
function source_start(string $source): array
{
    // two clicks at once: the second one waits at this gate until the first one's run holds its lock, then sees it
    $gate = @fopen(FT_ROOT . "/data/source-$source.start", 'ce');   // "e": the run started below must not inherit the gate
    if ($gate) flock($gate, LOCK_EX);
    try {
        if (source_running($source)) return ['ok' => false, 'message' => t('Already running.', 'Déjà en cours.')];
        $php = (string)config('tools', 'php', PHP_BINARY ?: 'php');
        // --log: the run writes its own log once it holds the lock, so a start that loses the race never empties the log of the run that won
        exec('(' . escapeshellarg($php) . ' ' . escapeshellarg(FT_ROOT . '/tools/source-import.php') . ' ' . escapeshellarg($source) . ' --log) > /dev/null 2>&1 &');
        for ($i = 0; $i < 30 && !source_running($source); $i++) usleep(100000);   // PHP starts and takes the lock: well under a second
    } finally {
        if ($gate) { flock($gate, LOCK_UN); fclose($gate); }
    }
    return ['ok' => true, 'message' => sprintf(t('%s started in the background; its import card appears below when it is done (reload the page).', '%s a démarré en arrière-plan ; sa carte d’import apparaît ci-dessous une fois terminé (rechargez la page).'), SOURCES[$source][0] ?? $source)];
}

// Icy Veins: a mirror of its whole WoW Forever database, and the cards made from it
require_once __DIR__ . '/icyveins.php';
