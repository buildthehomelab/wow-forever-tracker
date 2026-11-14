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
// Sources: NorgannonDB (app/norgannon.php), AtlasLoot (app/atlasloot.php), EG Link, ForeverDB.net, Icy Veins (below).
// See docs/SOURCES.md.
require_once FT_APP . '/imports.php';
require_once FT_APP . '/collector.php';
require_once FT_APP . '/wowhead.php';

/** Profession names as trainers show them, to skill lines. */
const SOURCE_SKILLS = ['Alchemy' => 171, 'Blacksmithing' => 164, 'Enchanting' => 333, 'Engineering' => 202, 'Herbalism' => 182,
    'Leatherworking' => 165, 'Mining' => 186, 'Skinning' => 393, 'Tailoring' => 197, 'Cooking' => 185, 'First Aid' => 129,
    'Fishing' => 356, 'Jewelcrafting' => 755, 'Inscription' => 773, 'Lockpicking' => 633, 'Poisons' => 40, 'Riding' => 762];

const SOURCES = [
    'norgannondb' => ['NorgannonDB', 'GPL-3.0 (with QuestieDB, pfQuest, DungeonJournal)'],
    'eglink' => ['EG Link', 'CC BY 4.0: "Data from Efficient Games (https://efficient.games), licensed under CC BY 4.0."'],
    'foreverdb' => ['ForeverDB.net', 'GPL-3.0 with attribution: "Data from ForeverDB.net"'],
    'icyveins' => ['Icy Veins', 'no licence stated: reference for your own server'],
    'atlasloot' => ['AtlasLoot Classic Forever', 'GPL-2.0 (CurseForge project 1422985)'],
];

/** The analysis' gaps: items players cannot get (not internal), official quests without giver / ender. */
function source_gaps(): array
{
    $ids = function (string $sql, string $database = 'tracker'): array { $out = []; foreach (rows($sql, [], $database) as $r) $out[(int)reset($r)] = true; return $out; };
    // a quest an item starts (the Ancient Petrified Leaf) has no giver on purpose: a source naming the creature that
    // drops the item, or the chest it lies in, as its giver would be wrong
    $byItem = array_fill_keys(array_map('intval', (array)(meta()['item_quests'] ?? [])), true);
    // the server's quest_template holds tens of thousands of quests WoW: Forever does not have (other versions of the
    // game): only the client's own quests are gaps worth a lookup
    $official = official_quests();
    return [
        'items' => $ids("SELECT id FROM ft_entities WHERE type = 'item' AND internal = 0 AND status <> 'ok'"),
        'noGiver' => array_intersect_key(array_diff_key($ids('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_queststarter s WHERE s.quest = q.ID) AND NOT EXISTS (SELECT 1 FROM gameobject_queststarter g WHERE g.quest = q.ID)', 'world'), $byItem), $official),
        'noEnder' => array_intersect_key($ids('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_questender s WHERE s.quest = q.ID) AND NOT EXISTS (SELECT 1 FROM gameobject_questender g WHERE g.quest = q.ID)', 'world'), $official),
    ];
}

/** Creature entries of the server's trainers. */
function source_trainer_npcs(): array
{
    return array_map('intval', array_column(rows('SELECT DISTINCT CreatureID FROM creature_trainer', [], 'world'), 'CreatureID'));
}

/** The evidence as import tables, with the server's rules (see the top of this file). Returns [tables, left out]. */
function source_tables(array $ev, string $label, array $gaps): array
{
    $left = ['vendor_unknown' => 0, 'loot_chance_unknown' => 0, 'loot_known' => 0, 'loot_unknown_creature' => 0, 'object_no_loot' => 0,
             'quest_unknown' => 0, 'trainer_not_on_server' => 0, 'trainer_level_unknown' => 0, 'trainer_previous_rank_unknown' => 0, 'trainer_known' => 0];
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

    // ---- loot
    $drops = ['npc' => [], 'go' => []];
    foreach ($ev['drop'] ?? [] as [$kind, $id, $item, $chance]) {
        if (!isset($gaps['items'][(int)$item])) continue;
        $old = $drops[$kind][(int)$id][(int)$item] ?? 0;
        $drops[$kind][(int)$id][(int)$item] = max($old, (float)$chance);   // a source seen in several builds: its best measure
    }
    $lootIds = [];
    foreach (array_chunk(array_keys($drops['npc']), 1000) as $chunk) {
        foreach (rows('SELECT Entry, LootID FROM creature_template_difficulty WHERE DifficultyID = 0 AND Entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $lootIds[(int)$r['Entry']] = (int)$r['LootID'];
    }
    $chests = [];
    foreach (array_chunk(array_keys($drops['go']), 1000) as $chunk) {
        foreach (rows('SELECT entry, type, Data1 FROM gameobject_template WHERE entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $chests[(int)$r['entry']] = in_array((int)$r['type'], [3, 25], true) ? (int)$r['Data1'] : 0;
    }
    $questItems = $ids('SELECT DISTINCT ObjectID FROM quest_objectives WHERE Type = 1');
    $gives = ['creature_loot_template' => collector_loot_items('creature_loot_template', array_map(fn($e, $l) => $l ?: $e, array_keys($lootIds), $lootIds)),
              'gameobject_loot_template' => collector_loot_items('gameobject_loot_template', array_values(array_filter($chests)))];
    foreach ($drops as $kind => $sources) {
        foreach ($sources as $id => $list) {
            if ($kind === 'npc') {
                if (!array_key_exists($id, $lootIds)) { $left['loot_unknown_creature'] += count($list); continue; }
                [$table, $entry] = ['creature_loot_template', $lootIds[$id] ?: $id];
            } else {
                if (empty($chests[$id])) { $left['object_no_loot'] += count($list); continue; }
                [$table, $entry] = ['gameobject_loot_template', $chests[$id]];
            }
            foreach ($list as $item => $chance) {
                if ($chance <= 0) { $left['loot_chance_unknown']++; continue; }
                if (isset($gives[$table][$entry][$item])) { $left['loot_known']++; continue; }
                $rows[$table][] = ['Entry' => $entry, 'ItemType' => 0, 'Item' => $item, 'Chance' => round(min(100, max(0.01, $chance)), 2), 'QuestRequired' => isset($questItems[$item]) ? 1 : 0,
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
            if (!$line) { $level = (int)$level ?: ($levels[$spell] ?? 0) ?: ($levels[$spell] = wowhead_spell_level($spell)); if (!$level) { $left['trainer_level_unknown']++; continue; } }
            if ($needs === null) {
                $needs = $needsOf[$spell] ?? null;
                if ($needs === null) { if ((int)$rankNo > 1) { $left['trainer_previous_rank_unknown']++; continue; } $needs = []; }
            }
            $rows['trainer_spell'][] = ['TrainerId' => $trainer, 'SpellId' => $spell, 'MoneyCost' => (int)$cost, 'ReqSkillLine' => (int)$line, 'ReqSkillRank' => (int)$rank,
                'ReqAbility1' => $needs[0] ?? 0, 'ReqAbility2' => $needs[1] ?? 0, 'ReqAbility3' => $needs[2] ?? 0, 'ReqLevel' => (int)$level, 'VerifiedBuild' => $build];
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

/** Saves tables as an import card (preview, apply, history, rollback, data repo export). */
function source_card(string $source, string $name, string $file, array $tables, array $left): array
{
    import_schema();
    if (!$tables) return ['ok' => false, 'id' => 0, 'counts' => [], 'ignored' => $left,
        'message' => sprintf(t('%s has nothing this server lacks.', '%s n’a rien qui manque à ce serveur.'), SOURCES[$source][0] ?? $source)];
    $counts = []; foreach ($tables as $table => $entry) $counts[$table] = count($entry['groups'][0]['rows']);
    $name .= ' · ' . (SOURCES[$source][1] ?? '');
    rows('INSERT INTO ft_imports (name, file, admin, counts, ignored) VALUES (?, ?, ?, ?, ?)', [$name, $file, (string)(admin()['name'] ?? 'cli'), json_encode($counts), json_encode($left)]);
    $id = (int)db()->insert_id;
    @mkdir(import_dir() . '/parsed', 0775, true);
    file_put_contents(import_dir() . "/parsed/$id.json", json_encode(['tables' => $tables], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE));
    import_index($id, $tables);
    return ['ok' => true, 'id' => $id, 'counts' => $counts, 'ignored' => $left, 'bad' => 0, 'statements' => 0,
            'message' => sprintf(t('%s: %s rows for what the server lacks.', '%s : %s lignes pour ce qui manque au serveur.'), $name, number(array_sum($counts)))];
}

/** GET with a user agent; [status, body]. */
function source_http(string $url, int $timeout = 60): array
{
    $context = stream_context_create(['http' => ['timeout' => $timeout, 'ignore_errors' => true,
        'header' => "User-Agent: ForeverTracker/1.1 (private server admin tool)\r\nAccept: application/json, */*\r\n"]]);
    $body = @file_get_contents($url, false, $context);
    $status = 0;
    foreach ($http_response_header ?? [] as $h) if (preg_match('#^HTTP/\S+ (\d+)#', $h, $m)) $status = (int)$m[1];
    return [$status, $body === false ? '' : $body];
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
    return source_card('eglink', $label, 'eglink@' . $r['commit'], $tables, $left);
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
            if (!is_file($path)) {
                [$status, $body] = source_http('https://raw.githubusercontent.com/' . EGLINK_REPO . "/$commit/data/wowf/$b/$f.json", 120);
                if ($status === 404) continue;
                if ($status !== 200) return ['ok' => false, 'message' => sprintf(t('Could not download EG Link %s/%s.', 'Impossible de télécharger EG Link %s/%s.'), $b, $f)];
                @mkdir(dirname($path), 0775, true);
                file_put_contents($path, $body);
            }
            $d = json_decode((string)file_get_contents($path), true) ?: [];
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
    return source_card('foreverdb', $label, 'foreverdb@' . $r['version'], $tables, $left);
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
            if ($status !== 200 || hash('sha256', $body) !== $f['sha256']) return ['ok' => false, 'message' => sprintf(t('ForeverDB.net %s did not download cleanly.', 'ForeverDB.net %s ne s’est pas téléchargé correctement.'), $f['path'])];
            @mkdir($dir, 0775, true);
            file_put_contents($path, $body);
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

// ------------------------------------------------------------------ Icy Veins (reference only)
// db.icy-veins.com/wow-forever: one answer per item, quest and NPC, with what players' addons recorded on live Forever.
// Asked only about the gaps: items players cannot get, quests without giver / ender, the server's trainers. Polite (two
// requests a second), cached in data/icyveins/, asked again after 14 days (7 for "not found"): it keeps growing.
const ICYVEINS = 'https://db.icy-veins.com/api/catalog/wowf/';

function icyveins_get(string $kind, int $id, int &$asked): ?array
{
    static $last = 0.0;
    $path = FT_ROOT . "/data/icyveins/$kind/$id.json";
    if (is_file($path)) {
        $data = json_decode((string)file_get_contents($path), true) ?: [];
        $age = time() - (int)($data['fetched'] ?? 0);
        if ($age < (empty($data['missing']) ? 14 : 7) * 86400) return $data;
    }
    if ($asked >= (int)(config('icyveins', 'max', 20000) ?: 20000)) return is_file($path) ? $data : null;
    $wait = 0.5 - (microtime(true) - $last);
    if ($wait > 0) usleep((int)($wait * 1e6));
    $last = microtime(true); $asked++;
    [$status, $body] = source_http(ICYVEINS . "$kind/$id", 30);
    if ($status === 404) $data = ['missing' => true];
    elseif ($status !== 200) return is_file($path) ? $data : null;
    else {
        $full = json_decode($body, true);
        $data = is_array($full) && !empty($full['entity']) ? ['relations' => $full['relations'] ?? []] : ['missing' => true];
    }
    $data['fetched'] = time();
    @mkdir(dirname($path), 0775, true);
    file_put_contents($path, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
    return $data;
}

/** Drops and vendors of the gap items Icy Veins already answered (its cache only: no lookup). */
function icyveins_cached_items(array $items): array
{
    $ev = ['sell' => [], 'drop' => []];
    foreach (array_keys($items) as $item) {
        $path = FT_ROOT . "/data/icyveins/item/$item.json";
        if (!is_file($path)) continue;
        icyveins_item_evidence($ev, $item, (array)((json_decode((string)file_get_contents($path), true) ?: [])['relations'] ?? []));
    }
    return $ev;
}

/** Givers and enders of the gap quests Icy Veins already answered (its cache only). */
function icyveins_cached_quests(array $quests): array
{
    $ev = ['start' => [], 'end' => []];
    foreach (array_keys($quests) as $quest) {
        $path = FT_ROOT . "/data/icyveins/quest/$quest.json";
        if (is_file($path)) icyveins_quest_evidence($ev, $quest, (array)((json_decode((string)file_get_contents($path), true) ?: [])['relations'] ?? []));
    }
    return $ev;
}

function icyveins_quest_evidence(array &$ev, int $quest, array $r): void
{
    foreach ((array)($r['addon_givers'] ?? []) as $g) {
        [$kind, $id] = !empty($g['npc_id']) ? ['npc', (int)$g['npc_id']] : ['go', (int)($g['gameobject_id'] ?? 0)];
        if (!$id) continue;
        if (!empty($g['starts'])) $ev['start'][] = [$kind, $id, $quest];
        if (!empty($g['ends'])) $ev['end'][] = [$kind, $id, $quest];
    }
}

function icyveins_item_evidence(array &$ev, int $item, array $r): void
{
    foreach ((array)($r['addon_dropped_by'] ?? []) as $d) {
        $chance = 100 * (float)($d['chance'] ?? 0);
        if (!empty($d['npc_id'])) $ev['drop'][] = ['npc', (int)$d['npc_id'], $item, $chance];
        elseif (!empty($d['gameobject_id'])) $ev['drop'][] = ['go', (int)$d['gameobject_id'], $item, $chance];
    }
    foreach ((array)($r['addon_sold_by'] ?? []) as $s) {
        if (empty($s['npc_id']) || (isset($s['current']) && !$s['current']) || !empty($s['cost_item_ids']) || !empty($s['cost_currency_ids'])) continue;
        $ev['sell'][] = [(int)$s['npc_id'], $item, (int)($s['remaining'] ?? 0) > 0 ? (int)$s['remaining'] : 0];
    }
}

function icyveins_import(?callable $progress = null): array
{
    if ($e = source_check()) return $e;
    $gaps = source_gaps();
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => []];
    $asked = 0; $done = 0;
    $todo = count($gaps['items']) + count($gaps['noGiver'] + $gaps['noEnder']);
    $trainers = source_trainer_npcs();
    $todo += count($trainers);
    $tick = function () use (&$done, $todo, $progress, &$asked) { if ($progress && ++$done % 200 === 0) $progress("$done/$todo looked at, $asked asked"); };
    foreach (array_keys($gaps['items']) as $item) {
        icyveins_item_evidence($ev, $item, (array)(icyveins_get('item', $item, $asked)['relations'] ?? [])); $tick();
    }
    foreach (array_keys($gaps['noGiver'] + $gaps['noEnder']) as $quest) {
        icyveins_quest_evidence($ev, $quest, (array)(icyveins_get('quest', $quest, $asked)['relations'] ?? [])); $tick();
    }
    foreach ($trainers as $npc) {
        $r = icyveins_get('npc', $npc, $asked)['relations'] ?? []; $tick();
        foreach ((array)($r['addon_trains'] ?? []) as $s) {
            if (empty($s['spell_id']) || !empty($s['item_id'])) continue;
            if ((int)(json_decode((string)($s['details'] ?? ''), true)['trainerType'] ?? 0) === 2) {
                $ev['left']['trainer_profession_skill_unknown'] = ($ev['left']['trainer_profession_skill_unknown'] ?? 0) + 1;   // no skill rank given
                continue;
            }
            $cost = max(array_map(fn($p) => (int)($p['cost'] ?? 0), (array)($s['prices'] ?? [])) ?: [(int)($s['cost'] ?? 0)]);
            $rankNo = preg_match('/(\d+)/', (string)($s['rank'] ?? ''), $m) ? (int)$m[1] : 0;
            $ev['train'][] = [$npc, (int)$s['spell_id'], $cost, (int)($s['req_level'] ?? 0), 0, 0, null, $rankNo];
        }
    }
    $label = 'Icy Veins ' . date('Y-m-d');
    [$tables, $left] = source_tables($ev, $label, $gaps);
    if ($asked >= (int)(config('icyveins', 'max', 20000) ?: 20000)) $left['icyveins_lookup_limit_reached_run_again'] = 1;
    return source_card('icyveins', $label, 'icyveins@' . date('Y-m-d'), $tables, $left);
}

// ------------------------------------------------------------------ background runs (long imports)
function source_log(string $source): string { return FT_ROOT . "/data/source-$source.log"; }

function source_running(string $source): bool
{
    // the run touches its lock at each progress line (every 200 Icy Veins lookups, under two minutes): a lock left
    // untouched for 15 minutes belongs to a run that a restart or a crash stopped
    $lock = FT_ROOT . "/data/source-$source.running";
    return is_file($lock) && time() - filemtime($lock) < 15 * 60;
}

/** Starts tools/source-import.php <source> in the background (Icy Veins takes about an hour the first time). */
function source_start(string $source): array
{
    if (source_running($source)) return ['ok' => false, 'message' => t('Already running.', 'Déjà en cours.')];
    $php = (string)config('tools', 'php', PHP_BINARY ?: 'php');
    exec('(' . escapeshellarg($php) . ' ' . escapeshellarg(FT_ROOT . '/tools/source-import.php') . ' ' . escapeshellarg($source) . ' > ' . escapeshellarg(source_log($source)) . ' 2>&1) > /dev/null 2>&1 &');
    return ['ok' => true, 'message' => sprintf(t('%s started in the background; its import card appears below when it is done (reload the page).', '%s a démarré en arrière-plan ; sa carte d’import apparaît ci-dessous une fois terminé (rechargez la page).'), SOURCES[$source][0] ?? $source)];
}
