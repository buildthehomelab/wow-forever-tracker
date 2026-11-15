<?php
// What the website accepts from the original game's database (tools/tracker.py classic -> app/sources.php): trainer
// lines of the right shape, a spell for a quest that casts none, and nothing else, whatever the file says.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$ev = classicdb_evidence(['ev' => [
    'train' => [[12939, 10841, 100000, 0, 129, 240, [], 1], [8696, 13028, 0, 0, 185, 175, [], 1],
                [12939, 10841, 100000, 0, 0, 240, [], 1],          // no skill line: a class spell, not asked here
                ['12939', 10841, 1, 0, 129, 240, [], 1], [12939, 0, 1, 0, 129, 240, [], 1], [12939, 10841, -5, 0, 129, 240, [], 1],
                [12939, 10841, 1, 0, 129, 240, [10840], 1], [12939, 10841, 1, 0, 129, 240, [], 2], [12939, 10841, 1, 0, 129, 240, []], '12939 OR 1=1'],
    'sell' => [[1, 2, 0]], 'drop' => [['npc', 1, 2, 50.0]], 'start' => [['npc', 1, 2]],
], 'left' => ['classic_conversation' => 14, 'classic_silent' => 0, 'report_name_unknown' => 3, 'DROP TABLE x' => 1]]);
check($ev['train'] === [[12939, 10841, 100000, 0, 129, 240, [], 1], [8696, 13028, 0, 0, 185, 175, [], 1]], 'trainer lines: whole numbers, a skill line, no rank it would need');
check($ev['sell'] === [] && $ev['drop'] === [] && $ev['start'] === [] && $ev['end'] === [], 'nothing it does not make: no vendors, drops or quest givers');
check($ev['left'] === ['classic_conversation' => 14], 'only its own reasons are counted');
check(classicdb_evidence([])['train'] === [] && classicdb_evidence(['ev' => 'x'])['train'] === [], 'a result that is no result gives nothing');

$op = fn(array $over = []) => $over + ['table' => 'quest_template', 'columns' => ['ID', 'RewardSpell'], 'match' => ['ID'], 'set' => 'RewardSpell', 'rows' => [[2203, 11453], [2501, 11453]]];
$changes = classicdb_changes(['changes' => [$op(), $op(['set' => 'LogTitle', 'columns' => ['ID', 'LogTitle'], 'rows' => [[2203, 'x']]]), $op(['table' => 'quest_objectives']),
    $op(['rows' => [[2771, 0], [7647, 'x'], [-1, 5], [7648, 23214]]])]]);
check(count($changes) === 2 && $changes[0]['rows'] === [[2203, 11453], [2501, 11453]] && $changes[1]['rows'] === [[7648, 23214]], 'quest changes: the spell cast at the turn-in, and that column only');
check($changes[0]['fill'] === 'RewardSpell' && $changes[0]['set'] === 'RewardSpell' && $changes[0]['db'] === 'world', 'written only where the quest casts nothing yet (a fill, never a replacement)');
check(classicdb_changes([]) === [] && classicdb_changes(['changes' => 'x']) === [], 'no change in a result that has none');

// ---- a creature Classic trains at that is no trainer here becomes one
$lines = [[12939, 10841, 100000, 0, 129, 240, [], 1], [12939, 18630, 150000, 35, 129, 290, [], 1], [8696, 13028, 0, 0, 185, 175, [], 1],
          [1215, 2337, 250, 0, 171, 55, [], 1], [99999, 5, 1, 0, 171, 1, [], 1], [12920, 10841, 100000, 0, 129, 240, [], 1], [4611, 7, 1, 0, 171, 1, [], 1]];
$state = ['trainer' => [1215 => true], 'known' => [12939 => true, 8696 => true, 1215 => true, 12920 => true, 4611 => true],
          'spawned' => [12939 => true, 8696 => true, 1215 => true, 4611 => true], 'taken' => [1004611 => true], 'later' => [18630 => true]];
[$own, $ownLeft, $rest] = classicdb_trainer_rows($lines, $state, 70938);
check($own['trainer'] === [['Id' => 1012939, 'Type' => 2, 'Greeting' => '', 'VerifiedBuild' => 70938], ['Id' => 1008696, 'Type' => 2, 'Greeting' => '', 'VerifiedBuild' => 70938]],
    'a spawned creature that is no trainer gets a list of its own, numbered after the creature');
check($own['creature_trainer'] === [['CreatureID' => 12939, 'TrainerID' => 1012939, 'MenuID' => 0, 'OptionID' => 0], ['CreatureID' => 8696, 'TrainerID' => 1008696, 'MenuID' => 0, 'OptionID' => 0]],
    'and the link to it, as the creature\'s own trainer (no menu, no option)');
check(array_map(fn($r) => [$r['TrainerId'], $r['SpellId'], $r['MoneyCost'], $r['ReqSkillLine'], $r['ReqSkillRank'], $r['ReqLevel']], $own['trainer_spell'])
    === [[1012939, 10841, 100000, 129, 240, 0], [1008696, 13028, 0, 185, 175, 0]], 'its spells with Classic\'s cost, skill and level; a spell of a phase that is not open is not sold yet');
check($rest === [[1215, 2337, 250, 0, 171, 55, [], 1]], 'a creature that is a trainer already keeps its lines for the usual rules');
check($ownLeft === ['trainer_not_on_server' => 1, 'classic_trainer_not_spawned' => 1, 'classic_trainer_number_taken' => 1], 'unknown, not spawned, or its number already used: counted, nothing written');
check(classicdb_trainer_rows([], $state, 70938) === [[], [], []], 'no line, nothing');
check(classicdb_trainer_rows([[12939, 18630, 150000, 35, 129, 290, [], 1]], $state, 70938) === [[], [], []], 'no trainer list for a creature whose only recipe waits for a later phase');

check(isset(SOURCES['classicdb'], SOURCE_MARKS['classicdb']) && source_named('Classic database 2026-11-14') === 'classicdb', 'the source is known by its name in a row\'s comment');
$trust = source_trust('');
check(end($trust) === 'classicdb' && $trust[0] === 'client', 'the last source asked: every other one is trusted before it');
check(str_ends_with(classicdb_pack(), '/data/classicdb/pack.cdbpack'), 'one pack, kept with the tracker\'s data');

ft_test_done();
