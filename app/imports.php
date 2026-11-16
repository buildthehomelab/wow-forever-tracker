<?php
// Imports: world data in WowPacketParser's SQL format (or any SQL of INSERT statements),
// merged into the server with the Forge's engine. Nothing is ever deleted or overwritten: only the rows the server
// lacks are added, spawns get new guids, spawns that already stand at the same place are left out, and every
// operation keeps an exact rollback.
//
//   data/imports/*.sql            files to import (drop them there, or upload them from the Forge)
//   data/imports/parsed/<id>.json what an import kept: {tables: {name: {db, columns, rows}}}
//   ft_imports, ft_import_items     the imports, and which items each one makes obtainable (loot, vendor, quest reward)
require_once FT_APP . '/forge.php';

const IMPORT_SPAWN_TABLES = ['creature' => 'npc', 'gameobject' => 'go'];
/** How near (yards, same map) a spawn of the same creature or object is taken for the one the server already has. */
const IMPORT_SAME_SPAWN = 3.0;
/** The same for a holiday's spawn (one the import links to a game event), which is matched farther: the realm's holiday
 *  spawns come from another database, which places the same NPC a few yards off (a second Silas Darkmoon 18 yards from
 *  the first, the Elders of the Lunar Festival 4 to 25), and an object a step aside. Only the server's spawns are
 *  matched this far: the import's own stay apart at IMPORT_SAME_SPAWN, so a crowd of the same NPC keeps its members. */
const IMPORT_SAME_HOLIDAY_SPAWN = ['creature' => 30.0, 'gameobject' => 10.0];
// tables keyed by a spawn guid: [table => [guid columns]]
const IMPORT_GUID_TABLES = ['creature_addon' => ['guid'], 'gameobject_addon' => ['guid'], 'creature_formations' => ['leaderGUID', 'memberGUID'],
    'game_event_creature' => ['guid'], 'game_event_gameobject' => ['guid'], 'linked_respawn' => ['guid', 'linkedGuid'], 'spawn_group' => ['spawnId'],
    'pool_members' => ['spawnId'], 'creature_movement_override' => ['SpawnId']];
// the spawn kind behind the guid columns of those tables
/** The loot tables a creature's template points to, and the creature_template_difficulty column that does it. */
const IMPORT_LOOT_COLUMN = ['creature_loot_template' => 'LootID', 'skinning_loot_template' => 'SkinLootID', 'pickpocketing_loot_template' => 'PickPocketLootID'];
const IMPORT_GUID_KIND = ['creature_addon' => 'npc', 'gameobject_addon' => 'go', 'creature_formations' => 'npc', 'game_event_creature' => 'npc',
    'game_event_gameobject' => 'go', 'creature_movement_override' => 'npc'];

function import_dir(): string { return FT_ROOT . '/data/imports'; }

// ------------------------------------------------------------------ who wrote a row
/**
 * ft_row_origin: the source that last wrote a server row through an import (inserted it, or gave it a new value), so
 * a later import knows whether its word may replace it ([sources] trust). A row it does not list is the core's own,
 * unless its Comment names a source (loot rows). Kept by row key: "guid" for a spawn, the primary key otherwise.
 */
function import_origin_schema(): void
{
    db()->query("CREATE TABLE IF NOT EXISTS ft_row_origin (db VARCHAR(16) NOT NULL, tbl VARCHAR(64) NOT NULL, row_key VARCHAR(190) NOT NULL,
        source VARCHAR(32) NOT NULL, import_id INT NOT NULL, written_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (db, tbl, row_key)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
}

function import_origin_key(array $values): string { return mb_substr(implode('|', array_map(fn($v) => (string)$v, $values)), 0, 190); }

/** [row key => source] of the rows of a table an import wrote, among $keys. */
function import_origins(string $database, string $table, array $keys): array
{
    import_origin_schema();
    $found = [];
    foreach (array_chunk(array_values(array_unique($keys)), 500) as $chunk) {
        $marks = implode(',', array_fill(0, count($chunk), '?'));
        foreach (rows("SELECT row_key, source FROM ft_row_origin WHERE db = ? AND tbl = ? AND row_key IN ($marks)", array_merge([$database, $table], $chunk)) as $r) $found[$r['row_key']] = $r['source'];
    }
    return $found;
}

/** Records who wrote the rows an apply wrote: $origins [[db, table, row key, source], …]. */
function import_origin_record(array $origins, int $importId): void
{
    if (!$origins) return;
    import_origin_schema();
    foreach (array_chunk($origins, 500) as $chunk) {
        $values = []; $params = [];
        foreach ($chunk as [$database, $table, $key, $source]) { $values[] = '(?, ?, ?, ?, ?)'; array_push($params, $database, $table, $key, $source, $importId); }
        rows('REPLACE INTO ft_row_origin (db, tbl, row_key, source, import_id) VALUES ' . implode(',', $values), $params);
    }
}

/** The source of an import card: the one its file names ("icyveins@…", "classicdb-holiday-…@…", Wowhead's quest
 *  enders), 'scribe' for ForeverScribe's notes, 'sniff' for a file in WowPacketParser's format. */
function import_source(int $id): string
{
    import_schema();
    $card = rows('SELECT name, file FROM ft_imports WHERE id = ?', [$id])[0] ?? ['name' => '', 'file' => ''];
    $file = (string)$card['file'];
    if ($file === 'wowhead-quest-enders') return 'wowhead';
    if (preg_match('/^([a-z][a-z0-9-]*)@/', $file, $m)) {
        foreach (array_keys(SOURCE_MARKS) as $source) if ($m[1] === $source || str_starts_with($m[1], $source . '-')) return $source;
        return $m[1];
    }
    if (str_starts_with((string)$card['name'], 'ForeverScribe') || preg_match('/\.lua$/i', $file)) return 'scribe';
    return 'sniff';
}

function import_schema(): void
{
    db()->query("CREATE TABLE IF NOT EXISTS ft_imports (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(190) NOT NULL, file VARCHAR(255) NOT NULL,
        imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, admin VARCHAR(190) NOT NULL DEFAULT '', counts JSON, ignored JSON) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
    db()->query("CREATE TABLE IF NOT EXISTS ft_import_items (item INT NOT NULL, import_id INT NOT NULL, kind VARCHAR(8) NOT NULL, source INT NOT NULL,
        PRIMARY KEY (item, import_id, kind, source), KEY ix_import (import_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
}

// ------------------------------------------------------------------ parsing
/** Statements of an SQL file, one at a time (quotes, backticks and comments respected). */
function import_statements(string $path): Generator
{
    $handle = fopen($path, 'rb');
    if (!$handle) return;
    $statement = ''; $quote = ''; $comment = ''; $star = false;
    while (!feof($handle)) {
        $chunk = (string)fread($handle, 1 << 20);
        $length = strlen($chunk);
        for ($i = 0; $i < $length; $i++) {
            $c = $chunk[$i];
            if ($comment === '-') { if ($c === "\n") { $comment = ''; $statement .= "\n"; } continue; }
            if ($comment === '*') { if ($c === '/' && $star) { $comment = ''; $statement .= ' '; } $star = $c === '*'; continue; }
            if ($quote !== '') {
                // copy everything up to the next quote or backslash at once
                $span = strcspn($chunk, $quote . '\\', $i);
                if ($span > 0) { $statement .= substr($chunk, $i, $span); $i += $span - 1; continue; }
                $statement .= $c;
                if ($c === '\\') { if ($i + 1 < $length) { $statement .= $chunk[++$i]; } else { $statement .= (string)fread($handle, 1); } }
                elseif ($c === $quote) $quote = '';
                continue;
            }
            if ($c === "'" || $c === '"' || $c === '`') { $quote = $c; $statement .= $c; continue; }
            if ($c === '-' && ($chunk[$i + 1] ?? '') === '-') { $comment = '-'; $i++; continue; }
            if ($c === '#') { $comment = '-'; continue; }
            if ($c === '/' && ($chunk[$i + 1] ?? '') === '*') { $comment = '*'; $star = false; $i++; continue; }
            if ($c === ';') { if (trim($statement) !== '') yield trim($statement); $statement = ''; continue; }
            $statement .= $c;
        }
    }
    fclose($handle);
    if (trim($statement) !== '') yield trim($statement);
}

/** [table, columns|null, rows] of an INSERT / REPLACE statement, or null. Values: int, float, string, null, or ['@', NAME, offset]. */
function import_insert(string $sql): ?array
{
    if (!preg_match('/^(?:INSERT(?:\s+IGNORE)?|REPLACE)\s+INTO\s+`?(\w+)`?(?:\.`?(\w+)`?)?\s*(?:\(([^)]*)\))?\s*VALUES\s*/is', $sql, $m)) return null;
    $table = ($m[2] ?? '') !== '' ? $m[2] : $m[1];
    $columns = ($m[3] ?? '') !== '' ? array_map(fn($c) => trim($c, " `\t\r\n"), explode(',', $m[3])) : null;
    $rows = []; $row = []; $i = strlen($m[0]); $n = strlen($sql); $depth = 0;
    while ($i < $n) {
        $c = $sql[$i];
        if ($c === '(') { $depth = 1; $row = []; $i++; continue; }
        if ($c === ')') { if ($depth) { $rows[] = $row; $depth = 0; } $i++; continue; }
        if ($c === ',' || ctype_space($c)) { $i++; continue; }
        if (!$depth) { $i++; continue; }
        if ($c === "'" || $c === '"') {
            $value = ''; $i++;
            while ($i < $n) {
                $ch = $sql[$i];
                if ($ch === '\\' && $i + 1 < $n) {
                    $next = $sql[$i + 1];
                    $value .= ['n' => "\n", 'r' => "\r", 't' => "\t", '0' => "\0", 'Z' => "\x1a"][$next] ?? $next;
                    $i += 2; continue;
                }
                if ($ch === $c) { if (($sql[$i + 1] ?? '') === $c) { $value .= $c; $i += 2; continue; } $i++; break; }
                $value .= $ch; $i++;
            }
            $row[] = $value;
            continue;
        }
        // a bare token: number, NULL, @VAR, @VAR+N
        $span = strcspn($sql, ",)", $i);
        $token = trim(substr($sql, $i, $span));
        $i += $span;
        if (strcasecmp($token, 'NULL') === 0) $row[] = null;
        elseif (preg_match('/^@(\w+)\s*([+-]\s*\d+)?$/', $token, $v)) $row[] = ['@', strtoupper($v[1]), (int)str_replace(' ', '', $v[2] ?? '0')];
        elseif (preg_match('/^-?\d+$/', $token)) $row[] = (int)$token;
        elseif (is_numeric($token)) $row[] = (float)$token;
        elseif (preg_match('/^0x[0-9a-f]+$/i', $token)) $row[] = hexdec($token);
        else $row[] = $token;  // an expression the importer does not understand: the row is dropped later
    }
    return [$table, $columns, $rows];
}

/** Columns of a table of a database, in order (cached). */
function import_columns(string $database, string $table): array
{
    static $cache = [];
    return $cache[$database . '.' . $table] ??= array_column(rows('SELECT COLUMN_NAME c FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = ? ORDER BY ORDINAL_POSITION', [$table], $database), 'c');
}

/** Imports a file: keeps the INSERT rows of the server's world and hotfixes tables; returns the new import id. */
function import_file(string $path, string $name): array
{
    require_once FT_APP . '/collector.php';
    if (collector_is($path)) return collector_import($path, $name);
    import_schema();
    @set_time_limit(0);
    @ini_set('memory_limit', '1024M');
    $tables = []; $ignored = []; $statements = 0; $bad = 0;
    foreach (import_statements($path) as $sql) {
        $statements++;
        $insert = import_insert($sql);
        if (!$insert) continue;
        [$table, $columns, $rows] = $insert;
        $database = table_exists($table, 'world') ? 'world' : (table_exists($table, 'hotfixes') ? 'hotfixes' : '');
        if ($database === '' || !$rows) { if ($rows) $ignored[$table] = ($ignored[$table] ?? 0) + count($rows); continue; }
        $known = import_columns($database, $table);
        $columns ??= array_slice($known, 0, count($rows[0]));
        // columns this core does not have are dropped (older or newer WowPacketParser)
        $keep = []; foreach ($columns as $i => $column) { $at = array_search(strtolower($column), array_map('strtolower', $known), true); if ($at !== false) $keep[$i] = $known[$at]; }
        $entry = &$tables[$table];
        $entry ??= ['db' => $database, 'columns' => [], 'rows' => []];
        foreach ($rows as $row) {
            if (count($row) !== count($columns)) { $bad++; continue; }
            $record = [];
            foreach ($keep as $i => $column) {
                if (is_string($row[$i]) && $row[$i] !== '' && !preg_match('/^[\s\S]*$/u', $row[$i])) $row[$i] = mb_convert_encoding($row[$i], 'UTF-8', 'Windows-1252');
                $record[$column] = $row[$i];
            }
            $entry['rows'][] = $record;
            foreach (array_keys($record) as $column) $entry['columns'][$column] = true;
        }
        unset($entry);
    }
    foreach ($tables as $table => &$entry) {
        $entry['columns'] = array_keys($entry['columns']);
        // every row on the same columns (a missing one takes the column's default: left out of the INSERT)
        $groups = [];
        foreach ($entry['rows'] as $record) $groups[implode(',', array_keys($record))][] = array_values($record);
        $entry['groups'] = array_map(fn($k, $rows) => ['columns' => explode(',', $k), 'rows' => $rows], array_keys($groups), $groups);
        unset($entry['rows']);
    }
    unset($entry);
    if (!$tables) return ['ok' => false, 'message' => sprintf(t('No INSERT of a world or hotfixes table was found in %s (%d statements read).', 'Aucun INSERT d’une table world ou hotfixes trouvé dans %s (%d requêtes lues).'), basename($path), $statements)];
    $counts = []; foreach ($tables as $table => $entry) $counts[$table] = array_sum(array_map(fn($g) => count($g['rows']), $entry['groups']));
    rows('INSERT INTO ft_imports (name, file, admin, counts, ignored) VALUES (?, ?, ?, ?, ?)', [$name, basename($path), (string)(admin()['name'] ?? 'cli'), json_encode($counts), json_encode($ignored)]);
    $id = (int)db()->insert_id;
    @mkdir(import_dir() . '/parsed', 0775, true);
    file_put_contents(import_dir() . "/parsed/$id.json", json_encode(['tables' => $tables], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE));
    import_index($id, $tables);
    return ['ok' => true, 'id' => $id, 'counts' => $counts, 'ignored' => $ignored, 'bad' => $bad, 'statements' => $statements];
}

/** Which items each import makes obtainable: loot (creature / gameobject / skinning / pick pocketing), vendor, quest reward. */
function import_index(int $id, array $tables): void
{
    $found = [];
    $each = function (string $table, callable $fn) use ($tables) {
        foreach ($tables[$table]['groups'] ?? [] as $group) foreach ($group['rows'] as $row) $fn(array_combine($group['columns'], $row));
    };
    foreach (['creature_loot_template' => 'loot', 'gameobject_loot_template' => 'object', 'skinning_loot_template' => 'skin', 'pickpocketing_loot_template' => 'pick'] as $table => $kind) {
        $each($table, function ($r) use (&$found, $kind) { if ((int)($r['ItemType'] ?? 0) === 0 && is_int($r['Item'] ?? null) && is_int($r['Entry'] ?? null)) $found[] = [$r['Item'], $kind, $r['Entry']]; });
    }
    $each('npc_vendor', function ($r) use (&$found) { if (is_int($r['item'] ?? null) && is_int($r['entry'] ?? null) && (int)($r['type'] ?? 1) === 1) $found[] = [$r['item'], 'vendor', $r['entry']]; });
    $each('quest_template', function ($r) use (&$found) {
        foreach (['RewardItem1', 'RewardItem2', 'RewardItem3', 'RewardItem4', 'RewardChoiceItemID1', 'RewardChoiceItemID2', 'RewardChoiceItemID3', 'RewardChoiceItemID4', 'RewardChoiceItemID5', 'RewardChoiceItemID6'] as $c)
            if (is_int($r[$c] ?? null) && $r[$c] > 0 && is_int($r['ID'] ?? null)) $found[] = [$r[$c], 'quest', $r['ID']];
    });
    foreach (array_chunk($found, 500) as $chunk) {
        db()->query('INSERT IGNORE INTO ft_import_items (item, import_id, kind, source) VALUES ' . implode(',', array_map(fn($f) => '(' . (int)$f[0] . ',' . $id . ",'" . $f[1] . "'," . (int)$f[2] . ')', $chunk)));
    }
}

function import_load(int $id): ?array
{
    $path = import_dir() . "/parsed/$id.json";
    return is_file($path) ? json_decode((string)file_get_contents($path), true) : null;
}

/**
 * The cards a newer card of the same source stands above: [id, …]. $imports: rows of ft_imports (id, file). A source's
 * card is built against the server as it is at that moment, so its newest card says all an earlier one said and is
 * still true. An earlier one is still listed when something was applied from it (the history may name it), but it is
 * not what to apply next. A file imported by hand is nobody's earlier card.
 */
function import_earlier(array $imports): array
{
    $newest = []; $earlier = [];
    usort($imports, fn($a, $b) => (int)$b['id'] <=> (int)$a['id']);
    foreach ($imports as $s) {
        // a source's card is filed as "icyveins@2026-11-14"; Wowhead's as "wowhead-quest-enders"
        if (!preg_match('/^([a-z][a-z0-9-]*)@.+$/', (string)$s['file'], $m) && !preg_match('/^(wowhead-quest-enders)$/', (string)$s['file'], $m)) continue;
        if (isset($newest[$m[1]])) $earlier[] = (int)$s['id']; else $newest[$m[1]] = (int)$s['id'];
    }
    return $earlier;
}

function import_delete(int $id): void
{
    import_schema();
    rows('DELETE FROM ft_import_items WHERE import_id = ?', [$id]);
    rows('DELETE FROM ft_imports WHERE id = ?', [$id]);
    @unlink(import_dir() . "/parsed/$id.json");
}

// ------------------------------------------------------------------ planning
/** The spawns an import links to a holiday (a game event that brings them in), by their guid in the import, with those
 *  events: ['creature' => [guid => [event, ...]], 'gameobject' => [...]]. A negative event (one that hides a spawn) does
 *  not count. */
function import_holiday_spawns(array $tables): array
{
    $holiday = ['creature' => [], 'gameobject' => []];
    foreach (['game_event_creature' => 'creature', 'game_event_gameobject' => 'gameobject'] as $links => $spawnTable) {
        foreach ($tables[$links]['groups'] ?? [] as $group) foreach ($group['rows'] as $row) {
            $r = array_combine($group['columns'], $row);
            if ((int)($r['eventEntry'] ?? 0) > 0 && array_key_exists('guid', $r)) $holiday[$spawnTable][is_array($r['guid']) ? implode('', $r['guid']) : (string)$r['guid']][] = (int)$r['eventEntry'];
        }
    }
    return $holiday;
}

/** Whether a server spawn is there while a holiday's spawn is: it is when it stands all year (no event, or only events
 *  that hide it other than these) or when one of these events brings it in. A spawn of another holiday is not: the
 *  same fireworks over Booty Bay at Midsummer are not New Year's Eve's. $spotEvents: the server spawn's game_event rows
 *  (negative = the event hides it). Moving one ($move) needs it brought in by one of these events: a spawn that stands
 *  all year would become the holiday's. */
function import_spot_shares(array $events, array $spotEvents, bool $move = false): bool
{
    $brings = array_filter($spotEvents, fn($e) => $e > 0);
    if ($brings || $move) return (bool)array_intersect($events, $brings);
    return !array_intersect($events, array_map('abs', $spotEvents));
}

/** Whether a spawn of the import stands already: the server has the same creature / object near it ($server, [x, y,
 *  guid] on the same map: IMPORT_SAME_SPAWN yards; for a holiday's spawn, $events its events, IMPORT_SAME_HOLIDAY_SPAWN
 *  yards and only a server spawn there while it is, import_spot_shares() with $serverEvents [guid => events]), or the
 *  import placed one at the same spot ($added: IMPORT_SAME_SPAWN, so a crowd of the same NPC keeps its members). */
function import_spawn_stands(string $table, ?array $events, float $x, float $y, array $server, array $added, array $serverEvents = []): bool
{
    $reach = $events ? (IMPORT_SAME_HOLIDAY_SPAWN[$table] ?? IMPORT_SAME_SPAWN) : IMPORT_SAME_SPAWN;
    foreach ($server as $spot) {
        if ($events && !import_spot_shares($events, $serverEvents[(int)($spot[2] ?? 0)] ?? [])) continue;
        if (hypot($spot[0] - $x, $spot[1] - $y) < $reach) return true;
    }
    foreach ($added as [$sx, $sy]) if (hypot($sx - $x, $sy - $y) < IMPORT_SAME_SPAWN) return true;
    return false;
}

/**
 * The Forge plan of an import: tables to apply (all when empty), optionally only the rows that make the given items
 * obtainable. Spawns get new guids from the current maximum; a spawn whose creature / object already stands within
 * IMPORT_SAME_SPAWN yards on the same map (IMPORT_SAME_HOLIDAY_SPAWN for a holiday's) is left out, with the rows that
 * depend on its guid.
 */
function import_build(int $id, array $only = [], array $items = []): array
{
    $data = import_load($id);
    if (!$data) return ['plans' => [], 'rows' => 0, 'skipped' => 0, 'duplicates' => 0, 'tables' => [], 'warnings' => [t('This import has no data any more: import the file again.', 'Cet import n’a plus de données : importez le fichier à nouveau.')], 'items' => []];
    $tables = $data['tables'];
    // values a source measured again (source_refresh): each a line of the card named "table.column", ticked like a table
    $changes = array_values(array_filter($data['changes'] ?? [], fn($op) => is_array($op) && isset($op['table'], $op['set']) && (!$only || in_array($op['table'] . '.' . $op['set'], $only, true))));
    if ($only) $tables = array_intersect_key($tables, array_flip($only));
    $warnings = []; $ops = []; $nearby = 0; $unknown = 0; $lootIds = []; $vendors = []; $trainers = [];
    $itemSet = $items ? array_flip(array_map('intval', $items)) : null;
    if ($itemSet !== null) {
        // only what makes these items obtainable: their loot rows, vendor rows and the quests that reward them
        $tables = array_intersect_key($tables, array_flip(['creature_loot_template', 'gameobject_loot_template', 'skinning_loot_template', 'pickpocketing_loot_template', 'npc_vendor', 'quest_template']));
    }
    // the newer word wins: rows the server already has take this card's values, and spawns it places a few yards off
    // are moved there, wherever the row's writer (ft_row_origin, a loot row's Comment, else the core) is not more
    // trusted than this card's source ([sources] trust). Only the whole card does it, and [sources] refresh = 0 stops it.
    require_once FT_APP . '/sources.php';
    $source = import_source($id); $trust = source_trust();
    $refresh = $itemSet === null && filter_var(config('sources', 'refresh', '1'), FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE) !== false;
    $tolerance = (float)(config('sources', 'chance_tolerance', 10) ?: 10);
    $radius = max(0.0, (float)config('imports', 'spawn_move_yards', 40));
    $origins = []; $moved = 0; $updated = 0; $kept = 0;

    // new guids for spawns, and the spawns that already exist close by
    $guidMap = ['npc' => [], 'go' => []]; $next = [];
    $holiday = import_holiday_spawns($tables);
    foreach (IMPORT_SPAWN_TABLES as $table => $kind) {
        if (!isset($tables[$table])) continue;
        $next[$kind] = (int)value("SELECT COALESCE(MAX(guid), 0) FROM `$table`", [], 'world');
        $entries = [];
        foreach ($tables[$table]['groups'] as $group) foreach ($group['rows'] as $row) { $r = array_combine($group['columns'], $row); if (is_int($r['id'] ?? null)) $entries[$r['id']] = true; }
        $existing = []; $added = [];
        foreach (array_chunk(array_keys($entries), 1000) as $chunk) {
            foreach (rows("SELECT guid, id, map, position_x x, position_y y FROM `$table` WHERE id IN (" . implode(',', $chunk) . ')', [], 'world') as $e) $existing[$e['id'] . ':' . $e['map']][] = [(float)$e['x'], (float)$e['y'], (int)$e['guid']];
        }
        // the events of the server's spawns, for a holiday's: only a spawn there while the holiday runs is the same one
        $serverEvents = [];
        if ($holiday[$table]) {
            $links = $table === 'creature' ? 'game_event_creature' : 'game_event_gameobject';
            $guids = []; foreach ($existing as $list) foreach ($list as $e) $guids[] = $e[2];
            foreach (array_chunk($guids, 1000) as $chunk) {
                foreach (rows("SELECT guid, eventEntry FROM `$links` WHERE guid IN (" . implode(',', array_map('intval', $chunk)) . ')', [], 'world') as $l) $serverEvents[(int)$l['guid']][] = (int)$l['eventEntry'];
            }
        }
        // a spawn the card also places (within IMPORT_SAME_SPAWN yards, a holiday's IMPORT_SAME_HOLIDAY_SPAWN) is confirmed:
        // never moved to another of the card's places
        $confirmed = []; $spawnOrigin = [];
        if ($refresh && $radius > 0) {
            foreach ($tables[$table]['groups'] as $group) foreach ($group['rows'] as $row) {
                $r = array_combine($group['columns'], $row);
                $original = is_array($r['guid'] ?? null) ? implode('', $r['guid']) : (string)($r['guid'] ?? '');
                $events = $holiday[$table][$original] ?? null;
                $reach = $events ? IMPORT_SAME_HOLIDAY_SPAWN[$table] : IMPORT_SAME_SPAWN;
                foreach ($existing[($r['id'] ?? 0) . ':' . ($r['map'] ?? 0)] ?? [] as [$x, $y, $guid]) {
                    if ($events && !import_spot_shares($events, $serverEvents[$guid] ?? [])) continue;
                    if (is_numeric($r['position_x'] ?? null) && hypot($x - (float)$r['position_x'], $y - (float)$r['position_y']) < $reach) $confirmed[$guid] = true;
                }
            }
            $guids = []; foreach ($existing as $list) foreach ($list as $e) $guids[] = (string)$e[2];
            $spawnOrigin = import_origins('world', $table, $guids);
        }
        $templates = $kind === 'npc' ? 'creature_template' : 'gameobject_template';
        $known = [];
        foreach (array_chunk(array_keys($entries), 1000) as $chunk) foreach (rows("SELECT entry FROM `$templates` WHERE entry IN (" . implode(',', $chunk) . ')', [], 'world') as $t) $known[(int)$t['entry']] = true;
        foreach ($tables[$templates]['groups'] ?? [] as $group) foreach ($group['rows'] as $row) { $r = array_combine($group['columns'], $row); if (is_int($r['entry'] ?? null)) $known[$r['entry']] = true; }
        foreach ($tables[$table]['groups'] as &$group) {
            $keepRows = [];
            foreach ($group['rows'] as $row) {
                $r = array_combine($group['columns'], $row);
                $original = is_array($r['guid'] ?? null) ? implode('', $r['guid']) : (string)($r['guid'] ?? '');
                if (!isset($known[(int)($r['id'] ?? 0)])) { $unknown++; continue; }
                // the same creature or object close by on the server (a holiday's farther: IMPORT_SAME_HOLIDAY_SPAWN), or this
                // card's own at the same spot: it stands already
                $at = ($r['id'] ?? 0) . ':' . ($r['map'] ?? 0);
                $events = $holiday[$table][$original] ?? null;
                if (import_spawn_stands($table, $events, (float)$r['position_x'], (float)$r['position_y'], $existing[$at] ?? [], $added[$at] ?? [], $serverEvents)) { $nearby++; continue; }
                // the same creature or object a few yards off, that the card does not place where it stands: it moved
                if ($refresh && $radius > 0 && !isset($guidMap[$kind][$original])) {
                    $best = null; $bestAt = $radius;
                    foreach ($existing[$r['id'] . ':' . $r['map']] ?? [] as $i => [$x, $y, $guid]) {
                        if (!$guid || isset($confirmed[$guid])) continue;
                        // a holiday's spawn moves only a spawn its own event brings in, never another holiday's or one of all year
                        if ($events && !import_spot_shares($events, $serverEvents[$guid] ?? [], true)) continue;
                        $d = hypot($x - (float)$r['position_x'], $y - (float)$r['position_y']);
                        if ($d < $bestAt) { $best = $i; $bestAt = $d; }
                    }
                    if ($best !== null) {
                        $guid = $existing[$r['id'] . ':' . $r['map']][$best][2];
                        if (source_may_change($source, $spawnOrigin[(string)$guid] ?? null, $trust) === 'yes') {
                            foreach (['position_x', 'position_y', 'position_z', 'orientation'] as $c) {
                                if (is_int($r[$c] ?? null) || is_float($r[$c] ?? null)) forge_merge($ops, ['db' => 'world', 'table' => $table, 'columns' => ['guid', $c], 'match' => ['guid'], 'set' => $c, 'rows' => [[$guid, (float)$r[$c]]]]);
                            }
                            $confirmed[$guid] = true;
                            $existing[$r['id'] . ':' . $r['map']][$best] = [(float)$r['position_x'], (float)$r['position_y'], $guid];
                            $guidMap[$kind][$original] = $guid;   // its addon, formation… rows go with the spawn that stands
                            $origins[] = ['world', $table, (string)$guid, $source];
                            $moved++;
                            continue;
                        }
                        // a more trusted source placed it there: its word stands, and no second one is added beside it
                        $kept++;
                        continue;
                    }
                }
                $guidMap[$kind][$original] ??= ++$next[$kind];
                $r['guid'] = $guidMap[$kind][$original];
                $added[$at][] = [(float)$r['position_x'], (float)$r['position_y']];
                $origins[] = ['world', $table, (string)$r['guid'], $source];
                $keepRows[] = array_values($r);
            }
            $group['rows'] = $keepRows;
        }
        unset($group);
    }

    foreach ($tables as $table => $entry) {
        $database = $entry['db'];
        // the primary key, or the table's first index when it has none (loot tables: Entry, ItemType, Item)
        $primary = forge_primary($database, $table) ?: array_column(rows("SELECT COLUMN_NAME c FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = ?
            AND INDEX_NAME = (SELECT MIN(INDEX_NAME) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = ?) ORDER BY SEQ_IN_INDEX", [$table, $table], $database), 'c');
        foreach ($entry['groups'] as $group) {
            $columns = $group['columns'];
            $rows = [];
            foreach ($group['rows'] as $row) {
                $r = array_combine($columns, $row);
                // guid references of dependent tables follow their spawn's new guid
                if (isset(IMPORT_GUID_TABLES[$table])) {
                    $kind = IMPORT_GUID_KIND[$table] ?? (str_contains($table, 'gameobject') ? 'go' : 'npc');
                    $lost = false;
                    foreach (IMPORT_GUID_TABLES[$table] as $c) {
                        if (!array_key_exists($c, $r)) continue;
                        $original = is_array($r[$c]) ? implode('', $r[$c]) : (string)$r[$c];
                        if (isset($guidMap[$kind][$original])) $r[$c] = $guidMap[$kind][$original];
                        elseif (is_array($r[$c]) || !in_array($table, ['spawn_group', 'pool_members', 'linked_respawn'], true)) { $lost = true; break; }
                    }
                    if ($lost) continue;
                }
                if ($itemSet !== null) {
                    if (in_array($table, ['creature_loot_template', 'gameobject_loot_template', 'skinning_loot_template', 'pickpocketing_loot_template'], true) && !isset($itemSet[(int)($r['Item'] ?? 0)])) continue;
                    if ($table === 'npc_vendor' && !isset($itemSet[(int)($r['item'] ?? 0)])) continue;
                    if ($table === 'quest_template') {
                        $rewards = array_intersect_key($r, array_flip(['RewardItem1', 'RewardItem2', 'RewardItem3', 'RewardItem4', 'RewardChoiceItemID1', 'RewardChoiceItemID2', 'RewardChoiceItemID3', 'RewardChoiceItemID4', 'RewardChoiceItemID5', 'RewardChoiceItemID6']));
                        if (!array_intersect_key(array_flip(array_map('intval', $rewards)), $itemSet)) continue;
                    }
                }
                // a value the importer could not read (an unknown @variable or expression): the row is left out
                if (array_filter($r, 'is_array')) { $unknown++; continue; }
                if (isset(IMPORT_LOOT_COLUMN[$table]) && is_int($r['Entry'] ?? null)) $lootIds[$table][$r['Entry']] = true;
                if ($table === 'npc_vendor' && is_int($r['entry'] ?? null)) $vendors[$r['entry']] = true;
                if ($table === 'creature_trainer' && is_int($r['CreatureID'] ?? null)) $trainers[$r['CreatureID']] = true;
                $rows[] = array_values($r);
            }
            if (!$rows) continue;
            $match = $primary && !array_diff($primary, $columns) ? $primary : $columns;
            forge_merge($ops, ['db' => $database, 'table' => $table, 'columns' => $columns, 'match' => $match, 'rows' => $rows]);
            if ($refresh && $match !== $columns && !isset(IMPORT_SPAWN_TABLES[$table]) && !isset(IMPORT_GUID_TABLES[$table])) {
                [$sets, $written, $held] = import_newer_values($database, $table, $columns, $match, $rows, $source, $trust, $tolerance);
                foreach ($sets as $op) { forge_merge($ops, $op); $updated += count($op['rows']); }
                foreach ($written as $key) $origins[] = [$database, $table, $key, $source];
                $kept += $held;
            }
        }
    }
    // a creature drops a loot table only when its template points to it: fill LootID where it is still 0
    // a creature sells only with the vendor flag (npcflag 128): added where it lacks it
    // and trains only with the trainer flags (16 trainer + 64 profession trainer), added the same way
    $flags = [];
    foreach (array_keys($vendors) as $entry) $flags[$entry] = 128;
    foreach (array_keys($trainers) as $entry) $flags[$entry] = ($flags[$entry] ?? 0) | 16 | 64;
    if ($flags) forge_merge($ops, ['db' => 'world', 'table' => 'creature_template', 'columns' => ['entry', 'npcflag'], 'match' => ['entry'], 'bits' => 'npcflag',
        'rows' => array_map(fn($entry, $bits) => [$entry, $bits], array_keys($flags), $flags)]);
    // a creature drops, is skinned or pick-pocketed for a loot table only when its template points to it: the column
    // (LootID, SkinLootID, PickPocketLootID) is filled where it is still 0. A table some creature already points to
    // needs nothing: the rows were added to that creature's own table
    foreach ($lootIds as $table => $entries) {
        $column = IMPORT_LOOT_COLUMN[$table];
        foreach (array_chunk(array_keys($entries), 1000) as $chunk) {
            foreach (rows("SELECT DISTINCT `$column` id FROM creature_template_difficulty WHERE `$column` IN (" . implode(',', $chunk) . ')', [], 'world') as $r) unset($entries[(int)$r['id']]);
        }
        if (!$entries) continue;
        $fill = [];
        foreach (array_keys($entries) as $entry) $fill[] = [$entry, 0, $entry];
        forge_merge($ops, ['db' => 'world', 'table' => 'creature_template_difficulty', 'columns' => ['Entry', 'DifficultyID', $column], 'match' => ['Entry', 'DifficultyID'], 'fill' => $column, 'rows' => $fill]);
    }
    // only the whole card changes values: "the sources of these items" (the Items page) adds what is missing, no more
    if ($itemSet === null) foreach ($changes as $op) forge_merge($ops, $op);
    if ($nearby) $warnings[] = sprintf(t('%d spawn(s) already stand at the same place on the server and were left out.', '%d placement(s) existent déjà au même endroit sur le serveur et ont été écartés.'), $nearby);
    if ($moved) $warnings[] = sprintf(t('%d spawn(s) stood a few yards off and are moved to where this source places them.', '%d placement(s) se trouvaient à quelques mètres et sont déplacés là où cette source les place.'), $moved);
    if ($updated) $warnings[] = sprintf(t('%d value(s) of rows the server already has differ: this source\'s newer word replaces them.', '%d valeur(s) de lignes que le serveur a déjà diffèrent : le mot plus récent de cette source les remplace.'), $updated);
    if ($kept) $warnings[] = sprintf(t('%d row(s) or spawn(s) a more trusted source wrote differ and were left as they are.', '%d ligne(s) ou placement(s) écrits par une source plus fiable diffèrent et ont été laissés tels quels.'), $kept);
    if ($unknown) $warnings[] = sprintf(t('%d row(s) were left out: unknown template or a value the importer could not read.', '%d ligne(s) écartées : modèle inconnu ou valeur illisible.'), $unknown);
    $built = forge_plan($ops, [], $warnings);
    $built['items'] = [['type' => 'import', 'id' => $id, 'kind' => 'import']];
    $built['spawns'] = (bool)array_intersect(array_keys($tables), array_keys(IMPORT_SPAWN_TABLES));
    $built['origins'] = $origins;
    return $built;
}

/**
 * The newer values a card gives for rows the server already has: [set operations, row keys it writes (new or
 * changed), rows left alone because a more trusted source wrote them]. Every column the card gives is compared but
 * the key, VerifiedBuild and Comment; a drop chance only counts as moved past [sources] chance_tolerance.
 */
function import_newer_values(string $database, string $table, array $columns, array $match, array $rows, string $source, array $trust, float $tolerance): array
{
    $known = import_columns($database, $table);
    $compare = array_values(array_diff($columns, $match, ['VerifiedBuild', 'Comment']));
    $hasComment = in_array('Comment', $known, true);
    $at = array_flip($columns);
    $byKey = [];
    foreach ($rows as $row) $byKey[import_origin_key(array_map(fn($c) => $row[$at[$c]], $match))] ??= $row;
    $current = [];
    foreach (array_chunk(array_values($byKey), 500) as $chunk) {
        $tuples = array_map(fn($row) => array_map(fn($c) => $row[$at[$c]], $match), $chunk);
        $select = implode(',', array_map('forge_ident', array_merge($match, $compare, $hasComment ? ['Comment'] : [])));
        foreach (rows("SELECT $select FROM " . forge_ident($table) . ' WHERE ' . forge_in($match, $tuples, $database), [], $database) as $r) {
            $current[import_origin_key(array_map(fn($c) => $r[$c], $match))] = $r;
        }
    }
    $written = []; $sets = []; $held = 0;
    $origin = $current ? import_origins($database, $table, array_keys($current)) : [];
    foreach ($byKey as $key => $row) {
        if (!isset($current[$key])) { $written[] = $key; continue; }   // a new row: the insert writes it
        $now = $current[$key];
        $changed = [];
        foreach ($compare as $c) {
            $new = $row[$at[$c]];
            if ($new === null || is_array($new)) continue;
            $old = $now[$c];
            $differs = $c === 'Chance' && is_numeric($old) && is_numeric($new) ? source_chance_moved((float)$old, (float)$new, $tolerance) : ($old === null || !forge_same_value(is_float($new) ? (float)$old : $old, $new));
            if ($differs) $changed[$c] = $new;
        }
        if (!$changed) continue;
        if (source_may_change($source, $origin[$key] ?? ($hasComment ? source_origin($now['Comment'] ?? '') : null), $trust) !== 'yes') { $held++; continue; }
        foreach ($changed as $c => $new) $sets[$c][] = array_merge(array_map(fn($m) => $row[$at[$m]], $match), [$new]);
        $written[] = $key;
    }
    $ops = [];
    foreach ($sets as $c => $list) $ops[] = ['db' => $database, 'table' => $table, 'columns' => array_merge($match, [$c]), 'match' => $match, 'set' => $c, 'rows' => $list];
    return [$ops, $written, $held];
}

/** $stopped: the administrator confirmed "I have stopped the worldserver" (asked when no remote console can tell). */
function import_apply(int $id, array $only = [], array $items = [], bool $stopped = false): array
{
    forge_schema();
    require_once FT_APP . '/spawns.php';
    $built = import_build($id, $only, $items);
    if (!empty($built['spawns']) && $built['rows']) {
        $world = spawn_world_state();
        if ($world === 'running') {
            return ['ok' => false, 'message' => t('This import adds spawns and the worldserver is running: it hands out spawn ids itself. Stop it first, or leave the creature and gameobject tables out.', 'Cet import ajoute des placements et le worldserver tourne : il attribue lui-même les identifiants. Arrêtez-le d’abord, ou écartez les tables creature et gameobject.')];
        }
        // no console to ask: "it did not answer" would read as "stopped" and the spawns would go in under a running server
        if ($world === 'unknown' && !$stopped) {
            return ['ok' => false, 'confirm_stopped' => true, 'message' => t('This import adds spawns.', 'Cet import ajoute des placements.') . ' ' . spawn_world_unknown_message() . ' ' . t('Or leave the creature and gameobject tables out.', 'Ou écartez les tables creature et gameobject.')];
        }
    }
    $result = forge_commit($built, 'import');
    if ($result['ok'] && (int)($result['log'] ?? 0)) {
        try { import_origin_record($built['origins'] ?? [], $id); }
        catch (Throwable $e) { error_log('Forever Tracker: who wrote the rows of import #' . $id . ' could not be kept: ' . $e->getMessage()); }
    }
    return $result;
}

/**
 * Applies a card as soon as it is made ([imports] auto_apply, on unless set to 0), so an import is not left waiting
 * for its Apply button. $card: what import_file / source_card returned. Spawn rows (and the rows keyed by their guid)
 * go in only when the remote console says the worldserver is stopped: otherwise they stay on the card for the
 * Apply button, and the card says so. Returns $card with 'applied' (the Forge's answer) and the message extended.
 */
function import_auto_apply(array $card): array
{
    if (empty($card['ok']) || empty($card['id']) || !(int)config('imports', 'auto_apply', 1)) return $card;
    require_once FT_APP . '/spawns.php';
    $id = (int)$card['id'];
    $only = array_keys((array)($card['counts'] ?? []));
    $held = array_merge(array_keys(IMPORT_SPAWN_TABLES), array_keys(IMPORT_GUID_TABLES));
    $kept = [];
    if (array_intersect($only, array_keys(IMPORT_SPAWN_TABLES)) && spawn_world_state() !== 'stopped') {
        $kept = array_values(array_intersect($only, $held));
        $only = array_values(array_diff($only, $held));
    }
    try {
        $applied = $only ? import_apply($id, $only, [], false) : ['ok' => false, 'message' => ''];
    } catch (Throwable $e) {
        error_log('Forever Tracker: import #' . $id . ' could not be applied on its own: ' . $e->getMessage());
        $applied = ['ok' => false, 'message' => $e->getMessage()];
    }
    $card['applied'] = $applied;
    // nothing written: everything on it is already there (spawns that already stand at the same place included)
    $said = $only && !(int)($applied['log'] ?? 0) && ($applied['ok'] || !(int)($applied['rows'] ?? 0))
        ? trim(t('Nothing on it is missing from the server any more.', 'Plus rien n’y manque au serveur.') . ' ' . implode(' ', (array)($applied['warnings'] ?? [])))
        : ($applied['ok']
        ? trim(sprintf(t('Applied at once: %s row(s) (history #%d).', 'Appliqué aussitôt : %s ligne(s) (historique #%d).'), number((int)($applied['rows'] ?? 0)), (int)($applied['log'] ?? 0)) . ' ' . implode(' ', (array)($applied['warnings'] ?? [])))
        : ($only ? t('Not applied on its own:', 'Pas appliqué automatiquement :') . ' ' . strip_tags((string)($applied['message'] ?? '')) : ''));
    if ($kept) $said .= ' ' . sprintf(t('Spawns left on the card (%s): stop the worldserver, then press Apply.', 'Placements laissés sur la carte (%s) : arrêtez le worldserver, puis appliquez.'), implode(', ', $kept));
    $card['message'] = trim(trim((string)($card['message'] ?? '')) . ' ' . trim($said));
    return $card;
}
