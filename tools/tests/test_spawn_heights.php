<?php
// The database mode writes a point when it has a height: one the locator read in the server's maps and vmaps
// ('terrain', whatever the distance to the nearest spawn), else one borrowed from an existing spawn within 15 yards.
// Points the locator wrote before it read the maps have five fields and borrowed their z (app/spawns.php).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/spawns.php';

check(spawn_height_from([1.0, 2.0, 30.5, 4.0, 0.0, 'terrain']) === 'terrain', 'a terrain point says so');
check(spawn_height_from([1.0, 2.0, 30.5, 4.0, 0.0, 'spawn']) === 'spawn', 'a borrowed z says so');
check(spawn_height_from([1.0, 2.0, 30.5, 4.0, 0.0]) === 'spawn', 'an older point (five fields) borrowed its z');
check(spawn_height_from([1.0, 2.0, null, null, 0.0, null]) === null, 'no z, no source');

check(spawn_has_height(30.5, null, 'terrain'), 'a terrain height with no spawn near counts');
check(spawn_has_height(30.5, 19.0, 'terrain'), 'a terrain height with the nearest spawn 19 yards away counts');
check(spawn_has_height(30.5, 12.0, 'spawn'), 'a spawn within 15 yards lends its height');
check(!spawn_has_height(30.5, 19.0, 'spawn'), 'a spawn 19 yards away is too far to lend one');
check(!spawn_has_height(null, null, null), 'no z at all is left out');

ft_test_done();
