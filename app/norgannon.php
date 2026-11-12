<?php
// NorgannonDB (https://github.com/zmarotrix/NorgannonDB, GPL-3.0): an open, crowd-sourced WoW Forever database built
// from QuestieDB, pfQuest, WoW Forever's own tables and what players saw with the NorgannonDB Collector. It is read
// at run time from a pinned commit (never bundled here) and turned into an import like any other (preview, apply what
// is missing, history, rollback), aimed at the gaps the analysis found:
//
//   loot and vendor rows       only for items players cannot get and that are not internal (Wowhead's verdict included)
//   quest givers and enders    only for quests the server has no giver (or no ender) for
//   trainer_spell rows         spells NorgannonDB players saw a trainer teach (class training, profession recipes),
//                              at the trainers the server has for those creatures, with their level (NorgannonDB's, the
//                              server's other trainers', or Wowhead's "Requires level N"), price and the ranks they need first
//
// See docs/NORGANNONDB.md.
require_once FT_APP . '/imports.php';
require_once FT_APP . '/collector.php';
require_once FT_APP . '/wowhead.php';

const NORGANNON_REPO = 'zmarotrix/NorgannonDB';
const NORGANNON_PIN = 'a2a5bcf1031019093a3ad8a355ddab63cb630c65';   // 2026-11-12, schema 1.5 (training), data 1.4.8
const NORGANNON_FILES = ['items', 'quests', 'recipes'];

function norgannon_commit(): string
{
    $c = trim((string)config('norgannondb', 'commit', ''));
    return preg_match('/^[0-9a-f]{40}$/', $c) ? $c : NORGANNON_PIN;
}

/** The pinned data files, downloaded once into data/norgannondb/<commit>/. Returns the folder, or an error string. */
function norgannon_fetch(string $commit): array
{
    $dir = FT_ROOT . "/data/norgannondb/$commit";
    @mkdir($dir, 0775, true);
    foreach (NORGANNON_FILES as $name) {
        $path = "$dir/$name.lua";
        if (is_file($path) && filesize($path) > 1000) continue;
        $url = 'https://raw.githubusercontent.com/' . NORGANNON_REPO . "/$commit/data/$name.lua";
        $body = @file_get_contents($url, false, stream_context_create(['http' => ['timeout' => 120, 'header' => "User-Agent: ForeverTracker\r\n"]]));
        if ($body === false || strlen($body) < 1000) return [null, sprintf(t('Could not download %s.', 'Impossible de télécharger %s.'), $url)];
        file_put_contents($path, $body);
    }
    return [$dir, ''];
}

/** id => fields of a packed data file (R(id, "name", [[fields]]) lines; see NorgannonDB's SPEC.md). */
function norgannon_records(string $path, ?array $only = null): array
{
    $out = [];
    $handle = fopen($path, 'r');
    while (($line = fgets($handle)) !== false) {
        if (!preg_match('/^R\((\d+),"((?:[^"\\\\]|\\\\.)*)"(?:,\[\[(.*)\]\])?\)\s*$/', $line, $m)) continue;
        $id = (int)$m[1];
        if ($only !== null && !isset($only[$id])) continue;
        $fields = isset($m[3]) && $m[3] !== '' ? collector_lua('{' . $m[3] . '}') : [];
        $fields['name'] = stripcslashes($m[2]);
        $out[$id] = $fields;
    }
    fclose($handle);
    return $out;
}

/** One `NorgannonDB.<table> = {...}` literal of a data file (recipes.lua holds recipes and training). */
function norgannon_table(string $path, string $table): array
{
    $text = (string)file_get_contents($path);
    $at = strpos($text, "NorgannonDB.$table = ");
    if ($at === false) return [];
    $end = strpos($text, '} end f() end', $at);
    return collector_lua(substr($text, $at + strlen("NorgannonDB.$table = "), $end === false ? null : $end - $at - strlen("NorgannonDB.$table = ") + 1));
}

/** [tables (import_file's shape), left-out counts] from the pinned data, aimed at the analysis' gaps. */
function norgannon_tables(string $dir): array
{
    $left = ['loot_chance_unknown' => 0, 'loot_known' => 0, 'loot_unknown_creature' => 0, 'object_no_loot' => 0, 'vendor_unknown' => 0,
             'quest_unknown' => 0, 'quest_hidden' => 0, 'trainer_not_on_server' => 0, 'trainer_level_unknown' => 0, 'trainer_known' => 0];
    $rows = [];
    $build = (int)(meta()['client_build'] ?? 0);
    $ids = function (string $sql, string $database = 'tracker'): array { $out = []; foreach (rows($sql, [], $database) as $r) $out[(int)reset($r)] = true; return $out; };

    // ---- the gaps: items players cannot get (internal ones left out), quests without giver / ender
    $wanted = $ids("SELECT id FROM ft_entities WHERE type = 'item' AND internal = 0 AND status <> 'ok'");
    $noGiver = $ids('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_queststarter s WHERE s.quest = q.ID) AND NOT EXISTS (SELECT 1 FROM gameobject_queststarter g WHERE g.quest = q.ID)', 'world');
    $noEnder = $ids('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_questender s WHERE s.quest = q.ID) AND NOT EXISTS (SELECT 1 FROM gameobject_questender g WHERE g.quest = q.ID)', 'world');

    // ---- items: where the wanted ones come from
    $items = norgannon_records("$dir/items.lua", $wanted);
    $npcDrops = []; $goDrops = []; $sells = [];
    foreach ($items as $item => $r) {
        foreach ((array)($r['drops']['npcs'] ?? []) as $npc => $chance) $npcDrops[(int)$npc][$item] = (float)$chance;
        foreach ((array)($r['drops']['objects'] ?? []) as $go => $chance) $goDrops[(int)$go][$item] = (float)$chance;
        foreach ((array)($r['vendors'] ?? []) as $npc => $count) $sells[(int)$npc][$item] = (int)$count;
    }

    // vendors: as listed (a count is a limited stock, restocked hourly); the price is the item's own unless another
    // vendor of this server sells it for items or currencies (then that ExtendedCost)
    $creatures = $ids('SELECT entry FROM creature_template WHERE entry IN (' . (implode(',', array_keys($sells + $npcDrops)) ?: '0') . ')', 'world');
    $costs = [];
    if ($wanted) foreach (rows('SELECT item, MIN(ExtendedCost) c FROM npc_vendor WHERE ExtendedCost > 0 AND item IN (' . implode(',', array_keys($items) ?: [0]) . ') GROUP BY item', [], 'world') as $r) $costs[(int)$r['item']] = (int)$r['c'];
    foreach ($sells as $npc => $list) {
        if (!isset($creatures[$npc])) { $left['vendor_unknown'] += count($list); continue; }
        foreach ($list as $item => $count) {
            $rows['npc_vendor'][] = ['entry' => $npc, 'slot' => 0, 'item' => $item, 'maxcount' => max(0, $count), 'incrtime' => $count > 0 ? 3600 : 0,
                'ExtendedCost' => $costs[$item] ?? 0, 'type' => 1, 'VerifiedBuild' => $build];
        }
    }

    // loot: into the creature's own loot table (LootID, filled where 0) or the chest's (Data1), at NorgannonDB's chance
    $lootIds = [];
    foreach (array_chunk(array_keys($npcDrops), 1000) as $chunk) {
        foreach (rows('SELECT Entry, LootID FROM creature_template_difficulty WHERE DifficultyID = 0 AND Entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $lootIds[(int)$r['Entry']] = (int)$r['LootID'];
    }
    $chests = [];
    foreach (array_chunk(array_keys($goDrops), 1000) as $chunk) {
        foreach (rows('SELECT entry, type, Data1 FROM gameobject_template WHERE entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $chests[(int)$r['entry']] = in_array((int)$r['type'], [3, 25], true) ? (int)$r['Data1'] : 0;
    }
    $questItems = $ids('SELECT DISTINCT ObjectID FROM quest_objectives WHERE Type = 1', 'world');
    $gives = ['creature_loot_template' => collector_loot_items('creature_loot_template', array_map(fn($e, $l) => $l ?: $e, array_keys($lootIds), $lootIds)),
              'gameobject_loot_template' => collector_loot_items('gameobject_loot_template', array_values(array_filter($chests)))];
    foreach (['npc' => $npcDrops, 'go' => $goDrops] as $kind => $sources) {
        foreach ($sources as $id => $list) {
            if ($kind === 'npc') {
                if (!array_key_exists($id, $lootIds)) { $left['loot_unknown_creature'] += count($list); continue; }
                [$table, $entry] = ['creature_loot_template', $lootIds[$id] ?: $id];
            } else {
                if (empty($chests[$id])) { $left['object_no_loot'] += count($list); continue; }
                [$table, $entry] = ['gameobject_loot_template', $chests[$id]];
            }
            foreach ($list as $item => $chance) {
                if ($chance <= 0) { $left['loot_chance_unknown']++; continue; }   // 0 = drops, chance unknown: nothing safe to write
                if (isset($gives[$table][$entry][$item])) { $left['loot_known']++; continue; }
                $rows[$table][] = ['Entry' => $entry, 'ItemType' => 0, 'Item' => $item, 'Chance' => round(min(100, $chance), 2), 'QuestRequired' => isset($questItems[$item]) ? 1 : 0,
                    'LootMode' => 1, 'GroupId' => 0, 'MinCount' => 1, 'MaxCount' => 1, 'Comment' => 'NorgannonDB ' . substr(norgannon_commit(), 0, 8)];
            }
        }
    }

    // ---- quest givers and enders, for the quests that have none
    $quests = norgannon_records("$dir/quests.lua", $noGiver + $noEnder);
    $by = ['npc' => [], 'go' => []];
    foreach ($quests as $r) foreach (['starters', 'finishers'] as $role) { foreach ((array)($r[$role]['npcs'] ?? []) as $n) $by['npc'][] = (int)$n; foreach ((array)($r[$role]['objects'] ?? []) as $o) $by['go'][] = (int)$o; }
    $templates = ['npc' => $ids('SELECT entry FROM creature_template WHERE entry IN (' . (implode(',', array_unique($by['npc'])) ?: '0') . ')', 'world'),
                  'go' => $ids('SELECT entry FROM gameobject_template WHERE entry IN (' . (implode(',', array_unique($by['go'])) ?: '0') . ')', 'world')];
    foreach ($quests as $quest => $r) {
        if (!empty($r['hidden']) && $r['hidden'] === true) { $left['quest_hidden']++; continue; }
        foreach (['starters' => ['queststarter', $noGiver], 'finishers' => ['questender', $noEnder]] as $role => [$suffix, $gap]) {
            if (!isset($gap[$quest])) continue;
            foreach (['npcs' => 'npc', 'objects' => 'go'] as $list => $kind) {
                foreach ((array)($r[$role][$list] ?? []) as $who) {
                    if (!isset($templates[$kind][(int)$who])) { $left['quest_unknown']++; continue; }
                    $rows[($kind === 'npc' ? 'creature_' : 'gameobject_') . $suffix][] = ['id' => (int)$who, 'quest' => $quest, 'VerifiedBuild' => $build];
                }
            }
        }
    }

    // ---- trainers: what players saw them teach
    $recipes = norgannon_table("$dir/recipes.lua", 'recipes');
    $training = norgannon_table("$dir/recipes.lua", 'training');
    $teach = [];   // npc => [spell => [cost, level, skill line, skill rank, needs]]
    foreach ($training as $class => $spells) foreach ((array)$spells as $spell => $s) {
        foreach ((array)($s['trainers'] ?? []) as $npc) $teach[(int)$npc][(int)$spell] = [(int)($s['cost'] ?? 0), (int)($s['level'] ?? 0), 0, 0, array_slice(array_map('intval', (array)($s['needs'] ?? [])), 0, 3)];
    }
    foreach ($recipes as $spell => $r) {
        foreach ((array)($r['trainers'] ?? []) as $npc => $cost) $teach[(int)$npc][(int)$spell] = [(int)$cost, 0, (int)($r['skill'] ?? 0), (int)($r['learn'] ?? 0), []];
    }
    $trainerOf = [];
    foreach (array_chunk(array_keys($teach), 1000) as $chunk) {
        foreach (rows('SELECT CreatureID, TrainerID FROM creature_trainer WHERE CreatureID IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $trainerOf[(int)$r['CreatureID']][] = (int)$r['TrainerID'];
    }
    $taught = []; $levels = [];
    foreach (rows('SELECT TrainerId, SpellId, ReqLevel FROM trainer_spell', [], 'world') as $r) {
        $taught[(int)$r['TrainerId'] . ':' . (int)$r['SpellId']] = true;
        if ((int)$r['ReqLevel'] > 0) $levels[(int)$r['SpellId']] = (int)$r['ReqLevel'];
    }
    $seen = [];
    foreach ($teach as $npc => $spells) {
        if (empty($trainerOf[$npc])) { $left['trainer_not_on_server'] += count($spells); continue; }
        foreach ($trainerOf[$npc] as $trainer) foreach ($spells as $spell => [$cost, $level, $line, $rank, $needs]) {
            if (isset($seen["$trainer:$spell"])) continue;
            $seen["$trainer:$spell"] = true;
            if (isset($taught["$trainer:$spell"])) { $left['trainer_known']++; continue; }
            // a class spell's level: NorgannonDB's, else what other trainers of this server ask for it, else Wowhead's
            // "Requires level N"; never 0 (anyone could learn it)
            if (!$line) { $level = $level ?: ($levels[$spell] ?? 0) ?: ($levels[$spell] = wowhead_spell_level($spell)); if (!$level) { $left['trainer_level_unknown']++; continue; } }
            $rows['trainer_spell'][] = ['TrainerId' => $trainer, 'SpellId' => $spell, 'MoneyCost' => $cost, 'ReqSkillLine' => $line, 'ReqSkillRank' => $rank,
                'ReqAbility1' => $needs[0] ?? 0, 'ReqAbility2' => $needs[1] ?? 0, 'ReqAbility3' => $needs[2] ?? 0, 'ReqLevel' => $level, 'VerifiedBuild' => $build];
        }
    }

    $tables = [];
    foreach ($rows as $table => $records) {
        if (!$records || !table_exists($table, 'world')) continue;
        $columns = import_columns('world', $table);
        $use = array_values(array_intersect(array_keys($records[0]), $columns));
        $tables[$table] = ['db' => 'world', 'columns' => $use, 'groups' => [['columns' => $use, 'rows' => array_map(fn($r) => array_map(fn($c) => $r[$c], $use), $records)]]];
    }
    return [$tables, array_filter($left)];
}

/** Imports the pinned NorgannonDB as an import card (see import_file); returns what import_file returns. */
function norgannon_import(): array
{
    import_schema();
    if (!table_exists('ft_entities')) return ['ok' => false, 'message' => t('Run the analysis first: the import aims at its gaps.', 'Lancez d’abord l’analyse : l’import vise ses manques.')];
    $commit = norgannon_commit();
    [$dir, $error] = norgannon_fetch($commit);
    if (!$dir) return ['ok' => false, 'message' => $error];
    @ini_set('memory_limit', '2048M');
    [$tables, $left] = norgannon_tables($dir);
    if (!$tables) return ['ok' => false, 'id' => 0, 'counts' => [], 'ignored' => $left, 'message' => t('NorgannonDB has nothing this server lacks.', 'NorgannonDB n’a rien qui manque à ce serveur.')];
    $counts = []; foreach ($tables as $table => $entry) $counts[$table] = count($entry['groups'][0]['rows']);
    $name = 'NorgannonDB ' . substr($commit, 0, 8);
    rows('INSERT INTO ft_imports (name, file, admin, counts, ignored) VALUES (?, ?, ?, ?, ?)', [$name, 'norgannondb@' . $commit, (string)(admin()['name'] ?? 'cli'), json_encode($counts), json_encode($left)]);
    $id = (int)db()->insert_id;
    @mkdir(import_dir() . '/parsed', 0775, true);
    file_put_contents(import_dir() . "/parsed/$id.json", json_encode(['tables' => $tables], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE));
    import_index($id, $tables);
    return ['ok' => true, 'id' => $id, 'counts' => $counts, 'ignored' => $left, 'bad' => 0, 'statements' => 0,
            'message' => sprintf(t('%s: %s rows for what the server lacks.', '%s : %s lignes pour ce qui manque au serveur.'), $name, number(array_sum($counts)))];
}
