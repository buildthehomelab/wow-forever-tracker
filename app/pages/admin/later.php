<?php
// Later (administrators): the work list of what the content still to come needs (app/gather.php, docs/GATHER.md). Per
// release phase, and for the open one: each quest with who gives and takes it and what it asks, the creatures and
// objects the server lacks, the items with where they come from, and which source already holds each. ?format=json
// gives the list as the analysis wrote it (data/gather.json), for a world-data branch the day a phase opens.
require_once FT_APP . '/gather.php';
$list = gather_list();
if (($_GET['format'] ?? '') === 'json') json_out($list ?: ['phases' => []]);
$phasesByKey = [];
foreach ((array)($list['phases'] ?? []) as $p) if (is_array($p) && isset($p['key'])) $phasesByKey[(string)$p['key']] = $p;
$key = (string)($_GET['phase'] ?? '');
if (!isset($phasesByKey[$key])) {
    // the first phase with something to gather, else the first
    $key = '';
    foreach ($phasesByKey as $k => $p) if (array_sum(array_map(fn($c) => (int)($c['all'] ?? 0), (array)($p['counts'] ?? []))) > 0 && $k !== 'not-out') { $key = $k; break; }
    $key = $key !== '' ? $key : (string)array_key_first($phasesByKey);
}
$phase = $phasesByKey[$key] ?? null;
$kind = in_array($_GET['kind'] ?? '', ['quests', 'npcs', 'objects', 'items'], true) ? $_GET['kind'] : 'quests';
$open = in_array($_GET['show'] ?? '', ['todo', 'ready'], true) ? $_GET['show'] : '';
$rows = (array)($phase[$kind] ?? []);
if ($open) $rows = array_values(array_filter($rows, fn($r) => !empty($r['ready']) === ($open === 'ready')));
$limit = 500;
$branch = (string)config('wowhead', 'branch', 'forever');
$wh = fn(string $type, int $id) => '<a href="https://www.wowhead.com/' . e($branch) . '/' . e($type) . '=' . $id . '" target="_blank" rel="noopener">' . e($type) . ' ' . $id . '</a>';
$state = fn(string $s, string $ok, string $none) => $s === 'ok' ? '<span class="tag is-ok">' . e($ok) . '</span>' : ($s === 'missing' ? '<span class="tag is-plain">' . e(t('none', 'aucune')) . '</span>' : '<span class="muted">' . e($none) . '</span>');
$refs = function (array $map) use ($wh): string {
    $out = [];
    foreach ($map as $ref => $sources) {
        [$type, $id] = array_pad(explode(':', (string)$ref, 2), 2, '0');
        $type = $type === 'object' ? 'object' : ($type === 'item' ? 'item' : 'npc');
        $out[] = $wh($type, (int)$id) . ' <small class="muted">' . e(implode(', ', (array)$sources)) . '</small>';
    }
    return $out ? implode('<br>', $out) : '<span class="tag is-missing">' . e(t('no source', 'aucune source')) . '</span>';
};
$kindLabels = ['quests' => t('Quests', 'Quêtes'), 'npcs' => t('Creatures', 'Créatures'), 'objects' => t('Objects', 'Objets du monde'), 'items' => t('Items', 'Objets')];
$countKey = ['quests' => 'quest', 'npcs' => 'npc', 'objects' => 'object', 'items' => 'item'];
$query = fn(array $more) => url('admin/later', array_filter(array_merge(['phase' => $key, 'kind' => $kind, 'show' => $open], $more), fn($v) => $v !== ''));
page_start(t('Later', 'À venir'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-hourglass-half"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Gathered before it opens', 'Rassemblé avant l’ouverture')) ?></h1>
    <p><?= e(t('What each release phase not open yet needs, and the quests the server has no record of today: who gives and takes each quest and what it asks, the creatures and objects the server lacks with a template and a place, the items with where they come from. The analysis writes this list; the Wowhead crawl reads the pages it names (today’s first, then the later phases’), and Import Icy Veins asks its answers before the rest of its mirror. Rows are written when a phase opens; nothing is guessed.', 'Ce dont chaque phase pas encore ouverte a besoin, et les quêtes dont le serveur n’a aucune trace : qui donne et reprend chaque quête et ce qu’elle demande, les créatures et objets du monde qui manquent au serveur avec un modèle et un lieu, les objets avec leur provenance. L’analyse écrit cette liste ; le parcours Wowhead lit les pages qu’elle nomme (celles d’aujourd’hui d’abord, puis celles des phases à venir), et l’import Icy Veins demande ses réponses avant le reste de son miroir. Les lignes sont écrites quand une phase ouvre ; rien n’est deviné.')) ?></p>
    <p class="muted small"><?= $list ? e(sprintf(t('Made by the analysis of %s. Sources: %s. ', 'Faite par l’analyse du %s. Sources : %s. '), date('M j, Y H:i', (int)($list['made'] ?? 0)),
        implode(', ', array_map(fn($k, $v) => $k . ' ' . (is_string($v) ? substr($v, 0, 8) : number((int)$v)), array_keys((array)($list['sources'] ?? [])), array_values((array)($list['sources'] ?? [])))))) : '' ?><a class="link" href="<?= e(url('admin/later', ['format' => 'json'])) ?>">?format=json</a></p></div></div>
</section>
<?php if (!$phasesByKey): ?>
<div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No work list yet: the next analysis writes it (The Forge › Run again).', 'Pas encore de liste : la prochaine analyse l’écrit (La Forge › Relancer).')) ?></p></div>
<?php else: ?>
<nav class="tabs">
  <?php foreach ($phasesByKey as $k => $p): $n = array_sum(array_map(fn($c) => (int)($c['all'] ?? 0), (array)($p['counts'] ?? []))); ?>
  <a class="<?= $k === $key ? 'is-active' : '' ?>" href="<?= e(url('admin/later', ['phase' => $k])) ?>" title="<?= e(!empty($p['opens']) ? (string)$p['opens'] : '') ?>"><?= e((string)$p['name']) ?><em><?= number($n) ?></em></a>
  <?php endforeach; ?>
</nav>
<div class="stat-tiles is-compact">
  <?php foreach ($kindLabels as $k => $label): $c = (array)(($phase['counts'] ?? [])[$countKey[$k]] ?? []); ?>
  <a class="stat-tile <?= $k === $kind ? 'is-ok' : '' ?>" href="<?= e($query(['kind' => $k, 'show' => ''])) ?>"><strong><?= number((int)($c['ready'] ?? 0)) ?> / <?= number((int)($c['all'] ?? 0)) ?></strong><span><?= e($label) ?> · <?= e(t('ready', 'prêts')) ?></span></a>
  <?php endforeach; ?>
</div>
<nav class="tabs">
  <a class="<?= $open === '' ? 'is-active' : '' ?>" href="<?= e($query(['show' => ''])) ?>"><?= e(t('All', 'Tout')) ?></a>
  <a class="<?= $open === 'todo' ? 'is-active' : '' ?>" href="<?= e($query(['show' => 'todo'])) ?>"><?= e(t('Still missing data', 'Données encore manquantes')) ?></a>
  <a class="<?= $open === 'ready' ? 'is-active' : '' ?>" href="<?= e($query(['show' => 'ready'])) ?>"><?= e(t('Ready to build', 'Prêts à construire')) ?></a>
</nav>
<?php if (!$rows): ?>
<div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-check"></i></div><p><?= e(t('Nothing here.', 'Rien ici.')) ?></p></div>
<?php else: ?>
<div class="table-card">
<table class="table is-forge">
<?php if ($kind === 'quests'): ?>
  <thead><tr><th><?= e(t('Quest', 'Quête')) ?></th><th><?= e(t('Record', 'Fiche')) ?></th><th><?= e(t('Given by', 'Donnée par')) ?></th><th><?= e(t('Taken by', 'Rendue à')) ?></th><th><?= e(t('Asks for', 'Demande')) ?></th><th>Wowhead · Icy Veins</th></tr></thead>
  <tbody><?php foreach (array_slice($rows, 0, $limit) as $r): ?>
    <tr><td class="res"><div><strong><a href="<?= e(entry_url('quest', (int)$r['id'])) ?>"><?= e((string)($r['name'] ?: 'quest ' . $r['id'])) ?></a></strong><small><?= $wh('quest', (int)$r['id']) ?> · <?= e((string)$r['status']) ?><?= !empty($r['ready']) ? ' · <b class="is-ok">' . e(t('ready', 'prête')) . '</b>' : '' ?></small></div></td>
      <td><?= !empty($r['server']) ? '<span class="tag is-ok">' . e(t('server', 'serveur')) . '</span>' : ($r['record'] ? '<span class="tag is-plain">' . e((string)$r['record']) . '</span>' : '<span class="tag is-missing">' . e(t('none', 'aucune')) . '</span>') ?></td>
      <td><?= $refs((array)($r['gives'] ?? [])) ?></td><td><?= $refs((array)($r['takes'] ?? [])) ?></td>
      <td><?= implode('<br>', array_map(function ($ref) use ($wh) { [$t, $i] = explode(':', (string)$ref, 2); return $wh($t, (int)$i); }, (array)($r['objectives'] ?? []))) ?: '<span class="muted">—</span>' ?></td>
      <td><?= $state((string)($r['wowhead'] ?? ''), t('page read', 'page lue'), t('not read yet', 'pas encore lue')) ?> <?= $state((string)($r['icyveins'] ?? ''), 'Icy Veins', '') ?></td></tr>
  <?php endforeach; ?></tbody>
<?php elseif ($kind === 'items'): ?>
  <thead><tr><th><?= e(t('Item', 'Objet')) ?></th><th><?= e(t('Needed for', 'Pour')) ?></th><th>Icy Veins</th><th><?= e(t('Wowhead page', 'Page Wowhead')) ?></th></tr></thead>
  <tbody><?php foreach (array_slice($rows, 0, $limit) as $r): ?>
    <tr><td class="res"><div><strong><a href="<?= e(entry_url('item', (int)$r['id'])) ?>"><?= e((string)($r['name'] ?: 'item ' . $r['id'])) ?></a></strong><small><?= $wh('item', (int)$r['id']) ?><?= $r['status'] ? ' · ' . e((string)$r['status']) : '' ?><?= !empty($r['ready']) ? ' · <b class="is-ok">' . e(t('has a source', 'a une source')) . '</b>' : '' ?></small></div></td>
      <td><?= e(implode(', ', (array)($r['for'] ?? []))) ?: '<span class="muted">—</span>' ?></td>
      <td><?= ($r['icyveins'] ?? '') === 'ok' ? e(sprintf(t('dropped by %d · sold by %d', 'butin de %d · vendu par %d'), (int)$r['icy_dropped_by'], (int)$r['icy_sold_by'])) : $state((string)($r['icyveins'] ?? ''), '', t('not asked yet', 'pas encore demandé')) ?></td>
      <td><?= ($r['wowhead'] ?? '') === 'ok' ? (implode(', ', array_map('e', (array)($r['tabs'] ?? []))) ?: '<span class="muted">' . e(t('names no source', 'ne nomme aucune source')) . '</span>') : $state((string)($r['wowhead'] ?? ''), '', t('not read yet', 'pas encore lue')) ?></td></tr>
  <?php endforeach; ?></tbody>
<?php else: $type = $kind === 'npcs' ? 'npc' : 'object'; ?>
  <thead><tr><th><?= e($kind === 'npcs' ? t('Creature', 'Créature') : t('Object', 'Objet du monde')) ?></th><th><?= e(t('Needed for', 'Pour')) ?></th><th><?= e(t('Server', 'Serveur')) ?></th><th><?= e(t('Template', 'Modèle')) ?></th><th><?= e(t('Place', 'Lieu')) ?></th><th><?= e(t('Wowhead page', 'Page Wowhead')) ?></th></tr></thead>
  <tbody><?php foreach (array_slice($rows, 0, $limit) as $r): ?>
    <tr><td class="res"><div><strong><?= $wh($type, (int)$r['id']) ?></strong><small><?= !empty($r['ready']) ? '<b class="is-ok">' . e(t('ready', 'prêt')) . '</b>' : e(t('data missing', 'données manquantes')) ?><?= !empty($r['zones']) ? ' · ' . e(t('zones', 'zones') . ' ' . implode(', ', (array)$r['zones'])) : '' ?></small></div></td>
      <td><?= e(implode(', ', (array)($r['for'] ?? []))) ?><?= (int)($r['needed_by'] ?? 0) > count((array)($r['for'] ?? [])) ? ' <small class="muted">+' . ((int)$r['needed_by'] - count((array)$r['for'])) . '</small>' : '' ?></td>
      <td><?= !empty($r['template']) ? e(t('template', 'modèle')) . (!empty($r['spawned']) ? ', ' . e(t('spawned', 'placé')) : ', <b class="is-missing">' . e(t('not spawned', 'non placé')) . '</b>') : '<span class="tag is-missing">' . e(t('no template', 'pas de modèle')) . '</span>' ?></td>
      <td><?= implode(' ', array_filter([!empty($r['eglink']) ? '<span class="tag is-plain">EG Link</span>' : '', ($r['icyveins'] ?? '') === 'ok' ? '<span class="tag is-plain">Icy Veins</span>' : ''])) ?: '<span class="muted">—</span>' ?></td>
      <td><?= implode(', ', array_filter([(int)($r['eglink_seen'] ?? 0) ? e(sprintf(t('EG Link %d', 'EG Link %d'), (int)$r['eglink_seen'])) : '', (int)($r['icy_points'] ?? 0) ? e(sprintf('Icy Veins %d', (int)$r['icy_points'])) : '', (int)($r['pins'] ?? 0) ? e(sprintf(t('Wowhead %d pins', 'Wowhead %d repères'), (int)$r['pins'])) : ''])) ?: '<span class="muted">—</span>' ?></td>
      <td><?= $state((string)($r['wowhead'] ?? ''), t('read', 'lue') . (!empty($r['model']) ? ' · ' . t('model', 'modèle') : ''), t('not read yet', 'pas encore lue')) ?></td></tr>
  <?php endforeach; ?></tbody>
<?php endif; ?>
</table>
</div>
<?php if (count($rows) > $limit): ?><p class="muted small"><?= e(sprintf(t('The first %d of %d shown; ?format=json has them all.', 'Les %d premiers sur %d ; ?format=json les donne tous.'), $limit, count($rows))) ?></p><?php endif; ?>
<?php endif; ?>
<?php endif; ?>
<?php page_end();
