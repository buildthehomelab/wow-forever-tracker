<?php
// When an import's spawn already stands on the server (app/imports.php import_spawn_stands): a holiday's spawn is
// matched farther, since the realm's holiday spawns come from another database that places the same NPC a few yards
// off, but only against a server spawn there while the holiday runs (all year, or brought in by the same event); the
// import's own spawns are still told apart at a few yards, so a crowd of the same NPC stays whole.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/imports.php';
require_once FT_APP . '/datarepo.php';

// the Love is in the Air seller the realm already had 9.5 yards away, and the Mulgore Burth 6.7 yards away
$server = [[-8682.4, 841.9, 1]];
check(!import_spawn_stands('creature', null, -8691.85, 840.514, $server, []), 'an ordinary spawn 9.5 yards from the same NPC is a new one');
check(import_spawn_stands('creature', [8], -8691.85, 840.514, $server, []), 'a holiday spawn 9.5 yards from the same NPC of all year stands already');
check(import_spawn_stands('creature', [8], 0.0, 29.0, [[0.0, 0.0, 1]], []), 'a holiday creature is matched up to 30 yards');
check(!import_spawn_stands('creature', [8], 0.0, 31.0, [[0.0, 0.0, 1]], []), 'and not beyond');
check(import_spawn_stands('gameobject', [8], 0.0, 9.0, [[0.0, 0.0, 1]], []), 'a holiday object is matched up to 10 yards');
check(!import_spawn_stands('gameobject', [8], 0.0, 11.0, [[0.0, 0.0, 1]], []), 'and not beyond');
check(import_spawn_stands('gameobject', null, 0.0, 2.0, [[0.0, 0.0, 1]], []), 'an ordinary spawn 2 yards off stands already, as before');
check(!import_spawn_stands('gameobject', null, 0.0, 4.0, [[0.0, 0.0, 1]], []), 'and 4 yards off is a new one, as before');
// a crowd: celebrants the import places 5 yards apart, none of them on the server
check(!import_spawn_stands('creature', [1], 0.0, 5.0, [], [[0.0, 0.0]]), 'a holiday crowd keeps its members 5 yards apart');
check(import_spawn_stands('creature', [1], 0.0, 1.0, [], [[0.0, 0.0]]), 'but not the same spot twice');

// the same fireworks over Booty Bay at Midsummer (event 1) and on New Year's Eve (34)
$fireworks = [[-14360.7, 493.6, 77]];
check(!import_spawn_stands('gameobject', [34], -14360.7, 493.6, $fireworks, [], [77 => [1]]), 'another holiday\'s spawn at the very spot is not this holiday\'s');
check(import_spawn_stands('gameobject', [34], -14360.7, 493.6, $fireworks, [], [77 => [34]]), 'the same holiday\'s is');
check(import_spawn_stands('gameobject', [34], -14360.7, 493.6, $fireworks, [], [77 => [1, 34]]), 'and one that both bring in is');
check(!import_spawn_stands('gameobject', [34], -14360.7, 493.6, $fireworks, [], [77 => [-34]]), 'one of all year the holiday hides is not');
check(import_spawn_stands('gameobject', [34], -14360.7, 493.6, $fireworks, [], [77 => [-12]]), 'one of all year another event hides is');
check(import_spawn_stands('gameobject', null, -14360.7, 493.6, $fireworks, [], [77 => [1]]), 'an ordinary spawn still takes any spawn at its spot');
check(import_spot_shares([34], [34], true) && !import_spot_shares([34], [], true) && !import_spot_shares([34], [1], true), 'a holiday moves only a spawn its own event brings in');

$tables = [
    'game_event_creature' => ['groups' => [['columns' => ['eventEntry', 'guid'], 'rows' => [[8, 12954], [-8, 77], [8, ['@CGUID+', 3]]]]]],
    'game_event_gameobject' => ['groups' => [['columns' => ['eventEntry', 'guid'], 'rows' => [[1, 43526]]]]],
];
$holiday = import_holiday_spawns($tables);
check(($holiday['creature']['12954'] ?? null) === [8] && ($holiday['gameobject']['43526'] ?? null) === [1], 'the spawns linked to an event are a holiday\'s, with their events');
check(!isset($holiday['creature']['77']), 'a spawn an event hides is not');
check(isset($holiday['creature']['@CGUID+3']), 'a guid written as a variable is read as the import writes it');
check(import_holiday_spawns([]) === ['creature' => [], 'gameobject' => []], 'an import without events has none');

// the world data export asks the same of the server's spawn
check(datarepo_same_event('gameobject', []) === '', 'an ordinary export block has no event condition');
$sql = datarepo_same_event('gameobject', [34, 34, -2]);
check(str_contains($sql, '`game_event_gameobject`') && str_contains($sql, 'IN (34)') && str_contains($sql, 'IN (-34)') && !str_contains($sql, '-2'), 'a holiday block names its events and the events hiding them');

ft_test_done();
