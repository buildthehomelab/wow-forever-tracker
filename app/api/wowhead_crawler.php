<?php
// GET api/wowhead-crawler: the full crawler with the pages this tracker wants next queued (as The Forge › Crawl hands
// it out), for the Chrome extension (tools/wowhead-pages/extension), which loads it into its Wowhead tab after every
// load. No session: the X-Push-Token header must be a key wowhead_push_allowed() takes. Nothing is asked of Wowhead.
// It answers with the crawler kept in data/wowhead-crawler.js, made again in the background (wowhead_crawler_cache).
require_once FT_APP . '/wowheadpages.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') json_out(['ok' => false, 'error' => 'GET only'], 405);
if (!wowhead_push_allowed((string)($_SERVER['HTTP_X_PUSH_TOKEN'] ?? ''))) json_out(['ok' => false, 'error' => 'not allowed'], 403);
if (!table_exists('ft_entities')) json_out(['ok' => false, 'error' => 'run the analysis first: the crawler reads the pages of its gaps'], 409);
// the kept crawler, at once (wowhead_crawler_cache): a build takes longer than Chrome lets the extension wait
[$code, $due] = wowhead_crawler_cache();
if ($due) wowhead_crawler_build_start();
if ($code === '') json_out(['ok' => false, 'error' => 'the crawler is being made, try again in a minute'], 503);
header('Content-Type: text/javascript; charset=utf-8');
header('Cache-Control: no-store');
echo $code;
exit;
