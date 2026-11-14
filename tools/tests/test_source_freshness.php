<?php
// How old an answer may be before a source is asked again (app/wowhead.php), and "ask every source again".
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

$day = 86400; $now = 1000 * $day;
$due = fn(float $ageDays, bool $missing = false, int $id = 1, int $epoch = 0, float $refresh = 30, float $recheck = 7) => wowhead_stale((int)($now - $ageDays * $day), $missing, $id, $now, $epoch, $refresh, $recheck);

check(!$due(20) && $due(40), 'a Wowhead answer is believed for about a month, then asked again');
check(!$due(6, true) && $due(8, true), '"Wowhead does not know it" for a week');
check(!$due(900, false, 1, 0, 0) && $due(900, true, 1, 0, 0), '[wowhead] refresh_days = 0 keeps answers for good; "not known" still expires');
check(round(wowhead_spread(1), 4) === 1.1305 && round(wowhead_spread(2), 4) === 1.011, 'the spread by id is the analysis\' own (tools/ft/wowhead.py): both read the same cache');
$days = [];
for ($id = 1; $id < 400; $id++) for ($d = 1; $d < 60; $d++) if ($due($d, false, $id)) { $days[] = $d; break; }
check(min($days) >= 22 && max($days) <= 38 && count(array_unique($days)) > 10, 'answers fetched in one run come due over two weeks, not on one day');
check($due(2 / 24, false, 1, $now - 3600) && !$due(0.5 / 24, false, 1, $now - 3600), 'after "ask every source again", what was fetched before it is due and what was asked since is not');

ft_test_done();
