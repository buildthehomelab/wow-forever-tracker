<?php
// What the website accepts from the quest refresh (tools/tracker.py refresh quests -> app/sources.php): the tables and
// columns it may set, and nothing else, whatever the file says.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$op = fn(string $table, string $set, array $rows, ?array $columns = null, ?array $match = null) =>
    ['db' => 'world', 'table' => $table, 'columns' => $columns ?? ['ID', $set], 'match' => $match ?? ['ID'], 'set' => $set, 'rows' => $rows];
$kept = fn(array $ops) => array_map(fn($o) => $o['table'] . '.' . $o['set'] . ':' . count($o['rows']), source_quest_changes(['changes' => $ops]));

check($kept([$op('quest_template', 'RewardItem1', [[7, 2589]]), $op('quest_template', 'QuestDescription', [[7, "We need cloth.\n\nHurry."]]),
             $op('quest_objectives', 'Amount', [[9001, 8]]), $op('quest_classic_level', 'MinLevel', [[7, 6]]),
             $op('quest_template', 'RewardXPMultiplier', [[7, 1.5]])])
    === ['quest_template.RewardItem1:1', 'quest_template.QuestDescription:1', 'quest_objectives.Amount:1', 'quest_classic_level.MinLevel:1', 'quest_template.RewardXPMultiplier:1'],
    'rewards, texts, objective amounts and the offered level are accepted');
check($kept([$op('quest_template', 'Flags', [[7, 8]]), $op('quest_template', 'AllowableRaces', [[7, 1]]), $op('quest_template', 'ID', [[7, 8]])]) === [],
    'how the server handles a quest is never set: flags, races, the id');
check($kept([$op('creature_template', 'faction', [[7, 35]]), $op('account', 'gmlevel', [[1, 3]])]) === [], 'no other table');
check($kept([$op('quest_classic_money', 'RewardMoney', [[7, 6600]]), $op('quest_classic_level', 'QuestLevel', [[7, 57]])]) === [], 'money and the quest\'s own level follow the player who recorded them: never set');
check($kept([$op('quest_template', 'RewardItem1', [[7, 2589]], ['ID', 'RewardItem1', 'Flags']), $op('quest_template', 'RewardItem1', [[7, 2589]], null, ['RewardItem1'])]) === [],
    'an operation of another shape is dropped whole');
check($kept([$op('quest_template', 'RewardItem1', [[7, 2589], ['7 OR 1=1', 1], [0, 1], [8, [1]], [9, null], [10, 5, 6]])]) === ['quest_template.RewardItem1:1'],
    'rows without a whole-number key or a plain value are dropped');
check(source_quest_changes([]) === [] && source_quest_changes(['changes' => 'x']) === [], 'a result that is no result gives nothing');

ft_test_done();
