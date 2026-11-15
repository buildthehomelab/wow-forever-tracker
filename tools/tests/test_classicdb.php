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

// ---- conversation lines: the line, its conditions, the SmartAI that casts the spell
check(classicdb_talk_line(['npc', 14338, ' Please teach me ', 22813, 22814, [['skill', 197, 275], ['quest', 5518], ['lacks', 22813]]])
    === ['npc', 14338, 'Please teach me', 22813, 22814, [['skill', 197, 275], ['quest', 5518], ['lacks', 22813]]], 'a line of the right shape, its text trimmed');
foreach ([['pc', 1, 'x', 2, 3, []], ['npc', 1, '', 2, 3, []], ['npc', 1, "a\nb", 2, 3, []], ['npc', 1, 'x', 2, 3, [['rep', 529, 9]]], ['npc', 1, 'x', 2, 3, [['drop', 1]]],
          ['npc', 1, 'x', 2, 3, [['skill', 197]]], ['npc', '1', 'x', 2, 3, []], ['npc', 1, 'x', 2, 3]] as $bad) check(classicdb_talk_line($bad) === null, 'refused: ' . json_encode($bad));

$c = classicdb_conditions([['rep', 529, 6], ['skill', 197, 300], ['rep', 529, 7], ['level', 40], ['knows', 20222], ['lacks', 28208]], 1016365, 0, 'Omarion: learn 28208');
check(array_map(fn($r) => [$r['SourceTypeOrReferenceId'], $r['SourceGroup'], $r['SourceEntry'], $r['ConditionTypeOrReference'], $r['ConditionValue1'], $r['ConditionValue2'], $r['NegativeCondition']], $c)
    === [[15, 1016365, 0, 5, 529, 192, 0], [15, 1016365, 0, 7, 197, 300, 0], [15, 1016365, 0, 5, 529, 128, 0], [15, 1016365, 0, 27, 40, 3, 0], [15, 1016365, 0, 25, 20222, 0, 0], [15, 1016365, 0, 25, 28208, 0, 1]],
    'conditions: Revered or higher is a mask of ranks 6 and 7, Exalted of 7; a level or higher; a spell known, or not');
check(classicdb_conditions([['drop', 1]], 1, 0, '') === null, 'a term it cannot write: no rows at all');

$knot = ['npc', 14338, 'Please teach me how to make a Gordok Ogre Suit.', 22813, 22814, [['skill', 197, 275], ['quest', 5518], ['lacks', 22813]]];
$knot2 = ['npc', 14338, 'Please teach me how to make a Gordok Ogre Suit!', 22815, 22816, [['skill', 165, 275], ['quest', 5518], ['lacks', 22815]]];
$journal = ['go', 180794, 'Decipher the pattern and learn its content.', 26086, 26095, [['skill', 197, 280], ['lacks', 26086]]];
$gloom = ['npc', 9037, "I have payed your price, Gloom'rel.", 14891, 14894, [['quest', 4083], ['skill', 186, 230], ['lacks', 14891]]];
$state = ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => '', 'menus' => [5667], 'options' => [5667 => [0 => 'So, I found this shackle key...', 1 => 'Why should I bother']], 'smart' => -1],
          'go:180794' => ['known' => true, 'spawned' => true, 'type' => 2, 'script' => '', 'ai' => '', 'menus' => [], 'smart' => 4],
          'npc:9037' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => '', 'menus' => [1945], 'smart' => -1]];
[$rows, $ops, $left] = classicdb_talk_rows([$knot, $knot2, $journal, $gloom], $state, 70938, ['npc' => ['14338' => 'Knot Thimblejack'], 'go' => ['180794' => 'Journal of Jandice Barov']]);
check(array_map(fn($r) => [$r['MenuID'], $r['OptionID'], $r['OptionText']], $rows['gossip_menu_option'])
    === [[5667, 2, $knot[2]], [5667, 3, $knot2[2]], [2180794, 0, $journal[2]]], 'lines after the ones the conversation has; an object without one gets a menu of its own');
check(!isset($rows['creature_template_gossip']), 'Knot keeps his own conversation: no new one');
$smart = array_map(fn($r) => [$r['entryorguid'], $r['source_type'], $r['id'], $r['event_type'], $r['event_param1'], $r['event_param2'], $r['action_type'], $r['action_param1'], $r['target_type']], $rows['smart_scripts']);
check($smart === [[14338, 0, 0, 62, 5667, 2, 134, 22814, 7], [14338, 0, 1, 62, 5667, 2, 72, 0, 7], [14338, 0, 2, 62, 5667, 3, 134, 22816, 7], [14338, 0, 3, 62, 5667, 3, 72, 0, 7],
                  [180794, 1, 5, 62, 2180794, 0, 134, 26095, 7], [180794, 1, 6, 62, 2180794, 0, 72, 0, 7]],
    'SmartAI: picking the line makes the player cast the learn spell, then closes the conversation; ids after the ones the creature or object has');
check(count($rows['conditions']) === 8 && $rows['conditions'][0]['SourceGroup'] === 5667 && $rows['conditions'][0]['SourceEntry'] === 2 && str_contains($rows['conditions'][0]['Comment'], 'Knot Thimblejack'),
    'conditions on each line, named after who speaks');
$byOp = []; foreach ($ops as $op) $byOp[$op['table'] . '.' . $op['set']] = [$op['rows'], $op['fill'] ?? null, $op['bits'] ?? null];
check($byOp['creature_template.ScriptName'] === [[[9037, 'boss_gloomrel']], 'ScriptName', null], "Gloom'rel gets the core's script, not SmartAI");
check($byOp['gameobject_template.Data3'] === [[[180794, 2180794]], 'Data3', null], 'the object opens its new conversation');
check($byOp['creature_template.AIName'] === [[[14338, 'SmartAI']], 'AIName', null] && $byOp['gameobject_template.AIName'] === [[[180794, 'SmartGameObjectAI']], 'AIName', null], 'they run SmartAI (written only where they ran nothing)');
check($byOp['creature_template.npcflag'] === [[[14338, 1]], null, 'npcflag'], 'and players can talk to the creature');
check($left === [], 'nothing left out');

$cases = [
    ['npc:14338' => ['known' => true]] + $state, 'classic_talk_not_spawned',
    ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => 'npc_knot', 'ai' => '']] + $state, 'classic_talk_other_script',
    ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => 'NullCreatureAI']] + $state, 'classic_talk_other_ai',
    ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => '', 'menus' => [5667, 5668]]] + $state, 'classic_talk_several_menus',
    ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => '', 'menus' => [5667], 'shared' => [5667 => true]]] + $state, 'classic_talk_menu_shared',
    ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => '', 'menus' => [], 'taken' => [1014338 => true]]] + $state, 'classic_talk_menu_number_taken',
    ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => 'SmartAI', 'menus' => [5667], 'options' => [5667 => [4 => $knot[2]]]]] + $state, 'classic_talk_known',
];
for ($i = 0; $i < count($cases); $i += 2) {
    [, , $l] = classicdb_talk_rows([$knot], $cases[$i], 70938);
    check($l === [$cases[$i + 1] => 1], 'left out: ' . $cases[$i + 1]);
}
[$r2, $o2] = classicdb_talk_rows([$knot], ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => 'SmartAI', 'menus' => [], 'smart' => 9]], 70938);
check($r2['creature_template_gossip'] === [['CreatureID' => 14338, 'MenuID' => 1014338, 'VerifiedBuild' => 70938]] && $r2['gossip_menu_option'][0]['MenuID'] === 1014338 && $r2['smart_scripts'][0]['id'] === 10,
    'a creature without a conversation gets one of its own; it already runs SmartAI, so its AI is left as it is');
check(!in_array('creature_template.AIName', array_map(fn($op) => $op['table'] . '.' . $op['set'], $o2), true), 'no AI change where SmartAI already runs');
[, $o3, $l3] = classicdb_talk_rows([$gloom], ['npc:9037' => ['known' => true, 'spawned' => true, 'script' => 'boss_gloomrel', 'ai' => '']], 70938);
check($o3 === [] && $l3 === ['classic_talk_known' => 1], "Gloom'rel with his script already: nothing to write");
// Gloom'rel on Everlake runs SmartAI (his challenge) and no script: he gets the SmartAI line in his conversation
[$r4, $o4, $l4] = classicdb_talk_rows([$gloom], ['npc:9037' => ['known' => true, 'spawned' => true, 'script' => '', 'ai' => 'SmartAI', 'menus' => [1945],
    'options' => [1945 => [0 => 'Tell me more', 1 => 'Challenge me']], 'smart' => 6]], 70938);
check(array_map(fn($r) => [$r['MenuID'], $r['OptionID']], $r4['gossip_menu_option']) === [[1945, 2]] && $r4['smart_scripts'][0]['id'] === 7
    && $r4['smart_scripts'][0]['action_param1'] === 14894 && $l4 === [], "Gloom'rel running SmartAI gets the SmartAI line after his own, not the core's script");
check(!in_array('creature_template.ScriptName', array_map(fn($op) => $op['table'] . '.' . $op['set'], $o4), true) && !in_array('creature_template.AIName', array_map(fn($op) => $op['table'] . '.' . $op['set'], $o4), true),
    "his script and AI are left as they are");
// the core's own Classic scripts: counted apart, whether they teach or need the core fixed
foreach (['classic_mob_craftsman_omarion' => 'classic_talk_core_teaches', 'classic_npc_knot_thimblejack' => 'classic_talk_core_broken', 'npc_engineering_tele_trinket' => 'classic_talk_core_broken'] as $name => $why) {
    [, , $l5] = classicdb_talk_rows([$knot], ['npc:14338' => ['known' => true, 'spawned' => true, 'script' => $name, 'ai' => '']], 70938);
    check($l5 === [$why => 1], "a line of a creature run by $name: $why");
}
[, , $l6] = classicdb_talk_rows([$journal], ['go:180794' => ['known' => true, 'spawned' => true, 'type' => 2, 'script' => 'classic_go_field_repair_bot_74A', 'ai' => '']], 70938);
check($l6 === ['classic_talk_core_teaches' => 1], 'an object run by a teaching core script too');

check(isset(SOURCES['classicdb'], SOURCE_MARKS['classicdb']) && source_named('Classic database 2026-11-14') === 'classicdb', 'the source is known by its name in a row\'s comment');
$trust = source_trust('');
check(end($trust) === 'classicdb' && $trust[0] === 'client', 'the last source asked: every other one is trusted before it');
check(str_ends_with(classicdb_pack(), '/data/classicdb/pack.cdbpack'), 'one pack, kept with the tracker\'s data');

ft_test_done();
