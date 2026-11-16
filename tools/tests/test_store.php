<?php
// Every file a source gives, kept once (app/store.php): named by its content as git names it, refused when it is not
// the file named, and linked into each version's folder, so a second version that shares it downloads nothing.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';
$GLOBALS['ft_store_dir'] = ft_test_dir() . '/blobs';

$body = "hello store\n";
check(store_key('git', $body) === 'git-75d112b88195e456d90814b8b7db7af6b4d313b1', 'a file is named as git names it (git hash-object gives 75d112b8…)');
check(strlen(store_key('sha256', $body)) === 71 && store_valid_key(store_key('sha256', $body)) && !store_valid_key('git-zz') && !store_valid_key('../x'), 'and by its sha256');
$key = store_key('git', $body);
check(store_put($key, "something else\n") !== '' && !store_has($key), 'a file that is not the one named is refused');
check(store_put($key, $body) === '' && store_has($key) && file_get_contents(store_path($key)) === $body, 'the named file is kept');

// a folder downloaded before the store: its file is taken in, nothing is downloaded
$v1 = ft_test_dir(); $v2 = ft_test_dir();
$old = "old file\n"; $oldKey = store_key('git', $old);
file_put_contents("$v1/a.json", $old);
[$down, $linked, $problem] = store_fill($v1, ['a.json' => [$oldKey, 'http://127.0.0.1:9/never'], 'sub/b.json' => [$key, 'http://127.0.0.1:9/never']]);
check($problem === '' && $down === 0 && $linked === 2 && store_has($oldKey), 'a file already in place is taken into the store, a kept one linked: nothing downloaded');
check(file_get_contents("$v1/sub/b.json") === $body && is_file("$v1/.files.json") && json_decode(file_get_contents("$v1/.files.json"), true) === ['a.json' => $oldKey, 'sub/b.json' => $key], 'the folder says what it is made of');
// a second version sharing both files
[$down2, , $problem2] = store_fill($v2, ['a.json' => [$oldKey, 'http://127.0.0.1:9/never'], 'sub/b.json' => [$key, 'http://127.0.0.1:9/never']]);
check($problem2 === '' && $down2 === 0 && fileinode("$v2/a.json") === fileinode(store_path($oldKey)), 'the next version links the same file: no second copy, no download');
// a name that is no path is never written
[$down3, $linked3] = store_fill($v2, ['../escape.json' => [$key, 'x'], '/abs' => [$key, 'x'], 'ok name.json' => [$key, 'x']]);
check($linked3 === 0 && !is_file(dirname($v2) . '/escape.json'), 'a path outside the folder is not written');

$place = store_place_data('data/wowf');
check($place('data/wowf/1.60.1.70938/loot.json') === '1.60.1.70938/loot.json' && $place('data/index.json') === '_repo/data/index.json' && $place('README.md') === '_repo/README.md', 'a repository\'s data folder at the top, the rest under _repo/');

ft_test_done();
