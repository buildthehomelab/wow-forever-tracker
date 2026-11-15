<?php
// Wowhead's pages as a source of rows (docs/WOWHEAD-PAGES.md). The tooltips (app/wowhead.php) say what exists; the
// pages say where it comes from: the creatures and chests that drop an item, with how often players saw it; who
// sells it; who starts and ends a quest. A script cannot ask for a page (Wowhead answers 403), so they are read
// slowly from a browser tab by tools/wowhead-pages/crawler.js, which keeps numbers only, and kept in the repository
// (tools/wowhead-pages/cache/<kind>.jsonl, one page a line). The tracker itself never asks Wowhead for a page: this
// file reads the cache and hands source_tables() the same evidence every other source gives.
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

/** Where pages are kept: the cache that comes with the tracker, then data/wowhead-pages (pages read since, put there
 *  by hand or by a mount). The newer answer of a page wins. */
function wowhead_pages_dirs(): array { return [FT_ROOT . '/tools/wowhead-pages/cache', FT_ROOT . '/data/wowhead-pages']; }

/** The pages of one kind: [id => record], the newest answer of each. A line that does not read is skipped. */
function wowhead_pages(string $kind, ?array $dirs = null): array
{
    $pages = [];
    foreach ($dirs ?? wowhead_pages_dirs() as $dir) {
        $handle = @fopen("$dir/$kind.jsonl", 'r');
        if (!$handle) continue;
        while (($line = fgets($handle)) !== false) {
            $record = json_decode($line, true);
            if (!is_array($record) || !is_int($record['id'] ?? null) || $record['id'] <= 0) continue;
            if (isset($pages[$record['id']]) && (int)($pages[$record['id']]['fetched'] ?? 0) >= (int)($record['fetched'] ?? 0)) continue;
            $pages[$record['id']] = $record;
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
