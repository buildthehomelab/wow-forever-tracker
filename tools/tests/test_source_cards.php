<?php
// A new import card of a source replaces that source's earlier cards nothing was applied from, and only those
// (source_stale_cards(), app/sources.php).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$cards = [
    11 => 'atlasloot@7001',          // never applied
    12 => 'atlasloot@7002',          // applied (in whole or in part)
    13 => 'atlasloot@7003',          // applied, then rolled back
    14 => 'atlasloot@7004',          // its only apply failed: nothing was written
    15 => 'atlasloot@7005',          // an apply is being written
    16 => 'atlasloot@7006',          // failed once, then applied
    21 => 'icyveins@2026-11-01',     // another source
    22 => 'atlasloot-notes.sql',     // a file someone uploaded, whatever its name
    23 => 'wowhead-quest-enders',
];
$import = fn(int $id) => json_encode([['type' => 'import', 'id' => $id, 'kind' => 'import']]);
$logs = [
    ['items' => $import(12), 'state' => 'applied'],
    ['items' => $import(13), 'state' => 'rolled_back'],
    ['items' => $import(14), 'state' => 'failed'],
    ['items' => $import(15), 'state' => 'pending'],
    ['items' => $import(16), 'state' => 'failed'],
    ['items' => $import(16), 'state' => 'applied'],
    ['items' => json_encode([['type' => 'item', 'id' => 11, 'kind' => 'vendor']]), 'state' => 'applied'],   // item 11, not import 11
    ['items' => 'not json', 'state' => 'applied'],
];

check(source_stale_cards('atlasloot', $cards, $logs) === [11, 14], 'never applied, or only a failed apply: replaced');
check(!array_intersect(source_stale_cards('atlasloot', $cards, $logs), [12, 13, 15, 16]), 'applied, rolled back or being applied: kept');
check(source_stale_cards('icyveins', $cards, $logs) === [21], 'each source only replaces its own cards');
check(source_stale_cards('eglink', $cards, $logs) === [], 'a source without cards replaces nothing');
check(source_stale_cards('atlasloot', $cards, []) === [11, 12, 13, 14, 15, 16], 'with an empty history every earlier card of the source goes');
check(source_stale_cards('atlasloot', [], $logs) === [], 'no card: nothing');
// the history's rows may arrive decoded
check(source_stale_cards('atlasloot', [12 => 'atlasloot@7002'], [['items' => [['type' => 'import', 'id' => 12]], 'state' => 'applied']]) === [], 'items already decoded count too');

ft_test_done();
