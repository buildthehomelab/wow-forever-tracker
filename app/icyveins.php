<?php
// ------------------------------------------------------------------ Icy Veins (reference only)
// db.icy-veins.com/wow-forever: the game client's tables, and on top of them what players' addons recorded on live
// Forever. Its pages are built from a JSON API (/api/catalog/wowf/<kind>/<id>, and /api/catalog/wowf/<kind>?page=N for
// the list of a kind), which is what the tracker reads. robots.txt allows everything; no licence is stated: reference
// for your own server.
//
// The import keeps a mirror of all of it in data/icyveins/<kind>/<id>.json.gz: every NPC, object, quest, item, zone,
// flight path and map Icy Veins lists, each answer whole (the entity, its children and every relation), so nothing it
// knows is thrown away. The gaps are asked first (the items players cannot get, quests without giver / ender or turn-in
// text, the server's trainers), then the rest. Polite: one request at a time, two a second. A full first pass is about
// 67,000 lookups (nine hours); answers are asked again after 14 days (7 for "not found"): it keeps growing.
//
// What the cards take from the mirror (docs/SOURCES.md, "Icy Veins"):
//   NPC drops            creature_loot_template; Skinning -> skinning_loot_template; Pick Pocket -> pickpocketing_loot_template
//   object contents      gameobject_loot_template (chests, ore veins, herbs)
//   quest-only drops     QuestRequired = 1
//   vendor stock         npc_vendor
//   trainer lists        trainer_spell (only from NPCs whose service list says trainer: bankers and innkeepers carry
//                        stray lists in the recording)
//   quest givers/enders  creature_ / gameobject_queststarter / questender
//   turn-in words        quest_offer_reward, quest_request_items
//   NPC services         creature_template.npcflag bits (innkeeper, banker, flight master, spirit healer)
//   positions            the locator (tools/ft/locator.py), where Wowhead has none
// Kept in the mirror and counted on the card, not written: levels, coin, gossip text, container contents (no chance
// is recorded), flight routes, quest chains.

const ICYVEINS = 'https://db.icy-veins.com/api/catalog/wowf/';
/** Icy Veins' placeholders in turn-in words, and the core's tokens for them. */
const ICYVEINS_TEXT_TOKENS = ['<Class>' => '$C', '<class>' => '$c', '<Race>' => '$R', '<race>' => '$r', '<Name>' => '$N', '<name>' => '$n'];
const ICYVEINS_MAX_FAILURES = 20;   // lookups failing in a row before a run stops (an outage, a block, no network)
/** The kinds the mirror holds, in the order a run walks them. The rest of the API (spells, achievements, …) is the
 *  game client's own tables, which the tracker reads from the client itself. */
const ICYVEINS_KINDS = ['npc', 'gameobject', 'quest', 'zone', 'flight-path', 'ui-map', 'item'];
/** The parts of an answer that are kept; the rest is link metadata and tooltips, the same for all. */
const ICYVEINS_KEEP = ['type', 'id', 'entity', 'children', 'relations'];
const ICYVEINS_LIST_LIMIT = 200;    // the most the API gives per list page
const ICYVEINS_SKINNING = [8613, 8617, 8618, 10768];   // the Skinning spell of each rank
/** Mining and Herb Gathering on a creature: the core loots those through the skinning table too (SkinLootID). */
const ICYVEINS_SKIN_LIKE = [2575, 2576, 2366, 2368];
const ICYVEINS_PICK_POCKET = 921;
/** Icy Veins' service numbers (an NPC's addon_services) and the npcflag bit each needs on this server. Vendor (5) and
 *  trainer (7) are left to the vendor and trainer rows: applying those adds their flags. */
const ICYVEINS_SERVICE_FLAGS = [6 => 8192, 8 => 131072, 18 => 16384, 20 => 65536];
const ICYVEINS_SERVICE_VENDOR = 5;
const ICYVEINS_SERVICE_TRAINER = 7;

/** The run stops itself: Icy Veins did not answer ICYVEINS_MAX_FAILURES lookups in a row. */
final class IcyVeinsStopped extends Exception {}

/** Seconds to wait before the lookup that follows $failures failed ones in a row: 1, 2, 4 … up to a minute. A short
 *  outage then costs a handful of requests, and the 20 failures that stop a run take about a quarter of an hour. */
function icyveins_backoff(int $failures): int
{
    return $failures < 1 ? 0 : (int)min(60, 2 ** min($failures - 1, 6));
}

function icyveins_dir(): string { return FT_ROOT . '/data/icyveins'; }

/** Where an answer is kept: the gzipped file; a plain .json is the older form, still read. */
function icyveins_path(string $kind, int $id): string { return icyveins_dir() . "/$kind/$id.json.gz"; }

/** The kept answer of $kind $id, or null when there is none. */
function icyveins_cached(string $kind, int $id): ?array
{
    $path = icyveins_path($kind, $id);
    foreach ([$path, substr($path, 0, -3)] as $file) {
        if (!is_file($file)) continue;
        $raw = (string)@file_get_contents($file);
        if (str_ends_with($file, '.gz')) $raw = (string)@gzdecode($raw);
        $data = json_decode($raw, true);
        if (is_array($data)) return $data;
    }
    return null;
}

function icyveins_store(string $kind, int $id, array $data): void
{
    $path = icyveins_path($kind, $id);
    @mkdir(dirname($path), 0775, true);
    file_put_contents($path . '.tmp', gzencode(json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE), 6));
    rename($path . '.tmp', $path);
    @unlink(substr($path, 0, -3));   // the older plain file
}

/** Whether a kept answer is still good: two weeks (one for "not known"), never one of the older form that kept the
 *  relations alone, and never one older than "ask every source again". */
function icyveins_fresh(?array $data): bool
{
    if ($data === null) return false;
    if (empty($data['missing']) && !isset($data['entity'])) return false;
    $age = time() - (int)($data['fetched'] ?? 0);
    return $age < (empty($data['missing']) ? 14 : 7) * 86400 && (int)($data['fetched'] ?? 0) >= source_refresh_epoch();
}

/** One request to the API, at two a second at most and slower after failures: [status, body]. */
function icyveins_request(string $path, int $failures): array
{
    static $last = 0.0;
    $wait = max(0.5, icyveins_backoff($failures)) - (microtime(true) - $last);
    if ($wait > 0) usleep((int)($wait * 1e6));
    $last = microtime(true);
    [$status, $body] = source_http(ICYVEINS . $path, 30);
    return [$status, $body];
}

/** The lookups one run may make ([icyveins] max). */
function icyveins_max(): int { return (int)(config('icyveins', 'max', 100000) ?: 100000); }

/** One answer, from the mirror or asked. $failures counts the lookups that got no answer in a row (neither 200 nor
 *  404; nothing is kept for them, so the next run asks again) and $lastFailure says what the last one was. */
function icyveins_get(string $kind, int $id, int &$asked, int &$failures = 0, string &$lastFailure = ''): ?array
{
    $data = icyveins_cached($kind, $id);
    if (icyveins_fresh($data) || $asked >= icyveins_max()) return $data;
    $asked++;
    [$status, $body] = icyveins_request("$kind/$id", $failures);
    if ($status === 404) $new = ['missing' => true];
    elseif ($status !== 200) {
        $failures++;
        $lastFailure = "$kind $id: " . ($status ? "HTTP $status" : 'no answer');
        return $data;
    } else {
        // a 200 that is no JSON (a challenge page, a cut body) is a failure, not "not known": the kept answer stays
        $full = json_decode($body, true);
        if (!is_array($full)) {
            $failures++;
            $lastFailure = "$kind $id: an answer that is not JSON";
            return $data;
        }
        $new = !empty($full['entity']) ? array_intersect_key($full, array_flip(ICYVEINS_KEEP)) : ['missing' => true];
    }
    $failures = 0;
    $new['fetched'] = time();
    icyveins_store($kind, $id, $new);
    return $new;
}

/**
 * Every id Icy Veins lists for $kind, from its list pages (kept a day in data/icyveins/<kind>.ids.json). Without an
 * API key the API gives the first 10,000 rows of a list and answers HTTP 400 beyond them ("narrow the filters or
 * sort"): the list is read from both ends (dir=desc), which covers 20,000 rows. Items are more (about 32,000): the
 * ones neither end reaches are added from what the mirror's NPCs, objects and quests name (icyveins_named_items).
 * When a page does not answer, the list kept last time is used, and the ids already in the mirror without one.
 */
function icyveins_ids(string $kind, int &$asked, int &$failures, string &$lastFailure): array
{
    $file = icyveins_dir() . "/$kind.ids.json";
    $kept = is_file($file) ? (json_decode((string)file_get_contents($file), true) ?: []) : [];
    if ($kept && time() - (int)($kept['fetched'] ?? 0) < 86400 && (int)($kept['fetched'] ?? 0) >= source_refresh_epoch()) return array_map('intval', (array)$kept['ids']);
    $ids = []; $total = null;
    foreach (['', '&dir=desc'] as $order) {
        if ($total !== null && count($ids) >= $total) break;   // the first end gave all of it
        $pages = 1;
        for ($page = 1; $page <= $pages; $page++) {
            if ($asked >= icyveins_max()) { $ids = null; break 2; }
            $asked++;
            [$status, $body] = icyveins_request("$kind?limit=" . ICYVEINS_LIST_LIMIT . "&page=$page$order", $failures);
            $list = $status === 200 ? json_decode($body, true) : null;
            if ($status === 400 && $page > 1) { $failures = 0; break; }   // the 10,000-row cap: this end is done
            if (!is_array($list) || !isset($list['rows'])) {
                $failures++;
                $lastFailure = "$kind list page $page: " . ($status ? "HTTP $status" : 'no answer');
                if ($failures >= ICYVEINS_MAX_FAILURES) throw new IcyVeinsStopped($lastFailure);
                $page--;   // the same page again, after the back-off
                continue;
            }
            $failures = 0;
            $pages = max(1, (int)($list['pages'] ?? 1));
            $total = (int)($list['total'] ?? 0);
            foreach ((array)$list['rows'] as $r) if ((int)($r['id'] ?? 0) > 0) $ids[(int)$r['id']] = true;
            if (count($ids) >= $total) break 2;   // the two ends met
        }
    }
    if ($ids === null) {   // the run's lookups ran out half way: the list kept last time, else what the mirror has
        if ($kept) return array_map('intval', (array)$kept['ids']);
        return icyveins_mirrored($kind);
    }
    $ids = array_keys($ids);
    @mkdir(icyveins_dir(), 0775, true);
    file_put_contents($file, json_encode(['fetched' => time(), 'ids' => $ids, 'total' => $total]));
    return $ids;
}

/** The items the mirror's NPCs, objects and quests name: what they drop, sell, hold, ask for or give. */
function icyveins_named_items(array $mirror): array
{
    $items = [];
    $add = function ($id) use (&$items) { if ((int)$id > 0) $items[(int)$id] = true; };
    foreach ($mirror['npc'] ?? [] as $id) {
        $r = (array)((icyveins_cached('npc', (int)$id) ?? [])['relations'] ?? []);
        foreach (['addon_drops', 'addon_sells'] as $rel) foreach ((array)($r[$rel] ?? []) as $x) $add($x['item_id'] ?? 0);
    }
    foreach ($mirror['gameobject'] ?? [] as $id) {
        $r = (array)((icyveins_cached('gameobject', (int)$id) ?? [])['relations'] ?? []);
        foreach (['addon_contains', 'addon_gathers'] as $rel) foreach ((array)($r[$rel] ?? []) as $x) $add($x['item_id'] ?? 0);
    }
    foreach ($mirror['quest'] ?? [] as $id) {
        $r = (array)((icyveins_cached('quest', (int)$id) ?? [])['relations'] ?? []);
        foreach ((array)($r['rewards'] ?? []) as $x) $add($x['item_id'] ?? 0);
        foreach (['quest_items', 'started_by_items'] as $rel) foreach ((array)($r[$rel] ?? []) as $x) $add($x['id'] ?? 0);
    }
    return array_keys($items);
}

/** The ids of $kind the mirror holds an answer for. */
function icyveins_mirrored(string $kind): array
{
    $ids = [];
    foreach ((array)@scandir(icyveins_dir() . "/$kind") as $f) if (preg_match('/^(\d+)\.json(\.gz)?$/', (string)$f, $m)) $ids[(int)$m[1]] = true;
    return array_keys($ids);
}

// ---- reading answers into evidence

/** The table a drop goes to by the spell that looted it: 'npc' (a corpse), 'skin', 'pick', or null (unknown). */
function icyveins_loot_kind(int $spell): ?string
{
    if ($spell === 0) return 'npc';
    if (in_array($spell, ICYVEINS_SKINNING, true) || in_array($spell, ICYVEINS_SKIN_LIKE, true)) return 'skin';
    if ($spell === ICYVEINS_PICK_POCKET) return 'pick';
    return null;
}

function icyveins_left(array &$ev, string $why, int $n = 1): void { $ev['left'][$why] = ($ev['left'][$why] ?? 0) + $n; }

/** One drop: [kind, id, item, chance %]; quest-only drops are remembered in $ev['quest_drop']. */
function icyveins_drop(array &$ev, string $kind, int $id, int $item, array $d): void
{
    if ($id <= 0 || $item <= 0) return;
    $ev['drop'][] = [$kind, $id, $item, 100 * (float)($d['chance'] ?? 0)];
    if (!empty($d['quest'])) $ev['quest_drop']["$kind:$id:$item"] = true;
}

/** A sale players saw for money ([npc, item, stock]): a sale for items or a currency has no cost this import can give. */
function icyveins_sale(array &$ev, int $npc, int $item, array $s): void
{
    if ($npc <= 0 || $item <= 0 || (isset($s['current']) && !$s['current'])) return;
    if (!empty($s['cost_item_ids']) || !empty($s['cost_currency_ids'])) { icyveins_left($ev, 'icyveins_vendor_other_cost'); return; }
    $ev['sell'][] = [$npc, $item, (int)($s['remaining'] ?? 0) > 0 ? (int)$s['remaining'] : 0];
}

function icyveins_quest_evidence(array &$ev, int $quest, array $r): void
{
    foreach ((array)($r['addon_givers'] ?? []) as $g) {
        [$kind, $id] = !empty($g['npc_id']) ? ['npc', (int)$g['npc_id']] : ['go', (int)($g['gameobject_id'] ?? 0)];
        if (!$id) continue;
        if (!empty($g['starts'])) $ev['start'][] = [$kind, $id, $quest];
        if (!empty($g['ends'])) $ev['end'][] = [$kind, $id, $quest];
    }
    foreach ((array)($r['addon_dialog'] ?? []) as $d) {
        // the recording writes the player's class and race as <Class> and <Race> (its $B and $N are the core's already)
        $text = strtr(trim((string)($d['text'] ?? '')), ICYVEINS_TEXT_TOKENS);
        if (in_array($d['kind'] ?? '', ['complete', 'progress'], true) && $text !== '' && strlen($text) <= 8000) $ev['text'][] = [$quest, (string)$d['kind'], $text];
    }
}

function icyveins_item_evidence(array &$ev, int $item, array $r): void
{
    foreach ((array)($r['addon_dropped_by'] ?? []) as $d) {
        if (!empty($d['gameobject_id'])) { icyveins_drop($ev, 'go', (int)$d['gameobject_id'], $item, $d); continue; }
        $kind = icyveins_loot_kind((int)($d['spell_id'] ?? 0));
        if ($kind === null) { icyveins_left($ev, 'icyveins_loot_spell_unknown'); continue; }
        icyveins_drop($ev, $kind, (int)($d['npc_id'] ?? 0), $item, $d);
    }
    foreach ((array)($r['addon_sold_by'] ?? []) as $s) icyveins_sale($ev, (int)($s['npc_id'] ?? 0), $item, $s);
    // opened from another item (a clam, a lockbox, a bag): Icy Veins records no chance for these
    foreach ((array)($r['addon_gathered_from'] ?? []) as $g) {
        if (($g['src'] ?? '') === 'item' && (int)($g['container_item_id'] ?? 0) > 0) $ev['container'][(int)$g['container_item_id'] . ':' . $item] = true;
    }
}

/** One NPC's answer: drops (by corpse, Skinning, Pick Pocket), stock, trainer list, quests, services, and what is kept
 *  for the report (levels, coin, gossip, positions). */
function icyveins_npc_evidence(array &$ev, int $npc, array $r): void
{
    foreach ((array)($r['addon_drops'] ?? []) as $d) {
        $kind = icyveins_loot_kind((int)($d['spell_id'] ?? 0));
        if ($kind === null) { icyveins_left($ev, 'icyveins_loot_spell_unknown'); continue; }
        icyveins_drop($ev, $kind, $npc, (int)($d['item_id'] ?? 0), $d);
    }
    foreach ((array)($r['addon_sells'] ?? []) as $s) icyveins_sale($ev, $npc, (int)($s['item_id'] ?? 0), $s);
    $services = array_map(fn($s) => (int)($s['service'] ?? 0), (array)($r['addon_services'] ?? []));
    foreach ($services as $service) {
        if (isset(ICYVEINS_SERVICE_FLAGS[$service])) $ev['service'][] = [$npc, ICYVEINS_SERVICE_FLAGS[$service]];
        elseif (!in_array($service, [ICYVEINS_SERVICE_VENDOR, ICYVEINS_SERVICE_TRAINER], true)) icyveins_left($ev, 'icyveins_service_unknown');
    }
    // the recording gives bankers, innkeepers and spirit healers the trainer list of whoever was spoken to before:
    // a list counts only from an NPC that offers training (or one whose services were never recorded)
    $trains = (array)($r['addon_trains'] ?? []);
    if ($trains && $services && !in_array(ICYVEINS_SERVICE_TRAINER, $services, true)) { icyveins_left($ev, 'icyveins_trainer_list_not_a_trainer', count($trains)); $trains = []; }
    $recipes = [];
    foreach ($trains as $s) {
        if (empty($s['spell_id']) || !empty($s['item_id'])) continue;
        $cost = max(array_map(fn($p) => (int)($p['cost'] ?? 0), (array)($s['prices'] ?? [])) ?: [(int)($s['cost'] ?? 0)]);
        $rankNo = preg_match('/(\d+)/', (string)($s['rank'] ?? ''), $m) ? (int)$m[1] : 0;
        $details = json_decode((string)($s['details'] ?? ''), true) ?: [];
        if ((int)($details['trainerType'] ?? 0) === 2) {
            // a profession or a recipe: the recording names its skill and the rank it needs ("Tailoring", "140")
            if (!isset($details['skillRank']) || !is_numeric($details['skillRank'])) { icyveins_left($ev, 'trainer_profession_skill_unknown'); continue; }
            $line = source_skill_line((string)($details['skillLine'] ?? $details['skill'] ?? ''), (string)($s['name'] ?? ''));
            if (!$line) { icyveins_left($ev, 'trainer_skill_unknown'); continue; }
            $recipes[$line][] = [$npc, (int)$s['spell_id'], $cost, (int)($s['req_level'] ?? 0), $line, (int)$details['skillRank'], [], $rankNo];
            continue;
        }
        $ev['train'][] = [$npc, (int)$s['spell_id'], $cost, (int)($s['req_level'] ?? 0), 0, 0, null, $rankNo];
    }
    // a profession trainer teaches one profession: recipes of another one in its list were recorded at someone else
    if ($recipes) {
        $main = array_search(max(array_map('count', $recipes)), array_map('count', $recipes), true);
        foreach ($recipes as $line => $list) {
            if ($line === $main) $ev['train'] = array_merge($ev['train'] ?? [], $list);
            else icyveins_left($ev, 'icyveins_recipe_other_profession', count($list));
        }
    }
    foreach ((array)($r['addon_quests'] ?? []) as $q) {
        if ((int)($q['quest_id'] ?? 0) <= 0) continue;
        if (!empty($q['starts'])) $ev['start'][] = ['npc', $npc, (int)$q['quest_id']];
        if (!empty($q['ends'])) $ev['end'][] = ['npc', $npc, (int)$q['quest_id']];
    }
    if (!empty($r['addon_levels'])) $ev['kept']['icyveins_kept_levels'] = ($ev['kept']['icyveins_kept_levels'] ?? 0) + 1;
    if (array_filter((array)($r['addon_loot'] ?? []), fn($l) => (int)($l['spell_id'] ?? 0) === 0 && (int)($l['average_coin'] ?? 0) > 0)) $ev['kept']['icyveins_kept_coin'] = ($ev['kept']['icyveins_kept_coin'] ?? 0) + 1;
    if (!empty($r['addon_gossip'])) $ev['kept']['icyveins_kept_gossip'] = ($ev['kept']['icyveins_kept_gossip'] ?? 0) + 1;
    if (!empty($r['addon_points'])) $ev['kept']['icyveins_kept_positions'] = ($ev['kept']['icyveins_kept_positions'] ?? 0) + 1;
}

function icyveins_object_evidence(array &$ev, int $go, array $r): void
{
    foreach ((array)($r['addon_contains'] ?? []) as $d) icyveins_drop($ev, 'go', $go, (int)($d['item_id'] ?? 0), $d);
    foreach ((array)($r['addon_quests'] ?? []) as $q) {
        if ((int)($q['quest_id'] ?? 0) <= 0) continue;
        if (!empty($q['starts'])) $ev['start'][] = ['go', $go, (int)$q['quest_id']];
        if (!empty($q['ends'])) $ev['end'][] = ['go', $go, (int)$q['quest_id']];
    }
    if (!empty($r['addon_points'])) $ev['kept']['icyveins_kept_positions'] = ($ev['kept']['icyveins_kept_positions'] ?? 0) + 1;
}

/** Everything the mirror holds, as one evidence set. The same drop seen from both ends (the NPC's page and the item's)
 *  is the same measure: source_tables() keeps the best of a pair. */
function icyveins_evidence(?array $mirror = null): array
{
    $ev = ['sell' => [], 'drop' => [], 'start' => [], 'end' => [], 'train' => [], 'text' => [], 'service' => [], 'quest_drop' => [], 'container' => [], 'left' => [], 'kept' => []];
    $read = ['npc' => 'icyveins_npc_evidence', 'gameobject' => 'icyveins_object_evidence', 'quest' => 'icyveins_quest_evidence', 'item' => 'icyveins_item_evidence'];
    foreach ($read as $kind => $fn) {
        foreach ($mirror[$kind] ?? icyveins_mirrored($kind) as $id) {
            $data = icyveins_cached($kind, (int)$id);
            if ($data && empty($data['missing'])) $fn($ev, (int)$id, (array)($data['relations'] ?? []));
        }
    }
    foreach (['flight-path' => 'icyveins_kept_flight_paths', 'zone' => 'icyveins_kept_zones'] as $kind => $why) {
        $n = count($mirror[$kind] ?? icyveins_mirrored($kind));
        if ($n) $ev['kept'][$why] = $n;
    }
    if ($ev['container']) $ev['left']['icyveins_container_no_chance'] = count($ev['container']);
    return $ev;
}

/** Drops and vendors of the gap items Icy Veins already answered (the mirror only: no lookup). */
function icyveins_cached_items(array $items): array
{
    $ev = ['sell' => [], 'drop' => []];
    foreach (array_keys($items) as $item) {
        $data = icyveins_cached('item', (int)$item);
        if ($data) icyveins_item_evidence($ev, (int)$item, (array)($data['relations'] ?? []));
    }
    return $ev;
}

/** Givers and enders of the gap quests Icy Veins already answered (the mirror only). */
function icyveins_cached_quests(array $quests): array
{
    $ev = ['start' => [], 'end' => []];
    foreach (array_keys($quests) as $quest) {
        $data = icyveins_cached('quest', (int)$quest);
        if ($data) icyveins_quest_evidence($ev, (int)$quest, (array)($data['relations'] ?? []));
    }
    return $ev;
}

/** The official quests whose turn-in words the server lacks (no quest_offer_reward row): asked early. */
function icyveins_quests_without_words(): array
{
    if (!table_exists('quest_offer_reward', 'world')) return [];
    $out = [];
    foreach (rows('SELECT q.ID FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM quest_offer_reward o WHERE o.ID = q.ID)', [], 'world') as $r) $out[(int)$r['ID']] = true;
    return array_intersect_key($out, official_quests());
}

/** The npcflag bits the recorded services need and the server's creatures lack, as one "bits" change. */
function icyveins_service_changes(array $services): array
{
    $want = [];
    foreach ($services as [$npc, $bit]) $want[(int)$npc] = ($want[(int)$npc] ?? 0) | (int)$bit;
    $rows = []; $left = [];
    foreach (array_chunk(array_keys($want), 1000) as $chunk) {
        $have = [];
        foreach (rows('SELECT entry, npcflag FROM creature_template WHERE entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $have[(int)$r['entry']] = (int)$r['npcflag'];
        foreach ($chunk as $npc) {
            if (!isset($have[$npc])) { $left['icyveins_service_npc_unknown'] = ($left['icyveins_service_npc_unknown'] ?? 0) + 1; continue; }
            $missing = $want[$npc] & ~$have[$npc];
            if ($missing) $rows[] = [$npc, $missing];
        }
    }
    $changes = $rows ? [['db' => 'world', 'table' => 'creature_template', 'columns' => ['entry', 'npcflag'], 'match' => ['entry'], 'set' => 'npcflag', 'bits' => 'npcflag', 'rows' => $rows]] : [];
    return [$changes, $left];
}

/**
 * The card of the gaps' answers alone (items players cannot get, quests without giver, ender or turn-in words, the
 * server's trainers), made when they are all asked, before the rest of the mirror. Returns the log line that says
 * so. A failure here is logged and the run goes on: the full card comes at the end either way.
 */
function icyveins_early_card(array $first, array $gaps): string
{
    try {
        $ev = icyveins_evidence(['npc' => $first['npc'] ?? [], 'item' => $first['item'] ?? [], 'quest' => $first['quest'] ?? [], 'gameobject' => [], 'zone' => [], 'flight-path' => []]);
        $label = 'Icy Veins ' . date('Y-m-d') . ' (gaps)';
        [$tables, $left] = source_tables($ev, $label, $gaps);
        [$flags, $flagsLeft] = icyveins_service_changes($ev['service']);
        $left['icyveins_early_card'] = 1;
        $card = source_card('icyveins', $label, 'icyveins@' . date('Y-m-d') . '-gaps', $tables, $left + $flagsLeft, $flags);
        return $card['ok'] ? sprintf('early card #%d from the gaps: %s', $card['id'], strip_tags((string)$card['message'])) : 'no early card: ' . strip_tags((string)$card['message']);
    } catch (Throwable $e) {
        error_log('Forever Tracker: the early Icy Veins card could not be made: ' . $e->getMessage());
        return 'no early card (' . mb_substr($e->getMessage(), 0, 200) . '); the run goes on';
    }
}

function icyveins_import(?callable $progress = null): array
{
    if ($e = source_check()) return $e;
    $gaps = source_gaps();
    // besides the gaps: the items of the drops an import brought, to see whether their chance moved (source_refresh)
    $again = array_diff_key(source_refresh_items('icyveins'), $gaps['items']);
    $first = [
        'item' => array_keys($gaps['items'] + $again),
        'quest' => array_keys($gaps['noGiver'] + $gaps['noEnder'] + array_diff_key(icyveins_quests_without_words(), $gaps['later']['quests'] ?? [])),
        'npc' => source_trainer_npcs(),
    ];
    $asked = 0; $done = 0; $failures = 0; $lastFailure = ''; $saidAt = 0;
    $say = function (string $what) use (&$done, &$asked, &$saidAt, $progress) { $saidAt = $asked; if ($progress) $progress("$what: $done looked at, $asked asked"); };
    $get = function (string $kind, int $id) use (&$asked, &$failures, &$lastFailure, &$done, &$saidAt, $say): void {
        icyveins_get($kind, $id, $asked, $failures, $lastFailure);
        if ($failures >= ICYVEINS_MAX_FAILURES) throw new IcyVeinsStopped($lastFailure);
        // a line (and a sign of life on the Imports page) every 20 lookups asked, or every 2,000 the mirror answered
        if (++$done % 2000 === 0 || $asked - $saidAt >= 20) $say($kind);
    };
    $mirror = [];
    try {
        // what the gaps need first, so that a run cut short has already asked what matters most
        foreach ($first as $kind => $ids) foreach ($ids as $id) $get($kind, (int)$id);
        $say('gaps asked');
        // a card now, from the gaps' answers alone: the whole mirror takes hours more. The full card at the end
        // replaces it unless something was applied from it (source_supersede)
        $early = icyveins_early_card($first, $gaps);
        if ($progress) $progress($early);
        foreach (ICYVEINS_KINDS as $kind) {
            $mirror[$kind] = icyveins_ids($kind, $asked, $failures, $lastFailure);
            // items are listed only in part (the API's 10,000-row cap, from both ends): the rest come from what the
            // NPCs, objects and quests read before them name
            if ($kind === 'item') $mirror[$kind] = array_values(array_unique(array_merge($mirror[$kind], icyveins_named_items($mirror))));
            if ($progress) $progress(sprintf('%s: %d listed', $kind, count($mirror[$kind])));
            foreach ($mirror[$kind] as $id) $get($kind, (int)$id);
            $mirror[$kind] = array_values(array_unique(array_merge($mirror[$kind], array_map('intval', $first[$kind] ?? []))));
        }
    } catch (IcyVeinsStopped $stop) {
        // no card from half the answers: it would replace a fuller one made earlier
        return ['ok' => false, 'stopped' => true, 'id' => 0, 'counts' => [], 'ignored' => [],
            'message' => sprintf(t('Icy Veins stopped: %d lookups in a row got no answer (the last one, %s), after %d were looked at. What it answered is kept: start Import Icy Veins again once it answers, and the run goes on from there.',
                'Icy Veins arrêté : %d requêtes de suite sont restées sans réponse (la dernière, %s), après %d consultations. Ses réponses sont conservées : relancez Importer Icy Veins quand il répondra, l’import reprendra où il en était.'),
                ICYVEINS_MAX_FAILURES, $stop->getMessage(), $done)];
    }
    if ($progress) $progress('reading the mirror');
    $ev = icyveins_evidence($mirror);
    if ($asked >= icyveins_max()) $ev['left']['icyveins_lookup_limit_reached_run_again'] = 1;
    snapshot_try('icyveins', date('Y-m-d'), $ev);
    return icyveins_card($ev, date('Y-m-d'), $gaps);
}

/** The card of Icy Veins' evidence: rows, drops measured again, the service flags its NPCs show. Also made from the
 *  database (snapshot_card). */
function icyveins_card(array $ev, string $date, array $gaps): array
{
    $label = 'Icy Veins ' . $date;
    [$tables, $left] = source_tables($ev, $label, $gaps);
    [$changes, $moved] = source_refresh($ev, 'icyveins');
    [$flags, $flagsLeft] = icyveins_service_changes($ev['service'] ?? []);
    return source_card('icyveins', $label, 'icyveins@' . $date, $tables, $left + $moved + $flagsLeft + ($ev['kept'] ?? []), array_merge($changes, $flags));
}
