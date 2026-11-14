<?php
// Checks: the server's data compared with Wowhead's Forever tooltips. A ticked difference takes Wowhead's value through
// the Forge: previewed as SQL, applied in a transaction, kept in the history with its rollback.
require_once FT_APP . '/forge.php';
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
    <p><?= e(t('Creatures whose level or rank on your server differs from Wowhead\'s Forever tooltips: quest givers, enders and targets, elites, rares and bosses that are spawned. The analysis fills this list (with Wowhead lookups on). Nothing is changed unless you tick it below.', 'Créatures dont le niveau ou le rang sur votre serveur diffère des infobulles Forever de Wowhead : donneurs, valideurs et cibles de quête, élites, rares et boss placés. L’analyse remplit cette liste (avec les consultations Wowhead). Rien n’est modifié sans que vous le cochiez ci-dessous.')) ?></p></div></div>
</section>
<nav class="tabs">
  <a class="<?= $issue === '' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks')) ?>"><?= e(t('All', 'Tout')) ?><em><?= number($counts['all']) ?></em></a>
  <a class="<?= $issue === 'level' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks', ['issue' => 'level'])) ?>"><?= e(t('Level', 'Niveau')) ?><em><?= number($counts['level']) ?></em></a>
  <a class="<?= $issue === 'rank' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks', ['issue' => 'rank'])) ?>"><?= e(t('Rank', 'Rang')) ?><em><?= number($counts['rank']) ?></em></a>
</nav>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No check yet: run the analysis with Wowhead lookups (the Docker image does it at start).', 'Pas encore de contrôle : lancez l’analyse avec les consultations Wowhead (l’image Docker le fait au démarrage).')) ?></p></div><?php else: ?>
<div class="alert"><i class="fas fa-circle-info"></i><div><?= e(t('Tick a difference to give the creature Wowhead’s value. Look before you tick: Wowhead’s tooltip is sometimes the one that is wrong (a level 1 that stands for "not known", a rank your server holds on purpose). A level the server or Wowhead does not state cannot be taken.', 'Cochez une différence pour donner à la créature la valeur de Wowhead. Regardez avant de cocher : c’est parfois l’infobulle de Wowhead qui se trompe (un niveau 1 qui veut dire « inconnu », un rang que votre serveur tient exprès). Un niveau que le serveur ou Wowhead n’indique pas ne peut pas être repris.')) ?></div></div>
<table class="table is-forge" data-forge-table data-tab="checks">
  <thead><tr><th><?= e(t('Creature', 'Créature')) ?></th><th><?= e(t('Server', 'Serveur')) ?></th><th>Wowhead</th><th><?= e(t('Take Wowhead’s', 'Prendre celui de Wowhead')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <tr>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted">#<?= (int)$x['entry'] ?></small> <a class="link small" href="https://www.wowhead.com/forever/npc=<?= (int)$x['entry'] ?>" target="_blank" rel="noopener">Wowhead</a></td>
      <td><?= e(t('Level', 'Niveau')) ?> <?= e($levels($x['level_min'], $x['level_max'])) ?> · <?= e($rankName($x['rank_id'])) ?></td>
      <td><?= e(t('Level', 'Niveau')) ?> <?= e($levels($x['wh_min'], $x['wh_max'])) ?> · <?= e($x['wh_type']) ?> · <?= e($rankName($x['wh_rank'])) ?></td>
      <td><?php foreach (explode(',', (string)$x['issues']) as $kind): $label = $kind === 'level' ? t('level', 'niveau') : t('rank', 'rang'); ?>
        <?php if (forge_check_ops($x, $kind)): ?><label class="checkbox-line is-inline"><input type="checkbox" data-pick="<?= e(json_encode(['type' => 'npc', 'id' => (int)$x['entry'], 'kind' => $kind])) ?>"> <span><?= e($label) ?></span></label>
        <?php else: ?><span class="muted" title="<?= e(t('Not stated on one side: nothing to take.', 'Non indiqué d’un côté : rien à reprendre.')) ?>"><?= e($label) ?></span><?php endif; ?>
      <?php endforeach; ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>
<div class="action-bar" data-action-bar hidden>
  <div class="action-count"><strong data-selected-count>0</strong> <span><?= e(t('selected', 'sélectionnée(s)')) ?></span></div>
  <button class="btn is-small" type="button" data-forge-preview-selection><i class="fas fa-eye"></i> <?= e(t('Preview SQL', 'Voir le SQL')) ?></button>
  <button class="btn is-small" type="button" data-forge-download><i class="fas fa-download"></i> .sql</button>
  <button class="btn is-small is-gold" type="button" data-forge-apply-selection><i class="fas fa-bolt"></i> <?= e(t('Take Wowhead’s values', 'Prendre les valeurs de Wowhead')) ?></button>
</div>
<?php require FT_APP . '/pages/admin/_modals.php'; ?>
<?php page_end();
