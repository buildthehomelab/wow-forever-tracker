<?php
// Extras: what the server's world holds that the live game does not (tools/ft/extras.py fills ft_world_extras at each
// analysis). A list to look at: nothing is changed from here. ?sql=1 gives the removals it is sure enough to write
// (stacked copies, and the twins whose live entry the server spawns as well) as an update file to review.
$have = table_exists('ft_world_extras');
$issues = [
    'twin' => [t('Old twin', 'Ancien jumeau'), t('The server spawns a creature the live server never sent to a client; live uses another entry of the same name (often Forever\'s copy of a Classic creature).', 'Le serveur place une créature que le serveur officiel n’a jamais envoyée ; le jeu utilise une autre entrée du même nom.')],
    'stacked' => [t('Stacked', 'Empilés'), t('Two spawns of the same name on one spot, in the same phase and the same world events, neither in a pool: one model inside another. The one to keep is named.', 'Deux placements du même nom au même endroit, même phase et mêmes événements, hors pool. Celui à garder est indiqué.')],
    'crowded' => [t('Crowded', 'Surpeuplé'), t('Far more spawns of a creature than Wowhead\'s Forever map marks in that place.', 'Bien plus de placements que la carte Forever de Wowhead n’en montre.')],
    'invented' => [t('Invented', 'Inventé'), t('An entry nothing outside the server knows: not in the client, never recorded on the game, not on Wowhead (Forever).', 'Une entrée que rien hors du serveur ne connaît.')],
    'giver' => [t('Quest giver', 'Donneur de quête'), t('The server has it give or take a quest that live players only saw others give or take. Weaker: a second giver may simply not have been recorded.', 'Le serveur lui fait donner ou rendre une quête que les joueurs n’ont vue que chez d’autres.')],
];
$issue = isset($issues[$_GET['issue'] ?? '']) ? $_GET['issue'] : 'twin';
$kind = in_array($_GET['kind'] ?? '', ['npc', 'go'], true) ? $_GET['kind'] : '';

if ($have && ($_GET['sql'] ?? '') === '1') {
    $out = ["-- Extras the tracker is sure enough to remove (" . date('Y-m-d H:i') . "): review before applying.", ''];
    foreach (['npc' => ['creature', 0], 'go' => ['gameobject', 1]] as $k => [$table, $type]) {
        $guids = array_map('intval', array_column(rows("SELECT guid FROM ft_world_extras WHERE issue = 'stacked' AND kind = ? AND guid IS NOT NULL ORDER BY guid", [$k]), 'guid'));
        if ($guids) {
            $list = implode(',', $guids);
            $out[] = "-- $table: " . count($guids) . " stacked copies";
            $out[] = "DELETE FROM `{$table}_addon` WHERE `guid` IN ($list);";
            $out[] = "DELETE FROM `spawn_group` WHERE `spawnType` = $type AND `spawnId` IN ($list);";
            $out[] = "DELETE FROM `$table` WHERE `guid` IN ($list);";
            $out[] = '';
        }
    }
    $twins = rows("SELECT entry, name, live FROM ft_world_extras WHERE issue = 'twin' AND note LIKE '%remove these%' ORDER BY entry");
    if ($twins) {
        $out[] = '-- creature: ' . count($twins) . ' old twins whose live entry the server spawns as well';
        foreach ($twins as $x) $out[] = '-- ' . (int)$x['entry'] . ' ' . str_replace(["\n", "\r"], ' ', (string)$x['name']) . ' (live: ' . preg_replace('/[^0-9,]/', '', (string)$x['live']) . ')';
        $list = implode(',', array_map(fn($x) => (int)$x['entry'], $twins));
        $out[] = "DELETE FROM `creature_addon` WHERE `guid` IN (SELECT `guid` FROM `creature` WHERE `id` IN ($list));";
        $out[] = "DELETE FROM `spawn_group` WHERE `spawnType` = 0 AND `spawnId` IN (SELECT `guid` FROM `creature` WHERE `id` IN ($list));";
        $out[] = "DELETE FROM `creature` WHERE `id` IN ($list);";
    }
    header('Content-Type: text/plain; charset=utf-8');
    header('Content-Disposition: attachment; filename="world-extras-removals.sql"');
    echo implode("\n", $out), "\n";
    exit;
}

$where = 'WHERE issue = ?' . ($kind ? ' AND kind = ?' : '');
$params = $kind ? [$issue, $kind] : [$issue];
$list = $have ? rows("SELECT * FROM ft_world_extras $where ORDER BY name, entry, guid LIMIT 3000", $params) : [];
$total = $have ? (int)value("SELECT COUNT(*) FROM ft_world_extras $where", $params) : 0;
$counts = [];
foreach ($issues as $key => $_) $counts[$key] = $have ? (int)value('SELECT COUNT(*) FROM ft_world_extras WHERE issue = ?', [$key]) : 0;
$wowhead = fn($k, $id) => 'https://www.wowhead.com/forever/' . ($k === 'go' ? 'object' : 'npc') . '=' . (int)$id;
page_start(t('Extras', 'En trop'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-clone"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Extras', 'En trop')) ?></h1>
    <p><?= e(t('What your server\'s world holds that the live game does not: the other way round from every other page. Each finding needs a witness that something else stands in its place (players\' EG Link recordings, Wowhead\'s Forever map): that nobody recorded a thing is never enough. The analysis fills this list. Nothing is changed from here.', 'Ce que le monde de votre serveur contient et que le jeu officiel n’a pas. Rien n’est modifié ici.')) ?></p></div></div>
</section>
<nav class="tabs">
  <?php foreach ($issues as $key => [$label]): ?>
  <a class="<?= $issue === $key ? 'is-active' : '' ?>" href="<?= e(url('admin/extras', ['issue' => $key])) ?>"><?= e($label) ?><em><?= number($counts[$key]) ?></em></a>
  <?php endforeach; ?>
  <a href="<?= e(url('admin/checks')) ?>"><i class="fas fa-scale-balanced"></i><?= e(t('Checks', 'Contrôles')) ?></a>
</nav>
<p class="tab-desc"><i class="fas fa-circle-info"></i> <?= e($issues[$issue][1]) ?></p>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No list yet: it is made by the next analysis (it needs an EG Link import).', 'Pas encore de liste : la prochaine analyse la fera (il faut un import EG Link).')) ?></p></div><?php else: ?>
<p class="small">
  <a class="link" href="<?= e(url('admin/extras', ['issue' => $issue])) ?>"><?= e(t('All', 'Tout')) ?></a> ·
  <a class="link" href="<?= e(url('admin/extras', ['issue' => $issue, 'kind' => 'npc'])) ?>"><?= e(t('Creatures', 'Créatures')) ?></a> ·
  <a class="link" href="<?= e(url('admin/extras', ['issue' => $issue, 'kind' => 'go'])) ?>"><?= e(t('Objects', 'Objets')) ?></a> ·
  <a class="link" href="<?= e(url('admin/extras', ['sql' => '1'])) ?>"><i class="fas fa-download"></i> <?= e(t('Removals as SQL (stacked + old twins)', 'Suppressions en SQL')) ?></a>
  <?php if ($total > count($list)): ?> · <span class="muted"><?= e(sprintf(t('first %s of %s', '%s premiers sur %s'), number(count($list)), number($total))) ?></span><?php endif; ?>
</p>
<table class="table">
  <thead><tr><th><?= e(t('Entry', 'Entrée')) ?></th><th><?= e(t('Where', 'Où')) ?></th><th><?= e(t('Server', 'Serveur')) ?></th><th><?= e(t('Live', 'Officiel')) ?></th><th><?= e(t('Finding', 'Constat')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <tr>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted"><?= e($x['kind'] === 'go' ? t('object', 'objet') : t('creature', 'créature')) ?> #<?= (int)$x['entry'] ?></small> <a class="link small" href="<?= e($wowhead($x['kind'], $x['entry'])) ?>" target="_blank" rel="noopener">Wowhead</a></td>
      <td class="small"><?php if ($x['guid'] !== null): ?>guid <?= (int)$x['guid'] ?><br><?php endif; ?><?php if ($x['map'] !== null): ?><?= e(t('map', 'carte')) ?> <?= (int)$x['map'] ?><?php if ($x['x'] !== null): ?> · <?= e(sprintf('%.1f %.1f %.1f', $x['x'], $x['y'], $x['z'])) ?><?php endif; ?><?php endif; ?></td>
      <td><?= $x['server'] === null ? '—' : number($x['server']) ?></td>
      <td class="small"><?php foreach (array_filter(explode(',', (string)$x['live'])) as $id): ?><?php if ($issue === 'crowded'): ?><?= e($id) ?> <?= e(t('on Wowhead', 'sur Wowhead')) ?><?php elseif ($issue === 'giver'): ?>#<?= (int)$id ?> <?php else: ?><a class="link" href="<?= e($wowhead($x['kind'], $id)) ?>" target="_blank" rel="noopener">#<?= (int)$id ?></a> <?php endif; ?><?php endforeach; ?></td>
      <td class="small"><?= e($x['note']) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>
<?php page_end();
