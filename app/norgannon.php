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
require_once FT_APP . '/sources.php';

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

/** What NorgannonDB says about the gaps, as evidence for source_tables() (app/sources.php). */
function norgannon_evidence(string $dir, array $gaps): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => []];
    foreach (norgannon_records("$dir/items.lua", $gaps['items']) as $item => $r) {
        foreach ((array)($r['drops']['npcs'] ?? []) as $npc => $chance) $ev['drop'][] = ['npc', (int)$npc, $item, (float)$chance];
        foreach ((array)($r['drops']['objects'] ?? []) as $go => $chance) $ev['drop'][] = ['go', (int)$go, $item, (float)$chance];
        foreach ((array)($r['vendors'] ?? []) as $npc => $count) $ev['sell'][] = [(int)$npc, $item, (int)$count];
    }
    foreach (norgannon_records("$dir/quests.lua", $gaps['noGiver'] + $gaps['noEnder']) as $quest => $r) {
        if (($r['hidden'] ?? null) === true) continue;   // not obtainable in the game
        foreach (['starters' => 'start', 'finishers' => 'end'] as $role => $as) {
            foreach ((array)($r[$role]['npcs'] ?? []) as $n) $ev[$as][] = ['npc', (int)$n, $quest];
            foreach ((array)($r[$role]['objects'] ?? []) as $o) $ev[$as][] = ['go', (int)$o, $quest];
        }
    }
    foreach (norgannon_table("$dir/recipes.lua", 'training') as $class => $spells) foreach ((array)$spells as $spell => $s) {
        foreach ((array)($s['trainers'] ?? []) as $npc) $ev['train'][] = [(int)$npc, (int)$spell, (int)($s['cost'] ?? 0), (int)($s['level'] ?? 0), 0, 0,
            array_slice(array_map('intval', array_values((array)($s['needs'] ?? []))), 0, 3), (int)($s['rank'] ?? 0)];
    }
    foreach (norgannon_table("$dir/recipes.lua", 'recipes') as $spell => $r) {
        foreach ((array)($r['trainers'] ?? []) as $npc => $cost) $ev['train'][] = [(int)$npc, (int)$spell, (int)$cost, 0, (int)($r['skill'] ?? 0), (int)($r['learn'] ?? 0), [], 0];
    }
    return $ev;
}

/** Imports the pinned NorgannonDB as an import card (see app/sources.php). */
function norgannon_import(): array
{
    if ($e = source_check()) return $e;
    $commit = norgannon_commit();
    [$dir, $error] = norgannon_fetch($commit);
    if (!$dir) return ['ok' => false, 'message' => $error];
    $gaps = source_gaps();
    $label = 'NorgannonDB ' . substr($commit, 0, 8);
    [$tables, $left] = source_tables(norgannon_evidence($dir, $gaps), $label, $gaps);
    return source_card('norgannondb', $label, 'norgannondb@' . $commit, $tables, $left);
}
