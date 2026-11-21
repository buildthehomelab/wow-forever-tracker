<?php
// The Forge › Query: one read-only statement on the world, hotfixes or tracker database (app/query.php).
require_once FT_APP . '/query.php';
$databases = query_databases();
$label = isset($databases[$_POST['db'] ?? $_GET['db'] ?? '']) ? ($_POST['db'] ?? $_GET['db']) : 'world';
$sql = (string)($_POST['sql'] ?? $_GET['sql'] ?? '');
$out = null; $error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!csrf_ok($_POST['csrf'] ?? null)) $error = t('Session expired, please try again.', 'Session expirée, réessayez.');
    else {
        $out = query_run($label, $sql);
        if (!$out['ok']) $error = $out['error'];
    }
}
page_start(t('Query', 'Requête'), 'admin');
?>
<section class="page-head"><div class="page-title"><span class="page-icon is-gold"><i class="fas fa-database"></i></span>
  <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Query', 'Requête')) ?></h1>
  <p><?= e(sprintf(t('One statement that reads (SELECT, WITH, SHOW, EXPLAIN, DESCRIBE) on a database the tracker reads, as a MySQL account that may only read (checked before every query), in a read-only transaction that is rolled back, stops after %d seconds and shows at most %s rows. Nothing can be changed from here.', 'Une requête de lecture sur une base que le tracker lit, dans une transaction en lecture seule annulée ensuite ; %d secondes et %s lignes au plus. Rien ne peut être modifié ici.'), QUERY_SECONDS, number(QUERY_MAX_ROWS))) ?></p></div></div></section>
<?php if ($error): ?><div class="alert is-warn"><i class="fas fa-triangle-exclamation"></i><div><?= e($error) ?></div></div><?php endif; ?>
<form method="post" class="block form" id="query-form" data-csrf="<?= e(csrf_token()) ?>">
  <input type="hidden" name="csrf" value="<?= e(csrf_token()) ?>">
  <div class="form-row">
    <label class="field is-stacked"><span><?= e(t('Database', 'Base')) ?></span><select name="db">
      <?php foreach ($databases as $key => $name): ?><option value="<?= e($key) ?>" <?= $key === $label ? 'selected' : '' ?>><?= e($key . ' (' . $name . ')') ?></option><?php endforeach; ?>
    </select></label>
  </div>
  <label class="field is-stacked"><span>SQL</span><textarea name="sql" rows="10" spellcheck="false" style="font-family: monospace"><?= e($sql) ?></textarea></label>
  <button class="btn is-primary"><i class="fas fa-play"></i> <?= e(t('Run', 'Exécuter')) ?></button>
</form>
<?php if ($out && $out['ok']): ?>
<p class="small"><?= e(sprintf(t('%s rows in %d ms on %s.', '%s lignes en %d ms sur %s.'), number(count($out['rows'])), $out['ms'], $out['database'])) ?><?php if ($out['truncated']): ?> <strong><?= e(sprintf(t('Stopped at %s rows.', 'Arrêté à %s lignes.'), number(QUERY_MAX_ROWS))) ?></strong><?php endif; ?></p>
<div style="overflow-x: auto">
<table class="table" id="query-result">
  <thead><tr><?php foreach ($out['columns'] as $c): ?><th><?= e($c) ?></th><?php endforeach; ?></tr></thead>
  <tbody>
  <?php foreach ($out['rows'] as $r): ?><tr><?php foreach ($r as $v): ?><td class="small"><?= $v === null ? '<span class="muted">NULL</span>' : e((string)$v) ?></td><?php endforeach; ?></tr><?php endforeach; ?>
  </tbody>
</table>
</div>
<?php endif; ?>
<?php page_end();
