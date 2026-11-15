<?php
// Wowhead's pages as evidence (app/wowheadpages.php): what a kept page gives, what is counted and left out, and the
// newest answer of a page winning between the cache that comes with the tracker and the one in data/.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/wowheadpages.php';

$tab = fn(array $rows, ?int $total = null) => ['template' => 'npc', 'rows' => $rows] + ($total ? ['total' => $total] : []);
$many = array_map(fn($i) => ['id' => 5000 + $i, 'count' => 3, 'outof' => 900], range(1, 15));
$items = [
    // a boss drop and a chest, both counted
    100 => ['id' => 100, 'fetched' => 1000, 'status' => 'ok', 'tabs' => [
        'dropped-by' => $tab([['id' => 939, 'count' => 57, 'outof' => 460], ['id' => 978, 'count' => 1, 'outof' => 500], ['id' => 979, 'count' => 4, 'outof' => 9], ['id' => 980], ['id' => 981, 'count' => 50, 'outof' => 40]]),
        'contained-in-object' => $tab([['id' => 7001, 'count' => 30, 'outof' => 40]]),
    ]],
    // vendors: money, money with empty lists, limited stock, a currency, items
    200 => ['id' => 200, 'fetched' => 3000, 'status' => 'ok', 'tabs' => ['sold-by' => $tab([
        ['id' => 3413, 'stock' => -1, 'cost' => [1500]], ['id' => 3414, 'stock' => 2, 'cost' => [1500, [], []]], ['id' => 3415, 'stock' => -1, 'cost' => [0, [[1901, 30]], []]],
        ['id' => 3416, 'stock' => -1, 'cost' => [0, 0, [[20558, 3]]]], ['id' => 3417, 'stock' => -1]])]],
    300 => ['id' => 300, 'fetched' => 2000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab($many)]],                      // a world drop
    301 => ['id' => 301, 'fetched' => 2000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab(array_slice($many, 0, 3), 40)]],  // ... of which the page shows a part
    400 => ['id' => 400, 'fetched' => 2000, 'status' => 'ok', 'tabs' => ['reward-from-q' => ['template' => 'quest', 'rows' => [['id' => 77]]]]],
    500 => ['id' => 500, 'fetched' => 2000, 'status' => 'ok', 'tabs' => ['same-model-as' => $tab([['id' => 1]])]],
    600 => ['id' => 600, 'fetched' => 2000, 'status' => 'missing'],
    // not a gap: its drops are still given (the server's rows are measured again), nothing is counted for it
    700 => ['id' => 700, 'fetched' => 2000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 12, 'count' => 10, 'outof' => 100], ['id' => 13, 'count' => 1, 'outof' => 3]])]],
    701 => ['id' => 701, 'fetched' => 2000, 'status' => 'missing'],
];
$quests = [
    10 => ['id' => 10, 'fetched' => 2500, 'status' => 'ok', 'quick' => ['Level: 12', 'Start: [url=/forever/npc=253812]', 'End: [url=/forever/object=180001]', 'Sharable']],
    11 => ['id' => 11, 'fetched' => 2500, 'status' => 'ok', 'quick' => ['Start: [url=/forever/item=5505]', 'End: [url=/forever/npc=7]']],
    12 => ['id' => 12, 'fetched' => 2500, 'status' => 'ok', 'quick' => ['Start: [url=/forever/npc=1] [url=/forever/npc=2]', 'Starts at level: 5']],
    13 => ['id' => 13, 'fetched' => 2500, 'status' => 'missing'],
];
[$ev, $newest] = wowhead_pages_evidence($items, $quests, array_fill_keys([100, 200, 300, 301, 400, 500, 600], true));

check($newest === 3000, 'the newest page dates the card');
check($ev['drop'] === [['npc', 939, 100, 12.3913], ['npc', 981, 100, 100.0], ['go', 7001, 100, 75.0], ['npc', 12, 700, 10.0]], 'counted drops: creature and chest, the chance is drops over loots');
check($ev['sell'] === [[3413, 200, 0], [3414, 200, 2]], 'vendors paid with money: unlimited and limited stock');
check($ev['start'] === [['npc', 253812, 10], ['npc', 1, 12], ['npc', 2, 12]] && $ev['end'] === [['go', 180001, 10], ['npc', 7, 11]], 'quest givers and enders by number, an object as an object');
check($ev['left'] === ['wowhead_item_unknown' => 1, 'wowhead_no_source' => 1, 'wowhead_only_other_source' => 1, 'wowhead_drop_world' => 18, 'wowhead_drop_few' => 2,
    'wowhead_drop_not_counted' => 1, 'wowhead_vendor_other_cost' => 3, 'wowhead_quest_unknown' => 1, 'wowhead_quest_started_by_item' => 1], 'what was left out is counted for the gap items only: ' . json_encode($ev['left']));
check(!array_filter($ev['drop'], fn($d) => $d[3] > 100), 'no chance above 100 (more drops than loots, several in one corpse, is capped)');

check(wowhead_pages_money_only([1500]) && wowhead_pages_money_only([0, 0, 0]) && wowhead_pages_money_only([5, [], null]), 'money only');
check(!wowhead_pages_money_only([0, [[1, 2]]]) && !wowhead_pages_money_only([0, 0, 0, 5]) && !wowhead_pages_money_only(null), 'a currency, items, or no cost at all: not money only');
check(wowhead_pages_links(['Start: [url=/forever/npc=5/x] and [url=/forever/object=6]', 'Start level: [url=/forever/npc=9]', 'End: [url=/forever/npc=7]'], 'Start') === [['npc', 5], ['object', 6]], 'links of one label only');

// the cache: one page a line, the newer answer wins, a broken line is skipped
$shipped = ft_test_dir(); $local = ft_test_dir();
file_put_contents("$shipped/item.jsonl", json_encode(['id' => 1, 'fetched' => 100, 'status' => 'ok', 'tabs' => []]) . "\n" . json_encode(['id' => 2, 'fetched' => 500, 'status' => 'missing']) . "\n{\"id\": 3, cut sho\n");
file_put_contents("$local/item.jsonl", json_encode(['id' => 1, 'fetched' => 900, 'status' => 'missing']) . "\n" . json_encode(['id' => 2, 'fetched' => 400, 'status' => 'ok', 'tabs' => []]) . "\n\n" . json_encode(['id' => 'x']) . "\n");
$pages = wowhead_pages('item', [$shipped, $local, "$local/none"]);
check(array_keys($pages) === [1, 2] && $pages[1]['status'] === 'missing' && $pages[2]['status'] === 'missing', 'the newer answer of a page wins, whichever folder holds it');
check(wowhead_pages('quest', [$shipped]) === [], 'no file: no page');
check(isset(SOURCES['wowhead']) && source_trust()[1] === 'wowhead' && source_named('Wowhead 2026-11-15') === 'wowhead', 'Wowhead is a source of its own, first after the client');

ft_test_done();
