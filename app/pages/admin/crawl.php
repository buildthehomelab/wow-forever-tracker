<?php
// Crawl (administrators): reads Wowhead's pages in a tab this page opens, and keeps each page in the tracker as it comes
// (docs/WOWHEAD-PAGES.md, "A linked crawl"). The crawler runs in the Wowhead tab; this page receives what it reads,
// sends it to api/imports (wowhead_push) and makes the import cards again every [wowhead] card_minutes.
require_once FT_APP . '/wowheadpages.php';
$shelves = ['item', 'quest', 'npc', 'object', 'classic-item', 'classic-npc', 'classic-object', 'forever-list', 'classic-list'];
$kept = array_combine($shelves, array_map('wowhead_pages_count', $shelves));
// when a crawl last sent something: the newest of the files a push adds to (a crawl that stopped shows here)
$lastIn = 0;
foreach (glob(wowhead_pages_dir() . '/*.jsonl') ?: [] as $file) $lastIn = max($lastIn, (int)@filemtime($file));
page_start(t('Crawl Wowhead', 'Parcourir Wowhead'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-spider"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Crawl Wowhead', 'Parcourir Wowhead')) ?></h1>
    <p><?= e(t('Reads Wowhead’s pages in a tab this page opens, the most valuable first, and keeps each page here as it comes: nothing to save or send by hand. The import cards are made again every half hour; applying one stays your click.', 'Lit les pages de Wowhead dans un onglet que cette page ouvre, les plus utiles d’abord, et garde chaque page ici dès qu’elle arrive : rien à enregistrer ni envoyer à la main. Les cartes d’import sont refaites toutes les demi-heures ; en appliquer une reste votre clic.')) ?></p>
    <p class="muted small"><?= e(t('Wowhead’s page may not call this tracker (it turns every http:// request into https://), but two tabs may pass messages: keep both tabs open. What the crawl reads while this tab is closed waits in the Wowhead tab and comes the next time it is linked.', 'La page de Wowhead ne peut pas appeler ce tracker (elle change toute requête http:// en https://), mais deux onglets peuvent échanger des messages : gardez les deux ouverts. Ce que le parcours lit pendant que cet onglet est fermé attend dans l’onglet Wowhead et arrive au prochain lien.')) ?></p></div></div>
</section>

<section class="block">
  <h2><?= e(t('By itself: the Chrome extension', 'Tout seul : l’extension Chrome')) ?></h2>
  <p><?= e(t('On a computer that stays on, the extension keeps a pinned Wowhead tab crawling with no console and no tab of this site open: it loads the crawler with this tracker’s queue after every load, opens the tab again when it is closed or Chrome restarts, and sends each page here. Its icon shows what it is doing and can pause it.', 'Sur un ordinateur qui reste allumé, l’extension garde un onglet Wowhead épinglé qui parcourt le site sans console ni onglet de ce site ouvert : elle charge le crawler avec la file de ce tracker après chaque chargement, rouvre l’onglet quand il est fermé ou que Chrome redémarre, et envoie chaque page ici. Son icône montre ce qu’elle fait et peut la mettre en pause.')) ?></p>
  <ol class="steps-list">
    <li><?= e(t('Download it (it carries this tracker’s address and a key of its own) and unzip it somewhere it can stay.', 'Téléchargez-la (elle porte l’adresse de ce tracker et une clé à elle) et décompressez-la là où elle peut rester.')) ?></li>
    <li><?= e(t('In Chrome: chrome://extensions › Developer mode › Load unpacked › the wowhead-crawl folder.', 'Dans Chrome : chrome://extensions › Mode développeur › Charger l’extension non empaquetée › le dossier wowhead-crawl.')) ?></li>
    <li><?= e(t('Close any other Wowhead crawl first (WHC.stop() in its tab): only one may run per address.', 'Fermez d’abord tout autre parcours Wowhead (WHC.stop() dans son onglet) : un seul par adresse.')) ?></li>
  </ol>
  <div class="btn-row"><button class="btn is-gold" type="button" data-scribe="wowhead_extension"><i class="fas fa-puzzle-piece"></i> <?= e(t('Download the Chrome extension', 'Télécharger l’extension Chrome')) ?></button></div>
</section>

<section class="block" data-crawl-link data-wowhead="https://www.wowhead.com/forever">
  <ol class="steps-list">
    <li><?= e(t('Open Wowhead from here: a tab opens on wowhead.com/forever with the crawler and its queue (the full crawl: your gaps first, then the whole database).', 'Ouvrez Wowhead d’ici : un onglet s’ouvre sur wowhead.com/forever avec le crawler et sa file (le parcours complet : vos manques d’abord, puis toute la base).')) ?></li>
    <li><?= e(t('In that tab, open the developer console (F12) and run the line below once. A crawl already running in another tab: stop it there first (WHC.stop()), only one may run.', 'Dans cet onglet, ouvrez la console (F12) et lancez une fois la ligne ci-dessous. Un parcours déjà lancé dans un autre onglet : arrêtez-le d’abord (WHC.stop()), un seul peut tourner.')) ?></li>
  </ol>
  <pre class="analysis-log">(0, eval)(JSON.parse(window.name).src)</pre>
  <div class="btn-row"><button class="btn is-gold" type="button" data-crawl-open><i class="fas fa-up-right-from-square"></i> <?= e(t('Open Wowhead', 'Ouvrir Wowhead')) ?></button>
    <button class="btn is-small" type="button" data-crawl-cards><i class="fas fa-book-open"></i> <?= e(t('Make the cards now', 'Faire les cartes maintenant')) ?></button></div>
  <p class="small"><strong data-crawl-state><?= e(t('Not linked: no page received since this tab opened.', 'Pas de lien : aucune page reçue depuis l’ouverture de cet onglet.')) ?></strong></p>
  <p class="muted small" data-crawl-last></p>
  <p class="muted small"><?= e(sprintf(t('Kept so far: %s item, %s quest, %s npc and %s object pages of Forever; %s item, %s npc and %s object pages of Classic.', 'Conservées : %s pages d’objets, %s de quêtes, %s de PNJ et %s d’objets du monde de Forever ; %s d’objets, %s de PNJ et %s d’objets du monde de Classic.'),
      number($kept['item']), number($kept['quest']), number($kept['npc']), number($kept['object']), number($kept['classic-item']), number($kept['classic-npc']), number($kept['classic-object']))) ?></p>
  <p class="muted small"><?= e(sprintf(t('List pages: %s of Forever, %s of Classic (a whole crawl reads these first). Last page received: %s.', 'Pages de listes : %s de Forever, %s de Classic (un parcours complet les lit d’abord). Dernière page reçue : %s.'),
      number($kept['forever-list']), number($kept['classic-list']), $lastIn ? date('M j, Y H:i', $lastIn) : t('never', 'jamais'))) ?></p>
</section>
<?php page_end();
