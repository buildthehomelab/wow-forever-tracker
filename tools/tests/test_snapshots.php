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
check(array_keys($facts) === ['drop|npc|939|100', 'drop|go|7001|100', 'drop|npc|5|200', 'sell|npc|3413|200', 'sell|npc|3414|200', 'start|npc|253812|10', 'end|go|180001|10', 'train|npc|3001|2550', 'text|-|1|' . (crc32('a line') & 0x7fffffff)],
    'one fact a key, a row without an id left out: ' . json_encode(array_keys($facts)));
check($facts['drop|npc|939|100'] === ['drop', 'npc', 939, 100, 12.3913, null], 'the same drop twice: its highest chance');
check($facts['drop|npc|5|200'][5] === '[1]' && $facts['train|npc|3001|2550'] === ['train', 'npc', 3001, 2550, 100.0, '[5,0,0,[],1]'], 'the rest of a row is kept as it is');
check($facts['start|npc|253812|10'][4] === null, 'a quest giver has no value');

// a run against the one before
$open = ['drop|npc|939|100' => [1, 12.3913, null], 'drop|go|7001|100' => [2, 70.0, null], 'sell|npc|9|9' => [3, 0.0, null]];
[$carry, $insert, $added, $changed, $gone] = snapshot_diff($open, $facts);
check($carry === [1], 'the same fact with the same value is carried on');
check($changed === 1 && $added === 7 && $gone === 1 && count($insert) === 8, 'a moved chance is a new row; new facts; a fact no longer said is gone');
[$carry2, , , , $gone2] = snapshot_diff($open, $facts, 'gaps');
check($carry2 === [1, 3] && $gone2 === 0, 'a run asked about the gaps only: what it did not say is carried on, not gone');

// what a snapshot holds gives the evidence back: a card from the database is the card the source would make
$full = $ev + ['service' => [[7, 128]], 'quest_drop' => ['npc:939:100' => true], 'kept' => ['icyveins_kept_levels' => 3]];
$full['text'] = [[77, 'complete', 'Well done, $N.'], [77, 'progress', 'Not yet.']];
$stored = array_map(fn($f) => ['fact' => $f[0], 'kind' => $f[1], 'entity' => (string)$f[2], 'target' => (string)$f[3], 'value' => $f[4] === null ? null : (string)$f[4], 'extra' => $f[5]], array_values(snapshot_facts($full)));
$back = snapshot_rows_evidence($stored, ['left' => ['x' => 1], 'kept' => $full['kept']], 'v1');
check($back['drop'] === [['npc', 939, 100, 12.3913], ['go', 7001, 100, 75.0], ['npc', 5, 200, 10.0, 1]], 'drops back, the most a source said of each, an even share\'s mark kept: ' . json_encode($back['drop']));
check($back['sell'] === [[3413, 200, 0], [3414, 200, 2]] && $back['start'] === [['npc', 253812, 10]] && $back['end'] === [['go', 180001, 10]], 'vendors, quest givers and enders back');
check($back['train'] === [[3001, 2550, 100, 5, 0, 0, [], 1]], 'a trainer\'s row back whole');
check($back['text'] === $full['text'] && $back['service'] === [[7, 128]] && $back['quest_drop'] === ['npc:939:100' => true], 'Icy Veins\' texts, services and quest-only drops back');
check($back['left'] === ['x' => 1] && $back['kept'] === ['icyveins_kept_levels' => 3] && $back['version'] === 'v1', 'the counters and the version back');

ft_test_done();
