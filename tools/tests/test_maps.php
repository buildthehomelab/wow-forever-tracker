<?php
// The Spawns page's map pictures (app/maps.php): a world position put on the right official zone map, and the
// picture downloaded once, only for maps the client draws, only when it is a PNG.
require __DIR__ . '/helpers.php';
ft_test_boot();
require_once FT_APP . '/maps.php';

// WoW: Forever 1.60.1.70959 (data/ui-maps.json as tools/ft/geo.py writes it)
$ui = ['build' => 70959, 'maps' => [
    '1411' => ['name' => 'Durotar', 'type' => 3, 'rects' => [[1, -1716.6666, -7249.9995, 1808.3333, -1962.4999, 0, 0, 1, 1, 14]]],
    '1414' => ['name' => 'Kalimdor', 'type' => 2, 'rects' => [[1, -11733.2998, -19733.2109, 12799.9004, 17066.5996, 0, 0, 1, 1, 0]]],
    '1454' => ['name' => 'Orgrimmar', 'type' => 3, 'rects' => [[1, 1338.4606, -5083.2056, 2273.8772, -3680.6011, 0, 0, 1, 1, 1637]]],
    '2548' => ['name' => 'Riverglades', 'type' => 3, 'rects' => [[0, -9700, -6741.666, -6466.666, -1891.666, 0, 0, 1, 1, 16591]]],
]];

// Razor Hill's inn (Durotar), Thrall's room (Orgrimmar)
$razor = maps_place(1, 304.0, -4730.0, null, $ui);
check($razor !== null && $razor[0] === 1411, 'a Durotar position is drawn on Durotar, not on Kalimdor');
check(abs($razor[1] - (-1962.4999 + 4730.0) / (-1962.4999 + 7249.9995)) < 1e-4 && abs($razor[2] - (1808.3333 - 304.0) / (1808.3333 + 1716.6666)) < 1e-4, 'at the game\'s own projection (u from y, v from x, north up)');
check(maps_place(1, 1600.0, -4400.0, null, $ui)[0] === 1454, 'inside Orgrimmar the city map wins over its zone');
check(maps_place(1, 1600.0, -4400.0, 14, $ui)[0] === 1411, 'unless the spawn is said to stand in Durotar');
check(maps_place(1, -7000.0, 1000.0, null, $ui)[0] === 1414, 'a position outside every zone map falls back to the continent');
check(maps_place(0, -8000.0, -4000.0, null, $ui)[0] === 2548, 'Eastern Kingdoms positions only match Eastern Kingdoms maps');
check(maps_place(36, 0.0, 0.0, null, $ui) === null, 'a dungeon has no picture');

$pins = maps_pins(1, [[304.0, -4730.0, 12.0], [310.0, -4740.0, null], [1920.0, -4139.0, 20.0], 'bad'], null, $ui);
check($pins['map'] === 1411 && count($pins['pins']) === 2 && $pins['elsewhere'] === 2 && $pins['name'] === 'Durotar', 'the map with most of the points is shown, the others are counted');
check(maps_pins(null, [[1, 2, 3]], null, $ui) === null && maps_pins(1, [], null, $ui) === null, 'no map and no points: no picture');

// pictures
$dir = ft_test_dir();
$png = "\x89PNG\r\n\x1a\n" . str_repeat('x', 100);
$asked = [];
$get = function (string $url) use (&$asked, $png) { $asked[] = $url; return [200, $png]; };
$path = maps_image(1411, $get, $ui, $dir);
check($path === "$dir/70959/1411.png" && file_get_contents($path) === $png, 'a picture is downloaded once per build');
check($asked === ['https://wago.tools/api/map/1411?product=wowf&explored=1'], 'from wago.tools, for the configured product');
maps_image(1411, $get, $ui, $dir);
check(count($asked) === 1, 'and kept');
check(maps_image(9999, $get, $ui, $dir) === null && count($asked) === 1, 'a map the client does not draw is never asked for');
$bad = function (string $url) use (&$asked) { $asked[] = $url; return [200, '<html>not a map</html>']; };
check(maps_image(1414, $bad, $ui, $dir) === null && !is_file("$dir/70959/1414.png"), 'an answer that is not a PNG is not kept');
check(maps_image(1414, $get, $ui, $dir) === null && count($asked) === 2, 'and not asked again for a day');
$down = function (string $url) { return [500, null]; };
check(maps_image(2548, $down, $ui, $dir) === null, 'a failed download is no picture');

// the route is for administrators only
foreach (["[site]\npublic = 0\n", "[site]\npublic = 1\n"] as $ini) {
    [$status, $body] = ft_test_request('/admin/map?id=1411', $ini);
    check(in_array($status, [302, 303, 403], true) && strpos($body, "\x89PNG") === false, 'visitors get no map picture (' . trim(strstr($ini, 'public')) . ')');
}

ft_test_done();
