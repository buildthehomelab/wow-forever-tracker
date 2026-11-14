<?php
// Imports one open data source as an import card aimed at the last analysis' gaps (docs/SOURCES.md).
//
//   php tools/source-import.php norgannondb|eglink|foreverdb|icyveins|atlasloot [--if-new] [--resume] [--log]
//
// One run of a source at a time: the run holds a lock (app/sources.php, source_lock) and a second one says so and
// exits 3 without touching anything.
// --if-new (AtlasLoot only): nothing when the newest CurseForge file is the one imported last (the container's check);
//   exit 3 while an analysis runs (check again soon).
// --resume (Icy Veins only, the container's start): goes on with a run a restart cut short, when there is one
//   (data/source-icyveins.resume, left by a run in flight); exit 3 while an analysis runs.
// --log: writes its lines to data/source-<source>.log (what the Imports page shows) instead of printing them, once it
//   holds the lock: a start that lost the race leaves the log of the run that won alone.
// Says what the card holds and what was left out. Nothing is applied: preview and apply it from The Forge › Imports.
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require FT_APP . '/norgannon.php';
require FT_APP . '/atlasloot.php';
$source = $argv[1] ?? '';
$flags = array_slice($argv, 2);
$ifNew = in_array('--if-new', $flags, true);
$resume = in_array('--resume', $flags, true) && $source === 'icyveins';
$run = ['norgannondb' => 'norgannon_import', 'eglink' => 'eglink_import', 'foreverdb' => 'foreverdb_import', 'icyveins' => 'icyveins_import', 'atlasloot' => 'atlasloot_import'];
if (!isset($run[$source])) { fwrite(STDERR, "usage: php tools/source-import.php " . implode('|', array_keys($run)) . " [--if-new] [--resume] [--log]\n"); exit(2); }
$lock = source_lock($source, 10);
if ($lock === false) { fwrite(STDERR, 'cannot open ' . source_lock_file($source) . ": is the data folder writable?\n"); exit(1); }
if ($lock === null) { echo date('H:i:s') . ' ' . SOURCES[$source][0] . ": an import of it is already running\n"; exit(3); }
$marker = source_resume_file($source);
if ($resume && !is_file($marker)) { echo date('H:i:s') . " Icy Veins: no run was cut short\n"; exit(0); }
$log = null;
if (in_array('--log', $flags, true)) {
    $log = fopen(source_log($source), 'w');
    ini_set('log_errors', '1'); ini_set('error_log', source_log($source));   // what stops the run shows where its progress did
}
$line = function (string $text) use (&$log) { if ($log) fwrite($log, $text); else echo $text; };
forge_schema();
$started = microtime(true);
$say = function (string $m) use ($source, $line) { @touch(source_lock_file($source)); $line(date('H:i:s') . " $m\n"); };   // the lock file's time: the run's last sign of life
if ($resume && analysis_status()['running']) { $say('an analysis is running: Icy Veins goes on after it'); exit(3); }
// a restart kills a run that takes hours: the marker says one was in flight. It goes when the run ends by itself (a
// card, nothing to add, or stopped because Icy Veins does not answer), and stays when the run is killed or breaks.
if ($source === 'icyveins') touch($marker);
$say($resume ? 'started again after a restart' : 'started');
$out = match ($source) { 'icyveins' => icyveins_import($say), 'atlasloot' => atlasloot_import($ifNew), default => $run[$source]() };
if ($source === 'icyveins') @unlink($marker);
// with a card, it closes the list; without one, the message is the last line (the Imports page shows it)
if (!empty($out['id'])) $line(date('H:i:s') . ' ' . ($out['message'] ?? '') . "\n");
foreach ($out['counts'] ?? [] as $table => $n) $line(sprintf("  %-28s %7d rows\n", $table, $n));
foreach ($out['ignored'] ?? [] as $why => $n) $line(sprintf("  left out: %-40s %7d\n", $why, $n));
if (!empty($out['id'])) $line(sprintf("import #%d in %.0f s\n", $out['id'], microtime(true) - $started));
else $line(date('H:i:s') . ' ' . ($out['message'] ?? '') . "\n");
source_unlock($lock);
exit(!empty($out['retry']) ? 3 : (!empty($out['ok']) ? 0 : 1));   // 3: try again soon (the container's check)
