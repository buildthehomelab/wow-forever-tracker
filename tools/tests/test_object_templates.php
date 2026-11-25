<?php
// Object templates (app/objecttemplates.php): the objects gap links name, and the gameobject_template row each one
// gets from Icy Veins' record with Wowhead's Forever page as the second witness, or the reason it gets none.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/objecttemplates.php';

// ---- which objects gap links name
$gaps = ['items' => [209848 => true, 226417 => true], 'noGiver' => [78088 => true], 'noEnder' => [94359 => true]];
$facts = [
    ['drop', 409717, 209848],    // drops a gap item
    ['drop', 409717, 209848],    // the same link from a second source
    ['drop', 457089, 226417],
    ['start', 409289, 78088],    // gives a quest without a giver
    ['end', 642497, 94359],      // takes a quest without an ender
    ['drop', 500000, 2589],      // drops an item players can already get
    ['start', 500001, 94359],    // gives a quest that has a giver (it lacks only its ender)
    ['end', 0, 94359],           // no object
];
$links = object_templates_links($facts, $gaps);
check(array_keys($links) === [409289, 409717, 457089, 642497], 'only objects that a gap link names: ' . implode(',', array_keys($links)));
check($links[409717] === ['drop:209848'], 'the same link from two sources is one link');
check($links[642497] === ['end:94359'], 'an ender of a quest without an ender is a link');
check(object_templates_links([['drop', 409717, 209848]], []) === [], 'no gaps: no links');

// ---- a row from Icy Veins' record, witnessed by Wowhead's page (record shapes as the answers table keeps them)
$props = array_fill(0, 35, 0);
$props[0] = 93; $props[1] = 119763; $props[20] = 4096;
$entity = ['product' => 'wowf', 'id' => 409717, 'name' => 'Scrolls', 'type_id' => 3, 'display_id' => 164, 'cursor_name' => null, 'content_tuning_id' => 5841,
    'lock_id' => 93, 'gossip_id' => null, 'scale' => 2, 'cast_bar_caption' => null, 'props' => $props];
$icy = fn(array $e, string $status = 'found') => ['status' => $status, 'data' => json_encode(['type' => 'gameobject', 'id' => $e['id'] ?? 0, 'entity' => $e, 'children' => [], 'relations' => []])];
$page = fn(array $model, ?string $name = 'Scrolls', string $status = 'found') => ['status' => $status, 'name' => $name, 'data' => json_encode(['id' => 409717, 'status' => 'ok', 'model' => $model])];

[$row, $why] = object_template_row(409717, $icy($entity), $page([164]), 70888);
check($why === null && is_array($row), 'a whole record with an agreeing page gives a row');
check($row['entry'] === 409717 && $row['type'] === 3 && $row['displayId'] === 164 && $row['name'] === 'Scrolls' && $row['size'] === 2.0, 'type, display, name and scale come from the record');
check($row['Data0'] === 93 && $row['Data1'] === 119763 && $row['Data20'] === 4096 && $row['Data34'] === 0, 'props[n] is Data<n>');
check(count(array_filter(array_keys($row), fn($k) => preg_match('/^Data\d+$/', $k))) === 35, 'all 35 Data columns are on the row');
check($row['ContentTuningId'] === 5841 && $row['VerifiedBuild'] === 70888 && $row['IconName'] === '' && $row['castBarCaption'] === '', 'tuning, build, and empty text where the record has none');

// null content_tuning_id and lock_id: the object has none
[$row] = object_template_row(409289, $icy(['content_tuning_id' => null, 'lock_id' => null] + $entity), $page([164]));
check($row && $row['ContentTuningId'] === 0, 'a null tuning is 0');
// 34 props: Data34 is 0
[$row] = object_template_row(409717, $icy(['props' => array_slice($props, 0, 34)] + $entity), $page([164]));
check($row && $row['Data33'] === 0 && $row['Data34'] === 0, 'a record of 34 props fills Data0..Data33');
// a value past 2^31 is the 32-bit value the client keeps
$big = $props; $big[5] = 4294967295;
[$row] = object_template_row(409717, $icy(['props' => $big] + $entity), $page([164]));
check($row && $row['Data5'] === -1, 'an unsigned 32-bit value becomes its signed INT');
// a page without a name of its own (older crawler records) still witnesses the model
[$row, $why] = object_template_row(409717, $icy($entity), $page([164], null));
check($row !== null, 'a page that keeps no name witnesses by its model');
// case of the name does not matter
[$row] = object_template_row(409717, $icy($entity), $page([164], 'scrolls'));
check($row !== null, 'the names are compared without case');

// ---- what is left out, and why
$reason = fn(?array $i, ?array $p) => object_template_row(409717, $i, $p)[1];
check($reason(null, $page([164])) === 'object_template_no_record', 'no Icy Veins record');
check($reason($icy($entity, 'missing'), $page([164])) === 'object_template_no_record', 'Icy Veins does not know it');
check($reason(['status' => 'found', 'data' => 'not json'], $page([164])) === 'object_template_no_record', 'a record that is not one');
foreach (['type_id', 'display_id', 'scale', 'props', 'content_tuning_id', 'lock_id', 'name'] as $field) {
    $e = $entity; unset($e[$field]);
    check($reason($icy($e), $page([164])) === 'object_template_incomplete', "a record without $field");
}
foreach (['type_id' => null, 'display_id' => null, 'scale' => null, 'scale ' => 0, 'name' => '', 'props' => array_slice($props, 0, 33), 'props ' => array_merge(array_slice($props, 0, 34), [null]), 'type_id ' => 'chest'] as $field => $value) {
    $e = $entity; $e[trim($field)] = $value;
    check($reason($icy($e), $page([164])) === 'object_template_incomplete', 'a record whose ' . trim($field) . ' is ' . json_encode($value));
}
check($reason($icy($entity), null) === 'object_template_no_witness', 'no Wowhead page');
check($reason($icy($entity), ['status' => 'missing', 'name' => null, 'data' => json_encode(['id' => 409717, 'status' => 'missing'])]) === 'object_template_no_witness', 'Wowhead has no such page');
check($reason($icy($entity), $page([])) === 'object_template_no_witness', 'a page without a model');
check($reason($icy($entity), $page([165])) === 'object_template_witness_differs', 'the page shows another model');
check($reason($icy($entity), $page([164], 'The Shadow Connection')) === 'object_template_witness_differs', 'the page has another name');

// ---- the rows of several objects, with the reasons counted
[$rows, $left] = object_templates_rows(['409717' => ['drop:209848'], 457089 => ['drop:226417'], 460005 => ['drop:254546']],
    [409717 => $icy($entity), 457089 => $icy(['id' => 457089, 'props' => []] + $entity)], [409717 => $page([164]), 457089 => $page([4431])]);
check(count($rows) === 1 && $rows[0]['entry'] === 409717, 'one row for the whole, witnessed record');
check($left === ['object_template_incomplete' => 1, 'object_template_no_record' => 1], 'the others are left out with their reason: ' . json_encode($left));

ft_test_done();
