<?php
// The Checks page's fix (app/forge.php, forge_check_ops): what "take Wowhead's level or rank" writes, and when there
// is nothing to take. And which import cards are a source's earlier ones (app/imports.php, import_earlier).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/forge.php';
require_once FT_APP . '/imports.php';

$check = ['entry' => 639, 'name' => 'Edwin VanCleef', 'level_min' => 21, 'level_max' => 21, 'rank_id' => 1, 'wh_min' => 22, 'wh_max' => 23, 'wh_rank' => 2, 'issues' => 'level,rank'];
$sets = fn(array $ops) => array_map(fn($o) => $o['table'] . '.' . $o['set'] . '=' . $o['rows'][0][1] . ' where ' . $o['match'][0] . '=' . $o['rows'][0][0], $ops);

check($sets(forge_check_ops($check, 'rank')) === ['creature_template.Classification=2 where entry=639'], 'the rank is the creature template\'s classification');
check($sets(forge_check_ops($check, 'level')) === ['creature_classic_level.level_min=22 where entry=639', 'creature_classic_level.level_max=23 where entry=639'], 'the level is both ends of its range');
check(forge_check_ops(['issues' => 'rank'] + $check, 'level') === [], 'a difference the check does not name is not written');
check(forge_check_ops(['level_min' => null, 'level_max' => null] + $check, 'level') === [], 'a level the server does not state (a boss\'s "??") cannot be taken');
check(forge_check_ops(['wh_min' => null, 'wh_max' => null] + $check, 'level') === [] && forge_check_ops(['wh_min' => 0, 'wh_max' => 0] + $check, 'level') === [], 'nor one Wowhead does not state');
check(forge_check_ops($check, 'faction') === [] && forge_check_ops(['entry' => 0] + $check, 'rank') === [], 'no other kind, no creature 0');
$ops = [];
foreach (forge_check_ops($check, 'level') as $op) forge_merge($ops, $op);
check(count($ops) === 2 && array_values($ops)[0]['set'] === 'level_min', 'the Forge takes them as "set" operations (a value replaced, with its rollback)');

$cards = [['id' => 18, 'file' => 'icyveins@2026-11-14'], ['id' => 17, 'file' => 'wowhead-quest-enders'], ['id' => 15, 'file' => 'eglink@ea970da0'], ['id' => 13, 'file' => 'wowhead-quest-enders'],
          ['id' => 9, 'file' => 'my world fixes.sql'], ['id' => 8, 'file' => 'my world fixes.sql'], ['id' => 2, 'file' => 'eglink@164bd1e2'], ['id' => 1, 'file' => 'foreverdb@2026-11-11']];
check(import_earlier($cards) === [13, 2], 'a source\'s cards below its newest are its earlier ones; a file imported by hand never is');
check(import_earlier(array_reverse($cards)) === [13, 2] && import_earlier([]) === [], 'whatever order they come in');

ft_test_done();
