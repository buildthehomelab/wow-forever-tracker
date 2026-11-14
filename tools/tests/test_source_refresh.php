<?php
// Rows the server already has, measured again by a source (app/sources.php): whose word counts, which rows a source
// may change, and when a drop chance has moved enough to be worth a change.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

// ---- the order of trust
check(source_trust('') === ['wowhead', 'norgannondb', 'icyveins', 'eglink', 'foreverdb', 'atlasloot'], 'by default: Wowhead, Questie\'s data (NorgannonDB), Icy Veins, then the others');
check(source_trust('icyveins, wowhead') === ['icyveins', 'wowhead', 'norgannondb', 'eglink', 'foreverdb', 'atlasloot'], '[sources] trust goes first; the sources it leaves out follow in the default order');
check(source_trust('Wowhead, Questie, nonsense, icyveins')[1] === 'norgannondb', '"questie" is NorgannonDB, and a name that is no source is ignored');

// ---- who wrote a row
check(source_named('Icy Veins 2026-11-14') === 'icyveins', 'a loot row\'s Comment names its source');
check(source_named('Forge #16: NorgannonDB a2a5bcf1, seen by a live Forever recording') === 'norgannondb', 'so does a ledger note');
check(source_named('AtlasLoot 1.3.9') === 'atlasloot' && source_named('EG Link ea970da0') === 'eglink' && source_named('ForeverDB.net 2026-11-14.852e11f0') === 'foreverdb', 'every source by its name');
check(source_named('NorgannonDB a2a5bcf1 (chance: Icy Veins)') === 'norgannondb', 'the first source named is the one that brought the row');
check(source_named('') === null && source_named(null) === null && source_named('Kobold Vermin') === null, 'a row no import wrote names none');

// ---- which rows a source may change
$trust = source_trust('');
check(source_may_change('icyveins', 'icyveins', $trust) === 'yes', 'its own rows');
check(source_may_change('icyveins', 'atlasloot', $trust) === 'yes' && source_may_change('icyveins', 'eglink', $trust) === 'yes', 'the rows of a less trusted source');
check(source_may_change('icyveins', 'norgannondb', $trust) === 'trusted', 'not the rows of a more trusted one');
check(source_may_change('icyveins', null, $trust) === 'core', 'not the rows no import brought (the core\'s own data, a hand fix)');
check(source_may_change('atlasloot', 'icyveins', $trust) === 'trusted', 'the least trusted changes only its own');

// ---- when a chance has moved
check(!source_chance_moved(4.35, 4.35), 'the same chance has not moved');
check(!source_chance_moved(4.35, 4.6), 'nor one within a tenth of what it was: a few more corpses counted');
check(source_chance_moved(4.35, 2.1) && source_chance_moved(2.1, 4.35), 'a chance that halved or doubled has');
check(!source_chance_moved(0.09, 0.12), 'a tiny chance that moved by less than 0.05 points has not');
check(source_chance_moved(0.09, 0.2), 'one that more than doubled has');
check(source_chance_moved(50.0, 56.0, 10.0) && !source_chance_moved(50.0, 54.0, 10.0), 'the tolerance is a share of the old chance');
check(source_chance_moved(50.0, 54.0, 5.0), 'and can be set ([sources] chance_tolerance)');

// ---- what an import proposes
$current = [
    'creature_loot_template:780:213127' => ['Chance' => 7.75, 'Comment' => 'Icy Veins 2026-11-14'],     // ours: moved
    'creature_loot_template:939:216616' => ['Chance' => 12.39, 'Comment' => 'Icy Veins 2026-11-14'],    // ours: hardly moved
    'creature_loot_template:588:2589' => ['Chance' => 30.0, 'Comment' => 'Linen Cloth'],                 // the core's: differs
    'creature_loot_template:5357:18956' => ['Chance' => 100.0, 'Comment' => 'NorgannonDB a2a5bcf1'],     // a more trusted source's: differs
    'gameobject_loot_template:1421:268416' => ['Chance' => 2.38, 'Comment' => 'AtlasLoot 1.3.9'],        // a less trusted source's: moved
];
$measured = [
    'creature_loot_template:780:213127' => 5.2,
    'creature_loot_template:939:216616' => 12.8,
    'creature_loot_template:588:2589' => 42.0,
    'creature_loot_template:5357:18956' => 80.0,
    'gameobject_loot_template:1421:268416' => 1.1049,
    'creature_loot_template:1:1' => 50.0,          // not on the server: the import's other half adds what is missing
    'creature_loot_template:2:2' => 0.0,           // no chance known
];
[$rows, $left] = source_drop_changes('icyveins', $measured, $current + ['creature_loot_template:2:2' => ['Chance' => 5.0, 'Comment' => 'Icy Veins']], 10.0, $trust);
check($rows === ['creature_loot_template' => [[780, 0, 213127, 5.2]], 'gameobject_loot_template' => [[1421, 0, 268416, 1.1]]], 'its own row and a less trusted source\'s take the new chance, rounded as an import writes it');
check($left === ['drop_same' => 1, 'drop_differs_core' => 1, 'drop_differs_trusted' => 1], 'what has not moved, the core\'s row and the more trusted source\'s row are counted and left alone');
[$rows] = source_drop_changes('atlasloot', $measured, $current, 10.0, $trust);
check($rows === ['gameobject_loot_template' => [[1421, 0, 268416, 1.1]]], 'a less trusted source changes only its own row');
[$rows, $left] = source_drop_changes('icyveins', ['creature_loot_template:780:213127' => 250.0], $current, 10.0, $trust);
check($rows === ['creature_loot_template' => [[780, 0, 213127, 100.0]]], 'a chance is never above 100');

// ---- the statement a change becomes (app/forge.php)
require_once FT_APP . '/forge.php';
check(forge_same_value(4.35, 4.3500001) && !forge_same_value(4.35, 4.36), 'two decimal numbers are the same within a rounding step');
check(forge_same_value(5, '5') && !forge_same_value(5, 6), 'whole numbers and text are compared as written');
$ops = [];
forge_merge($ops, ['db' => 'world', 'table' => 'creature_loot_template', 'columns' => ['Entry', 'ItemType', 'Item', 'Chance'], 'match' => ['Entry', 'ItemType', 'Item'], 'set' => 'Chance', 'rows' => [[780, 0, 213127, 5.2], [780, 0, 213127, 9.9]]]);
$op = reset($ops);
check(count($ops) === 1 && $op['set'] === 'Chance' && count($op['rows']) === 1 && $op['duplicates'] === 1, 'a "set" operation is merged like the others: one row a key');
$ops = [];
forge_merge($ops, ['db' => 'world', 'table' => 'creature_loot_template', 'columns' => ['Entry', 'Item', 'Chance'], 'match' => ['Entry', 'Chance'], 'set' => 'Chance', 'rows' => [[1, 2, 3.0]]]);
forge_merge($ops, ['db' => 'world', 'table' => 'creature_loot_template', 'columns' => ['Entry', 'Chance', 'Item'], 'match' => ['Entry'], 'set' => 'Chance', 'rows' => [[1, 3.0, 2]]]);
check($ops === [], 'the column it sets is the last one and never part of the key: anything else is refused');

ft_test_done();
