<?php
// QuestieDB's drops (app/questie.php): its item database, corrections applied as Questie applies them, and the
// chance each row takes.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/questie.php';

$base = "QuestieDB.itemData = [[return {\n"
    . "[25] = {'Worn Shortsword',nil,nil,nil,nil,nil,nil,nil,2,1,0,2,7},\n"
    . "[750] = {'Tough Wolf Meat',{525,238425,238426},nil,nil,nil,nil,nil,nil,1,0,0,12,0},\n"
    . "[772] = {'Large Candle',{40,327,475,476},nil,nil,nil,nil,nil,nil,1,0,0,12,0},\n"
    . "[780] = {'Torn Murloc Fin',{46,732,202060},nil,nil,nil,nil,nil,nil,1,0,0,12,0},\n"
    . "[2320] = {'Coarse Thread',{100},{2843},nil,nil,nil,nil,nil,1,0,0,7,0},\n"
    . "[3000] = {'Kobold\\'s {odd} name',{9},nil,nil,nil,nil,nil,nil,1,0,0,12,0},\n"
    . "}]]\n";
$fixes = "function ForeverItemFixes:Load()\n    local itemKeys = QuestieDB.itemKeys\n    return {\n"
    . "        [750] = { -- Tough Wolf Meat\n            [itemKeys.npcDrops_remove] = {238425,238426},\n        },\n"
    . "        [780] = { -- Torn Murloc Fin\n            [itemKeys.npcDrops_remove] = {202060},\n        },\n"
    . "        [2320] = { -- Coarse Thread\n            [itemKeys.npcDrops] = {},\n        },\n"
    . "        -- [772] = { [itemKeys.npcDrops] = {1}, },\n"
    . "    }\nend\n";
$traces = "function ForeverItemTraces:Load()\n    local itemKeys = QuestieDB.itemKeys\n    return {\n"
    . "        [772] = {\n            [itemKeys.name] = \"Large Candle\",\n            [itemKeys.npcDrops_add] = {476,6000},\n        },\n"
    . "        [190179] = {\n            [itemKeys.name] = \"Avelina's Heart\",\n            [itemKeys.npcDrops_add] = {185333},\n            [itemKeys.objectDrops_add] = {5},\n        },\n"
    . "    }\nend\n";

$drops = questie_drops($base, [$fixes, $traces]);
check(!isset($drops[25]), 'an item nothing drops is left out');
check($drops[750] === ['npc' => [525]], '_remove takes creatures out');
check($drops[772] === ['npc' => [40, 327, 475, 476, 6000]], '_add adds players\' recordings once; a commented-out correction is not applied');
check($drops[780] === ['npc' => [46, 732]], 'a creature a hand fix removes is gone');
check($drops[2320] === ['go' => [2843]], 'an empty plain list means drops from no creature; the chest stays');
check($drops[3000] === ['npc' => [9]], 'a name with an escaped quote and braces is read');
check($drops[190179] === ['npc' => [185333], 'go' => [5]], 'an item only the traces know comes in, with its chest');

$ev = questie_evidence(
    [772 => ['npc' => [40, 327]], 780 => ['npc' => [46]], 2320 => ['go' => [2843]], 999 => ['npc' => [1]], 555 => ['npc' => [2]]],
    [772 => true, 780 => true, 2320 => true, 555 => true],   // in Forever (999 is not)
    [555 => true],                                          // a phase not open yet
    [780 => 12.5],                                          // the server's best chance elsewhere
    [772 => true, 780 => true],                             // a quest asks for them
    40.0);
check($ev['drop'] === [['npc', 40, 772, 40.0], ['npc', 327, 772, 40.0], ['npc', 46, 780, 12.5]], 'a quest item takes the server\'s chance, else the quest chance; any other item without one is left out');
check(isset($ev['quest_drop']['npc:40:772']) && isset($ev['quest_drop']['npc:46:780']), 'a quest item drops only for players on the quest');
check($ev['any_item'] === true, 'not only items nobody can get');
check($ev['left'] === ['questie_item_not_in_forever' => 1, 'questie_phase_not_open' => 1, 'loot_chance_unknown' => 1], 'what is left out is counted');

check(questie_whole(QUESTIE_BASE, $base) && !questie_whole(QUESTIE_BASE, substr($base, 0, 120)), 'a cut item database is not kept');
check(questie_whole(QUESTIE_CORRECTIONS[0], $traces . "return ForeverBaseItem\n"), 'a correction file that hands its module back is whole');
check(questie_whole(QUESTIE_CORRECTIONS[1], $fixes) && !questie_whole(QUESTIE_CORRECTIONS[1], substr($fixes, 0, 60)), 'nor a cut correction file');

$rows = questie_drop_rows(['772' => ['npc' => [40, 327]], 2320 => ['go' => [2843]]]);
check($rows === [['npc', 40, 772, null], ['npc', 327, 772, null], ['go', 2843, 2320, null]], 'a snapshot keeps every drop, with no chance');
check(questie_drops_from_rows($rows) === [772 => ['npc' => [40, 327]], 2320 => ['go' => [2843]]], 'and the drops come back from it as they were');

// ---- who gives and takes each quest (questie_relations): the reviewed delta, the fixes written by hand, the traces
$base = "function ForeverBaseQuest:Load()\n    return {\n        [92100] = { -- Anywhere But Here\n            [questKeys.name] = \"Anywhere But Here\",\n            [questKeys.startedBy] = {{255009}},\n            [questKeys.finishedBy] = {nil, {654121}},\n        },\n        [94359] = { -- Craftsman's Writ\n            [questKeys.startedBy] = {nil, nil, {264159}},\n        },\n        [5] = {\n            [questKeys.startedBy] = {{1,2}},\n        },\n    }\nend\n";
$fixes = "    return {\n        [5] = {\n            [questKeys.startedBy_remove] = {{2}},\n            -- [questKeys.finishedBy] = {{99}},\n        },\n    }\nend\n";
$traces = "    return {\n        [94359] = {\n            [questKeys.finishedBy_add] = {nil,{642497}},\n        },\n        [93572] = {\n            [questKeys.startedBy_add] = {{7363}},\n            [questKeys.finishedBy_add] = {{7363}},\n        },\n    }\nend\n";
$rel = questie_relations([$base, $fixes, $traces]);
check($rel[92100] === ['start' => ['npc' => [255009]], 'end' => ['go' => [654121]]], 'a creature that gives it, an object that takes it: ' . json_encode($rel[92100] ?? null));
check($rel[94359] === ['end' => ['go' => [642497]]], 'an item that starts it is the quest\'s own StartItem, not kept; a trace adds who takes it');
check($rel[5] === ['start' => ['npc' => [1]]], '_remove takes one out; a commented-out field is not applied: ' . json_encode($rel[5] ?? null));
check($rel[93572] === ['start' => ['npc' => [7363]], 'end' => ['npc' => [7363]]], 'traces alone give a quest its giver and ender');
check(questie_relation_rows([7 => ['start' => ['npc' => [1]], 'end' => ['go' => [2]]]]) === ['start' => [['npc', 1, 7]], 'end' => [['go', 2, 7]]], 'as evidence rows');
check(questie_table('{nil, {642497}}') === [null, [642497]] && questie_table('{{1},os.exit()}') === null, 'a Lua table of numbers and nils, nothing else');

ft_test_done();
