<?php
// The answers table (app/sourceanswers.php): rows of every outside source, a downloaded file cut into records, the due
// times each source's rules give, and the backfill of each source's files. With FT_TEST_MYSQL=host:port:root:password:db
// the rows are also written to that MySQL (the table ft_source_answers is made there and dropped again).
require __DIR__ . '/helpers.php';
$mysql = getenv('FT_TEST_MYSQL');
if ($mysql) {
    [$host, $port, $user, $password, $database] = explode(':', $mysql, 5);
    ft_test_boot("[database]\nhost = \"$host\"\nport = $port\nuser = \"$user\"\npassword = \"$password\"\ntracker = \"$database\"\n[foreverchanges]\nolder = 14\n");
} else ft_test_boot("[foreverchanges]\nolder = 14\n");
require FT_APP . '/sourceanswers.php';

// ---------------------------------------------------------------- rows
$row = source_answers_row(['source' => 'icyveins', 'feed' => 'api', 'kind' => 'npc', 'ref' => '7', 'id' => '7', 'name' => '  Hogger ', 'data' => ['b' => 1, 'a' => 2], 'fetched' => 10]);
check($row['id'] === 7 && $row['name'] === 'Hogger' && $row['status'] === 'found' && $row['branch'] === '' && $row['data'] === '{"b":1,"a":2}', 'a row: id, name trimmed, found, data as JSON');
check($row['hash'] === source_answers_hash(['a' => 2, 'b' => 1]) && $row['whole'] === null && $row['whole_hash'] === null, 'the hash of data with its keys sorted; no whole');
check(source_answers_row(['source' => 'x', 'feed' => 'f', 'kind' => 'k', 'ref' => '1', 'data' => 1]) === null && source_answers_row(['source' => 'x y', 'feed' => 'f', 'kind' => 'k', 'ref' => '1', 'fetched' => 1]) === null
    && source_answers_row(['source' => 'x', 'feed' => 'f', 'kind' => 'k', 'ref' => '', 'fetched' => 1]) === null, 'no time, a bad name or no ref: no row');
$long = source_answers_row(['source' => 'x', 'feed' => 'f', 'kind' => 'k', 'ref' => str_repeat('a/', 400), 'fetched' => 1]);
check(strlen($long['ref']) === SOURCE_ANSWERS_REF && str_ends_with($long['ref'], '#' . sha1(str_repeat('a/', 400))), 'a ref too long ends in the SHA-1 of the whole');
$w = source_answers_row(['source' => 'x', 'feed' => 'f', 'kind' => 'k', 'ref' => '1', 'whole' => ['z' => 1], 'fetched' => 1]);
$n = source_answers_row(['source' => 'x', 'feed' => 'f', 'kind' => 'k', 'ref' => '1', 'whole' => ['z' => 1], 'whole_hash' => null, 'fetched' => 1]);
check($w['whole_hash'] === source_answers_hash(['z' => 1]) && $n['whole'] === '{"z":1}' && $n['whole_hash'] === null, 'a whole answer is hashed, unless its builder says it is never compared');

// ---------------------------------------------------------------- a file cut into records
check(source_answers_file_kind('data/wowf/1.15.8/loot.json') === 'loot' && source_answers_file_kind('Data/NPCs.lua') === 'NPCs' && source_answers_file_kind('x/.json') === 'file', 'a file\'s kind is its name');
check(source_answers_key_id('25') === 25 && source_answers_key_id('npc:25') === 25 && source_answers_key_id('object:9|spell:3') === 9 && source_answers_key_id('kills') === null, 'an id from a key');
$small = source_answers_split_json(['a' => [1, 2]]);
check($small === [['', ['a' => [1, 2]]]], 'a small JSON value is one record');
$sources = [];
for ($i = 1; $i <= 3000; $i++) $sources["npc:$i"] = ['items' => [$i + 100 => ['chance' => 0.25]], 'name' => "Creature $i", 'pad' => str_repeat('x', 60)];
$big = ['version' => 3, 'sources' => $sources, 'kills' => ['npc:1' => ['deaths' => 12]]];
$parts = source_answers_split_json($big);
$pointers = array_column($parts, 0);
check(in_array('/sources/npc:1', $pointers, true) && in_array('/sources/npc:3000', $pointers, true) && in_array('/kills', $pointers, true) && in_array('/~rest', $pointers, true), 'a large JSON file: each large child cut, a small one whole, the scalars together');
$back = [];
foreach ($parts as [$pointer, $value]) {
    if ($pointer === '/~rest') { $back += $value; continue; }
    $keys = array_map(fn($k) => str_replace(['~1', '~0'], ['/', '~'], $k), explode('/', substr($pointer, 1)));
    $at = &$back;
    foreach ($keys as $k) $at = &$at[$k];
    $at = $value;
    unset($at);
}
check(source_answers_hash($back) === source_answers_hash($big), 'nothing of it is lost: the records make the file again');
$rows = source_answers_file_rows('eglink', 'abc', 'data/wowf/1.15.8/loot.json', json_encode($big), 100);
$one = array_values(array_filter($rows, fn($r) => $r['ref'] === 'data/wowf/1.15.8/loot.json#/sources/npc:42'))[0] ?? null;
check($one && $one['kind'] === 'loot' && $one['id'] === 42 && $one['name'] === 'Creature 42' && $one['feed'] === 'file' && $one['version'] === 'abc', 'a record\'s row: the file\'s kind, the key\'s id, its name, the version');

$lua = "-- Forever items\nQuestieDB.itemData = [[return {\n";
for ($i = 1; $i <= 3000; $i++) $lua .= "[$i] = {'Item $i',{1,2},nil,{3},\"" . str_repeat('y', 60) . "\"},\n";
$lua .= "}]]\nns.npcs = {\n  [5] = {\n    \"Old Man\",\n    {1, 2},\n  },\n  [6] = {\"Second\"},\n}\n";
$records = source_answers_split_lua($lua);
$labels = array_column($records, 0);
check(in_array('QuestieDB.itemData/1', $labels, true) && in_array('QuestieDB.itemData/3000', $labels, true) && in_array('ns.npcs/5', $labels, true) && in_array('~rest', $labels, true), 'a large Lua file: an entry a record, by its table');
check(implode('', array_column($records, 1)) !== '' && strlen(implode('', array_column($records, 1))) === strlen($lua), 'nothing of it is lost');
$npc = array_values(array_filter($records, fn($r) => $r[0] === 'ns.npcs/5'))[0];
check(str_contains($npc[1], '"Old Man"') && str_contains($npc[1], '{1, 2}') && $npc[2] === 5 && !str_contains($npc[1], 'Second'), 'a record holds the lines indented under it');
check(source_answers_lua_name($npc[1]) === 'Old Man' && source_answers_lua_name('R(25,"Worn \"Short\" Sword",[[1]])') === 'Worn "Short" Sword', 'its name: the first string');
$norgannon = '';
for ($i = 1; $i <= 2000; $i++) $norgannon .= "R($i,\"Item $i\",[[" . str_repeat('z', 150) . "]])\n";
$rows = source_answers_file_rows('norgannondb', 'c1', 'items.lua', $norgannon, 100);
check(count($rows) === 2000 && $rows[41]['ref'] === 'items.lua#42' && $rows[41]['id'] === 42 && $rows[41]['name'] === 'Item 42', 'NorgannonDB\'s R(...) lines: one row each');
$text = source_answers_file_rows('eglink', 'c', '_repo/README.md', "# EG Link\n", 1);
check(count($text) === 1 && $text[0]['ref'] === '_repo/README.md' && $text[0]['data'] === ['text' => "# EG Link\n"], 'other text: whole');
$bin = source_answers_file_rows('atlasloot', '1', 'Images/logo.blp', "BLP2\0\x01\x02", 1);
check($bin[0]['data']['base64'] === base64_encode("BLP2\0\x01\x02"), 'a small binary file: as base64');

// ---------------------------------------------------------------- Icy Veins and ForeverChanges rows
$iv = icyveins_answer_row('npc', 448, ['type' => 'npc', 'id' => 448, 'entity' => ['name' => 'Hogger'], 'relations' => ['drops' => [1]], 'fetched' => 500], ['entity' => ['name' => 'Hogger'], 'links' => ['x' => 1]]);
check($iv['source'] === 'icyveins' && $iv['feed'] === 'api' && $iv['branch'] === 'wowf' && $iv['name'] === 'Hogger' && !str_contains($iv['data'], 'fetched') && str_contains($iv['whole'], 'links') && $iv['whole_hash'] === null,
    'an Icy Veins answer: the mirror\'s record as data, the whole API answer kept but never compared');
check(icyveins_answer_row('quest', 9, ['missing' => true, 'fetched' => 5])['status'] === 'missing', 'not known: missing');
$list = icyveins_list_row('npc', ['fetched' => 9, 'ids' => [1, 2], 'total' => 2]);
check($list['feed'] === 'list' && $list['kind'] === 'npc' && $list['ref'] === 'ids', 'a kind\'s list of ids');
$fc = foreverchanges_answer_row(['f' => 'quest/123.html.gz', 'at' => 700, 's' => 200, 'key' => 'sha256-' . str_repeat('a', 64)], '<main>Hand it in</main>', ['title' => 'A Quest', 'start' => ['npc' => 1]]);
check($fc['kind'] === 'quest' && $fc['id'] === 123 && $fc['name'] === 'A Quest' && str_contains($fc['data'], '"start"') && $fc['whole'] === '"<main>Hand it in</main>"' && $fc['whole_hash'] === sha1('<main>Hand it in</main>'), 'a ForeverChanges page: what it states, its text whole');
$map = foreverchanges_answer_row(['f' => 'map/kalimdor/quest-givers.json', 'at' => 700, 's' => 200], '{"givers":[["n620","Bob"]]}');
check($map['kind'] === 'map' && $map['id'] === null && str_contains($map['data'], 'n620') && $map['whole'] === null, 'a map file: its JSON is the data');
check(foreverchanges_answer_row(['f' => 'item/5.html.gz', 'at' => 7, 's' => 404], null)['status'] === 'missing' && foreverchanges_answer_row(['f' => 'x', 'at' => 7, 's' => 503], null) === null, '404: missing; anything else is no answer');

// ---------------------------------------------------------------- due times
check(str_contains(source_answers_due_case('icyveins', ['epoch' => 0]), "WHEN status = 'missing' THEN fetched_at + INTERVAL 604800 SECOND ELSE fetched_at + INTERVAL 1209600 SECOND"), 'Icy Veins: 7 days for not known, 14 for the rest');
check(str_contains(source_answers_due_case('icyveins', ['epoch' => 1700000000]), 'WHEN fetched_at < FROM_UNIXTIME(1700000000) THEN fetched_at'), 'Icy Veins: "ask every source again"');
check(source_answers_due_case('foreverchanges', ['older_days' => 14]) === "CASE WHEN status = 'missing' THEN fetched_at + INTERVAL 4838400 SECOND ELSE fetched_at + INTERVAL 1209600 SECOND END", 'ForeverChanges: older days, four times that for a 404');
check(source_answers_due_case('eglink') === 'NULL', 'a versioned source: never by itself');

if (!$mysql) { echo "(FT_TEST_MYSQL not set: the rows are not written to MySQL)\n"; ft_test_done(); }

// ---------------------------------------------------------------- in MySQL
$link = new mysqli($host, $user, $password, $database, (int)$port);
$link->set_charset('utf8mb4');
$link->query('DROP TABLE IF EXISTS ft_source_answers');
$get = fn(string $source, string $feed, string $kind, string $ref) => $link->query("SELECT *, UNIX_TIMESTAMP(fetched_at) f, UNIX_TIMESTAMP(changed_at) c, UNIX_TIMESTAMP(first_seen) s, UNIX_TIMESTAMP(due_at) d
    FROM ft_source_answers WHERE source = '$source' AND feed = '$feed' AND kind = '$kind' AND ref = '" . $link->real_escape_string($ref) . "'")->fetch_assoc();

// the first version's Wowhead table moves in
$link->query('DROP TABLE IF EXISTS ft_wowhead');
$link->query("CREATE TABLE ft_wowhead (source VARCHAR(8) NOT NULL, branch VARCHAR(16) NOT NULL, kind VARCHAR(16) NOT NULL, ref VARCHAR(190) NOT NULL,
    id INT NULL, name VARCHAR(255) NULL, status VARCHAR(8) NOT NULL, version SMALLINT NOT NULL DEFAULT 0, data LONGTEXT NOT NULL, hash CHAR(40) NOT NULL,
    page LONGTEXT NULL, page_hash CHAR(40) NULL, page_at DATETIME NULL, fetched_at DATETIME NOT NULL, first_seen DATETIME NOT NULL, changed_at DATETIME NOT NULL,
    due_at DATETIME NULL, PRIMARY KEY (source, branch, kind, ref))");
$link->query("INSERT INTO ft_wowhead VALUES ('page', 'forever', 'npc', '939', 939, 'Kurzen Elite', 'found', 3, '{}', '" . str_repeat('a', 40) . "', '{\"name\":\"Kurzen Elite\"}', '" . str_repeat('b', 40) . "', NOW(), NOW(), NOW(), NOW(), NULL)");
source_answers_ensure($link);
$moved = $get('wowhead', 'page', 'npc', '939');
check($moved && $moved['whole'] === '{"name":"Kurzen Elite"}' && $moved['version'] === '3' && !$link->query("SHOW TABLES LIKE 'ft_wowhead'")->num_rows, 'ft_wowhead\'s rows move to source wowhead, and the old table goes');

// Icy Veins: the whole answer is kept but a new one that differs in it alone changes nothing
$t = time() - 30 * 86400;
source_answers_put([icyveins_answer_row('npc', 448, ['entity' => ['name' => 'Hogger'], 'fetched' => $t], ['entity' => ['name' => 'Hogger'], 'links' => 1])], $link);
$r = $get('icyveins', 'api', 'npc', '448');
check($r && (int)$r['c'] === $t && (int)$r['d'] === $t + 14 * 86400 && str_contains($r['whole'], 'links'), 'an Icy Veins answer: due after 14 days, the whole answer kept');
source_answers_put([icyveins_answer_row('npc', 448, ['entity' => ['name' => 'Hogger'], 'fetched' => $t + 10], ['entity' => ['name' => 'Hogger'], 'links' => 2])], $link);
$r = $get('icyveins', 'api', 'npc', '448');
check((int)$r['f'] === $t + 10 && (int)$r['c'] === $t && str_contains($r['whole'], '"links":2'), 'asked again, only its links differ: no change, the new whole kept');
source_answers_put([icyveins_answer_row('npc', 448, ['entity' => ['name' => 'Hogger'], 'fetched' => $t + 20])], $link);
$r = $get('icyveins', 'api', 'npc', '448');
check((int)$r['f'] === $t + 20 && str_contains($r['whole'], '"links":2') && (int)$r['whole_at'] !== 0, 'an answer without its whole (the backfill) keeps the one held');
source_answers_put([icyveins_answer_row('npc', 448, ['missing' => true, 'fetched' => $t + 30])], $link);
$r = $get('icyveins', 'api', 'npc', '448');
check((int)$r['c'] === $t + 30 && $r['status'] === 'missing' && (int)$r['d'] === $t + 30 + 7 * 86400, 'Icy Veins no longer knows it: changed, due after 7 days');

// the backfill of each source's files
$data = ft_test_dir();
$now = time();
mkdir("$data/icyveins/gameobject", 0777, true);
file_put_contents("$data/icyveins/gameobject/1617.json.gz", gzencode(json_encode(['entity' => ['name' => 'Silverleaf'], 'children' => [], 'fetched' => $now - 100])));
file_put_contents("$data/icyveins/npc.ids.json", json_encode(['fetched' => $now - 50, 'ids' => [448], 'total' => 1]));
touch("$data/icyveins/gameobject/1617.json.gz", $now - 100);   // written before the run: a file of the run's own second is read again
touch("$data/icyveins/npc.ids.json", $now - 50);
mkdir("$data/foreverchanges/site/quest", 0777, true);
$html = gzencode('<main>Bring me ten pelts.</main>');
$key = 'sha256-' . hash('sha256', $html);
mkdir("$data/sources/blobs/" . substr($key, 7, 2), 0777, true);
file_put_contents("$data/sources/blobs/" . substr($key, 7, 2) . "/$key", $html);
file_put_contents("$data/foreverchanges/pages.jsonl", json_encode(['f' => 'quest/33.html.gz', 'at' => $now - 3000, 's' => 404]) . "\n" . json_encode(['f' => 'quest/33.html.gz', 'at' => $now - 200, 's' => 200, 'key' => $key]) . "\n");
file_put_contents("$data/foreverchanges/parsed.jsonl", json_encode(['key' => $key, 'rec' => ['title' => 'Wolf Pelts', 'end' => ['npc' => 7]]]) . "\n");
// QuestieDB: an older commit, then a newer one that changed one entry and dropped another
$old = str_repeat('a', 40); $new = str_repeat('b', 40);
foreach ([$old => $now - 5000, $new => $now - 1000] as $commit => $at) {
    mkdir("$data/questie/$commit/data/Forever", 0777, true);
    $db = "QuestieDB.itemData = [[return {\n";
    for ($i = 1; $i <= 2500; $i++) if (!($commit === $new && $i === 7)) $db .= "[$i] = {'Item $i'," . ($commit === $new && $i === 5 ? '{99}' : '{1}') . ",\"" . str_repeat('q', 100) . "\"},\n";
    file_put_contents("$data/questie/$commit/data/Forever/foreverItemDB.lua", "$db}]]\n");
    touch("$data/questie/$commit", $at);
}
mkdir("$data/atlasloot", 0777, true);
$zip = new ZipArchive();
$zip->open("$data/atlasloot/7001.zip", ZipArchive::CREATE);
$zip->addFromString('AtlasLootClassic_DungeonsAndRaids\\data.lua', "local data = {}\n");
$zip->close();
mkdir("$data/vmangos", 0777, true);
file_put_contents("$data/vmangos/pack.cdbpack", gzencode(json_encode(['source' => 'VMaNGOS', 'drop' => [[1, 2, 3]]])));

$counts = source_answers_backfill(false, null, $link, $data);
check(($counts['icyveins'] ?? 0) === 2 && ($counts['foreverchanges'] ?? 0) === 1 && ($counts['questie'] ?? 0) === 2500 && ($counts['atlasloot'] ?? 0) === 1 && ($counts['vmangos'] ?? 0) === 1,
    'the backfill reads every source\'s files: ' . json_encode($counts));
$r = $get('icyveins', 'api', 'gameobject', '1617');
check($r && $r['name'] === 'Silverleaf' && $get('icyveins', 'list', 'npc', 'ids') !== null, 'Icy Veins: the mirror\'s answers and the lists');
$r = $get('foreverchanges', 'site', 'quest', 'quest/33.html.gz');
check($r && $r['name'] === 'Wolf Pelts' && (int)$r['f'] === $now - 200 && $r['whole'] === json_encode('<main>Bring me ten pelts.</main>', JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) && (int)$r['d'] === $now - 200 + 14 * 86400,
    'ForeverChanges: the last reading of a page, what it states, its text, due after older days');
$r = $get('questie', 'file', 'foreverItemDB', 'data/Forever/foreverItemDB.lua#QuestieDB.itemData/5');
check($r && $r['version'] === $new && str_contains($r['data'], '{99}') && $r['id'] === '5' && $r['name'] === 'Item 5' && $r['due_at'] === null, 'QuestieDB: the newest commit only, an item a row');
check($get('questie', 'file', 'foreverItemDB', 'data/Forever/foreverItemDB.lua#QuestieDB.itemData/7') === null, 'the older commit is not read (it was superseded before the table)');
check($get('atlasloot', 'file', 'data', 'AtlasLootClassic_DungeonsAndRaids/data.lua') !== null && $get('vmangos', 'file', 'pack', 'pack.json') !== null, 'AtlasLoot\'s zip and a VMaNGOS pack');
$again = source_answers_backfill(false, null, $link, $data);
check(array_sum($again) === 0, 'again: nothing new, nothing written ' . json_encode($again));

// a new QuestieDB commit: what changed moves changed_at, what it dropped is gone
$newer = str_repeat('c', 40);
mkdir("$data/questie/$newer/data/Forever", 0777, true);
$db = "QuestieDB.itemData = [[return {\n";
for ($i = 1; $i <= 2500; $i++) if ($i !== 8) $db .= "[$i] = {'Item $i'," . ($i === 6 ? '{77}' : ($i === 5 ? '{99}' : '{1}')) . ",\"" . str_repeat('q', 100) . "\"},\n";
file_put_contents("$data/questie/$newer/data/Forever/foreverItemDB.lua", "$db}]]\n");
touch("$data/questie/$newer", $now - 10);
source_answers_backfill(false, null, $link, $data, ['questie']);
$five = $get('questie', 'file', 'foreverItemDB', 'data/Forever/foreverItemDB.lua#QuestieDB.itemData/5');
$six = $get('questie', 'file', 'foreverItemDB', 'data/Forever/foreverItemDB.lua#QuestieDB.itemData/6');
$eight = $get('questie', 'file', 'foreverItemDB', 'data/Forever/foreverItemDB.lua#QuestieDB.itemData/8');
check($five['version'] === $newer && (int)$five['c'] === $now - 1000 && (int)$six['c'] === $now - 10, 'a new commit: only what it changed moves changed_at');
check($eight['status'] === 'gone' && (int)$eight['c'] === $now - 10 && $eight['version'] === $new, 'what it no longer holds is gone, as of that commit');

// ForeverChanges: only the readings added since
file_put_contents("$data/foreverchanges/pages.jsonl", json_encode(['f' => 'item/5.html.gz', 'at' => $now - 5, 's' => 404]) . "\n", FILE_APPEND);
check(source_answers_backfill(false, null, $link, $data, ['foreverchanges']) === ['foreverchanges' => 1] && $get('foreverchanges', 'site', 'item', 'item/5.html.gz')['status'] === 'missing', 'ForeverChanges: the new readings only');

// one backfill at a time
$lock = fopen("$data/source-answers.lock", 'c');
flock($lock, LOCK_EX);
check(source_answers_backfill(false, null, $link, $data) === ['busy' => true], 'a second backfill while one runs does nothing');
flock($lock, LOCK_UN);
fclose($lock);
$link->query('DROP TABLE ft_source_answers');
ft_test_done();
