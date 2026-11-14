<?php
// Long imports (app/sources.php, tools/source-import.php): one run of a source at a time, by a lock the system lets
// go when the run ends; and Icy Veins lookups that get no answer slow the run down instead of being fired one after
// the other.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

// ---- the lock
$path = ft_test_dir() . '/source-test.running';
check(!source_running('test', $path), 'no lock file: not running');
$first = source_lock('test', 1, $path);
check(is_resource($first), 'the first run gets the lock');
check(source_lock('test', 1, $path) === null, 'a second one does not');
check(source_running('test', $path), 'and the source shows as running');
$t = microtime(true);
check(source_lock('test', 3, $path) === null && microtime(true) - $t >= 0.35, 'asking three times waits between the tries');
source_unlock($first);
check(is_file($path), 'the lock file stays in place when the run ends');
check(!source_running('test', $path), 'but nothing holds it: not running');
$again = source_lock('test', 1, $path);
check(is_resource($again), 'so the next run gets it');

// a program the run starts must not carry the lock on after it
exec('(sleep 2) > /dev/null 2>&1 &');
fclose($again);   // the run ends without unlocking, as a killed one does
check(!source_running('test', $path), 'a run that died holds nothing, whatever it had started');

// a lock file another user made (a run started as root) can still be locked
chmod($path, 0444);
$readonly = source_lock('test', 1, $path);
check(is_resource($readonly) && source_lock('test', 1, $path) === null, 'a lock file that cannot be written is locked all the same');
source_unlock($readonly);
check(source_lock('test', 1, ft_test_dir() . '/no/such/folder/x.running') === false, 'a lock file that cannot be opened is not "running"');

// ---- the command: a second run of a source says so and leaves the log alone
$lockFile = source_lock_file('eglink');
check($lockFile === FT_ROOT . '/data/source-eglink.running', 'the lock lives in the data folder');
$mine = !is_file($lockFile);
$held = source_lock('eglink');
if (!is_resource($held)) check(false, 'could not take the eglink lock of this checkout (an import is running here?)');
else {
    $log = source_log('eglink');
    $before = is_file($log) ? file_get_contents($log) : null;
    exec(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(FT_ROOT . '/tools/source-import.php') . ' eglink --log 2>&1', $output, $code);
    check($code === 3 && str_contains(implode("\n", $output), 'already running'), 'a second run of the command exits 3: already running');
    check((is_file($log) ? file_get_contents($log) : null) === $before, 'and does not touch the log of the run that holds the lock');
    source_unlock($held);
    if ($mine) @unlink($lockFile);   // this checkout had none: leave it as it was
}

// ---- the container's restart: nothing to go on with when no run was cut short (asked before any database is opened)
if (!is_file(source_resume_file('icyveins'))) {
    $mine = !is_file(source_lock_file('icyveins'));
    $output = [];
    exec(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(FT_ROOT . '/tools/source-import.php') . ' icyveins --resume --log 2>&1', $output, $code);
    check($code === 0 && str_contains(implode("\n", $output), 'no run was cut short'), '--resume without a run that was cut short: nothing to do');
    if ($mine) @unlink(source_lock_file('icyveins'));
}

// ---- Icy Veins: lookups without an answer
check(icyveins_backoff(0) === 0, 'no failure: the usual pace');
check(array_map('icyveins_backoff', [1, 2, 3, 4, 5, 6, 7, 8, 19]) === [1, 2, 4, 8, 16, 32, 60, 60, 60], 'each failure in a row doubles the wait, up to a minute');
$total = array_sum(array_map('icyveins_backoff', range(1, ICYVEINS_MAX_FAILURES - 1)));
check(ICYVEINS_MAX_FAILURES === 20 && $total > 600 && $total < 1200, "the 20 failures that stop a run take $total s: a short outage is waited out, a long one stops it");

ft_test_done();
