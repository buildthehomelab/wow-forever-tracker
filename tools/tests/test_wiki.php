<?php
// warcraft.wiki.gg (app/wiki.php): what is read of its pages, and the evidence made of them. No database, no network.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/wiki.php';

$quest = <<<'WIKI'
{{Stub|Quest|1.60.1}}
{{Forever only|quest}}
{{Questbox
 | id = 92749
 | name = A Dynamite Plan
 | faction = Alliance
 | level = 16
 | start = [[Sprite Jumpsprocket]] {{co|30.8|66.2|Stormwind City (Forever)}}
 | end = [[Charred Remains (Silverpine Forest)|Charred Remains]]{{Co|65|34.2|Silverpine Forest (Forever)}}
 | previous =
}}

==Objectives==
Obtain 10 Coarse Dynamite.

==Progress==
Show me those explosives, <name>!

==Completion==
This is a great start, <class>!<br />
Now to tie it all together... and add a [[Coarse Dynamite|little extra]] ''zing''...<!-- editor note --><ref>a source</ref>

==Notes==
...

==Patch changes==
*{{Patch 1.60.1|added=}}
WIKI;

$npc = <<<'WIKI'
{{Forever only|NPC}}
{{Npcbox
| name = Kagil
| title = Junior Skinning Trainer
}}

==Sells==
{| class="darktable zebra sortable col2-right"
|-
! Item !! Cost !! Type
|-
| [[Skinning Knife#Classic]] || {{Cost|||10}} || {{ware|skinning}}
|-
| [[Salt]] || {{Cost|||50}} || {{ware|crafting reagent}}
|-
| [[Fancy Badge]] || {{Cost|item=Mark of Honor|5}} || {{ware|token}}
|-
| [[Missing Thing]] || {{Cost||1|}} || {{ware|junk}}
|-
| [[Pattern: Fine Cloak]] || {{Costitem|5|Merchant's Favor}} || {{ware|pattern}}
|}

==External links==
{{Elinks-NPC|267327}}
WIKI;

$pages = [
    'A Dynamite Plan' => [$quest, '2026-11-20T10:00:00Z'],
    'Kagil' => [$npc, '2026-11-21T10:00:00Z'],
    'Sprite Jumpsprocket' => ["{{Npcbox\n| name = Sprite\n}}\n{{Elinks-NPC|250001}}", '2026-11-19T00:00:00Z'],
    'Charred Remains (Silverpine Forest)' => ["{{Objectbox\n| name = Charred Remains\n}}\n{{Elinks-object|658836}}", '2026-11-19T00:00:00Z'],
    'Skinning Knife' => ["{{#data:Itemtip\n|name=Skinning Knife\n|itemid=7005\n}}{{#data:#Classic\n|name=Skinning Knife\n|itemid=7005\n}}", '2026-11-01T00:00:00Z'],
    'Salt' => ["{{#data:Itemtip\n|itemid=4289\n}}\n{{Elinks-item|4289}}", '2026-11-01T00:00:00Z'],
    'Fancy Badge' => ["{{Elinks-item|9999}}", '2026-11-01T00:00:00Z'],
    'Pattern: Fine Cloak' => ["{{#data:Itemtip\n|itemid=270001\n}}", '2026-11-01T00:00:00Z'],
    "Merchant's Favor" => ["{{#data:currencytip\n|name=Merchant's Favor\n|currencyid=3402\n}}", '2026-11-01T00:00:00Z'],
];

// ---- reading a page
check(wiki_title('skinning_Knife#Classic') === 'Skinning Knife', 'a link\'s title: anchor gone, first letter up');
check(wiki_first_link('[[Charred Remains (Silverpine Forest)|Charred Remains]]{{Co|65}}') === 'Charred Remains (Silverpine Forest)', 'the page a piped link leads to');
check(wiki_quest($quest) === [92749, 'Sprite Jumpsprocket', 'Charred Remains (Silverpine Forest)'], 'a quest page: its id, giver and ender');
check(wiki_quest($npc) === null, 'an NPC page is no quest');
check(wiki_section($quest, 'Progress') === 'Show me those explosives, <name>!', 'a section up to the next heading');
check(wiki_who($npc) === ['npc', 267327], 'an NPC page names its creature');
check(wiki_who($pages['Charred Remains (Silverpine Forest)'][0]) === ['go', 658836], 'an object page names its object');
check(wiki_who("{{Elinks-NPC2|252077|256966|loc1=A|loc2=B}}") === null, 'two creatures on one page: none taken');
check(wiki_item($pages['Skinning Knife'][0]) === 7005, 'the same item id twice is one item');
check(wiki_item("{{#data:Itemtip\n|itemid=1\n}}{{#data:#Old\n|itemid=2\n}}") === 0, 'two item ids: none taken');
check(wiki_sells($npc) === [['Skinning Knife', []], ['Salt', []], ['Fancy Badge', null], ['Missing Thing', []], ['Pattern: Fine Cloak', [["Merchant's Favor", 5]]]], 'the rows of a Sells table and their prices');
check(wiki_price('{{Costitem|2|A}}{{Costitem|1|B}}') === [['A', 2], ['B', 1]] && wiki_price('{{Cost||5|}}{{Costitem|1|B}}') === null, 'currencies alone, or money and items together');
check(wiki_token($pages["Merchant's Favor"][0]) === 'c3402' && wiki_token($pages['Salt'][0]) === 'i4289', 'a currency page and an item page');
$two = "{{Elinks-NPC2|11026|157813|loc1=A|loc2=B}}";
check(wiki_who($two, ['npc' => [157813 => true], 'go' => []]) === ['npc', 157813], 'several ids: the one the server spawns');
check(wiki_who($two, ['npc' => [11026 => true, 157813 => true], 'go' => []]) === null, 'several spawned: none taken');
check(wiki_several(['x' => [$two, ''], 'y' => [$npc, '']]) === ['npc' => [11026, 157813], 'go' => []], 'the ids of pages that name several');

// ---- the words as the core writes them
check(wiki_core_text('Show me those explosives, <name>!') === 'Show me those explosives, $n!', '<name> becomes $n');
check(wiki_core_text("One.\n\nTwo, <Race>.") === 'One.$B$BTwo, $R.', 'line breaks become $B');
check(wiki_core_text('...') === null && wiki_core_text('') === null, 'no words');
check(wiki_core_text('(Needs the text.)') === null && wiki_core_text('Unknown') === null, 'a note instead of the words');
check(wiki_core_text("{{Quest text|x}}") === null && wiki_core_text("* a list") === null, 'a template or a list');

check(wiki_core_text('The [[:Symbol of Life]] is yours.') === 'The Symbol of Life is yours.', 'a [[:link]] keeps its words alone');
check(wiki_core_text("Done.\n[[File:Map.jpg|thumb]]") === null && wiki_core_text('[[Category:Quests]]') === null, 'a picture or a category: left out');
check(wiki_core_text('Thank you, <Brother/Sister>. Go, <lad/lass>!') === 'Thank you, $GBrother:Sister;. Go, $Glad:lass;!', 'gender words as $G');
check(wiki_core_text('<Ayessa listens quietly.>$') === null || wiki_core_text('<Ayessa listens quietly.>') === '<Ayessa listens quietly.>', 'an emote line stays the game\'s words');
$qty = "==Sells==\n{|\n|-\n! Qty !! Item !! Cost\n|-\n| {{qty|limited=4}} || [[Bronze Framework]] || {{Cost||2|}}\n|}";
check(wiki_sells($qty) === [['Bronze Framework', []]], 'a quantity column before the item');

// ---- pages outside the Forever categories, vendors with several tables
$medic = ["{{Elinks-NPC|16284}}", '', false];
check(wiki_who($medic[0], ['npc' => [], 'go' => []], false) === null, 'a linked page\'s one id, not spawned: not taken');
check(wiki_who($medic[0], ['npc' => [16284 => true], 'go' => []], false) === ['npc', 16284], 'a linked page\'s one id, spawned: taken');
check(wiki_several(['m' => $medic]) === ['npc' => [16284], 'go' => []], 'a linked page\'s ids are checked for spawns');
$two = ['Fizz' => ["{{Elinks-NPC|240654}}\n==Sells==\n{|\n|-\n| [[Salt]] || {{Cost|||50}}\n|}\n{|\n|-\n| [[Salt]] || {{Cost|||50}}\n|}", '', true], 'Salt' => $pages['Salt']];
$e2 = wiki_evidence($two);
check($e2['sell'] === [] && ($e2['left']['wiki_vendor_several_tables'] ?? 0) === 2, 'a vendor page with several Sells tables: left out');

// ---- the evidence
$ev = wiki_evidence($pages);
check($ev['start'] === [['npc', 250001, 92749]], 'the giver, by the id its page names');
check($ev['end'] === [['go', 658836, 92749]], 'the ender, an object');
check($ev['sell'] === [[267327, 7005, 0], [267327, 4289, 0], [267327, 270001, 0, 'c3402x5']], 'what the NPC sells, for money or a currency');
$texts = array_column($ev['text'], 2, 1);
check(($texts['progress'] ?? '') === 'Show me those explosives, $n!', 'the progress words');
check(($texts['complete'] ?? '') === 'This is a great start, $c!$BNow to tie it all together... and add a little extra zing...', 'the turn-in words, links, comments and refs gone');
check(($ev['left']['wiki_vendor_price_unread'] ?? 0) === 1 && ($ev['left']['wiki_vendor_item_no_page'] ?? 0) === 1, 'a price it cannot read, an item without a page: counted');
check(wiki_links_wanted($quest) === ['Sprite Jumpsprocket', 'Charred Remains (Silverpine Forest)'], 'a quest page wants its giver and ender');
check(wiki_version($pages) === '2026-11-21T10:00:00Z', 'the version: the newest revision');

// ---- its place among the sources
check(array_slice(source_trust(''), 3, 3) === ['norgannondb', 'icyveins', 'wiki'], 'right after Icy Veins');
check(source_named('warcraft.wiki.gg 2026-11-23') === 'wiki', 'a row it wrote is known as its own');

ft_test_done();
