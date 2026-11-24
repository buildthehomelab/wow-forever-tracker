<?php
// QuestieDB (https://github.com/Questie/QuestieDB, GPL-3.0): the quest database of the Questie addon, kept for WoW
// Forever with what more than a million of its players' sessions recorded (QuestieTrace) and curated by hand. It
// ranks right after Wowhead (the user's decision of 2026-11-16) and needs no second source: its drops come in alone.
//
// What it imports: which creatures drop an item and which chests hold it (itemKeys npcDrops / objectDrops), for every
// creature or chest the server has that does not give the item yet, not only for items nobody can get.
// And who gives and takes each quest (questKeys startedBy / finishedBy, creatures and objects) for the quests the server
// has no giver or ender for: its reviewed delta, its fixes and what its players recorded on live (foreverQuestTraces). Read from the
// commit of QuestieDB's newest release, downloaded once into data/questie/<commit>/:
//
//   data/Forever/foreverItemDB.lua                             its Forever item database (Classic's, moved to
//                                                               Forever's maps and corrected since)
//   src/corrections/Forever/generated/foreverBaseItem.lua      the reviewed delta it builds for Forever
//   src/corrections/Forever/foreverItemFixes.lua               fixes written by hand
//   src/corrections/Forever/traces/foreverItemTraces.lua       drops its players recorded on live Forever
//
// A correction applies as in Questie: a plain list replaces the list (an empty one means "drops from nothing"),
// `_add` adds to it, `_remove` takes out. QuestieDB has no drop chance. A row takes the chance the server already
// gives the item elsewhere (its best one); an item a quest asks for, with none, takes [questie] quest_chance (40 by
// default) and drops only for a player on the quest; any other item without a chance is left out and counted.
//
// See docs/SOURCES.md.
require_once FT_APP . '/sources.php';

const QUESTIE_REPO = 'Questie/QuestieDB';
const QUESTIE_BASE = 'data/Forever/foreverItemDB.lua';
/** The correction files, in the order Questie applies them. */
const QUESTIE_CORRECTIONS = ['src/corrections/Forever/generated/foreverBaseItem.lua', 'src/corrections/Forever/foreverItemFixes.lua',
    'src/corrections/Forever/traces/foreverItemTraces.lua'];
const QUESTIE_KINDS = ['npcDrops' => 'npc', 'objectDrops' => 'go'];
/** The quest files, in the order Questie applies them: the reviewed delta it builds for Forever, the fixes written by
 *  hand, what its players recorded on live (who gives and takes each quest: startedBy / finishedBy). */
const QUESTIE_QUEST_FILES = ['src/corrections/Forever/generated/foreverBaseQuest.lua', 'src/corrections/Forever/foreverQuestFixes.lua',
    'src/corrections/Forever/traces/foreverQuestTraces.lua'];

/** [commit, tag, error]: [questie] commit when set, else the commit QuestieDB's newest release was tagged on. */
function questie_release(): array
{
    $c = trim((string)config('questie', 'commit', ''));
    if (preg_match('/^[0-9a-f]{40}$/', $c)) return [$c, '', ''];
    [$status, $body] = source_http('https://api.github.com/repos/' . QUESTIE_REPO . '/releases/latest', 30);
    $tag = (string)(json_decode($body, true)['tag_name'] ?? '');
    if ($status !== 200 || !preg_match('/^[\w.\-+]+$/', $tag)) return ['', '', sprintf(t('QuestieDB\'s newest release cannot be read (HTTP %d).', 'La dernière version de QuestieDB est illisible (HTTP %d).'), $status)];
    [$status, $body] = source_http('https://api.github.com/repos/' . QUESTIE_REPO . '/commits/' . rawurlencode($tag), 30);
    $sha = (string)(json_decode($body, true)['sha'] ?? '');
    if ($status !== 200 || !preg_match('/^[0-9a-f]{40}$/', $sha)) return ['', $tag, sprintf(t('QuestieDB %s: its commit cannot be read (HTTP %d).', 'QuestieDB %s : son commit est illisible (HTTP %d).'), $tag, $status)];
    return [$sha, $tag, ''];
}

/** Whether a downloaded file came whole: the item database ends its table, a correction file its function. */
function questie_whole(string $path, string $body): bool
{
    if ($path === QUESTIE_BASE) return preg_match('/^\[\d+\] = \{/m', $body) === 1 && preg_match('/\}\]\]\s*$/', $body) === 1;
    // its Load function's last line, then perhaps a line that hands the module back (return ForeverBaseItem)
    return str_contains($body, ':Load()') && preg_match('/\bend\s*(return\s+\w+\s*)?$/', $body) === 1;
}

/** [folder, error] of a commit, its files downloaded once. */
function questie_fetch(string $commit): array
{
    $dir = FT_ROOT . "/data/questie/$commit";
    foreach (array_merge([QUESTIE_BASE], QUESTIE_CORRECTIONS, QUESTIE_QUEST_FILES) as $path) {
        $target = "$dir/$path";
        if (is_file($target)) continue;
        [$status, $body, $length] = source_http('https://raw.githubusercontent.com/' . QUESTIE_REPO . "/$commit/$path", 120);
        if ($status !== 200) return ['', sprintf(t('QuestieDB %s cannot be downloaded (HTTP %d).', 'QuestieDB %s ne peut pas être téléchargé (HTTP %d).'), basename($path), $status)];
        $problem = source_keep($target, $body, $length, fn($b) => questie_whole($path, $b));
        if ($problem !== '') return ['', 'QuestieDB ' . basename($path) . ': ' . $problem];
    }
    // every file of the commit in the answers table (app/sourceanswers.php): nothing when it is there already
    require_once FT_APP . '/sourceanswers.php';
    source_answers_version_try('questie');
    return [$dir, ''];
}

/** The ids of a Lua list of numbers ("{40,327}", "{}"); null for nil or anything else. */
function questie_ids(string $list): ?array
{
    if (!preg_match('/^\{\s*([\d\s,]*)\}$/', trim($list), $m)) return null;
    return array_values(array_unique(array_map('intval', array_filter(array_map('trim', explode(',', $m[1])), 'strlen'))));
}

/**
 * Who drops each item: [item => ['npc' => [ids], 'go' => [ids]]], from the item database's text and the correction
 * files' texts in Questie's order. An item no creature or chest drops is left out.
 */
function questie_drops(string $base, array $corrections): array
{
    $out = [];
    // [id] = {'name',npcDrops,objectDrops,...}: a name in single quotes, escapes kept
    preg_match_all("/^\\[(\\d+)\\] = \\{'(?:[^'\\\\]|\\\\.)*',(\\{[\\d,]*\\}|nil),(\\{[\\d,]*\\}|nil),/m", $base, $rows, PREG_SET_ORDER);
    foreach ($rows as [, $item, $npcs, $objects]) {
        foreach (['npc' => $npcs, 'go' => $objects] as $kind => $list) if (($ids = questie_ids($list)) !== null) $out[(int)$item][$kind] = $ids;
    }
    foreach ($corrections as $text) {
        $text = preg_replace('/--[^\n]*/', '', $text);                 // comments (a commented-out field is not applied)
        // one item's correction: [id] = { ... }, its fields on their own lines
        preg_match_all('/^\s*\[(\d+)\]\s*=\s*\{(.*?)^\s*\},?\s*$/ms', $text, $blocks, PREG_SET_ORDER);
        foreach ($blocks as [, $item, $body]) {
            preg_match_all('/\[itemKeys\.(npcDrops|objectDrops)(_add|_remove)?\]\s*=\s*(\{[\d\s,]*\})/', $body, $fields, PREG_SET_ORDER);
            foreach ($fields as [, $field, $how, $list]) {
                $kind = QUESTIE_KINDS[$field];
                $ids = questie_ids($list) ?? [];
                $now = $out[(int)$item][$kind] ?? [];
                $now = match ($how) { '_add' => array_values(array_unique(array_merge($now, $ids))), '_remove' => array_values(array_diff($now, $ids)), default => $ids };
                $out[(int)$item][$kind] = $now;
            }
        }
    }
    foreach ($out as $item => $kinds) {
        $out[$item] = array_filter($kinds);
        if (!$out[$item]) unset($out[$item]);
    }
    return $out;
}

/** A Lua table of numbers and nils ("{nil, {642497}}", "{{217996},nil,{264125}}") as a PHP array; null when it is
 *  anything else. */
function questie_table(string $lua): ?array
{
    $lua = trim($lua);
    if (!preg_match('/^[\{\}\d\s,nil]+$/', $lua)) return null;
    $json = json_decode(str_replace(['{', '}', 'nil'], ['[', ']', 'null'], $lua), true);
    return is_array($json) ? $json : null;
}

/**
 * Who gives and who takes each quest: [quest => ['start' => ['npc' => [ids], 'go' => [ids]], 'end' => [...]]], from
 * the quest files' texts in Questie's order. A plain field replaces what came before, `_add` adds, `_remove` takes out;
 * a commented-out field is not applied. Items that start a quest (startedBy's third list) are left out: the quest's own
 * StartItem says it.
 */
function questie_relations(array $texts): array
{
    $out = [];
    $kinds = [0 => 'npc', 1 => 'go'];
    foreach ($texts as $text) {
        $text = preg_replace('/--[^\n]*/', '', $text);
        preg_match_all('/^\s*\[(\d+)\]\s*=\s*\{(.*?)^\s*\},?\s*$/ms', $text, $blocks, PREG_SET_ORDER);
        foreach ($blocks as [, $quest, $body]) {
            preg_match_all('/\[questKeys\.(startedBy|finishedBy)(_add|_remove)?\]\s*=\s*(\{[^\n]*\})\s*,?\s*$/m', $body, $fields, PREG_SET_ORDER);
            foreach ($fields as [, $field, $how, $lua]) {
                $table = questie_table($lua);
                if ($table === null) continue;
                $role = $field === 'startedBy' ? 'start' : 'end';
                foreach ($kinds as $i => $kind) {
                    $ids = array_values(array_unique(array_map('intval', array_filter((array)($table[$i] ?? []), fn($v) => is_int($v) && $v > 0))));
                    $now = $out[(int)$quest][$role][$kind] ?? [];
                    $now = match ($how) { '_add' => array_values(array_unique(array_merge($now, $ids))), '_remove' => array_values(array_diff($now, $ids)), default => $ids };
                    $out[(int)$quest][$role][$kind] = $now;
                }
            }
        }
    }
    foreach ($out as $quest => $roles) {
        foreach ($roles as $role => $kinds) { $roles[$role] = array_filter($kinds); if (!$roles[$role]) unset($roles[$role]); }
        if ($roles) $out[$quest] = $roles; else unset($out[$quest]);
    }
    return $out;
}

/** The relations as evidence rows: ['start' => [[kind, id, quest]], 'end' => [...]], as source_tables() reads them. */
function questie_relation_rows(array $relations): array
{
    $ev = ['start' => [], 'end' => []];
    foreach ($relations as $quest => $roles) foreach ($roles as $role => $kinds) foreach ($kinds as $kind => $ids) foreach ($ids as $id) $ev[$role][] = [$kind, (int)$id, (int)$quest];
    return $ev;
}

/**
 * The drop evidence of these drops for the server: ['drop' => [[kind, id, item, chance]], 'quest_drop' => [...],
 * 'left' => [...]]. $allowed: the items Forever has ([item => true], the analysis' official items); $later: items of
 * a release phase not open yet; $chances: the server's best chance per item; $questItems: items a quest asks for.
 */
function questie_evidence(array $drops, array $allowed, array $later, array $chances, array $questItems, float $questChance): array
{
    $ev = ['drop' => [], 'quest_drop' => [], 'any_item' => true,
           'left' => ['questie_item_not_in_forever' => 0, 'questie_phase_not_open' => 0, 'loot_chance_unknown' => 0]];
    foreach ($drops as $item => $kinds) {
        $n = array_sum(array_map('count', $kinds));
        if (!isset($allowed[$item])) { $ev['left']['questie_item_not_in_forever'] += $n; continue; }
        if (isset($later[$item])) { $ev['left']['questie_phase_not_open'] += $n; continue; }
        $quest = isset($questItems[$item]);
        $chance = (float)($chances[$item] ?? 0) ?: ($quest ? $questChance : 0.0);
        if ($chance <= 0) { $ev['left']['loot_chance_unknown'] += $n; continue; }
        foreach ($kinds as $kind => $ids) foreach ($ids as $id) {
            $ev['drop'][] = [$kind, (int)$id, (int)$item, $chance];
            if ($quest) $ev['quest_drop']["$kind:$id:$item"] = true;
        }
    }
    $ev['left'] = array_filter($ev['left']);
    return $ev;
}

/** The server's best chance of each of these items, in any creature's or chest's table. */
function questie_server_chances(array $items): array
{
    $out = [];
    foreach (array_chunk(array_keys($items), 2000) as $chunk) {
        $in = implode(',', array_map('intval', $chunk));
        foreach (['creature_loot_template', 'gameobject_loot_template'] as $table) {
            foreach (rows("SELECT Item, MAX(ABS(Chance)) c FROM `$table` WHERE ItemType = 0 AND Chance <> 0 AND Item IN ($in) GROUP BY Item", [], 'world') as $r) {
                $out[(int)$r['Item']] = max($out[(int)$r['Item']] ?? 0, (float)$r['c']);
            }
        }
    }
    return $out;
}

/** Imports QuestieDB's newest release as an import card (see the top of this file). $ifNew (the container's check):
 *  nothing when that release was imported last, unless every source was asked again since; exit 3 (retry) while an
 *  analysis runs. */
function questie_import(bool $ifNew = false): array
{
    if ($e = source_check()) return $e;
    if ($ifNew && analysis_status()['running']) return ['ok' => true, 'retry' => true, 'id' => 0, 'counts' => [], 'ignored' => [], 'message' => t('An analysis is running: QuestieDB is checked next time.', 'Une analyse est en cours : QuestieDB sera vérifié la prochaine fois.')];
    [$commit, $tag, $error] = questie_release();
    if ($error !== '') return ['ok' => false, 'message' => $error];
    $mark = FT_ROOT . '/data/questie/imported';
    if ($ifNew && trim((string)@file_get_contents($mark)) === $commit && (int)@filemtime($mark) >= source_refresh_epoch()) {
        return ['ok' => true, 'id' => 0, 'counts' => [], 'ignored' => [], 'message' => sprintf(t('QuestieDB %s already imported.', 'QuestieDB %s déjà importé.'), $tag ?: substr($commit, 0, 8))];
    }
    $out = questie_card_from($commit, $tag);
    if (!empty($out['ok']) || empty($out['counts'])) @file_put_contents($mark, $commit);
    return $out;
}

/** The card of one QuestieDB commit: what it says is kept as a snapshot first (docs/SNAPSHOTS.md), every drop it names
 *  with no chance (QuestieDB has none), so that its card can be made again from the database. */
function questie_card_from(string $commit, string $tag): array
{
    [$dir, $error] = questie_fetch($commit);
    if ($error !== '') return ['ok' => false, 'message' => $error];
    $drops = questie_drops((string)file_get_contents("$dir/" . QUESTIE_BASE), array_map(fn($p) => (string)file_get_contents("$dir/$p"), QUESTIE_CORRECTIONS));
    $relations = questie_relation_rows(questie_relations(array_map(fn($p) => (string)@file_get_contents("$dir/$p"), QUESTIE_QUEST_FILES)));
    $version = $tag !== '' ? "$tag $commit" : $commit;
    snapshot_try('questie', $version, ['drop' => questie_drop_rows($drops)] + $relations);
    return questie_card($drops, $version, $relations);
}

/** [[kind, id, item, null], ...] of the drops: how a snapshot keeps them. */
function questie_drop_rows(array $drops): array
{
    $out = [];
    foreach ($drops as $item => $kinds) foreach ($kinds as $kind => $ids) foreach ($ids as $id) $out[] = [$kind, (int)$id, (int)$item, null];
    return $out;
}

/** The drops back from a snapshot's rows: [item => [kind => [ids]]]. */
function questie_drops_from_rows(array $rows): array
{
    $out = [];
    foreach ($rows as $r) if (isset(QUESTIE_KINDS_BACK[$r[0] ?? ''])) $out[(int)$r[2]][$r[0]][] = (int)$r[1];
    return $out;
}
const QUESTIE_KINDS_BACK = ['npc' => true, 'go' => true];

/** The import card of QuestieDB's drops, against the gaps and the server as they are now. $version: "tag commit". */
function questie_card(array $drops, string $version, array $relations = []): array
{
    $gaps = source_gaps();
    $allowed = [];
    foreach (array_chunk(array_keys($drops), 2000) as $chunk) {
        foreach (rows("SELECT id FROM ft_entities WHERE type = 'item' AND internal = 0 AND id IN (" . implode(',', $chunk) . ')') as $r) $allowed[(int)$r['id']] = true;
    }
    $questItems = [];
    foreach (rows('SELECT DISTINCT ObjectID FROM quest_objectives WHERE Type = 1', [], 'world') as $r) $questItems[(int)$r['ObjectID']] = true;
    $ev = questie_evidence($drops, $allowed, $gaps['later']['items'] ?? [], questie_server_chances($allowed), $questItems, (float)config('questie', 'quest_chance', 40));
    // who gives and takes the quests: givers and enders for the quests that have none (source_tables)
    $ev['start'] = array_values(array_filter($relations['start'] ?? [], fn($r) => !isset($gaps['later']['quests'][(int)$r[2]])));
    $ev['end'] = array_values(array_filter($relations['end'] ?? [], fn($r) => !isset($gaps['later']['quests'][(int)$r[2]])));
    $parts = explode(' ', $version, 2);
    $label = 'QuestieDB ' . (count($parts) === 2 ? $parts[0] : substr($version, 0, 8));
    [$tables, $left] = source_tables($ev, $label, $gaps);
    return source_card('questie', $label, 'questie@' . end($parts), $tables, $left);
}
