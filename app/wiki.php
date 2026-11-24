<?php
// warcraft.wiki.gg (https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever, CC BY-SA 4.0): the community wiki's WoW
// Forever pages, written by its editors. It ranks right after Icy Veins (the project's decision of 2026-11-23).
//
// What it imports, for the last analysis' gaps only:
//   start / end   who gives and who takes a quest: the quest page's Questbox names them by a link ([[Sprite
//                 Jumpsprocket]]); the linked page's {{Elinks-NPC|id}} or {{Elinks-object|id}} is the id
//   sell          what an NPC sells: the rows of its ==Sells== table, each item by a link whose page holds the item's
//                 id (itemid=, {{Elinks-item|id}}). A row paid in money ({{Cost|g|s|c}}) sells at the item's price; one
//                 paid in currencies or items alone ({{Costitem|5|Merchant's Favor}}, the page of each naming its
//                 currencyid or itemid) takes the server's own ItemExtendedCost that asks exactly that; any other
//                 price (money and items together, a price written in words) is left out and counted
//   text          the turn-in words: a quest page's ==Progress== and ==Completion== sections, as the core writes them
//                 (<name> becomes $N, a line break $B), only where the server's quest window holds none
// A link whose page names no id, or that does not exist, is left out and counted: names are never matched against the
// server's own. A page that names several (a Classic NPC's id beside its retail copy's, Elinks-NPC2) is taken only when
// exactly one of them stands in the server's world (a spawn): read at the import, so the snapshot holds the id taken.
//
// How it is read: the MediaWiki API (api.php), never the pages themselves. The Forever categories (WIKI_CATEGORIES),
// fifty pages with their wikitext a request, then the pages their links name that the categories do not hold, fifty
// titles a request: about sixty requests in all, one a second, with maxlag so that a busy wiki is left alone. What was
// read is kept in data/wiki/pages.json.gz. See docs/SOURCES.md.
require_once FT_APP . '/sources.php';

const WIKI_API = 'https://warcraft.wiki.gg/api.php';
/** The categories read whole: the wiki's Forever quests, the creatures and objects that give, take and sell, the items. */
const WIKI_CATEGORIES = ['Forever quests', 'Forever NPCs', 'Forever mobs', 'Forever objects', 'Forever items'];
/** Pages a request (the API's limit for wikitext). */
const WIKI_BATCH = 50;
/** Requests one import may make at most: the whole Forever set is about sixty. */
const WIKI_MAX_REQUESTS = 400;

/** One API answer as an array, or [null, why]. A maxlag or 429 answer waits what the wiki asks and tries once more. */
function wiki_api(array $params): array
{
    static $last = 0.0;
    $params += ['format' => 'json', 'formatversion' => 2, 'maxlag' => 5];
    $url = WIKI_API . '?' . http_build_query($params);
    for ($try = 0; $try < 3; $try++) {
        $wait = 1.0 - (microtime(true) - $last);
        if ($wait > 0) usleep((int)($wait * 1e6));
        $last = microtime(true);
        [$status, $body] = source_http($url, 60);
        $json = json_decode($body, true);
        if ($status === 429 || $status === 503 || (($json['error']['code'] ?? '') === 'maxlag')) { sleep(5 * ($try + 1)); continue; }
        if ($status !== 200 || !is_array($json)) return [null, sprintf(t('the wiki answered HTTP %d', 'le wiki a répondu HTTP %d'), $status)];
        if (isset($json['error'])) return [null, (string)($json['error']['info'] ?? $json['error']['code'] ?? 'error')];
        return [$json, ''];
    }
    return [null, t('the wiki is busy: try again later', 'le wiki est occupé : réessayez plus tard')];
}

/** A page of an API answer as [title, text, revision time], or null (missing, no content). */
function wiki_page_of(array $p): ?array
{
    $text = $p['revisions'][0]['slots']['main']['content'] ?? null;
    if (!is_string($text) || !empty($p['missing'])) return null;
    return [(string)$p['title'], $text, (string)($p['revisions'][0]['timestamp'] ?? '')];
}

/**
 * Reads the wiki: [pages, error, requests], pages as [title => [text, revision time]]. Every page of WIKI_CATEGORIES,
 * then the pages their quest givers, enders and vendor rows link to ($more: the titles wanted besides). $say: progress.
 */
function wiki_fetch(?callable $say = null): array
{
    $pages = []; $requests = 0;
    $rv = ['prop' => 'revisions', 'rvprop' => 'content|timestamp', 'rvslots' => 'main'];
    foreach (WIKI_CATEGORIES as $category) {
        $continue = [];
        do {
            if (++$requests > WIKI_MAX_REQUESTS) return [$pages, t('too many requests: stopped', 'trop de requêtes : arrêt'), $requests];
            [$json, $error] = wiki_api(['action' => 'query', 'generator' => 'categorymembers', 'gcmtitle' => "Category:$category",
                'gcmnamespace' => 0, 'gcmlimit' => WIKI_BATCH] + $rv + $continue);
            if ($json === null) return [$pages, "$category: $error", $requests];
            foreach ($json['query']['pages'] ?? [] as $p) if ($page = wiki_page_of($p)) $pages[$page[0]] = [$page[1], $page[2], true];   // a Forever page
            $continue = (array)($json['continue'] ?? []);
        } while ($continue);
        if ($say) $say(sprintf('%s: %d pages so far', $category, count($pages)));
    }
    // the pages the links name that no category held (a Classic NPC who gives a Forever quest, a Classic item sold)
    $wanted = [];
    foreach ($pages as [$text]) foreach (wiki_links_wanted($text) as $title) if (!isset($pages[$title])) $wanted[$title] = true;
    foreach (array_chunk(array_keys($wanted), WIKI_BATCH) as $chunk) {
        if (++$requests > WIKI_MAX_REQUESTS) return [$pages, t('too many requests: stopped', 'trop de requêtes : arrêt'), $requests];
        // a batch of large pages passes the API's size limit: the rest of their content comes with 'continue'
        $to = []; $continue = [];
        do {
            [$json, $error] = wiki_api(['action' => 'query', 'titles' => implode('|', $chunk), 'redirects' => 1] + $rv + $continue);
            if ($json === null) return [$pages, $error, $requests];
            // a linked page is no Forever page (false): its one id is taken only when the server spawns it (wiki_who)
            foreach ($json['query']['pages'] ?? [] as $p) if ($page = wiki_page_of($p)) $pages[$page[0]] = [$page[1], $page[2], false];
            // a link that leads through a redirect (or another spelling) is kept under the title the link wrote
            foreach (array_merge($json['query']['normalized'] ?? [], $json['query']['redirects'] ?? []) as $r) $to[(string)$r['from']] = (string)$r['to'];
            $continue = (array)($json['continue'] ?? []);
        } while ($continue && ++$requests <= WIKI_MAX_REQUESTS);
        if ($continue) return [$pages, t('too many requests: stopped', 'trop de requêtes : arrêt'), $requests];
        foreach ($chunk as $title) {
            $t = $title; for ($i = 0; $i < 3 && isset($to[$t]); $i++) $t = $to[$t];
            if ($t !== $title && isset($pages[$t])) $pages[$title] = $pages[$t];
        }
    }
    if ($say) $say(sprintf('%d pages read in %d requests', count($pages), $requests));
    return [$pages, '', $requests];
}

/** A link's page title as MediaWiki keeps it: no anchor, spaces for underscores, the first letter upper case. */
function wiki_title(string $target): string
{
    $target = trim(preg_replace('/\s+/u', ' ', str_replace('_', ' ', explode('#', $target, 2)[0])));
    return $target === '' ? '' : mb_strtoupper(mb_substr($target, 0, 1)) . mb_substr($target, 1);
}

/** The title the first [[link]] of a value leads to, '' when it has none. */
function wiki_first_link(string $value): string
{
    return preg_match('/\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/u', $value, $m) ? wiki_title($m[1]) : '';
}

/** The fields of a page's first {{<box> ...}} infobox: [field => value]. */
function wiki_box(string $text, string $box): array
{
    if (!preg_match('/\{\{\s*' . preg_quote($box, '/') . '\s*\n(.*?)\n\s*\}\}/su', $text, $m)) return [];
    $out = [];
    preg_match_all('/^\s*\|\s*(\w+)\s*=(.*)$/mu', $m[1], $fields, PREG_SET_ORDER);
    foreach ($fields as [, $key, $value]) $out[strtolower($key)] = trim($value);
    return $out;
}

/** A section's text (==Name==, any level) up to the next heading, '' when the page has none. */
function wiki_section(string $text, string $name): string
{
    if (!preg_match('/^(=+)\s*' . preg_quote($name, '/') . '\s*\1\s*$/mu', $text, $m, PREG_OFFSET_CAPTURE)) return '';
    $from = $m[0][1] + strlen($m[0][0]);
    $end = preg_match('/^=+[^=\n]+=+\s*$/mu', $text, $n, PREG_OFFSET_CAPTURE, $from) ? $n[0][1] : strlen($text);
    return trim(substr($text, $from, $end - $from));
}

/** What a page is in the game: ['npc'|'go'|'item' => [ids]], from its {{Elinks-…}} links and item tooltips. */
function wiki_ids(string $text): array
{
    $out = ['npc' => [], 'go' => [], 'item' => []];
    preg_match_all('/\{\{\s*Elinks-(NPC2?|object|item)\s*\|([^}]*)\}\}/iu', $text, $links, PREG_SET_ORDER);
    foreach ($links as [, $kind, $args]) {
        $kind = ['npc' => 'npc', 'npc2' => 'npc', 'object' => 'go', 'item' => 'item'][strtolower($kind)];
        foreach (explode('|', $args) as $arg) if (preg_match('/^\s*(\d+)\s*$/', $arg, $m)) $out[$kind][] = (int)$m[1];
    }
    preg_match_all('/^\s*\|\s*itemid\s*=\s*(\d+)\s*$/mu', $text, $items);
    foreach ($items[1] as $id) $out['item'][] = (int)$id;
    return array_map(fn($ids) => array_values(array_unique(array_filter($ids))), $out);
}

/**
 * The one creature or object a page is: [kind, id], or null when it names none, or several and $spawned does not pick
 * one. $spawned: [kind => [id => true]], the ids that stand in the server's world; null: none is picked.
 */
function wiki_who(string $text, ?array $spawned = null, bool $forever = true): ?array
{
    $ids = wiki_ids($text);
    $all = array_merge(array_map(fn($id) => ['npc', $id], $ids['npc']), array_map(fn($id) => ['go', $id], $ids['go']));
    // a page outside the Forever categories often names the Classic or retail creature of that name (Argent Medic:
    // the old Naxxramas event's), so even its one id must stand in the server's world
    if (count($all) === 1 && ($forever || isset($spawned[$all[0][0]][$all[0][1]]))) return $all[0];
    if ($spawned === null || count($all) < 2) return null;
    $standing = array_values(array_filter($all, fn($w) => isset($spawned[$w[0]][$w[1]])));
    return count($standing) === 1 ? $standing[0] : null;
}

/** The ids whose spawns decide (wiki_who): of every page that names several creatures or objects, and of every page
 *  outside the Forever categories. ['npc' => [ids], 'go' => [ids]]. */
function wiki_several(array $pages): array
{
    $out = ['npc' => [], 'go' => []];
    foreach ($pages as $page) {
        $ids = wiki_ids($page[0]);
        if (count($ids['npc']) + count($ids['go']) < 2 && ($page[2] ?? true)) continue;
        foreach (['npc', 'go'] as $kind) foreach ($ids[$kind] as $id) $out[$kind][$id] = true;
    }
    return array_map('array_keys', $out);
}

/** Which of these ids stand in the server's world: [kind => [id => true]]. */
function wiki_spawned(array $ids): array
{
    $out = ['npc' => [], 'go' => []];
    foreach (['npc' => 'creature', 'go' => 'gameobject'] as $kind => $table) {
        foreach (array_chunk($ids[$kind] ?? [], 1000) as $chunk) {
            foreach (rows("SELECT DISTINCT id FROM `$table` WHERE id IN (" . implode(',', array_map('intval', $chunk)) . ')', [], 'world') as $r) $out[$kind][(int)$r['id']] = true;
        }
    }
    return $out;
}

/** The currency or item a page is: 'c<id>' or 'i<id>', '' when it names neither, or several. */
function wiki_token(string $text): string
{
    preg_match_all('/^\s*\|\s*currencyid\s*=\s*(\d+)\s*$/mu', $text, $c);
    $currencies = array_values(array_unique(array_map('intval', $c[1])));
    if (count($currencies) === 1) return 'c' . $currencies[0];
    if ($currencies) return '';
    $item = wiki_item($text);
    return $item ? "i$item" : '';
}

/** The one item a page is, or 0. */
function wiki_item(string $text): int
{
    $ids = wiki_ids($text)['item'];
    return count($ids) === 1 ? $ids[0] : 0;
}

/** The quest a page is: [id, start link, end link], or null when it is no quest page. */
function wiki_quest(string $text): ?array
{
    $box = wiki_box($text, 'Questbox');
    if (!preg_match('/^\d+$/', $box['id'] ?? '')) return null;
    return [(int)$box['id'], wiki_first_link($box['start'] ?? ''), wiki_first_link($box['end'] ?? '')];
}

/** The rows of a page's ==Sells== table: [[item title, price]]. The price: [] for money alone, [[title, count], ...]
 *  for currencies or items alone ({{Costitem|count|title}}), null for anything else. */
function wiki_sells(string $text): array
{
    $out = [];
    foreach (preg_split('/^\|-.*$/mu', wiki_section($text, 'Sells')) as $row) {
        $row = trim($row);
        if (!str_starts_with($row, '|') || str_starts_with($row, '|}')) continue;
        $cells = wiki_cells(ltrim($row, "| \t"));
        // the item is the first cell with a link; the price follows it (a quantity column may come first)
        $at = wiki_first_link($cells[0] ?? '') !== '' ? 0 : (wiki_first_link($cells[1] ?? '') !== '' ? 1 : -1);
        if ($at < 0) continue;
        $out[] = [wiki_first_link($cells[$at]), wiki_price((string)($cells[$at + 1] ?? ''))];
    }
    return $out;
}

/** A Sells table's price cell as wiki_sells() gives it. */
function wiki_price(string $cost): ?array
{
    // {{Cost|gold|silver|copper}} alone is money
    if (preg_match('/^\s*\{\{\s*Cost\s*(\|\s*\d*\s*){0,3}\}\}\s*$/iu', $cost)) return [];
    // {{Costitem|count|title}} one or more times, and nothing else
    if (!preg_match('/^\s*(\{\{\s*Costitem\s*\|\s*\d+\s*\|[^{}|]+\}\}\s*)+$/iu', $cost)) return null;
    preg_match_all('/\{\{\s*Costitem\s*\|\s*(\d+)\s*\|([^{}|]+)\}\}/iu', $cost, $m, PREG_SET_ORDER);
    return array_map(fn($x) => [wiki_title($x[2]), (int)$x[1]], $m);
}

/** A table row's cells, split on || and on a new line's | but never inside {{templates}} or [[links]]. */
function wiki_cells(string $row): array
{
    $cells = ['']; $depth = 0;
    for ($i = 0, $n = strlen($row); $i < $n; $i++) {
        $two = substr($row, $i, 2);
        if ($two === '{{' || $two === '[[') { $depth++; $cells[count($cells) - 1] .= $two; $i++; continue; }
        if (($two === '}}' || $two === ']]') && $depth > 0) { $depth--; $cells[count($cells) - 1] .= $two; $i++; continue; }
        if ($depth === 0 && $two === '||') { $cells[] = ''; $i++; continue; }
        if ($depth === 0 && $row[$i] === "\n" && ($row[$i + 1] ?? '') === '|') { $cells[] = ''; $i++; continue; }
        $cells[count($cells) - 1] .= $row[$i];
    }
    return array_map('trim', $cells);
}

/** The titles a page links to that a card may need: its quest's giver and ender, the items it sells. */
function wiki_links_wanted(string $text): array
{
    $out = [];
    if ($q = wiki_quest($text)) { if ($q[1] !== '') $out[] = $q[1]; if ($q[2] !== '') $out[] = $q[2]; }
    foreach (wiki_sells($text) as [$title, $price]) { $out[] = $title; foreach ((array)$price as [$token]) $out[] = $token; }
    return $out;
}

/**
 * A section's words as the core writes them, or null when they cannot be (empty, "...", a template or a table the
 * wiki draws for them, a note in brackets instead of the words). <name> becomes $N, <class> $C, <race> $R; a line
 * break $B.
 */
function wiki_core_text(string $section): ?string
{
    $s = preg_replace(['/<!--.*?-->/su', '/<ref[^>]*\/>/iu', '/<ref[^>]*>.*?<\/ref>/isu'], '', $section);
    $s = preg_replace('/<br\s*\/?>[ \t]*\n?/iu', "\n", $s);   // a break at a line's end is one break
    if (preg_match('/\[\[\s*:?\s*(File|Image|Category|Media)\s*:/iu', $s)) return null;   // a picture or a category: no words
    $s = preg_replace('/\[\[\s*:?(?:[^\]|]*\|)?([^\]]*)\]\]/u', '$1', $s);   // [[target|words]], [[words]], [[:words]]
    // the game's words for one gender or the other, <brother/sister>, as the core writes them
    $s = preg_replace('/<([A-Za-z\' -]+)\/([A-Za-z\' -]+)>/u', '\$G$1:$2;', $s);
    $s = str_replace(["'''", "''"], '', $s);
    $s = strtr($s, ['<name>' => '$n', '<Name>' => '$N', '<class>' => '$c', '<Class>' => '$C', '<race>' => '$r', '<Race>' => '$R']);
    $s = trim(preg_replace("/[ \t]+\n/u", "\n", $s));
    if ($s === '' || preg_match('/^[.…\s]*$/u', $s) || preg_match('/\{\{|\}\}|\{\||\[\[|\]\]|^[:*#;]|<[a-z\/]/mu', $s)) return null;
    if (preg_match('/^\(.*\)$/su', $s) || preg_match('/^(unknown|none|n\/a|tbd)\.?$/iu', $s)) return null;
    if (strlen($s) > 8000) return null;
    return str_replace("\n", '$B', $s);
}

/**
 * The evidence of the pages ([title => [text, revision time]]): ['start', 'end', 'sell', 'text', 'left'], as
 * source_tables() reads it. Everything the pages say, not only the gaps: source_tables keeps to them. $spawned: the
 * ids that stand in the server's world, which pick among a page's several ids (wiki_who).
 */
function wiki_evidence(array $pages, ?array $spawned = null): array
{
    $ev = ['start' => [], 'end' => [], 'sell' => [], 'text' => [], 'left' => []];
    $count = function (string $why) use (&$ev) { $ev['left'][$why] = ($ev['left'][$why] ?? 0) + 1; };
    foreach ($pages as $title => $page) {
        $text = $page[0];
        if ($q = wiki_quest($text)) {
            [$quest, $start, $end] = $q;
            foreach (['start' => $start, 'end' => $end] as $role => $link) {
                if ($link === '') continue;
                if (!isset($pages[$link])) { $count('wiki_link_no_page'); continue; }
                $who = wiki_who($pages[$link][0], $spawned, $pages[$link][2] ?? true);
                if ($who === null) { $count('wiki_link_no_single_id'); continue; }
                $ev[$role][] = [$who[0], $who[1], $quest];
            }
            foreach (['progress' => 'Progress', 'complete' => 'Completion'] as $moment => $section) {
                $words = wiki_section($text, $section);
                if ($words === '') continue;
                $core = wiki_core_text($words);
                if ($core === null) { $count('wiki_text_not_plain'); continue; }
                $ev['text'][] = [$quest, $moment, $core];
            }
        }
        $sells = wiki_sells($text);
        if (!$sells) continue;
        // a vendor is taken only when its page names one creature and its Sells section holds one table: Fizzlefuse's
        // page names three and holds a Season of Discovery table beside Forever's, whose rows must not be mixed
        $who = wiki_who($text, null, $page[2] ?? true);
        if (substr_count(wiki_section($text, 'Sells'), '{|') > 1) { $ev['left']['wiki_vendor_several_tables'] = ($ev['left']['wiki_vendor_several_tables'] ?? 0) + count($sells); continue; }
        if ($who === null || $who[0] !== 'npc') { $ev['left']['wiki_vendor_no_single_id'] = ($ev['left']['wiki_vendor_no_single_id'] ?? 0) + count($sells); continue; }
        foreach ($sells as [$link, $price]) {
            if ($price === null) { $count('wiki_vendor_price_unread'); continue; }
            if (!isset($pages[$link])) { $count('wiki_vendor_item_no_page'); continue; }   // the wiki has no page for it yet
            $item = wiki_item($pages[$link][0]);
            if (!$item) { $count('wiki_vendor_item_no_id'); continue; }
            // currencies and items as ft/costs.py keys them: "c3402x5", sorted, comma-separated
            $parts = [];
            foreach ($price as [$token, $n]) {
                $id = isset($pages[$token]) ? wiki_token($pages[$token][0]) : '';
                if ($id === '' || $n <= 0) { $parts = null; break; }
                $parts[] = "{$id}x$n";
            }
            if ($parts === null) { $count('wiki_vendor_price_no_id'); continue; }
            sort($parts);
            $ev['sell'][] = $parts ? [$who[1], $item, 0, implode(',', $parts)] : [$who[1], $item, 0];
        }
    }
    $ev['left'] = array_filter($ev['left']);
    return $ev;
}

/** The newest revision time of the pages read, as the version: "2026-11-23T14:02:11Z". */
function wiki_version(array $pages): string
{
    $newest = '';
    foreach ($pages as [, $time]) if ($time > $newest) $newest = $time;
    return $newest !== '' ? $newest : gmdate('Y-m-d\TH:i:s\Z');
}

/** Reads the wiki and makes its import card (see the top of this file). $ifNew (the container's check): no card when
 *  no page changed since the last one. */
function wiki_import(?callable $say = null, bool $ifNew = false): array
{
    if ($e = source_check()) return $e;
    if (analysis_status()['running']) return ['ok' => true, 'retry' => true, 'id' => 0, 'counts' => [], 'ignored' => [], 'message' => t('An analysis is running: warcraft.wiki.gg is read next time.', 'Une analyse est en cours : warcraft.wiki.gg sera lu la prochaine fois.')];
    [$pages, $error, $requests] = wiki_fetch($say);
    if ($error !== '') return ['ok' => false, 'message' => 'warcraft.wiki.gg: ' . $error];
    if (!$pages) return ['ok' => false, 'message' => t('warcraft.wiki.gg: no page was read.', 'warcraft.wiki.gg : aucune page lue.')];
    $keep = FT_ROOT . '/data/wiki/pages.json.gz';
    @mkdir(dirname($keep), 0775, true);
    @file_put_contents($keep, gzencode((string)json_encode($pages, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE)));
    $ev = wiki_evidence($pages, wiki_spawned(wiki_several($pages)));
    $version = wiki_version($pages);
    // the container's check: the same wiki (no page edited since) makes no new card, unless every source was asked again
    $mark = FT_ROOT . '/data/wiki/imported';
    if ($ifNew && trim((string)@file_get_contents($mark)) === $version && (int)@filemtime($mark) >= source_refresh_epoch()) {
        return ['ok' => true, 'id' => 0, 'counts' => [], 'ignored' => [], 'message' => sprintf(t('warcraft.wiki.gg: no page changed since %s.', 'warcraft.wiki.gg : aucune page modifiée depuis %s.'), $version)];
    }
    @file_put_contents($mark, $version);
    snapshot_try('wiki', $version, $ev);
    return wiki_card($ev, $version, source_gaps());
}

/** The card of the wiki's evidence, against the gaps and the server as they are now. Also made from the database
 *  (snapshot_card). */
function wiki_card(array $ev, string $version, array $gaps): array
{
    $label = 'warcraft.wiki.gg ' . substr($version, 0, 10);
    [$tables, $left, $fills] = source_tables($ev, $label, $gaps);   // fills: words for turn-in rows that hold none
    return source_card('wiki', $label, 'wiki@' . $version, $tables, $left, $fills);
}
