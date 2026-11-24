<?php
// A whole quest a source recorded, written as the server's rows when the server has none (source_quest_rows(),
// app/sources.php): Icy Veins' recording of Lifted by Legacy (92101, Mount Hyjal), trimmed to what is read.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$payload = [
    'e' => ['id' => 92101, 'title' => 'Lifted by Legacy', 'objective' => "Find the Veteran of the Third War's markings of significance on the Great Lift.",
        'description' => "Hyjal is difficult to bear.\r\n\r\nSee if the marks remain, <name>?", 'flags' => 35782656, 'obsolete' => false, 'level' => 58, 'min_level' => 54,
        'content_tuning_id' => null, 'zone_id' => 616, 'quest_sort' => null, 'next_quest_id' => null, 'reward_money' => 17050, 'reward_xp_difficulty' => 5,
        'reward_spell_id' => null, 'start_item_id' => 274795, 'races' => 8589934762, 'expansion' => -2, 'reward_xp_multiplier' => 1,
        'reward_money_difficulty' => 5, 'reward_money_multiplier' => 1.8944445, 'accepted_sound_kit_id' => 890, 'complete_sound_kit_id' => 878],
    'o' => [['quest_id' => 92101, 'idx' => 0, 'type' => 19, 'object_id' => 40396, 'amount' => 0, 'description' => "Tobin's spot visited", 'objective_id' => 466710,
             'storage_index' => 0, 'flags' => 32, 'flags2' => 0, 'progress_weight' => 0, 'parent_objective_id' => null],
            ['quest_id' => 92101, 'idx' => 1, 'type' => 1, 'object_id' => 274795, 'amount' => 1, 'description' => null, 'objective_id' => 477675,
             'storage_index' => 1, 'flags' => 48, 'flags2' => 1, 'progress_weight' => 0, 'parent_objective_id' => null]],
    'r' => [['reward' => 'money', 'amount' => 17050], ['reward' => 'xp', 'amount' => 6200], ['reward' => 'item', 'item_id' => 221316, 'amount' => 1],
            ['reward' => 'item', 'item_id' => 216619, 'amount' => 3], ['reward' => 'choice', 'item_id' => 274802, 'amount' => 1],
            ['reward' => 'reputation', 'faction_id' => 68, 'amount' => 300], ['reward' => 'currency', 'currency_id' => 3201, 'amount' => 2],
            ['reward' => 'spell', 'spell_id' => 1301001, 'how' => 'learn']],
    'p' => [['id' => 92100, 'level' => 57], 92099],
];
$rows = source_quest_rows(92101, $payload, 71037);
$q = $rows['quest_template'][0];
check($q['ID'] === 92101 && $q['LogTitle'] === 'Lifted by Legacy' && $q['QuestSortID'] === 616 && $q['StartItem'] === 274795, 'the quest, filed under its zone when it names no sort');
check($q['QuestDescription'] === 'Hyjal is difficult to bear.$B$BSee if the marks remain, $n?', 'line breaks as $B, the recording\'s <name> as $n: ' . $q['QuestDescription']);
check($q['RewardXPDifficulty'] === 5 && $q['RewardMoneyDifficulty'] === 5 && abs($q['RewardMoneyMultiplier'] - 1.8944445) < 1e-9 && $q['AllowableRaces'] === '8589934762', 'XP and money by difficulty, the races as they are');
check($q['RewardItem1'] === 221316 && $q['RewardAmount2'] === 3 && $q['RewardChoiceItemID1'] === 274802 && $q['RewardFactionID1'] === 68 && $q['RewardFactionOverride1'] === 30000
    && $q['RewardCurrencyID1'] === 3201 && $q['RewardDisplaySpell1'] === 1301001 && $q['VerifiedBuild'] === 71037, 'items, a choice, reputation x 100, a currency, the spell shown');
check(array_column($rows['quest_objectives'], 'ID') === [466710, 477675] && $rows['quest_objectives'][1]['ObjectID'] === 274795 && $rows['quest_objectives'][0]['Type'] === 19,
    'the objectives with their own ids, types and order');
check($rows['quest_classic_level'] === [['ID' => 92101, 'QuestLevel' => 58, 'MinLevel' => 54, 'MaxLevel' => 0]] && $rows['quest_template_classic_level'][0]['QuestLevel'] === 58, 'its level and minimum level');
check($rows['quest_template_addon'][0]['PrevQuestID'] === 92100, 'the quest before it, as an object or a number');

$all = source_quest_rows(5, ['e' => ['title' => 'Everyone', 'races' => -1]]);
check(array_keys($all['quest_template'][0]) === array_keys($rows['quest_template'][0]), 'every quest row has the same columns, whatever it rewards (a card takes its columns from its first row)');
check($all['quest_template'][0]['AllowableRaces'] === '18446744073709551615' && !isset($all['quest_template_addon']) && !isset($all['quest_classic_level']), 'races -1 as the unsigned mask; no addon or level row when the source has none');
foreach (['REUSE ME', 'REUSEME', 'Violent Winds (Temp Disabled)', '<UNUSED> Old', '[DNT] Credit'] as $title) check(source_quest_rows(7, ['e' => ['title' => $title]]) === null, "not written: $title");
check(source_quest_rows(7, ['e' => ['title' => 'Gone', 'obsolete' => true]]) === null && source_quest_rows(7, ['e' => ['title' => '']]) === null, 'an obsolete or untitled one is not written either');

ft_test_done();
