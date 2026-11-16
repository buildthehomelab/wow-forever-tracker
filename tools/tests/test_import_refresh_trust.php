<?php
// A card's values measured again (its "changes") are weighed against who wrote each row when the card is applied, not
// only when it was made (app/imports.php, import_weigh_changes); and who wrote the rows refreshed before that was kept
// is read back from the History's scripts (import_refresh_keys).
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/forge.php';
require_once FT_APP . '/imports.php';
require_once FT_APP . '/sources.php';

$trust = source_trust('');
$op = ['db' => 'world', 'table' => 'creature_loot_template', 'columns' => ['Entry', 'ItemType', 'Item', 'Chance'], 'match' => ['Entry', 'ItemType', 'Item'], 'set' => 'Chance',
       'rows' => [[38, 0, 159, 11.76], [38, 0, 2070, 5.88], [639, 0, 2592, 20.0], [640, 0, 1, 9.0], [641, 0, 1, 30.0], [642, 0, 1, 50.0]]];
$current = [
    '38|0|159' => ['value' => 6.05, 'comment' => ''],          // Wowhead set it since the card was made
    '38|0|2070' => ['value' => 3.0, 'comment' => ''],          // Wowhead Classic set it: EG Link ranks above
    '639|0|2592' => ['value' => 3.83, 'comment' => ''],        // the core's own row
    '640|0|1' => ['value' => 9.02, 'comment' => ''],           // already what the card says, give or take
    '641|0|1' => ['value' => 2.0, 'comment' => 'Forge #12'],   // an administrator's own fix
    // 642: the server has no such row any more
];
$origin = ['38|0|159' => 'wowhead', '38|0|2070' => 'wowheadclassic'];
[$rows, $keys, $held] = import_weigh_changes($op, $current, $origin, 'eglink', $trust, 10.0);
check($keys === ['38|0|2070', '639|0|2592'], 'only what no more trusted source wrote is set: ' . json_encode($keys));
check($rows === [[38, 0, 2070, 5.88], [639, 0, 2592, 20.0]], 'the rows keep the card\'s values');
check($held === 2, 'a more trusted source\'s row and an administrator\'s are held: ' . $held);
[, $keys] = import_weigh_changes($op, $current, $origin, 'wowhead', $trust, 10.0);
check($keys === ['38|0|159', '38|0|2070', '639|0|2592'], 'Wowhead may change its own rows and those ranked below it');

$script = implode("\n", [
    forge_set_statement('creature_loot_template', 'Chance', 11.76, 6.05, '`Entry` = 38 AND `ItemType` = 0 AND `Item` = 159', 'world'),
    "INSERT INTO `creature_loot_template` (`Entry`) VALUES\n(1);",
    forge_set_statement('quest_template', 'RewardChoiceItemID1', 2070, null, '`ID` = 7', 'world'),
    forge_set_statement('creature_loot_template', 'Chance', 3.5, 11.76, '`Entry` = 38 AND `ItemType` = 0 AND `Item` = 159', 'world'),
]);
check(import_refresh_keys($script) === [['creature_loot_template', '38|0|159'], ['quest_template', '7'], ['creature_loot_template', '38|0|159']],
    'the rows a script refreshed, in order: ' . json_encode(import_refresh_keys($script)));
check(import_refresh_keys("UPDATE `creature_template` SET `npcflag` = `npcflag` | 128 WHERE `entry` = 5;") === [], 'other updates are not refreshes');

ft_test_done();
