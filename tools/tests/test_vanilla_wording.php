<?php
// The original game as the changelog's start (app/bootstrap.php, docs/VANILLA.md): how a build is named, and why what
// the original game had and WoW: Forever does not is never called "removed".
require __DIR__ . '/helpers.php';
ft_test_boot();

// an analysis from before the original game was stored: everything reads as it did
meta(['schema' => 3]);
check(baseline() === [], 'no original game stored: no baseline');
check(build_name(69876) === 'build 69876', 'a build is named by its number');
check(change_label('removed', 69876) === 'Removed', 'the first build held is not compared with anything');
check(!from_vanilla(69876) && !build_is_vanilla(['build' => 69876]), 'no build is the original game');
check(changes_shown('c.') === '', 'an older analysis has no mark on its removals: none is asked for');

meta(['schema' => 4, 'baseline' => ['build' => 31650, 'version' => '1.13.2.31650', 'first' => 69876, 'hidden' => ['ItemSparse' => 63], 'alone' => 4097]]);
check(baseline()['version'] === '1.13.2.31650', 'the original game is known from the analysis');
check(build_is_vanilla(['build' => 31650]) && !build_is_vanilla(['build' => 69876]), 'its build is the original game');
check(from_vanilla(69876) && !from_vanilla(70009) && !from_vanilla(31650), 'the game\'s first build is the one compared with it');
check(build_name(31650) === 'the original game (1.12)' && build_name(70938) === 'build 70938', '"since the original game", not "since build 31650"');
check(change_label('removed', 69876) === 'Not in Forever', 'against the original game: not in Forever (taken out, or not released yet)');
check(change_label('removed', 70009) === 'Removed', 'a later build removes');
check(change_label('added', 69876) === 'Added' && change_label('modified', 69876) === 'Changed', 'added and changed read as everywhere');
check(changes_shown('c.') === ' AND c.internal = 0', 'removals of no interest are left out once the analysis marks them');

meta(['schema' => 4, 'baseline' => []]);
check(baseline() === [] && change_label('removed', 69876) === 'Removed', 'the original game switched off: as before');

ft_test_done();
