<?php
// The Wowhead table (ft_wowhead, app/wowheaddb.php) from the command line.
//
//   php tools/wowhead-db.php backfill [--all]   what the files hold, into the table: the tooltip files written since the
//                                               last run and the page shelves that changed (--all: everything again).
//                                               The container runs it at start, the analysis after it asked Wowhead.
//   php tools/wowhead-db.php due [N]            the pages due to be read again that the crawl will be given (at most N)
//   php tools/wowhead-db.php changed [DATE]     how many answers changed since DATE (default: 7 days ago), by kind
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require_once FT_APP . '/wowheaddb.php';

$command = $argv[1] ?? '';
$link = wowhead_db_link();
if (!$link) { fwrite(STDERR, "the tracker's database cannot be reached ([database] of config.ini)\n"); exit(1); }
switch ($command) {
    case 'backfill':
        $started = microtime(true);
        $counts = wowhead_db_backfill(in_array('--all', $argv, true), fn(string $line) => print("$line\n"), $link);
        printf("%d tooltip(s) and %d page(s) from %d shelf file(s) written in %.1f s\n", $counts['tooltips'], $counts['pages'], $counts['shelves'], microtime(true) - $started);
        break;
    case 'due':
        foreach (wowhead_db_due_pages(isset($argv[2]) ? max(1, (int)$argv[2]) : null) as $kind => $ids) printf("%s: %d page(s): %s\n", $kind, count($ids), implode(' ', array_slice($ids, 0, 50)) . (count($ids) > 50 ? ' …' : ''));
        break;
    case 'changed':
        $since = $argv[2] ?? date('Y-m-d', time() - 7 * 86400);
        wowhead_db_ensure($link);
        $statement = $link->prepare('SELECT source, kind, COUNT(*) n FROM ' . WOWHEAD_DB_TABLE . ' WHERE changed_at > first_seen AND changed_at >= ? GROUP BY source, kind ORDER BY source, kind');
        $statement->bind_param('s', $since);
        $statement->execute();
        foreach ($statement->get_result()->fetch_all(MYSQLI_ASSOC) as $r) printf("%-8s %-10s %d changed since %s\n", $r['source'], $r['kind'], $r['n'], $since);
        break;
    default:
        fwrite(STDERR, "php tools/wowhead-db.php backfill [--all] | due [N] | changed [DATE]\n");
        exit(2);
}
