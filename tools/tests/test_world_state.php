<?php
// Spawn rows go straight into the database only while the worldserver is stopped (it hands out spawn ids itself). The
// tracker asks the remote console's port; with no console configured it cannot tell, and must not take "no answer" for
// "stopped": the administrator then has to confirm it (app/spawns.php).
require __DIR__ . '/helpers.php';
ft_test_boot("[site]\npublic = 1\n[console]\nhost = \"\"\nport = 3443\n[database]\nhost = \"127.0.0.1\"\nport = 1\n");
require FT_APP . '/spawns.php';

check(spawn_world_state() === 'unknown', 'no console configured: the worldserver\'s state is unknown');
check(spawn_world_running() === false, 'which is not "running"');

// refused before anything is planned or written (this test has no database: going further would fail)
$out = spawn_apply_database([['kind' => 'npc', 'entry' => 1]]);
check($out['ok'] === false && !empty($out['confirm_stopped']) && str_contains($out['message'], 'stopped'), 'the database mode refuses without the confirmation, and asks for it');
$out = spawn_apply_database([['kind' => 'npc', 'entry' => 1]], false);
check($out['ok'] === false && !empty($out['confirm_stopped']), 'an explicit "not confirmed" is refused the same way');

ft_test_done();
