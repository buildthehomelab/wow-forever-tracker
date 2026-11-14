<?php
// The gaps an import aims at leave out what waits for a release phase that is not open yet, and count it
// (source_gap_sets(), app/sources.php).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$set = fn(int ...$ids) => array_fill_keys($ids, true);

$gaps = source_gap_sets(
    $set(100, 101, 102, 103),          // items players cannot get
    $set(1, 2, 3, 4, 5, 900),          // quests of the server without a giver
    $set(2, 3, 6, 7, 901),             // ... without an ender
    $set(4),                           // quest 4 is started by an item: no giver on purpose
    $set(1, 2, 3, 4, 5, 6, 7),         // the client's own quests (900 and 901 belong to another version of the game)
    ['items' => $set(102, 103, 555), 'quests' => $set(3, 5, 7, 8), 'spells' => $set(9001)]);

check(array_keys($gaps['items']) === [100, 101], 'items of a phase that is not open are no gap');
check(array_keys($gaps['noGiver']) === [1, 2], 'nor are its quests without a giver (the quest an item starts and the other versions\' quests stay out as before)');
check(array_keys($gaps['noEnder']) === [2, 6], 'nor its quests without an ender');
check(array_keys($gaps['later']['items']) === [102, 103], 'the items left out for their phase are counted: only those that were gaps');
$quests = array_keys($gaps['later']['quests']); sort($quests);
check($quests === [3, 5, 7], 'so are the quests, each once (quest 3 lacks both a giver and an ender)');
check($gaps['later']['spells'] === $set(9001), 'the spells no trainer may teach yet are handed on');

// no phase is closed: the gaps are what they were
$open = source_gap_sets($set(100, 101), $set(1, 4, 900), $set(2), $set(4), $set(1, 2, 4), ['items' => [], 'quests' => [], 'spells' => []]);
check(array_keys($open['items']) === [100, 101] && array_keys($open['noGiver']) === [1] && array_keys($open['noEnder']) === [2], 'with every phase open nothing is left out');
check($open['later'] === ['items' => [], 'quests' => [], 'spells' => []], 'and nothing is counted');

ft_test_done();
