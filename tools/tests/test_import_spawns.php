<?php
// When an import's spawn already stands on the server (app/imports.php import_spawn_stands): a holiday's spawn is
// matched farther, since the realm's holiday spawns come from another database that places the same NPC a few yards
// off; the import's own spawns are still told apart at a few yards, so a crowd of the same NPC stays whole.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/imports.php';

// the Love is in the Air seller the realm already had 9.5 yards away, and the Mulgore Burth 6.7 yards away
$server = [[-8682.4, 841.9]];
check(!import_spawn_stands('creature', false, -8691.85, 840.514, $server, []), 'an ordinary spawn 9.5 yards from the same NPC is a new one');
check(import_spawn_stands('creature', true, -8691.85, 840.514, $server, []), 'a holiday spawn 9.5 yards from the same NPC stands already');
check(import_spawn_stands('creature', true, 0.0, 29.0, [[0.0, 0.0]], []), 'a holiday creature is matched up to 30 yards');
check(!import_spawn_stands('creature', true, 0.0, 31.0, [[0.0, 0.0]], []), 'and not beyond');
check(import_spawn_stands('gameobject', true, 0.0, 9.0, [[0.0, 0.0]], []), 'a holiday object is matched up to 10 yards');
check(!import_spawn_stands('gameobject', true, 0.0, 11.0, [[0.0, 0.0]], []), 'and not beyond');
check(import_spawn_stands('gameobject', false, 0.0, 2.0, [[0.0, 0.0]], []), 'an ordinary spawn 2 yards off stands already, as before');
check(!import_spawn_stands('gameobject', false, 0.0, 4.0, [[0.0, 0.0]], []), 'and 4 yards off is a new one, as before');
// a crowd: celebrants the import places 5 yards apart, none of them on the server
check(!import_spawn_stands('creature', true, 0.0, 5.0, [], [[0.0, 0.0]]), 'a holiday crowd keeps its members 5 yards apart');
check(import_spawn_stands('creature', true, 0.0, 1.0, [], [[0.0, 0.0]]), 'but not the same spot twice');

$tables = [
    'game_event_creature' => ['groups' => [['columns' => ['eventEntry', 'guid'], 'rows' => [[8, 12954], [-8, 77], [8, ['@CGUID+', 3]]]]]],
    'game_event_gameobject' => ['groups' => [['columns' => ['eventEntry', 'guid'], 'rows' => [[1, 43526]]]]],
];
$holiday = import_holiday_spawns($tables);
check(isset($holiday['creature']['12954'], $holiday['gameobject']['43526']), 'the spawns linked to an event are a holiday\'s');
check(!isset($holiday['creature']['77']), 'a spawn an event hides is not');
check(isset($holiday['creature']['@CGUID+3']), 'a guid written as a variable is read as the import writes it');
check(import_holiday_spawns([]) === ['creature' => [], 'gameobject' => []], 'an import without events has none');

ft_test_done();
