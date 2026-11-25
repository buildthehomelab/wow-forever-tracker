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
//   an npc page    tab drops: rows {id (the item), count, outof}; sells: rows {id, avail, cost: [[money, ...], ...]};
//                  starts, ends: rows {id (the quest)}
//   an object page tabs contains (the openings as the tab's total), mining, herbalism; starts, ends
require_once FT_APP . '/sources.php';
require_once FT_APP . '/gather.php';
require_once FT_APP . '/wowheaddb.php';

const WOWHEAD_PAGES_MIN_LOOTS = 10;    // a drop counts from this many looted corpses (or opened chests) ...
const WOWHEAD_PAGES_MIN_DROPS = 2;     // ... in which the item fell at least twice: once is a sighting, not a rate,
                                       // used only for an item nothing else gives (wowhead_pages_evidence)
/** A page the tracker queues that the crawl's tab read longer ago than this (seconds) is read again: the tracker
 *  queues only pages it does not hold or holds and wants again, so a younger copy in the tab is one on its way to the
 *  tracker (the tab sends what it read every few seconds to minutes). */
const WOWHEAD_PAGES_AGAIN = 86400;
const WOWHEAD_PAGES_WORLD_DROP = 15;   // an item this many different creatures drop is nobody's own loot
/** The tabs of an item page that are loot of a creature or of a chest; every other source tab is counted only. */
const WOWHEAD_PAGES_DROP_TABS = ['dropped-by' => 'npc', 'contained-in-object' => 'go', 'mined-from-object' => 'go', 'gathered-from-object' => 'go',
    'skinned-from' => 'skin', 'pick-pocketed-from' => 'pick', 'contained-in-item' => 'item'];
/** The other source tabs of an item page, counted only, each with the counter of a gap item that has nothing else. A
 *  quest reward (reward-from-q) is evidence of its own (wowhead_pages_evidence), counted here when its row does not
 *  say whether the item is a fixed reward or a choice. */
const WOWHEAD_PAGES_OTHER_TABS = ['created-by' => 'wowhead_only_craft', 'reward-from-q' => 'wowhead_only_quest_reward',
    'disenchanted-from' => 'wowhead_only_other_source', 'prospected-from' => 'wowhead_only_other_source', 'milled-from' => 'wowhead_only_other_source', 'salvaged-from' => 'wowhead_only_other_source'];

/** Where pages are kept: data/wowhead-pages, outside the repository (a copy of Wowhead's data is not republished
 *  with the code); tools/wowhead-pages/cache is read too, for a copy someone keeps there. The newer answer wins. */
function wowhead_pages_dirs(): array { return [FT_ROOT . '/tools/wowhead-pages/cache', wowhead_pages_dir()]; }
function wowhead_pages_dir(): string { return FT_ROOT . '/data/wowhead-pages'; }
const WOWHEAD_PAGES_KINDS = ['item', 'npc', 'quest', 'object', 'spell', 'zone', 'faction', 'itemset'];
/** A guide's path under /<branch>/guide/ (the crawler's parseKey takes the same). */
const WOWHEAD_GUIDE_QUERY = '#^[a-z0-9-]{1,80}(/[a-z0-9-]{1,80}){0,3}$#';
/** Wowhead's Craftsman's Writs guide: each writ with its tier (Journeyman 1, Expert 2, Artisan 3). */
const WOWHEAD_WRIT_GUIDE = 'professions/craftsmans-writs-overview-recipes-rewards';
/** The tier names of the writ guide, by the number the crawler keeps. */
const WOWHEAD_WRIT_TIERS = [1 => 'Journeyman', 2 => 'Expert', 3 => 'Artisan'];
const WOWHEAD_PAGES_BRANCHES = ['forever', 'classic'];

/** Where a crawler line is kept (tools/wowhead_pages.py shelf_of): 'item' for Forever's item pages, as before there
 *  were branches; 'classic-npc'; 'forever-list' for the list pages that named every id of a branch. */
function wowhead_pages_shelf(array $raw): string
{
    $branch = (string)($raw['branch'] ?? 'forever');
    if (($raw['kind'] ?? '') === 'list') return "$branch-list";
    if (($raw['kind'] ?? '') === 'guide') return "$branch-guide";
    return $branch === 'forever' ? (string)$raw['kind'] : $branch . '-' . $raw['kind'];
}

/** What a record is one of on its shelf: a page's id, a list's query. */
function wowhead_pages_entity(array $record): int|string|null
{
    if (in_array($record['kind'] ?? '', ['list', 'guide'], true)) return is_string($record['query'] ?? null) ? $record['query'] : null;
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

/** The pages of one shelf as the crawl queue needs them, each kept small: its id, time and status, and of an item
 *  page the source tabs (wowhead_pages_has_source) and the zones it is fished in, each row its id only. The whole
 *  records of every item page do not fit in PHP's memory beside the queue's other work. */
function wowhead_pages_brief(string $kind, ?array $dirs = null): array
{
    static $tabs = null;
    $tabs ??= array_flip(array_merge(array_keys(WOWHEAD_PAGES_DROP_TABS), ['sold-by', WOWHEAD_PAGES_FISHED_IN]));
    $pages = [];
    foreach ($dirs ?? wowhead_pages_dirs() as $dir) {
        $handle = @fopen("$dir/$kind.jsonl", 'r');
        if (!$handle) continue;
        while (($line = fgets($handle)) !== false) {
            $record = json_decode($line, true);
            $key = is_array($record) ? wowhead_pages_entity($record) : null;
            if ($key === null) continue;
            if (isset($pages[$key]) && (int)($pages[$key]['fetched'] ?? 0) >= (int)($record['fetched'] ?? 0)) continue;
            $brief = ['id' => $record['id'] ?? $key, 'fetched' => (int)($record['fetched'] ?? 0), 'status' => (string)($record['status'] ?? ''), 'v' => (int)($record['v'] ?? 0)];
            foreach (array_intersect_key(is_array($record['tabs'] ?? null) ? $record['tabs'] : [], $tabs) as $tab => $data) {
                $rows = array_values(array_filter(array_map(fn($r) => is_array($r) && (int)($r['id'] ?? 0) > 0 ? ['id' => (int)$r['id']] : null, (array)($data['rows'] ?? []))));
                if ($rows) $brief['tabs'][$tab] = ['rows' => $rows];
            }
            $pages[$key] = $brief;
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

/** The tabs of an npc or object page that are its loot, and whose; the npc's other loot (own tables no source fills). */
const WOWHEAD_PAGES_PAGE_LOOT_TABS = ['npc' => ['drops' => 'npc', 'skinning' => 'skin', 'pickpocketing' => 'pick'], 'object' => ['contains' => 'go', 'mining' => 'go', 'herbalism' => 'go']];
const WOWHEAD_PAGES_PAGE_OTHER_LOOT = ['salvaging', 'fishing'];
/** A zone's fishing: the item page's Fished in tab (a row a zone, its count of the zone's catches) and the zone page's
 *  Fishing tab (a row an item, the tab's total the zone's catches). Both go to fishing_loot_template under the zone. */
const WOWHEAD_PAGES_FISHED_IN = 'fished-in';
const WOWHEAD_PAGES_ZONE_FISHING = 'fishing';

/** A vendor row's cost, as an item page's sold-by tab writes it ([money, currencies, items]) or an npc page's sells
 *  tab ([[money, currencies, items], ...], one list a way to pay): the first way to pay. */
function wowhead_pages_first_cost($cost)
{
    return is_array($cost) && isset($cost[0]) && is_array($cost[0]) && array_is_list($cost) && count($cost) >= 1 && (is_int($cost[0][0] ?? null) || is_float($cost[0][0] ?? null)) ? $cost[0] : $cost;
}

/** What a vendor row's cost ([money, currencies, items], each list [[id, count], ...]) asks besides money, as
 *  ft/costs.py keys the server's ItemExtendedCost rows: "c<id>x<count>" and "i<id>x<count>", sorted, comma-separated.
 *  '' for money only; null for a cost that cannot be read. */
function wowhead_pages_cost_key($cost): ?string
{
    if (!is_array($cost) || !array_is_list($cost)) return null;
    $parts = [];
    foreach ([1 => 'c', 2 => 'i'] as $at => $mark) {
        $list = $cost[$at] ?? [];
        if ($list === 0 || $list === null) continue;
        if (!is_array($list)) return null;
        foreach ($list as $pair) {
            if (!is_array($pair) || !is_numeric($pair[0] ?? null) || !is_numeric($pair[1] ?? null)) return null;
            if ((int)$pair[0] > 0 && (int)$pair[1] > 0) $parts[] = $mark . (int)$pair[0] . 'x' . (int)$pair[1];
        }
    }
    sort($parts, SORT_STRING);
    return implode(',', $parts);
}

/** Where a quest row of an item's reward-from-q tab gives the item: [count, 0 a fixed reward | 1 a choice], null when
 *  the row names it in neither list (a row read before Wowhead gave them, or an item the quest hands out otherwise). */
function wowhead_pages_reward_slot(array $row, int $item): ?array
{
    foreach (['itemrewards' => 0, 'itemchoices' => 1] as $list => $choice) {
        foreach ((array)($row[$list] ?? []) as $pair) {
            if (is_array($pair) && (int)($pair[0] ?? 0) === $item) return [max(1, (int)($pair[1] ?? 1)), $choice];
        }
    }
    return null;
}

/**
 * The evidence in pages, as source_tables() takes it: [evidence, the newest page's time].
 *
 * $items and $quests are [id => record] (wowhead_pages); $npcs and $objects any iterable of page records (the cache is
 * read a line at a time: a whole crawl holds tens of thousands of npc pages, see wowhead_pages_each). Drops come from
 * an item page's tabs (dropped-by, contained-in-object ...) and from an npc's or object's own page (drops, contains,
 * mining ...), whichever counted more loots; vendors from sold-by and an npc's sells tab; quest givers and enders from a
 * quest's Quick Facts and an npc's or object's starts and ends tabs.
 *
 * $keep ([item => true], null: all) limits the drops and vendors kept from npc and object pages to the items worth a
 * row: the gaps and the items of drops an import brought, which are measured again. What was left out is counted for
 * the items of $gapItems only ([id => true]), since the others are no question the card answers. $itemFacts
 * ([item => how many creatures drop it]) are item pages read elsewhere (Forever's, for Classic's pages): they tell a
 * world drop as the item's own page would. $notWorldDrop ([item => true]): items whose many creatures each get a row
 * of their own (a Season of Discovery currency every boss of a level drops, as Season of Discovery had it).
 */
function wowhead_pages_evidence(array $items, array $quests, array $gapItems = [], iterable $npcs = [], iterable $objects = [], ?array $keep = null, array $itemFacts = [], array $notWorldDrop = [], iterable $zones = [], ?array $fishTables = null): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => [], 'reward' => [], 'left' => [], 'fish_whole' => []];
    $left = ['wowhead_item_unknown' => 0, 'wowhead_no_source' => 0, 'wowhead_only_other_source' => 0, 'wowhead_only_craft' => 0, 'wowhead_only_fishing' => 0,
             'wowhead_only_quest_reward' => 0, 'wowhead_drop_world' => 0,
             'wowhead_drop_few' => 0, 'wowhead_drop_not_counted' => 0, 'wowhead_vendor_other_cost' => 0, 'wowhead_quest_unknown' => 0,
             'wowhead_quest_started_by_item' => 0, 'wowhead_other_loot' => 0, 'wowhead_drop_item_page_not_read' => 0];
    $newest = 0;
    $drops = [];        // "kind:id:item" => [kind, id, item, count, outof]: the best counted of what the pages say
    $droppers = [];     // item => how many creatures drop it, the most any page says
    $npcDroppers = [];  // item => how many npc pages list it
    $sells = [];        // "npc:item" => [npc, item, stock, what it asks besides money ('' none, null unreadable)]
    $rewards = [];      // "quest:item" => [quest, item, count, 0 fixed | 1 choice]
    $roles = ['start' => [], 'end' => []];
    $noSource = [];     // gap item => the counter it goes to when no other page gives it a source
    $itemRead = [];     // items whose own page was read: its Dropped by tab says how many creatures drop it
    foreach ($itemFacts as $item => $n) { $itemRead[(int)$item] = true; $droppers[(int)$item] = (int)$n; }
    $put = function (string $kind, int $id, int $item, $count, $outof) use (&$drops) {
        $key = "$kind:$id:$item";
        $counted = is_numeric($count) && is_numeric($outof) && $outof > 0;
        $have = $drops[$key] ?? null;
        if ($have !== null && (!$counted || (is_numeric($have[4]) && $have[4] >= $outof))) return;
        $drops[$key] = [$kind, $id, $item, $counted ? (float)$count : null, $counted ? (float)$outof : null];
    };
    $sell = function (int $npc, int $item, array $row) use (&$sells) {
        $cost = wowhead_pages_first_cost($row['cost'] ?? null);
        $sells["$npc:$item"] ??= [$npc, $item, max(0, (int)($row['stock'] ?? $row['avail'] ?? 0)), wowhead_pages_money_only($cost) ? '' : wowhead_pages_cost_key($cost)];
    };
    $ids = fn($rows) => array_values(array_filter((array)$rows, fn($r) => is_array($r) && (int)($r['id'] ?? 0) > 0));

    foreach ($items as $item => $page) {
        $newest = max($newest, (int)($page['fetched'] ?? 0));
        if (($page['status'] ?? '') !== 'ok') { if (isset($gapItems[$item])) $left['wowhead_item_unknown']++; continue; }
        $itemRead[$item] = true;
        $tabs = is_array($page['tabs'] ?? null) ? $page['tabs'] : [];
        $found = 0;
        foreach (WOWHEAD_PAGES_DROP_TABS as $tab => $kind) {
            $rows = $ids($tabs[$tab]['rows'] ?? []);
            $found += count($rows);
            if ($kind === 'npc') $droppers[$item] = max($droppers[$item] ?? 0, count($rows), (int)($tabs[$tab]['total'] ?? 0));
            foreach ($rows as $row) $put($kind, (int)$row['id'], (int)$item, $row['count'] ?? null, $row['outof'] ?? null);
        }
        foreach ($ids($tabs['sold-by']['rows'] ?? []) as $row) { $found++; $sell((int)$row['id'], (int)$item, $row); }
        // the zones it is fished in: each row's count of all that zone's catches
        foreach ($ids($tabs[WOWHEAD_PAGES_FISHED_IN]['rows'] ?? []) as $row) { $found++; $put('fish', (int)$row['id'], (int)$item, $row['count'] ?? null, $row['outof'] ?? null); }
        // a quest that rewards it: its row says whether as a fixed reward or a choice, and how many
        foreach ($ids($tabs['reward-from-q']['rows'] ?? []) as $row) {
            if (!($slot = wowhead_pages_reward_slot($row, (int)$item))) continue;
            $found++;
            $rewards[(int)$row['id'] . ':' . $item] ??= [(int)$row['id'], (int)$item, $slot[0], $slot[1]];
        }
        if (!$found && isset($gapItems[$item])) {
            $noSource[$item] = 'wowhead_no_source';
            foreach (WOWHEAD_PAGES_OTHER_TABS as $tab => $why) if (!empty($tabs[$tab]['rows'])) { $noSource[$item] = $why; break; }
        }
    }

    foreach (['npc' => $npcs, 'object' => $objects] as $type => $pages) {
        foreach ($pages as $page) {
            $id = (int)($page['id'] ?? 0);
            if ($id <= 0 || ($page['status'] ?? '') !== 'ok') continue;
            $newest = max($newest, (int)($page['fetched'] ?? 0));
            $tabs = is_array($page['tabs'] ?? null) ? $page['tabs'] : [];
            foreach (WOWHEAD_PAGES_PAGE_LOOT_TABS[$type] as $tab => $kind) {
                // a chest's page counts its openings once, as the tab's total; a creature's page on each row
                $opened = $tabs[$tab]['total'] ?? null;
                foreach ($ids($tabs[$tab]['rows'] ?? []) as $row) {
                    $item = (int)$row['id'];
                    if ($kind === 'npc') $npcDroppers[$item] = ($npcDroppers[$item] ?? 0) + 1;
                    if ($keep !== null && !isset($keep[$item])) continue;
                    $put($kind, $id, $item, $row['count'] ?? null, $row['outof'] ?? $opened);
                }
            }
            if ($type === 'npc') {
                foreach ($ids($tabs['sells']['rows'] ?? []) as $row) if ($keep === null || isset($keep[(int)$row['id']])) $sell($id, (int)$row['id'], $row);
                foreach (WOWHEAD_PAGES_PAGE_OTHER_LOOT as $tab) foreach ($ids($tabs[$tab]['rows'] ?? []) as $row) if (isset($gapItems[(int)$row['id']])) $left['wowhead_other_loot']++;
            }
            foreach (['start' => 'starts', 'end' => 'ends'] as $role => $tab) {
                foreach ($ids($tabs[$tab]['rows'] ?? []) as $row) $roles[$role][($type === 'npc' ? 'npc' : 'go') . ':' . $id . ':' . (int)$row['id']] = [$type === 'npc' ? 'npc' : 'go', $id, (int)$row['id']];
            }
        }
    }

    $wholeZones = [];
    // zones' fishing: a zone the server has no fishing table for takes its whole table (the realm catches nothing there:
    // Mount Hyjal, the Riverglades); one it has takes the items worth a row, as an npc page does
    foreach ($zones as $page) {
        $zone = (int)($page['id'] ?? 0);
        if ($zone <= 0 || ($page['status'] ?? '') !== 'ok') continue;
        $tab = $page['tabs'][WOWHEAD_PAGES_ZONE_FISHING] ?? null;
        if (!is_array($tab)) continue;
        $newest = max($newest, (int)($page['fetched'] ?? 0));
        $whole = $fishTables !== null && !isset($fishTables[$zone]);
        if ($whole) $wholeZones[$zone] = true;
        foreach ($ids($tab['rows'] ?? []) as $row) {
            if (!$whole && $keep !== null && !isset($keep[(int)$row['id']])) continue;
            $put('fish', $zone, (int)$row['id'], $row['count'] ?? null, $tab['total'] ?? null);
        }
    }

    // the drops, now that every page told how many creatures drop each item
    $given = [];
    $sighted = [];      // gap item => its drops seen once (kept only when nothing better gives it)
    $rated = [];        // items a counted drop or a money vendor gives
    foreach ($drops as [$kind, $id, $item, $count, $outof]) {
        $gap = isset($gapItems[$item]) || ($kind === 'fish' && isset($wholeZones[$id]));
        // many creatures drop it: a world drop, which belongs to the shared tables no page describes
        if ($kind === 'npc' && !isset($notWorldDrop[$item]) && max($droppers[$item] ?? 0, $npcDroppers[$item] ?? 0) >= WOWHEAD_PAGES_WORLD_DROP) { if ($gap) $left['wowhead_drop_world']++; continue; }
        // a creature's drop of a gap item, from the creature's page only: until every npc page is read, only the item's
        // own page tells a world drop from a creature's own loot
        if ($kind === 'npc' && $gap && !isset($itemRead[$item])) { $left['wowhead_drop_item_page_not_read']++; continue; }
        $given[$item] = true;
        if ($count === null) { if ($gap) $left['wowhead_drop_not_counted']++; continue; }
        if ($outof < WOWHEAD_PAGES_MIN_LOOTS || $count < WOWHEAD_PAGES_MIN_DROPS) {
            // a gap item seen dropping once on enough loots: kept aside, it is used when nothing better gives the item
            if ($gap && $outof >= WOWHEAD_PAGES_MIN_LOOTS && $count >= 1) $sighted[$item][] = [$kind, $id, $item, round(min(100, 100 * $count / $outof), 4)];
            elseif ($gap) $left['wowhead_drop_few']++;
            continue;
        }
        $ev['drop'][] = [$kind, $id, $item, round(min(100, 100 * $count / $outof), 4)];
        $rated[$item] = true;
    }
    foreach ($sells as [$npc, $item, $stock, $cost]) {
        $given[$item] = true;
        // paid with a currency or with items: the row carries what it asks, source_tables() names the server's
        // ItemExtendedCost that asks the same (a cost it cannot read is left out)
        if ($cost === null) { if (isset($gapItems[$item])) $left['wowhead_vendor_other_cost']++; continue; }
        $ev['sell'][] = $cost === '' ? [$npc, $item, $stock] : [$npc, $item, $stock, $cost];
        $rated[$item] = true;
    }
    foreach ($rewards as [$quest, $item]) $given[$item] = true;
    $ev['reward'] = array_values(array_filter($rewards, fn($r) => isset($gapItems[$r[1]])));
    // sightings (one drop in WOWHEAD_PAGES_MIN_LOOTS or more loots) of an item nobody can get and that no counted drop
    // or vendor gives: players' one count is a better rate than no source at all (user decision 2026-11-18)
    foreach ($sighted as $item => $rows) {
        if (isset($rated[$item])) { $left['wowhead_drop_few'] += count($rows); continue; }
        foreach ($rows as $row) $ev['drop'][] = $row;
    }
    foreach ($noSource as $item => $why) if (!isset($given[$item])) $left[$why]++;

    foreach ($quests as $quest => $page) {
        $newest = max($newest, (int)($page['fetched'] ?? 0));
        if (($page['status'] ?? '') !== 'ok') { $left['wowhead_quest_unknown']++; continue; }
        $quick = is_array($page['quick'] ?? null) ? $page['quick'] : [];
        foreach (['start' => 'Start', 'end' => 'End'] as $role => $label) {
            foreach (wowhead_pages_links($quick, $label) as [$kind, $id]) {
                if ($kind === 'item') { if ($role === 'start') $left['wowhead_quest_started_by_item']++; continue; }
                $kind = $kind === 'npc' ? 'npc' : 'go';
                $roles[$role]["$kind:$id:$quest"] ??= [$kind, $id, (int)$quest];
            }
        }
    }
    $ev['start'] = array_values($roles['start']);
    $ev['end'] = array_values($roles['end']);
    $ev['left'] = array_filter($left);
    // a list of [zone] rows, as a snapshot keeps it (snapshot_facts)
    $ev['fish_whole'] = array_map(fn($zone) => [$zone], array_keys($wholeZones));
    return [$ev, $newest];
}

/**
 * The turn-in words of a quest's page text, as the crawler kept it since record v3 (the whole page's 'text': its
 * objectives, then the headings Description, Progress, Completion, Rewards, Gains): ['progress' => words,
 * 'complete' => words] as the core writes them (wiki_core_text: <name> is $N, a line break $B), each only when the page
 * has it. A heading can follow the text before it with no line break ("...know!Completion"): it is looked for after
 * the Description heading only, so that a word of the objectives is never taken for one.
 */
function wowhead_pages_turn_in_text(string $text): array
{
    require_once FT_APP . '/wiki.php';
    $from = preg_match('/(?:^|\n)Description\n/u', $text, $m, PREG_OFFSET_CAPTURE) ? $m[0][1] + strlen($m[0][0]) : 0;
    $rest = substr($text, $from);
    $out = [];
    foreach (['progress' => 'Progress', 'complete' => 'Completion'] as $moment => $head) {
        if (!preg_match('/' . $head . '\n(.*?)(?=\n+(?:Progress|Completion|Rewards|Gains|Related|Comments|Screenshots)\n|$)/su', $rest, $m)) continue;
        $words = trim($m[1]);
        if ($words === '' || ($core = wiki_core_text($words)) === null) continue;
        $out[$moment] = $core;
    }
    return $out;
}

/**
 * What the NPC says at the turn-in of these quests ([quest => true]), from their Wowhead pages kept whole in the
 * answers table: [[quest, 'progress'|'complete', words], ...] as source_tables() reads $ev['text'], and how many pages
 * were read whole and had none ('wowhead_quest_no_turn_in_text').
 */
function wowhead_pages_texts(array $quests): array
{
    $ev = []; $none = 0;
    if (!$quests || !table_exists('ft_source_answers')) return [$ev, $none];
    foreach (array_chunk(array_map('intval', array_keys($quests)), 500) as $chunk) {
        foreach (rows("SELECT id, JSON_UNQUOTE(JSON_EXTRACT(whole, '$.text')) words FROM ft_source_answers WHERE source = 'wowhead' AND feed = 'page'"
            . " AND kind = 'quest' AND branch = 'forever' AND status = 'found' AND whole IS NOT NULL AND id IN (" . implode(',', $chunk) . ')') as $r) {
            $said = wowhead_pages_turn_in_text((string)$r['words']);
            if (!$said) { $none++; continue; }
            foreach ($said as $moment => $words) $ev[] = [(int)$r['id'], $moment, $words];
        }
    }
    return [$ev, $none];
}

/** Every page of one shelf, the newest answer of each, read a line at a time (a whole crawl's npc pages do not fit
 *  in memory at once): a generator of records. */
function wowhead_pages_each(string $shelf, ?array $dirs = null): Generator
{
    $dirs ??= wowhead_pages_dirs();
    $key = function (string $line): array {
        // the cache writes each line's id and time first
        if (preg_match('/^\{"id":(\d+),"fetched":(\d+)/', $line, $m)) return [(int)$m[1], (int)$m[2]];
        $r = json_decode($line, true);
        return is_array($r) ? [(int)($r['id'] ?? 0), (int)($r['fetched'] ?? 0)] : [0, 0];
    };
    $best = [];
    foreach ($dirs as $d => $dir) {
        $handle = @fopen("$dir/$shelf.jsonl", 'r');
        if (!$handle) continue;
        while (($line = fgets($handle)) !== false) { [$id, $at] = $key($line); if ($id > 0 && (!isset($best[$id]) || $best[$id][1] < $at)) $best[$id] = [$d, $at]; }
        fclose($handle);
    }
    foreach ($dirs as $d => $dir) {
        $handle = @fopen("$dir/$shelf.jsonl", 'r');
        if (!$handle) continue;
        while (($line = fgets($handle)) !== false) {
            [$id, $at] = $key($line);
            if ($id <= 0 || ($best[$id] ?? null) !== [$d, $at]) continue;
            unset($best[$id]);   // the same answer in two folders: once
            $record = json_decode($line, true);
            if (is_array($record)) yield $record;
        }
        fclose($handle);
    }
}

/** How many pages a shelf holds, by its lines (a whole crawl's npc pages are not read for a count). */
function wowhead_pages_count(string $shelf, ?array $dirs = null): int
{
    $n = 0;
    foreach ($dirs ?? wowhead_pages_dirs() as $dir) {
        $handle = @fopen("$dir/$shelf.jsonl", 'r');
        if (!$handle) continue;
        while (fgets($handle) !== false) $n++;
        fclose($handle);
    }
    return $n;
}

/** What Forever's item pages say of each item for another branch's pages: [item => how many creatures drop it]. */
function wowhead_pages_item_facts(array $items): array
{
    $out = [];
    foreach ($items as $item => $page) {
        if (($page['status'] ?? '') !== 'ok') continue;
        $tab = $page['tabs']['dropped-by'] ?? [];
        $out[(int)$item] = max(count((array)($tab['rows'] ?? [])), (int)($tab['total'] ?? 0));
    }
    return $out;
}

/**
 * Classic's pages as evidence for Forever: [evidence, the newest page's time]. Only drops: Classic's players looted
 * the same creatures and chests far more often, but Forever moved vendors and quests, so those are not taken. A drop
 * is taken only where Forever's pages ($forever, its evidence) give no counted chance of their own, and Forever's item
 * pages ($foreverItems) tell a world drop. The crawler reads a Classic npc or object page only for an id Forever has
 * too, whose Forever page lacks counts (crawler.js richEnough).
 *
 * $classicItems ([id => record]): Classic's item pages of the Season of Discovery items Forever kept, read where the
 * Forever page names no source (wowhead_pages_season_queue). Their Dropped by and Contained in tabs count as an item
 * page of Forever's would; one that pays for other items (a Currency for tab: the Tarnished Undermine Real) is no world
 * drop however many creatures drop it. Their Sold by tab is not taken: Forever cut those vendors' stock (Forever's
 * own npc pages give it), and is counted.
 */
function wowhead_pages_classic_evidence(array $forever, array $foreverItems, array $gapItems, iterable $npcs, iterable $objects, ?array $keep = null, array $classicItems = []): array
{
    $facts = wowhead_pages_item_facts($foreverItems);
    $currencies = []; $vendors = 0;
    foreach ($classicItems as $item => $page) {
        if (($page['status'] ?? '') !== 'ok') continue;
        unset($facts[(int)$item]);   // the Classic page says how many creatures drop it
        if (!empty($page['tabs']['currency-for']['rows'])) $currencies[(int)$item] = true;
        if (!empty($page['tabs']['sold-by']['rows']) && isset($gapItems[(int)$item])) $vendors++;
    }
    [$ev, $newest] = wowhead_pages_evidence($classicItems, [], $gapItems, $npcs, $objects, $keep, $facts, $currencies);
    $counted = [];
    foreach ($forever['drop'] ?? [] as $d) $counted["{$d[0]}:{$d[1]}:{$d[2]}"] = true;
    $drops = []; $known = 0;
    foreach ($ev['drop'] as $d) {
        if (isset($counted["{$d[0]}:{$d[1]}:{$d[2]}"])) { if (isset($gapItems[$d[2]])) $known++; continue; }
        $drops[] = $d;
    }
    $left = array_intersect_key($ev['left'], array_flip(['wowhead_drop_world', 'wowhead_drop_few', 'wowhead_drop_not_counted', 'wowhead_drop_item_page_not_read', 'wowhead_other_loot']));
    if ($known) $left['wowhead_classic_forever_counted'] = $known;
    if ($vendors) $left['wowhead_classic_season_vendor'] = $vendors;
    return [['sell' => [], 'drop' => $drops, 'start' => [], 'end' => [], 'train' => [], 'left' => $left], $newest];
}

/** Classic's item pages worth taking: those of Season of Discovery items Forever kept whose Forever page ($forever)
 *  names no source. A Forever page that does is the one taken. */
function wowhead_pages_classic_items(array $forever, ?array $classic = null, ?string $baseline = null): array
{
    $classic ??= wowhead_pages('classic-item');
    $season = wowhead_pages_season_items(array_keys($classic), $baseline);
    return array_filter($classic, fn($page, $id) => isset($season[(int)$id]) && !wowhead_pages_has_source($forever[(int)$id] ?? null), ARRAY_FILTER_USE_BOTH);
}

/** Classic's pages in the cache as an import card: drops of the last analysis' gaps that Forever's pages count too
 *  few of, and the drops a less trusted import brought measured again. */
function wowhead_pages_classic_import(): array
{
    if ($e = source_check()) return $e;
    $has = fn(string $shelf) => is_file(wowhead_pages_dir() . "/$shelf.jsonl") || is_file(FT_ROOT . "/tools/wowhead-pages/cache/$shelf.jsonl");
    if (!$has('classic-npc') && !$has('classic-object') && !$has('classic-item')) return ['ok' => false, 'message' => t('No Classic page has been read yet: the full crawl reads them after Forever\'s (docs/WOWHEAD-PAGES.md).', 'Aucune page Classic n’a encore été lue : le crawl complet les lit après celles de Forever (docs/WOWHEAD-PAGES.md).')];
    $gaps = source_gaps();
    $keep = wowhead_pages_keep($gaps['items']);
    $foreverItems = wowhead_pages('item');
    [$forever] = wowhead_pages_evidence($foreverItems, [], $gaps['items'], wowhead_pages_each('npc'), wowhead_pages_each('object'), $keep);
    [$ev, $newest] = wowhead_pages_classic_evidence($forever, $foreverItems, $gaps['items'], wowhead_pages_each('classic-npc'), wowhead_pages_each('classic-object'), $keep,
        wowhead_pages_classic_items($foreverItems));
    $date = date('Y-m-d', $newest ?: time());
    snapshot_try('wowheadclassic', $date, $ev, 'gaps');
    return wowhead_pages_card('wowheadclassic', $ev, $date, $date . '-' . $newest, $gaps);
}

// ------------------------------------------------------------------ what players' comments point to

const WOWHEAD_COMMENT_KINDS = [1 => 'npc', 2 => 'object', 3 => 'item', 4 => 'quest'];   // crawler.js COMMENT_KINDS
const WOWHEAD_COMMENT_START = 1, WOWHEAD_COMMENT_END = 2, WOWHEAD_COMMENT_DROP = 3, WOWHEAD_COMMENT_SELL = 4;   // COMMENT_ROLES
const WOWHEAD_PAGES_COMMENTS_V = 4;   // the crawler's record version that keeps the comments' links
const WOWHEAD_PAGES_COMMENTS_WHOLE_V = 5;   // ... and their words (full.comments): what the gap quests' pages are read again for

/**
 * The comments' links of Forever's pages (crawler v4, record 'comments': [[rating, [[role, kind, id]...]]...]) as
 * evidence of their own, "Wowhead comments", trusted after every other source: only for what the server still lacks.
 * A comment voted down (rating below 0) is not taken.
 *   - a quest page: the creature or object a comment says starts it, or takes it (turned in), for a quest without a
 *     giver or an ender ($gapQuests: ['noGiver' => [...], 'noEnder' => [...]]);
 *   - a creature's or object's page: the quests a comment says it starts or takes, for those same quests;
 *   - an item page of a gap item: the creature a comment says sells it (money only: a comment does not say the price,
 *     the server's own price of the item is asked), and the creatures or chests it says drop it, at the server's best
 *     chance of the item ($chances) or, for an item a quest asks for, $questChance. A drop with no chance is left.
 * $pages: [kind => iterable of records]. Returns [evidence, the newest page's time].
 */
function wowhead_comments_evidence(array $pages, array $gapItems, array $gapQuests, array $chances = [], array $questItems = [], float $questChance = 40.0): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'quest_drop' => [], 'left' => []];
    $left = ['wowhead_comment_voted_down' => 0, 'wowhead_comment_drop_no_chance' => 0];
    $newest = 0;
    $roles = ['start' => [], 'end' => []]; $drops = []; $sells = [];
    $role = fn(int $r) => $r === WOWHEAD_COMMENT_START ? 'start' : ($r === WOWHEAD_COMMENT_END ? 'end' : null);
    $wanted = fn(string $r, int $quest) => isset($gapQuests[$r === 'start' ? 'noGiver' : 'noEnder'][$quest]);
    foreach ($pages as $kind => $records) {
        foreach ($records as $page) {
            $id = (int)($page['id'] ?? 0);
            if ($id <= 0 || ($page['status'] ?? '') !== 'ok' || empty($page['comments']) || !is_array($page['comments'])) continue;
            $newest = max($newest, (int)($page['fetched'] ?? 0));
            foreach ($page['comments'] as $comment) {
                if (!is_array($comment) || !is_array($comment[1] ?? null)) continue;
                $down = (int)($comment[0] ?? 0) < 0;
                foreach ($comment[1] as $link) {
                    if (!is_array($link) || count($link) < 3) continue;
                    [$r, $k, $to] = [(int)$link[0], WOWHEAD_COMMENT_KINDS[(int)$link[1]] ?? null, (int)$link[2]];
                    if (!$k || $to <= 0) continue;
                    $found = null;
                    if ($kind === 'quest' && ($k === 'npc' || $k === 'object') && ($rr = $role($r)) && $wanted($rr, $id)) $found = [$rr, [$k === 'npc' ? 'npc' : 'go', $to, $id]];
                    elseif (($kind === 'npc' || $kind === 'object') && $k === 'quest' && ($rr = $role($r)) && $wanted($rr, $to)) $found = [$rr, [$kind === 'npc' ? 'npc' : 'go', $id, $to]];
                    elseif ($kind === 'item' && isset($gapItems[$id]) && $r === WOWHEAD_COMMENT_SELL && $k === 'npc') $found = ['sell', [$to, $id, 0]];
                    elseif ($kind === 'item' && isset($gapItems[$id]) && $r === WOWHEAD_COMMENT_DROP && ($k === 'npc' || $k === 'object')) $found = ['drop', [$k === 'npc' ? 'npc' : 'go', $to, $id]];
                    if (!$found) continue;
                    if ($down) { $left['wowhead_comment_voted_down']++; continue; }
                    [$what, $row] = $found;
                    $key = implode(':', $row);
                    if ($what === 'sell') $sells[$key] = $row;
                    elseif ($what === 'drop') $drops[$key] = $row;
                    else $roles[$what][$key] = $row;
                }
            }
        }
    }
    foreach ($drops as $key => [$k, $id, $item]) {
        $quest = isset($questItems[$item]);
        $chance = (float)($chances[$item] ?? 0) ?: ($quest ? $questChance : 0.0);
        if ($chance <= 0) { $left['wowhead_comment_drop_no_chance']++; continue; }
        $ev['drop'][] = [$k, $id, $item, $chance];
        if ($quest) $ev['quest_drop'][$key] = true;
    }
    $ev['sell'] = array_values($sells);
    $ev['start'] = array_values($roles['start']);
    $ev['end'] = array_values($roles['end']);
    $ev['left'] = array_filter($left);
    return [$ev, $newest];
}

/**
 * The creature and object pages whose comments may name the giver or ender of a quest that lacks one: what the crawl
 * reads first for the "Wowhead comments" source. $questPages: the quest pages (records) of those quests; $gapQuests:
 * ['noGiver' => [quest => true], 'noEnder' => [...]]; $givers / $enders: the server's [quest => [[kind, id]...]] (kind
 * 'npc' or 'object') for the quests of their series. For each such quest:
 *   - what a comment on its own page links to, as a creature or object, whatever it says of it (a comment voted down
 *     too: its target's own page may say better);
 *   - in its series, for a quest without a giver, who takes the quest before it (the next step is often given where
 *     the last one was turned in), and for a quest without an ender, who gives the quest after it.
 * Returns ['npc' => [id => true], 'object' => [id => true]].
 */
function wowhead_comments_targets(iterable $questPages, array $gapQuests, array $givers = [], array $enders = []): array
{
    $out = ['npc' => [], 'object' => []];
    foreach ($questPages as $page) {
        $quest = (int)($page['id'] ?? 0);
        $noGiver = isset($gapQuests['noGiver'][$quest]); $noEnder = isset($gapQuests['noEnder'][$quest]);
        if ($quest <= 0 || (!$noGiver && !$noEnder) || ($page['status'] ?? '') !== 'ok') continue;
        foreach (is_array($page['comments'] ?? null) ? $page['comments'] : [] as $comment) {
            foreach (is_array($comment[1] ?? null) ? $comment[1] : [] as $link) {
                $kind = is_array($link) && count($link) >= 3 ? (WOWHEAD_COMMENT_KINDS[(int)$link[1]] ?? null) : null;
                if (($kind === 'npc' || $kind === 'object') && (int)$link[2] > 0) $out[$kind][(int)$link[2]] = true;
            }
        }
        $series = array_map(fn($q) => (int)$q === 0 ? $quest : (int)$q, is_array($page['series'] ?? null) ? $page['series'] : []);
        $at = array_search($quest, $series, true);
        if ($at === false) continue;
        $near = [];
        if ($noGiver && $at > 0) $near = array_merge($near, $enders[$series[$at - 1]] ?? []);
        if ($noEnder && isset($series[$at + 1])) $near = array_merge($near, $givers[$series[$at + 1]] ?? []);
        foreach ($near as [$kind, $id]) if (isset($out[$kind]) && (int)$id > 0) $out[$kind][(int)$id] = true;
    }
    return $out;
}

/** The server's givers and enders of $quests: [[quest => [[kind, id]...]] givers, enders] (kind 'npc' or 'object'). */
function wowhead_comments_server_links(array $quests): array
{
    $out = [[], []];
    foreach (array_chunk(array_values(array_unique(array_map('intval', $quests))), 2000) as $chunk) {
        $in = implode(',', $chunk);
        foreach ([[0, 'creature_queststarter', 'npc'], [0, 'gameobject_queststarter', 'object'], [1, 'creature_questender', 'npc'], [1, 'gameobject_questender', 'object']] as [$side, $table, $kind]) {
            foreach (rows("SELECT id, quest FROM `$table` WHERE quest IN ($in)", [], 'world') as $r) $out[$side][(int)$r['quest']][] = [$kind, (int)$r['id']];
        }
    }
    return $out;
}

/** The creature and object pages to read for the comments of the quests without a giver or an ender
 *  (wowhead_comments_targets), less those held with their comments (record v4) and not due again: [kind => ids]. */
function wowhead_comments_queue(array $gapQuests): array
{
    $wanted = $gapQuests['noGiver'] + $gapQuests['noEnder'];
    if (!$wanted) return [];
    $pages = [];
    foreach (wowhead_pages_each('quest') as $page) if (isset($wanted[(int)($page['id'] ?? 0)])) $pages[] = $page;
    $series = [];
    foreach ($pages as $page) foreach (is_array($page['series'] ?? null) ? $page['series'] : [] as $q) if ((int)$q > 0) $series[] = (int)$q;
    [$givers, $enders] = $series ? wowhead_comments_server_links($series) : [[], []];
    $out = [];
    foreach (wowhead_comments_targets($pages, $gapQuests, $givers, $enders) as $kind => $ids) {
        if (!$ids) continue;
        foreach (wowhead_pages_each($kind) as $page) {
            $id = (int)($page['id'] ?? 0);
            if (!isset($ids[$id])) continue;
            $old = ($page['status'] ?? '') === 'ok' && (int)($page['v'] ?? 0) < WOWHEAD_PAGES_COMMENTS_V;
            if (!$old && !wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', $id)) unset($ids[$id]);
        }
        if ($ids) $out[$kind] = array_keys($ids);
    }
    return $out;
}

/** Words before a name in a comment that say the named one takes the quest (end) or gives it (start): the crawler's
 *  COMMENT_ROLES for the text (crawler.js), with the name written out instead of linked. */
const WOWHEAD_COMMENT_TEXT_CUES = [
    'end' => '(?:turn(?:s|ed|ing)?\s+(?:it|this|them|the\s+quest)?\s*in|hand(?:s|ed|ing)?\s+(?:it|this|them)?\s*in|return(?:s|ed)?(?:\s+it)?|deliver(?:s|ed)?(?:\s+it)?|complete[sd]?|ends?)\s+(?:to|at|with)',
    'start' => '(?:start(?:s|ed|ing)?\s+(?:at|with|from|by)|pick(?:s|ed)?\s+(?:it|this|the\s+quest)?\s*up\s+(?:from|at)|given\s+by|offered\s+by|(?:get|got|grab)\s+(?:it|this|the\s+quest)\s+from)',
];

/**
 * The names a comment's words give as a quest's giver or ender: [['start'|'end', name], ...]. A name is what follows a
 * cue (WOWHEAD_COMMENT_TEXT_CUES), "the" left out: words starting with a capital letter, joined by "the", "of" or
 * "de" ("Griniblix the Spectator"), six words at most. Links ([npc=5], [url=...]) are the crawler's comment links, not
 * read here. Each name comes with its shorter starts too ("Griniblix the Spectator", then "Griniblix"), longest first:
 * the server's names pick (wowhead_comments_text_evidence).
 */
function wowhead_comment_text_names(string $body): array
{
    $text = preg_replace('/\[(npc|object|item|quest|url)[^\]]*\].*?\[\/\1\]|\[(npc|object|item|quest)=\d+[^\]]*\]|\[\/?[a-z]+[^\]]*\]/iu', ' # ', $body);
    $out = [];
    foreach (WOWHEAD_COMMENT_TEXT_CUES as $role => $cue) {
        if (!preg_match_all('/\b(?i:' . $cue . ')\s+(?:(?i:the)\s+)?((?:[A-Z][\w\'’-]*)(?:\s+(?:(?:the|of|de)\s+)?[A-Z][\w\'’-]*){0,5})/u', $text, $m)) continue;
        foreach ($m[1] as $name) {
            $words = preg_split('/\s+/u', trim($name));
            for ($n = count($words); $n >= 1; $n--) {
                $part = implode(' ', array_slice($words, 0, $n));
                if (preg_match('/\s(the|of|de)$/u', $part) || mb_strlen($part) < 4) continue;
                $out[] = [$role, $part];
            }
        }
    }
    return $out;
}

/**
 * Givers and enders the words of a quest page's comments name, for the quests that lack them: [start rows, end rows,
 * left counts] as wowhead_comments_evidence's ($ev['start'] / ['end']: [kind 'npc'|'go', id, quest]). $comments:
 * [quest => the page's whole comments, [{rating, body, replies?}]]; $resolve(names): [lowercase name => [[kind, id],
 * ...]] of the server's spawned creatures and objects of that name. A name is taken when exactly one spawned creature
 * or object has it, the longest name of a cue first; a comment voted down is not read.
 */
function wowhead_comments_text_evidence(array $comments, array $gapQuests, callable $resolve): array
{
    $said = [];   // [quest][role] => [names, longest first, in the order said]
    $left = ['wowhead_comment_voted_down' => 0, 'wowhead_comment_name_unknown' => 0, 'wowhead_comment_name_several' => 0];
    foreach ($comments as $quest => $list) {
        foreach (is_array($list) ? $list : [] as $c) {
            if (!is_array($c) || !is_string($c['body'] ?? null)) continue;
            $bodies = [$c['body']];
            foreach (is_array($c['replies'] ?? null) ? $c['replies'] : [] as $r) if (is_string($r['body'] ?? null)) $bodies[] = $r['body'];
            foreach ($bodies as $body) {
                foreach (wowhead_comment_text_names($body) as [$role, $name]) {
                    if (!isset($gapQuests[$role === 'start' ? 'noGiver' : 'noEnder'][$quest])) continue;
                    if ((int)($c['rating'] ?? 0) < 0) { $left['wowhead_comment_voted_down']++; continue 3; }
                    $said[$quest][$role][] = $name;
                }
            }
        }
    }
    $names = [];
    foreach ($said as $roles) foreach ($roles as $list) foreach ($list as $name) $names[mb_strtolower($name)] = true;
    $known = $names ? $resolve(array_keys($names)) : [];
    $rows = ['start' => [], 'end' => []];
    foreach ($said as $quest => $roles) {
        foreach ($roles as $role => $list) {
            $picked = null; $several = false;
            foreach ($list as $name) {
                $who = $known[mb_strtolower($name)] ?? [];
                if (count($who) === 1) { $picked = $who[0]; break; }
                if (count($who) > 1) $several = true;
            }
            if ($picked === null) { $left[$several ? 'wowhead_comment_name_several' : 'wowhead_comment_name_unknown']++; continue; }
            [$kind, $id] = $picked;
            $rows[$role]["$kind:$id:$quest"] = [$kind, (int)$id, (int)$quest];
        }
    }
    return [array_values($rows['start']), array_values($rows['end']), array_filter($left)];
}

/** The server's spawned creatures and objects of these names (lowercase): [name => [['npc'|'go', entry], ...]]. */
function wowhead_comments_server_names(array $names): array
{
    $out = [];
    foreach (array_chunk($names, 500) as $chunk) {
        $in = implode(',', array_map(fn($n) => "'" . db('world')->real_escape_string((string)$n) . "'", $chunk));
        foreach ([['npc', 'creature_template', 'creature', '(t.npcflag & 2) <> 0'], ['go', 'gameobject_template', 'gameobject', 't.type = 2']] as [$kind, $template, $spawns, $quests]) {
            foreach (rows("SELECT t.entry, LOWER(t.name) name, $quests asks FROM `$template` t WHERE LOWER(t.name) IN ($in) AND EXISTS (SELECT 1 FROM `$spawns` s WHERE s.id = t.entry)", [], 'world') as $r)
                $out[$r['name']][] = [$kind, (int)$r['entry'], (bool)(int)$r['asks']];
        }
    }
    return wowhead_comments_name_pick($out);
}

/** Of the spawned creatures and objects of one name ([name => [[kind, id, gives or takes quests]...]]), the one that
 *  deals in quests when only one of several does (two Sully McClearys stand, one is a quest giver): [name => [[kind, id]
 *  ...]]. */
function wowhead_comments_name_pick(array $byName): array
{
    $out = [];
    foreach ($byName as $name => $list) {
        $asks = array_values(array_filter($list, fn($w) => !empty($w[2])));
        $out[$name] = array_map(fn($w) => [$w[0], $w[1]], count($list) > 1 && count($asks) === 1 ? $asks : $list);
    }
    return $out;
}

/** The whole comments of the quest pages of $quests ([quest => true]) the answers table keeps (crawler v5): [quest =>
 *  comments] and the newest page's time. */
function wowhead_comments_whole(array $quests): array
{
    $out = []; $newest = 0;
    if (!$quests || !table_exists('ft_source_answers')) return [$out, $newest];
    foreach (array_chunk(array_map('intval', array_keys($quests)), 500) as $chunk) {
        foreach (rows("SELECT id, UNIX_TIMESTAMP(fetched_at) at, JSON_EXTRACT(whole, '$.comments') comments FROM ft_source_answers WHERE source = 'wowhead' AND feed = 'page'"
            . " AND kind = 'quest' AND branch = 'forever' AND status = 'found' AND JSON_EXTRACT(whole, '$.comments') IS NOT NULL AND id IN (" . implode(',', $chunk) . ')') as $r) {
            $list = json_decode((string)$r['comments'], true);
            if (!is_array($list) || !$list) continue;
            $out[(int)$r['id']] = $list;
            $newest = max($newest, (int)$r['at']);
        }
    }
    return [$out, $newest];
}

/** The comments' links of the pages in the cache as an import card of their own ("Wowhead comments"). */
function wowhead_comments_import(): array
{
    if ($e = source_check()) return $e;
    require_once FT_APP . '/questie.php';
    $gaps = source_gaps();
    $later = $gaps['later'] ?? [];
    $gapItems = array_diff_key($gaps['items'], $later['items'] ?? []);
    $gapQuests = ['noGiver' => array_diff_key($gaps['noGiver'], $later['quests'] ?? []), 'noEnder' => array_diff_key($gaps['noEnder'], $later['quests'] ?? [])];
    $questItems = [];
    foreach (rows('SELECT DISTINCT ObjectID FROM quest_objectives WHERE Type = 1', [], 'world') as $r) $questItems[(int)$r['ObjectID']] = true;
    $pages = [];
    foreach (['quest', 'item', 'npc', 'object'] as $kind) $pages[$kind] = wowhead_pages_each($kind);
    [$ev, $newest] = wowhead_comments_evidence($pages, $gapItems, $gapQuests, questie_server_chances($gapItems), $questItems, (float)config('questie', 'quest_chance', 40));
    // the words of the quests' comments (crawler v5): a giver or ender named, not linked, is matched to the server's names
    [$whole, $wholeNewest] = wowhead_comments_whole($gapQuests['noGiver'] + $gapQuests['noEnder']);
    if ($whole) {
        [$starts, $ends, $textLeft] = wowhead_comments_text_evidence($whole, $gapQuests, 'wowhead_comments_server_names');
        foreach (['start' => $starts, 'end' => $ends] as $role => $found) {
            $have = [];
            foreach ($ev[$role] as $r) $have[implode(':', $r)] = true;
            foreach ($found as $r) if (!isset($have[implode(':', $r)])) $ev[$role][] = $r;
        }
        foreach ($textLeft as $why => $n) $ev['left'][$why] = ($ev['left'][$why] ?? 0) + $n;
        $newest = max($newest, $wholeNewest);
    }
    if (!$newest) return ['ok' => false, 'message' => t('No page read yet keeps its comments\' links: the crawler reads the gaps\' pages again (record v4).', 'Aucune page lue ne garde encore les liens de ses commentaires : le crawler relit les pages des manques (fiche v4).')];
    $date = date('Y-m-d', $newest);
    snapshot_try('wowheadcomments', $date, $ev, 'gaps');
    $label = SOURCES['wowheadcomments'][0] . ' ' . $date;
    [$tables, $left] = source_tables($ev, $label, $gaps);
    return source_card('wowheadcomments', $label, 'wowheadcomments@' . $date . '-' . $newest, $tables, $left);
}

/** The card of Wowhead's (or Wowhead Classic's) evidence: what the server lacks, and the drops it has measured again.
 *  Also made from the database (snapshot_card). */
function wowhead_pages_card(string $source, array $ev, string $date, string $file, array $gaps): array
{
    $label = SOURCES[$source][0] . ' ' . $date;
    // a quest's reward slots are filled (source_tables), drop chances measured again set (source_refresh)
    [$tables, $left, $rewards] = source_tables($ev, $label, $gaps);
    [$changes, $moved] = source_refresh($ev, $source);
    return source_card($source, $label, $source . '@' . $file, $tables, $left + $moved, array_merge($rewards, $changes));
}

/** The zones the server has a fishing table of its own for: [zone => true]. A zone page's whole Fishing tab goes to the
 *  others. Rows this import wrote do not make a table (Mount Hyjal had none, then a Wowhead card gave it two of its item
 *  pages' catches): such a zone still takes its page's whole table. */
function wowhead_pages_fish_tables(): array
{
    if (!table_exists('fishing_loot_template', 'world')) return [];
    $out = [];
    foreach (rows("SELECT DISTINCT Entry FROM fishing_loot_template WHERE Comment IS NULL OR Comment NOT LIKE ?", [SOURCE_MARKS['wowhead'] . ' 2%'], 'world') as $r) $out[(int)$r['Entry']] = true;
    return $out;
}

/** The zones whose page the crawl reads for their fishing: the realm's zones with no fishing table (ft_entities, the
 *  analysis' zones), and the zones the gap items' pages say they are fished in. */
function wowhead_pages_fish_zones(array $items, array $gapItems): array
{
    $tables = wowhead_pages_fish_tables();
    $zones = [];
    if (table_exists('ft_entities')) {
        foreach (rows("SELECT id FROM ft_entities WHERE type = 'zone' AND internal = 0") as $r) if (!isset($tables[(int)$r['id']])) $zones[(int)$r['id']] = true;
    }
    foreach ($gapItems as $item => $_) {
        foreach ((array)($items[$item]['tabs'][WOWHEAD_PAGES_FISHED_IN]['rows'] ?? []) as $row) if ((int)($row['id'] ?? 0) > 0) $zones[(int)$row['id']] = true;
    }
    ksort($zones);
    return array_keys($zones);
}

/** The items whose drops an npc or object page may give: the gaps, and the items of drop rows an import brought (a
 *  source named in the row's comment), which the card measures again. */
function wowhead_pages_keep(array $gapItems): array
{
    $keep = $gapItems;
    $marks = implode(' OR ', array_map(fn($m) => "Comment LIKE '%" . db('world')->real_escape_string($m) . "%'", array_values(SOURCE_MARKS)));
    foreach (['creature_loot_template', 'gameobject_loot_template'] as $table) {
        foreach (rows("SELECT DISTINCT Item FROM `$table` WHERE ItemType = 0 AND ($marks)", [], 'world') as $r) $keep[(int)$r['Item']] = true;
    }
    return $keep;
}

/** The pages in the cache as an import card aimed at the last analysis' gaps, with the drops the server already has
 *  measured again. */
function wowhead_pages_import(): array
{
    if ($e = source_check()) return $e;
    $items = wowhead_pages('item'); $quests = wowhead_pages('quest');
    $hasPages = $items || $quests || array_filter(array_map(fn($s) => is_file(wowhead_pages_dir() . "/$s.jsonl") || is_file(FT_ROOT . "/tools/wowhead-pages/cache/$s.jsonl"), ['npc', 'object']));
    if (!$hasPages) return ['ok' => false, 'message' => t('No Wowhead page has been read yet: see docs/WOWHEAD-PAGES.md (tools/wowhead-pages/crawler.js reads them from a browser tab).', 'Aucune page Wowhead n’a encore été lue : voir docs/WOWHEAD-PAGES.md (tools/wowhead-pages/crawler.js les lit depuis un onglet de navigateur).')];
    $gaps = source_gaps();
    [$ev, $newest] = wowhead_pages_evidence($items, $quests, $gaps['items'], wowhead_pages_each('npc'), wowhead_pages_each('object'), wowhead_pages_keep($gaps['items']),
        [], [], wowhead_pages_each('zone'), wowhead_pages_fish_tables());
    // the gaps no page told about yet: the crawler's queue (Download the crawler) holds their pages
    $told = [];
    foreach ($ev['drop'] as $d) $told[$d[2]] = true;
    foreach ($ev['sell'] as $s) $told[$s[1]] = true;
    $unread = count(array_diff_key($gaps['items'], $items, $told));
    $roles = ['start' => [], 'end' => []];
    foreach (['start', 'end'] as $role) foreach ($ev[$role] as $r) $roles[$role][$r[2]] = true;
    // a quest is told about by its own page, or by npc and object pages naming what it lacks
    $unreadQuests = 0;
    foreach ($gaps['noGiver'] + $gaps['noEnder'] as $quest => $_) {
        if (isset($quests[$quest]) || ((!isset($gaps['noGiver'][$quest]) || isset($roles['start'][$quest])) && (!isset($gaps['noEnder'][$quest]) || isset($roles['end'][$quest])))) continue;
        $unreadQuests++;
    }
    // the turn-in words of the quests that lack them, from their pages kept whole (crawler v3)
    [$ev['text'], $noText] = wowhead_pages_texts($gaps['noText'] ?? []);
    if ($noText) $ev['left']['wowhead_quest_no_turn_in_text'] = $noText;
    if ($unread) $ev['left']['wowhead_item_not_read'] = $unread;
    if ($unreadQuests) $ev['left']['wowhead_quest_not_read'] = $unreadQuests;
    $date = date('Y-m-d', $newest ?: time());
    snapshot_try('wowhead', $date, $ev, 'gaps');   // npc and object pages give only the drops worth a row (wowhead_pages_keep)
    return wowhead_pages_card('wowhead', $ev, $date, $date . '-' . $newest, $gaps);
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
    if (($record['kind'] ?? null) === 'guide') {
        // a guide: its path, and the items its tables link to with the tier their row names (numbers only)
        $query = $record['query'] ?? null;
        if (!is_string($query) || !preg_match(WOWHEAD_GUIDE_QUERY, $query)) return null;
        $out = ['kind' => 'guide', 'query' => $query, 'fetched' => $fetched, 'v' => (int)($record['v'] ?? 0), 'status' => $record['status']] + $branch;
        if ($record['status'] === 'missing') return $out;
        if (!is_array($record['rows'] ?? null)) return null;
        $out['rows'] = array_values(array_filter($record['rows'], fn($r) => is_array($r) && is_int($r['id'] ?? null) && $r['id'] > 0 && wowhead_pages_numbers_only($r)));
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
    // map, series, and what players' comments link to (crawler v4: [[rating, [[role, kind, id]...]]...], numbers only)
    foreach (['map', 'series', 'comments'] as $extra) if (!empty($record[$extra]) && wowhead_pages_numbers_only($record[$extra])) $out[$extra] = $record[$extra];
    // the model display ids of a creature's or object's page (crawler v2)
    if (!empty($record['model']) && is_array($record['model']) && array_is_list($record['model']))
        $out['model'] = array_values(array_slice(array_filter($record['model'], fn($m) => is_int($m) && $m > 0), 0, 8));
    return $out;
}

/** What the crawler saved (one JSON line a page) into the cache: the newer answer of a page wins; each kind's file is
 *  written whole and sorted by id. Returns the counts: new, newer, older (kept the one we had), not_a_page, and db (rows sent to
 *  the answers table, app/wowheaddb.php) when it is the tracker's own cache. */
function wowhead_pages_merge(string $text, ?string $dir = null): array
{
    $record_db = $dir === null;   // the tracker's own cache: its pages go to the answers table too
    $dir ??= wowhead_pages_dir();
    $counts = ['new' => 0, 'newer' => 0, 'older' => 0, 'not_a_page' => 0];
    $incoming = [];
    $dbRows = [];   // for the answers table (app/wowheaddb.php), the whole page too when the crawler kept it
    foreach (preg_split('/\r?\n/', $text) as $line) {
        if (trim($line) === '') continue;
        $raw = json_decode($line, true);
        $record = wowhead_pages_clean($raw);
        if ($record === null) { $counts['not_a_page']++; continue; }
        $incoming[wowhead_pages_shelf($raw)][] = $record;
        if ($record_db) $dbRows[] = wowhead_db_page_rows([$raw])[0] ?? null;
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
    if ($record_db) $counts['db'] = wowhead_db_try($dbRows);
    return $counts;
}

/**
 * Pages a linked crawl sent (one JSON line each) added to the cache at the end of their shelves: nothing is rewritten,
 * so it stays quick however large the cache grows. Every reader takes the newest answer of a page, wherever it is in
 * the file; *Send wowhead-pages.jsonl* (wowhead_pages_merge) writes a shelf sorted again. Returns the counts: pages,
 * not_a_page.
 */
function wowhead_pages_append(array $lines, ?string $dir = null): array
{
    $record_db = $dir === null;   // the tracker's own cache: its pages go to the answers table too
    $dir ??= wowhead_pages_dir();
    $counts = ['pages' => 0, 'not_a_page' => 0];
    $out = [];
    $dbRows = [];
    foreach ($lines as $line) {
        $raw = is_string($line) ? json_decode($line, true) : null;
        $record = is_array($raw) ? wowhead_pages_clean($raw) : null;
        if ($record === null) { $counts['not_a_page']++; continue; }
        if ($record_db) $dbRows[] = wowhead_db_page_rows([$raw])[0] ?? null;
        if (($record['tabs'] ?? null) === []) $record['tabs'] = new stdClass();
        $out[wowhead_pages_shelf($raw)][] = json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION) . "\n";
        $counts['pages']++;
    }
    @mkdir($dir, 0775, true);
    foreach ($out as $shelf => $rows) {
        $handle = @fopen("$dir/$shelf.jsonl", 'a');
        if (!$handle) throw new RuntimeException("cannot write $dir/$shelf.jsonl");
        flock($handle, LOCK_EX);
        fwrite($handle, implode('', $rows));
        flock($handle, LOCK_UN);
        fclose($handle);
    }
    if ($record_db) $counts['db'] = wowhead_db_try($dbRows);
    return $counts;
}

/** After pages came from a linked crawl: the import cards made again, at most every [wowhead] card_minutes (30), so
 *  that the cards follow the crawl. [message, card id or 0]. */
function wowhead_pages_cards_due(bool $force = false): array
{
    $mark = wowhead_pages_dir() . '/.cards-made';
    $every = max(1, (int)config('wowhead', 'card_minutes', 30)) * 60;
    if (!$force && is_file($mark) && time() - (int)@filemtime($mark) < $every) return ['', 0];
    @touch($mark);
    $card = wowhead_pages_import();
    $said = (string)($card['message'] ?? '');
    $id = (int)($card['id'] ?? 0);
    if (wowhead_pages_count('classic-npc') + wowhead_pages_count('classic-object') + wowhead_pages_count('classic-item')) {
        $classic = wowhead_pages_classic_import();
        $said .= ' ' . (string)($classic['message'] ?? '');
        $id = $id ?: (int)($classic['id'] ?? 0);
    }
    // what players' comments link to: a card of its own, once a page keeps its comments (crawler v4)
    $comments = wowhead_comments_import();
    if (!empty($comments['ok'])) { $said .= ' ' . (string)($comments['message'] ?? ''); $id = $id ?: (int)($comments['id'] ?? 0); }
    return [trim($said), $id];
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
    // 'blocking': how many of the items, from the first, are ones other content waits for (the crawler's tier 1)
    return ['item' => $unread('item', array_merge(array_keys($first), $rest)), 'quest' => $unread('quest', $quests), 'blocking' => count($unread('item', array_keys($first)))];
}

/**
 * Which of these items are Season of Discovery's: an id from 190000 up that the Classic Era client has too
 * (tools/baseline/classic-era.json, the same test as tools/ft/baseline.py season()). Forever kept some of them (the
 * Tarnished Undermine Real, say): Wowhead's Forever pages often know no source for them yet, its Classic pages do.
 * [id => true]. $baseline: another file (the tests).
 */
function wowhead_pages_season_items(array $ids, ?string $baseline = null): array
{
    static $spans = [];
    $baseline ??= FT_ROOT . '/tools/baseline/classic-era.json';
    if (!isset($spans[$baseline])) {
        $data = is_file($baseline) ? json_decode((string)file_get_contents($baseline), true) : null;
        $spans[$baseline] = array_values(array_filter((array)($data['tables']['ItemSparse'] ?? []), 'is_array'));
    }
    $out = [];
    foreach ($ids as $id) {
        $id = (int)$id;
        if ($id < 190000) continue;
        // the spans are sorted [start, end] pairs: a binary search
        [$lo, $hi] = [0, count($spans[$baseline]) - 1];
        while ($lo <= $hi) {
            $mid = intdiv($lo + $hi, 2);
            [$start, $end] = $spans[$baseline][$mid];
            if ($id < $start) $hi = $mid - 1;
            elseif ($id > $end) $lo = $mid + 1;
            else { $out[$id] = true; break; }
        }
    }
    return $out;
}

/** Whether an item page names a source the import can use: a creature or chest it drops from, a vendor. */
function wowhead_pages_has_source(?array $page): bool
{
    if (!$page || ($page['status'] ?? '') !== 'ok') return false;
    foreach (array_merge(array_keys(WOWHEAD_PAGES_DROP_TABS), ['sold-by']) as $tab) if (!empty($page['tabs'][$tab]['rows'])) return true;
    return false;
}

/**
 * The Classic item pages worth reading for the Season of Discovery items Forever kept: of $items (the queue's gap
 * items, in order), the Season ones whose Forever page was not read yet or names no source ($forever: [id => record]),
 * and whose Classic page is not in the cache ($classicRead: [id => true]). In the order of $items.
 */
function wowhead_pages_season_queue(array $items, array $forever, array $classicRead, ?string $baseline = null): array
{
    $season = wowhead_pages_season_items($items, $baseline);
    return array_values(array_filter($items, fn($id) => isset($season[(int)$id]) && !isset($classicRead[(int)$id]) && !wowhead_pages_has_source($forever[(int)$id] ?? null)));
}

/** The ids a branch's whole list pages name ('npcs', 'objects', ...): [id => true], or null when none was read. Read a
 *  line at a time: the item lists are large. */
function wowhead_pages_listed(string $list, string $branch = 'forever', ?array $dirs = null): ?array
{
    $ids = null;
    foreach ($dirs ?? wowhead_pages_dirs() as $dir) {
        $handle = @fopen("$dir/$branch-list.jsonl", 'r');
        if (!$handle) continue;
        while (($line = fgets($handle)) !== false) {
            if (!str_contains($line, '"query":"' . $list)) continue;
            $page = json_decode($line, true);
            if (!is_array($page) || !empty($page['truncated']) || strtok((string)($page['query'] ?? ''), '?') !== $list) continue;
            $ids ??= [];
            foreach ((array)($page['rows'] ?? []) as $row) if (is_int($row['id'] ?? null)) $ids[$row['id']] = true;
        }
        fclose($handle);
    }
    return $ids;
}

/**
 * The creatures and objects of the server whose data is missing, the ones a page would fill first: vendors that sell
 * nothing, trainers that teach nothing, chests that hold nothing, creatures without loot (those with no service first:
 * the ones players fight). Only those Wowhead's Forever lists name, when they were read: ['npc' => [...], 'object' =>
 * [...]], in that order.
 */
function wowhead_pages_missing_data(): array
{
    $ids = fn(string $sql) => array_map(fn($r) => (int)reset($r), rows($sql, [], 'world'));
    // spawned creatures with the id their loot is kept under, and whether that loot exists: joins against lists made
    // once (a correlated lookup per creature takes minutes on a world of every expansion)
    $creatures = "SELECT ct.entry, ct.npcflag, IF(IFNULL(d.LootID, 0) = 0, ct.entry, d.LootID) loot FROM creature_template ct
        JOIN (SELECT DISTINCT id FROM creature) c ON c.id = ct.entry
        LEFT JOIN creature_template_difficulty d ON d.Entry = ct.entry AND d.DifficultyID = 0";
    $lootless = "SELECT x.entry FROM ($creatures) x LEFT JOIN (SELECT DISTINCT Entry FROM creature_loot_template) l ON l.Entry = x.loot WHERE l.Entry IS NULL";
    $npc = array_merge(
        $ids("SELECT x.entry FROM ($creatures) x LEFT JOIN (SELECT DISTINCT entry FROM npc_vendor) v ON v.entry = x.entry WHERE x.npcflag & 128 AND v.entry IS NULL ORDER BY x.entry"),
        $ids("SELECT x.entry FROM ($creatures) x LEFT JOIN (SELECT DISTINCT CreatureID FROM creature_trainer) t ON t.CreatureID = x.entry WHERE x.npcflag & 16 AND t.CreatureID IS NULL ORDER BY x.entry"),
        $ids("$lootless AND x.npcflag = 0 ORDER BY x.entry"),
        $ids("$lootless AND x.npcflag <> 0 ORDER BY x.entry"));
    $object = $ids('SELECT g.entry FROM gameobject_template g JOIN (SELECT DISTINCT id FROM gameobject) s ON s.id = g.entry
        LEFT JOIN (SELECT DISTINCT Entry FROM gameobject_loot_template) l ON l.Entry = COALESCE(NULLIF(g.Data1, 0), NULLIF(g.Data30, 0), NULLIF(g.Data33, 0), 0)
        WHERE g.type = 3 AND l.Entry IS NULL ORDER BY g.entry');   // the loot a chest rolls: source_chest_loot_id
    $out = ['npc' => array_values(array_unique($npc)), 'object' => $object];
    foreach (['npc' => 'npcs', 'object' => 'objects'] as $kind => $list) {
        $listed = wowhead_pages_listed($list);
        if ($listed !== null) $out[$kind] = array_values(array_filter($out[$kind], fn($id) => isset($listed[$id])));
    }
    return $out;
}

/** The failing checks of what is released and not ok yet (quests, recipes, mounts, toys, spells), as [type, text]:
 *  what wowhead_pages_order() reads the items other content waits for from. ForeverChanges' pull reads them too. */
function wowhead_pages_waiting(): array
{
    $waiting = [];
    foreach (rows("SELECT type, checks FROM ft_entities WHERE internal = 0 AND status <> 'ok' AND type IN ('quest', 'recipe', 'mount', 'toy', 'spell') AND " . released_sql()) as $x) {
        foreach (failing_checks(json_decode((string)$x['checks'], true) ?: []) as $c) $waiting[] = [$x['type'], is_array($c['detail'] ?? null) ? (string)($c['detail']['en'] ?? '') : (string)($c['detail'] ?? '')];
    }
    return $waiting;
}

/** The items the last analysis put in a closed phase because their Wowhead page named no source: [id => true].
 *  $phases: [phase number => phase] as phases() gives them; $closed: the numbers not open (closed_phases()). */
function wowhead_pages_unsourced_later(?array $phases = null, ?array $closed = null): array
{
    $phases ??= phases();          // [number => phase]
    $closed ??= closed_phases();
    $out = [];
    foreach ($phases as $n => $phase) {
        if (!in_array((int)$n, $closed, true)) continue;
        foreach ((array)($phase['wowhead_no_source'] ?? []) as $id) if ((int)$id > 0) $out[(int)$id] = true;
    }
    return $out;
}

/**
 * The Wowhead pages the work list of data/gather.json wants (docs/GATHER.md), by tier: ['gap' => [kind => ids],
 * 'later' => [kind => ids]]. The open phase ("now") and a phase that opened since the analysis go in 'gap', a phase
 * still closed in 'later', in release order. $held(kind): [id => true] the pages held and not due again, left out.
 * $closed: the numbers of the closed phases (closed_phases()), $phases the phases (phases()).
 */
function wowhead_pages_gather_queue(array $list, callable $held, ?array $phases = null, ?array $closed = null): array
{
    $phases ??= phases();
    $closed ??= closed_phases();
    $closedKeys = [];
    foreach ($phases as $n => $p) if (in_array((int)$n, $closed, true)) $closedKeys[(string)$p['key']] = true;
    $out = ['gap' => [], 'later' => []];
    $have = [];
    foreach ((array)($list['wowhead'] ?? []) as $key => $kinds) {
        $tier = isset($closedKeys[(string)$key]) ? 'later' : 'gap';
        foreach ((array)$kinds as $kind => $ids) {
            if (!in_array($kind, ['quest', 'npc', 'object', 'item'], true)) continue;
            $have[$kind] ??= $held($kind);
            foreach ((array)$ids as $id) {
                $id = (int)$id;
                if ($id > 0 && !isset($have[$kind][$id])) $out[$tier][$kind][$id] = $id;
            }
        }
    }
    // a page the open phase wants is not asked again for a later one
    foreach ($out['gap'] as $kind => $ids) if (isset($out['later'][$kind])) $out['later'][$kind] = array_diff_key($out['later'][$kind], $ids);
    foreach ($out as $tier => $kinds) $out[$tier] = array_filter(array_map('array_values', $kinds));
    return $out;
}

/** The pages this tracker wants next, from the last analysis (wowhead_pages_order), and the creatures and objects
 *  whose data is missing (wowhead_pages_missing_data): their pages are moved up in a running crawl. */
function wowhead_pages_queue(): array
{
    $gaps = source_gaps();
    // the items Later only because their page named no source (ft.phases, wowhead_no_source) are read again like gaps:
    // a source that appears on Wowhead brings them back
    $gaps['items'] += wowhead_pages_unsourced_later();
    $waiting = wowhead_pages_waiting();
    $read = [];
    $pages = [];
    foreach (['item', 'quest', 'classic-item'] as $kind) {
        $pages[$kind] = wowhead_pages_brief($kind);
        foreach ($pages[$kind] as $id => $page) {
            // a Forever item or quest page read before the crawler kept its comments' links (record v4) is read again
            if ($kind !== 'classic-item' && ($page['status'] ?? '') === 'ok' && (int)($page['v'] ?? 0) < ($kind === 'quest' ? WOWHEAD_PAGES_COMMENTS_WHOLE_V : WOWHEAD_PAGES_COMMENTS_V)) continue;
            if (!wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', $id)) $read[$kind][$id] = true;
        }
    }
    // the quests without a giver, an ender or their turn-in words: a page read before the crawler kept the whole page
    // (its text, record v3) is read again with them (the v4 test above)
    $queue = wowhead_pages_order($gaps['items'], $waiting, $gaps['noGiver'] + $gaps['noEnder'] + ($gaps['noText'] ?? []), $read, (int)config('wowhead', 'crawl_min_item', 190000));
    // Season of Discovery items Forever kept: their Classic page where Forever's names no source (read in the same
    // tier as the Forever page, right after it)
    $all = wowhead_pages_order($gaps['items'], $waiting, [], [], (int)config('wowhead', 'crawl_min_item', 190000));
    $season = wowhead_pages_season_queue($all['item'], $pages['item'], $read['classic-item'] ?? []);
    $blocking = array_flip(array_slice($all['item'], 0, $all['blocking']));
    $queue['classic/item'] = $season;
    $queue['classicBlocking'] = count(array_filter($season, fn($id) => isset($blocking[$id])));   // in front: $all['item'] has the blocking items first
    // pages an administrator asked for first (wowhead_wanted): those not read yet, or due again
    $queue['wanted'] = [];
    foreach (wowhead_wanted() as $kind => $ids) {
        $have = [];
        foreach (wowhead_pages_each($kind) as $page) {
            // a creature's or object's page read before the crawler kept models (record v1) is read again: the
            // content these pages are asked for needs the model
            if (in_array($kind, ['npc', 'object'], true) && ($page['status'] ?? '') === 'ok' && (int)($page['v'] ?? 0) < WOWHEAD_PAGES_MODEL_V) continue;
            if (!wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', (int)$page['id'])) $have[(int)$page['id']] = true;
        }
        $left = array_values(array_filter($ids, fn($id) => !isset($have[$id])));
        if ($left) $queue['wanted'][$kind] = $left;
    }
    // zones whose fishing the realm lacks, or a gap item is fished in: their page, in the administrator's tier (few)
    $zoneHave = [];
    foreach (wowhead_pages_each('zone') as $page) if (!wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', (int)$page['id'])) $zoneHave[(int)$page['id']] = true;
    $zones = array_values(array_filter(wowhead_pages_fish_zones($pages['item'], $gaps['items']), fn($id) => !isset($zoneHave[$id])));
    if ($zones) $queue['wanted']['zone'] = array_values(array_unique(array_merge($queue['wanted']['zone'] ?? [], $zones)));
    // what the content still to come needs (data/gather.json, docs/GATHER.md): the open phase's in tier 'gap', a closed
    // phase's in tier 'later', earliest phase first; pages held and not due again are left out
    $queue['gather'] = wowhead_pages_gather_queue(gather_list(), function (string $kind) {
        $have = [];
        foreach (wowhead_pages_each($kind) as $page) {
            if (in_array($kind, ['npc', 'object'], true) && ($page['status'] ?? '') === 'ok' && (int)($page['v'] ?? 0) < WOWHEAD_PAGES_MODEL_V) continue;
            if (!wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', (int)$page['id'])) $have[(int)$page['id']] = true;
        }
        return $have;
    });
    // the Craftsman's Writs: their item pages and Wowhead's writ guide, read again every [wowhead] writ_days
    // the item pages loaded above: a second copy of every one of them does not fit in PHP's memory (3,764 pages, about 500 MB each)
    [$queue['writ'], $queue['writGuide']] = wowhead_pages_writ_queue(wowhead_writ_items(), $pages['item'], wowhead_pages('forever-guide'));
    // pages whose row in the answers table is due to be read again ([wowhead] refresh_days, recheck_days; app/wowheaddb.php):
    // the crawl reads them again, so that the table learns what changed on Wowhead
    $queue['recheck'] = wowhead_db_due_pages();
    // the creatures and objects whose comments may name a missing giver or ender (wowhead_comments_queue): read in the
    // gaps' own tier, right after the quests' pages
    $queue['comments'] = wowhead_comments_queue(['noGiver' => $gaps['noGiver'], 'noEnder' => $gaps['noEnder']]);
    foreach (wowhead_pages_missing_data() as $kind => $list) {
        $have = [];
        foreach (wowhead_pages_each($kind) as $page) if (!wowhead_stale((int)($page['fetched'] ?? 0), ($page['status'] ?? '') === 'missing', (int)$page['id'])) $have[(int)$page['id']] = true;
        $queue[$kind] = array_values(array_filter($list, fn($id) => !isset($have[$id])));
    }
    return $queue;
}

/**
 * crawler.js with the queue added and started: what the browser tab runs. Each page goes in with what it is worth
 * (the crawler's TIERS, most first): the quests without a giver or an ender and the items other content waits for
 * ('gap'), the items that only lack a source ('gapOther'), the creatures and objects of the server whose data is missing
 * ('missing'). In a crawl that already queued them they move up. $full: the whole database too (WHC.full(): every
 * list of Forever and Classic first, then the pages they name, after these).
 */
function wowhead_pages_crawler(array $queue, bool $full = false): string
{
    $js = (string)file_get_contents(FT_ROOT . '/tools/wowhead-pages/crawler.js');
    $counted = array_filter($queue, fn($v, $k) => is_array($v) && !in_array($k, ['wanted', 'writ', 'gather', 'recheck', 'comments'], true), ARRAY_FILTER_USE_BOTH) + array_map(fn($ids) => (array)$ids, array_combine(array_map(fn($k) => "wanted $k", array_keys($queue['wanted'] ?? [])), array_values($queue['wanted'] ?? [])));
    $lines = ["\n// ---- queued by the tracker on " . date('Y-m-d H:i') . ': ' . implode(', ', array_map(fn($k) => count($counted[$k]) . " $k pages", array_keys($counted)))
        . (empty($queue['writ']) ? '' : ', ' . count($queue['writ']) . ' writ pages')
        . implode('', array_map(fn($tier) => ', ' . array_sum(array_map('count', (array)($queue['gather'][$tier] ?? []))) . " $tier pages of the work list", array_keys(array_filter((array)($queue['gather'] ?? [])))))
        . (empty($queue['comments']) ? '' : ', ' . array_sum(array_map('count', (array)$queue['comments'])) . ' pages for their comments')
        . (empty($queue['recheck']) ? '' : ', ' . array_sum(array_map('count', (array)$queue['recheck'])) . ' pages due again')];
    $lines[] = '(async () => {';
    // $kind may carry a branch: 'classic/item'. Every page here is one the tracker does not hold, or holds and wants
    // again (due by [wowhead] refresh_days or recheck_days): a tab that read it longer ago than WOWHEAD_PAGES_AGAIN reads
    // it again. Without that a tab that crawls for weeks (the Chrome extension) never reads a page twice, and nothing
    // the tracker holds ever came due again.
    $againAll = json_encode(['again' => WOWHEAD_PAGES_AGAIN]);
    $put = function (string $kind, array $ids, string $tier, int $minV = 0) use (&$lines, $againAll) {
        // $minV: a copy the tab read with an older record version is read again now, not a day later (crawler minV)
        $options = $minV ? json_encode(['again' => WOWHEAD_PAGES_AGAIN, 'minV' => $minV]) : $againAll;
        if ($ids) $lines[] = '  await WHC.prioritize(' . json_encode(array_map(fn($id) => "$kind:" . (int)$id, array_values($ids)), JSON_UNESCAPED_SLASHES) . ', ' . json_encode($tier) . ", $options);";
    };
    $items = array_values($queue['item'] ?? []);
    $blocking = (int)($queue['blocking'] ?? count($items));
    // the Classic pages of Season of Discovery items Forever kept, each after its Forever page (same tier)
    $season = array_values($queue['classic/item'] ?? []);
    $seasonBlocking = (int)($queue['classicBlocking'] ?? 0);
    foreach ($queue['wanted'] ?? [] as $kind => $ids) $put((string)$kind, (array)$ids, 'wanted');
    // the Craftsman's Writs: read again when this tab read them longer ago than the tracker waits between two reads
    $writs = array_values($queue['writ'] ?? []);
    $again = json_encode(['again' => wowhead_writ_seconds() - 6 * 3600]);
    if ($writs) $lines[] = '  await WHC.prioritize(' . json_encode(array_map(fn($id) => 'item:' . (int)$id, $writs)) . ", 'gap', $again);";
    if (!empty($queue['writGuide'])) $lines[] = '  await WHC.prioritize(' . json_encode(['guide:' . WOWHEAD_WRIT_GUIDE], JSON_UNESCAPED_SLASHES) . ", 'gap', $again);";
    $put('quest', $queue['quest'] ?? [], 'gap', WOWHEAD_PAGES_COMMENTS_WHOLE_V);
    // creatures and objects whose comments may name a missing giver or ender: before the items, the quests they are for
    // being what the server misses most
    foreach ($queue['comments'] ?? [] as $kind => $ids) $put((string)$kind, (array)$ids, 'gap', WOWHEAD_PAGES_COMMENTS_V);
    $put('item', array_slice($items, 0, $blocking), 'gap', WOWHEAD_PAGES_COMMENTS_V);
    $put('classic/item', array_slice($season, 0, $seasonBlocking), 'gap');
    // the missing quests, their creatures and objects, and the items they ask for (data/gather.json, the open phase)
    foreach ($queue['gather']['gap'] ?? [] as $kind => $ids) $put((string)$kind, (array)$ids, 'gap');
    $put('item', array_slice($items, $blocking), 'gapOther', WOWHEAD_PAGES_COMMENTS_V);
    $put('classic/item', array_slice($season, $seasonBlocking), 'gapOther');
    // what the release phases not open yet need, earliest phase first
    foreach ($queue['gather']['later'] ?? [] as $kind => $ids) $put((string)$kind, (array)$ids, 'later');
    $put('npc', $queue['npc'] ?? [], 'missing');
    $put('object', $queue['object'] ?? [], 'missing');
    // pages the answers table holds that are due again (wowhead_db_due_pages): with the creatures and objects whose data
    // is missing, before the rest of the database; a page already queued worth more stays where it is
    foreach ($queue['recheck'] ?? [] as $kind => $ids) $put((string)$kind, (array)$ids, 'missing');
    if ($full) $lines[] = '  await WHC.full();';
    $lines[] = '  WHC.start();';
    $lines[] = "  console.log('Wowhead crawler: ' + (await WHC.status()).queued + ' pages queued. WHC.status() says how far it is; WHC.save() saves what it read.');";
    $lines[] = '})();';
    return $js . implode("\n", $lines) . "\n";
}

// ---------------------------------------------------------------- pages asked for by hand
//
// An administrator building content the gaps do not name (a new dungeon's creatures) asks for their pages first:
// data/wowhead-wanted.json {kind: [ids]}, kinds npc, object, item, quest. The crawl reads them before anything else
// (tier 'wanted'); a page read and not due again drops out of the queue by itself.

const WOWHEAD_WANTED_KINDS = ['npc', 'object', 'item', 'quest'];
const WOWHEAD_PAGES_MODEL_V = 2;   // the crawler's record version that keeps a page's model
const WOWHEAD_WANTED_MAX = 2000;

function wowhead_wanted_file(): string { return FT_ROOT . '/data/wowhead-wanted.json'; }

/** {kind: [ids]} asked for first; empty when none. */
function wowhead_wanted(?string $file = null): array
{
    $raw = @json_decode((string)@file_get_contents($file ?? wowhead_wanted_file()), true);
    $out = [];
    foreach (WOWHEAD_WANTED_KINDS as $kind) {
        $ids = array_values(array_unique(array_filter(array_map('intval', (array)($raw[$kind] ?? [])), fn($id) => $id > 0 && $id <= 2147483647)));
        if ($ids) $out[$kind] = $ids;
    }
    return $out;
}

/** Adds ids of one kind to the pages asked for first (or replaces that kind's list). Returns the whole list. */
function wowhead_wanted_set(string $kind, array $ids, bool $replace = false, ?string $file = null): array
{
    if (!in_array($kind, WOWHEAD_WANTED_KINDS, true)) throw new InvalidArgumentException('unknown kind');
    $all = wowhead_wanted($file);
    $ids = array_values(array_filter(array_map('intval', $ids), fn($id) => $id > 0 && $id <= 2147483647));
    $list = array_values(array_unique(array_merge($replace ? [] : ($all[$kind] ?? []), $ids)));
    $all[$kind] = array_slice($list, 0, WOWHEAD_WANTED_MAX);
    if (!$all[$kind]) unset($all[$kind]);
    $path = $file ?? wowhead_wanted_file();
    @mkdir(dirname($path), 0775, true);
    if (@file_put_contents($path, json_encode($all, JSON_UNESCAPED_SLASHES) . "\n", LOCK_EX) === false) throw new RuntimeException('not writable');
    return $all;
}

/** The kept pages of one kind for some ids: {id: record} (only those read). */
function wowhead_pages_get(string $kind, array $ids, ?array $dirs = null): array
{
    $want = array_flip(array_map('intval', $ids));
    $out = [];
    foreach (wowhead_pages_each($kind, $dirs) as $page) if (isset($want[(int)($page['id'] ?? 0)])) $out[(int)$page['id']] = $page;
    ksort($out);
    return $out;
}

// ---------------------------------------------------------------- the Chrome extension (tools/wowhead-pages/extension)
//
// The extension keeps a Wowhead tab open in Chrome, loads the crawler this tracker builds into it after every load, and
// sends what it reads to api/wowhead-push: a crawl that starts and goes on by itself (docs/WOWHEAD-PAGES.md). It sends
// a key of its own, made the first time it is downloaded and kept in data/, so it needs no setting.

function wowhead_extension_key_file(): string { return FT_ROOT . '/data/wowhead-extension.key'; }

/** The extension's key ('' while none was made); $make: made now when there is none. */
function wowhead_extension_key(bool $make = false, ?string $file = null): string
{
    $file ??= wowhead_extension_key_file();
    $key = is_file($file) ? trim((string)file_get_contents($file)) : '';
    if ($key === '' && $make) {
        $key = bin2hex(random_bytes(20));
        if (@file_put_contents($file, $key . "\n", LOCK_EX) === false) throw new RuntimeException('the data folder cannot be written to');
        @chmod($file, 0600);
    }
    return $key;
}

/** Whether a key sent to api/wowhead-push or api/wowhead-crawler is one this tracker takes: [wowhead] push_token
 *  (a script's), or the extension's. Each counts only with 16 characters or more. */
function wowhead_push_allowed(string $given, ?string $keyFile = null): bool
{
    foreach ([(string)config('wowhead', 'push_token', ''), wowhead_extension_key(false, $keyFile)] as $key) {
        if (strlen($key) >= 16 && hash_equals($key, $given)) return true;
    }
    return false;
}

/** The address the extension calls this tracker at: the one this request came to (an administrator's browser). */
function wowhead_extension_origin(): ?string
{
    $host = (string)($_SERVER['HTTP_HOST'] ?? '');
    if (!preg_match('/^[\w.\-]+(:\d{1,5})?$|^\[[0-9a-f:.]+\](:\d{1,5})?$/i', $host)) return null;
    $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || strtolower((string)($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https';
    return ($https ? 'https' : 'http') . '://' . $host . rtrim(base_path(), '/');
}

/** The extension as a zip (one folder, wowhead-crawl/), with this tracker's address and key in config.json. */
function wowhead_extension_zip(string $tracker, string $key, ?string $dir = null): string
{
    $dir ??= FT_ROOT . '/tools/wowhead-pages/extension';
    $tmp = tempnam(sys_get_temp_dir(), 'whx');
    $zip = new ZipArchive();
    if ($zip->open($tmp, ZipArchive::OVERWRITE) !== true) throw new RuntimeException('the zip cannot be made');
    foreach (scandir($dir) ?: [] as $file) {
        if ($file[0] !== '.' && !str_starts_with($file, 'config') && is_file("$dir/$file")) $zip->addFile("$dir/$file", "wowhead-crawl/$file");
    }
    $zip->addFromString('wowhead-crawl/config.json', json_encode(['tracker' => $tracker, 'key' => $key], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");
    $zip->close();
    $bytes = (string)file_get_contents($tmp);
    @unlink($tmp);
    return $bytes;
}

// ---------------------------------------------------------------- Craftsman's Writs
//
// A Craftsman's Writ is a tradable item that starts a crafting quest. Wowhead's Forever guide calls them world drops
// that suit the zone and level, and gives each its tier (Journeyman, Expert, Artisan); no item page names a creature
// or a chest yet. So the crawl reads the writs' pages and the guide again every [wowhead] writ_days, and The Forge ›
// Writs shows what they say: the day Wowhead names a source, it is there, for a world-data file to turn into loot rows.

/** {item id => quest id} of the Craftsman's Writs, from the last analysis (ft_meta writ_items). */
function wowhead_writ_items(?array $meta = null): array
{
    $out = [];
    foreach ((array)(($meta ?? meta())['writ_items'] ?? []) as $item => $quest) if ((int)$item > 0) $out[(int)$item] = (int)$quest;
    ksort($out);
    return $out;
}

/** {item id => tier} of the writs as the client names them under the name (1 Journeyman, 2 Expert, 3 Artisan; ft_meta
 *  writ_tiers): the client's word, before the guide's. */
function wowhead_writ_tiers(?array $meta = null): array
{
    $out = [];
    foreach ((array)(($meta ?? meta())['writ_tiers'] ?? []) as $item => $tier) if ((int)$item > 0 && isset(WOWHEAD_WRIT_TIERS[(int)$tier])) $out[(int)$item] = (int)$tier;
    return $out;
}

/** How long a writ page is kept before it is read again: [wowhead] writ_days (3), in seconds; at least a day. */
function wowhead_writ_seconds(?float $days = null): int
{
    $days ??= (float)config('wowhead', 'writ_days', 3);
    return (int)max(86400, $days * 86400);
}

/** [the writ items whose page is due (none kept, or older than wowhead_writ_seconds), whether the guide is due].
 *  $items: Forever's item pages [id => record]; $guides: the guide shelf [query => record]. */
function wowhead_pages_writ_queue(array $writs, array $items, array $guides, ?int $now = null, ?int $seconds = null): array
{
    $now ??= time();
    $seconds ??= wowhead_writ_seconds();
    $due = fn(?array $page) => !$page || $now - (int)($page['fetched'] ?? 0) > $seconds;
    $ids = array_values(array_filter(array_keys($writs), fn($id) => $due($items[$id] ?? null)));
    return [$ids, $writs ? $due($guides[WOWHEAD_WRIT_GUIDE] ?? null) : false];
}

/** The tabs of an item page that name where a writ comes from: [tab => what it is], the ones the import reads first. */
const WOWHEAD_WRIT_SOURCE_TABS = ['dropped-by' => 'npc', 'contained-in-object' => 'object', 'contained-in-item' => 'item', 'mined-from-object' => 'object',
    'gathered-from-object' => 'object', 'skinned-from' => 'npc', 'pick-pocketed-from' => 'npc', 'sold-by' => 'npc', 'reward-from-q' => 'quest', 'fished-in' => 'zone'];

/**
 * What Wowhead says of each writ: [item => ['quest', 'tier' (the client's, else the guide's: 1-3, 0 unknown), 'guideTier'
 * (the guide's, 0 when it names none), 'fetched' (0: not read),
 * 'status' ('ok', 'missing', '' not read), 'sources' => [tab => rows {id, count?, outof?}], 'zones' => [zone ids of
 * its map pins]]], in item order. Facts only: no row is made up where a page shows none.
 */
function wowhead_pages_writs(array $writs, array $items, array $guides, array $clientTiers = []): array
{
    $tiers = [];
    foreach ((array)($guides[WOWHEAD_WRIT_GUIDE]['rows'] ?? []) as $row) if (is_int($row['id'] ?? null)) $tiers[$row['id']] = (int)($row['tier'] ?? 0);
    $out = [];
    foreach ($writs as $item => $quest) {
        $page = $items[$item] ?? null;
        $sources = [];
        foreach (WOWHEAD_WRIT_SOURCE_TABS as $tab => $_) {
            $rows = array_values(array_filter((array)($page['tabs'][$tab]['rows'] ?? []), fn($r) => is_int($r['id'] ?? null)));
            if (!$rows) continue;
            $sources[$tab] = array_map(fn($r) => array_filter(['id' => $r['id'], 'count' => $r['count'] ?? null, 'outof' => $r['outof'] ?? null], fn($v) => $v !== null), $rows);
        }
        $out[$item] = ['quest' => $quest, 'tier' => $clientTiers[$item] ?? $tiers[$item] ?? 0, 'guideTier' => $tiers[$item] ?? 0, 'fetched' => (int)($page['fetched'] ?? 0), 'status' => (string)($page['status'] ?? ''),
            'sources' => $sources, 'zones' => array_values(array_map('intval', array_filter(array_keys((array)($page['map'] ?? [])), 'is_numeric')))];
    }
    return $out;
}
