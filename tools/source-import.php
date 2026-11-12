<?php
// Imports one open data source as an import card aimed at the last analysis' gaps (docs/SOURCES.md).
//
//   php tools/source-import.php norgannondb|eglink|foreverdb|icyveins
//
// Prints what the card holds and what was left out. Nothing is applied: preview and apply it from The Forge › Imports.
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require FT_APP . '/norgannon.php';
$source = $argv[1] ?? '';
$run = ['norgannondb' => 'norgannon_import', 'eglink' => 'eglink_import', 'foreverdb' => 'foreverdb_import', 'icyveins' => 'icyveins_import'];
if (!isset($run[$source])) { fwrite(STDERR, "usage: php tools/source-import.php " . implode('|', array_keys($run)) . "\n"); exit(2); }
forge_schema();
$lock = FT_ROOT . "/data/source-$source.running";
touch($lock);
$started = microtime(true);
try {
    $say = function (string $m) use ($lock) { touch($lock); echo date('H:i:s') . " $m\n"; };
    $say('started');
    $out = $source === 'icyveins' ? icyveins_import($say) : $run[$source]();
} finally {
    @unlink($lock);
}
echo date('H:i:s') . ' ' . ($out['message'] ?? '') . "\n";
foreach ($out['counts'] ?? [] as $table => $n) echo sprintf("  %-28s %7d rows\n", $table, $n);
foreach ($out['ignored'] ?? [] as $why => $n) echo sprintf("  left out: %-40s %7d\n", $why, $n);
echo sprintf("import #%d in %.0f s\n", $out['id'] ?? 0, microtime(true) - $started);
exit(!empty($out['ok']) ? 0 : 1);
