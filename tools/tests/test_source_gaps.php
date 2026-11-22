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

// quests only givers live replaced give or take (meta not_given_quests): not given on Forever, no giver proposed
$given = source_gap_sets([], $set(1, 2, 8951), $set(), $set(), $set(1, 2, 8951), ['items' => [], 'quests' => [], 'spells' => []], $set(8951));
check(array_keys($given['noGiver']) === [1, 2], 'a quest not given on WoW: Forever is no giver gap');

// the quest links a rolled-back Forge operation added are never proposed again
$links = source_rolled_back_links([
    ['sql_apply' => json_encode(['world' => "INSERT INTO `creature_queststarter` (`id`,`quest`,`VerifiedBuild`) VALUES\n(16016,8951,71037),\n(16016,8953,71037);"])],
    ['sql_apply' => json_encode(['world' => "INSERT INTO `gameobject_questender` (`id`, `quest`) VALUES (500, 77);\nUPDATE `creature_loot_template` SET `Chance` = 5 WHERE `Entry` = 1;"])],
    ['sql_apply' => json_encode(['world' => "INSERT INTO `creature_loot_template` (`Entry`,`Item`) VALUES (1,2);"])],
    ['sql_apply' => 'not json'],
]);
$keys = array_keys($links); sort($keys);
check($keys === ['creature_queststarter:16016:8951', 'creature_queststarter:16016:8953', 'gameobject_questender:500:77'], 'only the quest giver and ender links are read, each by table, creature and quest');

ft_test_done();
