<?php
// Every Wowhead answer this tracker holds, in one table of the tracker's database (docs/WOWHEAD-PAGES.md "The Wowhead
// table"): the tooltips (data/wowhead/<kind>/<id>.json, app/wowhead.php and tools/ft/wowhead.py) and the pages the
// browser crawler read (data/wowhead-pages/<shelf>.jsonl, app/wowheadpages.php). The files stay what the analysis and
// the imports read; the table is for people: The Forge › Query reads it (SELECT … FROM ft_wowhead), and it says what
// changed on Wowhead and when, and which answers are due to be read again.
//
//   ft_wowhead   one row an answer: source ('tooltip' or 'page'), branch, kind, ref (the id, or a list's or guide's
//                query), id, name, status ('found' or 'missing'), data (the answer as the files keep it), page (the
//                whole page as the crawler read it, names and text too: crawler records from v3 on), the times it was
//                fetched, first seen and last changed, and when it is due to be read again (due_at, NULL: never).
//
// changed_at moves only when what Wowhead says changed: the hash of `data` (without the time it was fetched), or of
// `page` when the row held a whole page already. An answer older than the one held changes nothing, so the backfill
// can run as often as it likes. The tracker never asks Wowhead for a page: due pages go to the crawl's queue
// (wowhead_pages_queue 'recheck'), and due tooltips are asked again by the analysis as before.
require_once FT_APP . '/wowhead.php';
require_once FT_APP . '/wowheadpages.php';

const WOWHEAD_DB_TABLE = 'ft_wowhead';
/** Rows written in one INSERT, and the bytes one INSERT may hold (MySQL's max_allowed_packet is 16 MB at least). */
const WOWHEAD_DB_CHUNK_ROWS = 200;
const WOWHEAD_DB_CHUNK_BYTES = 8 * 1048576;
/** The tooltip kinds the tooltip cache holds (data/wowhead/<kind>/), as the page kinds name them. */
const WOWHEAD_DB_TOOLTIP_KINDS = ['npc', 'object', 'item', 'quest', 'spell', 'zone', 'faction', 'itemset', 'achievement', 'currency'];

function wowhead_db_ensure(?mysqli $link = null): void
{
    static $done = false;
    if ($done && $link === null) return;
    $link ??= db();
    $link->query('CREATE TABLE IF NOT EXISTS ' . WOWHEAD_DB_TABLE . " (
        source VARCHAR(8) NOT NULL, branch VARCHAR(16) NOT NULL, kind VARCHAR(16) NOT NULL, ref VARCHAR(190) NOT NULL,
        id INT NULL, name VARCHAR(255) NULL, status VARCHAR(8) NOT NULL, version SMALLINT NOT NULL DEFAULT 0,
        data LONGTEXT NOT NULL, hash CHAR(40) NOT NULL, page LONGTEXT NULL, page_hash CHAR(40) NULL, page_at DATETIME NULL,
        fetched_at DATETIME NOT NULL, first_seen DATETIME NOT NULL, changed_at DATETIME NOT NULL, due_at DATETIME NULL,
        PRIMARY KEY (source, branch, kind, ref), KEY ix_id (kind, id), KEY ix_name (name), KEY ix_changed (changed_at),
        KEY ix_due (due_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
    $done = true;
}

/** A value with its object keys sorted at every depth, so that the same answer always hashes the same. */
function wowhead_db_canonical($value)
{
    if (!is_array($value)) return $value;
    if (!array_is_list($value)) ksort($value, SORT_STRING);
    return array_map('wowhead_db_canonical', $value);
}

function wowhead_db_json($value): string
{
    return (string)json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION | JSON_INVALID_UTF8_SUBSTITUTE);
}

function wowhead_db_hash($value): string { return sha1(wowhead_db_json(wowhead_db_canonical($value))); }

/** The name a tooltip of the cache gives a kind's id, or null (the page records keep none before crawler v3). */
function wowhead_db_tooltip_name(string $kind, int $id, ?string $root = null): ?string
{
    if (!in_array($kind, WOWHEAD_DB_TOOLTIP_KINDS, true) || $id <= 0) return null;
    $data = json_decode((string)@file_get_contents(($root ?? FT_ROOT . '/data/wowhead') . "/$kind/$id.json"), true);
    return is_array($data) && is_string($data['name'] ?? null) && $data['name'] !== '' ? mb_substr($data['name'], 0, 255) : null;
}

/**
 * A tooltip answer as a row: ['source', 'branch', 'kind', 'ref', 'id', 'name', 'status', 'version', 'data', 'hash',
 * 'page', 'page_hash', 'fetched']. The hash leaves out the time it was fetched, and a creature's or object's tooltip
 * text (older answers were kept without it: its coming back is no change of Wowhead's).
 */
function wowhead_db_tooltip_row(string $kind, int $id, array $data, ?string $branch = null): ?array
{
    $fetched = (int)($data['fetched'] ?? 0);
    if ($id <= 0 || $fetched <= 0 || !preg_match('/^[a-z-]{1,16}$/', $kind)) return null;
    $kept = $data;
    unset($kept['fetched']);
    $hashed = $kept;
    if (in_array($kind, ['npc', 'object'], true)) unset($hashed['tooltip']);
    $missing = !empty($data['missing']);
    return ['source' => 'tooltip', 'branch' => $branch ?? ((string)(config('wowhead', 'branch', 'forever') ?: 'forever')), 'kind' => $kind, 'ref' => (string)$id, 'id' => $id,
        'name' => !$missing && is_string($data['name'] ?? null) && $data['name'] !== '' ? mb_substr($data['name'], 0, 255) : null,
        'status' => $missing ? 'missing' : 'found', 'version' => 0, 'data' => wowhead_db_json($kept), 'hash' => wowhead_db_hash($hashed),
        'page' => null, 'page_hash' => null, 'fetched' => $fetched];
}

/**
 * A crawler record as a row. $clean is the record as the cache keeps it (wowhead_pages_clean: numbers only), $whole
 * what the crawler read of the whole page ($raw['full'], crawler v3: names, Quick Facts with their text, every tab row
 * as Wowhead gives it, the map, what the page's links name), or null. $names: a tooltip name for a page without its
 * own (a callable kind, id → ?string).
 */
function wowhead_db_page_row(array $clean, ?array $whole = null, ?callable $names = null): ?array
{
    $fetched = (int)($clean['fetched'] ?? 0);
    $branch = (string)($clean['branch'] ?? 'forever');
    $list = in_array($clean['kind'] ?? '', ['list', 'guide'], true);
    $ref = wowhead_pages_entity($clean);
    if ($fetched <= 0 || $ref === null) return null;
    // the shelf says what a page is (the cache's records of 'item' pages carry no kind of their own)
    $kind = $list ? (string)$clean['kind'] : (string)($clean['kind'] ?? '');
    if ($kind === '' || !preg_match('/^[a-z-]{1,16}$/', $kind)) return null;
    $kept = $clean;
    unset($kept['fetched'], $kept['v']);
    $id = $list ? null : (int)$ref;
    $name = is_string($whole['name'] ?? null) && $whole['name'] !== '' ? mb_substr($whole['name'], 0, 255) : null;
    if ($name === null && $id !== null && $branch === 'forever' && $names) $name = $names($kind, $id);
    $page = is_array($whole) && $whole ? wowhead_db_json($whole) : null;
    return ['source' => 'page', 'branch' => $branch, 'kind' => $kind, 'ref' => (string)$ref, 'id' => $id, 'name' => $name,
        'status' => ($clean['status'] ?? '') === 'missing' ? 'missing' : 'found', 'version' => (int)($clean['v'] ?? 0),
        'data' => wowhead_db_json($kept), 'hash' => wowhead_db_hash($kept), 'page' => $page, 'page_hash' => $page === null ? null : wowhead_db_hash($whole),
        'fetched' => $fetched];
}

/**
 * The INSERT of some rows. A row older than the one held changes nothing (but a name the held row lacks); a newer one
 * replaces data, and page when it brings a whole page (a numbers-only answer after a whole one keeps the whole one,
 * page_at says how old it is). changed_at moves to the new answer's time when the hash of data differs, or that of
 * page when both hold one. The assignments run in order: changed_at reads the old values, so it comes first.
 */
function wowhead_db_insert_sql(mysqli $link, array $rows): string
{
    $q = fn($v) => $v === null ? 'NULL' : (is_int($v) ? (string)$v : "'" . $link->real_escape_string((string)$v) . "'");
    $values = [];
    foreach ($rows as $r) {
        $at = 'FROM_UNIXTIME(' . (int)$r['fetched'] . ')';
        $values[] = '(' . implode(',', [$q($r['source']), $q($r['branch']), $q($r['kind']), $q($r['ref']), $q($r['id']), $q($r['name']), $q($r['status']), (int)$r['version'],
            $q($r['data']), $q($r['hash']), $q($r['page']), $q($r['page_hash']), $r['page'] === null ? 'NULL' : $at, $at, $at, $at]) . ')';
    }
    $newer = 'VALUES(fetched_at) > fetched_at';
    return 'INSERT INTO ' . WOWHEAD_DB_TABLE . ' (source, branch, kind, ref, id, name, status, version, data, hash, page, page_hash, page_at, fetched_at, first_seen, changed_at) VALUES '
        . implode(',', $values) . ' ON DUPLICATE KEY UPDATE '
        . "changed_at = IF($newer AND (VALUES(hash) <> hash OR (VALUES(page_hash) IS NOT NULL AND page_hash IS NOT NULL AND VALUES(page_hash) <> page_hash)), VALUES(fetched_at), changed_at), "
        . 'first_seen = LEAST(first_seen, VALUES(fetched_at)), '
        . "name = IF($newer AND VALUES(name) IS NOT NULL, VALUES(name), COALESCE(name, VALUES(name))), "
        . "page = IF($newer AND VALUES(page) IS NOT NULL, VALUES(page), page), "
        . "page_hash = IF($newer AND VALUES(page_hash) IS NOT NULL, VALUES(page_hash), page_hash), "
        . "page_at = IF($newer AND VALUES(page_at) IS NOT NULL, VALUES(page_at), page_at), "
        . "status = IF($newer, VALUES(status), status), version = IF($newer, VALUES(version), version), "
        . "data = IF($newer, VALUES(data), data), hash = IF($newer, VALUES(hash), hash), "
        . "fetched_at = IF($newer, VALUES(fetched_at), fetched_at)";
}

/**
 * When each row is due to be read again, by the rules of wowhead_stale(): an answer older than the last "ask every
 * source again" at once; "Wowhead does not know it" after [wowhead] recheck_days; an answer after [wowhead]
 * refresh_days give or take a quarter by id (wowhead_spread), never when it is 0. $where limits the rows.
 */
function wowhead_db_due_sql(?float $refreshDays = null, ?float $recheckDays = null, ?int $epoch = null, string $where = '1'): string
{
    $refresh = $refreshDays ?? max(0.0, (float)config('wowhead', 'refresh_days', 30));
    $recheck = $recheckDays ?? (float)(config('wowhead', 'recheck_days', 7) ?: 7);
    $epoch ??= source_refresh_epoch();
    $spread = '(0.75 + MOD(CAST(COALESCE(id, 0) AS SIGNED) * 2654435761, 1000) / 2000)';
    return 'UPDATE ' . WOWHEAD_DB_TABLE . ' SET due_at = CASE'
        . ($epoch > 0 ? ' WHEN fetched_at < FROM_UNIXTIME(' . (int)$epoch . ') THEN fetched_at' : '')
        . " WHEN status = 'missing' THEN fetched_at + INTERVAL " . (int)round($recheck * 86400) . ' SECOND'
        . ($refresh > 0 ? " ELSE fetched_at + INTERVAL ROUND(" . sprintf('%.6F', $refresh * 86400) . " * $spread) SECOND" : ' ELSE NULL')
        . " END WHERE $where";
}

/** Writes rows (wowhead_db_tooltip_row, wowhead_db_page_row) and sets when they are due. Returns how many were sent. */
function wowhead_db_put(array $rows, ?mysqli $link = null): int
{
    $rows = array_values(array_filter($rows));
    if (!$rows) return 0;
    $link ??= db();
    wowhead_db_ensure($link);
    $chunk = []; $bytes = 0; $sent = 0;
    $flush = function () use (&$chunk, &$bytes, &$sent, $link) {
        if (!$chunk) return;
        $link->query(wowhead_db_insert_sql($link, $chunk));
        $sent += count($chunk);
        $chunk = []; $bytes = 0;
    };
    foreach ($rows as $r) {
        $size = strlen($r['data']) + strlen((string)$r['page']) + 512;
        if ($chunk && (count($chunk) >= WOWHEAD_DB_CHUNK_ROWS || $bytes + $size > WOWHEAD_DB_CHUNK_BYTES)) $flush();
        $chunk[] = $r; $bytes += $size;
    }
    $flush();
    // the rows just written: their due time from their (maybe new) fetch time
    $since = min(array_map(fn($r) => (int)$r['fetched'], $rows));
    $link->query(wowhead_db_due_sql(where: 'fetched_at >= FROM_UNIXTIME(' . $since . ')'));
    return $sent;
}

/** The tracker's database, or null when it cannot be reached (db() would end the request with an error page). */
function wowhead_db_link(): ?mysqli
{
    static $link = false;
    if ($link !== false) return $link;
    try {
        $link = new mysqli((string)config('database', 'host', '127.0.0.1'), (string)config('database', 'user', ''), (string)config('database', 'password', ''),
            (string)config('database', 'tracker', 'tracker'), (int)config('database', 'port', 3306));
        $link->set_charset('utf8mb4');
    } catch (Throwable $e) {
        error_log('Forever Tracker: no database for ' . WOWHEAD_DB_TABLE . ': ' . $e->getMessage());
        $link = null;
    }
    return $link;
}

/** Writes rows and never fails the caller: the files are what the tracker keeps, the table follows them. */
function wowhead_db_try(array $rows): int
{
    if (!$rows || !($link = wowhead_db_link())) return 0;
    try { return wowhead_db_put($rows, $link); }
    catch (Throwable $e) { error_log('Forever Tracker: Wowhead answers not written to ' . WOWHEAD_DB_TABLE . ': ' . $e->getMessage()); return 0; }
}

/** Rows of crawler lines as they came (each with its 'full' block when the crawler kept the whole page). */
function wowhead_db_page_rows(array $raws): array
{
    $names = fn(string $kind, int $id) => wowhead_db_tooltip_name($kind, $id);
    $out = [];
    foreach ($raws as $raw) {
        $clean = is_array($raw) ? wowhead_pages_clean($raw) : null;
        if ($clean === null) continue;
        $clean['kind'] ??= (string)$raw['kind'];
        $out[] = wowhead_db_page_row($clean, wowhead_db_whole($raw['full'] ?? null), $names);
    }
    return array_values(array_filter($out));
}

/** The whole page a crawler line carries: a JSON object, or null (an older crawler, or something that is not one). */
function wowhead_db_whole($full): ?array
{
    return is_array($full) && $full && !array_is_list($full) ? $full : null;
}

// ------------------------------------------------------------------ the backfill: what the files already hold

function wowhead_db_state_file(): string { return FT_ROOT . '/data/wowhead-db.json'; }

/** Raise when a backfill must read every file again (a new column filled from the files). */
const WOWHEAD_DB_BACKFILL_V = 1;

/**
 * Puts what the files hold into the table: every page shelf, and every tooltip file written since the last run (all of
 * them the first time). Pages are read again only when a shelf's file changed since (its size or time), or the
 * backfill's version rose. Returns counts: tooltips, pages, shelves.
 */
function wowhead_db_backfill(bool $all = false, ?callable $say = null, ?mysqli $link = null, ?string $data = null): array
{
    $say ??= fn(string $line) => null;
    $link ??= db();
    wowhead_db_ensure($link);
    // $data: another data folder (the tests'): its wowhead/, wowhead-pages/ and wowhead-db.json
    $statePath = $data === null ? wowhead_db_state_file() : "$data/wowhead-db.json";
    $pageDirs = $data === null ? wowhead_pages_dirs() : ["$data/wowhead-pages"];
    $state = json_decode((string)@file_get_contents($statePath), true);
    if (!is_array($state) || (int)($state['v'] ?? 0) !== WOWHEAD_DB_BACKFILL_V || $all) $state = ['v' => WOWHEAD_DB_BACKFILL_V, 'tooltips_since' => 0, 'shelves' => []];
    $started = time();
    $counts = ['tooltips' => 0, 'pages' => 0, 'shelves' => 0];
    // tooltips: the files written since the last run (a second's margin: a file written while the last run read)
    $root = ($data ?? FT_ROOT . '/data') . '/wowhead';
    $since = max(0, (int)$state['tooltips_since'] - 1);
    $branch = (string)(config('wowhead', 'branch', 'forever') ?: 'forever');
    $batch = [];
    foreach (glob("$root/*", GLOB_ONLYDIR) ?: [] as $dir) {
        $kind = basename($dir);
        if (!preg_match('/^[a-z-]{1,16}$/', $kind)) continue;
        foreach (new DirectoryIterator($dir) as $file) {
            if (!$file->isFile() || !preg_match('/^(\d+)\.json$/', $file->getFilename(), $m) || $file->getMTime() < $since) continue;
            $data = json_decode((string)@file_get_contents($file->getPathname()), true);
            if (!is_array($data)) continue;
            $batch[] = wowhead_db_tooltip_row($kind, (int)$m[1], $data, $branch);
            if (count($batch) >= 2000) { $counts['tooltips'] += wowhead_db_put($batch, $link); $batch = []; }
        }
    }
    $counts['tooltips'] += wowhead_db_put($batch, $link);
    $say("tooltips: {$counts['tooltips']} written");
    // pages: each shelf whose file changed since the last run
    $names = fn(string $kind, int $id) => wowhead_db_tooltip_name($kind, $id, $root);
    foreach ($pageDirs as $dir) {
        foreach (glob("$dir/*.jsonl") ?: [] as $path) {
            $shelf = basename($path, '.jsonl');
            $mark = filesize($path) . ':' . filemtime($path);
            if (($state['shelves'][$path] ?? null) === $mark) continue;
            [$branchOf, $kind] = wowhead_db_shelf_kind($shelf);
            if ($kind === null) continue;
            $batch = []; $n = 0;
            foreach (wowhead_db_shelf_records($shelf, [$dir], $kind) as $record) {
                $record['kind'] ??= $kind;
                if ($branchOf !== 'forever') $record['branch'] ??= $branchOf;
                $batch[] = wowhead_db_page_row($record, null, $names);
                if (count($batch) >= 1000) { $n += wowhead_db_put($batch, $link); $batch = []; }
            }
            $n += wowhead_db_put($batch, $link);
            $state['shelves'][$path] = $mark;
            $counts['pages'] += $n; $counts['shelves']++;
            $say("pages: $shelf, $n written");
        }
    }
    $state['tooltips_since'] = $started;
    @file_put_contents($statePath, json_encode($state, JSON_UNESCAPED_SLASHES) . "\n", LOCK_EX);
    // the due times follow [wowhead] refresh_days, recheck_days and "ask every source again" as they are now
    $link->query(wowhead_db_due_sql());
    return $counts;
}

/** A shelf's branch and kind: 'item' → [forever, item], 'classic-npc' → [classic, npc], 'forever-list' → [forever, list]. */
function wowhead_db_shelf_kind(string $shelf): array
{
    if (!preg_match('/^(?:(' . implode('|', WOWHEAD_PAGES_BRANCHES) . ')-)?([a-z]+)$/', $shelf, $m)) return [null, null];
    $kind = $m[2];
    if (!in_array($kind, [...WOWHEAD_PAGES_KINDS, 'list', 'guide'], true)) return [null, null];
    return [$m[1] !== '' ? $m[1] : 'forever', $kind];
}

/** The newest record of each page of a shelf, as the cache keeps them; a list's or guide's shelf by its query. */
function wowhead_db_shelf_records(string $shelf, array $dirs, string $kind): iterable
{
    return in_array($kind, ['list', 'guide'], true) ? wowhead_pages($shelf, $dirs) : wowhead_pages_each($shelf, $dirs);
}

// ------------------------------------------------------------------ what is due again

/**
 * The pages the crawl should read again because their row is due (due_at passed): [kind => [ids]], oldest first, at
 * most $limit in all ([wowhead] recheck_pages, 300). Forever's npc, object, item and quest pages only: the crawl reads
 * the rest by itself. Without the table (no database yet), nothing.
 */
function wowhead_db_due_pages(?int $limit = null): array
{
    $limit ??= max(0, (int)config('wowhead', 'recheck_pages', 300));
    if ($limit <= 0) return [];
    try {
        if (!table_exists(WOWHEAD_DB_TABLE)) return [];
        $out = [];
        foreach (rows("SELECT kind, id FROM " . WOWHEAD_DB_TABLE . " WHERE source = 'page' AND branch = 'forever' AND kind IN ('npc', 'object', 'item', 'quest')
                       AND due_at IS NOT NULL AND due_at <= NOW() ORDER BY due_at LIMIT " . (int)$limit) as $r) $out[$r['kind']][] = (int)$r['id'];
        return $out;
    } catch (Throwable $e) {
        return [];
    }
}
