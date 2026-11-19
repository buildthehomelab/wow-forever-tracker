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

// a gap item seen dropping once only: that rate is written when nothing better gives it (Blue Suede Shoulders, 1 in 158)
$seen = [800 => ['id' => 800, 'fetched' => 1000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 1831, 'count' => 1, 'outof' => 158], ['id' => 1832, 'count' => 1, 'outof' => 5]])]],
         801 => ['id' => 801, 'fetched' => 1000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 1831, 'count' => 1, 'outof' => 158]]), 'sold-by' => $tab([['id' => 3413, 'stock' => -1, 'cost' => [500]]])]],
         802 => ['id' => 802, 'fetched' => 1000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 1831, 'count' => 1, 'outof' => 158]])]]];
[$evSeen] = wowhead_pages_evidence($seen, [], array_fill_keys([800, 801], true));
check($evSeen['drop'] === [['npc', 1831, 800, 0.6329]], 'a sighting of an item nothing else gives, on ten loots or more; not one a vendor gives, not one that is no gap: ' . json_encode($evSeen['drop']));
check($evSeen['left'] === ['wowhead_drop_few' => 2], 'the sighting on five loots and the one a vendor makes needless are left out: ' . json_encode($evSeen['left']));

// ---- npc and object pages: whole loot tables, vendors, quests
$npcPages = [
    // a creature's own page: its drops counted on each row, what it sells (one way to pay a list), the quests it gives and takes
    ['id' => 250484, 'fetched' => 4000, 'status' => 'ok', 'tabs' => [
        'drops' => ['template' => 'item', 'total' => 995, 'rows' => [['id' => 900, 'count' => 27, 'outof' => 995], ['id' => 901, 'count' => 1, 'outof' => 995], ['id' => 999, 'count' => 50, 'outof' => 995]]],
        'sells' => ['template' => 'item', 'rows' => [['id' => 902, 'avail' => -1, 'cost' => [[23157, [], []]]], ['id' => 903, 'avail' => -1, 'cost' => [[0, [], [[22484, 15]]]]], ['id' => 999, 'avail' => 3, 'cost' => [[5, [], []]]]]],
        'starts' => ['template' => 'quest', 'rows' => [['id' => 5504], ['id' => 5524]]],
        'ends' => ['template' => 'quest', 'rows' => [['id' => 5504]]],
        'skinning' => ['template' => 'item', 'rows' => [['id' => 904, 'count' => 5, 'outof' => 20]]],
    ]],
    // the same drop the item page counted on fewer kills: the page that counted more wins
    ['id' => 939, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 100, 'count' => 120, 'outof' => 1000]]]]],
    ['id' => 1, 'fetched' => 9000, 'status' => 'missing'],
];
// 15 creatures' pages list item 905: a world drop, though no item page was read for it
foreach (range(1, 15) as $i) $npcPages[] = ['id' => 6000 + $i, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 905, 'count' => 30, 'outof' => 100]]]]];
$objectPages = [
    // a chest counts its openings once, as the tab's total; a mining node on each row
    ['id' => 2843, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['contains' => ['template' => 'item', 'total' => 3722, 'rows' => [['id' => 906, 'count' => 607]]],
        'starts' => ['template' => 'quest', 'rows' => [['id' => 7000]]], 'same-model-as' => ['template' => 'object', 'rows' => [['id' => 2849]]]]],
    ['id' => 1731, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['mining' => ['template' => 'item', 'total' => 129848, 'rows' => [['id' => 907, 'count' => 1356, 'outof' => 129848]]]]],
];
$gapsPlus = array_fill_keys([100, 200, 300, 301, 400, 500, 600, 900, 901, 902, 903, 904, 905, 906, 907], true);
$keepItems = $gapsPlus;   // 999: neither a gap nor an import's drop
[$ev2, $newest2] = wowhead_pages_evidence($items, $quests, $gapsPlus, (fn() => yield from $npcPages)(), $objectPages, $keepItems);
check($newest2 === 4000, 'npc and object pages date the card too (a page Wowhead does not have does not)');
$drop2 = array_map(fn($d) => implode(':', $d), $ev2['drop']);
sort($drop2);
check($drop2 === ['go:1731:907:1.0443', 'go:2843:906:16.3084', 'go:7001:100:75', 'npc:12:700:10', 'npc:939:100:12', 'npc:981:100:100'], 'drops of npc and object pages, the better counted of two pages: ' . json_encode($drop2));
check(in_array([250484, 902, 0], $ev2['sell'], true) && !array_filter($ev2['sell'], fn($s) => in_array($s[1], [903, 999], true)), 'an npc page\'s stock: money as the first way to pay; a currency left out, an item worth no row not kept');
check(in_array(['npc', 250484, 5504], $ev2['start'], true) && in_array(['npc', 250484, 5524], $ev2['start'], true) && in_array(['npc', 250484, 5504], $ev2['end'], true) && in_array(['go', 2843, 7000], $ev2['start'], true), 'quests an npc or object page starts and ends');
check(($ev2['left']['wowhead_drop_world'] ?? 0) === 18 + 15 && ($ev2['left']['wowhead_other_loot'] ?? 0) === 1 && ($ev2['left']['wowhead_drop_few'] ?? 0) === 2 && ($ev2['left']['wowhead_vendor_other_cost'] ?? 0) === 4
    && ($ev2['left']['wowhead_drop_item_page_not_read'] ?? 0) === 2, 'left out: 15 creatures\' world drop, skinning, too few, another cost, a gap item whose own page is not read: ' . json_encode($ev2['left']));
// once the item's page is read, the creature's page gives the drop
$withPage = $items + [900 => ['id' => 900, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 250484, 'count' => 20, 'outof' => 900]])]]];
[$ev3] = wowhead_pages_evidence($withPage, [], $gapsPlus, $npcPages, [], $keepItems);
check(in_array(['npc', 250484, 900, 2.7136], $ev3['drop'], true), 'the item page read: the npc page\'s better count is taken');
// a drop that is no gap (an import's row, measured again) needs no item page
[$ev4] = wowhead_pages_evidence([], [], [], [$npcPages[0]], [], [900 => true]);
check($ev4['drop'] === [['npc', 250484, 900, 2.7136]], 'a drop measured again needs no item page');

$slim = wowhead_pages_clean(['kind' => 'npc', 'id' => 5, 'fetched' => 100, 'status' => 'ok', 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 818, 'count' => 27, 'outof' => 995, 'modes' => ['0' => ['count' => 27]], 'flags2' => -5, 'envChange' => ['labels' => []]]]]]]);
check($slim['tabs']['drops']['rows'] === [['id' => 818, 'count' => 27, 'outof' => 995, 'modes' => ['0' => ['count' => 27]], 'flags2' => -5, 'envChange' => ['labels' => []]]], 'every number of a row is kept, the per-mode counts too');

// ---- Classic's pages: drops only, where Forever's pages count too few
$foreverItems = [
    910 => ['id' => 910, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 70, 'count' => 1, 'outof' => 4]])]],   // Forever saw it once
    911 => ['id' => 911, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 71, 'count' => 40, 'outof' => 400]])]], // counted on Forever
    912 => ['id' => 912, 'fetched' => 4000, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab($many)]],                                       // a world drop by Forever's page
];
$classicNpcs = [
    ['id' => 70, 'fetched' => 5000, 'status' => 'ok', 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 910, 'count' => 120, 'outof' => 3000], ['id' => 913, 'count' => 9, 'outof' => 3000]]],
        'sells' => ['template' => 'item', 'rows' => [['id' => 910, 'avail' => -1, 'cost' => [[100, [], []]]]]], 'starts' => ['template' => 'quest', 'rows' => [['id' => 50]]]]],
    ['id' => 71, 'fetched' => 5000, 'status' => 'ok', 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 911, 'count' => 300, 'outof' => 3000], ['id' => 912, 'count' => 90, 'outof' => 3000]]]]],
];
$classicObjects = [['id' => 2843, 'fetched' => 5000, 'status' => 'ok', 'tabs' => ['contains' => ['template' => 'item', 'total' => 900, 'rows' => [['id' => 914, 'count' => 90]]]]]];
$classicGaps = array_fill_keys([910, 911, 912, 913, 914], true);
[$foreverEv] = wowhead_pages_evidence($foreverItems, [], $classicGaps);
[$cev, $cnewest] = wowhead_pages_classic_evidence($foreverEv, $foreverItems, $classicGaps, $classicNpcs, $classicObjects, $classicGaps);
check($cnewest === 5000, 'Classic pages date their card');
check($cev['drop'] === [['npc', 70, 910, 4.0], ['go', 2843, 914, 10.0]], 'Classic gives the drops Forever counts too few of, and a chest\'s: ' . json_encode($cev['drop']));
check($cev['sell'] === [] && $cev['start'] === [] && $cev['end'] === [], 'no vendor and no quest from Classic: Forever moved them');
check(($cev['left']['wowhead_classic_forever_counted'] ?? 0) === 1 && ($cev['left']['wowhead_drop_world'] ?? 0) === 1 && ($cev['left']['wowhead_drop_item_page_not_read'] ?? 0) === 1 && !isset($cev['left']['wowhead_vendor_other_cost']),
    'left out: counted on Forever, a world drop by Forever\'s item page, an item whose Forever page is not read: ' . json_encode($cev['left']));
check(source_named('Wowhead Classic 2026-11-15') === 'wowheadclassic' && source_named('Wowhead 2026-11-15') === 'wowhead' && source_named('wowhead: 27 of 995 kills') === 'wowhead', 'Wowhead Classic is not Wowhead in a row\'s comment');
$trust = source_trust('');
check(array_search('wowheadclassic', $trust, true) > array_search('atlasloot', $trust, true) && array_search('wowheadclassic', $trust, true) < array_search('classicdb', $trust, true)
    && source_may_change('wowheadclassic', 'wowhead', $trust) === 'trusted' && source_may_change('wowheadclassic', 'classicdb', $trust) === 'yes', 'Classic\'s counts rank after every Forever recording, before the original game\'s database');

// ---- Season of Discovery items Forever kept: Classic's item page where Forever's names no source
$sb = ft_test_dir() . '/era.json';
file_put_contents($sb, json_encode(['build' => 'x', 'tables' => ['ItemSparse' => [[1, 25000], [226400, 226410], [230000, 230005]]]]));
check(wowhead_pages_season_items([5000, 226404, 226411, 230001, 250000], $sb) === [226404 => true, 230001 => true], 'Season items: from 190000 up and in the Classic Era client');
$sForever = [
    226404 => ['id' => 226404, 'fetched' => 1, 'status' => 'ok', 'tabs' => []],                                                            // Forever knows no source
    230001 => ['id' => 230001, 'fetched' => 1, 'status' => 'ok', 'tabs' => ['dropped-by' => $tab([['id' => 9, 'count' => 5, 'outof' => 50]])]],   // Forever has one
];
check(wowhead_pages_season_queue([250000, 226404, 230001, 230002, 230003], $sForever, [230003 => true], $sb) === [226404, 230002],
    'the Classic pages queued: Season items whose Forever page names no source or is not read, not read on Classic yet');
$js3 = wowhead_pages_crawler(['item' => [226404, 250000], 'blocking' => 1, 'classic/item' => [226404, 230002], 'classicBlocking' => 1]);
check(str_contains($js3, 'await WHC.prioritize(["classic/item:226404"], "gap");') && str_contains($js3, 'await WHC.prioritize(["classic/item:230002"], "gapOther");')
    && strpos($js3, '"item:226404"') < strpos($js3, '"classic/item:226404"'), 'a Season item\'s Classic page, in its tier, after its Forever page');
$bosses = array_map(fn($i) => ['id' => 600 + $i, 'count' => 40, 'outof' => 200], range(1, 20));
$sClassic = [
    // a currency twenty bosses drop: a row each
    226404 => ['id' => 226404, 'fetched' => 6000, 'status' => 'ok', 'branch' => 'classic', 'tabs' => ['dropped-by' => $tab($bosses, 133),
        'currency-for' => ['template' => 'item', 'rows' => [['id' => 226500]]], 'sold-by' => $tab([['id' => 14921, 'stock' => -1, 'cost' => [100]]])]],
    // a Season world drop: still one
    230002 => ['id' => 230002, 'fetched' => 6000, 'status' => 'ok', 'branch' => 'classic', 'tabs' => ['dropped-by' => $tab($bosses, 133)]],
    230001 => ['id' => 230001, 'fetched' => 6000, 'status' => 'ok', 'branch' => 'classic', 'tabs' => ['dropped-by' => $tab([['id' => 8, 'count' => 50, 'outof' => 100]])]],
    5000 => ['id' => 5000, 'fetched' => 6000, 'status' => 'ok', 'branch' => 'classic', 'tabs' => ['dropped-by' => $tab([['id' => 8, 'count' => 50, 'outof' => 100]])]],
];
$sTaken = wowhead_pages_classic_items($sForever, $sClassic, $sb);
check(array_keys($sTaken) === [226404, 230002], 'Classic item pages taken: Season items whose Forever page names no source');
$sGaps = array_fill_keys([226404, 230001, 230002], true);
[$sev] = wowhead_pages_classic_evidence([], $sForever, $sGaps, [], [], $sGaps, $sTaken);
$sDrops = array_values(array_filter($sev['drop'], fn($d) => $d[2] === 226404));
check(count($sDrops) === 20 && $sDrops[0] === ['npc', 601, 226404, 20.0] && !array_filter($sev['drop'], fn($d) => $d[2] === 230002),
    'a Season currency: each boss a row of its own; a Season world drop stays out: ' . json_encode(array_slice($sev['drop'], 0, 2)));
check($sev['sell'] === [] && ($sev['left']['wowhead_classic_season_vendor'] ?? 0) === 1 && ($sev['left']['wowhead_drop_world'] ?? 0) === 20,
    'no vendor from Classic\'s Season item pages, counted: ' . json_encode($sev['left']));

$cnt = ft_test_dir();
file_put_contents("$cnt/npc.jsonl", "{\"id\":1}\n{\"id\":2}\n");
check(wowhead_pages_count('npc', [$cnt]) === 2 && wowhead_pages_count('classic-npc', [$cnt]) === 0, 'a shelf counted by its lines');

// the ids Wowhead's whole lists name, the cut ones left out
$ld = ft_test_dir();
file_put_contents("$ld/forever-list.jsonl", implode("\n", array_map('json_encode', [
    ['kind' => 'list', 'query' => 'npcs?filter=37:37;2:4;1:100', 'fetched' => 1, 'status' => 'ok', 'rows' => [['id' => 7], ['id' => 9]], 'found' => 2, 'truncated' => false],
    ['kind' => 'list', 'query' => 'npcs', 'fetched' => 1, 'status' => 'ok', 'rows' => [['id' => 500]], 'found' => 15596, 'truncated' => true],
    ['kind' => 'list', 'query' => 'npcsx?filter=1', 'fetched' => 1, 'status' => 'ok', 'rows' => [['id' => 11]], 'found' => 1, 'truncated' => false],
    ['kind' => 'list', 'query' => 'objects?filter=15:15;2:4;1:100', 'fetched' => 1, 'status' => 'ok', 'rows' => [['id' => 31]], 'found' => 1, 'truncated' => false],
])) . "\n");
check(wowhead_pages_listed('npcs', 'forever', [$ld]) === [7 => true, 9 => true] && wowhead_pages_listed('objects', 'forever', [$ld]) === [31 => true] && wowhead_pages_listed('npcs', 'classic', [$ld]) === null,
    'the ids whole list pages name; a cut list, another list, another branch not');
$js2 = wowhead_pages_crawler(['item' => [3], 'quest' => [], 'npc' => [7, 9], 'object' => [31]]);
check(str_contains($js2, 'await WHC.prioritize(["npc:7","npc:9"], "missing");') && str_contains($js2, 'await WHC.prioritize(["object:31"], "missing");') && !str_contains(strstr($js2, '// ---- queued by the tracker'), 'WHC.add('), 'creatures and objects with missing data are worth tier "missing"');

// a linked crawl's pages: added at the end, nothing rewritten, the newest answer still wins
$ap = ft_test_dir();
file_put_contents("$ap/item.jsonl", json_encode(['id' => 5, 'fetched' => 100, 'v' => 1, 'status' => 'missing']) . "\n");
$before = file_get_contents("$ap/item.jsonl");
$got = wowhead_pages_append([json_encode(['kind' => 'item', 'id' => 5, 'fetched' => 200, 'v' => 1, 'status' => 'ok', 'quick' => [], 'tabs' => []]),
    json_encode(['kind' => 'npc', 'id' => 7, 'fetched' => 200, 'v' => 1, 'status' => 'ok', 'quick' => [], 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 5, 'count' => 3, 'outof' => 30]]]]]),
    json_encode(['kind' => 'npc', 'id' => 8, 'fetched' => 200, 'status' => 'ok', 'branch' => 'classic', 'tabs' => []]),
    '{not json', json_encode(['kind' => 'mount', 'id' => 1, 'fetched' => 1, 'status' => 'ok']), 42], $ap);
check($got === ['pages' => 3, 'not_a_page' => 3], 'pages kept, lines that are no page counted: ' . json_encode($got));
check(str_starts_with(file_get_contents("$ap/item.jsonl"), $before) && wowhead_pages('item', [$ap])[5]['status'] === 'ok', 'added at the end; the newer answer wins when read');
check(wowhead_pages('npc', [$ap])[7]['tabs']['drops']['rows'][0]['outof'] === 30 && isset(wowhead_pages('classic-npc', [$ap])[8]), 'each page on its own shelf, a Classic one apart');
check(wowhead_pages_append([], $ap) === ['pages' => 0, 'not_a_page' => 0], 'nothing sent, nothing written');

// The Forge › Crawl: in the site's layout (its script makes the button work; the layout needs the database, which these
// tests do not have, so the page's source is read), with the line to run in the Wowhead tab
$crawlPage = (string)file_get_contents(FT_APP . '/pages/admin/crawl.php');
check(str_contains($crawlPage, 'page_start(') && str_contains($crawlPage, 'page_end()') && str_contains($crawlPage, 'data-crawl-open') && str_contains($crawlPage, '(0, eval)(JSON.parse(window.name).src)'),
    'the Crawl page: in the layout, the button and the line to run');
check(ft_test_request('/admin/crawl', "[site]\npublic = 1\n")[0] === 303, 'not for visitors');
// the push endpoint: past the private site's gate (it has its own key), POST only
[$st, $out] = ft_test_request('/api/wowhead-push', "[site]\npublic = 0\n[wowhead]\npush_token = \"0123456789abcdef0123\"\n");
check($st === 405 && str_contains($out, 'POST only'), 'the push endpoint answers on a private site, to a POST only');

// the cache read a line at a time: the newest answer of each page, once
$a = ft_test_dir(); $b = ft_test_dir();
file_put_contents("$a/npc.jsonl", '{"id":1,"fetched":100,"status":"ok","tabs":{}}' . "\n" . '{"id":2,"fetched":500,"status":"missing"}' . "\n{cut\n");
file_put_contents("$b/npc.jsonl", '{"id":1,"fetched":900,"status":"missing"}' . "\n" . '{"id":2,"fetched":500,"status":"missing"}' . "\n" . '{"status":"ok","id":3,"fetched":7}' . "\n");
$streamed = iterator_to_array(wowhead_pages_each('npc', [$a, $b, "$b/none"]), false);
check(array_map(fn($r) => [$r['id'], $r['fetched']], $streamed) === [[2, 500], [1, 900], [3, 7]], 'streamed: the newer answer wins, the same answer twice is read once: ' . json_encode($streamed));

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

// ---- the round trip with the browser crawler
$waiting = [['quest', 'item 270001 not obtainable; item 3000 not obtainable'], ['quest', 'Quest giver: item 250001 (not obtainable)'],
    ['recipe', 'Recipe exists but cannot be obtained: 260001, 260002'], ['recipe', 'Taught by item 260003, which players cannot get.'],
    ['mount', 'Item exists but cannot be obtained: 8633'], ['toy', 'Item 255000 has no source.'], ['spell', 'Taught by item 9126, 0, which players cannot get.'],
    ['quest', 'No quest text']];
$order = wowhead_pages_order(array_fill_keys([5559, 250001, 250009, 190000], true), $waiting, array_fill_keys([902, 901], true));
check($order['item'] === [3000, 8633, 9126, 250001, 255000, 260001, 260002, 260003, 270001, 190000, 250009], 'what other content waits for first, then the gap items from 190000 up: ' . json_encode($order['item']));
check($order['quest'] === [901, 902] && $order['blocking'] === 9, 'the quests without a giver or an ender; 9 items other content waits for');
$order = wowhead_pages_order(array_fill_keys([250009], true), $waiting, [901 => true], ['item' => [3000 => true, 250009 => true], 'quest' => [901 => true]], 0);
check(!in_array(3000, $order['item'], true) && !in_array(250009, $order['item'], true) && $order['quest'] === [], 'pages the cache has are not read again');

$line = fn(array $r) => json_encode($r + ['kind' => 'item', 'v' => 1, 'fetched' => 1700000000, 'status' => 'ok']);
check(wowhead_pages_clean(json_decode($line(['id' => 5, 'quick' => ['Level: 3', str_repeat('x', 301)], 'tabs' => ['sold-by' => ['template' => 'npc', 'rows' => [['id' => 1, 'name' => 'A vendor'], ['id' => 2, 'cost' => [5]]]], 'bad tab!' => ['rows' => []]]]), true))
    === ['id' => 5, 'fetched' => 1700000000, 'v' => 1, 'status' => 'ok', 'quick' => ['Level: 3'], 'tabs' => ['sold-by' => ['template' => 'npc', 'rows' => [['id' => 2, 'cost' => [5]]]]]], 'a row with text is dropped, so is a line too long');
foreach ([['status' => 'blocked'], ['kind' => 'mount'], ['id' => 0], ['id' => '5'], ['fetched' => 0], ['fetched' => time() + 864000], ['tabs' => [[1]]]] as $bad) {
    check(wowhead_pages_clean(json_decode(json_encode($bad + ['kind' => 'item', 'id' => 5, 'v' => 1, 'fetched' => 1700000000, 'status' => 'ok', 'tabs' => []]), true)) === null, 'not a page: ' . json_encode($bad));
}

$dir = ft_test_dir() . '/pages';
$counts = wowhead_pages_merge(implode("\n", [$line(['id' => 30, 'tabs' => []]), $line(['id' => 4, 'tabs' => []]), '{cut', $line(['id' => 7, 'kind' => 'quest', 'quick' => ['Start: [url=/forever/npc=1]']])]), $dir);
check($counts === ['new' => 3, 'newer' => 0, 'older' => 0, 'not_a_page' => 1], 'merge: three pages and a broken line');
$counts = wowhead_pages_merge(implode("\n", [$line(['id' => 30, 'fetched' => 1600000000, 'status' => 'missing']), $line(['id' => 4, 'fetched' => 1790000000, 'status' => 'missing'])]), $dir);
check($counts === ['new' => 0, 'newer' => 1, 'older' => 1, 'not_a_page' => 0], 'merge: the newer answer of a page wins');
check(array_keys(wowhead_pages('item', [$dir])) === [4, 30] && wowhead_pages('item', [$dir])[4]['status'] === 'missing' && wowhead_pages('item', [$dir])[30]['status'] === 'ok', 'the kept file: sorted by id, the right answers');
check(file_get_contents("$dir/item.jsonl") === '{"id":4,"fetched":1790000000,"v":1,"status":"missing"}' . "\n" . '{"id":30,"fetched":1700000000,"v":1,"status":"ok","quick":[],"tabs":{}}' . "\n", 'the file is one page a line, an empty tab list written as an object');
check(wowhead_pages('quest', [$dir])[7]['quick'] === ['Start: [url=/forever/npc=1]'], 'each kind in its own file');

$list = ['kind' => 'list', 'query' => 'npcs?filter=37:37;2:4;1:20000', 'fetched' => 1700000000, 'v' => 2, 'status' => 'ok', 'found' => 2, 'truncated' => false, 'cr' => 37,
    'rows' => [['id' => 7, 'minlevel' => 3], ['id' => 9, 'name' => 'text'], ['minlevel' => 1]]];
$lines = array_map('json_encode', [
    ['kind' => 'npc', 'id' => 7, 'fetched' => 1700000000, 'v' => 1, 'status' => 'ok', 'branch' => 'classic', 'tabs' => []],
    $list, $list + ['branch' => 'classic'], ['branch' => 'retail'] + $list, ['query' => 'npcs?filter="x"'] + $list,
]);
$m = wowhead_pages_merge(implode("\n", $lines), $dir);
check($m['new'] === 3 && $m['not_a_page'] === 2, 'Classic pages and lists are kept, another branch or a query that is no filter is not');
check(wowhead_pages('classic-npc', [$dir])[7]['branch'] === 'classic' && !isset(wowhead_pages('npc', [$dir])[7]), 'a Classic page on a shelf of its own, apart from Forever\'s');
$kept = wowhead_pages('forever-list', [$dir])['npcs?filter=37:37;2:4;1:20000'] ?? [];
check(($kept['rows'] ?? null) === [['id' => 7, 'minlevel' => 3]] && !isset($kept['branch']) && isset(wowhead_pages('classic-list', [$dir])['npcs?filter=37:37;2:4;1:20000']), 'a list by its query, rows with text or no id dropped');

$js = wowhead_pages_crawler(['item' => [3, 4, 5], 'quest' => [7], 'blocking' => 2]);
check(str_contains($js, 'await WHC.prioritize(["quest:7"], "gap");') && str_contains($js, 'await WHC.prioritize(["item:3","item:4"], "gap");') && str_contains($js, 'await WHC.prioritize(["item:5"], "gapOther");')
    && str_contains($js, 'WHC.start();') && str_starts_with($js, '// Wowhead page crawler'), 'the crawler download: the script, then its pages with what each is worth, then start');

check(str_contains(wowhead_pages_crawler(['item' => [3]], true), "await WHC.full();\n  WHC.start();") && !str_contains($js, 'WHC.full'), 'the full crawl download also starts the whole database');

// the Chrome extension: a key of its own, made once; the push and crawler endpoints take it as well as push_token
$kd = ft_test_dir();
check(wowhead_extension_key(false, "$kd/x.key") === '' && !is_file("$kd/x.key"), 'no extension key until one is asked for');
$xk = wowhead_extension_key(true, "$kd/x.key");
check(strlen($xk) === 40 && wowhead_extension_key(true, "$kd/x.key") === $xk, 'the extension key: made once, then the same');
check(wowhead_push_allowed($xk, "$kd/x.key") && !wowhead_push_allowed('', "$kd/x.key") && !wowhead_push_allowed(substr($xk, 1), "$kd/x.key") && !wowhead_push_allowed('', "$kd/none.key"),
    'the extension key opens the push, nothing else does');
// its zip: the extension's files, and a config.json with this tracker's address and the key (never the example)
$zipFile = "$kd/x.zip";
file_put_contents($zipFile, wowhead_extension_zip('http://tracker.example:8090', $xk));
$zx = new ZipArchive();
$zx->open($zipFile);
$names = [];
for ($i = 0; $i < $zx->numFiles; $i++) $names[] = $zx->getNameIndex($i);
sort($names);
$zconf = json_decode((string)$zx->getFromName('wowhead-crawl/config.json'), true);
$manifest = json_decode((string)$zx->getFromName('wowhead-crawl/manifest.json'), true);
check($names === ['wowhead-crawl/background.js', 'wowhead-crawl/bridge.js', 'wowhead-crawl/config.json', 'wowhead-crawl/manifest.json', 'wowhead-crawl/popup.html', 'wowhead-crawl/popup.js'],
    'the extension zip: its files and config.json only: ' . implode(' ', $names));
check($zconf === ['tracker' => 'http://tracker.example:8090', 'key' => $xk], 'config.json: the tracker and the key');
check(($manifest['manifest_version'] ?? 0) === 3 && ($manifest['background']['service_worker'] ?? '') === 'background.js' && in_array('https://www.wowhead.com/*', $manifest['host_permissions'] ?? [], true),
    'the manifest: version 3, the worker, Wowhead');
$bg = (string)$zx->getFromName('wowhead-crawl/background.js');
check(str_contains($bg, "'/api/wowhead-crawler'") && str_contains($bg, "'/api/wowhead-push'") && str_contains($bg, "world: 'MAIN'") && str_contains($bg, '__whcExtension = true'),
    'the worker loads the tracker\'s crawler into the page, flagged, and sends to the push endpoint');
$zx->close();
$crawler = (string)file_get_contents(FT_ROOT . '/tools/wowhead-pages/crawler.js');
check(str_contains($crawler, 'root.__whcExtension') && str_contains($crawler, 'to.postMessage({ whc: \'pages\''), 'the crawler sends to its own tab when the extension loaded it');
$crawlSrc = (string)file_get_contents(FT_APP . '/pages/admin/crawl.php');
check(str_contains($crawlSrc, 'data-scribe="wowhead_extension"'), 'the Crawl page offers the extension');
check(str_contains($crawlSrc, "'forever-list'") && str_contains($crawlSrc, 'Last page received'), 'the Crawl page counts list pages and says when a page last came');
// the crawler endpoint: answered before the private site's gate, GET only, and only with a key
[$st, $out] = ft_test_request('/api/wowhead-crawler', "[site]\npublic = 0\n[wowhead]\npush_token = \"0123456789abcdef0123\"\n");
check($st === 403 && str_contains($out, 'not allowed'), 'the crawler endpoint: past the gate, refused without a key: ' . $st);

// ---- the items Later only because their page named no source are read again (wowhead_pages_queue)
$listed = [1 => ['key' => 'first-raids'], 2 => ['key' => 'not-out', 'wowhead_no_source' => [263505, '5', 0]], 3 => ['key' => 'open', 'wowhead_no_source' => [7]]];
check(wowhead_pages_unsourced_later($listed, [1, 2]) === [263505 => true, 5 => true], 'a closed phase\'s items without a source on Wowhead go back in the crawl; an open phase\'s do not');
check(wowhead_pages_unsourced_later($listed, []) === [], 'every phase open: nothing');

ft_test_done();
