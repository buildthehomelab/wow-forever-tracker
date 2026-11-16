<?php
// The timeline's written notes (app/bootstrap.php, tools/ft/notes.py): a hotfix entry named after the days it covers,
// Blizzard's lines a day at a time and kept once, ForeverChanges where Blizzard posted nothing.
require __DIR__ . '/helpers.php';
ft_test_boot();

$update = ['build' => 70888, 'hotfix' => 1, 'released' => '2026-11-10'];
check(hotfix_name($update, []) === 'Hotfixes of Nov 10', 'no window: the day it was read');
check(hotfix_name($update, ['from' => '2026-11-10', 'until' => '2026-11-12']) === 'Hotfixes of Nov 10–12', 'a window in one month');
check(hotfix_name($update, ['from' => '2026-10-30', 'until' => '2026-11-02']) === 'Hotfixes of Oct 30–Nov 2', 'a window over two months');
check(hotfix_name($update, ['from' => '2026-11-07', 'until' => '2026-11-07']) === 'Hotfixes of Nov 7', 'a window of one day');

$dir = ft_test_dir();
$day = ['day' => '2026-11-13', 'sections' => [['name' => 'Classes', 'lines' => [['text' => 'Druid: Wild Growth heals more.', 'mark' => '']]]]];
file_put_contents("$dir/blizzard.json", json_encode(['posts' => [
    ['id' => 1, 'date' => '2026-11-12T00:48:00Z', 'hotfixes' => true, 'url' => 'https://forum/1', 'days' => [$day]],
    ['id' => 2, 'date' => '2026-11-14T01:54:00Z', 'hotfixes' => true, 'url' => 'https://forum/2', 'days' => [$day]],
    ['id' => 3, 'date' => '2026-11-15T01:18:00Z', 'hotfixes' => false, 'url' => 'https://forum/3', 'topic' => 'Dungeon XP Adjustment', 'days' => []],
]]));
file_put_contents("$dir/foreverchanges.json", json_encode(['notes' => [
    ['id' => 'hotfix-2026-11-08', 'kind' => 'hotfix', 'day' => '2026-11-08', 'url' => 'https://fc#8', 'summary' => ['Dungeon XP up 50%.'],
     'sections' => [['name' => 'Dungeons', 'lines' => [['text' => 'Enemies give 50% more experience.', 'mark' => 'buff']]]]],
    ['id' => '1.60.1.70888', 'kind' => 'build', 'day' => '2026-11-10', 'build' => 70888, 'sections' => []],
]]));
$notes = timeline_notes($dir);
check(array_keys($notes['days']) === ['2026-11-08', '2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15'], 'every day something was written about, in order');
check(count($notes['days']['2026-11-13']['blizzard']['sections']['Classes']) === 1, 'a line Blizzard posted twice is kept once');
check($notes['days']['2026-11-13']['blizzard']['urls'] === ['https://forum/1', 'https://forum/2'], 'both posts are linked');
check($notes['days']['2026-11-15']['posts'] === [3], 'another blue post counts on the day it was posted');
check(($notes['days']['2026-11-08']['fc']['id'] ?? '') === 'hotfix-2026-11-08', 'ForeverChanges where Blizzard posted nothing');
check(isset($notes['builds'][70888]), 'a build note by its number');

ft_test_done();
