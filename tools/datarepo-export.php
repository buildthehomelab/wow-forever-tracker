<?php
// Writes applied Forge operations as world update files for a data repository (docs/DATA-REPO.md).
//
//   php tools/datarepo-export.php <operation id>|all <folder>
//
// Each file goes to <folder>/<name>.sql; an existing file of the same name is left alone (a deployed update file is
// never changed). Prints one line per operation.
if (PHP_SAPI !== 'cli') exit;
$_SERVER['SCRIPT_NAME'] = '/index.php';
require dirname(__DIR__) . '/app/bootstrap.php';
require FT_APP . '/datarepo.php';

[$which, $folder] = [$argv[1] ?? '', $argv[2] ?? ''];
if ($which === '' || $folder === '' || !is_dir($folder)) { fwrite(STDERR, "usage: php tools/datarepo-export.php <operation id>|all <folder>\n"); exit(2); }
forge_schema();
$ids = $which === 'all' ? array_map('intval', array_column(rows("SELECT id FROM ft_forge_log WHERE state = 'applied' ORDER BY id"), 'id')) : [(int)$which];
$failed = 0;
foreach ($ids as $id) {
    $out = datarepo_export($id);
    if (!$out['ok']) { echo "#$id: {$out['message']}\n"; $failed += $which === 'all' ? 0 : 1; continue; }
    $path = rtrim($folder, '/') . '/' . $out['name'];
    if (file_exists($path)) { echo "#$id: {$out['name']} exists, left alone\n"; continue; }
    file_put_contents($path, $out['sql']);
    echo "#$id: {$out['name']} ({$out['rows']} rows)" . ($out['warnings'] ? ' · ' . implode(' · ', $out['warnings']) : '') . "\n";
}
exit($failed ? 1 : 0);
