<?php
// AtlasLoot Classic Forever (GPL-2.0, CurseForge project 1422985): the loot browser most Forever players run, updated
// almost daily. Its dungeon and raid tables name the creature (or the boss) that drops each item, Forever's new items
// and dungeons included; droprate.lua holds measured chances for the Classic ones. There is no public git repository:
// the newest Forever file is taken from CurseForge and kept in data/atlasloot/<file id>.zip (all of them: [atlasloot] keep
// limits how many).
//
// Only the files the addon's _Forever.toc loads are read, and a file that switches itself off below The Burning
// Crusade (data-tbc.lua) is skipped: what it lists is not in Forever. So are blocks wrapped for a later game version,
// instances marked IgnoreAsSource and rows with a price (vendor stock, not drops).
//
//   atlasloot_import()          a card for the gaps (docs/SOURCES.md); with $ifNew, only when CurseForge has a file
//                               this tracker has not imported yet (the container checks every few hours)
//   atlasloot_cached_drops()    its drops from the last download, as a witness for NorgannonDB (no download)
require_once FT_APP . '/sources.php';
require_once FT_APP . '/forge.php';

const ATLASLOOT_PROJECT = 1422985;
const ATLASLOOT_FILES = 'https://www.curseforge.com/api/v1/mods/' . ATLASLOOT_PROJECT . '/files';
const ATLASLOOT_LOOT_ADDON = 'AtlasLootClassic_DungeonsAndRaids';
const ATLASLOOT_MAX_ENTRY = 32 * 1024 * 1024;   // bytes of one unpacked file (the largest is about 0.3 MB)
// downloads kept in data/atlasloot/: all of them (0) unless [atlasloot] keep says how many, a few MB each
function atlasloot_keep(): int { return max(0, (int)config('atlasloot', 'keep', 0)); }
const ATLASLOOT_MIN_SHARE = 3;                   // an even share never counts fewer items than this (1 item: 33 %)

function atlasloot_dir(): string { return FT_ROOT . '/data/atlasloot'; }

/** The newest Forever file on CurseForge: ['id', 'name', 'size', 'version'], or null. */
function atlasloot_latest(): ?array
{
    [$status, $body] = source_http(ATLASLOOT_FILES . '?pageIndex=0&pageSize=50&sort=dateCreated&sortDescending=true');
    if ($status !== 200) return null;
    foreach ((array)(json_decode($body, true)['data'] ?? []) as $f) {
        // the project also hosts AtlasLoot for the TBC Anniversary realms
        if ((int)($f['releaseType'] ?? 0) !== 1 || !preg_match('/^AtlasLoot[- ]Classic[- ]Forever[- ]([\d.]+)\b.*\.zip$/', (string)($f['fileName'] ?? ''), $m)) continue;
        return ['id' => (int)$f['id'], 'name' => (string)$f['fileName'], 'size' => (int)($f['fileLength'] ?? 0), 'version' => $m[1]];
    }
    return null;
}

/** Downloads $file once into data/atlasloot/ (whole, then renamed into place); [path, error]. */
function atlasloot_fetch(array $file): array
{
    $path = atlasloot_dir() . '/' . (int)$file['id'] . '.zip';
    if (is_file($path) && filesize($path) === $file['size']) return [$path, ''];
    [$status, $body] = source_http(ATLASLOOT_FILES . '/' . (int)$file['id'] . '/download', 120);
    if ($status !== 200 || strlen($body) !== $file['size']) return ['', sprintf(t('AtlasLoot %s did not download cleanly.', 'AtlasLoot %s ne s’est pas téléchargé correctement.'), $file['version'])];
    @mkdir(atlasloot_dir(), 0775, true);
    foreach (glob(atlasloot_dir() . '/*.part') ?: [] as $old) if (filemtime($old) < time() - 3600) @unlink($old);   // a killed run's
    $part = $path . '.' . getmypid() . '.part';
    file_put_contents($part, $body);
    rename($part, $path);
    $zips = glob(atlasloot_dir() . '/*.zip') ?: [];
    usort($zips, fn($a, $b) => (int)basename($b, '.zip') <=> (int)basename($a, '.zip'));
    if (atlasloot_keep()) foreach (array_slice($zips, atlasloot_keep()) as $old) @unlink($old);
    // every file of the addon in the answers table (app/sourceanswers.php)
    require_once FT_APP . '/sourceanswers.php';
    source_answers_version_try('atlasloot');
    return [$path, ''];
}

/**
 * The loot tables of a downloaded zip: ['bosses' => [[instance, boss, [npc ids], [item => heading]]], 'rates' => [npc]
 * [item] => chance %]. A heading is the label row above an item ("Hurley Blackbreath", "Forever"), '' before the
 * first. Read from the archive in memory (the zip uses \ in its paths; nothing is written out).
 */
function atlasloot_tables(string $zipPath): array
{
    if (!class_exists('ZipArchive')) throw new RuntimeException('PHP zip extension missing');
    $zip = new ZipArchive();
    if ($zip->open($zipPath) !== true) throw new RuntimeException("cannot open $zipPath");
    $files = [];
    for ($i = 0; $i < $zip->numFiles; $i++) {
        $name = str_replace('\\', '/', (string)$zip->getNameIndex($i));
        // the loot addon's files by their own path, every other file as "../<addon>/<path>"
        if (str_starts_with($name, ATLASLOOT_LOOT_ADDON . '/')) $files[substr($name, strlen(ATLASLOOT_LOOT_ADDON) + 1)] = $i;
        elseif (str_starts_with($name, 'AtlasLootClassic_')) $files["../$name"] = $i;
    }
    $read = function (string $name) use ($zip, $files): string {
        if (!isset($files[$name])) return '';
        if ((int)($zip->statIndex($files[$name])['size'] ?? 0) > ATLASLOOT_MAX_ENTRY) throw new RuntimeException("$name is too large");
        return (string)$zip->getFromIndex($files[$name]);
    };
    try {
        $toc = $read(ATLASLOOT_LOOT_ADDON . '_Forever.toc');
        if ($toc === '') throw new RuntimeException('no ' . ATLASLOOT_LOOT_ADDON . '_Forever.toc in the zip');
        $out = ['bosses' => [], 'rates' => [], 'lists' => []];
        foreach (atlasloot_toc_files($toc) as $line) {
            $text = $read($line);
            if (basename($line) === 'droprate.lua') { $out['rates'] = atlasloot_rates($text); continue; }
            if (atlasloot_later_only($text)) continue;
            if (!str_contains($text, 'ItemDB:Add(')) continue;
            array_push($out['bosses'], ...atlasloot_bosses($text));
            // vendor stock (a row with a price) is no drop: kept as a list row
            foreach (atlasloot_lists($text, 'DungeonsAndRaids') as $row) if ($row[6] !== '') $out['lists'][] = $row;
        }
        // the other parts the Forever addon loads (crafting, factions, PvP, collections): no creature is named, so
        // nothing on the server is made from them; they are kept as lists to compare with the other sources
        foreach (ATLASLOOT_LIST_ADDONS as $module) {
            $prefix = "AtlasLootClassic_$module/";
            $toc = $read("../{$prefix}AtlasLootClassic_{$module}_Forever.toc");
            foreach ($toc === '' ? [] : atlasloot_toc_files($toc) as $line) {
                $text = $read("../$prefix$line");
                if ($text === '' || atlasloot_later_only($text) || !str_contains($text, 'ItemDB:Add(')) continue;
                array_push($out['lists'], ...atlasloot_lists($text, $module));
            }
        }
    } finally {
        $zip->close();
    }
    return $out;
}

/** droprate.lua: `[npc] = { [item] = chance, ... }` (its later per-phase overrides are not read). */
function atlasloot_rates(string $text): array
{
    $rates = [];
    preg_match_all('/\[(\d+)\]\s*=\s*\{([^{}]*)\}/', $text, $m, PREG_SET_ORDER);
    foreach ($m as [, $npc, $body]) {
        preg_match_all('/\[(\d+)\]\s*=\s*([\d.]+)/', $body, $r, PREG_SET_ORDER);
        foreach ($r as [, $item, $chance]) $rates[(int)$npc][(int)$item] = (float)$chance;
    }
    return $rates;
}

/** The .lua files a .toc loads, in order, with / for \\. */
function atlasloot_toc_files(string $toc): array
{
    $out = [];
    foreach (preg_split('/\R/', $toc) as $line) {
        $line = str_replace('\\', '/', trim($line));
        if ($line !== '' && $line[0] !== '#' && str_ends_with($line, '.lua')) $out[] = $line;
    }
    return $out;
}

/** A file that switches itself off below The Burning Crusade (its lists are not Forever's). */
function atlasloot_later_only(string $text): bool
{
    return (bool)preg_match('/GameVersion_LT\(AtlasLoot\.BC_VERSION_NUM\)\s*then\s*return\s+end/', $text);
}

/** The AtlasLoot parts read as lists, besides the dungeons and raids. */
const ATLASLOOT_LIST_ADDONS = ['Crafting', 'Factions', 'PvP', 'Collections'];

/**
 * Every row of every list of a data file, as AtlasLoot shows it: [id, "module/table/list[/side]", module, table, list,
 * side, price, faction, standing]. The id is a spell in Crafting (what a profession makes), an item elsewhere. side
 * is the list's difficulty when it is a faction's (ALLIANCE_DIFF, HORDE_DIFF), price the row's price text
 * ("money:1500", honor and marks), faction and standing those of a reputation list ("f529rep8": Argent Dawn,
 * exalted; or the table's FactionID). Set tables (set numbers, not items) and blocks for a later version are left out.
 */
function atlasloot_lists(string $text, string $module): array
{
    $out = [];
    $table = ''; $faction = 0; $depth = 0; $itemsDepth = -1; $list = null; $side = ''; $standing = 0; $listFaction = 0; $skipTable = false;
    foreach (preg_split('/\R/', $text) as $line) {
        $code = preg_replace('/--.*$/', '', preg_replace('/"(?:[^"\\\\]|\\\\.)*"/', '""', $line));
        if ($depth === 0 && preg_match('/^data\["([^"]+)"\]\s*=\s*\{/', $line, $m)) { $table = $m[1]; $faction = 0; $itemsDepth = -1; $skipTable = false; }
        if ($table !== '' && $depth === 1) {
            if ($itemsDepth < 0 && preg_match('/^\s*items\s*=\s*\{/', $code)) $itemsDepth = 2;
            if (preg_match('/^\s*FactionID\s*=\s*(\d+)/', $code, $m)) $faction = (int)$m[1];
            if (preg_match('/^\s*TableType\s*=\s*SET_ITTYPE/', $code)) $skipTable = true;
        }
        $opens = substr_count($code, '{'); $closes = substr_count($code, '}');
        if ($itemsDepth > 0 && $depth === $itemsDepth && $opens > $closes) {
            $later = preg_match('/GameVersion_GE\(\s*AtlasLoot\.(\w+)/', $code, $v) && $v[1] !== 'CLASSIC_VERSION_NUM';
            $list = ['name' => '', 'skip' => $later];
        } elseif ($list !== null && $depth === $itemsDepth + 1) {
            if ($list['name'] === '' && preg_match('/^\s*name\s*=\s*[^"]*"([^"]+)"/', $line, $m)) $list['name'] = $m[1];
            if (preg_match('/^\s*TableType\s*=\s*SET_ITTYPE/', $code)) $list['skip'] = true;
            if (preg_match('/^\s*\[(\w+)\]\s*=\s*\{/', $code, $m)) {
                $side = in_array($m[1], ['ALLIANCE_DIFF', 'HORDE_DIFF'], true) ? strtolower(substr($m[1], 0, -5)) : '';
                $standing = 0; $listFaction = $faction;
            }
        } elseif ($list !== null && !$list['skip'] && !$skipTable && $depth === $itemsDepth + 2 && preg_match('/^\s*\{\s*\d+\s*,/', $code)) {
            if (preg_match('/^\s*\{\s*\d+\s*,\s*"f(\d+)rep(\d+)"/', $line, $m)) { $listFaction = (int)$m[1]; $standing = (int)$m[2]; }
            $price = preg_match('/\[PRICE_EXTRA_ITTYPE\]\s*=\s*"([^"]+)"/', $line, $p) ? $p[1] : '';
            $ids = preg_match('/^\s*\{\s*\d+\s*,\s*(\d+)\s*[,}]/', $code, $m) ? [(int)$m[1]] : [];
            if (preg_match_all('/\[ATLASLOOT_IT_(?:HORDE|ALLIANCE)\]\s*=\s*(\d+)/', $code, $f)) $ids = array_merge($ids, array_map('intval', $f[1]));
            $name = $list['name'] !== '' ? $list['name'] : '?';
            foreach (array_unique($ids) as $id) if ($id > 0) {
                $out[] = [$id, implode('/', array_filter([$module, $table, $name, $side])), $module, $table, $name, $side, $price, $listFaction, $standing];
            }
        }
        $depth += $opens - $closes;
        if ($list !== null && $depth <= $itemsDepth) $list = null;
        if ($depth <= 0) { $depth = 0; $table = ''; $itemsDepth = -1; }
    }
    return $out;
}

/**
 * The boss blocks of a data file: each entry of an instance's `items = { ... }` list, with its name, its npcID (one or
 * a list) and every item row `{ slot, item, ... }` of its difficulty lists (`[NORMAL_DIFF] = { ... }`), each with the
 * heading row above it. Left out: set tables (TableType = SET_ITTYPE: set numbers, not items), rows with a price
 * (PRICE_EXTRA_ITTYPE: vendor stock), blocks wrapped in GameVersion_GE(<later version>) and instances or blocks marked
 * IgnoreAsSource. Faction rows (`[ATLASLOOT_IT_HORDE] = x, [ATLASLOOT_IT_ALLIANCE] = y`) give both items.
 */
function atlasloot_bosses(string $text): array
{
    $bosses = [];
    $instance = ''; $depth = 0; $itemsDepth = -1; $boss = null; $inDiff = false; $ignored = false; $heading = '';
    foreach (preg_split('/\R/', $text) as $line) {
        $code = preg_replace('/--.*$/', '', preg_replace('/"(?:[^"\\\\]|\\\\.)*"/', '""', $line));   // strings and comments out, for the braces
        if ($depth === 0 && preg_match('/^data\["([^"]+)"\]\s*=\s*\{/', $line, $m)) { $instance = $m[1]; $itemsDepth = -1; $ignored = false; }
        if ($instance !== '' && $depth === 1) {
            if ($itemsDepth < 0 && preg_match('/^\s*items\s*=\s*\{/', $code)) $itemsDepth = 2;
            if (preg_match('/^\s*IgnoreAsSource\s*=\s*true/', $code)) $ignored = true;
        }
        $opens = substr_count($code, '{'); $closes = substr_count($code, '}');
        if ($itemsDepth > 0 && $depth === $itemsDepth && $opens > $closes) {
            $later = preg_match('/GameVersion_GE\(\s*AtlasLoot\.(\w+)/', $code, $v) && $v[1] !== 'CLASSIC_VERSION_NUM';
            $boss = ['name' => '', 'npcs' => [], 'items' => [], 'skip' => $later]; $inDiff = false;
        } elseif ($boss !== null && $depth === $itemsDepth + 1) {
            if ($boss['name'] === '' && preg_match('/^\s*name\s*=\s*(?:AL\[)?"([^"]+)"\]?\s*,/', $line, $m)) $boss['name'] = $m[1];
            if (preg_match('/^\s*npcID\s*=\s*(\{[^}]*\}|\d+)/', $code, $m)) $boss['npcs'] = array_map('intval', preg_match_all('/\d+/', $m[1], $n) ? $n[0] : []);
            if (preg_match('/^\s*(TableType\s*=\s*SET_ITTYPE|IgnoreAsSource\s*=\s*true)/', $code)) $boss['skip'] = true;
            $inDiff = (bool)preg_match('/^\s*\[\w+\]\s*=\s*\{/', $code);
            $heading = '';
        } elseif ($boss !== null && $inDiff && $depth === $itemsDepth + 2 && preg_match('/^\s*\{\s*\d+\s*,/', $code)) {
            if (preg_match('/^\s*\{\s*\d+\s*,\s*""\s*,\s*nil\s*,\s*(?:AL\[)?"/', $code) && preg_match('/AL\["([^"]+)"\]|,\s*nil\s*,\s*"([^"]+)"/', $line, $h)) {
                $heading = $h[1] !== '' ? $h[1] : ($h[2] ?? '');   // { 16, "INV_Box_01", nil, AL["Forever"], nil }
            } elseif (!str_contains($code, 'PRICE_EXTRA_ITTYPE')) {
                $ids = preg_match('/^\s*\{\s*\d+\s*,\s*(\d+)\s*[,}]/', $code, $m) ? [(int)$m[1]] : [];
                if (preg_match_all('/\[ATLASLOOT_IT_(?:HORDE|ALLIANCE)\]\s*=\s*(\d+)/', $code, $f)) $ids = array_merge($ids, array_map('intval', $f[1]));
                foreach ($ids as $id) if ($id > 0 && !isset($boss['items'][$id])) $boss['items'][$id] = $heading;
            }
        }
        $depth += $opens - $closes;
        if ($boss !== null && $depth <= $itemsDepth) {
            if (!$boss['skip'] && !$ignored && $boss['items']) $bosses[] = [$instance, $boss['name'], $boss['npcs'], $boss['items']];
            $boss = null;
        }
        if ($depth <= 0) { $depth = 0; $instance = ''; $itemsDepth = -1; }
    }
    return $bosses;
}

/** Lower-case key for names (MySQL compares names without case). */
function atlasloot_key(string $name): string { return mb_strtolower(trim($name)); }

/**
 * Who drops what: [[kind, creature or chest, [item => heading], several]] plus what was left out.
 *
 * A block with one npcID is that creature. A block naming several creatures (the Guzzler, the Twin Emperors) splits at
 * its heading rows (see below). A block without an npcID (Forever's new dungeons, chests such as Doan's Strongbox) is
 * found by name among spawned creatures, else spawned objects, on the map where most of the instance's bosses are
 * spawned (two or more agreeing): one candidate only; no such map or several candidates: left out.
 */
function atlasloot_sources(array $tables): array
{
    $out = []; $left = []; $kept = ['al_reward' => [], 'al_trash' => [], 'al_named' => []];
    $leave = function (string $why, int $n) use (&$left) { $left[$why] = ($left[$why] ?? 0) + $n; };
    $mapOf = [];
    // a list no creature takes is kept as it is (atlasloot_kind), and counted as left out of the card
    $keep = function (string $instance, string $name, array $items) use (&$kept, &$mapOf, $leave) {
        $kind = atlasloot_kind($name);
        $leave(['al_reward' => 'atlasloot_quest_reward', 'al_trash' => 'atlasloot_trash', 'al_named' => 'atlasloot_no_creature'][$kind], count($items));
        foreach (array_keys($items) as $item) $kept[$kind][] = match ($kind) {
            'al_reward' => [(int)$item, 0, $name, $instance],
            'al_trash' => [(int)$item, $instance, (int)($mapOf[$instance] ?? 0)],
            default => [(int)$item, "$instance / $name", $instance, $name],
        };
    };
    $names = $ids = [];
    foreach ($tables['bosses'] as [, $name, $npcs]) {
        if (!$npcs && $name !== '') $names[$name] = true;
        foreach ($npcs as $npc) $ids[$npc] = true;
    }
    // spawn maps: [kind][key] => [entry => [map => true]], by name (lower case) and by entry
    $byName = ['npc' => [], 'go' => []]; $mapsOf = []; $nameOf = []; $vendor = [];
    foreach (array_chunk(array_keys($names), 500) as $chunk) {
        $marks = implode(',', array_fill(0, count($chunk), '?'));
        foreach (rows("SELECT DISTINCT ct.entry, ct.name, ct.npcflag, c.map FROM creature_template ct JOIN creature c ON c.id = ct.entry WHERE ct.name IN ($marks)", $chunk, 'world') as $r) {
            $byName['npc'][atlasloot_key($r['name'])][(int)$r['entry']][(int)$r['map']] = true;
            if ((int)$r['npcflag'] & 128) $vendor[(int)$r['entry']] = true;
        }
        foreach (rows("SELECT DISTINCT gt.entry, gt.name, g.map FROM gameobject_template gt JOIN gameobject g ON g.id = gt.entry WHERE gt.name IN ($marks)", $chunk, 'world') as $r) $byName['go'][atlasloot_key($r['name'])][(int)$r['entry']][(int)$r['map']] = true;
    }
    foreach (array_chunk(array_keys($ids), 1000) as $chunk) {
        foreach (rows('SELECT DISTINCT ct.entry, ct.name, ct.npcflag, c.map FROM creature_template ct LEFT JOIN creature c ON c.id = ct.entry WHERE ct.entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) {
            $nameOf[(int)$r['entry']] = atlasloot_key($r['name']);
            if ((int)$r['npcflag'] & 128) $vendor[(int)$r['entry']] = true;
            if ($r['map'] !== null) $mapsOf[(int)$r['entry']][(int)$r['map']] = true;
        }
    }
    // each instance's map: the one most of its bosses (by npcID, or every name candidate) are spawned on
    $votes = [];
    foreach ($tables['bosses'] as [$instance, $name, $npcs]) {
        $maps = [];
        foreach ($npcs as $npc) $maps += $mapsOf[$npc] ?? [];
        if (!$npcs) foreach (['npc', 'go'] as $kind) foreach ($byName[$kind][atlasloot_key($name)] ?? [] as $entryMaps) $maps += $entryMaps;
        foreach (array_keys($maps) as $map) $votes[$instance][$map][$name] = true;
    }
    foreach ($votes as $instance => $maps) {
        uasort($maps, fn($a, $b) => count($b) <=> count($a));
        $best = array_key_first($maps);
        if (count($maps[$best]) >= 2) $mapOf[$instance] = $best;
    }
    // what the loot of each creature of a several-creature block already gives (the last way to tell them apart)
    $several = [];
    foreach ($tables['bosses'] as [, , $npcs]) if (count($npcs) > 1) foreach ($npcs as $npc) $several[$npc] = true;
    $lootOf = [];
    if ($several) {
        $lootIds = [];
        foreach (array_chunk(array_keys($several), 1000) as $chunk) {
            foreach (rows('SELECT Entry, LootID FROM creature_template_difficulty WHERE DifficultyID = 0 AND Entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) $lootIds[(int)$r['Entry']] = (int)$r['LootID'] ?: (int)$r['Entry'];
        }
        $gives = collector_loot_items('creature_loot_template', array_values($lootIds));
        foreach ($lootIds as $npc => $loot) $lootOf[$npc] = $gives[$loot] ?? [];
    }
    foreach ($tables['bosses'] as [$instance, $name, $npcs, $items]) {
        if (count($npcs) === 1) { $out[] = ['npc', $npcs[0], $items, false]; continue; }
        if ($npcs) {
            // under a creature's heading: that creature (a vendor's heading is its stock: left out); else every
            // creature when the block's name lists them all; else the one named like the block (Balnazzar); else, in
            // a block without headings only, those whose loot already gives another of its items (the Bug Trio). A
            // block with headings that name no creature (the Dark Coffer's "Secret Safe") is not guessed at.
            $byHeading = []; foreach ($npcs as $npc) if (isset($nameOf[$npc])) $byHeading[$nameOf[$npc]][] = $npc;
            $named = array_map('atlasloot_key', preg_split('#\s*[/&,]\s*#', $name));
            $shared = count($npcs) === count(array_filter($npcs, fn($npc) => in_array($nameOf[$npc] ?? '', $named, true)));
            $unheaded = $byHeading[atlasloot_key($name)] ?? null;
            if (!$shared && !$unheaded && !array_filter($items, fn($h) => $h !== '')) {
                $unheaded = array_values(array_filter($npcs, fn($npc) => array_intersect_key($lootOf[$npc] ?? [], $items) !== []));
            }
            $parts = []; $unsure = [];
            foreach ($items as $item => $heading) {
                $to = $byHeading[atlasloot_key($heading)] ?? null;
                if ($to !== null && array_filter($to, fn($npc) => isset($vendor[$npc]))) { $leave('atlasloot_vendor', 1); continue; }
                $to ??= $shared ? $npcs : $unheaded;
                if (!$to) { $leave('atlasloot_several_creatures', 1); $unsure[$item] = $heading; continue; }
                foreach ($to as $npc) $parts[$npc][$item] = $heading;
            }
            if ($unsure) { foreach (array_keys($unsure) as $item) $kept['al_named'][] = [(int)$item, "$instance / $name", $instance, $name]; $unsure = []; }
            foreach ($parts as $npc => $list) $out[] = ['npc', $npc, $list, true];
            continue;
        }
        $found = null;
        // a name alone is trusted only on the map the instance's other bosses share: Forever's bosses have plain names
        // (Arcane Anomaly, Gill, The Baron) that unrelated creatures elsewhere carry too
        if (isset($mapOf[$instance])) foreach (['npc', 'go'] as $kind) {
            $candidates = array_filter($byName[$kind][atlasloot_key($name)] ?? [], fn($maps) => isset($maps[$mapOf[$instance]]));
            if (count($candidates) === 1) { $found = [$kind, (int)array_key_first($candidates)]; break; }
            if ($candidates) break;   // several: the name is not enough
        }
        if (!$found) { $keep($instance, $name, $items); continue; }
        $out[] = [$found[0], $found[1], $items, false];
    }
    // the quests of the reward lists, by title: one quest of that title, or one of the side the list names
    $titles = [];
    foreach ($kept['al_reward'] as $row) if ($row[1] === 0 && $row[2] !== '') $titles[atlasloot_quest_title($row[2])[0]] = true;
    $quests = [];
    foreach (array_chunk(array_keys($titles), 500) as $chunk) {
        $marks = implode(',', array_fill(0, count($chunk), '?'));
        foreach (rows("SELECT ID, LogTitle, AllowableRaces FROM quest_template WHERE LogTitle IN ($marks)", $chunk, 'world') as $r) $quests[atlasloot_key($r['LogTitle'])][(int)$r['ID']] = (int)$r['AllowableRaces'];
    }
    foreach ($kept['al_reward'] as &$row) {
        [$title, $side] = atlasloot_quest_title($row[2]);
        // the quest's number once found, else the list's name: one fact per list either way
        $row[1] = atlasloot_pick_quest($quests[atlasloot_key($title)] ?? [], $side) ?: $row[2];
    }
    unset($row);
    return [$out, $left, $kept];
}

/**
 * The quest a reward list names: [title, 'horde'|'alliance'|''], from "Blood Red Bandanas (Horde Quest)" or "Quest
 * Rewards (Eye of Mugg)". A list that names no quest ("Alliance Only Quest Rewards") gives ''.
 */
function atlasloot_quest_title(string $name): array
{
    $side = preg_match('/\bhorde\b/i', $name) ? 'horde' : (preg_match('/\balliance\b/i', $name) ? 'alliance' : '');
    if (preg_match('/^\s*quest\s+rewards?\s*\((.+)\)\s*$/i', $name, $m)) return [trim($m[1]), $side];
    if (preg_match('/^(.+?)\s*\((?:horde|alliance)?\s*quest\)\s*$/i', $name, $m)) return [trim($m[1]), $side];
    return ['', $side];
}

/** Races of each side (AllowableRaces bits): orc, undead, tauren, troll / human, dwarf, night elf, gnome. */
const ATLASLOOT_SIDES = ['horde' => 2 | 16 | 32 | 128, 'alliance' => 1 | 4 | 8 | 64];

/** One quest out of [id => AllowableRaces] with that title: the only one, else the only one open to $side; else 0. */
function atlasloot_pick_quest(array $candidates, string $side): int
{
    if (count($candidates) === 1) return (int)array_key_first($candidates);
    if ($side === '' || !$candidates) return 0;
    $mask = ATLASLOOT_SIDES[$side];
    $open = array_filter($candidates, fn($races) => $races === 0 || $races === -1 || ($races & $mask));
    $only = array_filter($open, fn($races) => $races > 0 && !($races & ATLASLOOT_SIDES[$side === 'horde' ? 'alliance' : 'horde']));
    if (count($only) === 1) return (int)array_key_first($only);
    return count($open) === 1 ? (int)array_key_first($open) : 0;
}

/**
 * What a list that went to no creature is: a quest's rewards, the instance's trash, or a list under a name (a boss
 * this server has not spawned, a chest, a shared list such as "All bosses" or "Class books"). Kept as AtlasLoot said it,
 * as rows: al_reward [item, quest (its list name while no quest is found), list name, instance], al_trash [item, instance, map], al_named
 * [item, "instance / list name", instance, list name].
 */
function atlasloot_kind(string $name): string
{
    if (preg_match('/\bquests?\b/i', $name)) return 'al_reward';
    if (preg_match('/\btrash\b/i', $name)) return 'al_trash';
    return 'al_named';
}

/**
 * Its drops as evidence: [kind, creature or chest, item, chance, guessed]. The chance: AtlasLoot's droprate.lua (not
 * for a block of several creatures: its numbers sit under the first one), else the best one a live Forever recording
 * measured for the same creature (or chest) and item ($measured), else (`[atlasloot] guess`, on by default) an even
 * share of one drop over the list (counting at least three items), marked guessed.
 */
function atlasloot_evidence(array $tables, array $measured = []): array
{
    [$sources, $left, $kept] = atlasloot_sources($tables);
    $ev = ['drop' => [], 'left' => $left] + $kept;
    // what AtlasLoot holds besides the drops it ties to a creature, kept as it said it (atlasloot_lists)
    $ev['al_list'] = $tables['lists'] ?? [];
    $ev['al_rate'] = [];
    foreach ($tables['rates'] ?? [] as $npc => $items) foreach ($items as $item => $chance) $ev['al_rate'][] = [(int)$npc, (int)$item, (float)$chance];
    $guess = filter_var(config('atlasloot', 'guess', '1'), FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE) ?? true;
    foreach ($sources as [$kind, $id, $items, $several]) {
        foreach (array_keys($items) as $item) {
            $chance = ($kind === 'npc' && !$several ? ($tables['rates'][$id][$item] ?? null) : null) ?? $measured["$kind:$id:$item"] ?? 0.0;
            $guessed = $chance <= 0 && $guess;
            if ($guessed) $chance = 100 / max(ATLASLOOT_MIN_SHARE, count($items));
            $ev['drop'][] = [$kind, $id, $item, $chance, $guessed];   // source_tables() reads the first four
        }
    }
    return $ev;
}

/** Best chance per kind:id:item from the live Forever recordings at hand (EG Link, ForeverDB.net, Icy Veins' cache). */
function atlasloot_measured(array $gaps, array &$left): array
{
    $best = [];
    $sources = [icyveins_cached_items($gaps['items'])];
    foreach (['eglink', 'foreverdb'] as $source) {
        $w = ($source . '_evidence')();
        if (!empty($w['ev'])) $sources[] = $w['ev'];
        else $left["witness_{$source}_unreachable"] = 1;
    }
    foreach ($sources as $w) foreach ($w['drop'] ?? [] as [$kind, $id, $item, $chance]) {
        if ($chance > 0) $best["$kind:$id:$item"] = max($best["$kind:$id:$item"] ?? 0, (float)$chance);
    }
    return $best;
}

function atlasloot_import(bool $ifNew = false): array
{
    if ($e = source_check()) return $e;
    // the gaps are rewritten while an analysis runs: the container's check waits for the next round
    if ($ifNew && analysis_status()['running']) return ['ok' => true, 'retry' => true, 'id' => 0, 'counts' => [], 'ignored' => [], 'message' => t('An analysis is running: AtlasLoot is checked next time.', 'Une analyse est en cours : AtlasLoot sera vérifié la prochaine fois.')];
    $file = atlasloot_latest();
    if (!$file) return ['ok' => false, 'message' => t('Could not reach AtlasLoot on CurseForge.', 'AtlasLoot est injoignable sur CurseForge.')];
    $mark = atlasloot_dir() . '/imported';
    // "ask every source again" was pressed since this version was read: read it again, the gaps and the other
    // sources' measures it is weighed with have moved
    if ($ifNew && trim((string)@file_get_contents($mark)) === (string)$file['id'] && (int)@filemtime($mark) >= source_refresh_epoch()) {
        return ['ok' => true, 'id' => 0, 'counts' => [], 'ignored' => [], 'message' => sprintf(t('AtlasLoot %s already imported.', 'AtlasLoot %s déjà importé.'), $file['version'])];
    }
    [$path, $error] = atlasloot_fetch($file);
    if ($path === '') return ['ok' => false, 'message' => $error];
    try { $tables = atlasloot_tables($path); }
    catch (RuntimeException $x) { return ['ok' => false, 'message' => 'AtlasLoot ' . $file['version'] . ': ' . $x->getMessage()]; }
    $gaps = source_gaps();
    $witnessLeft = [];
    $ev = atlasloot_evidence($tables, atlasloot_measured($gaps, $witnessLeft));
    $ev['left'] += $witnessLeft;
    snapshot_try('atlasloot', (string)$file['version'], $ev);
    $out = atlasloot_card($ev, (string)$file['version'], (string)$file['id'], $gaps);
    if (!empty($out['ok']) || empty($out['counts'])) file_put_contents($mark, (string)$file['id']);
    return $out;
}

/** The card of AtlasLoot's evidence. Also made from the database (snapshot_card). */
function atlasloot_card(array $ev, string $version, string $file, array $gaps): array
{
    $label = 'AtlasLoot ' . $version;
    [$cards, $left] = source_tables($ev, $label, $gaps);
    [$changes, $rewardLeft] = atlasloot_reward_changes($ev['al_reward'] ?? []);
    foreach ($rewardLeft as $why => $n) $left[$why] = ($left[$why] ?? 0) + $n;
    // gap items whose chance is an even share (an upper bound: drops the server already has are left out later)
    $guessed = count(array_filter($ev['drop'], fn($d) => !empty($d[4]) && isset($gaps['items'][$d[2]])));
    $name = $label . ($guessed && $cards ? ' (' . sprintf(t('up to %d chances are an even share', 'jusqu’à %d chances en part égale'), $guessed) . ')' : '');
    return source_card('atlasloot', $name, 'atlasloot@' . $file, $cards, array_filter($left), $changes);
}

/**
 * Rewards for the quests of AtlasLoot's reward lists that give no item at all on this server: Forge "set" operations
 * on quest_template, each naming the 0 it replaces. A quest that already rewards anything is left as it is (Wowhead
 * and Questie, more trusted, fill rewards through the quest refresh). Several items are a choice, one item is given.
 */
function atlasloot_reward_changes(array $rewards): array
{
    $lists = [];
    foreach ($rewards as $row) if (is_int($row[1] ?? null) && $row[1] > 0) $lists[$row[1]][(int)$row[0]] = true;
    if (!$lists || !table_exists('quest_template', 'world')) return [[], []];
    $columns = [];
    for ($i = 1; $i <= 6; $i++) $columns[] = "RewardChoiceItemID$i";
    for ($i = 1; $i <= 4; $i++) $columns[] = "RewardItem$i";
    $have = [];
    foreach (array_chunk(array_keys($lists), 500) as $chunk) {
        foreach (rows('SELECT ID, ' . implode(',', $columns) . ' FROM quest_template WHERE ID IN (' . implode(',', $chunk) . ')', [], 'world') as $r) {
            $have[(int)$r['ID']] = array_sum(array_map(fn($c) => (int)$r[$c] > 0 ? 1 : 0, $columns));
        }
    }
    [$sets, $left] = atlasloot_reward_sets($lists, $have);
    $changes = [];
    foreach ($sets as $column => $list) $changes[] = ['db' => 'world', 'table' => 'quest_template', 'columns' => ['ID', $column], 'match' => ['ID'], 'set' => $column, 'rows' => $list];
    return [$changes, $left];
}

/**
 * The columns to set, from [quest => [item => true]] and [quest => how many reward items it has now]: [column => [[quest,
 * value], …]] and what was left out. Up to six items are a choice (RewardChoiceItemID/Quantity); one item is
 * RewardItem1/RewardAmount1; a quest the server lacks, or one that already rewards something, gets nothing.
 */
function atlasloot_reward_sets(array $lists, array $have): array
{
    $sets = []; $left = [];
    foreach ($lists as $quest => $items) {
        if (!isset($have[$quest])) { $left['atlasloot_quest_not_on_server'] = ($left['atlasloot_quest_not_on_server'] ?? 0) + count($items); continue; }
        if ($have[$quest] > 0) { $left['atlasloot_quest_has_rewards'] = ($left['atlasloot_quest_has_rewards'] ?? 0) + count($items); continue; }
        $items = array_slice(array_keys($items), 0, 6);
        if (count($items) === 1) { $sets['RewardItem1'][] = [$quest, $items[0]]; $sets['RewardAmount1'][] = [$quest, 1]; continue; }
        foreach ($items as $i => $item) { $sets['RewardChoiceItemID' . ($i + 1)][] = [$quest, $item]; $sets['RewardChoiceItemQuantity' . ($i + 1)][] = [$quest, 1]; }
    }
    return [$sets, $left];
}

/** Drops of the last downloaded AtlasLoot (no download), for NorgannonDB's second-source check. */
function atlasloot_cached_drops(): array
{
    $zips = glob(atlasloot_dir() . '/*.zip') ?: [];
    if (!$zips) return [];
    usort($zips, fn($a, $b) => (int)basename($b, '.zip') <=> (int)basename($a, '.zip'));
    try { [$sources] = atlasloot_sources(atlasloot_tables($zips[0])); } catch (RuntimeException $x) { return []; }
    $drops = [];
    foreach ($sources as [$kind, $id, $items]) foreach (array_keys($items) as $item) $drops[] = [$kind, $id, $item, 0];
    return ['drop' => $drops];
}
