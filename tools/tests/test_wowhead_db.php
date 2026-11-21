<?php
// Wowhead in the answers table (app/wowheaddb.php, app/sourceanswers.php): every tooltip and page as a row, the hash
// that says when Wowhead changed something, and the due times the crawl's queue is given. With
// FT_TEST_MYSQL=host:port:root:password:db the rows are also written to that MySQL (the table ft_source_answers is made
// there and dropped again).
require __DIR__ . '/helpers.php';
$mysql = getenv('FT_TEST_MYSQL');
if ($mysql) {
    [$host, $port, $user, $password, $database] = explode(':', $mysql, 5);
    ft_test_boot("[database]\nhost = \"$host\"\nport = $port\nuser = \"$user\"\npassword = \"$password\"\ntracker = \"$database\"\n[wowhead]\nrefresh_days = 30\nrecheck_days = 7\n");
} else ft_test_boot("[wowhead]\nrefresh_days = 30\nrecheck_days = 7\n");
require FT_APP . '/wowheaddb.php';

// ---------------------------------------------------------------- rows
$tip = wowhead_db_tooltip_row('npc', 1365, ['name' => 'Goli Krumn', 'tooltip' => '<td>Level 30</td>', 'map' => ['zone' => 1537], 'fetched' => 1000], 'forever');
check($tip['source'] === 'wowhead' && $tip['feed'] === 'tooltip' && $tip['ref'] === '1365' && $tip['id'] === 1365 && $tip['name'] === 'Goli Krumn' && $tip['status'] === 'found', 'a tooltip: its id, name and status');
check(!str_contains($tip['data'], 'fetched') && str_contains($tip['data'], 'Level 30'), 'its data is the whole answer but the time it was fetched');
$same = wowhead_db_tooltip_row('npc', 1365, ['map' => ['zone' => 1537], 'name' => 'Goli Krumn', 'fetched' => 2000], 'forever');
check($same['hash'] === $tip['hash'], "a creature's tooltip text and the key order are not part of the hash");
$moved = wowhead_db_tooltip_row('npc', 1365, ['name' => 'Goli Krumn', 'map' => ['zone' => 1519], 'fetched' => 2000], 'forever');
check($moved['hash'] !== $tip['hash'], 'a different map is');
$item = wowhead_db_tooltip_row('item', 5, ['name' => 'A', 'tooltip' => 'x', 'fetched' => 1], 'forever');
check($item['hash'] !== wowhead_db_tooltip_row('item', 5, ['name' => 'A', 'tooltip' => 'y', 'fetched' => 1], 'forever')['hash'], "an item's tooltip text is");
$gone = wowhead_db_tooltip_row('quest', 9, ['missing' => true, 'fetched' => 5], 'forever');
check($gone['status'] === 'missing' && $gone['name'] === null, 'Wowhead does not know it: missing');
check(wowhead_db_tooltip_row('npc', 0, ['fetched' => 1]) === null && wowhead_db_tooltip_row('npc', 3, []) === null, 'no id or no time: no row');

$line = ['kind' => 'npc', 'id' => 939, 'fetched' => time() - 60, 'v' => 3, 'status' => 'ok', 'quick' => ['Level: 37'],
    'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 100, 'count' => 5, 'outof' => 50, 'name' => 'Kurzen Sword']]]],
    'model' => [1234], 'full' => ['name' => 'Kurzen Elite', 'tabs' => ['drops' => ['template' => 'item', 'rows' => [['id' => 100, 'name' => 'Kurzen Sword']]]]]];
[$page] = wowhead_db_page_rows([$line]);
check($page['source'] === 'wowhead' && $page['feed'] === 'page' && $page['kind'] === 'npc' && $page['id'] === 939 && $page['name'] === 'Kurzen Elite' && $page['version'] === '3', 'a crawler line: kind, id, the name its whole page gives');
check(!str_contains($page['data'], 'Kurzen') && str_contains($page['whole'], 'Kurzen Sword'), 'data is the cache record (numbers only), whole the whole page');
$older = $line; unset($older['full']); $older['v'] = 2;
[$numbers] = wowhead_db_page_rows([$older]);
check($numbers['hash'] === $page['hash'] && $numbers['whole'] === null && $numbers['name'] === null, 'a line without the whole page: same facts hash, no page');
$named = wowhead_db_page_row(wowhead_pages_clean($older) + ['kind' => 'npc'], null, fn($kind, $id) => "$kind $id");
check($named['name'] === 'npc 939', 'a page without a name of its own takes its tooltip name');
$list = ['kind' => 'list', 'query' => 'npcs?filter=1:2', 'fetched' => 50, 'status' => 'ok', 'rows' => [['id' => 1]], 'branch' => 'classic'];
[$listRow] = wowhead_db_page_rows([$list]);
check($listRow['kind'] === 'list' && $listRow['ref'] === 'npcs?filter=1:2' && $listRow['id'] === null && $listRow['branch'] === 'classic', 'a list page: its query is the ref');
check(wowhead_db_page_rows([['kind' => 'npc', 'id' => 3, 'status' => 'blocked', 'fetched' => 5], 'nonsense']) === [], 'what is no page is left out');
check(wowhead_db_shelf_kind('item') === ['forever', 'item'] && wowhead_db_shelf_kind('classic-npc') === ['classic', 'npc'] && wowhead_db_shelf_kind('forever-list') === ['forever', 'list']
    && wowhead_db_shelf_kind('whc-batch') === [null, null], 'the shelves and what they hold');
check(source_answers_hash(['b' => 1, 'a' => [2, ['d' => 1, 'c' => 2]]]) === source_answers_hash(['a' => [2, ['c' => 2, 'd' => 1]], 'b' => 1]), 'the hash does not depend on key order');

// ---------------------------------------------------------------- the due times
$due = source_answers_due_case('wowhead', ['refresh_days' => 30, 'recheck_days' => 7, 'epoch' => 0]);
check(str_contains($due, "WHEN status = 'missing' THEN fetched_at + INTERVAL 604800 SECOND") && str_contains($due, '2592000.000000 * (0.75 + MOD(') && !str_contains($due, 'FROM_UNIXTIME'), 'due: missing after recheck_days, found after refresh_days spread by id');
check(str_contains(source_answers_due_case('wowhead', ['refresh_days' => 0, 'recheck_days' => 7, 'epoch' => 0]), 'ELSE NULL'), 'refresh_days 0: an answer is never due again');
check(str_contains(source_answers_due_case('wowhead', ['refresh_days' => 30, 'recheck_days' => 7, 'epoch' => 1700000000]), 'WHEN fetched_at < FROM_UNIXTIME(1700000000) THEN fetched_at'), '"ask every source again": due at once');

if (!$mysql) { echo "(FT_TEST_MYSQL not set: the rows are not written to MySQL)\n"; ft_test_done(); }

// ---------------------------------------------------------------- in MySQL
$link = new mysqli($host, $user, $password, $database, (int)$port);
$link->set_charset('utf8mb4');
$link->query('DROP TABLE IF EXISTS ft_source_answers');
$link->query('DROP TABLE IF EXISTS ft_wowhead');
$get = fn(string $feed, string $kind, string $ref) => $link->query("SELECT *, UNIX_TIMESTAMP(fetched_at) f, UNIX_TIMESTAMP(changed_at) c, UNIX_TIMESTAMP(first_seen) s, UNIX_TIMESTAMP(due_at) d FROM ft_source_answers WHERE source = 'wowhead' AND feed = '$feed' AND kind = '$kind' AND ref = '$ref'")->fetch_assoc();
$t = time() - 100 * 86400;
source_answers_put([wowhead_db_tooltip_row('npc', 1365, ['name' => 'Goli Krumn', 'map' => ['zone' => 1537], 'fetched' => $t], 'forever')], $link);
$r = $get('tooltip', 'npc', '1365');
check($r && (int)$r['f'] === $t && (int)$r['c'] === $t && (int)$r['s'] === $t, 'a new row: fetched, first seen and changed at its time');
$spread = 0.75 + (1365 * 2654435761 % 1000) / 2000;
check(abs((int)$r['d'] - ($t + 30 * 86400 * $spread)) <= 1, 'due after refresh_days, spread by id as wowhead_stale() spreads it');
check(wowhead_stale($t, false, 1365, (int)$r['d'] + 2, 0, 30, 7) && !wowhead_stale($t, false, 1365, (int)$r['d'] - 2, 0, 30, 7), 'the same moment wowhead_stale() says');
source_answers_put([wowhead_db_tooltip_row('npc', 1365, ['name' => 'Goli Krumn', 'map' => ['zone' => 1537], 'tooltip' => 'now kept', 'fetched' => $t + 10], 'forever')], $link);
$r = $get('tooltip', 'npc', '1365');
check((int)$r['f'] === $t + 10 && (int)$r['c'] === $t && str_contains($r['data'], 'now kept'), 'asked again, nothing changed: fetched moves, changed_at stays');
source_answers_put([wowhead_db_tooltip_row('npc', 1365, ['name' => 'Goli Krumn', 'map' => ['zone' => 1519], 'fetched' => $t + 20], 'forever')], $link);
$r = $get('tooltip', 'npc', '1365');
check((int)$r['c'] === $t + 20, 'the map changed: changed_at moves to that answer');
source_answers_put([wowhead_db_tooltip_row('npc', 1365, ['name' => 'Old', 'map' => ['zone' => 1], 'fetched' => $t + 5], 'forever')], $link);
$r = $get('tooltip', 'npc', '1365');
check((int)$r['f'] === $t + 20 && $r['name'] === 'Goli Krumn' && str_contains($r['data'], '1519'), 'an older answer changes nothing');

// pages: the whole page stays when a numbers-only answer comes later; changed_at follows the facts
$now = time();
$line['fetched'] = $now - 300;
source_answers_put(wowhead_db_page_rows([$line]), $link);
$r = $get('page', 'npc', '939');
check($r['name'] === 'Kurzen Elite' && str_contains((string)$r['whole'], 'Kurzen Sword') && $r['whole_at'] !== null, 'a page with its whole page');
$older['fetched'] = $now - 200;
source_answers_put(wowhead_db_page_rows([$older]), $link);
$r = $get('page', 'npc', '939');
check((int)$r['f'] === $now - 200 && (int)$r['c'] === $now - 300 && str_contains((string)$r['whole'], 'Kurzen Sword') && $r['name'] === 'Kurzen Elite', 'a later numbers-only answer: the whole page and its name stay, nothing changed');
$renamed = $line; $renamed['fetched'] = $now - 100; $renamed['full']['name'] = 'Kurzen Captain';
source_answers_put(wowhead_db_page_rows([$renamed]), $link);
$r = $get('page', 'npc', '939');
check((int)$r['c'] === $now - 100 && $r['name'] === 'Kurzen Captain', 'the whole page changed (a new name): changed_at moves');
$gone = ['kind' => 'npc', 'id' => 940, 'fetched' => $now - 8 * 86400, 'status' => 'missing'];
source_answers_put(wowhead_db_page_rows([$gone]), $link);
check($get('page', 'npc', '940')['status'] === 'missing', 'a page Wowhead does not have');
check(wowhead_db_due_pages(10) === ['npc' => [940]], 'due pages for the crawl: "missing" older than recheck_days, not the fresh one');

// the backfill: tooltip files and page shelves of a data folder, once; again only what changed
$data = ft_test_dir();
mkdir("$data/wowhead/item", 0777, true);
mkdir("$data/wowhead-pages", 0777, true);
file_put_contents("$data/wowhead/item/25.json", json_encode(['name' => 'Worn Shortsword', 'fetched' => $now - 50]));
touch("$data/wowhead/item/25.json", $now - 50);
file_put_contents("$data/wowhead-pages/item.jsonl", json_encode(['id' => 25, 'fetched' => $now - 40, 'v' => 2, 'status' => 'ok', 'quick' => [], 'tabs' => new stdClass()]) . "\n");
file_put_contents("$data/wowhead-pages/forever-list.jsonl", json_encode(['kind' => 'list', 'query' => 'items', 'fetched' => $now - 40, 'v' => 2, 'status' => 'ok', 'rows' => [['id' => 25]], 'found' => 1, 'truncated' => false]) . "\n");
$counts = source_answers_backfill(false, null, $link, $data, ['wowhead']);
check($counts === ['wowhead' => 3], 'the backfill reads every file the first time: ' . json_encode($counts));
check($get('page', 'item', '25')['name'] === 'Worn Shortsword' && $get('page', 'list', 'items') !== null, "a page takes its tooltip's name; a list is kept by its query");
check(source_answers_backfill(false, null, $link, $data, ['wowhead']) === ['wowhead' => 0], 'again: only the files written since are read');
$link->query('DROP TABLE ft_source_answers');
ft_test_done();
