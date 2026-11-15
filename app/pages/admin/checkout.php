<?php
// Checkout (administrators): every step of the timeline, the SQL file of its client data for a test realm's hotfixes
// database, made in the background and downloaded from here (docs/CHECKOUT.md).
require_once FT_APP . '/checkout.php';

if (isset($_GET['download'])) {
    $path = checkout_file((string)$_GET['download']);
    if ($path === null) { http_response_code(404); exit(t('No such file: make it first.', 'Aucun fichier : créez-le d’abord.')); }
    header('Content-Type: application/sql; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . basename($path) . '"');
    header('Content-Length: ' . filesize($path));
    readfile($path);
    exit;
}

$files = checkout_files();
$status = checkout_status();
// the steps as the timeline shows them, newest first: each build, its hotfix updates above it
$steps = [];
foreach (builds() as $b) {
    if (build_is_vanilla($b)) continue;   // the original game's tables are another client's: no checkout
    foreach (hotfix_updates() as $u) if ((int)$u['build'] === (int)$b['build'])
        $steps[] = ['id' => $u['build'] . '+' . $u['hotfix'], 'title' => hotfix_name($u), 'sub' => sprintf(t('After build %s', 'Après le build %s'), $b['version']), 'date' => $u['released'], 'hotfix' => true];
    $steps[] = ['id' => (string)(int)$b['build'], 'title' => $b['version'], 'sub' => build_is_beta($b) ? t('Beta', 'Bêta') : '', 'date' => $b['released'], 'hotfix' => false, 'server' => (int)$b['is_server']];
}
// a file of a step the timeline no longer lists (an older analysis) stays downloadable
$listed = array_column($steps, 'id');
foreach ($files as $id => $file) if (!in_array((string)$id, $listed, true))
    $steps[] = ['id' => (string)$id, 'title' => (string)($file['manifest']['version'] ?? $id), 'sub' => t('Not on the timeline any more', 'Plus sur la chronologie'), 'date' => null, 'hotfix' => false];

page_start(t('Checkout', 'Checkout'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-code-branch"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Checkout', 'Checkout')) ?></h1>
    <p><?= e(t('The client’s data at any step of the timeline, as an SQL file for a test realm’s hotfixes database: every record that differs from your server’s DB2 files, and what they have that the step does not, sent to clients as one hotfix push. Loading a file replaces the tables it names, so load it into a test realm, never the live one, then restart its worldserver.', 'Les données client à n’importe quelle étape de la chronologie, en fichier SQL pour la base hotfixes d’un royaume de test : chaque enregistrement qui diffère des fichiers DB2 de votre serveur, et ce qu’ils ont que l’étape n’a pas, envoyés aux clients en un seul correctif. Charger un fichier remplace les tables qu’il nomme : chargez-le sur un royaume de test, jamais sur le principal, puis redémarrez son worldserver.')) ?></p>
    <p class="muted small"><?= e(t('A build stored for the changelog alone is completed from Blizzard’s CDN first (about 40 MB, once). What a checkout cannot say is in docs/CHECKOUT.md and in each file’s list of tables left out.', 'Un build stocké pour le seul changelog est d’abord complété depuis le CDN de Blizzard (environ 40 Mo, une fois). Ce qu’un checkout ne peut pas dire est dans docs/CHECKOUT.md et dans la liste des tables écartées de chaque fichier.')) ?></p></div></div>
</section>

<div class="analysis-card" data-checkout data-running="<?= $status['running'] ? 1 : 0 ?>">
  <div><strong><?= e(t('Last run', 'Dernière exécution')) ?></strong>
    <small data-checkout-text><?php if ($status['running']): ?><?= e(sprintf(t('Writing step %s…', 'Écriture de l’étape %s…'), $status['step'])) ?>
      <?php elseif ($status['step'] !== ''): ?><?= e(sprintf($status['failed'] ? t('Failed: step %s, see the log.', 'Échec : étape %s, voir le journal.') : t('Step %s written.', 'Étape %s écrite.'), $status['step'])) ?>
      <?php else: ?><?= e(t('None yet.', 'Aucune pour l’instant.')) ?><?php endif; ?></small></div>
  <pre class="analysis-log" data-checkout-log <?= $status['log'] === '' ? 'hidden' : '' ?>><?= e($status['log']) ?></pre>
</div>

<div class="table-card"><table class="table">
  <thead><tr><th><?= e(t('Step', 'Étape')) ?></th><th><?= e(t('Date', 'Date')) ?></th><th><?= e(t('File', 'Fichier')) ?></th><th></th></tr></thead>
  <tbody>
  <?php foreach ($steps as $s): $file = $files[$s['id']] ?? null; $m = $file['manifest'] ?? []; ?>
    <tr id="step-<?= e($s['id']) ?>">
      <td><strong><?= e($s['title']) ?></strong> <small class="muted"><?= e($s['id']) ?></small><?php if (!empty($s['hotfix'])): ?> <em class="tag is-hotfix"><?= e(t('Hotfix', 'Correctif')) ?></em><?php endif; ?><?php if (!empty($s['server'])): ?> <em class="tag"><?= e(t('Your server', 'Votre serveur')) ?></em><?php endif; ?>
        <?php if ($s['sub'] !== ''): ?><br><small class="muted"><?= e($s['sub']) ?></small><?php endif; ?></td>
      <td><?= $s['date'] ? e(date(t('M j, Y', 'd/m/Y'), strtotime((string)$s['date']))) : '—' ?></td>
      <td><?php if ($file): $tables = (array)($m['tables'] ?? []); ?>
        <?= e(sprintf(t('%s tables, %s records, %s removed', '%s tables, %s enregistrements, %s retirés'), number(count($tables)), number(array_sum(array_column($tables, 'rows'))), number(array_sum(array_column($tables, 'removed'))))) ?>
        <br><small class="muted"><?= e(sprintf(t('Made %s · %s · for build %s', 'Créé le %s · %s · pour le build %s'), date(t('M j, H:i', 'd/m H:i'), $file['made']), checkout_size($file['size']), (string)($m['server_build'] ?? '?'))) ?><?= ($m['carry'] ?? true) === false ? ' · ' . e(t('without records that exist by hotfix alone', 'sans les enregistrements qui n’existent que par correctif')) : '' ?></small>
        <?php if (!empty($m['skipped'])): ?><details class="small"><summary><?= e(sprintf(t('%s table(s) left out', '%s table(s) écartée(s)'), number(count($m['skipped'])))) ?></summary><ul><?php foreach ($m['skipped'] as $name => $why): ?><li><strong><?= e($name) ?></strong>: <?= e($why) ?></li><?php endforeach; ?></ul></details><?php endif; ?>
      <?php else: ?><span class="muted"><?= e(t('Not made yet', 'Pas encore créé')) ?></span><?php endif; ?></td>
      <td class="num"><?php if ($file): ?><a class="btn is-small" href="<?= e(url('admin/checkout', ['download' => $s['id']])) ?>"><i class="fas fa-download"></i> .sql</a> <?php endif; ?>
        <button class="btn is-small" type="button" data-checkout-start="<?= e($s['id']) ?>" <?= $status['running'] ? 'disabled' : '' ?>><i class="fas fa-<?= $file ? 'rotate' : 'play' ?>"></i> <?= e($file ? t('Again', 'Refaire') : t('Make', 'Créer')) ?></button></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
<?php page_end();
