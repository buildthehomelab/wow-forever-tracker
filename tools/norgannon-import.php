<?php
// Imports the pinned NorgannonDB as an import card aimed at the last analysis' gaps (docs/NORGANNONDB.md).
//
//   php tools/norgannon-import.php
//
// Prints what the import holds per table and what was left out. Nothing is applied: preview and apply it from
// The Forge › Imports (or php tools/wpp-import.php's apply step).
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require FT_APP . '/norgannon.php';
forge_schema();
$started = microtime(true);
$out = norgannon_import();
echo ($out['message'] ?? '') . "\n";
foreach ($out['counts'] ?? [] as $table => $n) echo sprintf("  %-28s %7d rows\n", $table, $n);
foreach ($out['ignored'] ?? [] as $why => $n) echo sprintf("  left out: %-24s %7d\n", $why, $n);
echo sprintf("import #%d in %.0f s\n", $out['id'] ?? 0, microtime(true) - $started);
exit(!empty($out['ok']) ? 0 : 1);
