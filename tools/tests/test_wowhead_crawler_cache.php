<?php
// The crawler kept for the Chrome extension (app/wowheadpages.php, wowhead_crawler_cache): api/wowhead-crawler answers
// with it at once, since Chrome stops an extension that waits more than 30 s for a fetch, and a build takes longer.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/wowheadpages.php';

$dir = sys_get_temp_dir() . '/ft-crawler-' . getmypid();
@mkdir($dir);
$file = "$dir/wowhead-crawler.js";

check(wowhead_crawler_cache($file, null, 15) === ['', true], 'none kept: nothing to send, a build is due');
wowhead_crawler_cache_put('WHC.start();', $file);
check(wowhead_crawler_cache($file, time(), 15) === ['WHC.start();', false], 'a fresh one is sent, no build');
check(wowhead_crawler_cache($file, time() + 15 * 60, 15) === ['WHC.start();', true], 'an old one is still sent, and a build is due');
check(glob("$dir/*.tmp") === [], 'no half-written file left beside it');
wowhead_crawler_cache_clear($file);
check(wowhead_crawler_cache($file, null, 15)[0] === '', 'cleared: the next request starts a new one');
@rmdir($dir);
ft_test_done();
