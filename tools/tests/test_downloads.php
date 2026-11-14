<?php
// A download is kept only when it came whole, and is written beside its file and renamed into place (source_keep(),
// app/sources.php; norgannon_whole(), app/norgannon.php).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/norgannon.php';

$dir = ft_test_dir();
$json = fn(string $body) => is_array(json_decode($body, true));

// ---- the announced size
check(source_http_head(['HTTP/1.1 200 OK', 'Content-Type: application/json', 'Content-Length: 1234']) === [200, 1234], 'status and announced size are read');
check(source_http_head(['HTTP/1.1 302 Found', 'Content-Length: 0', 'Location: /x', 'HTTP/1.1 200 OK', 'content-length: 77']) === [200, 77], 'after a redirect, the last answer counts');
check(source_http_head(['HTTP/1.1 200 OK', 'Transfer-Encoding: chunked']) === [200, null], 'no announced size: none to compare');
check(source_http_head(['HTTP/1.1 200 OK', 'Content-Encoding: gzip', 'Content-Length: 50']) === [200, null], 'a packed body: its announced size is not the content\'s');
check(source_http_head([]) === [0, null], 'no answer at all');

// ---- kept or not
$whole = json_encode(['vendors' => [1 => ['entries' => [['itemId' => 2]]]]]);
check(source_keep("$dir/a/vendors.json", $whole, strlen($whole), $json) === '' && file_get_contents("$dir/a/vendors.json") === $whole, 'a whole answer is kept (its folder is made)');
check(glob("$dir/a/*.part") === [], 'nothing is left beside it');
$cut = substr($whole, 0, 20);
check(source_keep("$dir/a/loot.json", $cut, strlen($whole), $json) !== '' && !file_exists("$dir/a/loot.json"), 'fewer bytes than announced: not kept');
check(source_keep("$dir/a/loot.json", $cut, null, $json) !== '' && !file_exists("$dir/a/loot.json"), 'no size announced, but the JSON is cut short: not kept');
check(source_keep("$dir/a/loot.json", '<html>Service unavailable</html>', null, $json) !== '' && !file_exists("$dir/a/loot.json"), 'an error page with status 200: not kept');
check(source_keep("$dir/a/vendors.json", $cut, strlen($cut) + 5, $json) !== '' && file_get_contents("$dir/a/vendors.json") === $whole, 'a failed download leaves the file already kept alone');
check(source_keep("$dir/a/empty.json", '{}', 2, $json) === '', 'an empty list is still a whole answer');
check(source_keep("$dir/a/plain.bin", 'abc') === '' && file_get_contents("$dir/a/plain.bin") === 'abc', 'nothing to check against: kept (the caller checked, as with a checksum)');
mkdir("$dir/ro", 0500);
check(source_keep("$dir/ro/x.json", $whole, null, $json) !== '', 'a folder that cannot be written says so');
chmod("$dir/ro", 0700);

// ---- NorgannonDB's files
$pad = str_repeat("-- NorgannonDB data file, generated\n", 40);
$records = $pad . "do local R = NorgannonDB.R\n" . 'R(25,"Worn Shortsword",[[drops={npcs={[38]=0.5,[40]=1.2}},vendors={[54]=0}]])' . "\n" . 'R(35,"Bent Staff")' . "\n"
    . 'R(36,"Worn Mace",[[drops={npcs={[6]=2}}]])' . "\n";
check(norgannon_whole('items', $records), 'record lines, the last one complete: whole');
check(norgannon_whole('items', $records . "end\n"), 'whatever closes the file after the last record: whole');
check(norgannon_whole('quests', rtrim($records)), 'no line break at the end: whole');
check(!norgannon_whole('items', substr($records, 0, -12)), 'the last record cut inside its fields: cut short');
check(!norgannon_whole('items', $records . 'R(37,"Wo'), 'the last record cut inside its name: cut short');
check(!norgannon_whole('items', $records . 'R(37,"Worn Axe",[[drops={npcs={[6]=2}}'), 'the last record cut after a closing brace: cut short');
check(!norgannon_whole('items', $pad . '<html><body>Rate limit exceeded</body></html>'), 'no record at all: not the data file');
check(!norgannon_whole('items', 'R(1,"x")'), 'a few bytes: not the data file');

$table = fn(string $name, string $rows) => "do local function f() NorgannonDB.$name = {" . $rows . "} end f() end\n";
$training = $table('training', '["MAGE"]={[116]={cost=100,level=4,rank=1,trainers={198,328},name="Frost {Bolt}"}}');
$recipes = $table('recipes', '[2538]={skill=185,learn=1,trainers={[1355]=100}}');
check(norgannon_whole('recipes', $pad . $training . $recipes), 'both tables closed: whole');
check(norgannon_whole('recipes', $pad . $recipes), 'an older commit without the training table: whole');
check(norgannon_whole('recipes', $pad . str_repeat("-- nothing the import reads\n", 5)), 'a layout this does not know: kept as before');
check(!norgannon_whole('recipes', $pad . $training . substr($recipes, 0, -30)), 'the last table cut before it closes: cut short');
check(!norgannon_whole('recipes', $pad . substr($training, 0, 90)), 'the first table cut: cut short');
check(norgannon_whole('recipes', $pad . $training . 'NorgannonDB.recipes = {[2538]={skill=185,learn=1,trainers={[1355]=100},name="{"}}' . "\n"), 'a last table without the closing line, its braces balanced: whole');

ft_test_done();
