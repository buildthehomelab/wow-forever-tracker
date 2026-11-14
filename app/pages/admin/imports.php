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
    'creature_questender' => t('Quest enders', 'Valideurs de quête'), 'trainer_spell' => t('Trainers', 'Entraîneurs'), 'gossip_menu_option' => t('Gossip options', 'Options de dialogue'),
    'gameobject_queststarter' => t('Quest givers (objects)', 'Donneurs de quête (objets)'), 'gameobject_questender' => t('Quest enders (objects)', 'Valideurs de quête (objets)'),
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
    'loot_chance_unknown' => t('drops without a known chance', 'butins sans chance connue'), 'loot_unknown_creature' => t('drops of creatures or chests unknown to this server', 'butins de PNJ ou coffres inconnus de ce serveur'),
    'trainer_known' => t('spells the trainer already teaches', 'sorts que l’entraîneur enseigne déjà'), 'trainer_not_on_server' => t('trainers unknown to this server', 'entraîneurs inconnus de ce serveur'),
    'trainer_level_unknown' => t('class spells without a known level', 'sorts de classe sans niveau connu'), 'trainer_previous_rank_unknown' => t('higher ranks whose previous rank is unknown', 'rangs supérieurs dont le rang précédent est inconnu'),
    'trainer_skill_unknown' => t('profession entries with an unknown skill', 'entrées de métier à la compétence inconnue'), 'trainer_profession_skill_unknown' => t('profession entries without a skill rank', 'entrées de métier sans rang de compétence'),
    'phase_not_open' => t('gap items and quests of a release phase that is not open yet (not looked at)', 'objets et quêtes manquants d’une phase de sortie pas encore ouverte (non consultés)'),
    'trainer_phase_not_open' => t('trainer spells of a release phase that is not open yet', 'sorts d’entraîneur d’une phase de sortie pas encore ouverte'),
    // Wowhead quest enders (app/wowhead.php)
    'not_looked_up_yet' => t('quests not looked up on Wowhead yet (run it again)', 'quêtes pas encore consultées sur Wowhead (relancez)'),
    'not_on_wowhead' => t('quests Wowhead does not know', 'quêtes inconnues de Wowhead'),
    'no_ender_named' => t('quests whose Wowhead summary names nobody to return to', 'quêtes dont le résumé Wowhead ne nomme personne chez qui revenir'),
    'name_not_on_server' => t('enders Wowhead names that no spawned creature of this server is called', 'valideurs nommés par Wowhead dont aucun PNJ placé de ce serveur ne porte le nom'),
    'name_not_unique' => t('enders Wowhead names that several spawned creatures are called', 'valideurs nommés par Wowhead dont plusieurs PNJ placés portent le nom'),
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
<section class="block import-add">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Live Forever recordings', 'Enregistrements de Forever')) ?></span><h2><?= e(t('EG Link, ForeverDB.net, Icy Veins', 'EG Link, ForeverDB.net, Icy Veins')) ?></h2></div></header>
  <ol class="steps-list">
    <li><?= e(t('Three projects whose players\' addons record what live WoW Forever shows: vendor windows, loot, trainers, who gives and takes quests. Each import aims at the last analysis\' gaps, with the same rules as NorgannonDB (docs/SOURCES.md).', 'Trois projets dont les addons des joueurs enregistrent ce que montre WoW Forever : marchands, butin, entraîneurs, donneurs et valideurs de quêtes. Chaque import vise les manques de la dernière analyse, avec les mêmes règles que NorgannonDB (docs/SOURCES.md).')) ?></li>
    <li><?= e(t('EG Link (CC BY 4.0) and ForeverDB.net (GPL-3.0, credit "Data from ForeverDB.net") are downloaded whole. Icy Veins (no licence stated: for your own server) is asked about each gap, two lookups a second, in the background: several hours the first time (one lookup per gap item, quest and trainer). A restart stops it: the container goes on with it by itself at its next start (anywhere else, press the button again), from what it already asked. When Icy Veins stops answering, the run slows down, then stops after 20 lookups without an answer and says so below. Its answers are asked again after two weeks as it grows.', 'EG Link (CC BY 4.0) et ForeverDB.net (GPL-3.0, crédit « Data from ForeverDB.net ») sont téléchargés en entier. Icy Veins (sans licence : pour votre serveur) est consulté pour chaque manque, deux fois par seconde, en arrière-plan : plusieurs heures la première fois (une requête par objet, quête et entraîneur manquant). Un redémarrage l’arrête : le conteneur le reprend tout seul à son prochain démarrage (ailleurs, relancez-le), là où il en était. Quand Icy Veins ne répond plus, l’import ralentit, puis s’arrête après 20 requêtes sans réponse et le dit ci-dessous. Ses réponses sont redemandées après deux semaines.')) ?></li>
  </ol>
  <div class="btn-row">
    <button class="btn is-small is-gold" type="button" data-scribe="source_eglink"><i class="fas fa-link"></i> <?= e(t('Import EG Link', 'Importer EG Link')) ?></button>
    <button class="btn is-small is-gold" type="button" data-scribe="source_foreverdb"><i class="fas fa-book-atlas"></i> <?= e(t('Import ForeverDB.net', 'Importer ForeverDB.net')) ?></button>
    <button class="btn is-small is-gold" type="button" data-scribe="source_icyveins" <?= $icyRunning ? 'disabled' : '' ?>><i class="fas fa-snowflake"></i> <?= e($icyRunning ? t('Icy Veins: running…', 'Icy Veins : en cours…') : t('Import Icy Veins', 'Importer Icy Veins')) ?></button>
  </div>
  <?php if ($icyLog !== ''): ?><p class="muted small">Icy Veins: <?= e($icyLog) ?></p><?php endif; ?>
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
<?php foreach ($imports as $s): $counts = json_decode((string)$s['counts'], true) ?: []; $ignored = json_decode((string)$s['ignored'], true) ?: []; ?>
<article class="block import-card" data-import="<?= (int)$s['id'] ?>">
  <header class="op-head">
    <span class="fix-kind is-import"><i class="fas fa-file-import"></i></span>
    <div><strong>#<?= (int)$s['id'] ?> · <?= e($s['name']) ?></strong>
      <small><?= e($s['file']) ?> · <?= e(date(t('M j, Y H:i', 'd/m/Y H:i'), strtotime($s['imported_at']))) ?> · <?= number(array_sum($counts)) ?> <?= e(t('rows', 'lignes')) ?> · <?= number((int)$s['items']) ?> <?= e(t('item(s) made obtainable', 'objet(s) rendus obtenables')) ?></small></div>
    <button class="icon-btn is-small" type="button" data-import-delete title="<?= e(t('Forget this import (the server is not changed)', 'Oublier cet import (le serveur n’est pas modifié)')) ?>"><i class="fas fa-trash"></i></button>
  </header>
  <div class="import-tables">
    <?php foreach ($counts as $table => $n): ?>
      <label class="checkbox-line"><input type="checkbox" value="<?= e($table) ?>" checked> <span><?= e($tableLabels[$table] ?? $table) ?></span> <small class="muted"><?= e($table) ?> · <?= number($n) ?></small></label>
    <?php endforeach; ?>
  </div>
  <?php if ($ignored): ?><p class="muted small"><?= e(t('Left out:', 'Écarté :')) ?> <?= e(implode(', ', array_map(fn($t, $n) => ($leftLabels[$t] ?? $t) . " ($n)", array_keys($ignored), $ignored))) ?></p><?php endif; ?>
  <div class="btn-row">
    <button class="btn is-small" type="button" data-import-preview><i class="fas fa-eye"></i> <?= e(t('Preview', 'Aperçu')) ?></button>
    <button class="btn is-small is-gold" type="button" data-import-apply><i class="fas fa-bolt"></i> <?= e(t('Apply what is missing', 'Appliquer ce qui manque')) ?></button>
  </div>
</article>
<?php endforeach; ?>

<section class="block">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('How it merges', 'Comment la fusion se fait')) ?></span><h2><?= e(t('Safe by design', 'Sûr par conception')) ?></h2></div></header>
  <ul class="confirm-points">
    <li><i class="fas fa-shield-halved"></i><?= e(t('Only INSERT rows are read; DELETE and UPDATE statements of the file are never run.', 'Seules les lignes INSERT sont lues ; les DELETE et UPDATE du fichier ne sont jamais exécutés.')) ?></li>
    <li><i class="fas fa-code-merge"></i><?= e(t('Rows your server already has are left out; spawns get new guids, and a spawn that already stands within 3 yards is left out with its addon.', 'Les lignes déjà présentes sont écartées ; les placements reçoivent de nouveaux guid, et un placement qui existe déjà à moins de 3 mètres est écarté avec son addon.')) ?></li>
    <li><i class="fas fa-sack-dollar"></i><?= e(t('Loot works at once: a creature whose LootID is 0 gets its own loot table.', 'Le butin fonctionne aussitôt : un PNJ dont le LootID vaut 0 reçoit sa propre table de butin.')) ?></li>
    <li><i class="fas fa-rotate-left"></i><?= e(t('Columns your core does not have are dropped. The history keeps the exact SQL and a rollback.', 'Les colonnes que votre core n’a pas sont ignorées. L’historique garde le SQL exact et l’annulation.')) ?></li>
  </ul>
</section>
<?php require FT_APP . '/pages/admin/_modals.php'; ?>
<?php page_end();
