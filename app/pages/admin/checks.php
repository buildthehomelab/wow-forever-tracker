<?php
// Checks: the server's data compared with Wowhead's Forever tooltips. A ticked difference takes Wowhead's value through
// the Forge: previewed as SQL, applied in a transaction, kept in the history with its rollback.
require_once FT_APP . '/forge.php';
$have = table_exists('ft_npc_checks');
$kinds = ['level' => t('Level', 'Niveau'), 'rank' => t('Rank', 'Rang'), 'faction' => t('Faction', 'Faction'), 'sides' => t('Shown to one side', 'Montré à un seul camp'), 'discount' => t('Vendor reputation', 'Réputation du marchand')];
$issue = isset($kinds[$_GET['issue'] ?? '']) ? $_GET['issue'] : '';
$where = $issue ? 'WHERE FIND_IN_SET(?, issues)' : '';
$list = $have ? rows("SELECT * FROM ft_npc_checks $where ORDER BY issues DESC, name LIMIT 2000", $issue ? [$issue] : []) : [];
$counts = ['all' => $have ? (int)value('SELECT COUNT(*) FROM ft_npc_checks') : 0];
foreach ($kinds as $kind => $label) $counts[$kind] = $have ? (int)value('SELECT COUNT(*) FROM ft_npc_checks WHERE FIND_IN_SET(?, issues)', [$kind]) : 0;
$rankName = fn($r) => [0 => t('Normal', 'Normal'), 1 => t('Elite', 'Élite'), 2 => t('Rare Elite', 'Rare élite'), 3 => t('Boss', 'Boss'), 4 => t('Rare', 'Rare')][(int)$r] ?? (string)$r;
$levels = fn($lo, $hi) => $lo === null ? '??' : ((int)$lo === (int)$hi ? (string)(int)$lo : (int)$lo . '–' . (int)$hi);
page_start(t('Checks', 'Contrôles'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-scale-balanced"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Checks', 'Contrôles')) ?></h1>
    <p><?= e(t('Creatures whose level or rank on your server differs from Wowhead\'s Forever tooltips (quest givers, enders and targets, elites, rares and bosses that are spawned), and creatures whose side on your server contradicts what players saw on the live game. The analysis fills this list (with Wowhead lookups on). Nothing is changed unless you tick it below.', 'Créatures dont le niveau ou le rang sur votre serveur diffère des infobulles Forever de Wowhead (donneurs, valideurs et cibles de quête, élites, rares et boss placés), et créatures dont le camp sur votre serveur contredit ce que les joueurs ont vu en jeu. L’analyse remplit cette liste (avec les consultations Wowhead). Rien n’est modifié sans que vous le cochiez ci-dessous.')) ?></p></div></div>
</section>
<nav class="tabs">
  <a class="<?= $issue === '' ? 'is-active' : '' ?>" href="<?= e(url('admin/checks')) ?>"><?= e(t('All', 'Tout')) ?><em><?= number($counts['all']) ?></em></a>
  <?php foreach ($kinds as $kind => $label): ?>
  <a class="<?= $issue === $kind ? 'is-active' : '' ?>" href="<?= e(url('admin/checks', ['issue' => $kind])) ?>"><?= e($label) ?><em><?= number($counts[$kind]) ?></em></a>
  <?php endforeach; ?>
</nav>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No check yet: run the analysis with Wowhead lookups (the Docker image does it at start).', 'Pas encore de contrôle : lancez l’analyse avec les consultations Wowhead (l’image Docker le fait au démarrage).')) ?></p></div><?php else: ?>
<div class="alert"><i class="fas fa-people-arrows"></i><div><?= e(t('Faction, shown to one side, vendor reputation: where the server and the live game cannot both be right about whose side a creature is on. The live game is what players’ recordings (EG Link) show: how each side’s players saw the creature, and whom it served. A list to look at, with nothing to tick: no source states which faction is the right one. That a side never recorded a creature says nothing, so a creature the server shows to everyone that only one side should see is not found here.', 'Faction, montré à un seul camp, réputation du marchand : là où le serveur et le jeu ne peuvent pas avoir raison tous les deux sur le camp d’une créature. Le jeu, c’est ce que montrent les enregistrements des joueurs (EG Link) : comment les joueurs de chaque camp ont vu la créature, et qui elle a servi. Une liste à regarder, sans rien à cocher : aucune source ne dit quelle faction est la bonne. Qu’un camp n’ait jamais enregistré une créature ne dit rien : une créature que le serveur montre à tous et qu’un seul camp devrait voir n’est pas trouvée ici.')) ?></div></div>
<div class="alert"><i class="fas fa-circle-info"></i><div><?= e(t('Tick a difference to give the creature Wowhead’s value. Look before you tick: Wowhead’s tooltip is sometimes the one that is wrong (a level 1 that stands for "not known", a rank your server holds on purpose). A level the server or Wowhead does not state cannot be taken.', 'Cochez une différence pour donner à la créature la valeur de Wowhead. Regardez avant de cocher : c’est parfois l’infobulle de Wowhead qui se trompe (un niveau 1 qui veut dire « inconnu », un rang que votre serveur tient exprès). Un niveau que le serveur ou Wowhead n’indique pas ne peut pas être repris.')) ?></div></div>
<table class="table is-forge" data-forge-table data-tab="checks">
  <thead><tr><th><?= e(t('Creature', 'Créature')) ?></th><th><?= e(t('Server', 'Serveur')) ?></th><th>Wowhead</th><th><?= e(t('Take Wowhead’s', 'Prendre celui de Wowhead')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <tr>
      <?php $found = explode(',', (string)$x['issues']); $measured = (bool)array_intersect($found, ['level', 'rank']); $note = trim((string)($x['note'] ?? '')); ?>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted">#<?= (int)$x['entry'] ?></small> <a class="link small" href="https://www.wowhead.com/forever/npc=<?= (int)$x['entry'] ?>" target="_blank" rel="noopener">Wowhead</a>
        <?php if ($note !== ''): ?><br><small class="check-note"><i class="fas fa-people-arrows"></i> <?= e($note) ?></small><?php endif; ?></td>
      <td><?php if ($measured): ?><?= e(t('Level', 'Niveau')) ?> <?= e($levels($x['level_min'], $x['level_max'])) ?> · <?= e($rankName($x['rank_id'])) ?><?php else: ?><span class="muted">—</span><?php endif; ?></td>
      <td><?php if ($measured): ?><?= e(t('Level', 'Niveau')) ?> <?= e($levels($x['wh_min'], $x['wh_max'])) ?> · <?= e($x['wh_type']) ?> · <?= e($rankName($x['wh_rank'])) ?><?php else: ?><span class="muted">—</span><?php endif; ?></td>
      <td><?php foreach ($found as $kind): $label = mb_strtolower($kinds[$kind] ?? $kind); ?>
        <?php if (!in_array($kind, ['level', 'rank'], true)): ?><span class="tag is-plain" title="<?= e(t('For a person to look at: no source states which faction is the right one.', 'Pour une personne : aucune source ne dit quelle faction est la bonne.')) ?>"><?= e($label) ?></span>
        <?php elseif (forge_check_ops($x, $kind)): ?><label class="checkbox-line is-inline"><input type="checkbox" data-pick="<?= e(json_encode(['type' => 'npc', 'id' => (int)$x['entry'], 'kind' => $kind])) ?>"> <span><?= e($label) ?></span></label>
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
