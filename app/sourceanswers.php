<?php
// Every answer the tracker got from an outside source, whole, in one table of the tracker's database (docs/SOURCES.md,
// "The answers table"). The files under data/ stay what the analysis and the imports read; the table is for people:
// The Forge › Query reads it (SELECT … FROM ft_source_answers), and it says what a source changed and when, and which
// answers are due to be read again.
//
//   ft_source_answers   one row an answer: source (a key of SOURCES: wowhead, icyveins, questie, ...), feed (what of
//                       the source: Wowhead's 'tooltip' or 'page', Icy Veins' 'api' or 'list', ForeverChanges' 'site',
//                       a downloaded file's 'file'), branch, kind, ref (an id, a list's query, a file's path and a
//                       record of it), id, name, status ('found', 'missing': the source does not know it, 'gone': a
//                       newer version of the source no longer holds it), version (a commit, a release, a crawler's
//                       record version), data (the answer), whole (the whole answer when data is less: Wowhead's whole
//                       page, Icy Veins' whole API answer, a ForeverChanges page's text), when it was fetched, first
//                       seen and last changed, and when it is due to be read again (due_at, NULL: never by itself).
//
// changed_at moves only when what the source says changed: the hash of `data` (never the time it was fetched), of
// `whole` when both answers carry a whole one with a hash, or the status. An answer older than the one held changes
// nothing, so the backfill can run as often as it likes. The tracker asks a source again by that source's own rules;
// due_at only says when (the same rules: source_answers_due_case).
//
// Where each source's answers come from (and the backfill reads them again):
//   wowhead          data/wowhead/<kind>/<id>.json (tooltips), data/wowhead-pages/<shelf>.jsonl (pages): app/wowheaddb.php
//   icyveins         data/icyveins/<kind>/<id>.json.gz (one API answer each), data/icyveins/<kind>.ids.json (the lists)
//   foreverchanges   data/foreverchanges/pages.jsonl (each reading), site/ and the blob store (what was read),
//                    parsed.jsonl (what a page states)
//   questie, norgannondb, eglink, foreverdb
//                    data/<source>/<commit or release>/: every file the tracker downloaded of that version
//   atlasloot        data/atlasloot/<CurseForge file id>.zip: every file of the addon
//   vmangos, classicdb
//                    data/<source>/pack.cdbpack (sent through the Imports page; the tracker never downloads them)
// A downloaded file is cut into records so that a row stays small and means something: a JSON file by its keys (a
// creature's loot, a vendor), a Lua file by its numbered entries ([25] = {...}, R(25, ...)); whatever is left between
// them is kept too ('~rest' rows), so that nothing a file says is lost.
require_once FT_APP . '/wowhead.php';

const SOURCE_ANSWERS_TABLE = 'ft_source_answers';
/** Rows written in one INSERT, and the bytes one INSERT may hold (MySQL's max_allowed_packet is 16 MB at least). */
const SOURCE_ANSWERS_CHUNK_ROWS = 200;
const SOURCE_ANSWERS_CHUNK_BYTES = 8 * 1048576;
/** A downloaded file is cut into records of about this size at most (a single record of a file may be larger). */
const SOURCE_ANSWERS_RECORD_BYTES = 262144;
/** A file larger than this is kept as its size and checksum only (none of the sources has one near it). */
const SOURCE_ANSWERS_FILE_BYTES = 256 * 1048576;
/** The longest ref; a longer one ends in the SHA-1 of the whole. */
const SOURCE_ANSWERS_REF = 400;
/** The sources the backfill reads, in this order. */
const SOURCE_ANSWERS_SOURCES = ['wowhead', 'icyveins', 'foreverchanges', 'questie', 'norgannondb', 'eglink', 'foreverdb', 'atlasloot', 'vmangos', 'classicdb'];
/** The sources whose answers are the files of a version (a commit, a release, a pack): feed 'file'. */
const SOURCE_ANSWERS_VERSIONED = ['questie', 'norgannondb', 'eglink', 'foreverdb', 'atlasloot', 'vmangos', 'classicdb'];

function source_answers_ensure(?mysqli $link = null): void
{
    static $done = [];
    $link ??= db();
    if (isset($done[spl_object_id($link)])) return;
    $link->query('CREATE TABLE IF NOT EXISTS ' . SOURCE_ANSWERS_TABLE . " (
        source VARCHAR(16) NOT NULL, feed VARCHAR(16) NOT NULL, branch VARCHAR(32) NOT NULL DEFAULT '', kind VARCHAR(64) NOT NULL,
        ref VARCHAR(" . SOURCE_ANSWERS_REF . ") NOT NULL, id INT NULL, name VARCHAR(255) NULL, status VARCHAR(8) NOT NULL,
        version VARCHAR(64) NOT NULL DEFAULT '', data LONGTEXT NOT NULL, hash CHAR(40) NOT NULL,
        whole LONGTEXT NULL, whole_hash CHAR(40) NULL, whole_at DATETIME NULL,
        fetched_at DATETIME NOT NULL, first_seen DATETIME NOT NULL, changed_at DATETIME NOT NULL, due_at DATETIME NULL,
        PRIMARY KEY (source, feed, branch, kind, ref), KEY ix_id (source, kind, id), KEY ix_name (name), KEY ix_changed (changed_at),
        KEY ix_due (due_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
    // the Wowhead table of the first version (ft_wowhead, 2026-11-21): its rows move here, under source 'wowhead'
    if ($link->query("SHOW TABLES LIKE 'ft_wowhead'")->num_rows) {
        $link->query('INSERT IGNORE INTO ' . SOURCE_ANSWERS_TABLE . ' (source, feed, branch, kind, ref, id, name, status, version, data, hash, whole, whole_hash, whole_at,
            fetched_at, first_seen, changed_at, due_at) SELECT \'wowhead\', source, branch, kind, ref, id, name, status, CAST(version AS CHAR), data, hash, page, page_hash,
            page_at, fetched_at, first_seen, changed_at, due_at FROM ft_wowhead');
        $link->query('DROP TABLE ft_wowhead');
    }
    $done[spl_object_id($link)] = true;
}

/** A value with its object keys sorted at every depth, so that the same answer always hashes the same. */
function source_answers_canonical($value)
{
    if (!is_array($value)) return $value;
    if (!array_is_list($value)) ksort($value, SORT_STRING);
    return array_map('source_answers_canonical', $value);
}

function source_answers_json($value): string
{
    return (string)json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION | JSON_INVALID_UTF8_SUBSTITUTE);
}

function source_answers_hash($value): string { return sha1(source_answers_json(source_answers_canonical($value))); }

/**
 * A row as the table takes it, from what a source's builder says: source, feed, kind, ref and fetched (a Unix time)
 * are needed; branch, id, name, status ('found'), version, data (any value: kept as JSON), hash (of data unless
 * given), whole (any value, or null) and whole_hash (of whole unless given; null: whole is kept but never compared)
 * are not. Null when it is no row.
 */
function source_answers_row(array $r): ?array
{
    $fetched = (int)($r['fetched'] ?? 0);
    $ref = (string)($r['ref'] ?? '');
    if ($fetched <= 0 || $ref === '') return null;
    foreach (['source' => 16, 'feed' => 16, 'kind' => 64] as $key => $max) if (!preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]{0,' . ($max - 1) . '}$/', (string)($r[$key] ?? ''))) return null;
    if (strlen($ref) > SOURCE_ANSWERS_REF) $ref = substr($ref, 0, SOURCE_ANSWERS_REF - 41) . '#' . sha1($ref);
    $branch = (string)($r['branch'] ?? '');
    if (!preg_match('/^[A-Za-z0-9._-]{0,32}$/', $branch)) return null;
    $name = is_string($r['name'] ?? null) && trim($r['name']) !== '' ? mb_substr(trim($r['name']), 0, 255) : null;
    $status = in_array($r['status'] ?? 'found', ['found', 'missing', 'gone'], true) ? ($r['status'] ?? 'found') : 'found';
    $data = $r['data'] ?? null;
    $whole = $r['whole'] ?? null;
    return ['source' => (string)$r['source'], 'feed' => (string)$r['feed'], 'branch' => $branch, 'kind' => (string)$r['kind'], 'ref' => $ref,
        'id' => isset($r['id']) && is_numeric($r['id']) && (int)$r['id'] > 0 && (int)$r['id'] <= 2147483647 ? (int)$r['id'] : null, 'name' => $name,
        'status' => $status, 'version' => mb_substr((string)($r['version'] ?? ''), 0, 64), 'data' => source_answers_json($data),
        'hash' => (string)($r['hash'] ?? source_answers_hash($data)), 'whole' => $whole === null ? null : source_answers_json($whole),
        'whole_hash' => $whole === null ? null : (array_key_exists('whole_hash', $r) ? $r['whole_hash'] : source_answers_hash($whole)), 'fetched' => $fetched, '_row' => true];
}

/**
 * The INSERT of some rows. A row older than the one held changes nothing (but a name the held row lacks); a newer one
 * replaces data, and whole when it brings one (an answer without it keeps the one held, whole_at says how old it is).
 * changed_at moves to the new answer's time when the hash of data differs, or the status, or that of whole when both
 * have one. The assignments run in order: changed_at reads the old values, so it comes first.
 */
function source_answers_insert_sql(mysqli $link, array $rows): string
{
    $q = fn($v) => $v === null ? 'NULL' : (is_int($v) ? (string)$v : "'" . $link->real_escape_string((string)$v) . "'");
    $values = [];
    foreach ($rows as $r) {
        $at = 'FROM_UNIXTIME(' . (int)$r['fetched'] . ')';
        $values[] = '(' . implode(',', [$q($r['source']), $q($r['feed']), $q($r['branch']), $q($r['kind']), $q($r['ref']), $q($r['id']), $q($r['name']), $q($r['status']),
            $q($r['version']), $q($r['data']), $q($r['hash']), $q($r['whole']), $q($r['whole_hash']), $r['whole'] === null ? 'NULL' : $at, $at, $at, $at]) . ')';
    }
    $newer = 'VALUES(fetched_at) > fetched_at';
    $hasWhole = 'VALUES(whole) IS NOT NULL';
    return 'INSERT INTO ' . SOURCE_ANSWERS_TABLE . ' (source, feed, branch, kind, ref, id, name, status, version, data, hash, whole, whole_hash, whole_at, fetched_at, first_seen, changed_at) VALUES '
        . implode(',', $values) . ' ON DUPLICATE KEY UPDATE '
        . "changed_at = IF($newer AND (VALUES(hash) <> hash OR VALUES(status) <> status OR (VALUES(whole_hash) IS NOT NULL AND whole_hash IS NOT NULL AND VALUES(whole_hash) <> whole_hash)), VALUES(fetched_at), changed_at), "
        . 'first_seen = LEAST(first_seen, VALUES(fetched_at)), '
        . "id = IF($newer AND VALUES(id) IS NOT NULL, VALUES(id), COALESCE(id, VALUES(id))), "
        . "name = IF($newer AND VALUES(name) IS NOT NULL, VALUES(name), COALESCE(name, VALUES(name))), "
        . "whole_hash = IF($newer AND $hasWhole, VALUES(whole_hash), whole_hash), "
        . "whole_at = IF($newer AND $hasWhole, VALUES(whole_at), whole_at), "
        . "whole = IF($newer AND $hasWhole, VALUES(whole), whole), "
        . "status = IF($newer, VALUES(status), status), version = IF($newer, VALUES(version), version), "
        . "data = IF($newer, VALUES(data), data), hash = IF($newer, VALUES(hash), hash), "
        . "fetched_at = IF($newer, VALUES(fetched_at), fetched_at)";
}

// ------------------------------------------------------------------ when an answer is due again: each source's rules

/**
 * The SQL value of due_at for a source's rows, by the rules that source asks again by. $settings overrides the
 * configuration (the tests): refresh_days, recheck_days, older_days, epoch.
 *   wowhead          wowhead_stale(): older than "ask every source again" at once; missing after [wowhead]
 *                    recheck_days; the rest after [wowhead] refresh_days give or take a quarter by id (never when 0)
 *   icyveins         icyveins_fresh(): older than "ask every source again" at once; missing after 7 days, the rest
 *                    after 14; a kind's list of ids after a day
 *   foreverchanges   the pull's due(): after [foreverchanges] older days (14), a page the site did not have four
 *                    times later
 *   the rest         NULL: a new version of the source is looked for as a whole (its import), never one answer
 */
function source_answers_due_case(string $source, array $settings = []): string
{
    $epoch = (int)($settings['epoch'] ?? source_refresh_epoch());
    $again = $epoch > 0 ? ' WHEN fetched_at < FROM_UNIXTIME(' . $epoch . ') THEN fetched_at' : '';
    $days = fn(float $d) => 'fetched_at + INTERVAL ' . (int)round($d * 86400) . ' SECOND';
    switch ($source) {
        case 'wowhead':
            $refresh = (float)($settings['refresh_days'] ?? max(0.0, (float)config('wowhead', 'refresh_days', 30)));
            $recheck = (float)($settings['recheck_days'] ?? ((float)config('wowhead', 'recheck_days', 7) ?: 7));
            $spread = '(0.75 + MOD(CAST(COALESCE(id, 0) AS SIGNED) * 2654435761, 1000) / 2000)';
            return "CASE$again WHEN status = 'missing' THEN " . $days($recheck)
                . ($refresh > 0 ? ' ELSE fetched_at + INTERVAL ROUND(' . sprintf('%.6F', $refresh * 86400) . " * $spread) SECOND" : ' ELSE NULL') . ' END';
        case 'icyveins':
            return "CASE$again WHEN feed = 'list' THEN " . $days(1) . " WHEN status = 'missing' THEN " . $days(7) . ' ELSE ' . $days(14) . ' END';
        case 'foreverchanges':
            $older = (float)($settings['older_days'] ?? max(1, (int)config('foreverchanges', 'older', 14)));
            return "CASE WHEN status = 'missing' THEN " . $days(4 * $older) . ' ELSE ' . $days($older) . ' END';
        default:
            return 'NULL';
    }
}

/** The UPDATE that sets due_at of a source's rows ($where limits them). */
function source_answers_due_sql(string $source, string $where = '1', array $settings = []): string
{
    return 'UPDATE ' . SOURCE_ANSWERS_TABLE . ' SET due_at = IF(status = \'gone\', NULL, ' . source_answers_due_case($source, $settings) . ")
        WHERE source = '" . addslashes($source) . "' AND ($where)";
}

// ------------------------------------------------------------------ writing

/** Writes rows (each as source_answers_row takes it) and sets when they are due. Returns how many were sent. */
function source_answers_put(array $rows, ?mysqli $link = null): int
{
    // a row source_answers_row() made already, or what a builder says
    $rows = array_values(array_filter(array_map(fn($r) => is_array($r) ? (!empty($r['_row']) ? $r : source_answers_row($r)) : null, $rows)));
    if (!$rows) return 0;
    $link ??= db();
    source_answers_ensure($link);
    $chunk = []; $bytes = 0; $sent = 0;
    $flush = function () use (&$chunk, &$bytes, &$sent, $link) {
        if (!$chunk) return;
        $link->query(source_answers_insert_sql($link, $chunk));
        $sent += count($chunk);
        $chunk = []; $bytes = 0;
    };
    $since = [];
    foreach ($rows as $r) {
        $size = strlen($r['data']) + strlen((string)$r['whole']) + strlen($r['ref']) + 512;
        if ($chunk && (count($chunk) >= SOURCE_ANSWERS_CHUNK_ROWS || $bytes + $size > SOURCE_ANSWERS_CHUNK_BYTES)) $flush();
        $chunk[] = $r; $bytes += $size;
        $since[$r['source']] = min($since[$r['source']] ?? PHP_INT_MAX, (int)$r['fetched']);
    }
    $flush();
    // the rows just written: their due time from their (maybe new) fetch time
    foreach ($since as $source => $at) $link->query(source_answers_due_sql($source, 'fetched_at >= FROM_UNIXTIME(' . (int)$at . ')'));
    return $sent;
}

/** The tracker's database, or null when it cannot be reached (db() would end the request with an error page). */
function source_answers_link(): ?mysqli
{
    static $link = false;
    if ($link !== false) return $link;
    try {
        $link = new mysqli((string)config('database', 'host', '127.0.0.1'), (string)config('database', 'user', ''), (string)config('database', 'password', ''),
            (string)config('database', 'tracker', 'tracker'), (int)config('database', 'port', 3306));
        $link->set_charset('utf8mb4');
    } catch (Throwable $e) {
        error_log('Forever Tracker: no database for ' . SOURCE_ANSWERS_TABLE . ': ' . $e->getMessage());
        $link = null;
    }
    return $link;
}

/** Writes rows and never fails the caller: the files are what the tracker keeps, the table follows them. */
function source_answers_try(array $rows): int
{
    if (!$rows || !($link = source_answers_link())) return 0;
    try { return source_answers_put($rows, $link); }
    catch (Throwable $e) { error_log('Forever Tracker: answers not written to ' . SOURCE_ANSWERS_TABLE . ': ' . $e->getMessage()); return 0; }
}

/** The rows of a versioned source that a newer version no longer holds: status 'gone' as of $at. Returns how many. */
function source_answers_gone(mysqli $link, string $source, string $version, int $at): int
{
    $statement = $link->prepare('UPDATE ' . SOURCE_ANSWERS_TABLE . " SET status = 'gone', changed_at = FROM_UNIXTIME(?), due_at = NULL
        WHERE source = ? AND feed = 'file' AND version <> ? AND status <> 'gone' AND fetched_at < FROM_UNIXTIME(?)");
    $statement->bind_param('issi', $at, $source, $version, $at);
    $statement->execute();
    return $statement->affected_rows;
}

// ------------------------------------------------------------------ a downloaded file, as records

/** A file's kind: its name without its extensions ('foreverItemDB', 'loot', 'NPCs'), 'file' when nothing is left. */
function source_answers_file_kind(string $path): string
{
    $name = preg_replace('/[^A-Za-z0-9._-]+/', '-', basename(str_replace('\\', '/', $path)));
    $name = (string)preg_replace('/(\.[A-Za-z0-9]{1,8})+$/', '', $name);
    $name = trim(substr($name, 0, 64), '.-_');
    return $name === '' ? 'file' : $name;
}

/** A record's id from the last part of its key: '25', 'npc:25', 'object:9|spell:3'; null without one. */
function source_answers_key_id(string $key): ?int
{
    if (preg_match('/^\d{1,10}$/', $key)) return (int)$key;
    return preg_match('/^[a-z]+:(\d{1,10})\b/i', $key, $m) ? (int)$m[1] : null;
}

/**
 * A JSON value cut into records: [[JSON pointer, value]]. A value of at most SOURCE_ANSWERS_RECORD_BYTES is one
 * record; a larger object or list gives each of its children that is itself an object or a list (cut again when it is
 * large), and its other children together ('/~rest', '/~rest1', ... when they are many).
 */
function source_answers_split_json($value, string $pointer = ''): array
{
    if (!is_array($value) || !$value || strlen(source_answers_json($value)) <= SOURCE_ANSWERS_RECORD_BYTES) return [[$pointer, $value]];
    $out = []; $rest = []; $restBytes = 0; $parts = 0;
    $restOut = function () use (&$out, &$rest, &$restBytes, &$parts, $pointer) {
        if (!$rest) return;
        $out[] = [$pointer . '/~rest' . ($parts ? $parts : ''), $rest];
        $parts++; $rest = []; $restBytes = 0;
    };
    foreach ($value as $key => $child) {
        $at = $pointer . '/' . str_replace(['~', '/'], ['~0', '~1'], (string)$key);
        if (is_array($child) && $child) { array_push($out, ...source_answers_split_json($child, $at)); continue; }
        $bytes = strlen(source_answers_json($child)) + strlen((string)$key) + 4;
        if ($rest && $restBytes + $bytes > SOURCE_ANSWERS_RECORD_BYTES) $restOut();
        $rest[(string)$key] = $child; $restBytes += $bytes;
    }
    $restOut();
    return $out;
}

/**
 * A Lua file cut into records: [[label, text, id or null]]. A small file is one record (label ''). A larger one
 * gives each numbered entry of a table ("[25] = {...}" lines and what is indented under them, NorgannonDB's
 * "R(25, ...)" lines) as "<table>/<id>", the table being the last assignment at the start of a line (ns.npcs,
 * QuestieDB.itemData); the lines between entries (headers, a table's closing brace) go together into '~rest' records.
 */
function source_answers_split_lua(string $text): array
{
    if (strlen($text) <= SOURCE_ANSWERS_RECORD_BYTES) return [['', $text, null]];
    $out = []; $seen = [];
    $table = ''; $depth = null; $current = null;
    $rest = ''; $parts = 0;
    $restOut = function (bool $all = false) use (&$out, &$rest, &$parts) {
        if ($rest === '' || (!$all && strlen($rest) < SOURCE_ANSWERS_RECORD_BYTES)) return;
        $out[] = ['~rest' . ($parts ? $parts : ''), $rest, null];
        $parts++; $rest = '';
    };
    $close = function () use (&$current, &$out, &$seen) {
        if ($current === null) return;
        $label = $current[0];
        $seen[$label] = ($seen[$label] ?? 0) + 1;
        if ($seen[$label] > 1) $label .= '~' . $seen[$label];
        $out[] = [$label, $current[1], $current[2]];
        $current = null;
    };
    foreach (preg_split('/(?<=\n)/', $text) as $line) {
        if ($line === '') continue;
        if (preg_match('/^(?:local\s+)?([A-Za-z_][\w.:]{0,60})\s*=(?!=)/', $line, $m) && !preg_match('/^R\(/', $line)) {
            $close();
            $table = $m[1]; $depth = null;
            $rest .= $line; $restOut();
            continue;
        }
        if (preg_match('/^(\s*)(?:\[(\d{1,10})\]\s*=|R\((\d{1,10}),)/', $line, $m) && ($depth === null || strlen($m[1]) <= $depth)) {
            $close();
            $depth = strlen($m[1]);
            $id = (int)(($m[2] ?? '') !== '' ? $m[2] : $m[3]);
            $current = [($table === '' ? '' : "$table/") . $id, $line, $id];
            continue;
        }
        // what is indented under an entry is the entry's, and so is its closing brace at the entry's own indentation
        $indent = strlen($line) - strlen(ltrim($line, " \t"));
        if ($current !== null && trim($line) !== '' && ($indent > $depth || ($indent === $depth && preg_match('/^\s*\}\s*,?\s*$/', $line)))) { $current[1] .= $line; continue; }
        if ($current !== null && trim($line) === '') { $current[1] .= $line; continue; }
        $close();
        $rest .= $line; $restOut();
    }
    $close();
    $restOut(true);
    return $out;
}

/** The name a Lua record starts with: the first quoted string after "[id] = {" or "R(id,". */
function source_answers_lua_name(string $text): ?string
{
    return preg_match('/^\s*(?:\[\d+\]\s*=\s*\{\s*|R\(\d+,\s*)(["\'])((?:(?!\1)[^\\\\\n]|\\\\.){1,255})\1/', $text, $m) ? stripcslashes($m[2]) : null;
}

/**
 * The rows of one downloaded file of a source's version: JSON by its keys, Lua by its entries, other text whole (by
 * lines when large), anything else as base64 (or its size and checksum when large). $path is its path in the version
 * (the ref, then '#' and the record).
 */
function source_answers_file_rows(string $source, string $version, string $path, string $body, int $fetched): array
{
    $path = ltrim(str_replace('\\', '/', $path), '/');
    $base = ['source' => $source, 'feed' => 'file', 'branch' => '', 'kind' => source_answers_file_kind($path), 'version' => $version, 'fetched' => $fetched];
    $row = fn(string $part, $data, ?int $id = null, ?string $name = null) => $base + ['ref' => $path . ($part === '' ? '' : "#$part"), 'data' => $data, 'id' => $id, 'name' => $name];
    if (strlen($body) > SOURCE_ANSWERS_FILE_BYTES) return [$row('', ['size' => strlen($body), 'sha256' => hash('sha256', $body), 'too_large' => true])];
    $text = !str_contains($body, "\0") && mb_check_encoding($body, 'UTF-8');
    if ($text && preg_match('/\.json$/i', $path) && is_array($value = json_decode($body, true))) {
        $out = [];
        foreach (source_answers_split_json($value) as [$pointer, $part]) {
            $key = $pointer === '' ? '' : str_replace(['~1', '~0'], ['/', '~'], substr($pointer, strrpos($pointer, '/') + 1));
            $out[] = $row($pointer, $part, source_answers_key_id($key), is_array($part) && is_string($part['name'] ?? null) ? $part['name'] : null);
        }
        return $out;
    }
    if ($text && preg_match('/\.lua$/i', $path)) {
        return array_map(fn($r) => $row($r[0], ['text' => $r[1]], $r[2], $r[2] === null ? null : source_answers_lua_name($r[1])), source_answers_split_lua($body));
    }
    if ($text) {
        if (strlen($body) <= SOURCE_ANSWERS_RECORD_BYTES) return [$row('', ['text' => $body])];
        $out = []; $chunk = ''; $first = 1; $n = 0;
        foreach (preg_split('/(?<=\n)/', $body) as $line) {
            if ($chunk !== '' && strlen($chunk) + strlen($line) > SOURCE_ANSWERS_RECORD_BYTES) { $out[] = $row("lines/$first-$n", ['text' => $chunk]); $chunk = ''; $first = $n + 1; }
            $chunk .= $line; $n++;
        }
        if ($chunk !== '') $out[] = $row("lines/$first-$n", ['text' => $chunk]);
        return $out;
    }
    return [$row('', strlen($body) <= SOURCE_ANSWERS_RECORD_BYTES ? ['base64' => base64_encode($body), 'size' => strlen($body)] : ['size' => strlen($body), 'sha256' => hash('sha256', $body)])];
}

/** [path in the version => body getter] of what a version holds: a folder's files, a zip's, or a pack's JSON. */
function source_answers_version_files(string $path): array
{
    $out = [];
    if (is_dir($path)) {
        $walk = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($path, FilesystemIterator::SKIP_DOTS));
        foreach ($walk as $file) {
            if (!$file->isFile() || preg_match('/\.(part|link|tmp)$/', $file->getFilename())) continue;
            $name = $file->getPathname();
            $out[str_replace('\\', '/', substr($name, strlen($path) + 1))] = fn() => (string)@file_get_contents($name);
        }
        ksort($out, SORT_STRING);
    } elseif (preg_match('/\.zip$/i', $path)) {
        $zip = new ZipArchive();
        if ($zip->open($path) !== true) return [];
        for ($i = 0; $i < $zip->numFiles; $i++) {
            $name = (string)$zip->getNameIndex($i);
            if (str_ends_with($name, '/') || str_ends_with($name, '\\')) continue;
            $out[str_replace('\\', '/', $name)] = fn() => (string)$zip->getFromIndex($i);
        }
    } elseif (preg_match('/\.cdbpack$/i', $path)) {
        $out['pack.json'] = function () use ($path) { $raw = (string)@file_get_contents($path); return substr($raw, 0, 2) === "\x1f\x8b" ? (string)@gzdecode($raw) : $raw; };
    }
    return $out;
}

/** What says a version changed on disk since it was read: its files' count and bytes (a folder), or its size and time. */
function source_answers_version_mark(string $path): string
{
    if (!is_dir($path)) return @filesize($path) . ':' . @filemtime($path);
    $n = 0; $bytes = 0;
    foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator($path, FilesystemIterator::SKIP_DOTS)) as $file) {
        if (!$file->isFile() || preg_match('/\.(part|link|tmp)$/', $file->getFilename())) continue;
        $n++; $bytes += $file->getSize();
    }
    return "$n:$bytes";
}

/**
 * Every file of a version of a source as rows, then the rows of older versions it no longer holds marked 'gone'.
 * $fetched: when the version was downloaded. Returns how many rows were written.
 */
function source_answers_put_version(string $source, string $version, string $path, int $fetched, mysqli $link, ?callable $say = null): int
{
    @ini_set('memory_limit', '2048M');
    $n = 0; $batch = []; $bytes = 0;
    foreach (source_answers_version_files($path) as $file => $body) {
        foreach (source_answers_file_rows($source, $version, $file, $body(), $fetched) as $r) {
            $batch[] = $r;
            $bytes += strlen(source_answers_json($r['data']));
            if (count($batch) >= 2000 || $bytes > 32 * 1048576) { $n += source_answers_put($batch, $link); $batch = []; $bytes = 0; }
        }
    }
    $n += source_answers_put($batch, $link);
    $gone = $n ? source_answers_gone($link, $source, $version, $fetched) : 0;
    if ($say) $say("$source $version: $n record(s)" . ($gone ? ", $gone no longer there" : ''));
    return $n;
}

// ------------------------------------------------------------------ the backfill: what the files already hold

function source_answers_state_file(?string $data = null): string { return ($data ?? FT_ROOT . '/data') . '/source-answers.json'; }

/** Raise when a backfill must read every file again (a new column filled from the files). */
const SOURCE_ANSWERS_BACKFILL_V = 1;

/**
 * Puts what the files hold into the table, source by source ($only: some of SOURCE_ANSWERS_SOURCES): what was written
 * since the last run, all of it the first time or with $all. Returns [source => rows written], or ['busy' => true]
 * when another backfill is running. $data: another data folder (the tests').
 */
function source_answers_backfill(bool $all = false, ?callable $say = null, ?mysqli $link = null, ?string $data = null, ?array $only = null): array
{
    $say ??= fn(string $line) => null;
    $link ??= db();
    source_answers_ensure($link);
    $folder = $data ?? FT_ROOT . '/data';
    @mkdir($folder, 0775, true);
    $lock = @fopen("$folder/source-answers.lock", 'c');
    if ($lock && !flock($lock, LOCK_EX | LOCK_NB)) { fclose($lock); return ['busy' => true]; }
    $statePath = source_answers_state_file($folder);
    $state = json_decode((string)@file_get_contents($statePath), true);
    if (!is_array($state) || (int)($state['v'] ?? 0) !== SOURCE_ANSWERS_BACKFILL_V) $state = ['v' => SOURCE_ANSWERS_BACKFILL_V, 'sources' => []];
    $counts = [];
    try {
        foreach (SOURCE_ANSWERS_SOURCES as $source) {
            if ($only !== null && !in_array($source, $only, true)) continue;
            $mine = $all ? [] : (array)($state['sources'][$source] ?? []);
            if ($source === 'wowhead') {
                require_once FT_APP . '/wowheaddb.php';
                $counts[$source] = wowhead_db_backfill($mine, $link, $data, $say);
            } elseif ($source === 'icyveins') $counts[$source] = icyveins_answers_backfill($mine, $link, $folder, $say);
            elseif ($source === 'foreverchanges') $counts[$source] = foreverchanges_answers_backfill($mine, $link, $folder, $say);
            else $counts[$source] = source_answers_backfill_version($source, $mine, $link, $folder, $say);
            $state['sources'][$source] = $mine;
            @file_put_contents($statePath, json_encode($state, JSON_UNESCAPED_SLASHES) . "\n", LOCK_EX);
            // the due times follow the source's settings and "ask every source again" as they are now
            $link->query(source_answers_due_sql($source));
        }
    } finally {
        if ($lock) { flock($lock, LOCK_UN); fclose($lock); }
    }
    return $counts;
}

/** The backfill of some sources that never fails the caller (after an import wrote their files). */
function source_answers_backfill_try(array $only): array
{
    if (!($link = source_answers_link())) return [];
    try { return source_answers_backfill(false, null, $link, null, $only); }
    catch (Throwable $e) { error_log('Forever Tracker: answers of ' . implode(', ', $only) . ' not written to ' . SOURCE_ANSWERS_TABLE . ': ' . $e->getMessage()); return []; }
}

/** The versions a source keeps on disk: [version => path], the newest last (by the time it was written). */
function source_answers_versions(string $source, string $data): array
{
    $found = [];
    switch ($source) {
        case 'questie': case 'norgannondb': case 'eglink':
            foreach (glob("$data/$source/*", GLOB_ONLYDIR) ?: [] as $dir) if (preg_match('/^[0-9a-f]{40}$/', basename($dir))) $found[basename($dir)] = $dir;
            break;
        case 'foreverdb':
            foreach (glob("$data/foreverdb/*", GLOB_ONLYDIR) ?: [] as $dir) if (preg_match('/^[\w.\-]+$/', basename($dir))) $found[basename($dir)] = $dir;
            break;
        case 'atlasloot':
            foreach (glob("$data/atlasloot/*.zip") ?: [] as $zip) if (preg_match('/^\d+$/', basename($zip, '.zip'))) $found[basename($zip, '.zip')] = $zip;
            break;
        case 'vmangos': case 'classicdb':
            if (is_file($pack = "$data/$source/pack.cdbpack")) $found[date('Y-m-d H:i:s', (int)filemtime($pack))] = $pack;
            break;
    }
    uksort($found, fn($a, $b) => [(int)@filemtime($found[$a]), $a] <=> [(int)@filemtime($found[$b]), $b]);
    return $found;
}

/**
 * The newest version of a versioned source, when it was not written yet (or changed on disk since): every file of
 * it. Older versions on disk were superseded before the table existed; each new version is written when it is
 * downloaded (source_answers_version_try), so that changed_at and 'gone' say what a version changed.
 */
function source_answers_backfill_version(string $source, array &$state, mysqli $link, string $data, callable $say): int
{
    $versions = source_answers_versions($source, $data);
    if (!$versions) return 0;
    $version = (string)array_key_last($versions);
    $path = $versions[$version];
    $mark = source_answers_version_mark($path);
    if (($state['version'] ?? null) === $version && ($state['mark'] ?? null) === $mark) return 0;
    $n = source_answers_put_version($source, $version, $path, (int)filemtime($path), $link, $say);
    $state = ['version' => $version, 'mark' => $mark];
    return $n;
}

/** After a source downloaded a version: its files into the table (the backfill of that source; never fails). */
function source_answers_version_try(string $source): void
{
    source_answers_backfill_try([$source]);
}

// ------------------------------------------------------------------ Icy Veins (app/icyveins.php)

/**
 * An Icy Veins answer as a row: the mirror's record (data/icyveins/<kind>/<id>.json.gz: the entity, its children and
 * relations, or "missing") as data, and the whole API answer as whole when it is at hand (its link metadata and
 * tooltips, never compared: they are the same for all).
 */
function icyveins_answer_row(string $kind, int $id, array $data, ?array $whole = null): ?array
{
    $kept = $data;
    unset($kept['fetched']);
    $entity = is_array($data['entity'] ?? null) ? $data['entity'] : [];
    $name = $entity['name'] ?? $entity['title'] ?? null;
    return source_answers_row(['source' => 'icyveins', 'feed' => 'api', 'branch' => 'wowf', 'kind' => $kind, 'ref' => (string)$id, 'id' => $id,
        'name' => is_string($name) ? $name : null, 'status' => !empty($data['missing']) ? 'missing' : 'found', 'data' => $kept,
        'whole' => $whole, 'whole_hash' => null, 'fetched' => (int)($data['fetched'] ?? 0)]);
}

/** A kind's list of ids (data/icyveins/<kind>.ids.json) as a row. */
function icyveins_list_row(string $kind, array $list): ?array
{
    $kept = $list;
    unset($kept['fetched']);
    return source_answers_row(['source' => 'icyveins', 'feed' => 'list', 'branch' => 'wowf', 'kind' => $kind, 'ref' => 'ids', 'data' => $kept, 'fetched' => (int)($list['fetched'] ?? 0)]);
}

/** The mirror's files written since the last run (all of them the first time), and the lists. */
function icyveins_answers_backfill(array &$state, mysqli $link, string $data, callable $say): int
{
    $root = "$data/icyveins";
    $since = max(0, (int)($state['since'] ?? 0) - 1);   // a second's margin: a file written while the last run read
    $started = time();
    $n = 0; $batch = [];
    foreach (glob("$root/*", GLOB_ONLYDIR) ?: [] as $dir) {
        $kind = basename($dir);
        if (!preg_match('/^[a-z-]{1,32}$/', $kind)) continue;
        foreach (new DirectoryIterator($dir) as $file) {
            if (!$file->isFile() || !preg_match('/^(\d+)\.json(\.gz)?$/', $file->getFilename(), $m) || $file->getMTime() < $since) continue;
            $raw = (string)@file_get_contents($file->getPathname());
            if (!empty($m[2])) $raw = (string)@gzdecode($raw);
            $answer = json_decode($raw, true);
            if (!is_array($answer)) continue;
            $batch[] = icyveins_answer_row($kind, (int)$m[1], $answer);
            if (count($batch) >= 1000) { $n += source_answers_put($batch, $link); $batch = []; }
        }
    }
    foreach (glob("$root/*.ids.json") ?: [] as $path) {
        if (filemtime($path) < $since || !is_array($list = json_decode((string)@file_get_contents($path), true))) continue;
        $batch[] = icyveins_list_row(basename($path, '.ids.json'), $list);
    }
    $n += source_answers_put($batch, $link);
    $state['since'] = $started;
    $say("icyveins: $n answer(s) written");
    return $n;
}

// ------------------------------------------------------------------ ForeverChanges (tools/ft/foreverchanges_site.py)

/**
 * A reading of foreverchanges.pro as a row: {"f": file, "at", "s": 200 or 404, "key"} of pages.jsonl. $body: what
 * was read (the page's <title> and <main>, unzipped; a map file), $states: what the page states (parsed.jsonl).
 * A map data file's data is the file itself; a page's data is what it states, its text the whole.
 */
function foreverchanges_answer_row(array $reading, ?string $body, $states = null): ?array
{
    $file = (string)($reading['f'] ?? '');
    $status = (int)($reading['s'] ?? 0);
    if ($file === '' || !in_array($status, [200, 404], true)) return null;
    $kind = preg_match('#^(quest|item|map)/#', $file, $m) ? $m[1] : 'site';
    $id = in_array($kind, ['quest', 'item'], true) && preg_match('#^\w+/(\d+)#', $file, $m2) ? (int)$m2[1] : null;
    $row = ['source' => 'foreverchanges', 'feed' => 'site', 'kind' => $kind, 'ref' => $file, 'id' => $id, 'status' => $status === 404 ? 'missing' : 'found',
        'fetched' => (int)($reading['at'] ?? 0), 'version' => (string)($reading['key'] ?? '')];
    if ($status === 404) return source_answers_row($row + ['data' => ['status' => 404]]);
    $json = str_ends_with($file, '.json') && $body !== null ? json_decode($body, true) : null;
    if (is_array($json)) return source_answers_row($row + ['data' => $json]);
    $name = is_array($states) ? ($states['title'] ?? $states['name'] ?? null) : null;
    $text = $body === null ? null : (mb_check_encoding($body, 'UTF-8') ? $body : mb_convert_encoding($body, 'UTF-8', 'UTF-8'));
    return source_answers_row($row + ['name' => is_string($name) ? $name : null, 'data' => ['status' => 200, 'states' => $states],
        'whole' => $text, 'whole_hash' => $text === null ? null : sha1($text)]);
}

/** The readings added to pages.jsonl since the last run (all of them the first time): the last of each file. */
function foreverchanges_answers_backfill(array &$state, mysqli $link, string $data, callable $say): int
{
    $folder = "$data/foreverchanges";
    $log = "$folder/pages.jsonl";
    if (!is_file($log)) return 0;
    $from = (int)($state['offset'] ?? 0);
    if ($from > filesize($log)) $from = 0;   // a new log
    $handle = fopen($log, 'r');
    fseek($handle, $from);
    $last = [];
    while (($line = fgets($handle)) !== false) {
        if (!str_ends_with($line, "\n")) break;   // a line still being written: the next run reads it
        $from += strlen($line);
        $reading = json_decode($line, true);
        if (is_array($reading) && is_string($reading['f'] ?? null)) $last[$reading['f']] = $reading;
    }
    fclose($handle);
    $state['offset'] = $from;
    if (!$last) return 0;
    $parsed = [];
    if (is_file("$folder/parsed.jsonl")) foreach (new SplFileObject("$folder/parsed.jsonl") as $line) {
        $row = json_decode((string)$line, true);
        if (is_array($row) && is_string($row['key'] ?? null)) $parsed[$row['key']] = $row['rec'] ?? null;
    }
    $n = 0; $batch = [];
    foreach ($last as $file => $reading) {
        $body = null;
        $key = (string)($reading['key'] ?? '');
        foreach ([preg_match('/^sha256-[0-9a-f]{64}$/', $key) ? "$data/sources/blobs/" . substr($key, 7, 2) . "/$key" : null, "$folder/site/$file"] as $path) {
            if ($path !== null && is_file($path)) { $body = (string)file_get_contents($path); break; }
        }
        if ($body !== null && str_ends_with($file, '.gz')) $body = @gzdecode($body) ?: null;
        $batch[] = foreverchanges_answer_row($reading, $body, $parsed[$key] ?? null);
        if (count($batch) >= 500) { $n += source_answers_put($batch, $link); $batch = []; }
    }
    $n += source_answers_put($batch, $link);
    $say("foreverchanges: $n reading(s) written");
    return $n;
}
