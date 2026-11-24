<?php
// A quest's turn-in words from its Wowhead page kept whole (app/wowheadpages.php wowhead_pages_turn_in_text): the
// Progress and Completion sections as the core writes them, a heading glued to the text before it, and none taken
// from the objectives. The fixtures keep the layout of real pages (80241, 97270, 94325).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/wowheadpages.php';

$page = fn(string $name) => file_get_contents(__DIR__ . "/fixtures/wowhead-quest-text/$name.txt");

$both = wowhead_pages_turn_in_text($page('both'));
check(($both['progress'] ?? null) === 'Could you be the next Galvan protege?', 'the Progress words, glued to the Description: ' . json_encode($both));
check(($both['complete'] ?? null) === 'Very good, $n! Listen and learn.$B$BAnd now you know the origin of blacksmithing.',
    'the Completion words up to Rewards, <name> and paragraphs as the core writes them: ' . json_encode($both));

$complete = wowhead_pages_turn_in_text($page('complete'));
check(array_keys($complete) === ['complete'], 'only the Completion words when the page has no Progress: ' . json_encode($complete));
check(str_starts_with($complete['complete'], 'You won!$B$B') && str_contains($complete['complete'], '$Gbrother:sister;')
    && !str_contains($complete['complete'], 'Gains'), 'the words stop before Gains, a gender pair written $G: ' . json_encode($complete));

check(wowhead_pages_turn_in_text($page('none')) === [], 'a page with no turn-in words gives none, "Progress" and "Completion" in its objectives are no headings');
check(wowhead_pages_turn_in_text('') === [], 'an empty page gives none');

ft_test_done();
