<?php
// The Forge · Imports: world data in WowPacketParser's SQL format, merged safely into the server.
require_once FT_APP . '/imports.php';
import_schema();
forge_schema();
$dir = import_dir();
@mkdir($dir, 0775, true);
$imports = rows('SELECT s.*, (SELECT COUNT(DISTINCT item) FROM ft_import_items i WHERE i.import_id = s.id) items FROM ft_imports s ORDER BY s.id DESC');
$importedFiles = array_flip(array_column($imports, 'file'));
$waiting = [];
foreach (array_merge(glob($dir . '/*.sql') ?: [], glob($dir . '/*.lua') ?: []) as $path) if (!isset($importedFiles[basename($path)])) $waiting[] = ['file' => basename($path), 'size' => filesize($path), 'time' => filemtime($path)];
require_once FT_APP . '/collector.php';
collector_schema();
$scribeFiles = collector_files();
$scribeState = is_file(FT_ROOT . '/data/collector-state.json') ? (json_decode((string)file_get_contents(FT_ROOT . '/data/collector-state.json'), true) ?: []) : [];
$located = (int)value('SELECT COUNT(*) FROM ft_collected');
$clientAddons = (function () { require_once FT_APP . '/spawns.php'; return spawn_client_addons(); })();
$scribeInstalled = $clientAddons !== '' && is_file($clientAddons . '/ForeverScribe/ForeverScribe.toc');
$tableLabels = [
    'creature' => t('Creature spawns', 'Placements de PNJ'), 'gameobject' => t('Object spawns', 'Placements d’objets'), 'creature_template' => t('New creatures', 'Nouveaux PNJ'),
    'gameobject_template' => t('New objects', 'Nouveaux objets du monde'), 'creature_loot_template' => t('Creature loot', 'Butin des PNJ'), 'gameobject_loot_template' => t('Chest loot', 'Butin des coffres'),
    'npc_vendor' => t('Vendors', 'Marchands'), 'quest_template' => t('Quests', 'Quêtes'), 'creature_queststarter' => t('Quest givers', 'Donneurs de quête'),
    'creature_questender' => t('Quest enders', 'Valideurs de quête'), 'trainer_spell' => t('Trainers', 'Entraîneurs'), 'trainer' => t('New trainer lists', 'Nouvelles listes d’entraîneur'), 'conditions' => t('Conditions on conversation lines', 'Conditions des répliques'), 'smart_scripts' => t('SmartAI: what a line does', 'SmartAI : ce que fait une réplique'),
    'creature_template_gossip' => t('Creatures that get a conversation of their own', 'PNJ qui reçoivent une conversation propre'),
    'creature_template.AIName' => t('Creatures that run SmartAI (where they ran nothing)', 'PNJ qui utilisent SmartAI (là où ils n’avaient rien)'),
    'creature_template.ScriptName' => t('Creatures that get the core script that teaches (where they had none)', 'PNJ qui reçoivent le script du cœur qui enseigne (là où ils n’en avaient pas)'),
    'creature_template.npcflag' => t('Creatures players can talk to (gossip flag, where missing)', 'PNJ à qui l’on peut parler (drapeau de dialogue, là où il manque)'),
    'gameobject_template.AIName' => t('Objects that run SmartAI (where they ran nothing)', 'Objets qui utilisent SmartAI (là où ils n’avaient rien)'),
    'gameobject_template.Data3' => t('Objects that get a conversation of their own', 'Objets qui reçoivent une conversation propre'),
    'gameobject_template.Data10' => t('Objects that get a conversation of their own', 'Objets qui reçoivent une conversation propre'),
    'gameobject_template.Data19' => t('Objects that get a conversation of their own', 'Objets qui reçoivent une conversation propre'),
    'gameobject_template.Data2' => t('Objects that get a conversation of their own', 'Objets qui reçoivent une conversation propre'), 'creature_trainer' => t('Creatures that become trainers', 'PNJ qui deviennent entraîneurs'), 'gossip_menu_option' => t('Gossip options', 'Options de dialogue'),
    'gameobject_queststarter' => t('Quest givers (objects)', 'Donneurs de quête (objets)'), 'gameobject_questender' => t('Quest enders (objects)', 'Valideurs de quête (objets)'),
    'quest_offer_reward' => t('What the NPC says at the turn-in', 'Ce que dit le PNJ au rendu'), 'quest_request_items' => t('What the NPC says while the quest is not done', 'Ce que dit le PNJ tant que la quête n’est pas finie'),
    // rows the server already has, whose value the source measured again (docs/SOURCES.md)
    'creature_loot_template.Chance' => t('Creature drop chances that moved', 'Chances de butin de PNJ qui ont bougé'),
    'gameobject_loot_template.Chance' => t('Chest drop chances that moved', 'Chances de butin de coffre qui ont bougé'),
];
$leftLabels = [
    'vendor_unknown' => t('vendors unknown to this server', 'marchands inconnus de ce serveur'), 'cost_unknown' => t('items paid with items or currencies (no known ExtendedCost)', 'objets payés en objets ou monnaies (ExtendedCost inconnu)'),
    'loot_unknown' => t('creatures unknown to this server', 'PNJ inconnus de ce serveur'), 'object_no_loot' => t('objects without a loot table', 'objets sans table de butin'), 'loot_known' => t('drops the server already has (directly or through reference loot)', 'butins que le serveur a déjà (directement ou par référence)'),
    'quest_unknown' => t('quests unknown to this server', 'quêtes inconnues de ce serveur'),
    'vendor_no_second_source' => t('vendors no live Forever recording saw (EG Link, ForeverDB.net, Icy Veins)', 'marchands qu’aucun enregistrement de Forever n’a vus (EG Link, ForeverDB.net, Icy Veins)'),
    'quest_start_no_second_source' => t('quest givers no live Forever recording saw', 'donneurs de quête qu’aucun enregistrement de Forever n’a vus'),
    'quest_end_no_second_source' => t('quest enders no live Forever recording saw', 'valideurs de quête qu’aucun enregistrement de Forever n’a vus'),
    'drop_no_second_source' => t('drops no live Forever recording (EG Link, ForeverDB.net, Icy Veins) or AtlasLoot saw', 'butins qu’aucun enregistrement de Forever (EG Link, ForeverDB.net, Icy Veins) ni AtlasLoot n’a vus'),
    'atlasloot_no_creature' => t('AtlasLoot lists whose name is no single spawned creature or chest of this server (trash, sets, quest rewards)', 'listes AtlasLoot dont le nom n’est aucun PNJ ou coffre unique placé sur ce serveur (trash, ensembles, récompenses)'),
    'atlasloot_vendor' => t('AtlasLoot lists of vendors (their stock, not drops)', 'listes AtlasLoot de marchands (leur stock, pas du butin)'),
    'atlasloot_several_creatures' => t('AtlasLoot lists naming several creatures, none of whose loot gives the list\'s other items', 'listes AtlasLoot à plusieurs PNJ dont aucun butin ne donne les autres objets de la liste'),
    'witness_eglink_unreachable' => t('EG Link unreachable: its recordings could not confirm', 'EG Link injoignable : ses enregistrements n’ont pas pu confirmer'),
    'witness_foreverdb_unreachable' => t('ForeverDB.net unreachable: its recordings could not confirm', 'ForeverDB.net injoignable : ses enregistrements n’ont pas pu confirmer'),
    'drop_same' => t('drops the server has whose chance has not moved', 'butins que le serveur a et dont la chance n’a pas bougé'),
    'drop_differs_core' => t('drops whose chance differs but that no import brought (the core’s own rows: not changed)', 'butins dont la chance diffère mais qu’aucun import n’a apportés (lignes du core : inchangées)'),
    'drop_differs_trusted' => t('drops whose chance differs from a more trusted source’s row (not changed)', 'butins dont la chance diffère de celle d’une source plus fiable (inchangés)'),
    'report_quest_not_seen' => t('quests no player of the site saw (Classic’s lines: not taken)', 'quêtes qu’aucun joueur du site n’a vues (lignes de Classic : non reprises)'),
    'report_quest_started_by_item' => t('quests an item starts (no giver to write)', 'quêtes lancées par un objet (pas de donneur à écrire)'),
    'classic_conversation' => t('recipes the original game teaches through a line of a creature’s conversation (a script, not a row: not written)', 'recettes que le jeu d’origine enseigne par une réplique d’un PNJ (un script, pas une ligne : non écrites)'),
    'classic_quest_unknown' => t('quests of the original game that taught a recipe and that this server does not have', 'quêtes du jeu d’origine qui enseignaient une recette et que ce serveur n’a pas'),
    'classic_quest_casts_already' => t('quests that already cast a spell at the turn-in (left as they are)', 'quêtes qui lancent déjà un sort au rendu (laissées telles quelles)'),
    'classic_gone_from_forever' => t('recipes WoW: Forever took away (the spell is gone from the server’s data, or marked never learned): not asked', 'recettes que WoW: Forever a retirées (le sort a disparu des données du serveur, ou est marqué « jamais appris ») : non demandées'),
    'classic_trainer_not_spawned' => t('recipes of the original game’s trainers that nobody spawned here', 'recettes d’entraîneurs du jeu d’origine que personne n’a placés ici'),
    'classic_trainer_number_taken' => t('recipes of creatures whose own trainer list number is already used by another list', 'recettes de PNJ dont le numéro de liste propre est déjà pris par une autre liste'),
    'classic_talk_unknown' => t('conversation lines of creatures or objects this server does not have', 'répliques de PNJ ou d’objets que ce serveur n’a pas'),
    'classic_talk_not_spawned' => t('conversation lines of creatures or objects nobody spawned here', 'répliques de PNJ ou d’objets que personne n’a placés ici'),
    'classic_talk_known' => t('conversation lines the server already has', 'répliques que le serveur a déjà'),
    'classic_talk_other_script' => t('conversation lines of creatures or objects run by a core script (SmartAI would not run)', 'répliques de PNJ ou d’objets gérés par un script du cœur (SmartAI ne tournerait pas)'),
    'classic_talk_core_teaches' => t('conversation lines a script of the core already teaches (the Field Repair Bot schematic)', 'répliques qu’un script du cœur enseigne déjà (le schéma du robot réparateur)'),
    'classic_talk_core_broken' => t('conversation lines of a core script that teaches nobody until the core is fixed (Knot Thimblejack, the engineering transporters, Master Craftsman Omarion)', 'répliques d’un script du cœur qui n’enseigne à personne tant que le cœur n’est pas corrigé (Knot Thimblejack, les transporteurs d’ingénierie, le maître artisan Omarion)'),
    'classic_talk_other_ai' => t('conversation lines of creatures or objects with another AI', 'répliques de PNJ ou d’objets dotés d’une autre IA'),
    'classic_talk_object_type' => t('conversation lines of objects of a type that has no conversation', 'répliques d’objets d’un type sans conversation'),
    'classic_talk_several_menus' => t('conversation lines of creatures that open several conversations (which one shows is not known)', 'répliques de PNJ qui ouvrent plusieurs conversations (on ne sait laquelle s’affiche)'),
    'classic_talk_menu_shared' => t('conversation lines whose conversation other creatures or objects open too', 'répliques dont la conversation est aussi ouverte par d’autres PNJ ou objets'),
    'classic_talk_menu_number_taken' => t('conversation lines whose own conversation number is already used', 'répliques dont le numéro de conversation propre est déjà pris'),
    'classic_talk_condition' => t('conversation lines with a condition that cannot be written', 'répliques avec une condition qui ne peut pas être écrite'),
    'classic_silent' => t('recipes the original game’s database names no teacher for', 'recettes pour lesquelles la base du jeu d’origine ne nomme personne'),
    'report_name_unknown' => t('NPC names no creature or object of this server has', 'noms de PNJ qu’aucune créature ni objet de ce serveur ne porte'),
    'report_not_spawned' => t('names that two or more templates share, none of them spawned (nothing tells which one players met), and drops of creatures nobody spawned', 'noms que deux modèles ou plus partagent, aucun n’étant placé (rien ne dit lequel les joueurs ont rencontré), et butins de créatures que personne n’a placées'),
    'report_several_same_name' => t('names several creatures share, with nothing to tell them apart', 'noms partagés par plusieurs créatures, sans rien pour les distinguer'),
    'report_position_far' => t('NPCs reported far from where the only creature of that name stands', 'PNJ signalés loin de l’endroit où se tient la seule créature de ce nom'),
    'report_place_already_spawned' => t('reported places of creatures or objects this server already spawns (not needed)', 'lieux signalés de créatures ou d’objets que ce serveur place déjà (inutiles)'),
    'report_place_unknown_creature' => t('reported NPCs this server has no template of', 'PNJ signalés dont ce serveur n’a pas de modèle'),
    'report_place_name_unknown' => t('rares, commerce NPCs or books whose name nothing on this server has', 'rares, PNJ de commerce ou livres dont rien sur ce serveur ne porte le nom'),
    'report_place_no_map' => t('reported places on a map this server’s client data does not name', 'lieux signalés sur une carte que les données client de ce serveur ne nomment pas'),
    'report_drop_not_counted' => t('drops given as a bare percentage (Classic’s, not counted by players)', 'butins donnés en simple pourcentage (ceux de Classic, non comptés par des joueurs)'),
    'text_known' => t('turn-in texts of quests that already have a row for that window (left as they are)', 'textes de rendu de quêtes qui ont déjà une ligne pour cette fenêtre (laissés tels quels)'),
    'report_text_may_hold_a_name' => t('turn-in texts with a capitalised word no other quest uses (it may be the recording player’s name: not taken)', 'textes de rendu avec un mot en majuscule qu’aucune autre quête n’emploie (peut-être le nom du joueur : non repris)'),
    'report_text_names_class_or_race' => t('turn-in texts that name a class or a race in plain words (it may be the player’s: not taken)', 'textes de rendu qui nomment une classe ou une race en clair (peut-être celle du joueur : non repris)'),
    'report_text_unknown_mark' => t('turn-in texts with a mark the tracker does not know', 'textes de rendu avec une marque que le tracker ne connaît pas'),
    'report_text_empty' => t('turn-in texts that are empty', 'textes de rendu vides'),
    'report_drop_world' => t('drops of items that fifteen or more different creatures drop (world drops: nobody’s own loot)', 'butins d’objets que quinze créatures différentes ou plus laissent tomber (butin mondial : le butin propre de personne)'),
    'report_drop_seen_once' => t('drops players saw once (a sighting, not a rate)', 'butins vus une seule fois par les joueurs (une observation, pas un taux)'),
    'report_drop_few_kills' => t('drops counted in fewer than ten kills', 'butins comptés sur moins de dix morts'),
    'quest_value_gone' => t('quests with a value the recording does not state (a reward, a text): a recording never empties a value, so it stays', 'quêtes dont une valeur n’est pas indiquée par l’enregistrement (une récompense, un texte) : un enregistrement ne vide jamais une valeur, elle reste'),
    'quest_reputation_other_form' => t('quests whose reputation is written another way than the recording (tier or points) and could not be compared', 'quêtes dont la réputation est écrite autrement que dans l’enregistrement (palier ou points) et n’a pas pu être comparée'),
    'quest_same' => t('quests the server has that say what the newest recording of the live game says', 'quêtes du serveur qui disent ce que dit l’enregistrement le plus récent du jeu'),
    'quest_row_newer' => t('quests whose row is from the same client build as the recording, or a later one (the row is the newer word: not changed)', 'quêtes dont la ligne vient du même build client que l’enregistrement, ou d’un plus récent (inchangées)'),
    'quest_mechanics_differ' => t('quests whose type, flags, start item, time limit, zone, races or next quest differ from the recording (counted, never changed here)', 'quêtes dont le type, les drapeaux, l’objet de départ, la durée, la zone, les races ou la quête suivante diffèrent de l’enregistrement (comptées, jamais modifiées ici)'),
    'quest_record_unreadable' => t('quests whose recording does not fit the columns (not compared)', 'quêtes dont l’enregistrement ne tient pas dans les colonnes (non comparées)'),
    'quest_refresh_failed' => t('the quests the server has could not be compared with the recording this time (see the PHP error log)', 'les quêtes du serveur n’ont pas pu être comparées à l’enregistrement cette fois (voir le journal d’erreurs PHP)'),
    'loot_chance_unknown' => t('drops without a known chance', 'butins sans chance connue'), 'loot_unknown_creature' => t('drops of creatures or chests unknown to this server', 'butins de PNJ ou coffres inconnus de ce serveur'),
    'trainer_known' => t('spells the trainer already teaches', 'sorts que l’entraîneur enseigne déjà'), 'trainer_not_on_server' => t('trainers unknown to this server', 'entraîneurs inconnus de ce serveur'),
    'trainer_level_unknown' => t('class spells without a known level', 'sorts de classe sans niveau connu'), 'trainer_previous_rank_unknown' => t('higher ranks whose previous rank is unknown', 'rangs supérieurs dont le rang précédent est inconnu'),
    'trainer_skill_unknown' => t('profession entries with an unknown skill', 'entrées de métier à la compétence inconnue'), 'trainer_profession_skill_unknown' => t('profession entries without a skill rank', 'entrées de métier sans rang de compétence'),
    'phase_not_open' => t('gap items and quests of a release phase that is not open yet (not looked at)', 'objets et quêtes manquants d’une phase de sortie pas encore ouverte (non consultés)'),
    'trainer_phase_not_open' => t('trainer spells of a release phase that is not open yet', 'sorts d’entraîneur d’une phase de sortie pas encore ouverte'),
    // Wowhead pages (app/wowheadpages.php)
    'wowhead_item_not_read' => t('gap items whose Wowhead page has not been read yet (python tools/wowhead_pages.py todo lists them for the crawler)', 'objets manquants dont la page Wowhead n’a pas encore été lue (python tools/wowhead_pages.py todo les liste pour le crawler)'),
    'wowhead_quest_not_read' => t('quests without a giver or an ender whose Wowhead page has not been read yet', 'quêtes sans donneur ou sans valideur dont la page Wowhead n’a pas encore été lue'),
    'wowhead_item_unknown' => t('gap items Wowhead has no page for', 'objets manquants pour lesquels Wowhead n’a pas de page'),
    'wowhead_no_source' => t('gap items whose Wowhead page names no source at all', 'objets manquants dont la page Wowhead ne nomme aucune source'),
    'wowhead_only_other_source' => t('gap items Wowhead only knows from a quest reward, a craft, a container, skinning, pick pocketing or fishing (not written by this import)', 'objets manquants que Wowhead ne connaît que par une récompense de quête, un artisanat, un conteneur, le dépeçage, le vol à la tire ou la pêche (non écrits par cet import)'),
    'wowhead_drop_world' => t('drops of items that fifteen or more different creatures drop (world drops: nobody’s own loot)', 'butins d’objets que quinze créatures différentes ou plus laissent tomber (butin mondial : le butin propre de personne)'),
    'wowhead_classic_forever_counted' => t('Classic drops of gap items that Forever’s own pages count well enough: Forever’s count is the one taken', 'butins Classic d’objets manquants que les pages de Forever comptent assez : c’est le décompte de Forever qui est pris'),
    'wowhead_other_loot' => t('gap items an npc page gives as skinning or pick pocketing loot (tables no source fills)', 'objets manquants qu’une page de PNJ donne comme butin de dépeçage ou de vol à la tire (tables qu’aucune source ne remplit)'),
    'wowhead_drop_item_page_not_read' => t('creature drops of gap items whose own page is not read yet: only it tells a world drop from a creature\'s own loot', 'butins de créatures d’objets manquants dont la page n’est pas encore lue : elle seule distingue un butin mondial du butin propre à une créature'),
    'wowhead_drop_few' => t('drops players saw once, or counted in fewer than ten loots (a sighting, not a rate)', 'butins vus une seule fois, ou comptés sur moins de dix butins (une observation, pas un taux)'),
    'wowhead_drop_not_counted' => t('drops Wowhead gives without counts', 'butins que Wowhead donne sans décompte'),
    'wowhead_vendor_other_cost' => t('vendor stock paid with a currency or with items (no cost to give it)', 'articles de marchand payés avec une monnaie ou des objets (pas de coût à leur donner)'),
    'wowhead_quest_unknown' => t('quests Wowhead has no page for', 'quêtes pour lesquelles Wowhead n’a pas de page'),
    'wowhead_quest_started_by_item' => t('quests an item starts (no giver to write)', 'quêtes lancées par un objet (pas de donneur à écrire)'),
    // Wowhead quest enders (app/wowhead.php)
    'not_looked_up_yet' => t('quests not looked up on Wowhead yet (run it again)', 'quêtes pas encore consultées sur Wowhead (relancez)'),
    'not_on_wowhead' => t('quests Wowhead does not know', 'quêtes inconnues de Wowhead'),
    'no_ender_named' => t('quests whose Wowhead summary names nobody to return to', 'quêtes dont le résumé Wowhead ne nomme personne chez qui revenir'),
    'name_not_on_server' => t('enders Wowhead names that no spawned creature of this server is called', 'valideurs nommés par Wowhead dont aucun PNJ placé de ce serveur ne porte le nom'),
    'name_not_unique' => t('enders Wowhead names that several spawned creatures are called', 'valideurs nommés par Wowhead dont plusieurs PNJ placés portent le nom'),
    'icyveins_vendor_other_cost' => t('vendor stock paid with items or a currency (no cost to give it)', 'articles de marchand payés avec des objets ou une monnaie (pas de coût à leur donner)'),
    'icyveins_loot_spell_unknown' => t('loot taken with a spell other than Skinning or Pick Pocket (no table for it)', 'butins pris avec un autre sort que Dépeçage ou Vol à la tire (pas de table pour eux)'),
    'icyveins_service_unknown' => t('NPC services Icy Veins numbers in a way this tracker does not know yet', 'services de PNJ numérotés par Icy Veins d’une façon que ce tracker ne connaît pas encore'),
    'icyveins_service_npc_unknown' => t('NPCs with recorded services that this server has no template for', 'PNJ aux services enregistrés dont ce serveur n’a pas le modèle'),
    'icyveins_trainer_list_not_a_trainer' => t('trainer entries recorded on NPCs that offer no training (bankers, innkeepers: a stray list in the recording)', 'entrées d’entraîneur enregistrées sur des PNJ qui n’entraînent pas (banquiers, aubergistes : une liste égarée dans l’enregistrement)'),
    'icyveins_container_no_chance' => t('items opened from another item (clams, lockboxes): Icy Veins records no chance for them, kept in the mirror', 'objets tirés d’un autre objet (palourdes, coffrets) : Icy Veins n’enregistre pas de chance, gardés dans le miroir'),
    'icyveins_kept_levels' => t('NPCs with levels players recorded (kept in the mirror, not compared yet)', 'PNJ aux niveaux enregistrés par les joueurs (gardés dans le miroir, pas encore comparés)'),
    'icyveins_kept_coin' => t('NPCs with the money players looted from them (kept in the mirror, not compared yet)', 'PNJ avec l’argent que les joueurs y ont ramassé (gardés dans le miroir, pas encore comparés)'),
    'icyveins_kept_gossip' => t('NPCs with what they say when spoken to (kept in the mirror, not compared yet)', 'PNJ avec ce qu’ils disent quand on leur parle (gardés dans le miroir, pas encore comparés)'),
    'icyveins_kept_positions' => t('NPCs and objects with positions players recorded (the locator reads them)', 'PNJ et objets aux positions enregistrées par les joueurs (le localisateur les lit)'),
    'icyveins_kept_flight_paths' => t('flight paths with their routes (kept in the mirror)', 'trajets aériens avec leurs routes (gardés dans le miroir)'),
    'icyveins_kept_zones' => t('zones with the NPCs and objects seen in them (kept in the mirror)', 'zones avec les PNJ et objets qu’on y a vus (gardées dans le miroir)'),
    'icyveins_early_card' => t('an early card from the gaps’ answers alone, made while the rest of Icy Veins is still being read: the full card replaces it when the run ends, unless something was applied from it', 'une carte anticipée, faite des seules réponses sur les manques pendant que le reste d’Icy Veins est encore lu : la carte complète la remplace à la fin, sauf si quelque chose en a été appliqué'),
    'icyveins_lookup_limit_reached_run_again' => t('Icy Veins lookup limit of one run reached: run it again for the rest', 'limite de consultations Icy Veins d’un passage atteinte : relancez pour la suite'),
];
$megabytes = fn(int $bytes) => number($bytes / 1048576, 1) . ' MB';
page_start(t('Imports', 'Imports'), 'admin');
?>
<section class="page-head is-forge">
  <div class="page-title">
    <span class="page-icon is-gold"><i class="fas fa-file-import"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Imports', 'Imports')) ?></h1>
    <p><?= e(t('What the ForeverScribe addon noted while you played, and world data files in WowPacketParser\'s SQL format: vendors, loot, quest givers, spawns. ForeverTracker adds only what your server lacks — nothing is deleted or overwritten — and every operation can be rolled back.', 'Ce que l’addon ForeverScribe a noté pendant que vous jouiez, et les fichiers de données du monde au format SQL de WowPacketParser : marchands, butin, donneurs de quête, placements. ForeverTracker n’ajoute que ce qui manque à votre serveur (rien n’est supprimé ni écrasé) et chaque opération peut être annulée.')) ?></p></div>
  </div>
</section>

<nav class="tabs" aria-label="Forge">
  <a href="<?= e(url('admin')) ?>"><i class="fas fa-hammer"></i><?= e(t('Fixes', 'Corrections')) ?></a>
  <a href="<?= e(url('admin', ['tab' => 'vendor'])) ?>"><i class="fas fa-gem"></i><?= e(t('Items', 'Objets')) ?></a>
  <a href="<?= e(url('admin/spawns')) ?>"><i class="fas fa-location-crosshairs"></i><?= e(t('Spawns', 'Placements')) ?></a>
  <a class="is-active" href="<?= e(url('admin/imports')) ?>"><i class="fas fa-file-import"></i><?= e(t('Imports', 'Imports')) ?><em><?= count($imports) ?></em></a>
  <a href="<?= e(url('admin/checks')) ?>"><i class="fas fa-scale-balanced"></i><?= e(t('Checks', 'Contrôles')) ?></a>
  <a href="<?= e(url('admin/history')) ?>"><i class="fas fa-clock-rotate-left"></i><?= e(t('History', 'Historique')) ?></a>
</nav>

<?php require_once FT_APP . '/snapshots.php'; $snapshots = snapshot_latest(); ?>
<section class="block import-add" id="source-snapshots">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Kept in this tracker’s database', 'Conservé dans la base de ce tracker')) ?></span><h2><?= e(t('What the sources said', 'Ce que disent les sources')) ?></h2></div></header>
  <p class="muted small"><?= e(t('Each import keeps what its source said (who drops, sells, teaches, gives or takes what) as a snapshot in this tracker’s own database, never in the repository: a fact is kept once, with the first and last run that said it. Below, each source’s last run against the one before.', 'Chaque import conserve ce que dit sa source (qui donne, vend, enseigne, propose ou valide quoi) comme un instantané dans la base de ce tracker, jamais dans le dépôt : un fait est gardé une fois, avec le premier et le dernier passage qui l’a dit. Ci-dessous, le dernier passage de chaque source comparé au précédent.')) ?></p>
  <?php if (!$snapshots): ?>
    <p class="muted small"><?= e(t('No import has run since snapshots were kept.', 'Aucun import n’a tourné depuis que les instantanés sont conservés.')) ?></p>
  <?php else: ?>
  <table class="table is-forge">
    <thead><tr><th><?= e(t('Source', 'Source')) ?></th><th><?= e(t('Version', 'Version')) ?></th><th><?= e(t('Run', 'Passage')) ?></th><th><?= e(t('Facts', 'Faits')) ?></th><th><?= e(t('New', 'Nouveaux')) ?></th><th><?= e(t('Changed', 'Modifiés')) ?></th><th><?= e(t('Gone', 'Disparus')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($snapshots as $source => $snap): $changes = (int)$snap['added'] + (int)$snap['changed'] + (int)$snap['gone'] ? snapshot_changes((int)$snap['id'], 25) : null; ?>
      <tr>
        <td><?= e(SOURCES[$source][0] ?? $source) ?></td>
        <td><code><?= e(mb_strimwidth((string)$snap['version'], 0, 16, '…')) ?></code></td>
        <td><?= e(substr((string)$snap['made'], 0, 16)) ?></td>
        <td><?= e(number((int)$snap['facts'])) ?><?= $snap['scope'] !== 'all' ? ' <small class="muted" title="' . e(t('this source is asked about the gaps only: what it did not say is not gone, only not asked', 'cette source n’est interrogée que sur les manques : ce qu’elle n’a pas dit n’a pas disparu, il n’a pas été demandé')) . '">' . e(t('gaps', 'manques')) . '</small>' : '' ?></td>
        <td><?= e(number((int)$snap['added'])) ?></td>
        <td><?= e(number((int)$snap['changed'])) ?></td>
        <td><?= $snap['scope'] === 'all' ? e(number((int)$snap['gone'])) : '–' ?></td>
      </tr>
      <?php if ($changes): ?>
      <tr><td colspan="7"><details><summary class="small"><?= e(t('The first of them', 'Les premiers')) ?></summary><ul class="small">
        <?php $say = fn($r) => $r['fact'] . ' ' . ($r['kind'] ? $r['kind'] . ' ' : '') . $r['entity'] . ' → ' . $r['target'] . ($r['value'] !== null ? ' (' . rtrim(rtrim(number_format((float)$r['value'], 4, '.', ''), '0'), '.') . ')' : ''); ?>
        <?php foreach ($changes['added'] as $r): ?><li>+ <?= e($say($r)) ?></li><?php endforeach; ?>
        <?php foreach ($changes['changed'] as [$old, $new]): ?><li>~ <?= e($say($new)) ?> <span class="muted"><?= e(t('was', 'était')) ?> <?= e($old['value'] ?? '–') ?></span></li><?php endforeach; ?>
        <?php foreach ($changes['gone'] as $r): ?><li>− <?= e($say($r)) ?></li><?php endforeach; ?>
      </ul></details></td></tr>
      <?php endif; ?>
    <?php endforeach; ?>
    </tbody>
  </table>
  <?php endif; ?>
</section>

<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Collect while you play', 'Collecter en jouant')) ?></span><h2><?= e(t('The ForeverScribe addon', 'L’addon ForeverScribe')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('Install ForeverScribe in your game. It only uses the normal addon API: it notes what the game shows you — what vendors sell, what creatures and chests drop, who gives and takes quests, where creatures stand. It collects only on the official realms and pauses by itself on private servers (/scribe on · off · auto). No character, realm or account name is kept.', 'Installez ForeverScribe dans votre jeu. Il n’utilise que l’API normale des addons : il note ce que le jeu vous montre — ce que vendent les marchands, ce que lâchent les PNJ et les coffres, qui donne et valide les quêtes, où se tiennent les PNJ. Il ne collecte que sur les royaumes officiels et se met en pause tout seul sur les serveurs privés (/scribe on · off · auto). Aucun nom de personnage, de royaume ou de compte n’est gardé.')) ?></li>
    <li><?= e(t('Play: open vendors, loot, talk to quest givers. /scribe shows what was noted. The notes are saved when you log out or /reload.', 'Jouez : ouvrez les marchands, ramassez le butin, parlez aux donneurs de quête. /scribe montre ce qui a été noté. Les notes sont enregistrées quand vous vous déconnectez ou faites /reload.')) ?></li>
    <li><?= e(t('ForeverTracker imports the new notes by itself while the launcher runs, or press Import new notes. Vendors, loot and quest givers become an import below; where creatures stand feeds the locator (Spawns).', 'ForeverTracker importe les nouvelles notes tout seul tant que le lanceur tourne, ou appuyez sur Importer les nouvelles notes. Marchands, butin et donneurs de quête deviennent un import ci-dessous ; les positions des PNJ alimentent le localisateur (Placements).')) ?></li>
  </ol>
  <div class="btn-row">
    <button class="btn is-small" type="button" data-scribe="scribe_install" <?= $clientAddons === '' ? 'disabled' : '' ?>><i class="fas fa-download"></i> <?= e($scribeInstalled ? t('Update the addon in the game', 'Mettre à jour l’addon dans le jeu') : t('Install into the game', 'Installer dans le jeu')) ?></button>
    <button class="btn is-small" type="button" data-scribe="scribe_zip"><i class="fas fa-file-zipper"></i> <?= e(t('Download the addon', 'Télécharger l’addon')) ?></button>
    <button class="btn is-small is-gold" type="button" data-scribe="sync"><i class="fas fa-rotate"></i> <?= e(t('Import new notes', 'Importer les nouvelles notes')) ?></button>
  </div>
  <ul class="list is-compact import-waiting">
    <?php foreach ($scribeFiles as $f): $new = ($scribeState[$f['path']] ?? '') !== sha1_file($f['path']); ?><li><span class="fix-kind is-small"><i class="fas fa-feather"></i></span><div class="list-main"><strong>ForeverScribe · <?= e($f['flavor']) ?></strong><small><?= e(date(t('M j, H:i', 'd/m H:i'), $f['modified'])) ?> · <?= e($new ? t('new notes to import', 'nouvelles notes à importer') : t('imported', 'importé')) ?></small></div></li><?php endforeach; ?>
    <?php if (!$scribeFiles): ?><li class="muted small"><?= e($clientAddons === '' ? t('Set [client] path in config.ini to find the notes in your game folder, or send ForeverScribe.lua below.', 'Renseignez [client] path dans config.ini pour trouver les notes dans le dossier du jeu, ou envoyez ForeverScribe.lua ci-dessous.') : t('No notes yet: play with the addon, then log out or /reload.', 'Pas encore de notes : jouez avec l’addon, puis déconnectez-vous ou faites /reload.')) ?></li><?php endif; ?>
    <?php if ($located): ?><li class="small"><span class="muted"><?= e(sprintf(t('%d creature(s) or object(s) located by ForeverScribe. The locator uses them by itself after each import: the ones your server needs and lacks show as Ready in Spawns, marked "seen in game".', '%d PNJ ou objet(s) localisés par ForeverScribe. Le localisateur les utilise tout seul après chaque import : ceux dont votre serveur a besoin et qui lui manquent apparaissent comme Prêts dans Placements, marqués « seen in game ».'), $located)) ?></span> <a class="link" href="<?= e(url('admin/spawns')) ?>"><?= e(t('Open Spawns', 'Ouvrir Placements')) ?> →</a></li><?php endif; ?>
  </ul>
</section>

<?php require_once FT_APP . '/sources.php'; $icyRunning = source_running('icyveins'); $icyLog = is_file(source_log('icyveins')) ? trim((string)@shell_exec('tail -n 1 ' . escapeshellarg(source_log('icyveins')))) : ''; ?>
<?php $refreshedAt = source_refresh_epoch(); ?>
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Freshness', 'Fraîcheur')) ?></span><h2><?= e(t('How old an answer may be', 'L’âge permis d’une réponse')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('Answers are kept so that a source is not asked the same thing at every run, and they come due again by themselves: Wowhead after about a month (a week for what it did not know), Icy Veins after two weeks (one for what it did not know). EG Link, ForeverDB.net and AtlasLoot are read in their newest version at every import.', 'Les réponses sont conservées pour ne pas reposer la même question à chaque exécution, et elles redeviennent dues d’elles-mêmes : Wowhead après un mois environ (une semaine pour ce qu’il ne connaissait pas), Icy Veins après deux semaines (une pour ce qu’il ne connaissait pas). EG Link, ForeverDB.net et AtlasLoot sont lus dans leur dernière version à chaque import.')) ?></li>
    <li><?= e(t('Ask every source again: every answer kept so far counts as due, whatever its age. Nothing is asked now and nothing is deleted: the next analysis asks Wowhead again, the next imports their sources. Those runs take as long as the very first ones did (Wowhead and Icy Veins are asked one question at a time); a run that is cut short goes on from where it stopped.', 'Tout redemander : chaque réponse conservée compte comme due, quel que soit son âge. Rien n’est demandé maintenant et rien n’est supprimé : la prochaine analyse réinterroge Wowhead, les prochains imports leurs sources. Ces exécutions durent autant que les toutes premières (Wowhead et Icy Veins répondent à une question à la fois) ; une exécution interrompue reprend où elle s’est arrêtée.')) ?></li>
  </ol>
  <div class="btn-row">
    <button class="btn is-small" type="button" data-scribe="refresh_sources"><i class="fas fa-rotate"></i> <?= e(t('Ask every source again', 'Tout redemander aux sources')) ?></button>
  </div>
  <?php if ($refreshedAt): ?><p class="muted small"><?= e(sprintf(t('Last pressed %s: answers older than that are asked again.', 'Dernier appui le %s : les réponses plus anciennes sont redemandées.'), date(t('M j, Y H:i', 'd/m/Y H:i'), $refreshedAt))) ?></p><?php endif; ?>
</section>
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Live Forever recordings', 'Enregistrements de Forever')) ?></span><h2><?= e(t('EG Link, ForeverDB.net, Icy Veins', 'EG Link, ForeverDB.net, Icy Veins')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('Three projects whose players\' addons record what live WoW Forever shows: vendor windows, loot, trainers, who gives and takes quests. Each import aims at the last analysis\' gaps, with the same rules as NorgannonDB (docs/SOURCES.md).', 'Trois projets dont les addons des joueurs enregistrent ce que montre WoW Forever : marchands, butin, entraîneurs, donneurs et valideurs de quêtes. Chaque import vise les manques de la dernière analyse, avec les mêmes règles que NorgannonDB (docs/SOURCES.md).')) ?></li>
    <li><?= e(t('EG Link (CC BY 4.0) and ForeverDB.net (GPL-3.0, credit "Data from ForeverDB.net") are downloaded whole. Icy Veins (no licence stated: for your own server) is mirrored whole, the gaps first, two lookups a second, in the background: about nine hours the first time (every NPC, object, quest, item, zone and flight path it lists, some 67,000). A restart stops it: the container goes on with it by itself at its next start (anywhere else, press the button again), from what it already asked. When Icy Veins stops answering, the run slows down, then stops after 20 lookups without an answer and says so below. Its answers are asked again after two weeks as it grows.', 'EG Link (CC BY 4.0) et ForeverDB.net (GPL-3.0, crédit « Data from ForeverDB.net ») sont téléchargés en entier. Icy Veins (sans licence : pour votre serveur) est copié en entier, les manques d’abord, deux requêtes par seconde, en arrière-plan : environ neuf heures la première fois (chaque PNJ, objet, quête, objet d’inventaire, zone et trajet aérien qu’il liste, quelque 67 000). Un redémarrage l’arrête : le conteneur le reprend tout seul à son prochain démarrage (ailleurs, relancez-le), là où il en était. Quand Icy Veins ne répond plus, l’import ralentit, puis s’arrête après 20 requêtes sans réponse et le dit ci-dessous. Ses réponses sont redemandées après deux semaines.')) ?></li>
  </ol>
  <div class="btn-row">
    <button class="btn is-small is-gold" type="button" data-scribe="source_eglink"><i class="fas fa-link"></i> <?= e(t('Import EG Link', 'Importer EG Link')) ?></button>
    <button class="btn is-small is-gold" type="button" data-scribe="source_foreverdb"><i class="fas fa-book-atlas"></i> <?= e(t('Import ForeverDB.net', 'Importer ForeverDB.net')) ?></button>
    <button class="btn is-small is-gold" type="button" data-scribe="source_icyveins" <?= $icyRunning ? 'disabled' : '' ?>><i class="fas fa-snowflake"></i> <?= e($icyRunning ? t('Icy Veins: running…', 'Icy Veins : en cours…') : t('Import Icy Veins', 'Importer Icy Veins')) ?></button>
  </div>
  <?php if ($icyLog !== ''): ?><p class="muted small">Icy Veins: <?= e($icyLog) ?></p><?php endif; ?>
</section>

<?php $fcPack = foreverchanges_pack(); ?>
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Players’ reports, from a file', 'Rapports de joueurs, depuis un fichier')) ?></span><h2>ForeverChanges</h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('foreverchanges.pro collects what its players’ addon saw on live WoW Forever, over a base of Classic’s data. The tracker never asks the site: it reads a pack made from a copy of it you already have (python tools/foreverchanges_pack.py copy.db out.fcpack, a few MB).', 'foreverchanges.pro rassemble ce que l’addon de ses joueurs a vu sur WoW Forever, par-dessus les données de Classic. Le tracker n’interroge jamais le site : il lit un paquet créé à partir d’une copie que vous avez déjà (python tools/foreverchanges_pack.py copie.db sortie.fcpack, quelques Mo).')) ?></li>
    <li><?= e(t('The site names NPCs and places them on a map. A name becomes the server’s creature of that name that stands there; a name several creatures share with nothing to tell them apart is left out and counted, and so is a creature nobody spawned.', 'Le site nomme les PNJ et les place sur une carte. Un nom devient la créature du serveur de ce nom qui s’y trouve ; un nom partagé par plusieurs créatures sans rien pour les distinguer est écarté et compté, comme une créature que personne n’a placée.')) ?></li>
    <li><?= e(t('Only what its players saw counts: who gives and takes a quest marked as seen by players, vendors, and drops counted in at least ten kills. Classic’s lines (a quest nobody saw, a bare percentage) are left out.', 'Seul ce que ses joueurs ont vu compte : qui donne et valide une quête marquée comme vue, les marchands, et les butins comptés sur au moins dix morts. Les lignes de Classic (une quête que personne n’a vue, un simple pourcentage) sont écartées.')) ?></li>
  </ol>
  <div class="btn-row">
    <form class="import-upload" data-import-upload><label class="btn is-small is-gold"><i class="fas fa-file-arrow-up"></i> <?= e(t('Send a .fcpack file', 'Envoyer un fichier .fcpack')) ?><input type="file" accept=".fcpack" hidden></label></form>
    <?php if (is_file($fcPack)): ?><button class="btn is-small" type="button" data-scribe="source_foreverchanges"><i class="fas fa-rotate"></i> <?= e(t('Read the pack again', 'Relire le paquet')) ?></button>
      <small class="muted"><?= e(sprintf(t('Pack of %s, %s.', 'Paquet du %s, %s.'), date(t('M j, Y H:i', 'd/m/Y H:i'), (int)filemtime($fcPack)), $megabytes((int)filesize($fcPack)))) ?></small><?php endif; ?>
  </div>
</section>

<?php $cdbPack = classicdb_pack(); ?>
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('The original game, from a file', 'Le jeu d’origine, depuis un fichier')) ?></span><h2><?= e(t('Classic database', 'Base de données Classic')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('cmangos’ classic-db (GPL-3.0) is the content of the 1.12 game, not of WoW: Forever. The tracker never downloads it: it reads a pack made from the project’s own dump (python tools/classicdb_pack.py ClassicDB_1_12_1_….sql.gz out.cdbpack, about 150 kB).', 'classic-db de cmangos (GPL-3.0) est le contenu du jeu 1.12, pas de WoW: Forever. Le tracker ne le télécharge jamais : il lit un paquet créé à partir de l’export du projet (python tools/classicdb_pack.py ClassicDB_1_12_1_….sql.gz sortie.cdbpack, environ 150 ko).')) ?></li>
    <li><?= e(t('It is the last source asked, and only about profession recipes nobody can learn on this server: the trainers that taught them, and the quests whose turn-in cast them. A quest gets the spell only where it casts nothing yet.', 'C’est la dernière source consultée, et seulement pour les recettes de métier que personne ne peut apprendre sur ce serveur : les entraîneurs qui les enseignaient, et les quêtes dont le rendu les lançait. Une quête ne reçoit le sort que si elle n’en lance aucun.')) ?></li>
    <li><?= e(t('A recipe the original game teaches through a line of a creature’s or an object’s conversation becomes that line, with Classic’s conditions and a SmartAI script that teaches it. A creature run by a core script or another AI, or a conversation others share, is counted, not written. A pack made by an older tools/classicdb_pack.py carries no lines: make it again.', 'Une recette que le jeu d’origine enseigne par une réplique d’un PNJ ou d’un objet devient cette réplique, avec les conditions de Classic et un script SmartAI qui l’enseigne. Un PNJ mené par un script du cœur ou une autre IA, ou une conversation partagée, est compté, pas écrit. Un paquet créé par un ancien tools/classicdb_pack.py ne contient aucune réplique : recréez-le.')) ?></li>
  </ol>
  <div class="btn-row">
    <form class="import-upload" data-import-upload><label class="btn is-small is-gold"><i class="fas fa-file-arrow-up"></i> <?= e(t('Send a .cdbpack file', 'Envoyer un fichier .cdbpack')) ?><input type="file" accept=".cdbpack" hidden></label></form>
    <?php if (is_file($cdbPack)): ?><button class="btn is-small" type="button" data-scribe="source_classicdb"><i class="fas fa-rotate"></i> <?= e(t('Read the pack again', 'Relire le paquet')) ?></button>
      <small class="muted"><?= e(sprintf(t('Pack of %s, %s.', 'Paquet du %s, %s.'), date(t('M j, Y H:i', 'd/m/Y H:i'), (int)filemtime($cdbPack)), number((int)filesize($cdbPack) / 1024, 0) . ' kB')) ?></small><?php endif; ?>
  </div>
</section>

<?php $alLog = is_file(source_log('atlasloot')) ? trim((string)@shell_exec('tail -n 1 ' . escapeshellarg(source_log('atlasloot')))) : ''; ?>
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Addon data', 'Données d’addon')) ?></span><h2>AtlasLoot Classic Forever</h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('The loot browser most Forever players run (GPL-2.0, CurseForge), updated almost daily: which boss drops each item, Forever\'s new dungeons and items included. The newest Forever file is downloaded from CurseForge.', 'Le navigateur de butin de la plupart des joueurs de Forever (GPL-2.0, CurseForge), mis à jour presque chaque jour : quel boss lâche chaque objet, nouveaux donjons et objets de Forever compris. Le fichier Forever le plus récent est téléchargé depuis CurseForge.')) ?></li>
    <li><?= e(t('Drops for the items players cannot get, at the boss AtlasLoot names (a new dungeon\'s boss by its name). The chance: AtlasLoot\'s measured one, else a live Forever recording\'s, else an even share of the boss\'s list (the card says how many; FT_ATLASLOOT_GUESS=0 leaves those out). Its boss tables also count as a second source for NorgannonDB\'s drops.', 'Le butin des objets introuvables, sur le boss que nomme AtlasLoot (celui d’un nouveau donjon par son nom). La chance : celle mesurée par AtlasLoot, sinon celle d’un enregistrement de Forever, sinon une part égale de la liste du boss (la carte dit combien ; FT_ATLASLOOT_GUESS=0 les écarte). Ses tables comptent aussi comme seconde source pour le butin de NorgannonDB.')) ?></li>
    <li><?= e(t('The container checks CurseForge every few hours (FT_ATLASLOOT_EVERY_HOURS) and makes a new card when a new version is out. Nothing is applied by itself.', 'Le conteneur consulte CurseForge toutes les quelques heures (FT_ATLASLOOT_EVERY_HOURS) et crée une carte à chaque nouvelle version. Rien n’est appliqué tout seul.')) ?></li>
  </ol>
  <div class="btn-row">
    <button class="btn is-small is-gold" type="button" data-scribe="source_atlasloot"><i class="fas fa-book-skull"></i> <?= e(t('Import AtlasLoot', 'Importer AtlasLoot')) ?></button>
  </div>
  <?php if ($alLog !== ''): ?><p class="muted small">AtlasLoot: <?= e($alLog) ?></p><?php endif; ?>
</section>

<?php require_once FT_APP . '/wowheadpages.php'; $whPages = array_combine(['item', 'quest', 'npc', 'object', 'classic-npc', 'classic-object'], array_map('wowhead_pages_count', ['item', 'quest', 'npc', 'object', 'classic-npc', 'classic-object'])); ?>
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Players’ counts', 'Décomptes des joueurs')) ?></span><h2><?= e(t('Wowhead pages', 'Pages Wowhead')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('Wowhead’s tooltips say what WoW Forever has; its pages say where it comes from: the creatures and chests that drop an item and how often players saw it, who sells it, who starts and ends a quest. Wowhead answers page requests from a server with “forbidden”, so the pages are read slowly in your own browser, and this tracker asks Wowhead for nothing.', 'Les infobulles de Wowhead disent ce que WoW Forever contient ; ses pages disent d’où cela vient : les créatures et coffres qui donnent un objet et à quelle fréquence les joueurs l’ont vu, qui le vend, qui donne et valide une quête. Wowhead refuse les requêtes de pages venant d’un serveur : elles sont donc lues lentement dans votre propre navigateur, et ce tracker ne demande rien à Wowhead.')) ?></li>
    <li><?= e(t('Download the crawler: the pages this tracker wants next are already in it, the ones other content waits for first. Open wowhead.com/forever in a browser tab, open its developer console (F12), paste the file and press Enter. Leave the tab open: it reads a page every half minute or so, finds by itself how fast Wowhead lets it go, and waits when Wowhead says to. Pasting it again after a reload goes on where it stopped.', 'Téléchargez le crawler : les pages que ce tracker veut ensuite y sont déjà, d’abord celles que d’autres contenus attendent. Ouvrez wowhead.com/forever dans un onglet, ouvrez sa console (F12), collez le fichier et validez. Laissez l’onglet ouvert : il lit une page toutes les trente secondes environ, trouve seul l’allure que Wowhead tolère et attend quand Wowhead le demande. Le recoller après un rechargement reprend où il s’était arrêté.')) ?></li>
    <li><?= e(t('Type WHC.save() in that console at any time: it downloads wowhead-pages.jsonl. Send that file here: the pages are kept (numbers only, no name or text of a page) and an import card is made from all of them. Then download the crawler again for the next pages.', 'Tapez WHC.save() dans cette console quand vous voulez : cela télécharge wowhead-pages.jsonl. Envoyez ce fichier ici : les pages sont conservées (des nombres seulement, aucun nom ni texte) et une carte d’import est faite de toutes. Retéléchargez ensuite le crawler pour les pages suivantes.')) ?></li>
  </ol>
  <p class="muted small"><?= e(sprintf(t('Pages kept: %s item, %s quest, %s npc and %s object pages of Forever; %s npc and %s object pages of Classic.', 'Pages conservées : %s pages d’objets, %s de quêtes, %s de PNJ et %s d’objets du monde de Forever ; %s de PNJ et %s d’objets du monde de Classic.'), number($whPages['item']), number($whPages['quest']), number($whPages['npc']), number($whPages['object']), number($whPages['classic-npc']), number($whPages['classic-object']))) ?></p>
  <div class="btn-row">
    <button class="btn is-small" type="button" data-scribe="wowhead_crawler"><i class="fas fa-download"></i> <?= e(t('Download the crawler', 'Télécharger le crawler')) ?></button>
    <button class="btn is-small" type="button" data-scribe="wowhead_crawler_full" title="<?= e(t('The same, then the whole database of Forever and Classic: days of pages', 'Le même, puis toute la base de Forever et Classic : des jours de pages')) ?>"><i class="fas fa-database"></i> <?= e(t('Download the full crawl', 'Télécharger le crawl complet')) ?></button>
    <form class="import-upload" data-import-upload><label class="btn is-small"><i class="fas fa-file-arrow-up"></i> <?= e(t('Send wowhead-pages.jsonl', 'Envoyer wowhead-pages.jsonl')) ?><input type="file" accept=".jsonl" hidden></label></form>
    <button class="btn is-small is-gold" type="button" data-scribe="source_wowhead" <?= $whPages['item'] + $whPages['quest'] + $whPages['npc'] + $whPages['object'] ? '' : 'disabled' ?>><i class="fas fa-book-open"></i> <?= e(t('Import Wowhead pages', 'Importer les pages Wowhead')) ?></button>
    <button class="btn is-small" type="button" data-scribe="source_wowheadclassic" title="<?= e(t('Drops Classic’s players counted, where Forever’s pages count too few', 'Les butins comptés par les joueurs de Classic, là où les pages de Forever en comptent trop peu')) ?>" <?= $whPages['classic-npc'] + $whPages['classic-object'] ? '' : 'disabled' ?>><i class="fas fa-clock-rotate-left"></i> <?= e(t('Import Classic pages', 'Importer les pages Classic')) ?></button>
  </div>
</section>

<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Open data', 'Données ouvertes')) ?></span><h2>NorgannonDB</h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('NorgannonDB is an open WoW Forever database (GPL-3.0) built from QuestieDB, pfQuest, Forever\'s own tables and what its players saw. The pinned version is downloaded from GitHub when you import it.', 'NorgannonDB est une base ouverte de WoW Forever (GPL-3.0) faite de QuestieDB, pfQuest, des tables de Forever et de ce que ses joueurs ont vu. La version épinglée est téléchargée depuis GitHub à l’import.')) ?></li>
    <li><?= e(t('The import aims at the gaps of the last analysis: drops and vendors for the items players cannot get (internal items left out), givers and enders for the quests that have none, and the spells its players saw trainers teach. Run the analysis again first when the server changed.', 'L’import vise les manques de la dernière analyse : butin et marchands des objets introuvables (objets internes écartés), donneurs et valideurs des quêtes qui n’en ont pas, et les sorts que ses joueurs ont vu enseigner. Relancez l’analyse d’abord si le serveur a changé.')) ?></li>
    <li><?= e(t('It becomes an import below: preview, apply what is missing, roll back from the history, export to your data repository.', 'Il devient un import ci-dessous : aperçu, appliquer ce qui manque, annuler depuis l’historique, exporter vers votre dépôt de données.')) ?></li>
  </ol>
  <p class="muted small"><?= e(t('Wowhead quest enders: for quests the server has no ender for, the NPC Wowhead\'s quest summary sends the player back to ("then return to Hamish Bergwort in the Tower of Azora"), when exactly one spawned creature has that name. Up to 500 new Wowhead lookups per run; run it again for the rest.', 'Valideurs de quête Wowhead : pour les quêtes sans valideur, le PNJ chez qui le résumé de quête de Wowhead renvoie le joueur, quand une seule créature placée porte ce nom. Jusqu’à 500 nouvelles consultations par passage ; relancez pour la suite.')) ?></p>
  <div class="btn-row"><button class="btn is-small" type="button" data-scribe="wowhead_quests"><i class="fas fa-route"></i> <?= e(t('Import Wowhead quest enders', 'Importer les valideurs de Wowhead')) ?></button><button class="btn is-small is-gold" type="button" data-scribe="norgannon"><i class="fas fa-database"></i> <?= e(t('Import NorgannonDB', 'Importer NorgannonDB')) ?></button></div>
</section>

<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Add a file', 'Ajouter un fichier')) ?></span><h2><?= e(t('SQL in WowPacketParser\'s format', 'SQL au format de WowPacketParser')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('Use a SQL file you already have in WowPacketParser\'s world format (usually ending in _world.sql), or any file of INSERT statements for your world tables.', 'Utilisez un fichier SQL que vous avez déjà, au format monde de WowPacketParser (il finit souvent par _world.sql), ou tout fichier d’INSERT pour vos tables du monde.')) ?></li>
    <li><?= e(sprintf(t('Send it here, or copy big files into %s and import them from the list below.', 'Envoyez-le ici, ou copiez les gros fichiers dans %s et importez-les depuis la liste ci-dessous.'), str_replace('\\', '/', $dir))) ?></li>
    <li><?= e(t('Preview what your server lacks, then apply it.', 'Prévisualisez ce qui manque à votre serveur, puis appliquez-le.')) ?></li>
  </ol>
  <form class="import-upload" data-import-upload>
    <label class="btn"><i class="fas fa-file-arrow-up"></i> <?= e(t('Choose a .sql or ForeverScribe.lua file', 'Choisir un fichier .sql ou ForeverScribe.lua')) ?><input type="file" accept=".sql,.lua" hidden></label>
    <small class="muted"><?= e(sprintf(t('Up to %s through the browser.', 'Jusqu’à %s par le navigateur.'), (string)ini_get('upload_max_filesize'))) ?></small>
  </form>
  <?php if ($waiting): ?>
  <ul class="list is-compact import-waiting">
    <?php foreach ($waiting as $w): ?><li><span class="fix-kind is-small"><i class="fas fa-file-code"></i></span><div class="list-main"><strong><?= e($w['file']) ?></strong><small><?= e($megabytes($w['size'])) ?> · <?= e(date(t('M j, H:i', 'd/m H:i'), $w['time'])) ?></small></div><button class="btn is-small is-gold" type="button" data-import-file="<?= e($w['file']) ?>"><i class="fas fa-file-import"></i> <?= e(t('Import', 'Importer')) ?></button></li><?php endforeach; ?>
  </ul>
  <?php endif; ?>
</section>

<?php if (!$imports): ?>
  <div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-file-import"></i></div><p><?= e(t('No file imported yet.', 'Aucun fichier importé pour le moment.')) ?></p></div>
<?php endif; ?>
<?php
// a source's earlier cards go below, folded: its newest card says all they said and is still true
$earlierIds = array_flip(import_earlier($imports));
$ordered = array_merge(array_values(array_filter($imports, fn($s) => !isset($earlierIds[(int)$s['id']]))), array_values(array_filter($imports, fn($s) => isset($earlierIds[(int)$s['id']]))));
$folded = false;
foreach ($ordered as $s): $counts = json_decode((string)$s['counts'], true) ?: []; $ignored = json_decode((string)$s['ignored'], true) ?: []; ?>
<?php if (!$folded && isset($earlierIds[(int)$s['id']])): $folded = true; ?>
<details class="import-earlier">
  <summary><i class="fas fa-clock-rotate-left"></i> <?= e(sprintf(t('Earlier cards of sources that have a newer one (%d)', 'Cartes précédentes de sources qui en ont une plus récente (%d)'), count($earlierIds))) ?>
    <small class="muted"><?= e(t('Kept because something was applied from them. The newest card of each source, above, is the one to apply.', 'Conservées car quelque chose en a été appliqué. La carte la plus récente de chaque source, ci-dessus, est celle à appliquer.')) ?></small></summary>
<?php endif; ?>
<article class="block import-card" data-import="<?= (int)$s['id'] ?>">
  <header class="op-head">
    <span class="fix-kind is-import"><i class="fas fa-file-import"></i></span>
    <div><strong>#<?= (int)$s['id'] ?> · <?= e($s['name']) ?></strong>
      <small><?= e($s['file']) ?> · <?= e(date(t('M j, Y H:i', 'd/m/Y H:i'), strtotime($s['imported_at']))) ?> · <?= number(array_sum($counts)) ?> <?= e(t('rows', 'lignes')) ?> · <?= number((int)$s['items']) ?> <?= e(t('item(s) made obtainable', 'objet(s) rendus obtenables')) ?></small></div>
    <button class="icon-btn is-small" type="button" data-import-delete title="<?= e(t('Forget this import (the server is not changed)', 'Oublier cet import (le serveur n’est pas modifié)')) ?>"><i class="fas fa-trash"></i></button>
  </header>
  <div class="import-tables">
    <?php foreach ($counts as $table => $n): ?>
      <label class="checkbox-line"><input type="checkbox" value="<?= e($table) ?>" checked> <span><?= e($tableLabels[$table] ?? (str_starts_with((string)$s['file'], 'classicdb@') && $table === 'quest_template.RewardSpell' ? t('Quests that cast nothing at the turn-in: the spell the original game cast', 'Quêtes qui ne lancent rien au rendu : le sort que lançait le jeu d’origine') : (preg_match('/^quest_[a-z_]+\.(\w+)$/', (string)$table, $m) ? sprintf(t('Quests the server has: %s changed on live', 'Quêtes du serveur : %s a changé en jeu'), $m[1]) : $table))) ?></span> <small class="muted"><?= e($table) ?> · <?= number($n) ?></small></label>
    <?php endforeach; ?>
  </div>
  <?php if ($ignored): ?><p class="muted small"><?= e(t('Left out:', 'Écarté :')) ?> <?= e(implode(', ', array_map(fn($t, $n) => ($leftLabels[$t] ?? $t) . " ($n)", array_keys($ignored), $ignored))) ?></p><?php endif; ?>
  <div class="btn-row">
    <button class="btn is-small" type="button" data-import-preview><i class="fas fa-eye"></i> <?= e(t('Preview', 'Aperçu')) ?></button>
    <button class="btn is-small is-gold" type="button" data-import-apply><i class="fas fa-bolt"></i> <?= e(array_filter(array_keys($counts), fn($k) => str_contains((string)$k, '.')) ? t('Apply what is ticked', 'Appliquer ce qui est coché') : t('Apply what is missing', 'Appliquer ce qui manque')) ?></button>
  </div>
</article>
<?php endforeach; ?>
<?php if ($folded): ?></details><?php endif; ?>

<section class="block">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('How it merges', 'Comment la fusion se fait')) ?></span><h2><?= e(t('Safe by design', 'Sûr par conception')) ?></h2></div></header>
  <ul class="confirm-points">
    <li><i class="fas fa-shield-halved"></i><?= e(t('Only INSERT rows are read; DELETE and UPDATE statements of the file are never run.', 'Seules les lignes INSERT sont lues ; les DELETE et UPDATE du fichier ne sont jamais exécutés.')) ?></li>
    <li><i class="fas fa-rotate"></i><?= e(t('A drop chance a source measured again is proposed as a line of its card, only for rows an import brought and only by a source at least as trusted; each change names the value it replaces and can be rolled back.', 'Une chance de butin mesurée à nouveau par une source est proposée sur une ligne de sa carte, seulement pour les lignes apportées par un import et par une source au moins aussi fiable ; chaque changement nomme la valeur qu’il remplace et peut être annulé.')) ?></li>
    <li><i class="fas fa-scroll"></i><?= e(t('The EG Link card also reads the quests your server has again from the live game: where a reward, an amount or a text changed in a later client build than your row, it proposes the new value. Flags and the other fields that decide how a quest works are counted, never changed.', 'La carte EG Link relit aussi les quêtes de votre serveur depuis le jeu : là où une récompense, une quantité ou un texte a changé dans un build client plus récent que votre ligne, elle propose la nouvelle valeur. Les drapeaux et les autres champs qui décident du fonctionnement d’une quête sont comptés, jamais modifiés.')) ?></li>
    <li><i class="fas fa-code-merge"></i><?= e(t('Rows your server already has are left out; spawns get new guids, and a spawn that already stands within 3 yards is left out with its addon.', 'Les lignes déjà présentes sont écartées ; les placements reçoivent de nouveaux guid, et un placement qui existe déjà à moins de 3 mètres est écarté avec son addon.')) ?></li>
    <li><i class="fas fa-sack-dollar"></i><?= e(t('Loot works at once: a creature whose LootID is 0 gets its own loot table.', 'Le butin fonctionne aussitôt : un PNJ dont le LootID vaut 0 reçoit sa propre table de butin.')) ?></li>
    <li><i class="fas fa-rotate-left"></i><?= e(t('Columns your core does not have are dropped. The history keeps the exact SQL and a rollback.', 'Les colonnes que votre core n’a pas sont ignorées. L’historique garde le SQL exact et l’annulation.')) ?></li>
  </ul>
</section>
<?php require FT_APP . '/pages/admin/_modals.php'; ?>
<?php page_end();
