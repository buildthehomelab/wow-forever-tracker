<?php
// What a source said, kept as snapshots (app/snapshots.php): the facts of an evidence array, and a run compared with
// the one before. The database part (snapshot_keep) is the same comparison written to ft_source_facts.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/snapshots.php';

$ev = [
    'drop' => [['npc', 939, 100, 12.3913], ['npc', 939, 100, 9.0], ['go', 7001, 100, 75.0], ['npc', 5, 200, 10.0, 1], ['npc', 0, 100, 5.0]],
    'sell' => [[3413, 200, 0], [3414, 200, 2]],
    'start' => [['npc', 253812, 10]], 'end' => [['go', 180001, 10]],
    'train' => [[3001, 2550, 100, 5, 0, 0, [], 1]],
    'left' => ['x' => 1], 'text' => [[1, 'a line']],
];
$facts = snapshot_facts($ev);
check(array_keys($facts) === ['drop|npc|939|100', 'drop|go|7001|100', 'drop|npc|5|200', 'sell|npc|3413|200', 'sell|npc|3414|200', 'start|npc|253812|10', 'end|go|180001|10', 'train|npc|3001|2550'],
    'one fact a key, a row without an id left out: ' . json_encode(array_keys($facts)));
check($facts['drop|npc|939|100'] === ['drop', 'npc', 939, 100, 12.3913, null], 'the same drop twice: its highest chance');
check($facts['drop|npc|5|200'][5] === '[1]' && $facts['train|npc|3001|2550'] === ['train', 'npc', 3001, 2550, 100.0, '[5,0,0,[],1]'], 'the rest of a row is kept as it is');
check($facts['start|npc|253812|10'][4] === null, 'a quest giver has no value');

// a run against the one before
$open = ['drop|npc|939|100' => [1, 12.3913, null], 'drop|go|7001|100' => [2, 70.0, null], 'sell|npc|9|9' => [3, 0.0, null]];
[$carry, $insert, $added, $changed, $gone] = snapshot_diff($open, $facts);
check($carry === [1], 'the same fact with the same value is carried on');
check($changed === 1 && $added === 6 && $gone === 1 && count($insert) === 7, 'a moved chance is a new row; new facts; a fact no longer said is gone');
[$carry2, , , , $gone2] = snapshot_diff($open, $facts, 'gaps');
check($carry2 === [1, 3] && $gone2 === 0, 'a run asked about the gaps only: what it did not say is carried on, not gone');

ft_test_done();
