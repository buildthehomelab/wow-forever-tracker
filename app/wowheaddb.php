<?php
// Wowhead's answers in the answers table (ft_source_answers, source 'wowhead', app/sourceanswers.php; docs/WOWHEAD-PAGES.md
// "The Wowhead rows"): the tooltips (data/wowhead/<kind>/<id>.json, app/wowhead.php and tools/ft/wowhead.py, feed
// 'tooltip') and the pages the browser crawler read (data/wowhead-pages/<shelf>.jsonl, app/wowheadpages.php, feed
// 'page'). The files stay what the analysis and the imports read; the rows say what changed on Wowhead and when, and
// which answers are due to be read again.
//
// A row's data is the answer as the files keep it; a page's whole is the whole page as the crawler read it (names and
// text too: crawler records from v3 on). The tracker never asks Wowhead for a page: due pages go to the crawl's queue
// (wowhead_pages_queue 'recheck'), and due tooltips are asked again by the analysis as before.
require_once FT_APP . '/wowhead.php';
require_once FT_APP . '/wowheadpages.php';
require_once FT_APP . '/sourceanswers.php';

/** The tooltip kinds the tooltip cache holds (data/wowhead/<kind>/), as the page kinds name them. */
const WOWHEAD_DB_TOOLTIP_KINDS = ['npc', 'object', 'item', 'quest', 'spell', 'zone', 'faction', 'itemset', 'achievement', 'currency'];

/** The name a tooltip of the cache gives a kind's id, or null (the page records keep none before crawler v3). */
function wowhead_db_tooltip_name(string $kind, int $id, ?string $root = null): ?string
{
    if (!in_array($kind, WOWHEAD_DB_TOOLTIP_KINDS, true) || $id <= 0) return null;
    $data = json_decode((string)@file_get_contents(($root ?? FT_ROOT . '/data/wowhead') . "/$kind/$id.json"), true);
    return is_array($data) && is_string($data['name'] ?? null) && $data['name'] !== '' ? mb_substr($data['name'], 0, 255) : null;
}

/**
 * A tooltip answer as a row (source_answers_row). The hash leaves out the time it was fetched, and a creature's or object's tooltip
 * text (older answers were kept without it: its coming back is no change of Wowhead's).
 */
function wowhead_db_tooltip_row(string $kind, int $id, array $data, ?string $branch = null): ?array
{
    if ($id <= 0 || !preg_match('/^[a-z-]{1,16}$/', $kind)) return null;
    $kept = $data;
    unset($kept['fetched']);
    $hashed = $kept;
    if (in_array($kind, ['npc', 'object'], true)) unset($hashed['tooltip']);
    $missing = !empty($data['missing']);
    return source_answers_row(['source' => 'wowhead', 'feed' => 'tooltip', 'branch' => $branch ?? ((string)(config('wowhead', 'branch', 'forever') ?: 'forever')),
        'kind' => $kind, 'ref' => (string)$id, 'id' => $id, 'name' => $missing ? null : ($data['name'] ?? null), 'status' => $missing ? 'missing' : 'found',
        'data' => $kept, 'hash' => source_answers_hash($hashed), 'fetched' => (int)($data['fetched'] ?? 0)]);
}

/**
 * A crawler record as a row. $clean is the record as the cache keeps it (wowhead_pages_clean: numbers only), $whole
 * what the crawler read of the whole page ($raw['full'], crawler v3: names, Quick Facts with their text, every tab row
 * as Wowhead gives it, the map, what the page's links name), or null. $names: a tooltip name for a page without its
 * own (a callable kind, id → ?string).
 */
function wowhead_db_page_row(array $clean, ?array $whole = null, ?callable $names = null): ?array
{
    $branch = (string)($clean['branch'] ?? 'forever');
    $list = in_array($clean['kind'] ?? '', ['list', 'guide'], true);
    $ref = wowhead_pages_entity($clean);
    if ($ref === null) return null;
    // the shelf says what a page is (the cache's records of 'item' pages carry no kind of their own)
    $kind = (string)($clean['kind'] ?? '');
    if (!preg_match('/^[a-z-]{1,16}$/', $kind)) return null;
    $kept = $clean;
    unset($kept['fetched'], $kept['v']);
    $id = $list ? null : (int)$ref;
    $name = is_string($whole['name'] ?? null) && $whole['name'] !== '' ? $whole['name'] : null;
    if ($name === null && $id !== null && $branch === 'forever' && $names) $name = $names($kind, $id);
    return source_answers_row(['source' => 'wowhead', 'feed' => 'page', 'branch' => $branch, 'kind' => $kind, 'ref' => (string)$ref, 'id' => $id, 'name' => $name,
        'status' => ($clean['status'] ?? '') === 'missing' ? 'missing' : 'found', 'version' => (string)(int)($clean['v'] ?? 0),
        'data' => $kept, 'whole' => is_array($whole) && $whole ? $whole : null, 'fetched' => (int)($clean['fetched'] ?? 0)]);
}

/** Writes rows and never fails the caller (source_answers_try). */
function wowhead_db_try(array $rows): int { return source_answers_try($rows); }

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

/**
 * Puts what the files hold into the table (source_answers_backfill, $state its part of data/source-answers.json):
 * every tooltip file written since the last run (all of them the first time), and every page shelf whose file changed
 * since (its size or time). $data: another data folder (the tests'). Returns how many rows were written.
 */
function wowhead_db_backfill(array &$state, mysqli $link, ?string $data, callable $say): int
{
    $pageDirs = $data === null ? wowhead_pages_dirs() : ["$data/wowhead-pages"];
    $started = time();
    $tooltips = 0; $pages = 0;
    // tooltips: the files written since the last run (a second's margin: a file written while the last run read)
    $root = ($data ?? FT_ROOT . '/data') . '/wowhead';
    $since = max(0, (int)($state['tooltips_since'] ?? 0) - 1);
    $branch = (string)(config('wowhead', 'branch', 'forever') ?: 'forever');
    $batch = [];
    foreach (glob("$root/*", GLOB_ONLYDIR) ?: [] as $dir) {
        $kind = basename($dir);
        if (!preg_match('/^[a-z-]{1,16}$/', $kind)) continue;
        foreach (new DirectoryIterator($dir) as $file) {
            if (!$file->isFile() || !preg_match('/^(\d+)\.json$/', $file->getFilename(), $m) || $file->getMTime() < $since) continue;
            $answer = json_decode((string)@file_get_contents($file->getPathname()), true);
            if (!is_array($answer)) continue;
            $batch[] = wowhead_db_tooltip_row($kind, (int)$m[1], $answer, $branch);
            if (count($batch) >= 2000) { $tooltips += source_answers_put($batch, $link); $batch = []; }
        }
    }
    $tooltips += source_answers_put($batch, $link);
    $say("wowhead: $tooltips tooltip(s) written");
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
                if (count($batch) >= 1000) { $n += source_answers_put($batch, $link); $batch = []; }
            }
            $n += source_answers_put($batch, $link);
            $state['shelves'][$path] = $mark;
            $pages += $n;
            $say("wowhead: pages of $shelf, $n written");
        }
    }
    $state['tooltips_since'] = $started;
    return $tooltips + $pages;
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
        if (!table_exists(SOURCE_ANSWERS_TABLE)) return [];
        $out = [];
        foreach (rows("SELECT kind, id FROM " . SOURCE_ANSWERS_TABLE . " WHERE source = 'wowhead' AND feed = 'page' AND branch = 'forever' AND kind IN ('npc', 'object', 'item', 'quest')
                       AND due_at IS NOT NULL AND due_at <= NOW() ORDER BY due_at LIMIT " . (int)$limit) as $r) $out[$r['kind']][] = (int)$r['id'];
        return $out;
    } catch (Throwable $e) {
        return [];
    }
}
