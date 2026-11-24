<?php
// The words of players' comments as evidence of a quest's giver or ender (app/wowheadpages.php,
// wowhead_comment_text_names, wowhead_comments_text_evidence): names said after "turn it in to", "starts from", ...,
// matched to the one spawned creature or object of the server with that name.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/wowheadpages.php';

$names = wowhead_comment_text_names('You turn it in to Griniblix the Spectator above the Maul. Starts from Sully McCleary at the docks.');
check(in_array(['end', 'Griniblix the Spectator'], $names, true) && in_array(['end', 'Griniblix'], $names, true)
    && array_search(['end', 'Griniblix the Spectator'], $names, true) < array_search(['end', 'Griniblix'], $names, true),
    'the name after "turn it in to", longest first, then its shorter start: ' . json_encode($names));
check(in_array(['start', 'Sully McCleary'], $names, true), 'the name after "starts from": ' . json_encode($names));
check(!in_array(['end', 'Griniblix the Spectator above'], $names, true), 'a lowercase word ends the name');
check(wowhead_comment_text_names('Turn in to [npc=5]Rayan[/npc] in Azshara.') === [], 'a linked name is the crawler\'s link, not read again');
check(wowhead_comment_text_names('this quest is bugged, turn in does nothing') === [], 'no capitalised name, nothing');

$gaps = ['noGiver' => [100 => true], 'noEnder' => [100 => true, 200 => true, 300 => true]];
$comments = [
    100 => [['rating' => 2, 'body' => 'Turned it in to Griniblix the Spectator.', 'replies' => [['body' => 'It starts from Sully McCleary now.']]]],
    200 => [['rating' => -2, 'body' => 'Hand it in to Sully McCleary.']],
    300 => [['rating' => 0, 'body' => 'Return it to Guard Captain please.']],
    400 => [['rating' => 5, 'body' => 'Turn it in to Sully McCleary.']],   // no gap
];
$asked = [];
$resolve = function (array $n) use (&$asked) {
    $asked = $n;
    return ['griniblix the spectator' => [['npc', 14395]], 'sully mccleary' => [['npc', 260271]], 'guard captain' => [['npc', 1], ['npc', 2]]];
};
[$start, $end, $left] = wowhead_comments_text_evidence($comments, $gaps, $resolve);
check($end === [['npc', 14395, 100]], 'the ender named in a comment, the one spawned creature of that name: ' . json_encode($end));
check($start === [['npc', 260271, 100]], 'the giver named in a reply: ' . json_encode($start));
check(($left['wowhead_comment_voted_down'] ?? 0) === 1, 'a comment voted down is not read: ' . json_encode($left));
check(($left['wowhead_comment_name_several'] ?? 0) === 1, 'a name several spawned creatures have is left: ' . json_encode($left));
check(!in_array('turn it in to sully mccleary', $asked, true) && in_array('griniblix', $asked, true), 'names of gap quests only are looked up');

$picked = wowhead_comments_name_pick(['sully mccleary' => [['npc', 260146, false], ['npc', 260271, true]], 'guard' => [['npc', 1, true], ['npc', 2, true]], 'altar' => [['go', 9, false]]]);
check($picked === ['sully mccleary' => [['npc', 260271]], 'guard' => [['npc', 1], ['npc', 2]], 'altar' => [['go', 9]]],
    'of two of one name, the one that deals in quests; two that both do stay two: ' . json_encode($picked));

ft_test_done();
