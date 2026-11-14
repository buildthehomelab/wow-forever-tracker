<?php
// The home page's line on what a newer client build added (app/layout.php): one resource or many, none unknown or some.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/layout.php';

check(home_added_since(0, 0) === 'No tracked resource was added since.', 'nothing added');
check(home_added_since(1, 0) === 'The server’s data already knows the one resource added since.', 'one added and known: no "1 resources"');
check(home_added_since(1, 1) === 'The one resource added since is unknown to the server’s data.', 'one added and unknown');
check(home_added_since(5252, 0) === 'The server’s data already knows the ' . number(5252) . ' resources added since.', 'many added, all known');
check(home_added_since(12, 1) === 'Of the 12 resources added since, one is unknown to the server’s data.', 'many added, one unknown: no "1 are"');
check(home_added_since(12, 7) === 'Of the 12 resources added since, 7 are unknown to the server’s data.', 'many added, several unknown');

ft_test_done();
