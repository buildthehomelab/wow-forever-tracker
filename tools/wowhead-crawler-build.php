<?php
// Makes the crawler the Chrome extension loads (api/wowhead-crawler) and keeps it in data/wowhead-crawler.js
// (app/wowheadpages.php, wowhead_crawler_cache). Started in the background by that request when the kept one is old or
// missing; one build at a time (it holds data/wowhead-crawler.lock, a second start exits 3).
//
//   php tools/wowhead-crawler-build.php
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require FT_APP . '/wowheadpages.php';

$lock = fopen(FT_ROOT . '/data/wowhead-crawler.lock', 'c');
if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) exit(3);
if (!table_exists('ft_entities')) exit(1);   // no analysis yet: the crawler reads the pages of its gaps
wowhead_crawler_cache_put(wowhead_pages_crawler(wowhead_pages_queue(), true));
flock($lock, LOCK_UN);
exit(0);
