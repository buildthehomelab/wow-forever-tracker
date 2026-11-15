<?php
// Checkout: the client's data at a step of the timeline as an SQL file for a test realm's hotfixes database
// (tools/ft/checkout.py, docs/CHECKOUT.md). The website starts `tracker.py checkout` in the background, one at a
// time, shows its log, and hands out the files it wrote.

/** The folder the files are written to (tools/ft/checkout.py OUT). */
function checkout_dir(): string { return FT_ROOT . '/data/checkout'; }

/** A step's name as the timeline gives it: a build (70707) or a build's hotfix update (70938+1); null otherwise. */
function checkout_step(string $step): ?string
{
    return preg_match('/^\d{4,7}(\+\d{1,4})?\z/', $step) ? $step : null;
}

/** [step => ['manifest' => array, 'size' => bytes, 'made' => time]] of the files already written. */
function checkout_files(?string $dir = null): array
{
    $dir ??= checkout_dir();
    $out = [];
    foreach (glob($dir . '/hotfixes-*.sql') ?: [] as $sql) {
        $step = checkout_step(substr(basename($sql, '.sql'), strlen('hotfixes-')));
        $manifest = json_decode((string)@file_get_contents($sql . '.json'), true);
        if ($step === null || !is_array($manifest) || ($manifest['step'] ?? null) !== $step) continue;   // only a whole file has its manifest
        $out[$step] = ['manifest' => $manifest, 'size' => (int)filesize($sql), 'made' => (int)filemtime($sql)];
    }
    return $out;
}

/** The file of a step, when it was written whole; null otherwise. */
function checkout_file(string $step, ?string $dir = null): ?string
{
    $step = checkout_step($step);
    if ($step === null || !isset(checkout_files($dir)[$step])) return null;
    return ($dir ?? checkout_dir()) . '/hotfixes-' . $step . '.sql';
}

/** ['running' => bool, 'step' => the step asked for, 'failed' => bool, 'log' => the last lines] of the last checkout run. */
function checkout_status(?string $dir = null): array
{
    $dir ??= checkout_dir();
    $log = $dir . '/run.log';
    $state = json_decode((string)@file_get_contents($dir . '/run.json'), true) ?: [];
    $text = is_file($log) ? (string)file_get_contents($log) : '';
    $started = (int)($state['at'] ?? 0);
    $finished = str_contains($text, 'FT-END');
    // a log silent for 30 minutes is a run that died (the website stopped, the machine slept): the button is free again
    $alive = max($started, is_file($log) ? (int)filemtime($log) : 0) > time() - 1800;
    $failed = $finished && !preg_match('/checkout \S+: \d+ tables/', $text);
    $lines = array_filter(preg_split('/\R/', trim($text)), fn($l) => trim($l) !== 'FT-END' && trim($l) !== '');
    return ['running' => $started && !$finished && $alive, 'step' => (string)($state['step'] ?? ''), 'failed' => $failed,
            'log' => implode("\n", array_slice(array_values($lines), -12))];
}

/** Starts `tracker.py checkout <step> --fetch` in the background; one run at a time. */
function checkout_start(string $step): array
{
    $step = checkout_step($step);
    if ($step === null) return ['ok' => false, 'message' => t('No such step.', 'Étape inconnue.')];
    if (checkout_status()['running']) return ['ok' => false, 'message' => t('A checkout is already being written.', 'Un checkout est déjà en cours d’écriture.')];
    $dir = checkout_dir();
    if (!is_dir($dir) && !@mkdir($dir, 0775, true)) return ['ok' => false, 'message' => t('The data folder cannot be written.', 'Le dossier data ne peut pas être écrit.')];
    $log = $dir . '/run.log';
    file_put_contents($dir . '/run.json', json_encode(['at' => time(), 'step' => $step]));
    file_put_contents($log, '');
    $python = (string)config('tools', 'python', PHP_OS_FAMILY === 'Windows' ? 'python' : 'python3');
    $command = escapeshellarg($python) . ' -X utf8 -u ' . escapeshellarg(FT_ROOT . '/tools/tracker.py') . ' checkout ' . escapeshellarg($step) . ' --fetch > ' . escapeshellarg($log) . ' 2>&1';
    if (PHP_OS_FAMILY === 'Windows') {
        pclose(popen('start "" /B cmd /C "(' . $command . ') & echo FT-END>> ' . escapeshellarg($log) . '"', 'r'));
    } else {
        exec('(' . $command . '; echo FT-END >> ' . escapeshellarg($log) . ') > /dev/null 2>&1 &');
    }
    return ['ok' => true];
}

/** "3.1 MB" */
function checkout_size(int $bytes): string
{
    return $bytes >= 1048576 ? number_format($bytes / 1048576, 1) . ' MB' : number_format(max(1, (int)round($bytes / 1024))) . ' KB';
}
