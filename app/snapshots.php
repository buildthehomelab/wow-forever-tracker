<?php
// What every source said, kept in the tracker's own database (docs/SNAPSHOTS.md).
//
// Each import turns its source into the same evidence: drops, vendors, quest givers and enders, trainers. Before this,
// that evidence was used for one card and thrown away, so the next run had to read the source again to know anything,
// and nothing said what a source had added or changed since. Now each run keeps it as a snapshot: a fact (who drops
// what, who sells what, ...) is one row with the first and the last snapshot that said it, so the database holds the
// whole history of every source without a copy per run, and "what is new" is a query.
//
// It stays private: the facts live in this tracker's database, never in the repository. Whoever wants them runs the
// tracker against the sources; only the rows a card exports to a data repository are ever published.

/** The evidence kinds kept, and how a row of each is read: [kind of the thing (npc/go) from, its id, the target id,
 *  the value]. The rest of a row is kept as it is. */
const SNAPSHOT_FACTS = [
    'drop' => 'a creature or object drops an item; value: the chance',
    'sell' => 'a creature sells an item; value: the stock (0 unlimited)',
    'start' => 'a creature or object gives a quest',
    'end' => 'a creature or object takes a quest',
    'train' => 'a creature teaches a spell; value: the cost',
];

function snapshot_schema(): void
{
    db()->query("CREATE TABLE IF NOT EXISTS ft_source_snapshots (id INT AUTO_INCREMENT PRIMARY KEY, source VARCHAR(32) NOT NULL,
        version VARCHAR(190) NOT NULL DEFAULT '', made DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, scope VARCHAR(16) NOT NULL DEFAULT 'all',
        facts INT NOT NULL DEFAULT 0, added INT NOT NULL DEFAULT 0, changed INT NOT NULL DEFAULT 0, gone INT NOT NULL DEFAULT 0, left_out JSON,
        KEY ix_source (source, id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
    db()->query("CREATE TABLE IF NOT EXISTS ft_source_facts (id BIGINT AUTO_INCREMENT PRIMARY KEY, source VARCHAR(32) NOT NULL,
        fact VARCHAR(8) NOT NULL, kind VARCHAR(4) NOT NULL DEFAULT '', entity INT NOT NULL, target INT NOT NULL, value DOUBLE NULL, extra TEXT NULL,
        first_snapshot INT NOT NULL, last_snapshot INT NOT NULL,
        KEY ix_open (source, last_snapshot), KEY ix_target (fact, target), KEY ix_entity (fact, kind, entity)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
}

/**
 * The facts of an evidence array, one per key: [key => [fact, kind, entity, target, value, extra]]. The same fact said
 * twice (a source that recorded several builds) keeps its highest value, as source_tables() does.
 */
function snapshot_facts(array $ev): array
{
    $out = [];
    $put = function (string $fact, string $kind, $entity, $target, $value, $extra) use (&$out) {
        $entity = (int)$entity; $target = (int)$target;
        if ($entity <= 0 || $target <= 0) return;
        $key = "$fact|$kind|$entity|$target";
        $value = is_numeric($value) ? round((float)$value, 4) : null;
        $extra = $extra ? json_encode(array_values($extra), JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION) : null;
        $have = $out[$key] ?? null;
        if ($have !== null && ($value === null || ($have[4] !== null && $have[4] >= $value))) return;
        $out[$key] = [$fact, $kind, $entity, $target, $value, $extra];
    };
    foreach ($ev['drop'] ?? [] as $d) $put('drop', (string)$d[0], $d[1] ?? 0, $d[2] ?? 0, $d[3] ?? null, array_slice($d, 4));
    foreach ($ev['sell'] ?? [] as $s) $put('sell', 'npc', $s[0] ?? 0, $s[1] ?? 0, $s[2] ?? null, array_slice($s, 3));
    foreach (['start', 'end'] as $role) foreach ($ev[$role] ?? [] as $r) $put($role, (string)$r[0], $r[1] ?? 0, $r[2] ?? 0, null, array_slice($r, 3));
    foreach ($ev['train'] ?? [] as $t) $put('train', 'npc', $t[0] ?? 0, $t[1] ?? 0, $t[2] ?? null, array_slice($t, 3));
    return $out;
}

/**
 * Keeps what $source said this run as a new snapshot: a fact it said before with the same value is carried on (its
 * last snapshot moves to this one); a new fact, or a known one with another value, is a new row; a fact it no longer
 * says stays as it was, ending at the snapshot before. $scope says whether the evidence was all the source holds
 * ('all') or only what the gaps asked about ('gaps'): a fact a 'gaps' run did not say is not gone, only not asked.
 * Returns the snapshot: [id, facts, added, changed, gone].
 */
function snapshot_keep(string $source, string $version, array $ev, string $scope = 'all'): array
{
    snapshot_schema();
    $facts = snapshot_facts($ev);
    $before = (int)(rows('SELECT MAX(id) m FROM ft_source_snapshots WHERE source = ?', [$source])[0]['m'] ?? 0);
    rows('INSERT INTO ft_source_snapshots (source, version, scope, left_out) VALUES (?, ?, ?, ?)', [$source, mb_substr($version, 0, 190), $scope, json_encode($ev['left'] ?? new stdClass())]);
    $id = (int)db()->insert_id;
    $open = [];
    if ($before) {
        foreach (rows('SELECT id, fact, kind, entity, target, value, extra FROM ft_source_facts WHERE source = ? AND last_snapshot = ?', [$source, $before]) as $r) {
            $open["{$r['fact']}|{$r['kind']}|{$r['entity']}|{$r['target']}"] = [(int)$r['id'], $r['value'] === null ? null : round((float)$r['value'], 4), $r['extra']];
        }
    }
    [$carry, $insert, $added, $changed, $gone] = snapshot_diff($open, $facts, $scope);
    foreach (array_chunk($carry, 5000) as $chunk) db()->query("UPDATE ft_source_facts SET last_snapshot = $id WHERE id IN (" . implode(',', array_map('intval', $chunk)) . ')');
    $link = db();
    foreach (array_chunk($insert, 2000) as $chunk) {
        $values = array_map(fn($f) => sprintf("('%s', '%s', '%s', %d, %d, %s, %s, %d, %d)", $link->real_escape_string($source), $link->real_escape_string($f[0]), $link->real_escape_string($f[1]),
            $f[2], $f[3], $f[4] === null ? 'NULL' : var_export($f[4], true), $f[5] === null ? 'NULL' : "'" . $link->real_escape_string($f[5]) . "'", $id, $id), $chunk);
        $link->query('INSERT INTO ft_source_facts (source, fact, kind, entity, target, value, extra, first_snapshot, last_snapshot) VALUES ' . implode(',', $values));
    }
    rows('UPDATE ft_source_snapshots SET facts = ?, added = ?, changed = ?, gone = ? WHERE id = ?', [count($facts), $added, $changed, $gone, $id]);
    return ['id' => $id, 'facts' => count($facts), 'added' => $added, 'changed' => $changed, 'gone' => $gone];
}

/**
 * This run's facts against the open rows of the run before ([key => [row id, value, extra]]): [the rows carried on,
 * the facts to insert, how many are new, changed, gone]. A 'gaps' run says nothing of what it did not ask: those
 * rows are carried on, not ended.
 */
function snapshot_diff(array $open, array $facts, string $scope = 'all'): array
{
    $carry = []; $insert = []; $added = 0; $changed = 0;
    foreach ($facts as $key => $f) {
        $have = $open[$key] ?? null;
        if ($have !== null && $have[1] === $f[4] && $have[2] === $f[5]) { $carry[] = $have[0]; unset($open[$key]); continue; }
        if ($have !== null) { $changed++; unset($open[$key]); } else $added++;
        $insert[] = $f;
    }
    if ($scope !== 'all') foreach ($open as $o) $carry[] = $o[0];
    return [$carry, $insert, $added, $changed, $scope === 'all' ? count($open) : 0];
}

/** Keeps a snapshot, but never lets keeping it stop the import: a database that cannot take it is logged. */
function snapshot_try(string $source, string $version, array $ev, string $scope = 'all'): ?array
{
    try { return snapshot_keep($source, $version, $ev, $scope); }
    catch (Throwable $e) { error_log('Forever Tracker: the ' . $source . ' snapshot was not kept: ' . $e->getMessage()); return null; }
}

/** The newest snapshot of each source, with what it changed: [source => row]. */
function snapshot_latest(): array
{
    snapshot_schema();
    $out = [];
    foreach (rows('SELECT s.* FROM ft_source_snapshots s JOIN (SELECT source, MAX(id) id FROM ft_source_snapshots GROUP BY source) m ON m.id = s.id ORDER BY s.source') as $r) $out[$r['source']] = $r;
    return $out;
}

/** What a snapshot changed, fact by fact: ['added' => rows, 'changed' => [[old, new]...], 'gone' => rows], at most
 *  $limit of each. */
function snapshot_changes(int $snapshot, int $limit = 200): array
{
    snapshot_schema();
    $s = rows('SELECT source, scope FROM ft_source_snapshots WHERE id = ?', [$snapshot])[0] ?? null;
    if (!$s) return ['added' => [], 'changed' => [], 'gone' => []];
    $before = (int)(rows('SELECT MAX(id) m FROM ft_source_snapshots WHERE source = ? AND id < ?', [$s['source'], $snapshot])[0]['m'] ?? 0);
    $fresh = rows("SELECT fact, kind, entity, target, value, extra FROM ft_source_facts WHERE source = ? AND first_snapshot = ? ORDER BY fact, target, entity LIMIT " . (int)($limit * 4), [$s['source'], $snapshot]);
    $old = [];
    if ($before && $fresh) {
        $keys = array_map(fn($r) => "{$r['fact']}|{$r['kind']}|{$r['entity']}|{$r['target']}", $fresh);
        foreach (rows("SELECT fact, kind, entity, target, value, extra FROM ft_source_facts WHERE source = ? AND last_snapshot = ? AND CONCAT_WS('|', fact, kind, entity, target) IN ('" . implode("','", array_map(fn($k) => db()->real_escape_string($k), $keys)) . "')", [$s['source'], $before]) as $r) {
            $old["{$r['fact']}|{$r['kind']}|{$r['entity']}|{$r['target']}"] = $r;
        }
    }
    $out = ['added' => [], 'changed' => [], 'gone' => []];
    foreach ($fresh as $r) {
        $key = "{$r['fact']}|{$r['kind']}|{$r['entity']}|{$r['target']}";
        if (isset($old[$key])) { if (count($out['changed']) < $limit) $out['changed'][] = [$old[$key], $r]; }
        elseif (count($out['added']) < $limit) $out['added'][] = $r;
    }
    if ($before && $s['scope'] === 'all') $out['gone'] = rows("SELECT f.fact, f.kind, f.entity, f.target, f.value, f.extra FROM ft_source_facts f WHERE f.source = ? AND f.last_snapshot = ?
        AND NOT EXISTS (SELECT 1 FROM ft_source_facts n WHERE n.source = f.source AND n.first_snapshot = ? AND n.fact = f.fact AND n.kind = f.kind AND n.entity = f.entity AND n.target = f.target)
        ORDER BY f.fact, f.target LIMIT " . (int)$limit, [$s['source'], $before, $snapshot]);
    return $out;
}
