<?php
// The Imports page's cards (app/imports.php, import_groups): the ones with something left to apply count and come
// first; a card with nothing left, and a source's earlier card a newer one stands above, fold away.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/imports.php';

$cards = [
    ['id' => 124, 'file' => 'classicdb-holiday-newyear@2026-11-16', 'done_at' => null],
    ['id' => 120, 'file' => 'classicdb-holiday-midsummer@2026-11-16', 'done_at' => '2026-11-16 13:03:00'],
    ['id' => 110, 'file' => 'classicdb-holiday-midsummer@2026-11-16', 'done_at' => null],      // a newer card of its source stands above
    ['id' => 106, 'file' => 'wowhead@2026-11-16-1794846152', 'done_at' => '2026-11-16 13:03:00'],
    ['id' => 102, 'file' => 'wowhead@2026-11-16-1794844344', 'done_at' => '2026-11-16 13:01:00'],
    ['id' => 99, 'file' => 'Tanaris_world.sql', 'done_at' => null],                            // a file imported by hand
];
[$open, $done, $earlier] = import_groups($cards);
check($open === [124, 99], 'cards with something left to apply: the newest of each source, and files imported by hand');
check($done === [120, 106], 'a card with nothing left folds under Applied');
sort($earlier);
check($earlier === [102, 110], 'an earlier card of a source stays with the earlier ones, done or not');
check(import_groups([]) === [[], [], []], 'no card');

ft_test_done();
