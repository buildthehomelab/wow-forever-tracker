<?php
// Checks: the server's data compared with Wowhead's Forever tooltips (report only; nothing is changed from here).
$have = table_exists('ft_npc_checks');
$issue = in_array($_GET['issue'] ?? '', ['level', 'rank'], true) ? $_GET['issue'] : '';
$where = $issue ? 'WHERE FIND_IN_SET(?, issues)' : '';
$list = $have ? rows("SELECT * FROM ft_npc_checks $where ORDER BY issues DESC, name LIMIT 2000", $issue ? [$issue] : []) : [];
$counts = $have ? ['all' => (int)value('SELECT COUNT(*) FROM ft_npc_checks'), 'level' => (int)value("SELECT COUNT(*) FROM ft_npc_checks WHERE FIND_IN_SET('level', issues)"), 'rank' => (int)value("SELECT COUNT(*) FROM ft_npc_checks WHERE FIND_IN_SET('rank', issues)")] : ['all' => 0, 'level' => 0, 'rank' => 0];
$rankName = fn($r) => [0 => t('Normal', 'Normal'), 1 => t('Elite', 'Élite'), 2 => t('Rare Elite', 'Rare élite'), 3 => t('Boss', 'Boss'), 4 => t('Rare', 'Rare')][(int)$r] ?? (string)$r;
$levels = fn($lo, $hi) => $lo === null ? '??' : ((int)$lo === (int)$hi ? (string)(int)$lo : (int)$lo . '–' . (int)$hi);
page_start(t('Checks', 'Contrôles'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-scale-balanced"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Checks', 'Contrôles')) ?></h1>
    <p><?= e(t('Creatures whose level or rank on your server differs from Wowhead\'s Forever tooltips: quest givers, enders and targets, elites, rares and bosses that are spawned. The analysis fills this list (with Wowhead lookups on); nothing is changed from here.', 'Créatures dont le niveau ou le rang sur votre serveur diffère des infobulles Forever de Wowhead : donneurs, valideurs et cibles de quête, élites, rares et boss placés. L’analyse remplit cette liste (avec les consultations Wowhead) ; rien n’est modifié d’ici.')) ?></p></div></div>
</section>
<nav class="tabs">
  <a class="<?= $issue === '' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks')) ?>"><?= e(t('All', 'Tout')) ?><em><?= number($counts['all']) ?></em></a>
  <a class="<?= $issue === 'level' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks', ['issue' => 'level'])) ?>"><?= e(t('Level', 'Niveau')) ?><em><?= number($counts['level']) ?></em></a>
  <a class="<?= $issue === 'rank' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks', ['issue' => 'rank'])) ?>"><?= e(t('Rank', 'Rang')) ?><em><?= number($counts['rank']) ?></em></a>
</nav>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No check yet: run the analysis with Wowhead lookups (the Docker image does it at start).', 'Pas encore de contrôle : lancez l’analyse avec les consultations Wowhead (l’image Docker le fait au démarrage).')) ?></p></div><?php else: ?>
<table class="table is-forge">
  <thead><tr><th><?= e(t('Creature', 'Créature')) ?></th><th><?= e(t('Server', 'Serveur')) ?></th><th>Wowhead</th><th><?= e(t('Differs in', 'Diffère par')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <tr>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted">#<?= (int)$x['entry'] ?></small> <a class="link small" href="https://www.wowhead.com/forever/npc=<?= (int)$x['entry'] ?>" target="_blank" rel="noopener">Wowhead</a></td>
      <td><?= e(t('Level', 'Niveau')) ?> <?= e($levels($x['level_min'], $x['level_max'])) ?> · <?= e($rankName($x['rank_id'])) ?></td>
      <td><?= e(t('Level', 'Niveau')) ?> <?= e($levels($x['wh_min'], $x['wh_max'])) ?> · <?= e($x['wh_type']) ?> · <?= e($rankName($x['wh_rank'])) ?></td>
      <td><?= e(str_replace(['level', 'rank', ','], [t('level', 'niveau'), t('rank', 'rang'), ', '], $x['issues'])) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>
<?php page_end();
