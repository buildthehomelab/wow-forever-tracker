<?php
// POST api/wowhead-push: pages the Wowhead crawler saved (one JSON line a page, the body as it is), sent by a script
// rather than a browser (tools/wowhead-pages/push.sh, docs/WOWHEAD-PAGES.md "Batches from a computer"). No session:
// the X-Push-Token header must be [wowhead] push_token (empty, so closed, unless set) or the Chrome extension's key
// (made when it is first downloaded, wowhead_extension_key()).
// The pages are kept as a linked crawl's are (wowhead_pages_append) and answered at once; the import cards are made
// again after the answer, when due ([wowhead] card_minutes).
require_once FT_APP . '/wowheadpages.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') json_out(['ok' => false, 'error' => 'POST only'], 405);
if (!wowhead_push_allowed((string)($_SERVER['HTTP_X_PUSH_TOKEN'] ?? ''))) json_out(['ok' => false, 'error' => 'not allowed'], 403);
$body = (string)file_get_contents('php://input');
$lines = array_values(array_filter(preg_split('/\r?\n/', $body), fn($l) => trim($l) !== ''));
if (!$lines) json_out(['ok' => false, 'error' => 'no page in the body'], 400);
try { $got = wowhead_pages_append($lines); }
catch (RuntimeException $e) { json_out(['ok' => false, 'error' => 'the data folder cannot be written to'], 500); }
// the answer goes out now: the pages are kept whatever the cards do after (they need the database and take a while)
$answer = json_encode(['ok' => true, 'pages' => $got['pages'], 'not_a_page' => $got['not_a_page']]);
ignore_user_abort(true);
@set_time_limit(0);
header('Content-Type: application/json; charset=utf-8');
header('Content-Length: ' . strlen($answer));
header('Connection: close');
echo $answer;
while (ob_get_level() > 0) ob_end_flush();
flush();
if (function_exists('fastcgi_finish_request')) fastcgi_finish_request();
if ($got['pages']) {
    try { wowhead_pages_cards_due(); }
    catch (Throwable $e) { error_log('Forever Tracker: the cards after a Wowhead push were not made: ' . $e->getMessage()); }
}
exit;
