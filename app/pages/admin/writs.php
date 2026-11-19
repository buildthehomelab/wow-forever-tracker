<?php
// Writs (administrators): what Wowhead says of each Craftsman's Writ (app/wowheadpages.php wowhead_pages_writs). Wowhead's
// guide calls them world drops and gives their tier; no item page names a creature or a chest yet. The crawl reads the
// writs' pages again every [wowhead] writ_days, so a source Wowhead learns shows here, and ?format=json hands it to a
// world-data file (creature_loot_template rows from the dropped-by counts).
require_once FT_APP . '/wowheadpages.php';
$writItems = wowhead_writ_items();
$guides = wowhead_pages('forever-guide');
$guide = $guides[WOWHEAD_WRIT_GUIDE] ?? null;
// before an analysis that records the writs (ft_meta writ_items), the guide's own list stands in, without quests
if (!$writItems && $guide) foreach ((array)($guide['rows'] ?? []) as $row) if (is_int($row['id'] ?? null)) $writItems[$row['id']] = 0;
$writs = wowhead_pages_writs($writItems, wowhead_pages('item'), $guides, wowhead_writ_tiers());
$branch = (string)config('wowhead', 'branch', 'forever');

if (($_GET['format'] ?? '') === 'json') {
    json_out(['guide' => ['query' => WOWHEAD_WRIT_GUIDE, 'fetched' => (int)($guide['fetched'] ?? 0)], 'tiers' => WOWHEAD_WRIT_TIERS,
        'note' => 'tier: the client\'s (ItemNameDescription under the name), else the guide\'s; guideTier: the guide\'s. sources: the rows the item page names, with Wowhead\'s counts (count of outof looted).',
        'writs' => array_map(fn($item, $w) => ['item' => $item] + $w, array_keys($writs), array_values($writs))]);
}

$names = [];
if ($writs && table_exists('ft_entities')) {
    $ids = array_merge(array_keys($writs), array_filter(array_column($writs, 'quest')));
    foreach (array_chunk($ids, 500) as $chunk) {
        foreach (rows('SELECT type, id, name, name_en, quality, status, score, phase FROM ft_entities WHERE type IN (\'item\', \'quest\') AND id IN (' . implode(',', array_map('intval', $chunk)) . ')') as $x) $names[$x['type'] . ':' . $x['id']] = $x;
    }
}
$filter = in_array($_GET['show'] ?? '', ['sourced', 'unread'], true) ? $_GET['show'] : '';
$sourced = array_filter($writs, fn($w) => $w['sources']);
$unread = array_filter($writs, fn($w) => !$w['fetched']);
$list = ['sourced' => $sourced, 'unread' => $unread, '' => $writs][$filter];
$tabLabels = ['dropped-by' => t('Dropped by', 'Butin de'), 'contained-in-object' => t('In a chest', 'Dans un coffre'), 'contained-in-item' => t('In a container', 'Dans un contenant'),
    'mined-from-object' => t('Mined from', 'Miné sur'), 'gathered-from-object' => t('Gathered from', 'Cueilli sur'), 'skinned-from' => t('Skinned from', 'Dépecé sur'),
    'pick-pocketed-from' => t('Pick pocketed from', 'Volé sur'), 'sold-by' => t('Sold by', 'Vendu par'), 'reward-from-q' => t('Quest reward', 'Récompense de quête'), 'fished-in' => t('Fished in', 'Pêché à')];
$read = count($writs) - count($unread);
$days = wowhead_writ_seconds() / 86400;
page_start(t('Craftsman’s Writs', 'Ordres d’artisan'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-scroll"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a> · <a href="<?= e(url('admin/crawl')) ?>"><?= e(t('Crawl', 'Parcours')) ?></a></span><h1><?= e(t('Craftsman’s Writs on Wowhead', 'Les ordres d’artisan sur Wowhead')) ?></h1>
    <p><?= e(t('Each writ is an item that starts a crafting quest. Wowhead’s Forever guide calls them world drops that suit the zone and level, and gives each its tier; no public source says which creatures drop them yet. The crawl reads every writ’s page and the guide again every few days: a creature, chest or vendor Wowhead names shows here the next time, with its counts. Nothing is guessed: a writ whose page names nothing has nothing here.', 'Chaque ordre est un objet qui lance une quête d’artisanat. Le guide Forever de Wowhead dit qu’ils tombent partout dans le monde selon la zone et le niveau, et donne le rang de chacun ; aucune source publique ne dit encore quelles créatures les donnent. Le parcours relit la page de chaque ordre et le guide tous les quelques jours : une créature, un coffre ou un marchand que Wowhead nomme apparaît ici la fois suivante, avec ses comptes. Rien n’est deviné : un ordre dont la page ne nomme rien n’a rien ici.')) ?></p>
    <p class="muted small"><?= e(sprintf(t('Read again every %s days ([wowhead] writ_days). Guide read: %s. JSON for a world-data file: ', 'Relu tous les %s jours ([wowhead] writ_days). Guide lu : %s. JSON pour un fichier de données : '), number($days, $days == (int)$days ? 0 : 1),
        $guide ? date('M j, Y H:i', (int)$guide['fetched']) : t('not yet', 'pas encore'))) ?><a class="link" href="<?= e(url('admin/writs', ['format' => 'json'])) ?>">?format=json</a></p></div></div>
  <div class="stat-tiles is-compact">
    <span class="stat-tile"><strong><?= number(count($writs)) ?></strong><span><?= e(t('writs', 'ordres')) ?></span></span>
    <span class="stat-tile"><strong><?= number($read) ?></strong><span><?= e(t('pages read', 'pages lues')) ?></span></span>
    <span class="stat-tile <?= $sourced ? 'is-ok' : 'is-missing' ?>"><strong><?= number(count($sourced)) ?></strong><span><?= e(t('with a source', 'avec une source')) ?></span></span>
  </div>
</section>
<nav class="tabs">
  <a class="<?= $filter === '' ? 'is-active' : '' ?>" href="<?= e(url('admin/writs')) ?>"><?= e(t('All', 'Tout')) ?><em><?= number(count($writs)) ?></em></a>
  <a class="<?= $filter === 'sourced' ? 'is-active' : '' ?>" href="<?= e(url('admin/writs', ['show' => 'sourced'])) ?>"><?= e(t('With a source', 'Avec une source')) ?><em><?= number(count($sourced)) ?></em></a>
  <a class="<?= $filter === 'unread' ? 'is-active' : '' ?>" href="<?= e(url('admin/writs', ['show' => 'unread'])) ?>"><?= e(t('Page not read yet', 'Page pas encore lue')) ?><em><?= number(count($unread)) ?></em></a>
</nav>
<?php if (!$writs): ?>
<div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No writ known yet: the analysis records them (run it again after an update), or the crawl reads Wowhead’s writ guide first.', 'Aucun ordre connu pour l’instant : l’analyse les enregistre (relancez-la après une mise à jour), ou le parcours lit d’abord le guide des ordres de Wowhead.')) ?></p></div>
<?php elseif (!$list): ?>
<div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-magnifying-glass"></i></div><p><?= e($filter === 'sourced' ? t('Wowhead names no source for any writ yet.', 'Wowhead ne nomme encore aucune source pour aucun ordre.') : t('Nothing here.', 'Rien ici.')) ?></p></div>
<?php else: ?>
<div class="table-card">
<table class="table is-forge">
  <thead><tr><th><?= e(t('Writ', 'Ordre')) ?></th><th><?= e(t('Tier', 'Rang')) ?></th><th><?= e(t('Quest', 'Quête')) ?></th><th><?= e(t('Wowhead page', 'Page Wowhead')) ?></th><th><?= e(t('Where it comes from', 'D’où il vient')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $item => $w): $it = $names["item:$item"] ?? ['id' => $item, 'name' => '', 'name_en' => '', 'quality' => 1]; $q = $w['quest'] ? ($names['quest:' . $w['quest']] ?? null) : null; ?>
    <tr>
      <td class="res"><div><strong><?= name_link($it, 'item') ?></strong><small>item <?= (int)$item ?> · <a href="https://www.wowhead.com/<?= e($branch) ?>/item=<?= (int)$item ?>" target="_blank" rel="noopener">Wowhead <i class="fas fa-arrow-up-right-from-square"></i></a></small></div></td>
      <td><?= $w['tier'] ? e(WOWHEAD_WRIT_TIERS[$w['tier']] ?? (string)$w['tier']) : '<span class="muted">—</span>' ?><?php if ($w['guideTier'] && $w['guideTier'] !== $w['tier']): ?>
        <small class="muted" title="<?= e(t('The client names one tier under the item’s name, Wowhead’s guide another: the client is the game’s own word.', 'Le client indique un rang sous le nom de l’objet, le guide de Wowhead un autre : le client fait foi.')) ?>"><?= e(t('guide:', 'guide :') . ' ' . (WOWHEAD_WRIT_TIERS[$w['guideTier']] ?? '')) ?></small><?php endif; ?></td>
      <td><?php if ($q): ?><?= name_link($q, 'quest') ?> <?= row_badge($q) ?><?php elseif ($w['quest']): ?><a href="<?= e(entry_url('quest', $w['quest'])) ?>">quest <?= (int)$w['quest'] ?></a><?php else: ?><span class="muted">—</span><?php endif; ?></td>
      <td><?php if (!$w['fetched']): ?><span class="muted"><?= e(t('not read yet', 'pas encore lue')) ?></span><?php else: ?><?= e(date('M j, Y', $w['fetched'])) ?><?= $w['status'] === 'missing' ? ' <span class="tag is-plain">' . e(t('no such page', 'page inexistante')) . '</span>' : '' ?><?php endif; ?></td>
      <td class="fix-cell"><?php if (!$w['sources'] && !$w['zones']): ?><span class="muted"><?= e($w['fetched'] ? t('none named', 'aucune nommée') : '—') ?></span><?php endif; ?>
        <?php foreach ($w['sources'] as $tab => $rows): $kind = WOWHEAD_WRIT_SOURCE_TABS[$tab]; ?>
        <span class="reason"><em class="tag is-plain"><?= e($tabLabels[$tab] ?? $tab) ?> · <?= number(count($rows)) ?></em>
          <?php foreach (array_slice($rows, 0, 8) as $r): ?><a href="https://www.wowhead.com/<?= e($branch) ?>/<?= e($kind) ?>=<?= (int)$r['id'] ?>" target="_blank" rel="noopener"><?= e($kind) ?> <?= (int)$r['id'] ?></a><?= isset($r['count'], $r['outof']) && $r['outof'] > 0 ? ' <small class="muted">' . (int)$r['count'] . '/' . (int)$r['outof'] . '</small>' : '' ?> <?php endforeach; ?>
          <?= count($rows) > 8 ? '<small class="muted">+' . (count($rows) - 8) . '</small>' : '' ?></span>
        <?php endforeach; ?>
        <?php if ($w['zones']): ?><span class="reason"><em class="tag is-plain"><?= e(t('Map pins in zones', 'Repères dans les zones')) ?></em> <?= e(implode(', ', $w['zones'])) ?></span><?php endif; ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
</div>
<?php endif; ?>
<?php page_end();
