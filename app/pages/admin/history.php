<?php
// Forge history: every operation with its SQL and a rollback button.
require_once FT_APP . '/forge.php';
forge_schema();
$list = rows('SELECT id, created_at, admin, kind, items, rows_count, state, message, rolled_back_at, sql_apply, sql_rollback, ' . forge_interrupted_sql() . ' interrupted FROM ft_forge_log ORDER BY id DESC LIMIT 200');
page_start(t('Forge history', 'Historique de la Forge'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-clock-rotate-left"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('History', 'Historique')) ?></h1>
    <p><?= e(t('Every change made by the Forge, with the exact SQL. Rolling back runs the saved rollback in a transaction.', 'Chaque changement fait par la Forge, avec le SQL exact. L’annulation exécute le script enregistré dans une transaction.')) ?></p>
    <p class="muted small"><?= e(t('Tested here and good to go live? "Data repo .sql" turns an operation into a world update file for your data repository (docs/DATA-REPO.md).', 'Testé ici et prêt pour le serveur principal ? « Dépôt .sql » transforme une opération en fichier de mise à jour world pour votre dépôt de données (docs/DATA-REPO.md).')) ?></p></div></div>
  <?php if ($list): ?><button class="btn" type="button" data-forge-datarepo-all><i class="fas fa-file-zipper"></i> <?= e(t('All applied, as data repo files', 'Tout ce qui est appliqué, en fichiers du dépôt')) ?></button><?php endif; ?>
</section>
<?php if (!$list): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-feather"></i></div><p><?= e(t('Nothing forged yet.', 'Rien n’a encore été forgé.')) ?></p></div><?php endif; ?>
<div class="history-list">
<?php foreach ($list as $x): $items = json_decode($x['items'], true) ?: []; $apply = json_decode($x['sql_apply'], true) ?: []; $rollback = json_decode($x['sql_rollback'], true) ?: []; ?>
  <article class="block op is-<?= e($x['state']) ?>">
    <header class="op-head">
      <span class="fix-kind is-<?= e(explode(',', $x['kind'])[0]) ?>"><i class="fas fa-bolt"></i></span>
      <div><strong>#<?= (int)$x['id'] ?> · <?= e(implode(', ', array_map('forge_kind_label', explode(',', $x['kind'])))) ?></strong>
        <small><?= e(date(t('M j, Y H:i', 'd/m/Y H:i'), strtotime($x['created_at']))) ?> · <?= e($x['admin']) ?> · <?= count($items) ?> <?= e(t('resource(s)', 'ressource(s)')) ?> · <?= (int)$x['rows_count'] ?> <?= e(t('rows', 'lignes')) ?><?= $x['rolled_back_at'] ? ' · ' . e(t('rolled back', 'annulée le')) . ' ' . e(date(t('M j H:i', 'd/m H:i'), strtotime($x['rolled_back_at']))) : '' ?></small></div>
      <span class="badge is-<?= $x['state'] === 'applied' ? 'ok' : ($x['state'] === 'failed' ? 'missing' : 'partial') ?>"><i></i><?= e(forge_state_label($x['state'])) ?></span>
      <?php if ($x['state'] === 'applied'): ?><button class="btn is-small" type="button" data-forge-datarepo="<?= (int)$x['id'] ?>" title="<?= e(t('Update file for the data repository: the rows this operation added, as they are on the server now', 'Fichier de mise à jour pour le dépôt de données : les lignes ajoutées par cette opération, telles qu’elles sont sur le serveur')) ?>"><i class="fas fa-code-branch"></i> <?= e(t('Data repo .sql', 'Dépôt .sql')) ?></button>
      <?php endif; ?><?php if ($x['state'] === 'applied' || $x['interrupted']): ?><button class="btn is-small" type="button" data-forge-rollback="<?= (int)$x['id'] ?>"><i class="fas fa-rotate-left"></i> <?= e(t('Roll back', 'Annuler')) ?></button><?php endif; ?>
    </header>
    <?php if ($x['state'] === 'pending'): ?><p class="warn-text small"><?= e($x['interrupted']
        ? t('The website stopped, or lost its database, while this was being applied: nobody recorded whether the change was written. Look at the server with the SQL below. Roll back runs the saved rollback, which only removes what this operation would have added.', 'Le site s’est arrêté, ou a perdu sa base, pendant l’application : personne n’a noté si le changement a été écrit. Vérifiez le serveur avec le SQL ci-dessous. Annuler exécute l’annulation enregistrée, qui ne retire que ce que cette opération aurait ajouté.')
        : t('Being applied right now. Reload the page in a moment.', 'En cours d’application. Rechargez la page dans un instant.')) ?></p><?php endif; ?>
    <?php if ($x['message']): ?><p class="<?= $x['state'] === 'failed' ? 'warn-text' : 'muted' ?> small"><?= e($x['message']) ?></p><?php endif; ?>
    <div class="op-items"><?php foreach (array_slice($items, 0, 24) as $it): ?><?php if (!isset(TYPES[$it['type']])): ?><span class="tag is-plain"><?= e($it['type'] === 'import' ? 'Import #' : ($it['kind'] === 'go' ? t('Object', 'Objet') . ' ' : t('Creature', 'PNJ') . ' ')) ?><?= (int)$it['id'] ?></span><?php else: ?><a class="tag is-plain" href="<?= e(entry_url($it['type'], (int)$it['id'])) ?>" data-tt="<?= e($it['type'] . ':' . (int)$it['id']) ?>"><?= e(type_label($it['type'])) ?> <?= (int)$it['id'] ?></a><?php endif; ?><?php endforeach; ?><?= count($items) > 24 ? '<span class="more">+' . (count($items) - 24) . '</span>' : '' ?></div>
    <details class="op-sql"><summary><?= e(t('SQL', 'SQL')) ?></summary>
      <?php foreach ($apply as $database => $sql): ?><p class="facts-title"><?= e($database) ?> · <?= e(t('apply', 'application')) ?></p><pre class="code is-sql"><?= e(mb_strimwidth($sql, 0, 20000, '…')) ?></pre><?php endforeach; ?>
      <?php foreach ($rollback as $database => $sql): ?><p class="facts-title"><?= e($database) ?> · <?= e(t('rollback', 'annulation')) ?></p><pre class="code is-sql"><?= e($sql) ?></pre><?php endforeach; ?>
    </details>
  </article>
<?php endforeach; ?>
</div>
<?php require FT_APP . '/pages/admin/_modals.php'; ?>
<?php page_end();
