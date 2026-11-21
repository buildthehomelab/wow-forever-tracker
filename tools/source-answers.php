<?php
// The answers table (ft_source_answers, app/sourceanswers.php; docs/SOURCES.md "The answers table") from the command line.
//
//   php tools/source-answers.php backfill [--all] [SOURCE ...]
//                                         what the files hold, into the table: per source what was written since the
//                                         last run (--all: everything again). The container runs it at start, the
//                                         analysis at its end; an import writes its own source when it downloads.
//   php tools/source-answers.php due [N]  the Wowhead pages due to be read again that the crawl will be given (at most N)
//   php tools/source-answers.php changed [DATE]
//                                         how many answers changed since DATE (default: 7 days ago), by source and kind
//   php tools/source-answers.php count    rows by source and feed: how many, how many missing or gone, how many due
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require_once FT_APP . '/sourceanswers.php';
require_once FT_APP . '/wowheaddb.php';
@ini_set('memory_limit', '2048M');

$command = $argv[1] ?? '';
$link = source_answers_link();
if (!$link) { fwrite(STDERR, "the tracker's database cannot be reached ([database] of config.ini)\n"); exit(1); }
switch ($command) {
    case 'backfill':
        $only = array_values(array_filter(array_slice($argv, 2), fn($a) => $a !== '--all'));
        if ($unknown = array_diff($only, SOURCE_ANSWERS_SOURCES)) { fwrite(STDERR, 'no such source: ' . implode(', ', $unknown) . ' (' . implode(', ', SOURCE_ANSWERS_SOURCES) . ")\n"); exit(2); }
        $started = microtime(true);
        $counts = source_answers_backfill(in_array('--all', $argv, true), fn(string $line) => print("$line\n"), $link, null, $only ?: null);
        if (!empty($counts['busy'])) { echo "another backfill is running: nothing done\n"; break; }
        printf("%d answer(s) written (%s) in %.1f s\n", array_sum($counts), implode(', ', array_map(fn($s, $n) => "$s $n", array_keys($counts), $counts)), microtime(true) - $started);
        break;
    case 'due':
        foreach (wowhead_db_due_pages(isset($argv[2]) ? max(1, (int)$argv[2]) : null) as $kind => $ids) printf("%s: %d page(s): %s\n", $kind, count($ids), implode(' ', array_slice($ids, 0, 50)) . (count($ids) > 50 ? ' …' : ''));
        break;
    case 'changed':
        $since = $argv[2] ?? date('Y-m-d', time() - 7 * 86400);
        source_answers_ensure($link);
        $statement = $link->prepare('SELECT source, feed, kind, COUNT(*) n FROM ' . SOURCE_ANSWERS_TABLE . ' WHERE changed_at > first_seen AND changed_at >= ? GROUP BY source, feed, kind ORDER BY source, feed, kind');
        $statement->bind_param('s', $since);
        $statement->execute();
        foreach ($statement->get_result()->fetch_all(MYSQLI_ASSOC) as $r) printf("%-15s %-8s %-24s %d changed since %s\n", $r['source'], $r['feed'], $r['kind'], $r['n'], $since);
        break;
    case 'count':
        source_answers_ensure($link);
        foreach ($link->query('SELECT source, feed, COUNT(*) n, SUM(status = \'missing\') missing, SUM(status = \'gone\') gone, SUM(due_at <= NOW()) due FROM '
            . SOURCE_ANSWERS_TABLE . ' GROUP BY source, feed ORDER BY source, feed')->fetch_all(MYSQLI_ASSOC) as $r) {
            printf("%-15s %-8s %8d rows, %d missing, %d gone, %d due\n", $r['source'], $r['feed'], $r['n'], $r['missing'], $r['gone'], $r['due']);
        }
        break;
    default:
        fwrite(STDERR, "php tools/source-answers.php backfill [--all] [SOURCE ...] | due [N] | changed [DATE] | count\n");
        exit(2);
}
