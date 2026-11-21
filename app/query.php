<?php
// The Forge › Query: read-only SQL on the databases the tracker already reads (its world, hotfixes and own tables).
// For checks the pages do not show, without a shell on the database server. Nothing can be changed from here, by
// four locks that each hold alone:
//   1. a MySQL account of its own ([database] query_user, query_password) that may only read: before every query its
//      grants are read back, and anything but SELECT, SHOW VIEW or USAGE (a write right, a role, GRANT OPTION) stops
//      it. Without that account the page runs nothing: never the tracker's own user, which writes the PTR's world.
//   2. only statements that read are taken (query_check): no writes, executable comments, files or locking reads
//   3. one statement, on its own connection, inside START TRANSACTION READ ONLY, rolled back after
//   4. max_execution_time and a row limit
//
//   query_databases()        the databases offered: label => the name config.ini gives it
//   query_check($sql)        the statement as it will run, or an error message (string|array)
//   query_run($label, $sql)  ['ok' => true, columns, rows, truncated, ms] or ['ok' => false, 'error']
//   query_text($columns, $rows)  the rows as a text table, as `mysql -t` prints them

const QUERY_MAX_ROWS = 5000;
const QUERY_SECONDS = 30;
const QUERY_FIRST_WORDS = ['select', 'with', 'show', 'explain', 'describe', 'desc', 'table', 'values'];

/** Why the account's grants are not read-only, or null when they are. $grants: the lines SHOW GRANTS gives. */
function query_grants_problem(array $grants): ?string
{
    $allowed = ['SELECT', 'SHOW VIEW', 'USAGE'];
    foreach ($grants as $line) {
        if (!preg_match('/^GRANT\s+(.+?)\s+ON\s+(\S+)\s+TO\s+/i', $line, $m)) return 'a role or proxy is granted: ' . $line;
        if (preg_match('/WITH\s+GRANT\s+OPTION/i', $line)) return 'GRANT OPTION: ' . $line;
        // column grants name their columns in brackets: SELECT (`id`, `name`)
        foreach (array_map('trim', explode(',', strtoupper(preg_replace('/\([^)]*\)/', '', $m[1])))) as $privilege) {
            if (!in_array($privilege, $allowed, true)) return 'it may ' . $privilege . ' on ' . $m[2];
        }
    }
    return null;
}

function query_databases(): array
{
    $out = [];
    foreach (['world', 'hotfixes', 'tracker'] as $label) {
        $name = (string)config('database', $label, $label === 'tracker' ? 'forever_tracker' : $label);
        if ($name !== '') $out[$label] = $name;
    }
    return $out;
}

/** The statement to run (comments in front and semicolons at the end removed), or ['error' => why it is refused]. */
function query_check(string $sql)
{
    $sql = trim($sql);
    // comments in front: /* */, -- and #
    while (true) {
        if (strncmp($sql, '/*', 2) === 0) {
            $end = strpos($sql, '*/', 2);
            if ($end === false) return ['error' => 'unclosed comment'];
            $sql = ltrim(substr($sql, $end + 2));
        } elseif (preg_match('/^(--(\s|$)|#)/', $sql)) {
            $line = strpos($sql, "\n");
            $sql = $line === false ? '' : ltrim(substr($sql, $line + 1));
        } else break;
    }
    $sql = rtrim($sql, " \t\r\n;");
    if ($sql === '') return ['error' => 'no statement'];
    if (!preg_match('/^([a-z]+)\b/i', $sql, $m) || !in_array(strtolower($m[1]), QUERY_FIRST_WORDS, true)) {
        return ['error' => 'only statements that read: ' . strtoupper(implode(', ', QUERY_FIRST_WORDS))];
    }
    // MySQL runs the text of /*! ... */ as SQL: it could hide anything
    if (strpos($sql, '/*!') !== false) return ['error' => 'executable comments (/*! ... */) are not taken'];
    if (preg_match('/\binto\s+(outfile|dumpfile)\b/i', $sql)) return ['error' => 'nothing is written to files'];
    if (preg_match('/\bfor\s+(update|share)\b|\block\s+in\s+share\s+mode\b/i', $sql)) return ['error' => 'no locking reads: the worldserver uses these tables'];
    return $sql;
}

function query_run(string $label, string $sql, int $max = QUERY_MAX_ROWS): array
{
    $databases = query_databases();
    if (!isset($databases[$label])) return ['ok' => false, 'error' => 'unknown database'];
    $checked = query_check($sql);
    if (is_array($checked)) return ['ok' => false, 'error' => $checked['error']];
    $user = (string)config('database', 'query_user', '');
    if ($user === '') return ['ok' => false, 'error' => 'no read-only MySQL account: set [database] query_user and query_password (docs/FORGE.md, "Read-only SQL")'];
    $link = null;
    try {
        // its own connection and its own account: nothing it sets reaches the page's other queries
        $link = new mysqli((string)config('database', 'host', '127.0.0.1'), $user, (string)config('database', 'query_password', ''),
            $databases[$label], (int)config('database', 'port', 3306));
        $link->set_charset('utf8mb4');
        $grants = array_map(fn($r) => (string)$r[0], $link->query('SHOW GRANTS')->fetch_all(MYSQLI_NUM));
        $problem = query_grants_problem($grants);
        if ($problem !== null) return ['ok' => false, 'error' => "the account $user is not read-only ($problem): nothing was run"];
        $link->query('SET SESSION max_execution_time = ' . (QUERY_SECONDS * 1000));
        $link->query('SET SESSION TRANSACTION READ ONLY');
        $link->query('START TRANSACTION READ ONLY');
        $started = microtime(true);
        $result = $link->query($checked, MYSQLI_USE_RESULT);
        $columns = $rows = [];
        $truncated = false;
        if ($result instanceof mysqli_result) {
            foreach ($result->fetch_fields() as $field) $columns[] = $field->name;
            while (($row = $result->fetch_row()) !== null) {
                if (count($rows) >= $max) { $truncated = true; break; }
                $rows[] = $row;
            }
            $result->free();
        }
        $ms = (int)round((microtime(true) - $started) * 1000);
        $link->query('ROLLBACK');
        error_log('Forever Tracker query on ' . $label . ' (' . count($rows) . ' rows, ' . $ms . ' ms): ' . preg_replace('/\s+/', ' ', mb_substr($checked, 0, 300)));
        return ['ok' => true, 'database' => $databases[$label], 'columns' => $columns, 'rows' => $rows, 'truncated' => $truncated, 'ms' => $ms];
    } catch (mysqli_sql_exception $e) {
        return ['ok' => false, 'error' => $e->getMessage()];
    } finally {
        if ($link) { try { $link->close(); } catch (Throwable $e) {} }
    }
}

/** Rows as a text table, as `mysql -t` prints them (NULL for a null). */
function query_text(array $columns, array $rows): string
{
    if (!$columns) return "(no rows)\n";
    $cells = array_map(fn($r) => array_map(fn($v) => $v === null ? 'NULL' : str_replace(["\r", "\n", "\t"], ' ', (string)$v), $r), $rows);
    $width = array_map('mb_strlen', $columns);
    foreach ($cells as $r) foreach ($r as $i => $v) $width[$i] = max($width[$i], mb_strlen($v));
    $pad = fn($v, $w, $right) => $right ? str_repeat(' ', $w - mb_strlen($v)) . $v : $v . str_repeat(' ', $w - mb_strlen($v));
    $line = '+' . implode('+', array_map(fn($w) => str_repeat('-', $w + 2), $width)) . "+\n";
    $out = $line . '| ' . implode(' | ', array_map(fn($c, $i) => $pad($c, $width[$i], false), $columns, array_keys($columns))) . " |\n" . $line;
    foreach ($cells as $r) {
        $out .= '| ' . implode(' | ', array_map(fn($v, $i) => $pad($v, $width[$i], is_numeric($v) || $v === 'NULL'), $r, array_keys($r))) . " |\n";
    }
    return $out . $line;
}
