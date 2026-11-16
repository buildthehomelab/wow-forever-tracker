<?php
// VMaNGOS as a source of the original game's database (tools/vmangos_pack.py -> app/sources.php): its own name, its
// own pack, its place just above the Classic database, and holiday cards in the realm's own event numbers.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

check(isset(SOURCES['vmangos'], SOURCE_MARKS['vmangos']) && source_named('VMaNGOS 2026-11-16') === 'vmangos', 'the source is known by its name in a row\'s comment');
check(source_named('Doctor: learn 10841 (VMaNGOS)') === 'vmangos' && source_named('Doctor: learn 10841 (Classic database)') === 'classicdb', 'a conversation line names the database it came from');
$trust = source_trust('');
check(array_search('vmangos', $trust, true) === array_search('classicdb', $trust, true) - 1 && array_search('wowheadclassic', $trust, true) < array_search('vmangos', $trust, true),
    'VMaNGOS comes just before the Classic database, after Wowhead Classic');
check(source_may_change('vmangos', 'classicdb', $trust) === 'yes' && source_may_change('classicdb', 'vmangos', $trust) === 'trusted',
    'VMaNGOS may change what the Classic database wrote, not the other way round');
check(source_trust('wowhead,classicdb') !== [] && in_array('vmangos', source_trust('wowhead,classicdb'), true), 'a [sources] trust that leaves it out still asks it, in the default order');

check(str_ends_with(classicdb_pack('vmangos'), '/data/vmangos/pack.cdbpack') && str_ends_with(classicdb_pack(), '/data/classicdb/pack.cdbpack'), 'one pack per source');
$threw = false; try { classicdb_pack('../etc'); } catch (InvalidArgumentException $e) { $threw = true; }
check($threw, 'no pack path for an unknown source');
check(classicdb_pack_source(['source' => 'VMaNGOS']) === 'vmangos' && classicdb_pack_source(['source' => 'cmangos classic-db']) === 'classicdb' && classicdb_pack_source([]) === 'classicdb',
    'a pack names its source; an old pack without one is classic-db\'s');

// holidays: the realm's calendar is VMaNGOS's, so a VMaNGOS event is the realm's own number
$ev = classicdb_holiday_events('fishing', 'vmangos');
check(array_keys($ev) === [14, 15, 40] && $ev[40]['event'] === 40, 'the fishing contest: VMaNGOS 14, 15, 40 are the realm\'s 14, 15, 40');
check(array_keys(classicdb_holiday_events('fishing')) === [14, 15, 34], 'classic-db keeps its own numbers');
check(array_keys(classicdb_holiday_events('harvest', 'vmangos')) === [11] && array_keys(classicdb_holiday_events('noblegarden', 'vmangos')) === [28]
    && array_keys(classicdb_holiday_events('newyear', 'vmangos')) === [34], 'Harvest Festival 11, Noblegarden 28, New Year\'s Eve 34 in VMaNGOS as on the realm');
check(isset(classicdb_holiday_events('darkmoon', 'vmangos')[4]['create']), 'the Faire\'s events are still made where the realm lacks them');
$templates = ['npc' => [15077 => true], 'go' => []];
$spawn = ['creatures' => [[77, 15077, 0, 1, 2, 3, 0, 300, 0.0, 0]], 'objects' => []];
[$f, $fl] = classicdb_holiday_rows('fishing', ['14' => $spawn, '15' => $spawn, '40' => $spawn], [14 => 'Announce', 15 => 'Tournament', 40 => 'The Crew'], $templates, 70938, 'vmangos');
check(count($f['creature']) === 1 && array_column($f['game_event_creature'], 'eventEntry') === [14, 15, 40] && $fl === [], 'a VMaNGOS pack\'s spawns link to the same events');
[$n, $nl] = classicdb_holiday_rows('fishing', ['34' => $spawn], [40 => 'The Crew'], $templates, 70938, 'vmangos');
check(!isset($n['creature']) && ($nl['classic_holiday_no_spawns'] ?? 0) === 3, 'VMaNGOS\' event 34 is New Year\'s Eve, never the fishing crew');

ft_test_done();
