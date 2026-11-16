<?php
// AtlasLoot (app/atlasloot.php): what is kept of the lists no creature takes, the other parts of the addon, and the
// rewards of quests that give nothing on the server. No database, no download.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/atlasloot.php';

// ---- what a list without a creature is
check(atlasloot_kind('Trash') === 'al_trash' && atlasloot_kind('Trash Mobs') === 'al_trash', 'trash lists');
check(atlasloot_kind('Blood Red Bandanas (Horde Quest)') === 'al_reward' && atlasloot_kind('Alliance Only Quest Rewards') === 'al_reward', 'quest reward lists');
check(atlasloot_kind('Gill') === 'al_named' && atlasloot_kind('Class books') === 'al_named', 'anything else: a list under its name');

// ---- the quest a reward list names
check(atlasloot_quest_title('Blood Red Bandanas (Horde Quest)') === ['Blood Red Bandanas', 'horde'], 'a title with its side');
check(atlasloot_quest_title('A Bit of Wet Work (Alliance Quest)') === ['A Bit of Wet Work', 'alliance'], 'the other side');
check(atlasloot_quest_title('Quest Rewards (Eye of Mugg)') === ['Eye of Mugg', ''], 'the title in brackets');
check(atlasloot_quest_title('Alliance Only Quest Rewards')[0] === '', 'a list that names no quest');
check(atlasloot_pick_quest([101 => 0], 'horde') === 101, 'one quest of that title');
check(atlasloot_pick_quest([101 => 0, 102 => 0], '') === 0, 'two and no side: none');
check(atlasloot_pick_quest([101 => 1 | 4 | 8 | 64, 102 => 2 | 16 | 32 | 128], 'horde') === 102, 'two: the one open to the side');
check(atlasloot_pick_quest([101 => 1, 102 => 4], 'horde') === 0, 'two, neither for that side: none');
check(atlasloot_pick_quest([], 'horde') === 0, 'no quest of that title');

// ---- rewards for quests that give nothing
[$sets, $left] = atlasloot_reward_sets([7 => [500 => true, 501 => true], 8 => [600 => true], 9 => [700 => true], 10 => [800 => true]], [7 => 0, 8 => 0, 9 => 2]);
check($sets['RewardChoiceItemID1'] === [[7, 500]] && $sets['RewardChoiceItemID2'] === [[7, 501]] && $sets['RewardChoiceItemQuantity2'] === [[7, 1]], 'several items: a choice');
check($sets['RewardItem1'] === [[8, 600]] && $sets['RewardAmount1'] === [[8, 1]], 'one item: given');
check(!isset($sets['RewardChoiceItemID3']) && $left === ['atlasloot_quest_has_rewards' => 1, 'atlasloot_quest_not_on_server' => 1], 'a quest that rewards something, or one the server lacks: nothing');

// ---- the other parts of the addon, as lists
$lua = <<<'LUA'
data["ArgentDawn"] = {
	FactionID = 529,
	items = {
		{ -- Exalted
			name = ALIL["Exalted"],
			[NORMAL_DIFF] = {
				{ 1,  "f529rep8" },
				{ 2,  18182 }, -- Chromatic Mantle of the Dawn
				{ 17, 22523, 22524, [ATLASLOOT_IT_AMOUNT1] = "x" },
			},
		},
	},
}
data["AlteracValley"] = {
	items = {
		{
			name = _G["FACTION_STANDING_LABEL8"],
			[ALLIANCE_DIFF] = {
				{ 1,  "f730rep8" },
				{ 2,  19312 },
			},
			[HORDE_DIFF] = {
				{ 1,  "f729rep8" },
				{ 2,  19312 },
			},
		},
		GameVersion_GE(AtlasLoot.WRATH_VERSION_NUM, {
			name = "Later",
			[NORMAL_DIFF] = { { 1, 99999 } },
		}),
	},
}
data["Sets"] = {
	TableType = SET_ITTYPE,
	items = {
		{ name = "Set", [NORMAL_DIFF] = { { 1, 181 } } },
	},
}
data["DireMaulWest"] = {
	items = {
		{
			name = "Shen'dralar Provisioner",
			[NORMAL_DIFF] = {
				{ 1, 18487, [PRICE_EXTRA_ITTYPE] = "money:40000" }, -- Pattern
			},
		},
	},
}
LUA;
$rows = atlasloot_lists($lua, 'Test');
$by = []; foreach ($rows as $r) $by[$r[1]][] = $r[0];
check(($by['Test/ArgentDawn/Exalted'] ?? []) === [18182, 22523], 'a faction list: its items');
check($rows[0][7] === 529 && $rows[0][8] === 8, 'with its faction and standing');
check(($by['Test/AlteracValley/FACTION_STANDING_LABEL8/alliance'] ?? []) === [19312] && ($by['Test/AlteracValley/FACTION_STANDING_LABEL8/horde'] ?? []) === [19312], 'each side on its own');
check(!in_array(99999, array_merge(...array_values($by)), true), 'a block for a later version: left out');
check(!isset($by['Test/Sets/Set']), 'a set table: left out');
$priced = array_values(array_filter($rows, fn($r) => $r[0] === 18487));
check($priced && $priced[0][6] === 'money:40000', 'a row\'s price is kept');

// ---- the facts kept: every kind has one key per row
$facts = snapshot_facts(['drop' => [], 'al_trash' => [[1, 'Scholomance', 289], [1, 'Stratholme', 329]],
    'al_list' => [[18182, 'Factions/ArgentDawn/Exalted', 'Factions', 'ArgentDawn', 'Exalted', '', '', 529, 8]], 'al_rate' => [[644, 872, 3.91]]]);
check(count($facts) === 4, 'the same item in two trash lists is two facts');
$back = snapshot_rows_evidence(array_map(fn($f) => ['fact' => $f[0], 'kind' => $f[1], 'entity' => $f[2], 'target' => $f[3], 'value' => $f[4], 'extra' => $f[5]], array_values($facts)));
check($back['al_rate'] === [[644, 872, 3.91]] && $back['al_list'][0][7] === 529, 'and they come back from the database as they were');

ft_test_done();
