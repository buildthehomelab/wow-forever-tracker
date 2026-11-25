<?php
// The loot entry a chest rolls (source_chest_loot_id, app/sources.php), as the core's GameObject::Use reads it:
// chestLoot (Data1), else personal loot (Data30: Forever's treasures), else push loot (Data33).
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

check(source_chest_loot_id(3, 119763, 0, 0) === 119763, 'a chest with chestLoot rolls Data1');
check(source_chest_loot_id(3, 119763, 136348, 0) === 119763, 'Data1 comes first, as in the core');
check(source_chest_loot_id(3, 0, 136348, 0) === 136348, 'a treasure without Data1 rolls its personal loot (Data30)');
check(source_chest_loot_id(3, 0, 0, 2772) === 2772, 'then its push loot (Data33)');
check(source_chest_loot_id(3, 0, 0, 0) === 0, 'a chest with none has no entry');
check(source_chest_loot_id(25, 3000, 136348, 0) === 3000, 'a fishing hole rolls Data1 only');
check(source_chest_loot_id(25, 0, 136348, 0) === 0, 'a fishing hole never reads Data30');
check(source_chest_loot_id(2, 27710, 0, 0) === 0, 'a quest giver object has no loot entry');
check(source_chest_loot_id(10, 0, 136348, 0) === 0, 'nor has a goober');
ft_test_done();
