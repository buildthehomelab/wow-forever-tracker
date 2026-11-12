<?php
// Imports one open data source as an import card aimed at the last analysis' gaps (docs/SOURCES.md).
//
//   php tools/source-import.php norgannondb|eglink|foreverdb|icyveins|atlasloot [--if-new]
//
// --if-new (AtlasLoot only): nothing when the newest CurseForge file is the one imported last (the container's check);
// exit 3 while an analysis runs (check again soon).
// Prints what the card holds and what was left out. Nothing is applied: preview and apply it from The Forge › Imports.
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require FT_APP . '/norgannon.php';
require FT_APP . '/atlasloot.php';
$source = $argv[1] ?? '';
$ifNew = in_array('--if-new', array_slice($argv, 2), true);
$run = ['norgannondb' => 'norgannon_import', 'eglink' => 'eglink_import', 'foreverdb' => 'foreverdb_import', 'icyveins' => 'icyveins_import', 'atlasloot' => 'atlasloot_import'];
if (!isset($run[$source])) { fwrite(STDERR, "usage: php tools/source-import.php " . implode('|', array_keys($run)) . "\n"); exit(2); }
forge_schema();
$lock = FT_ROOT . "/data/source-$source.running";
touch($lock);
$started = microtime(true);
try {
    $say = function (string $m) use ($lock) { touch($lock); echo date('H:i:s') . " $m\n"; };
    $say('started');
    $out = match ($source) { 'icyveins' => icyveins_import($say), 'atlasloot' => atlasloot_import($ifNew), default => $run[$source]() };
} finally {
    @unlink($lock);
}
// with a card, it closes the list; without one, the message is the last line (the Imports page shows it)
if (!empty($out['id'])) echo date('H:i:s') . ' ' . ($out['message'] ?? '') . "\n";
foreach ($out['counts'] ?? [] as $table => $n) echo sprintf("  %-28s %7d rows\n", $table, $n);
foreach ($out['ignored'] ?? [] as $why => $n) echo sprintf("  left out: %-40s %7d\n", $why, $n);
if (!empty($out['id'])) echo sprintf("import #%d in %.0f s\n", $out['id'], microtime(true) - $started);
else echo date('H:i:s') . ' ' . ($out['message'] ?? '') . "\n";
exit(!empty($out['retry']) ? 3 : (!empty($out['ok']) ? 0 : 1));   // 3: try again soon (the container's check)
