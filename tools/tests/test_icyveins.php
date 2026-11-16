<?php
// Reading Icy Veins answers (app/icyveins.php): the shapes are those of db.icy-veins.com/api/catalog/wowf/<kind>/<id>
// on 2026-11-15, cut down to the fields that matter.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/sources.php';

check(icyveins_loot_kind(0) === 'npc' && icyveins_loot_kind(8613) === 'skin' && icyveins_loot_kind(10768) === 'skin' && icyveins_loot_kind(921) === 'pick' && icyveins_loot_kind(2575) === 'skin' && icyveins_loot_kind(1804) === null,
    'a drop goes to the table of the spell that looted it: corpse, Skinning (Mining and Herb Gathering on a creature too), Pick Pocket; another spell has none');

// Bristleback Hunter: a corpse drop, a quest-only drop, a skinned hide; an unknown spell is counted
$ev = [];
icyveins_npc_evidence($ev, 3258, [
    'addon_drops' => [
        ['spell_id' => 0, 'item_id' => 2589, 'quest' => false, 'stack' => 1.7, 'chance' => 0.41463],
        ['spell_id' => 0, 'item_id' => 5085, 'quest' => true, 'stack' => 1, 'chance' => 0.67428],
        ['spell_id' => 8617, 'item_id' => 2318, 'quest' => false, 'stack' => 1, 'chance' => 0.9],
        ['spell_id' => 1804, 'item_id' => 2770, 'quest' => false, 'stack' => 1, 'chance' => 0.5],
    ],
    'addon_loot' => [['spell_id' => 0, 'average_coin' => 27]],
    'addon_levels' => [['ui_map_id' => 1413, 'level_min' => 16, 'level_max' => 18]],
    'addon_points' => [['ui_map_id' => 1413, 'via' => 'loot', 'x' => 503.2, 'y' => 456.3]],
]);
check(in_array(['npc', 3258, 2589, 41.463], $ev['drop'], true), 'a corpse drop, its chance in percent');
check(in_array(['skin', 3258, 2318, 90.0], $ev['drop'], true) && !in_array(['npc', 3258, 2318, 90.0], $ev['drop'], true), 'a skinned hide is a skinning drop, not a corpse drop');
check(isset($ev['quest_drop']['npc:3258:5085']) && !isset($ev['quest_drop']['npc:3258:2589']), 'a quest-only drop is remembered as such');
check(($ev['left']['icyveins_loot_spell_unknown'] ?? 0) === 1 && count($ev['drop']) === 3, 'a drop of another spell is counted, not written');
check(($ev['kept']['icyveins_kept_levels'] ?? 0) === 1 && ($ev['kept']['icyveins_kept_coin'] ?? 0) === 1 && ($ev['kept']['icyveins_kept_positions'] ?? 0) === 1, 'levels, coin and positions are counted as kept');

// Innkeeper Belm: vendor + innkeeper, with a stray trainer list; a sale for items is counted
$ev = [];
icyveins_npc_evidence($ev, 1247, [
    'addon_services' => [['service' => 5, 'repair' => false], ['service' => 20, 'repair' => false]],
    'addon_trains' => [['spell_id' => 4187, 'cost' => 100, 'req_level' => 10, 'rank' => 'Rank 1'], ['spell_id' => 4188, 'cost' => 200, 'req_level' => 20, 'rank' => 'Rank 2']],
    'addon_sells' => [['item_id' => 159, 'current' => true, 'remaining' => -1], ['item_id' => 4540, 'current' => false], ['item_id' => 99, 'cost_item_ids' => [1]]],
    'addon_quests' => [['quest_id' => 293, 'starts' => false, 'ends' => true]],
]);
check($ev['service'] === [[1247, 65536]], 'innkeeper becomes its npcflag bit; vendor is left to the vendor rows');
check(empty($ev['train']) && ($ev['left']['icyveins_trainer_list_not_a_trainer'] ?? 0) === 2, 'a trainer list on an NPC that offers no training is left out');
check($ev['sell'] === [[1247, 159, 0]] && ($ev['left']['icyveins_vendor_other_cost'] ?? 0) === 1, 'stock sold for money is kept, stock no longer sold is dropped, stock sold for items is counted');
check($ev['end'] === [['npc', 1247, 293]] && empty($ev['start']), 'the quests it takes back');

// a trainer keeps its list
$ev = [];
icyveins_npc_evidence($ev, 5499, ['addon_services' => [['service' => 7]], 'addon_trains' => [['spell_id' => 2259, 'prices' => [['cost' => 10], ['cost' => 9]], 'req_level' => 5, 'rank' => '']]]);
check($ev['train'] === [[5499, 2259, 10, 5, 0, 0, null, 0]], 'a trainer\'s list is kept, at its highest price');

// Georgio Bolero: a tailoring trainer; each recipe names its skill and the rank it needs
$ev = [];
icyveins_npc_evidence($ev, 1346, ['addon_services' => [['service' => 7]], 'addon_trains' => [
    ['spell_id' => 8766, 'name' => 'Azure Silk Belt', 'cost' => 1000, 'req_level' => 0, 'rank' => null, 'prices' => [['cost' => 1000], ['cost' => 900]],
     'details' => '{"skill": "Tailoring", "skillLine": "Tailoring", "skillRank": "140", "trainerType": "2"}'],
    ['spell_id' => 1, 'name' => 'Old Recipe', 'cost' => 5, 'details' => '{"skill": "Tailoring", "trainerType": "2"}'],
    ['spell_id' => 2, 'name' => 'Odd Recipe', 'cost' => 5, 'details' => '{"skill": "Basket Weaving", "skillRank": "10", "trainerType": "2"}'],
    ['spell_id' => 3, 'name' => 'Stray Bandage', 'cost' => 5, 'details' => '{"skillLine": "First Aid", "skillRank": "40", "trainerType": "2"}'],
    ['spell_id' => 8760, 'name' => 'Azure Silk Hood', 'cost' => 600, 'details' => '{"skillLine": "Tailoring", "skillRank": "120", "trainerType": "2"}'],
]]);
check($ev['train'] === [[1346, 8766, 1000, 0, 197, 140, [], 0], [1346, 8760, 600, 0, 197, 120, [], 0]], 'a recipe gets its skill line and rank (Tailoring 197, 140), no previous rank asked');
check(($ev['left']['icyveins_recipe_other_profession'] ?? 0) === 1, 'a recipe of another profession than most of the list is a stray: left out');
check(($ev['left']['trainer_profession_skill_unknown'] ?? 0) === 1 && ($ev['left']['trainer_skill_unknown'] ?? 0) === 1, 'without a rank, or with a skill this tracker does not know, it is counted, not written');

// Copper Vein: what it holds, with chances
$ev = [];
icyveins_object_evidence($ev, 1731, ['addon_contains' => [['item_id' => 2770, 'stack' => 1, 'chance' => 0.97149]], 'addon_quests' => [['quest_id' => 9, 'starts' => true, 'ends' => false]]]);
check($ev['drop'] === [['go', 1731, 2770, 97.149]] && $ev['start'] === [['go', 1731, 9]], 'an object\'s contents and the quest it starts');

// Linen Cloth: dropped, skinned (rare), from a chest, from a container
$ev = [];
icyveins_item_evidence($ev, 2589, [
    'addon_dropped_by' => [['npc_id' => 2673, 'gameobject_id' => null, 'spell_id' => 0, 'chance' => 0.71981], ['npc_id' => 1116, 'gameobject_id' => null, 'spell_id' => 8617, 'chance' => 0.45],
                           ['npc_id' => null, 'gameobject_id' => 2843, 'spell_id' => 0, 'chance' => 0.2]],
    'addon_gathered_from' => [['src' => 'item', 'container_item_id' => 5523, 'gather' => ''], ['src' => 'creature', 'npc_id' => 1116, 'gather' => 'skin']],
]);
check(in_array(['npc', 2673, 2589, 71.981], $ev['drop'], true) && in_array(['skin', 1116, 2589, 45.0], $ev['drop'], true) && in_array(['go', 2843, 2589, 20.0], $ev['drop'], true), 'an item\'s page: corpse, skinning and chest drops');
check(isset($ev['container']['5523:2589']), 'opened from a container: kept, no chance');

// quest: givers and turn-in words
$ev = [];
icyveins_quest_evidence($ev, 783, ['addon_givers' => [['npc_id' => 823, 'starts' => true, 'ends' => false], ['npc_id' => 197, 'starts' => false, 'ends' => true]],
    'addon_dialog' => [['kind' => 'complete', 'npc_id' => 197, 'text' => 'Ah, good.  Another volunteer.'], ['kind' => 'complete', 'npc_id' => 197, 'text' => '  ']]]);
check($ev['start'] === [['npc', 823, 783]] && $ev['end'] === [['npc', 197, 783]], 'givers and enders');
check($ev['text'] === [[783, 'complete', 'Ah, good.  Another volunteer.']], 'the turn-in words; an empty one is skipped');

// what the mirror keeps is fresh only when whole
check(!icyveins_fresh(null), 'nothing kept: ask');
check(!icyveins_fresh(['relations' => [], 'fetched' => time()]), 'an answer of the older form (relations only) is asked again, to get all of it');
check(icyveins_fresh(['entity' => ['id' => 1], 'relations' => [], 'fetched' => time()]), 'a whole answer of today is kept');
check(icyveins_fresh(['missing' => true, 'fetched' => time() - 6 * 86400]) && !icyveins_fresh(['missing' => true, 'fetched' => time() - 8 * 86400]), '"not known" is asked again after a week');
check(!icyveins_fresh(['entity' => [], 'fetched' => time() - 15 * 86400]), 'a whole answer is asked again after two weeks');

check(ICYVEINS_KINDS[0] === 'npc' && in_array('item', ICYVEINS_KINDS, true) && in_array('flight-path', ICYVEINS_KINDS, true), 'the mirror holds NPCs, objects, quests, items, zones and flight paths');
check(SOURCE_LOOT_TABLES['skin'] === 'skinning_loot_template' && SOURCE_LOOT_TABLES['pick'] === 'pickpocketing_loot_template', 'skinning and pick pocketing have their own tables');

check(source_stale_cards('icyveins', [31 => 'icyveins@2026-11-15-gaps', 32 => 'atlasloot@1'], []) === [31], 'the early card is an Icy Veins card: the full one replaces it when nothing was applied from it');
check(source_stale_cards('icyveins', [31 => 'icyveins@2026-11-15-gaps'], [['items' => json_encode([['type' => 'import', 'id' => 31]]), 'state' => 'applied']]) === [], 'an early card something was applied from stays');

check(source_trainer_fits([], 197) && source_trainer_fits([], 0), 'a trainer list with no rows takes anything');
check(source_trainer_fits([164 => 40, 0 => 2], 164) && !source_trainer_fits([164 => 40, 0 => 2], 129), 'a blacksmithing list takes blacksmithing recipes, not a bandage');
check(source_trainer_fits([0 => 30], 0) && !source_trainer_fits([0 => 30], 197), 'a class list takes class spells, not recipes');
check(!source_trainer_fits([197 => 12], 0), 'a tailoring list takes no class spell');
check(source_trainer_fits([0 => 4], 165, 2), 'a profession list holding only its ranks (line 0) takes recipes');
check(source_trainer_fits([0 => 4, 165 => 2], 165, 2) && !source_trainer_fits([0 => 4, 164 => 9], 165, 2), 'a profession list takes its own recipes, not another profession\'s');
check(!source_trainer_fits([0 => 4], 0, 2), 'a profession list takes no class spell');
check(source_trainer_fits([0 => 30], 0, 0) && !source_trainer_fits([], 197, 0) && !source_trainer_fits([0 => 3], 129, 3), 'a class or pet list takes class spells, no recipe');

ft_test_done();
