<?php
// What the website accepts from the players' reports (tools/tracker.py reports -> app/sources.php): rows of the right
// shape and nothing else, whatever the file says.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$ev = foreverchanges_evidence(['ev' => [
    'start' => [['npc', 100, 7], ['go', 9000, 7], ['item', 5, 7], ['npc', '100 OR 1=1', 7], ['npc', 0, 7], ['npc', 100]],
    'end' => [['npc', 101, 7]],
    'sell' => [[102, 159, 0], [102, 159, -1], ['102', 159, 0], [102, 159]],
    'drop' => [['npc', 103, 159, 7.5], ['npc', 103, 160, 100], ['npc', 103, 161, 250], ['npc', 103, 162, 0], ['go', 103, 163, 5], ['npc', 103, 164, '5']],
    'train' => [[1, 2, 3, 4, 5, 6, null, 1]],
], 'left' => ['report_name_unknown' => 3, 'report_not_spawned' => 0, 'DROP TABLE x' => 1, 'quest_same' => 9]]);

check($ev['start'] === [['npc', 100, 7], ['go', 9000, 7]] && $ev['end'] === [['npc', 101, 7]], 'givers and enders: a creature or an object, whole numbers');
check($ev['sell'] === [[102, 159, 0]], 'vendors: creature, item, a stock that is not negative');
check($ev['drop'] === [['npc', 103, 159, 7.5], ['npc', 103, 160, 100.0]], 'drops: a creature\'s, with a chance above 0 and up to 100');
check($ev['train'] === [], 'nothing it does not make: no trainer rows');
check($ev['left'] === ['report_name_unknown' => 3], 'only its own reasons are counted');
check(foreverchanges_evidence([])['start'] === [] && foreverchanges_evidence(['ev' => 'x'])['sell'] === [], 'a result that is no result gives nothing');
check(isset(SOURCES['foreverchanges'], SOURCE_MARKS['foreverchanges']) && source_named('ForeverChanges 2026-11-14') === 'foreverchanges', 'the source is known by its name in a row\'s comment');
$trust = source_trust('');
check(array_search('foreverchanges', $trust, true) > array_search('icyveins', $trust, true) && array_search('foreverchanges', $trust, true) < array_search('eglink', $trust, true) && $trust[0] === 'client', 'trusted after Icy Veins, before the rest; the client first');

ft_test_done();
