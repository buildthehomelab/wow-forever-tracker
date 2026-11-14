<?php
require_once FT_APP . '/foreverchanges.php';
$fcReferences = foreverchanges_references($type, $id);
if ($fcReferences): ?>
<section class="block">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Additional source', 'Source complémentaire')) ?></span><h2>ForeverChanges</h2></div><a class="link" href="https://foreverchanges.pro/addon" target="_blank" rel="noopener"><?= e(t('Source', 'Source')) ?> ↗</a></header>
  <p class="muted small"><?= e(t('Compiled reference data. These records help investigate gaps; they do not change server coverage or apply fixes.', 'Données de référence compilées. Ces données aident à examiner les manques ; elles ne modifient ni la couverture du serveur ni ses données.')) ?></p>
  <?php foreach ($fcReferences as $fcRow): $fcData = json_decode($fcRow['data'], true) ?: []; ?>
    <p class="small"><?= e(t('Build', 'Build')) ?> <?= (int)$fcRow['build'] ?> · <?= e($fcData['pack']['version'] ?? '') ?>
      <?php if ((int)$fcRow['build'] !== (int)(meta()['client_build'] ?? 0)): ?><em class="tag"><?= e(t('Different from the current analysis build', 'Différent du build de l’analyse actuelle')) ?></em><?php endif; ?>
    </p>
    <?php foreach ($fcData['datasets'] ?? [] as $fcKind => $fcValues): ?>
      <details><summary><?= e(str_replace('_', ' ', $fcKind)) ?> · <?= count($fcValues) ?></summary><pre><?= e(json_encode($fcValues, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)) ?></pre></details>
    <?php endforeach; ?>
    <details><summary><?= e(t('Provenance', 'Provenance')) ?></summary><p class="muted small">SHA-256: <?= e($fcData['archive_sha256'] ?? '') ?></p></details>
  <?php endforeach; ?>
</section>
<?php endif; ?>
