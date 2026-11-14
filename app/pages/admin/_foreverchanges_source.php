<?php
require_once FT_APP . '/foreverchanges.php';
$fcStatus = foreverchanges_status();
$fcRunning = source_running('foreverchanges');
$fcLogPath = source_log('foreverchanges');
$fcLog = is_file($fcLogPath) ? trim((string)@shell_exec('tail -n 1 ' . escapeshellarg($fcLogPath))) : '';
$fcCounts = $fcStatus ? rows("SELECT f.subject_kind type, COUNT(*) total, SUM(e.id IS NOT NULL) matched, SUM(e.status <> 'ok' AND e.internal = 0) gaps FROM ft_world_facts f LEFT JOIN ft_entities e ON e.type = f.subject_kind AND e.id = f.subject WHERE f.source = 'foreverchanges' AND f.kind = 'reference' GROUP BY f.subject_kind ORDER BY f.subject_kind") : [];
$fcGaps = $fcStatus ? rows("SELECT e.* FROM ft_entities e JOIN ft_world_facts f ON e.type = f.subject_kind AND e.id = f.subject WHERE f.source = 'foreverchanges' AND f.kind = 'reference' AND e.status <> 'ok' AND e.internal = 0 ORDER BY e.type, e.id LIMIT 40") : [];
?>
<section class="block import-add" id="foreverchanges">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Additional reference source', 'Source de référence complémentaire')) ?></span><h2>ForeverChanges / ForeverMaster</h2></div><a class="link" href="https://foreverchanges.pro/about" target="_blank" rel="noopener"><?= e(t('About the data', 'À propos des données')) ?> ↗</a></header>
  <p><?= e(t('Items, profession recipes, quest details, dungeon loot and training from the official addon download. References appear on matching resource pages for review. No world rows or coverage scores are changed.', 'Objets, recettes de métiers, détails de quêtes, butin de donjons et apprentissage depuis le téléchargement officiel de l’addon. Les références apparaissent sur les ressources correspondantes. Aucune donnée du monde ni aucun score de couverture n’est modifié.')) ?></p>
  <p class="muted small"><?= e(t('All Rights Reserved. Kept as an administrator reference; excluded from public data exports. Talent build presets are not a complete talent database.', 'Tous droits réservés. Conservé comme référence pour les administrateurs ; exclu des exports publics. Les modèles de talents ne constituent pas une base complète de talents.')) ?></p>
  <div class="btn-row"><button class="btn is-small is-gold" type="button" data-scribe="source_foreverchanges" <?= $fcRunning ? 'disabled' : '' ?>><i class="fas fa-rotate"></i> <?= e($fcRunning ? t('ForeverChanges: running…', 'ForeverChanges : en cours…') : t('Refresh ForeverChanges', 'Actualiser ForeverChanges')) ?></button></div>
  <?php if ($fcLog !== ''): ?><p class="muted small"><?= e($fcLog) ?></p><?php endif; ?>
  <?php if ($fcStatus): ?>
    <p class="muted small"><?= e($fcStatus['loaded_at']) ?> · <?= number($fcStatus['facts']) ?> <?= e(t('reference records', 'entrées de référence')) ?> · <?= e($fcStatus['pin']) ?></p>
    <table><thead><tr><th><?= e(t('Category', 'Catégorie')) ?></th><th><?= e(t('References', 'Références')) ?></th><th><?= e(t('In this tracker', 'Dans ce tracker')) ?></th><th><?= e(t('Incomplete resources', 'Ressources incomplètes')) ?></th></tr></thead><tbody>
    <?php foreach ($fcCounts as $fcCount): ?><tr><td><?= e($fcCount['type']) ?></td><td><?= number($fcCount['total']) ?></td><td><?= number($fcCount['matched']) ?></td><td><?= number($fcCount['gaps'] ?? 0) ?></td></tr><?php endforeach; ?>
    </tbody></table>
    <?php if ($fcGaps): ?><p><?= e(t('First 40 matching incomplete resources. Open one to inspect its ForeverChanges references.', 'Les 40 premières ressources incomplètes correspondantes. Ouvrez-en une pour consulter ses références ForeverChanges.')) ?></p><ul class="list is-compact">
      <?php foreach ($fcGaps as $fcGap): ?><li><a href="<?= e(entry_url($fcGap['type'], (int)$fcGap['id'])) ?>"><?= e(display_name($fcGap)) ?></a> <small><?= e($fcGap['type']) ?> #<?= (int)$fcGap['id'] ?></small></li><?php endforeach; ?>
    </ul><?php endif; ?>
  <?php endif; ?>
</section>
