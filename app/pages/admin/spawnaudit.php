<?php
// Spawn audit: how many of each creature the server's world holds, against the worlds of other cores
// (tools/ft/spawncount.py fills ft_spawn_audit at each analysis; docs/SPAWNS.md "Spawn audit"). A list to look at:
// nothing is changed from here. ?csv=1 gives the list of the open verdict as a CSV file.
$have = table_exists('ft_spawn_audit');
$verdicts = [
    'above_all' => [t('Above every reference', 'Au-dessus de toutes les références'), t('More of the creature stand at one time on that map than in any reference world that has it: no era of the game had that many. An import laid a second spawn set over the first. More spots are fine; too many up at once is the fault: the fix is a pool that keeps the reference\'s number up, not removing spots. "No reference" counts the spawns standing where no reference has the creature: look at those first.', 'Plus d\'exemplaires présents en même temps sur cette carte que dans tout monde de référence qui la connaît : aucune époque du jeu n\'en avait autant. Un import a posé un second jeu de placements sur le premier. Davantage de points est bien ; trop d\'exemplaires à la fois est le défaut : la correction est un groupe (pool) qui garde le nombre de la référence, pas la suppression de points.')],
    'above_classic' => [t('Above Classic only', 'Au-dessus de Classic seulement'), t('More than VMaNGOS (the 1.12 game), but a 3.3.5 core has as many: the later game\'s numbers, as in the zones rebuilt after 1.12. Right only where WoW Forever uses the later zone.', 'Plus que VMaNGOS (le jeu en 1.12), mais un noyau 3.3.5 en a autant : les chiffres du jeu plus tardif, comme dans les zones refaites après la 1.12. Correct seulement là où WoW Forever utilise la zone plus tardive.')],
    'below_all' => [t('Below every reference', 'En dessous de toutes les références'), t('Fewer than every reference world: spawns may be missing. A creature Forever moved or replaced shows here too.', 'Moins que tout monde de référence : des placements manquent peut-être. Une créature que Forever a déplacée ou remplacée apparaît aussi ici.')],
    'ok' => [t('Within the references', 'Dans les références'), t('As many up as the references have, give or take.', 'Autant d\'exemplaires présents que dans les références, à peu près.')],
    'unknown' => [t('No reference', 'Sans référence'), t('No reference world has the creature on that map: Forever\'s own creatures, and later ones. Nothing to compare with.', 'Aucun monde de référence n\'a la créature sur cette carte : les créatures propres à Forever, et les plus tardives. Rien à comparer.')],
];
$verdict = isset($verdicts[$_GET['verdict'] ?? '']) ? $_GET['verdict'] : 'above_all';
$map = ($_GET['map'] ?? '') === '' ? null : (int)$_GET['map'];
$where = 'WHERE verdict = ?' . ($map !== null ? ' AND map = ?' : '');
$params = $map !== null ? [$verdict, $map] : [$verdict];
$order = $verdict === 'below_all' ? 'most - up DESC' : 'up - most DESC';
$sources = $have && table_exists('ft_spawn_audit_refs') ? rows('SELECT * FROM ft_spawn_audit_refs ORDER BY source') : [];

if ($have && ($_GET['csv'] ?? '') === '1') {
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="spawn-audit-' . $verdict . '.csv"');
    $out = fopen('php://output', 'w');
    fputcsv($out, array_merge(['entry', 'name', 'map', 'verdict', 'spots', 'up', 'most_in_a_reference', 'no_reference', 'later_core_only'],
        array_merge(...array_map(fn($s) => [$s['source'] . '_spots', $s['source'] . '_up'], $sources ?: [])), ['guids_no_reference']));
    foreach (rows("SELECT * FROM ft_spawn_audit $where ORDER BY $order, name, entry", $params) as $x) {
        $refs = json_decode((string)$x['refs'], true) ?: [];
        $cells = [];
        foreach ($sources as $s) { $cells[] = $refs[$s['source']][0] ?? ''; $cells[] = $refs[$s['source']][1] ?? ''; }
        fputcsv($out, array_merge([$x['entry'], $x['name'], $x['map'], $x['verdict'], $x['spots'], $x['up'], $x['most'], $x['unmatched'], $x['later']], $cells, [$x['guids']]));
    }
    exit;
}

$list = $have ? rows("SELECT * FROM ft_spawn_audit $where ORDER BY $order, name, entry LIMIT 2000", $params) : [];
$total = $have ? (int)value("SELECT COUNT(*) FROM ft_spawn_audit $where", $params) : 0;
$counts = [];
foreach ($verdicts as $key => $_) $counts[$key] = $have ? (int)value('SELECT COUNT(*) FROM ft_spawn_audit WHERE verdict = ?', [$key]) : 0;
$over = $have ? (float)value("SELECT COALESCE(SUM(up - most), 0) FROM ft_spawn_audit WHERE verdict = 'above_all'") : 0;
$maps = $have ? rows('SELECT map, COUNT(*) n FROM ft_spawn_audit WHERE verdict = ? GROUP BY map ORDER BY n DESC LIMIT 12', [$verdict]) : [];
$amount = fn($n) => rtrim(rtrim(number_format((float)$n, 1, '.', ','), '0'), '.');
page_start(t('Spawn audit', 'Audit des placements'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-users-viewfinder"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Spawn audit', 'Audit des placements')) ?></h1>
    <p><?= e(t('How many of each creature your world holds on each map, against the worlds of other cores. Two numbers: spots (the places it can stand) and up (how many stand at one time: a pool shows only some of its spots). The references are witnesses of their own era, not of WoW Forever. The analysis fills this list. Nothing is changed from here.', 'Combien d\'exemplaires de chaque créature votre monde contient sur chaque carte, face aux mondes d\'autres noyaux. Deux nombres : les points (où elle peut se tenir) et les présents (combien se tiennent en même temps : un groupe ne montre qu\'une partie de ses points). Les références témoignent de leur époque, pas de WoW Forever. L\'analyse remplit cette liste. Rien n\'est modifié d\'ici.')) ?></p></div></div>
</section>
<nav class="tabs">
  <?php foreach ($verdicts as $key => [$label]): ?>
  <a class="<?= $verdict === $key ? 'is-active' : '' ?>" href="<?= e(url('admin/spawnaudit', ['verdict' => $key])) ?>"><?= e($label) ?><em><?= number($counts[$key]) ?></em></a>
  <?php endforeach; ?>
  <a href="<?= e(url('admin/extras')) ?>"><i class="fas fa-clone"></i><?= e(t('Extras', 'En trop')) ?></a>
</nav>
<p class="tab-desc"><i class="fas fa-circle-info"></i> <?= e($verdicts[$verdict][1]) ?></p>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No list yet: it is made by the next analysis, which downloads the reference worlds once.', 'Pas encore de liste : la prochaine analyse la fera, en téléchargeant une fois les mondes de référence.')) ?></p></div><?php else: ?>
<p class="small">
  <?php foreach ($sources as $s): ?><span class="muted"><?= e($s['name']) ?> <?= e(substr((string)$s['version'], 0, 12)) ?>: <?= number((int)$s['spots']) ?> <?= e(t('spots', 'points')) ?></span> · <?php endforeach; ?>
  <?php if ($verdict === 'above_all'): ?><strong><?= e(sprintf(t('%s creatures up beyond every reference', '%s créatures présentes au-delà de toute référence'), number((int)round($over)))) ?></strong> · <?php endif; ?>
  <a class="link" href="<?= e(url('admin/spawnaudit', ['verdict' => $verdict, 'csv' => '1'] + ($map !== null ? ['map' => $map] : []))) ?>"><i class="fas fa-download"></i> CSV</a>
  <?php if ($total > count($list)): ?> · <span class="muted"><?= e(sprintf(t('first %s of %s', '%s premiers sur %s'), number(count($list)), number($total))) ?></span><?php endif; ?>
</p>
<p class="small">
  <a class="link" href="<?= e(url('admin/spawnaudit', ['verdict' => $verdict])) ?>"><?= e(t('All maps', 'Toutes les cartes')) ?></a>
  <?php foreach ($maps as $m): ?> · <a class="link" href="<?= e(url('admin/spawnaudit', ['verdict' => $verdict, 'map' => (int)$m['map']])) ?>"><?= e(t('map', 'carte')) ?> <?= (int)$m['map'] ?> <span class="muted">(<?= number((int)$m['n']) ?>)</span></a><?php endforeach; ?>
</p>
<table class="table">
  <thead><tr><th><?= e(t('Creature', 'Créature')) ?></th><th><?= e(t('Map', 'Carte')) ?></th><th><?= e(t('Spots', 'Points')) ?></th><th><?= e(t('Up', 'Présents')) ?></th>
    <?php foreach ($sources as $s): ?><th><?= e($s['name']) ?></th><?php endforeach; ?>
    <th><?= e(t('No reference', 'Sans référence')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): $refs = json_decode((string)$x['refs'], true) ?: []; ?>
    <tr>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted">#<?= (int)$x['entry'] ?></small> <a class="link small" href="https://www.wowhead.com/forever/npc=<?= (int)$x['entry'] ?>" target="_blank" rel="noopener">Wowhead</a></td>
      <td class="small"><?= (int)$x['map'] ?></td>
      <td><?= number((int)$x['spots']) ?></td>
      <td><strong><?= e($amount($x['up'])) ?></strong></td>
      <?php foreach ($sources as $s): $r = $refs[$s['source']] ?? [0, 0]; ?>
      <td class="small"><?php if (!$r[0]): ?>—<?php else: ?><?= e($amount($r[1])) ?> <span class="muted">(<?= number((int)$r[0]) ?> <?= e(t('spots', 'points')) ?>)</span><?php endif; ?></td>
      <?php endforeach; ?>
      <td class="small"><?php if ((int)$x['unmatched']): ?><span title="<?= e(substr((string)$x['guids'], 0, 1500)) ?>"><?= number((int)$x['unmatched']) ?></span><?php else: ?>—<?php endif; ?><?php if ((int)$x['later']): ?> <span class="muted">+ <?= number((int)$x['later']) ?> <?= e(t('at a later core\'s spot', 'au point d\'un noyau plus tardif')) ?></span><?php endif; ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>
<?php page_end();
