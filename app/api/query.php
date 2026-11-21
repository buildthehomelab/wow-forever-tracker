<?php
// POST api/query (administrators): one read-only statement on the tracker's world, hotfixes or own database
// (app/query.php). Body: {"db": "world", "sql": "SELECT ...", "format": "json" | "text"}, header X-CSRF-Token (the
// Query page holds it). Answers {ok, database, columns, rows, truncated, ms}, or the rows as a text table.
require_once FT_APP . '/query.php';
if (!is_admin()) json_out(['ok' => false, 'error' => t('Administrators only.', 'Réservé aux administrateurs.')], 403);
$input = json_decode((string)file_get_contents('php://input'), true) ?: [];
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !csrf_ok($_SERVER['HTTP_X_CSRF_TOKEN'] ?? ($input['csrf'] ?? null))) json_out(['ok' => false, 'error' => t('Session expired, reload the page.', 'Session expirée, rechargez la page.')], 400);

$out = query_run((string)($input['db'] ?? 'world'), (string)($input['sql'] ?? ''));
if (($input['format'] ?? '') === 'text') {
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    if (!$out['ok']) { http_response_code(400); echo 'ERROR: ', $out['error'], "\n"; exit; }
    echo query_text($out['columns'], $out['rows']), count($out['rows']), ' rows', $out['truncated'] ? ' (stopped at ' . QUERY_MAX_ROWS . ')' : '', ', ', $out['ms'], " ms\n";
    exit;
}
json_out($out, $out['ok'] ? 200 : 400);
