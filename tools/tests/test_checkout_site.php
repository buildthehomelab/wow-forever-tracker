<?php
// The website's side of a checkout (app/checkout.php): which names are steps, which files are whole, the run's state.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/checkout.php';

$dir = ft_test_dir();

// ---- a step's name
check(checkout_step('70707') === '70707', 'a build');
check(checkout_step('70938+1') === '70938+1', 'a hotfix update');
foreach (['', 'latest', '70938+', '+1', '70938 1', '../70938', '70938;rm', '70938+1+2', "70938\n"] as $bad)
    check(checkout_step($bad) === null, 'not a step: ' . json_encode($bad));

// ---- whole files only: a file without its manifest, or with another step's, is not offered
$write = function (string $step, ?string $manifestStep) use ($dir) {
    file_put_contents("$dir/hotfixes-$step.sql", "-- $step\n");
    if ($manifestStep !== null) file_put_contents("$dir/hotfixes-$step.sql.json", json_encode(['step' => $manifestStep, 'tables' => []]));
};
$write('70707', '70707');
$write('70888', null);
$write('70938+1', '70938');
file_put_contents("$dir/hotfixes-evil.sql", 'x');
file_put_contents("$dir/hotfixes-evil.sql.json", json_encode(['step' => 'evil']));
$files = checkout_files($dir);
check(array_map('strval', array_keys($files)) === ['70707'], 'only the file with its own manifest: ' . json_encode(array_keys($files)));
check(checkout_file('70707', $dir) === "$dir/hotfixes-70707.sql", 'its path');
check(checkout_file('70888', $dir) === null && checkout_file('../x', $dir) === null, 'nothing else is handed out');

// ---- the run
check(checkout_status($dir)['running'] === false, 'nothing ran yet');
file_put_contents("$dir/run.json", json_encode(['at' => time(), 'step' => '70707']));
file_put_contents("$dir/run.log", "10:00 client: reading 49 more table(s)\n");
$s = checkout_status($dir);
check($s['running'] && $s['step'] === '70707', 'running');
file_put_contents("$dir/run.log", "10:01 checkout 70707: 69 tables, 12 records\nFT-END\n", FILE_APPEND);
$s = checkout_status($dir);
check(!$s['running'] && !$s['failed'] && !str_contains($s['log'], 'FT-END'), 'finished well');
file_put_contents("$dir/run.log", "Traceback (most recent call last):\nFT-END\n");
check(checkout_status($dir)['failed'], 'finished without its last line: failed');
file_put_contents("$dir/run.log", "10:00 client: reading\n");
touch("$dir/run.log", time() - 3600);
file_put_contents("$dir/run.json", json_encode(['at' => time() - 3600, 'step' => '70707']));
check(!checkout_status($dir)['running'], 'a run silent for an hour died: the buttons are free again');

check(checkout_size(2578360) === '2.5 MB' && checkout_size(10) === '1 KB', 'sizes');

ft_test_done();
