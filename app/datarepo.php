<?php
// Data repository export: turns an applied Forge operation into a world update file for a data repository
// (TrinityCore updater format), so a change tested on a test realm can go to the live realm by the same road as the
// rest of the world data. See docs/DATA-REPO.md.
//
// The file holds the rows the operation added, AS THEY ARE ON THE SERVER NOW (a row corrected by hand after the
// Forge added it is exported corrected; a row deleted since is left out). Running the file again changes nothing:
// a row is added only where none exists, and each added row is recorded in everlake_import_rows.
require_once FT_APP . '/forge.php';

const DATAREPO_STAGE = 'everlake_forge_stage';
const DATAREPO_LEDGER = 'everlake_import_rows';
/** Spawns get fixed guids, never MAX(guid) + 1: base + operation id × 10000. Keeps clear of the import block (900000000). */
const DATAREPO_GUID_BASE = 910000000;
const DATAREPO_GUID_STEP = 10000;
/** A spawn of the same creature or object this close (yards, same map) is the same spawn. */
const DATAREPO_SAME_SPAWN = 5;
/** Rows a table's rows need before they mean anything: [table => [column, parent table, parent column]]. */
const DATAREPO_PARENTS = [
    'trainer_spell' => ['TrainerId', 'trainer', 'Id'],
    'npc_vendor' => ['entry', 'creature_template', 'entry'],
    'creature' => ['id', 'creature_template', 'entry'],
    'gameobject' => ['id', 'gameobject_template', 'entry'],
    'creature_queststarter' => ['id', 'creature_template', 'entry'],
    'creature_questender' => ['id', 'creature_template', 'entry'],
];

/** Columns of a table with their types, generated columns left out. */
function datarepo_columns(string $table): array
{
    static $cache = [];
    return $cache[$table] ??= array_column(rows("SELECT COLUMN_NAME c, DATA_TYPE t FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = ? AND EXTRA NOT LIKE '%GENERATED%' ORDER BY ORDINAL_POSITION", [$table], 'world'), 't', 'c');
}

/** SQL literal of a value read from the world database, by column type. */
function datarepo_literal($value, string $type): string
{
    if ($value === null) return 'NULL';
    $numeric = in_array($type, ['tinyint', 'smallint', 'mediumint', 'int', 'bigint', 'float', 'double', 'decimal', 'bit'], true);
    if ($numeric && preg_match('/^-?\d+(\.\d+)?([eE][-+]?\d+)?$/', (string)$value)) return (string)$value;
    return "'" . db('world')->real_escape_string((string)$value) . "'";
}

/** File name for an operation: the day it was applied, NN 900, the operation id and what it did. */
function datarepo_file_name(array $log): string
{
    $kind = preg_replace('/[^a-z]+/', '_', strtolower(str_replace(',', '_', (string)$log['kind'])));
    return date('Y_m_d', strtotime($log['created_at'])) . '_900_world_everlake_forge_' . sprintf('%05d', (int)$log['id']) . '_' . trim($kind, '_') . '.sql';
}

/**
 * What an operation changed in the world database, read back from its rollback (which names exactly the rows it added):
 * ['inserts' => [table => where-clauses], 'spawns' => [creature|gameobject => [guids]], 'updates' => [apply statements], 'skipped' => [why]].
 */
function datarepo_changes(array $log): array
{
    $out = ['inserts' => [], 'spawns' => [], 'updates' => [], 'refreshed' => [], 'skipped' => []];
    foreach (json_decode($log['sql_rollback'], true) ?: [] as $database => $sql) {
        if ($database === 'console') {
            // console spawns: "forge delete npc|go <guid>"
            preg_match_all('/forge delete (npc|go) (\d+)/', (string)$sql, $m, PREG_SET_ORDER);
            foreach ($m as [, $kind, $guid]) $out['spawns'][$kind === 'npc' ? 'creature' : 'gameobject'][] = (int)$guid;
            continue;
        }
        if ($database !== 'world') {
            $out['skipped'][] = sprintf(t('%s rows are not exported: the data repository holds world update files only.', 'Les lignes %s ne sont pas exportées : le dépôt de données ne contient que des mises à jour world.'), $database);
            continue;
        }
        foreach (forge_statements($sql) as $statement) {
            if (preg_match('/^DELETE FROM `([A-Za-z0-9_]+)` WHERE (.+?);?$/s', $statement, $m)) {
                if (in_array($m[1], ['creature', 'gameobject'], true) && preg_match('/^`guid` IN \(([\d,]+)\)$/', $m[2], $g)) {
                    foreach (explode(',', $g[1]) as $guid) $out['spawns'][$m[1]][] = (int)$guid;
                } else {
                    $out['inserts'][$m[1]][] = $m[2];
                }
            }
        }
    }
    // flag and fill changes: their apply statements, made safe to run twice
    foreach (json_decode($log['sql_apply'], true) ?: [] as $database => $sql) {
        if ($database !== 'world') continue;
        foreach (forge_statements($sql) as $statement) {
            if (str_contains($statement, FORGE_SET_MARK)) {
                // a refreshed value: the statement already names the value it replaces, so it is safe to run twice as it is
                $out['refreshed'][] = rtrim($statement, ';') . ';';
            } elseif (preg_match('/^UPDATE `([A-Za-z0-9_]+)` SET `([A-Za-z0-9_]+)` = `\2` \| (\d+) WHERE (.+?);?$/s', $statement, $m)) {
                $out['updates'][] = "UPDATE `$m[1]` SET `$m[2]` = `$m[2]` | $m[3] WHERE $m[4] AND (`$m[2]` & $m[3]) <> $m[3];";
            } elseif (preg_match('/^UPDATE `([A-Za-z0-9_]+)` SET `([A-Za-z0-9_]+)` = (.+?) WHERE (.+?);?$/s', $statement, $m)) {
                $out['updates'][] = "UPDATE `$m[1]` SET `$m[2]` = $m[3] WHERE $m[4] AND (`$m[2]` IS NULL OR `$m[2]` = 0 OR `$m[2]` = '');";
            }
        }
    }
    return $out;
}

/** The names of the import cards an operation applied, without their licence text ("Icy Veins 2026-11-14"); [] for
 *  another kind of operation, or when the cards were forgotten since. */
function datarepo_sources(array $log): array
{
    $ids = [];
    foreach (json_decode((string)($log['items'] ?? ''), true) ?: [] as $item) if (is_array($item) && ($item['type'] ?? '') === 'import') $ids[(int)($item['id'] ?? 0)] = true;
    if (!$ids || !table_exists('ft_imports')) return [];
    $names = [];
    foreach (rows('SELECT name FROM ft_imports WHERE id IN (' . implode(',', array_keys($ids)) . ') ORDER BY id') as $r) {
        $name = trim(preg_replace('/[\x00-\x1f]+/', ' ', explode(' · ', (string)$r['name'])[0]));
        if ($name !== '') $names[$name] = true;
    }
    return array_keys($names);
}

/** Stage, filter and insert one table's rows; $rows are read from the world database (column => value). */
function datarepo_block(string $table, array $rows, string $file, string $note, ?int $guidBase = null): array
{
    $types = datarepo_columns($table);
    $columns = array_keys($types);
    $ident = fn($c) => forge_ident($c);
    $list = implode(', ', array_map($ident, $columns));
    $stage = forge_ident(DATAREPO_STAGE);
    $out = ["-- $table: " . count($rows) . ' row(s)',
        "DROP TEMPORARY TABLE IF EXISTS $stage;",
        "CREATE TEMPORARY TABLE $stage SELECT $list FROM " . forge_ident($table) . ' LIMIT 0;'];
    foreach (array_chunk($rows, 200) as $chunk) {
        $out[] = "INSERT INTO $stage ($list) VALUES\n" . implode(",\n", array_map(fn($r) => '(' . implode(', ', array_map(fn($c) => datarepo_literal($r[$c] ?? null, $types[$c]), $columns)) . ')', $chunk)) . ';';
    }
    // the key a row is matched on: the primary key, else the table's first index (loot tables have no primary key:
    // Entry, ItemType, Item), else every column; without it a run again would add the row a second time
    $primary = forge_primary('world', $table) ?: array_column(rows("SELECT COLUMN_NAME c FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = ?
        AND INDEX_NAME = (SELECT MIN(INDEX_NAME) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = ?) ORDER BY SEQ_IN_INDEX", [$table, $table], 'world'), 'c') ?: $columns;
    if ($guidBase !== null) {
        // a spawn: same creature or object within a few yards on the same map = already there, and the guid must be free
        $d = DATAREPO_SAME_SPAWN * DATAREPO_SAME_SPAWN;
        $out[] = "DELETE s FROM $stage s JOIN `$table` x ON x.`id` = s.`id` AND x.`map` = s.`map` AND (x.`position_x` - s.`position_x`) * (x.`position_x` - s.`position_x`) + (x.`position_y` - s.`position_y`) * (x.`position_y` - s.`position_y`) <= $d;";
        $out[] = "DELETE s FROM $stage s JOIN `$table` x ON x.`guid` = s.`guid`;";
    } elseif ($primary) {
        $out[] = "DELETE s FROM $stage s JOIN `$table` x ON " . implode(' AND ', array_map(fn($c) => "x.`$c` <=> s.`$c`", $primary)) . ';';
    }
    if (isset(DATAREPO_PARENTS[$table])) {
        [$column, $parent, $parentColumn] = DATAREPO_PARENTS[$table];
        $out[] = "DELETE FROM $stage WHERE NOT EXISTS (SELECT 1 FROM `$parent` p WHERE p.`$parentColumn` = $stage.`$column`);";
    }
    $out[] = 'INSERT INTO ' . forge_ident($table) . " ($list) SELECT $list FROM $stage;";
    $keys = $primary ?: [];
    $numeric = !array_diff(array_map(fn($c) => in_array($types[$c] ?? '', ['tinyint', 'smallint', 'mediumint', 'int', 'bigint'], true) ? 'ok' : 'no', $keys), ['ok']);
    if ($keys && count($keys) <= 4 && $numeric) {
        $k = array_map(fn($i) => isset($keys[$i]) ? "s.`{$keys[$i]}`" : '0', range(0, 3));
        $out[] = 'INSERT IGNORE INTO ' . forge_ident(DATAREPO_LEDGER) . " (`tbl`, `k1`, `k2`, `k3`, `k4`, `file`, `note`) SELECT '$table', " . implode(', ', $k)
            . ", '" . db('world')->real_escape_string($file) . "', '" . db('world')->real_escape_string($note) . "' FROM $stage s;";
    } else {
        $out[] = "-- (not recorded in " . DATAREPO_LEDGER . ": the key of $table is not up to four numbers)";
    }
    return $out;
}

/** The update file of an applied operation: ['ok', 'name', 'sql', 'rows', 'warnings']. */
function datarepo_export(int $logId): array
{
    forge_schema();
    $log = row('SELECT * FROM ft_forge_log WHERE id = ?', [$logId]);
    if (!$log || $log['state'] !== 'applied') return ['ok' => false, 'message' => t('Only applied operations can be exported.', 'Seules les opérations appliquées peuvent être exportées.')];
    $file = datarepo_file_name($log);
    // an import names its card (the source and its version) in every ledger note and in the header: "Icy Veins 2026-11-14"
    $sources = datarepo_sources($log);
    $note = mb_substr('Forge #' . (int)$log['id'] . ($sources ? ': ' . implode(', ', $sources) : ' (' . $log['kind'] . ')'), 0, 250);
    $changes = datarepo_changes($log);
    $warnings = $changes['skipped']; $blocks = []; $count = 0;

    foreach ($changes['inserts'] as $table => $wheres) {
        if (!table_exists($table, 'world')) { $warnings[] = sprintf(t('Table %s is gone: left out.', 'La table %s n’existe plus : écartée.'), $table); continue; }
        $found = [];
        foreach ($wheres as $where) foreach (rows('SELECT * FROM ' . forge_ident($table) . ' WHERE ' . $where, [], 'world') as $r) $found[] = $r;
        if (!$found) { $warnings[] = sprintf(t('%s: the rows were removed from the server since.', '%s : les lignes ont été retirées du serveur depuis.'), $table); continue; }
        $blocks[] = datarepo_block($table, $found, $file, $note);
        $count += count($found);
    }
    $base = DATAREPO_GUID_BASE + (int)$log['id'] * DATAREPO_GUID_STEP;
    foreach ($changes['spawns'] as $table => $guids) {
        $found = [];
        foreach (array_chunk(array_values(array_unique($guids)), 500) as $chunk) {
            foreach (rows('SELECT * FROM ' . forge_ident($table) . ' WHERE guid IN (' . implode(',', array_map('intval', $chunk)) . ') ORDER BY guid', [], 'world') as $r) $found[] = $r;
        }
        if (!$found) { $warnings[] = sprintf(t('%s: the spawns were removed from the server since.', '%s : les placements ont été retirés du serveur depuis.'), $table); continue; }
        if (count($found) >= DATAREPO_GUID_STEP) return ['ok' => false, 'message' => 'Too many spawns in one operation.'];
        foreach ($found as $i => &$r) $r['guid'] = $base + $i;
        unset($r);
        $blocks[] = datarepo_block($table, $found, $file, $note, $base);
        $count += count($found);
    }
    if ($changes['updates']) {
        $blocks[] = array_merge(['-- flags and empty columns the operation set (only where still unset)'], $changes['updates']);
        $count += count($changes['updates']);
    }
    if ($changes['refreshed']) {
        $blocks[] = array_merge(['-- values a source measured again: each statement names the value it replaces, so it changes nothing where the', '-- row moved on, and nothing more when it runs again'], $changes['refreshed']);
        $count += count($changes['refreshed']);
    }
    if (!$blocks) return ['ok' => false, 'message' => $warnings ? implode(' ', $warnings) : t('Nothing of this operation is left to export.', 'Plus rien à exporter pour cette opération.')];

    $items = json_decode((string)$log['items'], true) ?: [];
    $build = (int)(meta()['client_build'] ?? 0);
    $head = [
        "-- Everlake Forge #{$log['id']}: " . forge_kind_label(explode(',', $log['kind'])[0]) . ', ' . count($items) . ' resource(s), ' . $count . ' row(s)',
        "-- $file: exported by the Forever Tracker Forge (https://github.com/buildthehomelab/wow-forever-tracker) from a realm where it was applied and tested first.",
        '-- Made from the official WoW Forever client data' . ($build ? " (build $build)" : '') . ' and the Forge rules (docs/FORGE.md); rows as they were on that realm when exported.',
        ...($sources ? ['-- Sources: ' . implode(', ', $sources) . ' (NOTICE.md, Forge exports).'] : []),
        '-- Never edit this file once it is deployed: a later fix is a new file. Running it again changes nothing: a row is added only',
        '-- where none exists, spawns only where the same creature or object is not already within ' . DATAREPO_SAME_SPAWN . ' yards, and each added row is recorded in ' . DATAREPO_LEDGER . '.',
        '',
        'CREATE TABLE IF NOT EXISTS `' . DATAREPO_LEDGER . "` (
  `tbl` varchar(64) NOT NULL COMMENT 'world table of the row',
  `k1` bigint NOT NULL COMMENT 'the row''s key, in the table''s primary key order',
  `k2` bigint NOT NULL DEFAULT '0',
  `k3` bigint NOT NULL DEFAULT '0',
  `k4` bigint NOT NULL DEFAULT '0',
  `file` varchar(200) NOT NULL COMMENT 'the update file that added the row',
  `note` varchar(255) NOT NULL DEFAULT '' COMMENT 'the sources that gave it',
  PRIMARY KEY (`tbl`, `k1`, `k2`, `k3`, `k4`),
  KEY `file` (`file`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Rows the Everlake world import added (docs/forever-import.md)';",
        '',
        'START TRANSACTION;',
    ];
    $body = implode("\n\n", array_map(fn($b) => implode("\n", $b), $blocks));
    $sql = implode("\n", $head) . "\n" . $body . "\n\nDROP TEMPORARY TABLE IF EXISTS `" . DATAREPO_STAGE . "`;\nCOMMIT;\n";
    return ['ok' => true, 'name' => $file, 'sql' => $sql, 'rows' => $count, 'warnings' => $warnings];
}

/** Every applied operation as one zip of update files (the ones with nothing left to export are listed in warnings). */
function datarepo_export_all(): array
{
    require_once FT_APP . '/spawns.php';
    forge_schema();
    $files = []; $warnings = [];
    foreach (rows("SELECT id FROM ft_forge_log WHERE state = 'applied' ORDER BY id") as $x) {
        $one = datarepo_export((int)$x['id']);
        if ($one['ok']) { $files['sql/world/' . $one['name']] = $one['sql']; foreach ($one['warnings'] as $w) $warnings[] = '#' . $x['id'] . ': ' . $w; }
        else $warnings[] = '#' . $x['id'] . ': ' . $one['message'];
    }
    if (!$files) return ['ok' => false, 'message' => $warnings ? implode(' ', $warnings) : t('Nothing applied yet.', 'Rien n’a encore été appliqué.')];
    return ['ok' => true, 'zip' => base64_encode(spawn_zip($files)), 'name' => 'forge-data-repo-' . date('Y-m-d') . '.zip', 'files' => count($files), 'warnings' => $warnings];
}
