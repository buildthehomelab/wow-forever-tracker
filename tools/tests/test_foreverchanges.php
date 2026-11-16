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

$places = foreverchanges_places(['places' => [
    ['npc', 244808, "Aramis\nHammerhand", [['m' => 0, 'x' => 1840, 'y' => 1628.04], ['m' => 0, 'x' => 999999, 'y' => 1], ['m' => '0', 'x' => 1, 'y' => 1], ['x' => 1, 'y' => 1]]],
    ['go', 180001, 'A Book', [['m' => 1, 'x' => 1017.9, 'y' => -3082.1]]],
    ['item', 5, 'x', [['m' => 0, 'x' => 1, 'y' => 1]]], ['npc', 0, 'x', [['m' => 0, 'x' => 1, 'y' => 1]]], ['npc', 7, 'no points', []], ['npc', 8, 'x'],
]]);
check($places === [['npc', 244808, 'Aramis Hammerhand', [['m' => 0, 'x' => 1840.0, 'y' => 1628.0]]], ['go', 180001, 'A Book', [['m' => 1, 'x' => 1017.9, 'y' => -3082.1]]]],
    'reported places: a creature or an object, a map, coordinates that are on a map');
check(foreverchanges_places([]) === [] && foreverchanges_places(['places' => 'x']) === [], 'no places in a result that has none');

$told = foreverchanges_evidence(['ev' => ['text' => [[7, 'complete', 'You have our thanks, $N.$B$BWell done.'], [7, 'progress', "A line\nbreak"], [7, 'accept', 'x'],
    [7, 'complete', 'Hail, ‹name›.'], ['7', 'complete', 'x'], [8, 'complete', '   '], [9, 'complete', str_repeat('a', 9000)], [10, 'progress', 'Still out there.']]]])['text'] ?? [];
check($told === [[7, 'complete', 'You have our thanks, $N.$B$BWell done.'], [10, 'progress', 'Still out there.']],
    'what an NPC says: a quest, one of the two windows, words without a raw line break or a mark of the site left in');

// what the pull reads first: the quests without a giver or an ender, the items other content waits for, then the other
// items players cannot get (all of them: the site's own item ids start low too)
$wanted = foreverchanges_wanted(['items' => [12 => true, 290000 => true, 280000 => true], 'noGiver' => [99001 => true], 'noEnder' => [5000 => true, 99001 => true]],
    [['quest', 'Quest giver: item 280000 not obtainable'], ['toy', 'Item 12 has no source.']]);
check($wanted === ['quests' => [5000, 99001], 'items_first' => [12, 280000], 'items' => [290000]], 'the pull is told the gaps, those other content waits for first');
require_once FT_APP . '/snapshots.php';
check(in_array('foreverchanges', SNAPSHOT_CARDS, true), 'its card can be made again from the database');

ft_test_done();
