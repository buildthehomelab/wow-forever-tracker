<?php
// Auction prices (administrators): every item the server's auction house bot has a market price for
// (world.auctionhousebot_market_price, app/auctionprices.php), with names from the analysis. Administrators only: the
// TradeSkillMaster data must not be republished in bulk.
require_once FT_APP . '/auctionprices.php';
$ready = auction_prices_ready();
$prices = $ready ? rows('SELECT ItemID, UnitPrice, Quantity, Samples FROM auctionhousebot_market_price WHERE UnitPrice > 0', [], 'world') : [];
$names = [];
if ($prices && table_exists('ft_entities')) {
    foreach (array_chunk(array_column($prices, 'ItemID'), 1000) as $chunk) {
        foreach (rows("SELECT id, name, name_en, quality, icon, status, score, phase FROM ft_entities WHERE type = 'item' AND id IN (" . implode(',', array_map('intval', $chunk)) . ')') as $x) $names[(int)$x['id']] = $x;
    }
}
$list = [];
foreach ($prices as $p) {
    $id = (int)$p['ItemID'];
    $it = $names[$id] ?? ['id' => $id, 'name' => '', 'name_en' => '', 'quality' => 1, 'icon' => ''];
    $list[] = ['item' => $it, 'id' => $id, 'name' => display_name($it) ?: "item $id", 'price' => (int)$p['UnitPrice'], 'sold' => (int)$p['Quantity'], 'tsm' => (int)$p['Samples'] === 0];
}
$tsmCount = count(array_filter($list, fn($x) => $x['tsm']));
$show = in_array($_GET['show'] ?? '', ['tsm', 'scan'], true) ? $_GET['show'] : '';
$q = trim((string)($_GET['q'] ?? ''));
$sort = in_array($_GET['sort'] ?? '', ['price', 'cheap', 'sold', 'name'], true) ? $_GET['sort'] : 'sold';
if ($show) $list = array_values(array_filter($list, fn($x) => $x['tsm'] === ($show === 'tsm')));
if ($q !== '') $list = array_values(array_filter($list, fn($x) => ctype_digit($q) ? $x['id'] === (int)$q : mb_stripos($x['name'], $q) !== false));
usort($list, ['price' => fn($a, $b) => $b['price'] <=> $a['price'], 'cheap' => fn($a, $b) => $a['price'] <=> $b['price'],
    'sold' => fn($a, $b) => [$b['sold'], $a['name']] <=> [$a['sold'], $b['name']], 'name' => fn($a, $b) => strcasecmp($a['name'], $b['name'])][$sort]);
$perPage = 100;
$total = count($list);
$page = max(1, min((int)($_GET['p'] ?? 1), max(1, (int)ceil($total / $perPage))));
$shown = array_slice($list, ($page - 1) * $perPage, $perPage);
$query = fn(array $change) => url('admin/prices', array_filter(array_merge(['show' => $show, 'q' => $q, 'sort' => $sort === 'sold' ? '' : $sort, 'p' => ''], $change), fn($v) => $v !== '' && $v !== 1));
page_start(t('Auction prices', 'Prix des enchères'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-coins"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Auction house prices', 'Prix de l’hôtel des ventes')) ?></h1>
    <p><?= e(t('What the server’s auction house bot lists each item at, per item, never below what a vendor pays for it. TSM rows are TradeSkillMaster’s market value for WoW: Forever, loaded from its public data each time the worldserver starts; scan rows are the lowest buyouts of the November auction house scans. Items not listed here are priced by the bot’s value curve.', 'Le prix auquel le bot de l’hôtel des ventes du serveur met chaque objet en vente, à l’unité, jamais sous ce qu’un marchand en donne. Les lignes TSM sont la valeur de marché TradeSkillMaster pour WoW: Forever, chargée depuis ses données publiques à chaque démarrage du worldserver ; les lignes relevé sont les plus bas prix d’achat des relevés de novembre. Les objets absents ici sont estimés par la courbe de valeur du bot.')) ?></p>
    <p class="muted small"><?= e(t('Pricing data from TradeSkillMaster (tradeskillmaster.com). Read from the realm’s world database; shown to administrators only.', 'Données de prix de TradeSkillMaster (tradeskillmaster.com). Lues dans la base world du royaume ; réservées aux administrateurs.')) ?></p></div></div>
  <div class="stat-tiles is-compact">
    <span class="stat-tile"><strong><?= number(count($prices)) ?></strong><span><?= e(t('priced items', 'objets avec un prix')) ?></span></span>
    <span class="stat-tile"><strong><?= number($tsmCount) ?></strong><span>TSM</span></span>
    <span class="stat-tile"><strong><?= number(count($prices) - $tsmCount) ?></strong><span><?= e(t('from scans', 'des relevés')) ?></span></span>
  </div>
</section>
<?php if (!$ready): ?>
<div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-database"></i></div><p><?= e(t('The world database has no auctionhousebot_market_price table: the realm’s core is older than the auction house bot’s market prices.', 'La base world n’a pas de table auctionhousebot_market_price : le cœur du royaume est antérieur aux prix de marché du bot.')) ?></p></div>
<?php else: ?>
<nav class="tabs">
  <a class="<?= $show === '' ? 'is-active' : '' ?>" href="<?= e($query(['show' => ''])) ?>"><?= e(t('All', 'Tout')) ?><em><?= number(count($prices)) ?></em></a>
  <a class="<?= $show === 'tsm' ? 'is-active' : '' ?>" href="<?= e($query(['show' => 'tsm'])) ?>">TSM<em><?= number($tsmCount) ?></em></a>
  <a class="<?= $show === 'scan' ? 'is-active' : '' ?>" href="<?= e($query(['show' => 'scan'])) ?>"><?= e(t('Scans', 'Relevés')) ?><em><?= number(count($prices) - $tsmCount) ?></em></a>
</nav>
<form class="toolbar" method="get" data-autosubmit-form>
  <?php if ($show): ?><input type="hidden" name="show" value="<?= e($show) ?>"><?php endif; ?>
  <label class="field is-search"><i class="fas fa-magnifying-glass"></i><input name="q" value="<?= e($q) ?>" placeholder="<?= e(t('Filter by name or ID…', 'Filtrer par nom ou ID…')) ?>"></label>
  <label class="field is-select"><span><?= e(t('Sort', 'Tri')) ?></span><select name="sort" data-autosubmit>
    <?php foreach (['sold' => t('Most sold', 'Plus vendus'), 'price' => t('Dearest', 'Plus chers'), 'cheap' => t('Cheapest', 'Moins chers'), 'name' => t('Name', 'Nom')] as $key => $label): ?><option value="<?= e($key) ?>" <?= $sort === $key ? 'selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?></select></label>
</form>
<?php if (!$shown): ?>
<div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-magnifying-glass"></i></div><p><?= e(count($prices) ? t('No item matches.', 'Aucun objet ne correspond.') : t('No prices yet: the worldserver loads TSM’s data the next time it starts.', 'Pas encore de prix : le worldserver charge les données TSM à son prochain démarrage.')) ?></p></div>
<?php else: ?>
<div class="table-card">
<table class="table">
  <thead><tr><th><?= e(t('Item', 'Objet')) ?></th><th class="num"><?= e(t('Price each', 'Prix à l’unité')) ?></th><th class="num"><?= e(t('Sold a day', 'Vendus par jour')) ?></th><th><?= e(t('Source', 'Source')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($shown as $x): ?>
    <tr>
      <td class="res"><div><strong><?= name_link($x['item'], 'item') ?></strong><small>item <?= $x['id'] ?></small></div></td>
      <td class="num"><?= money_html($x['price']) ?></td>
      <td class="num"><?= $x['tsm'] ? number($x['sold']) : '<span class="muted">—</span>' ?></td>
      <td><span class="tag is-plain"><?= e($x['tsm'] ? 'TSM' : t('scan', 'relevé')) ?></span></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
</div>
<?php $pages = (int)ceil($total / $perPage); if ($pages > 1): ?>
<nav class="pager">
  <?php if ($page > 1): ?><a class="btn is-small" href="<?= e($query(['p' => $page - 1])) ?>"><i class="fas fa-arrow-left"></i> <?= e(t('Previous', 'Précédent')) ?></a><?php else: ?><span></span><?php endif; ?>
  <span class="pager-info"><?= e(sprintf(t('Page %d of %s', 'Page %d sur %s'), $page, number($pages))) ?></span>
  <?php if ($page < $pages): ?><a class="btn is-small" href="<?= e($query(['p' => $page + 1])) ?>"><?= e(t('Next', 'Suivant')) ?> <i class="fas fa-arrow-right"></i></a><?php else: ?><span></span><?php endif; ?>
</nav>
<?php endif; endif; endif; ?>
<?php page_end();
