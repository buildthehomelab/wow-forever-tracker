<?php
// The history page asks MySQL for the first characters of each saved script only; the whole text of one operation
// comes from forge_log_script() (app/forge.php), and rolling back never reads either.
require __DIR__ . '/helpers.php';
ft_test_boot("[database]\nworld = \"my_world\"\nhotfixes = \"my_hotfixes\"\n");
require FT_APP . '/forge.php';

$columns = forge_log_preview_columns();
foreach (['apply', 'rollback'] as $part) foreach (['world', 'hotfixes', 'console'] as $key) {
    $text = "JSON_UNQUOTE(JSON_EXTRACT(sql_$part, '$.$key'))";
    check(str_contains($columns, "LEFT($text, 4000) {$part}_$key, CHAR_LENGTH($text) {$part}_{$key}_length"), "the page selects a prefix and the length of $part / $key");
}
check(!preg_match('/(^|[ ,])sql_(apply|rollback)\s*(,|$)/', $columns), 'and never a whole script');

$insert = "INSERT INTO `npc_vendor` (`entry`,`item`) VALUES\n(54,25),\n(54,35);";
$log = ['id' => 7, 'kind' => 'import', 'created_at' => '2026-11-14 10:00:00',
    'sql_apply' => json_encode(['world' => $insert . "\nUPDATE `creature_template` SET `npcflag` = `npcflag` | 128 WHERE `entry` = 54;", 'hotfixes' => "INSERT INTO `item` (`ID`) VALUES\n(25);"]),
    'sql_rollback' => json_encode(['world' => "UPDATE `creature_template` SET `npcflag` = `npcflag` & ~128 WHERE `entry` = 54;\nDELETE FROM `npc_vendor` WHERE (`entry`,`item`) IN ((54,25),(54,35));", 'hotfixes' => 'DELETE FROM `item` WHERE `ID` IN (25);'])];
$apply = forge_log_script($log, 'apply');
check(str_contains($apply, '#7') && str_contains($apply, 'USE `my_world`;') && str_contains($apply, 'USE `my_hotfixes`;'), 'the whole script names its operation and each database');
check(str_contains($apply, $insert) && str_contains($apply, '`npcflag` | 128') && str_contains($apply, "INSERT INTO `item` (`ID`) VALUES\n(25);"), 'with every statement of the apply');
check(substr_count($apply, 'START TRANSACTION;') === 2 && substr_count($apply, 'COMMIT;') === 2, 'each database in its transaction, as a downloaded preview is');
$rollback = forge_log_script($log, 'rollback');
check(str_contains($rollback, 'DELETE FROM `npc_vendor`') && str_contains($rollback, '& ~128') && !str_contains($rollback, 'INSERT INTO'), 'the rollback is the saved rollback, not the apply');
check(forge_log_script($log, 'anything else') === $apply, 'an unknown part is the apply');

// spawns made through the remote console keep commands, not SQL
$console = ['id' => 8, 'kind' => 'spawn', 'created_at' => '2026-11-14 11:00:00',
    'sql_apply' => json_encode(['console' => ".forge spawn npc 54 0 1 2 3   -> guid 900"]), 'sql_rollback' => json_encode(['console' => 'forge delete npc 900'])];
check(str_contains(forge_log_script($console, 'rollback'), "forge delete npc 900") && !str_contains(forge_log_script($console, 'rollback'), 'USE `'), 'console commands are listed as they are, with no USE');
check(str_contains(forge_log_script(['id' => 9], 'apply'), '#9'), 'an operation without scripts gives its heading alone');

ft_test_done();
