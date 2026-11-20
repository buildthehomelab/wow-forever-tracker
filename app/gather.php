<?php
// The work list of what the content still to come needs (docs/GATHER.md): data/gather.json, written by the analysis
// (tools/ft/gather.py). Per release phase, and for the open one ("now"): the quests with who gives and takes them and
// what they ask, the creatures and objects the server lacks, the items with where they come from, each with what the
// sources already hold. The Wowhead crawl reads the pages it names (app/wowheadpages.php), Import Icy Veins asks its
// answers first (app/icyveins.php), and The Forge › Later shows it (app/pages/admin/later.php).

function gather_file(): string { return FT_ROOT . '/data/gather.json'; }

/** The work list as the last analysis wrote it, [] when there is none. $file: another file (the tests). */
function gather_list(?string $file = null): array
{
    static $cache = [];
    $file ??= gather_file();
    if (!array_key_exists($file, $cache)) {
        $data = is_file($file) ? json_decode((string)file_get_contents($file), true) : null;
        $cache[$file] = is_array($data) ? $data : [];
    }
    return $cache[$file];
}

/** The Icy Veins answers the work list wants and the mirror does not hold: [kind => ids] (npc, gameobject, quest, item). */
function gather_icyveins(?array $list = null): array
{
    $out = [];
    foreach ((array)(($list ?? gather_list())['icyveins'] ?? []) as $kind => $ids) {
        if (!in_array($kind, ['npc', 'gameobject', 'quest', 'item'], true)) continue;
        $out[$kind] = array_values(array_unique(array_filter(array_map('intval', (array)$ids), fn($id) => $id > 0)));
    }
    return array_filter($out);
}

/** One line per phase of what the list counts, for the page and the log: [key => ['name', 'opens', 'counts']]. */
function gather_summary(?array $list = null): array
{
    $out = [];
    foreach ((array)(($list ?? gather_list())['phases'] ?? []) as $p) {
        if (!is_array($p) || !isset($p['key'])) continue;
        $out[(string)$p['key']] = ['name' => (string)($p['name'] ?? $p['key']), 'opens' => $p['opens'] ?? null, 'counts' => (array)($p['counts'] ?? [])];
    }
    return $out;
}
