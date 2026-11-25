<?php
// Creature templates (app/creaturetemplates.php): the creatures gap links name, the faction picked from Wowhead's
// reaction, and the rows each one gets from Icy Veins' record with Wowhead's Forever page as second witness.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/creaturetemplates.php';

// ---- which creatures gap links name
$gaps = ['items' => [212230 => true, 250176 => true], 'noGiver' => [10 => true], 'noEnder' => [11 => true]];
$links = creature_templates_links([['sell', 213077, 212230], ['drop', 249224, 250176], ['start', 300, 10], ['end', 300, 11], ['sell', 400, 2589], ['end', 0, 11]], $gaps);
check(array_keys($links) === [300, 213077, 249224], 'only creatures a gap link names: ' . implode(',', array_keys($links)));
check($links[300] === ['start' => true, 'end' => true] && $links[213077] === ['sell' => true], 'each with what it is linked by');

// ---- Wowhead's Quick Facts
$quick = ['Level: 30', 'React: [color=q2]A[/color]', 'Faction: [url=/forever/faction=2586/azeroth-commerce-authority]', 'Type: Humanoid'];
check(creature_template_reaction($quick) === ['Alliance' => 'friendly'], 'a side not shown is not guessed');
check(creature_template_reaction(['React: [color=q10]A[/color] [color=q10]H[/color]']) === ['Alliance' => 'hostile', 'Horde' => 'hostile'], 'hostile to both');
check(creature_template_reaction(['React: [color=q]A[/color] [color=q]H[/color]']) === ['Alliance' => 'neutral', 'Horde' => 'neutral'], 'neutral (yellow)');
check(creature_template_reaction(['Level: 30']) === [], 'no reaction line');
check(creature_template_rep_faction($quick) === 2586, 'the reputation faction');
check(creature_template_levels($quick) === [30, 30] && creature_template_levels(['Level: 57 - 58']) === [57, 58] && creature_template_levels(['Level: ??']) === null, 'levels');

// ---- the faction: {template: [faction, alliance, horde, spawned creatures using it]}
$table = [35 => [35, 'friendly', 'friendly', 900], 12 => [72, 'friendly', 'hostile', 300], 11 => [72, 'friendly', 'hostile', 40], 2600 => [2586, 'friendly', 'hostile', 0],
    2601 => [2586, 'friendly', 'friendly', 0], 3388 => [2587, 'hostile', 'friendly', 2], 29 => [76, 'hostile', 'friendly', 250], 14 => [14, 'hostile', 'hostile', 5000]];
check(creature_template_faction(['Alliance' => 'friendly'], 2586, [], $table) === [2600, 'rep_faction'] || creature_template_faction(['Alliance' => 'friendly'], 2586, [], $table) === [2601, 'rep_faction'], 'a template of the reputation faction that fits');
check(creature_template_faction(['Alliance' => 'friendly', 'Horde' => 'hostile'], 2586, [], $table) === [2600, 'rep_faction'], 'both sides must fit');
check(creature_template_faction(['Alliance' => 'hostile', 'Horde' => 'friendly'], 2587, [3388 => 1, 35 => 4], $table) === [3388, 'same_name'], 'a creature of the same name whose faction fits comes first');
check(creature_template_faction(['Alliance' => 'hostile', 'Horde' => 'friendly'], 0, [35 => 4], $table) === [29, 'reaction'], 'one that does not fit is passed over; then the most used that fits');
check(creature_template_faction(['Alliance' => 'hostile', 'Horde' => 'hostile'], 0, [], $table) === [14, 'reaction'], 'hostile to both: the most used hostile template');
check(creature_template_faction(['Alliance' => 'neutral'], 0, [], $table) === [0, 'creature_template_no_faction'], 'nothing fits');
check(creature_template_faction(['Alliance' => 'friendly'], 9999, [], $table) === [0, 'creature_template_no_faction'], 'a reputation faction with no fitting template: none (not the reaction rule)');
check(creature_template_faction([], 2586, [35 => 1], $table) === [0, 'creature_template_no_reaction'], 'no reaction: nothing is picked');

// ---- the rows
$entity = ['id' => 213077, 'name' => 'Elaine Compton', 'flags' => 134217728, 'flags_2' => 0, 'flags_3' => 0, 'type_id' => 7, 'family_id' => null, 'unit_class' => 1,
    'classification' => 0, 'description' => 'Supply Officer', 'difficulty_id' => 262474, 'movement_info_id' => 1693, 'health_multiplier' => 1.05, 'power_multiplier' => 1,
    'required_expansion' => 0, 'health_scaling_expansion' => 0, 'faction_id' => null];
$icy = fn(array $e, array $displays = [['display_id' => 115248, 'scale' => 1, 'probability' => 0, 'order_index' => 0]]) =>
    ['status' => 'found', 'data' => json_encode(['type' => 'npc', 'entity' => $e, 'children' => ['npc_display' => $displays], 'relations' => []])];
$page = fn(array $quick, array $model = [115248], ?string $name = 'Elaine Compton') => ['status' => 'found', 'name' => $name, 'data' => json_encode(['id' => 213077, 'status' => 'ok', 'quick' => $quick, 'model' => $model])];

[$made, $why] = creature_template_rows(213077, ['sell' => true], $icy($entity), $page($quick), $table, [], 71091);
check($why === null && $made['how'] === 'rep_faction', 'a whole, witnessed creature with a reaction gets its rows');
$t = $made['creature_template'][0];
check($t['entry'] === 213077 && $t['name'] === 'Elaine Compton' && $t['subname'] === 'Supply Officer' && $t['type'] === 7 && $t['unit_class'] === 1 && $t['movementId'] === 1693, 'the template from the record');
check($t['faction'] === 2600 && $t['npcflag'] === CREATURE_TEMPLATE_VENDOR && $t['VerifiedBuild'] === 71091, 'faction, vendor flag, build');
$d = $made['creature_template_difficulty'][0];
check($d['HealthModifier'] === 1.05 && $d['CreatureDifficultyID'] === 262474 && $d['TypeFlags'] === 134217728, 'its difficulty row');
check($made['creature_template_model'] === [['CreatureID' => 213077, 'Idx' => 0, 'CreatureDisplayID' => 115248, 'DisplayScale' => 1.0, 'Probability' => 1.0, 'VerifiedBuild' => 71091]], 'its model (probabilities all 0: even)');
check($made['creature_classic_level'] === [['entry' => 213077, 'level_min' => 30, 'level_max' => 30]], 'its level from Wowhead');
[$made] = creature_template_rows(300, ['start' => true, 'end' => true], $icy($entity), $page($quick), $table, []);
check($made['creature_template'][0]['npcflag'] === CREATURE_TEMPLATE_QUESTGIVER, 'a giver or ender is a quest giver');

$reason = fn(?array $i, ?array $p) => creature_template_rows(213077, ['sell' => true], $i, $p, $table, [])[1];
check($reason(null, $page($quick)) === 'creature_template_no_record', 'no record');
check($reason($icy(['name' => ''] + $entity), $page($quick)) === 'creature_template_incomplete', 'no name');
check($reason($icy($entity, []), $page($quick)) === 'creature_template_incomplete', 'no model');
check($reason($icy($entity), null) === 'creature_template_no_witness', 'no Wowhead page');
check($reason($icy($entity), $page($quick, [])) === 'creature_template_no_witness', 'a page without a model');
check($reason($icy($entity), $page($quick, [1])) === 'creature_template_witness_differs', 'another model');
check($reason($icy($entity), $page($quick, [115248], 'Someone Else')) === 'creature_template_witness_differs', 'another name');
check($reason($icy($entity), $page(['Level: ??', 'React: [color=q2]A[/color]'])) === 'creature_template_no_level', 'no level');
check($reason($icy($entity), $page(['Level: 30'])) === 'creature_template_no_reaction', 'no reaction');

// ---- the faction table file
$dir = ft_test_dir();
file_put_contents("$dir/f.json", json_encode(['made' => 1, 'templates' => ['35' => [35, 'friendly', 'friendly', 9], 'bad' => [1]]]));
check(creature_templates_factions("$dir/f.json") === [35 => [35, 'friendly', 'friendly', 9]], 'the table, bad rows dropped');
check(creature_templates_factions("$dir/none.json") === [], 'no table');

ft_test_done();
