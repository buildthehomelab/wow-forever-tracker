<?php
// Quest rewards from Wowhead's pages as Forge fills of quest_template (app/sources.php source_reward_changes): the
// first empty slot of the kind Wowhead names, never one that holds an item, and what was left out.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/sources.php';

$empty = fn(int $id, array $set = []) => array_merge(['ID' => $id], array_fill_keys(array_merge(...array_map(fn($n) => ["RewardItem$n", "RewardAmount$n"], range(1, 4)),
    ...array_map(fn($n) => ["RewardChoiceItemID$n", "RewardChoiceItemQuantity$n"], range(1, 6))), 0), $set);
$quests = [
    81000 => $empty(81000, ['RewardItem1' => 5, 'RewardAmount1' => 1]),                           // slot 1 taken: slot 2
    81001 => $empty(81001),                                                                          // a choice, then a second one
    81002 => $empty(81002, ['RewardChoiceItemID3' => 1001]),                                         // gives it already
    81003 => $empty(81003, array_combine(array_map(fn($n) => "RewardItem$n", range(1, 4)), [1, 2, 3, 4])),   // no free fixed slot
    81004 => $empty(81004),
];
$rewards = [[81000, 1001, 2, 0], [81001, 1002, 1, 1], [81001, 1003, 3, 1], [81002, 1001, 1, 0], [81003, 1004, 1, 0], [81004, 1005, 1, 0], [99999, 1006, 1, 0]];
[$ops, $left] = source_reward_changes($rewards, $quests, [81004 => true]);
$byColumn = [];
foreach ($ops as $op) {
    check($op['table'] === 'quest_template' && $op['columns'] === ['ID', $op['fill']] && $op['set'] === $op['fill'] && $op['match'] === ['ID'], 'a fill of one column, keyed by the quest: ' . json_encode($op));
    $byColumn[$op['fill']] = $op['rows'];
}
check($byColumn === ['RewardItem2' => [[81000, 1001]], 'RewardAmount2' => [[81000, 2]], 'RewardChoiceItemID1' => [[81001, 1002]], 'RewardChoiceItemQuantity1' => [[81001, 1]],
    'RewardChoiceItemID2' => [[81001, 1003]], 'RewardChoiceItemQuantity2' => [[81001, 3]]], 'the first free slot of each kind, the next reward of a quest the next slot: ' . json_encode($byColumn));
ksort($left);
check($left === ['reward_known' => 1, 'reward_no_free_slot' => 1, 'reward_phase_not_open' => 1, 'reward_quest_unknown' => 1],
    'left out: given already, no free slot, a phase not open, a quest unknown to the server: ' . json_encode($left));
check(source_reward_changes([], $quests) === [[], []], 'no rewards, no operation');

// the Forge takes such an operation as a fill: written only where the column is still 0
$ops2 = [];
forge_merge($ops2, $ops[0]);
check(count($ops2) === 1 && reset($ops2)['fill'] === $ops[0]['fill'], 'forge_merge keeps it as a fill');
ft_test_done();
