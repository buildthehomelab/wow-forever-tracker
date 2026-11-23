<?php
// Turn-in words from a source (app/sources.php source_text_rows): a quest with no row gets one, a row without words
// gets them through a Forge fill, a row with words is left alone, and a quest of a closed phase gets nothing.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/sources.php';

$list = [10 => 'No row yet.', 11 => 'A row without words.', 12 => 'A row with words.', 13 => 'Not on the server.', 14 => 'Opens later.', 15 => 'Blank row, opens later.'];
$quests = [10 => true, 11 => true, 12 => true, 14 => true, 15 => true];
$have = [11 => '', 12 => 'What the server says.', 15 => "  \n"];
[$new, $fill, $left] = source_text_rows('complete', $list, $quests, $have, [14 => true, 15 => true]);

check($new === [['ID' => 10, 'RewardText' => 'No row yet.', 'VerifiedBuild' => 0]], 'a quest with no row gets a quest_offer_reward row');
check(is_array($fill) && $fill['table'] === 'quest_offer_reward' && $fill['fill'] === 'RewardText' && $fill['set'] === 'RewardText'
    && $fill['columns'] === ['ID', 'RewardText'] && $fill['match'] === ['ID'] && $fill['db'] === 'world', 'a row without words is a fill of RewardText');
check(($fill['rows'] ?? null) === [[11, 'A row without words.']], 'for that quest alone: the row with words and the later quests are not in it');
check($left === ['text_known' => 1, 'quest_unknown' => 1], 'the row with words and the unknown quest are counted as left out');

[$new, $fill, $left] = source_text_rows('progress', [10 => 'Still at it?', 12 => 'Kept.'], $quests, [12 => 'Kept already.']);
check($new === [['ID' => 10, 'CompletionText' => 'Still at it?', 'VerifiedBuild' => 0]] && $fill === null, 'the progress window writes quest_request_items, and no fill when nothing is blank');
check($left === ['text_known' => 1], 'its row with words is left as it is');

ft_test_done();
