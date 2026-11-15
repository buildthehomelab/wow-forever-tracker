<?php
// Wowhead's pages as a source of rows (docs/WOWHEAD-PAGES.md). The tooltips (app/wowhead.php) say what exists; the
// pages say where it comes from: the creatures and chests that drop an item, with how often players saw it; who
// sells it; who starts and ends a quest. A script cannot ask for a page (Wowhead answers 403), so they are read
// slowly from a browser tab by tools/wowhead-pages/crawler.js, which keeps numbers only, and kept in the repository
// (data/wowhead-pages/<kind>.jsonl, one page a line). The tracker itself never asks Wowhead for a page: this
// file reads the cache and hands source_tables() the same evidence every other source gives.
//
// The round trip, from The Forge › Imports: *Download the crawler* gives crawler.js with the pages this tracker wants
// next already queued (wowhead_pages_queue); it runs in a browser tab on wowhead.com and saves wowhead-pages.jsonl;
// *Send pages* merges that file into data/wowhead-pages (wowhead_pages_merge) and makes the import card.
//
//   an item page   tabs dropped-by, contained-in-object, mined-from-object, gathered-from-object: rows {id, count,
//                  outof}; tab sold-by: rows {id, stock, cost: [money, ...]}
//   a quest page   Quick Facts lines "Start: [url=/forever/npc=123]", "End: [url=/forever/object=456]"
require_once FT_APP . '/sources.php';

const WOWHEAD_PAGES_MIN_LOOTS = 10;    // a drop counts from this many looted corpses (or opened chests) ...
const WOWHEAD_PAGES_MIN_DROPS = 2;     // ... in which the item fell at least twice: once is a sighting, not a rate
const WOWHEAD_PAGES_WORLD_DROP = 15;   // an item this many different creatures drop is nobody's own loot
/** The tabs of an item page that are loot of a creature or of a chest; every other source tab is counted only. */
const WOWHEAD_PAGES_DROP_TABS = ['dropped-by' => 'npc', 'contained-in-object' => 'go', 'mined-from-object' => 'go', 'gathered-from-object' => 'go'];
const WOWHEAD_PAGES_OTHER_TABS = ['reward-from-q', 'contained-in-item', 'created-by', 'pick-pocketed-from', 'skinned-from', 'fished-in', 'disenchanted-from', 'prospected-from', 'milled-from', 'salvaged-from'];

/** Where pages are kept: data/wowhead-pages, outside the repository (a copy of Wowhead's data is not republished
 *  with the code); tools/wowhead-pages/cache is read too, for a copy someone keeps there. The newer answer wins. */
function wowhead_pages_dirs(): array { return [FT_ROOT . '/tools/wowhead-pages/cache', wowhead_pages_dir()]; }
function wowhead_pages_dir(): string { return FT_ROOT . '/data/wowhead-pages'; }
const WOWHEAD_PAGES_KINDS = ['item', 'npc', 'quest', 'object', 'spell', 'zone', 'faction', 'itemset'];
const WOWHEAD_PAGES_BRANCHES = ['forever', 'classic'];

/** Where a crawler line is kept (tools/wowhead_pages.py shelf_of): 'item' for Forever's item pages, as before there
 *  were branches; 'classic-npc'; 'forever-list' for the list pages that named every id of a branch. */
function wowhead_pages_shelf(array $raw): string
{
    $branch = (string)($raw['branch'] ?? 'forever');
    if (($raw['kind'] ?? '') === 'list') return "$branch-list";
    return $branch === 'forever' ? (string)$raw['kind'] : $branch . '-' . $raw['kind'];
}

/** What a record is one of on its shelf: a page's id, a list's query. */
function wowhead_pages_entity(array $record): int|string|null
{
    if (($record['kind'] ?? '') === 'list') return is_string($record['query'] ?? null) ? $record['query'] : null;
    return is_int($record['id'] ?? null) && $record['id'] > 0 ? $record['id'] : null;
}

/** The pages of one shelf ('item', 'classic-npc', 'forever-list'): [id or query => record], the newest answer of
 *  each. A line that does not read is skipped. */
function wowhead_pages(string $kind, ?array $dirs = null): array
{
    $pages = [];
    foreach ($dirs ?? wowhead_pages_dirs() as $dir) {
        $handle = @fopen("$dir/$kind.jsonl", 'r');
        if (!$handle) continue;
        while (($line = fgets($handle)) !== false) {
            $record = json_decode($line, true);
            $key = is_array($record) ? wowhead_pages_entity($record) : null;
            if ($key === null) continue;
            if (isset($pages[$key]) && (int)($pages[$key]['fetched'] ?? 0) >= (int)($record['fetched'] ?? 0)) continue;
            $pages[$key] = $record;
        }
        fclose($handle);
    }
    return $pages;
}

/** A vendor row's cost is money and nothing else: [1500], [1500, 0, 0], [1500, [], []]. */
function wowhead_pages_money_only($cost): bool
{
    if (!is_array($cost)) return false;
    foreach (array_slice(array_values($cost), 1) as $part) if (!($part === 0 || $part === null || $part === [])) return false;
    return true;
}

/** The creatures, objects and items a Quick Facts line links to after its label ("Start", "End"): [[kind, id], …]. */
function wowhead_pages_links(array $quick, string $label): array
{
    $out = [];
    foreach ($quick as $line) {
        if (!is_string($line) || !preg_match('/^' . preg_quote($label, '/') . '\s*:/i', $line)) continue;
        if (preg_match_all('#/(npc|object|item)=(\d+)#', $line, $m, PREG_SET_ORDER)) foreach ($m as $link) $out[] = [$link[1], (int)$link[2]];
    }
    return $out;
}

/**
 * The evidence in pages, as source_tables() takes it: [evidence, the newest page's time]. $items and $quests are
 * [id => record] (wowhead_pages); the drops and vendors of every item page are given (the server's rules keep the
 * gaps, and the rest is compared with the drops the server already has), and what was left out is counted for the
 * items of $gapItems only ([id => true]), since the others are no question the card answers.
 */
function wowhead_pages_evidence(array $items, array $quests, array $gapItems = []): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => [], 'left' => []];
    $left = ['wowhead_item_unknown' => 0, 'wowhead_no_source' => 0, 'wowhead_only_other_source' => 0, 'wowhead_drop_world' => 0,
             'wowhead_drop_few' => 0, 'wowhead_drop_not_counted' => 0, 'wowhead_vendor_other_cost' => 0, 'wowhead_quest_unknown' => 0, 'wowhead_quest_started_by_item' => 0];
    $newest = 0;
    foreach ($items as $item => $page) {
        $gap = isset($gapItems[$item]);
        $newest = max($newest, (int)($page['fetched'] ?? 0));
        if (($page['status'] ?? '') !== 'ok') { if ($gap) $left['wowhead_item_unknown']++; continue; }
        $tabs = is_array($page['tabs'] ?? null) ? $page['tabs'] : [];
        $found = 0;
        foreach (WOWHEAD_PAGES_DROP_TABS as $tab => $kind) {
            $rows = array_values(array_filter((array)($tabs[$tab]['rows'] ?? []), fn($r) => is_array($r) && (int)($r['id'] ?? 0) > 0));
            if (!$rows) continue;
            $found += count($rows);
            // many creatures drop it: a world drop, which belongs to the shared tables no page describes
            if ($kind === 'npc' && max(count($rows), (int)($tabs[$tab]['total'] ?? 0)) >= WOWHEAD_PAGES_WORLD_DROP) { if ($gap) $left['wowhead_drop_world'] += count($rows); continue; }
            foreach ($rows as $row) {
                $count = $row['count'] ?? null; $outof = $row['outof'] ?? null;
                if (!is_numeric($count) || !is_numeric($outof) || $outof <= 0) { if ($gap) $left['wowhead_drop_not_counted']++; continue; }
                if ($outof < WOWHEAD_PAGES_MIN_LOOTS || $count < WOWHEAD_PAGES_MIN_DROPS) { if ($gap) $left['wowhead_drop_few']++; continue; }
                $ev['drop'][] = [$kind, (int)$row['id'], (int)$item, round(min(100, 100 * $count / $outof), 4)];
            }
        }
        foreach ((array)($tabs['sold-by']['rows'] ?? []) as $row) {
            if (!is_array($row) || (int)($row['id'] ?? 0) <= 0) continue;
            $found++;
            // paid with a currency or with items: the server's rules have no cost to give it
            if (!wowhead_pages_money_only($row['cost'] ?? null)) { if ($gap) $left['wowhead_vendor_other_cost']++; continue; }
            $ev['sell'][] = [(int)$row['id'], (int)$item, max(0, (int)($row['stock'] ?? 0))];
        }
        if (!$found && $gap) {
            $other = false;
            foreach (WOWHEAD_PAGES_OTHER_TABS as $tab) if (!empty($tabs[$tab]['rows'])) $other = true;
            $left[$other ? 'wowhead_only_other_source' : 'wowhead_no_source']++;
        }
    }
    foreach ($quests as $quest => $page) {
        $newest = max($newest, (int)($page['fetched'] ?? 0));
        if (($page['status'] ?? '') !== 'ok') { $left['wowhead_quest_unknown']++; continue; }
        $quick = is_array($page['quick'] ?? null) ? $page['quick'] : [];
        foreach (['start' => 'Start', 'end' => 'End'] as $role => $label) {
            foreach (wowhead_pages_links($quick, $label) as [$kind, $id]) {
                if ($kind === 'item') { if ($role === 'start') $left['wowhead_quest_started_by_item']++; continue; }
                $ev[$role][] = [$kind === 'npc' ? 'npc' : 'go', $id, (int)$quest];
            }
        }
    }
    $ev['left'] = array_filter($left);
    return [$ev, $newest];
}

/** The pages in the cache as an import card aimed at the last analysis' gaps, with the drops the server already has
 *  measured again. */
function wowhead_pages_import(): array
{
    if ($e = source_check()) return $e;
    $items = wowhead_pages('item'); $quests = wowhead_pages('quest');
    if (!$items && !$quests) return ['ok' => false, 'message' => t('No Wowhead page has been read yet: see docs/WOWHEAD-PAGES.md (tools/wowhead-pages/crawler.js reads them from a browser tab).', 'Aucune page Wowhead n’a encore été lue : voir docs/WOWHEAD-PAGES.md (tools/wowhead-pages/crawler.js les lit depuis un onglet de navigateur).')];
    $gaps = source_gaps();
    [$ev, $newest] = wowhead_pages_evidence($items, $quests, $gaps['items']);
    // the gaps no page was read for yet: `python tools/wowhead_pages.py todo` lists them for the crawler
    $unread = count(array_diff_key($gaps['items'], $items));
    $unreadQuests = count(array_diff_key($gaps['noGiver'] + $gaps['noEnder'], $quests));
    if ($unread) $ev['left']['wowhead_item_not_read'] = $unread;
    if ($unreadQuests) $ev['left']['wowhead_quest_not_read'] = $unreadQuests;
    $date = date('Y-m-d', $newest ?: time());
    $label = 'Wowhead ' . $date;
    [$tables, $left] = source_tables($ev, $label, $gaps);
    [$changes, $moved] = source_refresh($ev, 'wowhead');
    return source_card('wowhead', $label, 'wowhead@' . $date . '-' . (count($items) + count($quests)), $tables, $left + $moved, $changes);
}

// ------------------------------------------------------------------ the round trip with the browser crawler

/** A tab row holds numbers, true/false and null only, at any depth: the cache keeps no text. */
function wowhead_pages_numbers_only($value): bool
{
    if ($value === null || is_bool($value) || is_int($value) || is_float($value)) return true;
    if (!is_array($value)) return false;
    foreach ($value as $key => $v) if ((is_string($key) && !preg_match('/^[\w-]{1,40}$/', $key)) || !wowhead_pages_numbers_only($v)) return false;
    return true;
}

/** A crawler line as the cache keeps it, or null when it is not one (tools/wowhead_pages.py clean() does the same). */
function wowhead_pages_clean($record): ?array
{
    if (!is_array($record) || !in_array($record['status'] ?? null, ['ok', 'missing'], true) || !in_array($record['branch'] ?? 'forever', WOWHEAD_PAGES_BRANCHES, true)) return null;
    $fetched = $record['fetched'] ?? null;
    if (!is_int($fetched) || $fetched <= 0 || $fetched > time() + 86400) return null;
    $branch = ($record['branch'] ?? 'forever') === 'forever' ? [] : ['branch' => $record['branch']];
    if (($record['kind'] ?? null) === 'list') {
        // a list page: its query, its rows (numbers only, each with an id), how many it found, whether it was cut
        $query = $record['query'] ?? null;
        if (!is_string($query) || !preg_match('/^[a-z-]{1,30}(\?filter=[\d:;]{1,80})?$/', $query) || !is_array($record['rows'] ?? null) || $record['status'] !== 'ok') return null;
        $rows = array_values(array_filter($record['rows'], fn($r) => is_array($r) && is_int($r['id'] ?? null) && wowhead_pages_numbers_only($r)));
        $out = ['kind' => 'list', 'query' => $query, 'fetched' => $fetched, 'v' => (int)($record['v'] ?? 0), 'status' => 'ok'] + $branch;
        $out += ['rows' => $rows, 'found' => is_int($record['found'] ?? null) ? $record['found'] : count($rows), 'truncated' => !empty($record['truncated'])];
        if (is_int($record['cr'] ?? null)) $out['cr'] = $record['cr'];
        return $out;
    }
    if (!in_array($record['kind'] ?? null, WOWHEAD_PAGES_KINDS, true)) return null;
    $id = $record['id'] ?? null;
    if (!is_int($id) || $id <= 0 || $id > 2147483647) return null;
    $out = ['id' => $id, 'fetched' => $fetched, 'v' => (int)($record['v'] ?? 0), 'status' => $record['status']] + $branch;
    if ($record['status'] === 'missing') return $out;
    $quick = $record['quick'] ?? []; $tabs = $record['tabs'] ?? [];
    if (!is_array($quick) || !is_array($tabs) || ($tabs && array_is_list($tabs))) return null;
    // a tooltip's own text (crawlers before 2026-11-15 kept it) is no fact of the page
    $quick = array_map(fn($l) => is_string($l) ? trim((string)preg_replace('#\[tooltip[^\]]*\].*?\[/tooltip\]|\[span[^\]]*\]|\[/span\]#s', '', $l)) : $l, $quick);
    $out['quick'] = array_values(array_filter($quick, fn($l) => is_string($l) && $l !== '' && strlen($l) <= 300 && !str_contains($l, "\n")));
    $out['tabs'] = [];
    ksort($tabs);
    foreach ($tabs as $name => $tab) {
        if (!preg_match('/^[\w-]{1,60}$/', (string)$name) || !is_array($tab) || !is_array($tab['rows'] ?? null)) continue;
        $rows = array_values(array_filter($tab['rows'], fn($r) => is_array($r) && (!$r || !array_is_list($r)) && wowhead_pages_numbers_only($r)));
        $kept = ['template' => substr((string)($tab['template'] ?? ''), 0, 40), 'rows' => $rows];
        if (is_int($tab['total'] ?? null) && $tab['total'] > count($rows)) $kept['total'] = $tab['total'];
        $out['tabs'][(string)$name] = $kept;
    }
    if (!$out['tabs']) $out['tabs'] = new stdClass();
    foreach (['map', 'series'] as $extra) if (!empty($record[$extra]) && wowhead_pages_numbers_only($record[$extra])) $out[$extra] = $record[$extra];
    return $out;
}

/** What the crawler saved (one JSON line a page) into the cache: the newer answer of a page wins; each kind's file is
 *  written whole and sorted by id. Returns the counts: new, newer, older (kept the one we had), not_a_page. */
function wowhead_pages_merge(string $text, ?string $dir = null): array
{
    $dir ??= wowhead_pages_dir();
    $counts = ['new' => 0, 'newer' => 0, 'older' => 0, 'not_a_page' => 0];
    $incoming = [];
    foreach (preg_split('/\r?\n/', $text) as $line) {
        if (trim($line) === '') continue;
        $raw = json_decode($line, true);
        $record = wowhead_pages_clean($raw);
        if ($record === null) { $counts['not_a_page']++; continue; }
        $incoming[wowhead_pages_shelf($raw)][] = $record;
    }
    foreach ($incoming as $kind => $records) {
        $pages = wowhead_pages($kind, [$dir]);
        foreach ($records as $r) {
            $key = wowhead_pages_entity($r);
            $have = $pages[$key] ?? null;
            if ($have !== null && (int)($have['fetched'] ?? 0) >= $r['fetched']) { $counts['older']++; continue; }
            $counts[$have === null ? 'new' : 'newer']++;
            $pages[$key] = $r;
        }
        ksort($pages, SORT_STRING | SORT_NATURAL);
        @mkdir($dir, 0775, true);
        $scratch = "$dir/$kind.jsonl." . getmypid() . '.tmp';
        $out = '';
        foreach ($pages as $page) {
            if (array_key_exists('tabs', $page) && $page['tabs'] === []) $page['tabs'] = new stdClass();   // read back as a list, written as the object it is
            $out .= json_encode($page, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION) . "\n";
        }
        if (file_put_contents($scratch, $out) === false || !rename($scratch, "$dir/$kind.jsonl")) { @unlink($scratch); throw new RuntimeException("cannot write $dir/$kind.jsonl"); }
    }
    return $counts;
}

/**
 * The order the pages are worth reading in, from the gaps: ['item' => [...], 'quest' => [...]]. First the items other
 * content waits for ($waiting: the failing checks' text of quests, recipes, mounts, toys and spells, as [type, text]),
 * then the other gap items from $minItem up (below it: the original game's, nearly all test items), then the quests
 * without a giver or an ender. $read: [kind => [id => true]] pages the cache has and that are not due again.
 */
function wowhead_pages_order(array $gapItems, array $waiting, array $quests, array $read = [], int $minItem = 190000): array
{
    $first = [];
    $patterns = ['quest' => ['/item (\d+) not obtainable/', '/Quest giver: item (\d+)/'], 'toy' => ['/Item (\d+) has no source/']];
    $lists = ['recipe' => '/(?:cannot be obtained: |Taught by item )([\d, ]+)/', 'mount' => '/cannot be obtained: ([\d, ]+)/', 'spell' => '/Taught by item ([\d, ]+)/'];
    foreach ($waiting as [$type, $text]) {
        foreach ($patterns[$type] ?? [] as $re) if (preg_match_all($re, (string)$text, $m)) foreach ($m[1] as $id) $first[(int)$id] = true;
        if (isset($lists[$type]) && preg_match($lists[$type], (string)$text, $m)) foreach (preg_split('/\D+/', $m[1], -1, PREG_SPLIT_NO_EMPTY) as $id) $first[(int)$id] = true;
    }
    unset($first[0]);
    ksort($first);
    $rest = array_filter(array_keys($gapItems), fn($id) => $id >= $minItem && !isset($first[$id]));
    sort($rest);
    $quests = array_keys($quests);
    sort($quests);
    $unread = fn(string $kind, array $ids) => array_values(array_filter($ids, fn($id) => !isset($read[$kind][$id])));
    return ['item' => $unread('item', array_merge(array_keys($first), $rest)), 'quest' => $unread('quest', $quests)];
}

/** The pages this tracker wants next, from the last analysis (wowhead_pages_order). */
function wowhead_pages_queue(): array
{
    $gaps = source_gaps();
    $waiting = [];
    foreach (rows("SELECT type, checks FROM ft_entities WHERE internal = 0 AND status <> 'ok' AND type IN ('quest', 'recipe', 'mount', 'toy', 'spell') AND " . released_sql()) as $x) {
        foreach (failing_checks(json_decode((string)$x['checks'], true) ?: []) as $c) $waiting[] = [$x['type'], is_array($c['detail'] ?? null) ? (string)($c['detail']['en'] ?? '') : (string)($c['detail'] ?? '')];
    }
    $read = [];
    foreach (['item', 'quest'] as $kind) {
        foreach (wowhead_pages($kind) as $id => $page) if (!wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', $id)) $read[$kind][$id] = true;
    }
    return wowhead_pages_order($gaps['items'], $waiting, $gaps['noGiver'] + $gaps['noEnder'], $read, (int)config('wowhead', 'crawl_min_item', 190000));
}

/** crawler.js with the queue added and started: what the browser tab runs. $full: the whole database too
 *  (WHC.full(): every list of Forever and Classic first, then the pages they name, after the queue). */
function wowhead_pages_crawler(array $queue, bool $full = false): string
{
    $js = (string)file_get_contents(FT_ROOT . '/tools/wowhead-pages/crawler.js');
    $lines = ["\n// ---- queued by the tracker on " . date('Y-m-d H:i') . ': ' . implode(', ', array_map(fn($k) => count($queue[$k]) . " $k pages", array_keys($queue)))];
    $lines[] = '(async () => {';
    foreach ($queue as $kind => $ids) if ($ids) $lines[] = '  await WHC.add(' . json_encode($kind) . ', ' . json_encode(array_values($ids)) . ');';
    if ($full) $lines[] = '  await WHC.full();';
    $lines[] = '  WHC.start();';
    $lines[] = "  console.log('Wowhead crawler: ' + (await WHC.status()).queued + ' pages queued. WHC.status() says how far it is; WHC.save() saves what it read.');";
    $lines[] = '})();';
    return $js . implode("\n", $lines) . "\n";
}
