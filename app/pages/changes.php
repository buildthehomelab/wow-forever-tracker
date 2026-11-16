<?php
// Changelog of an official build: every resource added, changed or removed, with Blizzard's notes.
$builds = builds();
$withChanges = array_map('intval', array_column(rows('SELECT DISTINCT build FROM ft_changes' . (hotfix_entries() ? ' WHERE hotfix = 0' : '') . ' ORDER BY build DESC'), 'build'));
$build = (int)($_GET['build'] ?? ($withChanges[0] ?? 0));
// a hotfix update of the build (1, 2, ...): what one day's hotfix cache changed against the one before (docs/CLIENT.md)
$hotfix = hotfix_entries() ? max(0, (int)($_GET['hotfix'] ?? 0)) : 0;
$updates = hotfix_updates();
$update = null;
foreach ($updates as $u) if ((int)$u['build'] === $build && (int)$u['hotfix'] === $hotfix) $update = $u;
if (!$update) $hotfix = 0;
$hotfixWithChanges = hotfix_entries() ? array_map(fn($x) => $x['build'] . ':' . $x['hotfix'], rows('SELECT DISTINCT build, hotfix FROM ft_changes WHERE hotfix > 0')) : [];
$filterType = isset(TYPES[$_GET['type'] ?? '']) ? $_GET['type'] : '';
$kind = in_array($_GET['kind'] ?? '', ['added', 'modified', 'removed'], true) ? $_GET['kind'] : '';
$showInternal = !empty($_GET['internal']);
$current = null;
foreach ($builds as $b) if ((int)$b['build'] === $build) $current = $b;

// a removed resource has no line of its own any more: the change itself says whether it was a test or an unused one
$visible = $showInternal ? '' : " AND (e.internal = 0 OR (e.internal IS NULL AND c.kind = 'removed'" . changes_shown('c.') . '))';
$summary = [];
foreach (rows("SELECT c.type, c.kind, COUNT(*) n FROM ft_changes c LEFT JOIN ft_entities e ON e.type = c.type AND e.id = c.id WHERE c.build = ?" . hotfix_is($hotfix, 'c.') . "$visible GROUP BY c.type, c.kind", [$build]) as $x)
    $summary[$x['type']][$x['kind']] = (int)$x['n'];
$order = ['dungeon', 'boss', 'zone', 'quest', 'mount', 'pet', 'toy', 'talent', 'spell', 'recipe', 'item', 'achievement', 'taxi'];
uksort($summary, fn($a, $b) => array_search($a, $order, true) <=> array_search($b, $order, true));
// A kind's changes are read on their own, a page at a time: the first build against the original game is tens of
// thousands of lines, and one list cut at a fixed length would never reach the kinds that come last.
$perPage = 500; $limit = $filterType !== '' ? $perPage : 40;
$counted = fn(string $ty) => $kind !== '' ? ($summary[$ty][$kind] ?? 0) : array_sum($summary[$ty] ?? []);
$pages = $filterType !== '' ? max(1, (int)ceil($counted($filterType) / $perPage)) : 1;
$page = max(1, min($pages, (int)($_GET['p'] ?? 1)));   // never past the last page: the offset stays a small whole number
$grouped = [];
foreach (array_keys($summary) as $ty) {
    if (($filterType !== '' && $ty !== $filterType) || !$counted($ty)) continue;
    $where = 'c.build = ? AND c.type = ?' . hotfix_is($hotfix, 'c.') . $visible; $params = [$build, $ty];
    if ($kind !== '') { $where .= ' AND c.kind = ?'; $params[] = $kind; }
    $grouped[$ty] = rows("SELECT c.*, e.name_en, e.icon, e.quality, e.status, e.score, e.is_new, e.data" . phase_column('e.') . " FROM ft_changes c LEFT JOIN ft_entities e ON e.type = c.type AND e.id = c.id
        WHERE $where ORDER BY FIELD(c.kind,'added','modified','removed'), c.name, c.id LIMIT $limit OFFSET " . ($filterType !== '' ? ($page - 1) * $perPage : 0), $params);
}
$vanillaStep = !$hotfix && from_vanilla($build);       // this build is compared with the original game
$vanillaBuild = !$hotfix && $current && build_is_vanilla($current);
$replay = meta()['replay'] ?? [];
$note = $hotfix || !table_exists('ft_notes') ? null : row('SELECT * FROM ft_notes WHERE build = ?', [$build]);
// resources that exist by hotfix alone (in no build's tables): the analysis does not call them "added" (docs/CLIENT.md)
$byHotfix = !$hotfix && $withChanges && $build === $withChanges[0] ? array_sum(array_map('intval', (array)(meta()['hotfix_only'] ?? []))) : 0;
if (($_GET['format'] ?? '') === 'csv' && $build) {
    // every line the filters show, not only the page: the first build against the original game is too long to read here
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="changes-' . $build . ($hotfix ? '-hotfix-' . $hotfix : '') . '.csv"');
    $out = fopen('php://output', 'w');
    fwrite($out, "\xEF\xBB\xBF");
    // a spreadsheet takes a cell that starts with = + - or @ for a formula: such a text is written as text
    $csv_safe = fn(string $text) => $text !== '' && strpbrk($text[0], "=+-@\t\r") !== false && !is_numeric($text) ? "'" . $text : $text;
    fputcsv($out, ['type', 'id', 'name', 'change', 'field', 'before', 'after'], ';', '"', '');
    $flat = fn($v) => is_array($v) ? json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : (string)$v;
    $where = 'c.build = ?' . hotfix_is($hotfix, 'c.') . $visible; $params = [$build];
    if ($filterType !== '') { $where .= ' AND c.type = ?'; $params[] = $filterType; }
    if ($kind !== '') { $where .= ' AND c.kind = ?'; $params[] = $kind; }
    for ($after = 0; ; ) {
        $chunk = rows("SELECT c.seq, c.type, c.id, c.name, c.kind, c.fields FROM ft_changes c LEFT JOIN ft_entities e ON e.type = c.type AND e.id = c.id WHERE $where AND c.seq > ? ORDER BY c.seq LIMIT 2000", array_merge($params, [$after]));
        if (!$chunk) break;
        foreach ($chunk as $x) {
            $after = (int)$x['seq'];
            $fields = json_decode((string)$x['fields'], true) ?: [];
            if (!$fields) fputcsv($out, [$x['type'], $x['id'], $csv_safe((string)$x['name']), $x['kind'], '', '', ''], ';', '"', '');
            foreach ($fields as $field => $pair) fputcsv($out, [$x['type'], $x['id'], $csv_safe((string)$x['name']), $x['kind'], $field, $csv_safe($flat($pair[0] ?? '')), $csv_safe($flat($pair[1] ?? ''))], ';', '"', '');
        }
    }
    exit;
}
$fieldLabels = ['name' => t('name', 'nom'), 'quality' => t('quality', 'qualité'), 'ilvl' => t('item level', 'niveau d’objet'), 'req' => t('required level', 'niveau requis'),
    'stats' => t('stats', 'caractéristiques'), 'sell' => t('sell price', 'prix de vente'), 'buy' => t('buy price', 'prix d’achat'), 'desc' => 'description',
    'effects' => t('effects', 'effets'), 'aura' => 'aura', 'level' => t('level', 'niveau'), 'ranks' => t('ranks', 'rangs'), 'points' => 'points', 'reward' => t('reward', 'récompense'), 'source' => 'source',
    'classes' => t('classes', 'classes'), 'bonding' => t('binding', 'liaison'), 'set' => t('set', 'ensemble'), 'skill' => t('skill required', 'compétence requise'), 'slot' => t('slot', 'emplacement'),
    'rank' => t('rank', 'rang'), 'trivial' => t('skill-up range', 'plage de progression'), 'players' => t('players', 'joueurs'), 'acquire' => t('how it is learned', 'mode d’apprentissage')];
/** A stat list of the step from the original game ([["strength", 18], ...]) as "+18 strength, +5 stamina". */
$shown = function ($value) {
    if (is_array($value) && $value !== [] && array_keys($value) === range(0, count($value) - 1) && count(array_filter($value, fn($x) => is_array($x) && count($x) === 2 && is_string($x[0] ?? null) && is_int($x[1] ?? null))) === count($value))
        return implode(', ', array_map(fn($x) => sprintf('%+d %s', $x[1], $x[0]), $value));
    return $value === [] ? '' : $value;
};

/** Small Markdown subset for the official notes: headings, lists, bold, links, paragraphs. */
function markdown(string $text): string
{
    $html = ''; $list = false;
    foreach (preg_split('/\R/', $text) as $line) {
        $line = rtrim($line);
        $inline = preg_replace(['/\*\*(.+?)\*\*/', '/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/'], ['<strong>$1</strong>', '<a href="$2" target="_blank" rel="noopener">$1</a>'], e($line));
        if (preg_match('/^\s*[-*]\s+(.*)$/', $line)) { if (!$list) { $html .= '<ul>'; $list = true; } $html .= '<li>' . preg_replace('/^\s*[-*]\s+/', '', $inline) . '</li>'; continue; }
        if ($list) { $html .= '</ul>'; $list = false; }
        if ($line === '') continue;
        if (preg_match('/^(#{2,3})\s+/', $line, $m)) { $html .= '<h' . strlen($m[1]) . '>' . preg_replace('/^#{2,3}\s+/', '', $inline) . '</h' . strlen($m[1]) . '>'; continue; }
        $html .= '<p>' . $inline . '</p>';
    }
    return $html . ($list ? '</ul>' : '');
}
$query = fn(array $change) => '?' . http_build_query(array_filter(array_merge(['build' => $build, 'hotfix' => $hotfix ?: '', 'type' => $filterType, 'kind' => $kind, 'internal' => $showInternal ? 1 : ''], $change), fn($v) => $v !== '' && $v !== null));
$hidden = array_sum(array_map('intval', (array)(baseline()['hidden'] ?? [])));
$totals = ['added' => 0, 'modified' => 0, 'removed' => 0];
foreach ($summary as $counts) foreach ($counts as $k => $n) $totals[$k] += $n;

page_start(t('Changelog', 'Changelog') . ($current ? ' ' . $current['version'] : '') . ($update ? ' · ' . hotfix_name($update) : ''), 'changes', t('What changed in each official WoW Forever build.', 'Ce qui a changé dans chaque build officiel de WoW Forever.'));
?>
<section class="page-head">
  <div class="page-title">
    <span class="page-icon"><i class="fas fa-code-compare"></i></span>
    <div><span class="eyebrow"><?= e(t('Official changelog', 'Changelog officiel')) ?></span><h1><?= e($update ? hotfix_name($update) . ' · ' . t('build', 'build') : ($vanillaBuild ? t('The original game', 'Le jeu d’origine') : t('Build', 'Build'))) ?> <?= e($current['version'] ?? '—') ?></h1>
    <p><?= e($update
        ? sprintf(t('What Blizzard’s hotfixes changed in build %s, compared with the hotfixes the tracker had read before (%s records in the cache that day). Hover a name for its tooltip.', 'Ce que les correctifs de Blizzard ont changé dans le build %s, par rapport aux correctifs que le tracker avait lus avant (%s enregistrements dans le cache ce jour-là). Survolez un nom pour son infobulle.'), $current['version'] ?? $build, number((int)preg_replace('/\D.*/', '', (string)$update['note'])))
        : ($vanillaBuild
        ? t('Where the changelog starts. The first build of WoW: Forever is compared with it, and every build after that with the one before.', 'Le début du changelog. Le premier build de WoW: Forever lui est comparé, et chaque build suivant au précédent.')
        : ($vanillaStep
        ? t('The first build of WoW: Forever, compared with the original game (patch 1.12): what it added, what it changed, and what the original game had that it does not have. Hover a name for its tooltip.', 'Le premier build de WoW: Forever, comparé au jeu d’origine (patch 1.12) : ce qu’il a ajouté, ce qu’il a modifié, et ce que le jeu d’origine avait et qu’il n’a pas. Survolez un nom pour son infobulle.')
        : t('Every resource added, changed or removed in the client files of this build, compared with the previous tracked build. Hover a name for its tooltip.', 'Chaque ressource ajoutée, modifiée ou supprimée dans les fichiers du client de ce build, par rapport au build suivi précédent. Survolez un nom pour son infobulle.')))) ?></p></div>
    <?php if ($byHotfix): ?><p class="muted small"><?= e(sprintf(t('%s resources exist by hotfix alone: they are in no build’s files, so nothing says when they appeared, and they are not listed as added here.', '%s ressources n’existent que par correctif : elles ne sont dans les fichiers d’aucun build, rien ne dit donc quand elles sont apparues, et elles ne figurent pas ici comme ajoutées.'), number($byHotfix))) ?></p><?php endif; ?>
  </div>
  <?php if (!$vanillaBuild): ?><div class="stat-tiles is-compact">
    <span class="stat-tile is-ok"><strong>+<?= number($totals['added']) ?></strong><span><?= e(kind_label('added')) ?></span></span>
    <span class="stat-tile is-partial"><strong>~<?= number($totals['modified']) ?></strong><span><?= e(kind_label('modified')) ?></span></span>
    <span class="stat-tile is-missing"><strong>−<?= number($totals['removed']) ?></strong><span><?= e(change_label('removed', $hotfix ? 0 : $build)) ?></span></span>
  </div><?php endif; ?>
</section>

<div class="build-switch">
  <?php foreach ($builds as $b): $has = in_array((int)$b['build'], $withChanges, true); ?>
    <?php foreach ($updates as $u): if ((int)$u['build'] !== (int)$b['build']) continue; ?>
    <a class="<?= (int)$u['build'] === $build && (int)$u['hotfix'] === $hotfix ? 'is-active' : '' ?> <?= in_array($u['build'] . ':' . $u['hotfix'], $hotfixWithChanges, true) ? '' : 'is-quiet' ?>" href="?build=<?= (int)$u['build'] ?>&amp;hotfix=<?= (int)$u['hotfix'] ?>"><strong><?= e(hotfix_name($u)) ?></strong><small><?= e(t('hotfixes', 'correctifs')) ?> · <?= (int)$u['build'] ?></small></a>
    <?php endforeach; ?>
    <a class="<?= (int)$b['build'] === $build && !$hotfix ? 'is-active' : '' ?> <?= $has ? '' : 'is-quiet' ?>" href="?build=<?= (int)$b['build'] ?>"><strong><?= e($b['version']) ?></strong><small><?= $b['released'] ? e(date(t('M j', 'd/m'), strtotime($b['released']))) : '' ?><?= (int)$b['is_server'] ? ' · ' . e(t('server', 'serveur')) : '' ?><?= build_is_beta($b) ? ' · ' . e(t('beta', 'bêta')) : '' ?><?= build_is_vanilla($b) ? ' · vanilla 1.12' : '' ?></small></a>
  <?php endforeach; ?>
</div>

<?php if (!$hotfix && $current && $current['note']): ?><div class="alert is-info"><i class="fas fa-circle-info"></i><div><?= e($current['note']) ?></div></div><?php endif; ?>
<?php if ($vanillaStep): ?><div class="alert is-info"><i class="fas fa-circle-info"></i><div>
  <strong><?= e(t('How to read this page', 'Comment lire cette page')) ?></strong>
  <?= e(sprintf(t('It compares this build with the original game as Blizzard published it again in 2019 (%s). "Not in Forever" is what the original game had and WoW: Forever’s data does not: content Blizzard took out, and content that is not released yet (the later raids’ loot is not in the client or its hotfixes).', 'Elle compare ce build au jeu d’origine tel que Blizzard l’a republié en 2019 (%s). « Absent de Forever » : ce que le jeu d’origine avait et que les données de WoW: Forever n’ont pas, soit du contenu retiré par Blizzard, soit du contenu pas encore sorti (le butin des raids ultérieurs n’est ni dans le client ni dans ses correctifs).'), (string)baseline()['version'])) ?>
  <?php if ($hidden): ?><?= e(sprintf(t('%s records of this build are still encrypted: an original resource among them also reads as absent until its key is out.', '%s enregistrements de ce build sont encore chiffrés : une ressource d’origine parmi eux apparaît aussi comme absente tant que sa clé n’est pas publiée.'), number($hidden))) ?><?php endif; ?>
  <?php if (!empty(baseline()['alone'])): ?><?= e(sprintf(t('%s original resources are in no table of WoW: Forever and reach the client by hotfix: they are compared as their hotfix stands today.', '%s ressources d’origine ne sont dans aucune table de WoW: Forever et arrivent au client par correctif : elles sont comparées telles que leur correctif les donne aujourd’hui.'), number((int)baseline()['alone']))) ?><?php endif; ?>
  <?= e(t('An item’s stats are compared as amounts, a spell’s effects as the middle of the range the original game rolled.', 'Les caractéristiques d’un objet sont comparées en valeurs, les effets d’un sort au milieu de la plage que tirait le jeu d’origine.')) ?>
</div></div><?php endif; ?>

<?php if ($note): ?>
<section class="block notes">
  <header class="block-head"><div><span class="eyebrow">Blizzard</span><h2><?= e($note['title'] ?: t('Official patch notes', 'Notes de mise à jour officielles')) ?></h2></div><?php if ($note['url']): ?><a class="link" href="<?= e($note['url']) ?>" target="_blank" rel="noopener"><?= e(t('Source', 'Source')) ?> ↗</a><?php endif; ?></header>
  <div class="prose"><?= markdown((string)$note['body']) ?></div>
</section>
<?php elseif (is_admin() && $build && !$hotfix): ?>
<p class="muted"><a href="<?= e(url('admin/notes', ['build' => $build])) ?>"><i class="fas fa-pen-to-square"></i> <?= e(t('Add Blizzard’s patch notes for this build', 'Ajouter les notes de mise à jour de Blizzard pour ce build')) ?></a></p>
<?php endif; ?>
<?php
// What was written about this step (tools/ft/notes.py): Blizzard's own posts first, ForeverChanges where Blizzard posted
// none. A line naming something this step changed in the client's data is marked so; any other line tells of a change
// made on the servers alone, which no client file shows.
$written = timeline_notes();
$noteDays = $update ? hotfix_days($update) : [];
$buildNote = !$hotfix && $build ? ($written['builds'][$build] ?? null) : null;
$buildDay = !$hotfix && $current ? (string)$current['released'] : '';
$dayPosts = function (string $day) use ($written) {
    return array_values(array_filter(array_map(fn($id) => $written['posts'][$id] ?? null, $written['days'][$day]['posts'] ?? []),
        fn($p) => $p && empty($p['hotfixes'])));
};
$buildArticles = $buildDay !== '' ? ($written['days'][$buildDay]['iv'] ?? []) : [];
$ivLines = (bool)array_filter($buildArticles, fn($a) => $a['sections']);   // Icy Veins comes before ForeverChanges
$changedNames = [];
if ($noteDays || $buildNote || $buildArticles) {
    foreach (rows('SELECT DISTINCT c.name FROM ft_changes c WHERE c.build = ?' . hotfix_is($hotfix, 'c.'), [$build]) as $x) {
        $n = mb_strtolower(trim((string)$x['name']));
        if (mb_strlen($n) >= 5) $changedNames[$n] = true;
    }
}
$inClient = function (string $line) use ($changedNames): bool {
    $low = mb_strtolower($line);
    foreach ($changedNames as $n => $_) if (str_contains($low, $n)) return true;
    return false;
};
$lineHtml = function (array $line) use ($inClient, $changedNames): string {
    $mark = (string)($line['mark'] ?? '');
    $tag = $changedNames ? ($inClient((string)$line['text'])
        ? '<em class="tag is-client" title="' . e(t('Something this step changed in the client’s data is named here', 'Ce que cette étape a changé dans les données du client est nommé ici')) . '">' . e(t('In the client data', 'Dans les données client')) . '</em>'
        : '<em class="tag is-server" title="' . e(t('Nothing in the client’s data changed for it here: a change made on the servers', 'Rien dans les données du client n’a changé pour cela ici : un changement fait sur les serveurs')) . '">' . e(t('Server side', 'Côté serveur')) . '</em>') : '';
    return '<li' . ($mark ? ' class="is-' . e($mark) . '"' : '') . '><span>' . e((string)$line['text']) . '</span>' . $tag . '</li>';
};
?>
<?php if ($noteDays): ?>
<section class="block day-notes">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('What was written', 'Ce qui a été écrit')) ?></span><h2><?= e(sprintf(t('%d hotfix days', '%d jours de correctifs'), count($noteDays))) ?></h2></div></header>
  <?php $w = hotfix_window($update); if (!empty($w['from'])): ?><p class="muted small"><?= e(sprintf(t('Dated from Blizzard’s builds: the changes below were in no client before %s and were baked into build %s. Blizzard’s cache does not say on which day each came: the days are those Blizzard’s notes name in that time.', 'Daté à partir des builds de Blizzard : les changements ci-dessous n’étaient dans aucun client avant le %s et ont été intégrés au build %s. Le cache de Blizzard ne dit pas quel jour chacun est arrivé : les jours sont ceux que nomment les notes de Blizzard dans cette période.'), date(t('M j', 'd/m'), strtotime((string)$w['from'])), $w['next'] ? (string)$w['next'] : t('none yet', 'aucun encore'))) ?></p><?php endif; ?>
  <?php foreach ($noteDays as $day): $entry = $written['days'][$day]; $from = day_source($day); $sections = day_sections($day); $posts = $dayPosts($day); ?>
  <article class="day-note">
    <h3><time datetime="<?= e($day) ?>"><?= e(date(t('l, F j', 'l j F'), strtotime($day))) ?></time>
      <?php if ($from === 'blizzard'): ?><span class="source is-blizzard">Blizzard</span><?php foreach ($entry['blizzard']['urls'] as $u): ?> <a class="link small" href="<?= e($u) ?>" target="_blank" rel="noopener"><?= e(t('post', 'message')) ?> ↗</a><?php endforeach; ?>
      <?php elseif ($from === 'iv'): ?><span class="source" title="<?= e(t('Blizzard’s notes as Icy Veins quoted them', 'Les notes de Blizzard telles qu’Icy Veins les cite')) ?>">Icy Veins</span>
      <?php elseif ($from === 'fc'): ?><span class="source" title="<?= e(t('Neither Blizzard nor Icy Veins wrote about this day: ForeverChanges fills the gap', 'Ni Blizzard ni Icy Veins n’ont écrit sur ce jour : ForeverChanges comble le manque')) ?>">ForeverChanges</span> <a class="link small" href="<?= e((string)$entry['fc']['url']) ?>" target="_blank" rel="noopener"><?= e(t('source', 'source')) ?> ↗</a><?php endif; ?>
      <?php foreach ($entry['iv'] as $article): if ($article['url'] === '') continue; ?> <a class="link small" href="<?= e($article['url']) ?>" target="_blank" rel="noopener" title="<?= e($article['title']) ?>">Icy Veins ↗</a><?php endforeach; ?></h3>
    <?php if ($from === 'fc' && !empty($entry['fc']['summary'])): ?><p class="muted"><?= e(implode(' ', (array)$entry['fc']['summary'])) ?></p><?php endif; ?>
    <?php foreach ($sections as $name => $lines): ?>
      <h4><?= e($name) ?></h4><ul class="note-lines"><?php foreach ($lines as $line) echo $lineHtml($line); ?></ul>
    <?php endforeach; ?>
    <?php foreach ($posts as $p): ?><p class="blue-post"><a href="<?= e((string)$p['url']) ?>" target="_blank" rel="noopener"><strong><?= e((string)$p['topic']) ?></strong></a> <small class="muted"><?= e((string)$p['author']) ?></small><br><span class="muted"><?= e((string)$p['excerpt']) ?></span></p><?php endforeach; ?>
  </article>
  <?php endforeach; ?>
</section>
<?php elseif (!$note && ($buildNote || $buildArticles || ($buildDay !== '' && $dayPosts($buildDay)))): ?>
<section class="block day-notes">
  <header class="block-head"><div><span class="eyebrow"><?= e($ivLines ? 'Icy Veins' : ($buildNote ? 'ForeverChanges' : 'Blizzard')) ?></span><h2><?= e(t('About this build', 'À propos de ce build')) ?></h2></div><?php if ($buildNote): ?><a class="link" href="<?= e((string)$buildNote['url']) ?>" target="_blank" rel="noopener"><?= e(t('Source', 'Source')) ?> ↗</a><?php endif; ?></header>
  <?php if ($buildNote): ?>
    <?php if (!empty($buildNote['summary'])): ?><p><?= e(implode(' ', (array)$buildNote['summary'])) ?></p><?php endif; ?>
    <?php foreach ($ivLines ? [] : (array)$buildNote['sections'] as $section): ?><h4><?= e((string)$section['name']) ?></h4><ul class="note-lines"><?php foreach ((array)$section['lines'] as $line) echo $lineHtml($line); ?></ul><?php endforeach; ?>
  <?php endif; ?>
  <?php foreach ($buildArticles as $article): ?>
    <h4><a href="<?= e($article['url']) ?>" target="_blank" rel="noopener">Icy Veins: <?= e($article['title']) ?> ↗</a></h4>
    <?php foreach ($article['sections'] as $name => $lines): ?><h4><?= e($name) ?></h4><ul class="note-lines"><?php foreach ($lines as $line) echo $lineHtml($line); ?></ul><?php endforeach; ?>
  <?php endforeach; ?>
  <?php foreach ($buildDay !== '' ? $dayPosts($buildDay) : [] as $p): ?><p class="blue-post"><a href="<?= e((string)$p['url']) ?>" target="_blank" rel="noopener"><strong><?= e((string)$p['topic']) ?></strong></a> <small class="muted"><?= e((string)$p['author']) ?></small><br><span class="muted"><?= e((string)$p['excerpt']) ?></span></p><?php endforeach; ?>
</section>
<?php endif; ?>
<?php if (is_admin() && $build && $current && !$vanillaBuild): $stepId = $build . ($hotfix ? '+' . $hotfix : ''); ?>
<p class="muted"><a href="<?= e(url('admin/checkout')) ?>#step-<?= e($stepId) ?>"><i class="fas fa-code-branch"></i> <?= e(t('Check out this step: its client data as a test realm’s hotfixes database', 'Extraire cette étape : ses données client comme base hotfixes d’un royaume de test')) ?></a></p>
<?php endif; ?>

<?php $firstHeld = !$hotfix && $builds && $build === (int)end($builds)['build'];
if ($firstHeld && !empty($replay['kinds'])): $allOk = !empty($replay['ok']); ?>
<section class="block">
  <header class="block-head"><div><span class="eyebrow"><?= e(t('Double check', 'Double vérification')) ?></span>
    <h2><?= e(sprintf($vanillaBuild ? t('From the original game to build %s', 'Du jeu d’origine au build %s') : t('From this build to build %s', 'De ce build au build %s'), (string)$replay['to'])) ?></h2></div>
    <span class="badge is-<?= $allOk ? 'ok' : 'missing' ?>"><i></i><?= e($allOk ? t('Adds up', 'Le compte est bon') : t('Does not add up', 'Le compte n’y est pas')) ?></span></header>
  <p class="muted"><?= e(sprintf(t('What is stored here, plus everything the %s builds after it are said to have added, minus everything they are said to have removed, must give the newest build. It is worked out again at every analysis, resource by resource; from the first build of WoW: Forever on, each resource’s content is followed too.', 'Ce qui est stocké ici, plus tout ce que les %s builds suivants sont dits avoir ajouté, moins tout ce qu’ils sont dits avoir supprimé, doit donner le build le plus récent. C’est recalculé à chaque analyse, ressource par ressource ; à partir du premier build de WoW: Forever, le contenu de chaque ressource est suivi aussi.'), number((int)$replay['steps']))) ?></p>
  <div class="table-card"><table class="table">
    <thead><tr><th><?= e(t('Kind', 'Type')) ?></th><th class="num"><?= e($vanillaBuild ? t('Original game', 'Jeu d’origine') : t('This build', 'Ce build')) ?></th><th class="num"><?= e(t('Added', 'Ajouté')) ?></th><th class="num"><?= e(t('By hotfix alone', 'Par correctif seul')) ?></th><th class="num"><?= e(t('Removed', 'Supprimé')) ?></th><th class="num"><?= e(t('Gives', 'Donne')) ?></th><th class="num"><?= e(sprintf(t('Build %s has', 'Le build %s a'), (string)$replay['to'])) ?></th><th></th></tr></thead>
    <tbody>
    <?php foreach ($order as $ty): if (!isset($replay['kinds'][$ty])) continue; $k = $replay['kinds'][$ty]; $same = (int)$k['end'] === (int)$k['now']; ?>
      <tr><td><i class="fas <?= TYPES[$ty][1] ?> muted"></i> <?= e(type_label($ty)) ?></td><td class="num"><?= number($k['start']) ?></td><td class="num">+<?= number($k['added']) ?></td><td class="num">+<?= number($k['alone']) ?></td><td class="num">−<?= number($k['removed']) ?></td>
        <td class="num"><?= number($k['end']) ?></td><td class="num"><?= number($k['now']) ?></td><td><span class="badge is-<?= $same ? 'ok' : 'missing' ?>"><i></i><?= e($same ? '=' : '≠') ?></span></td></tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
  <?php if (!$allOk): ?><div class="alert is-warn"><i class="fas fa-triangle-exclamation"></i><div><strong><?= e(sprintf(t('%s resources are not what the changes add up to', '%s ressources ne correspondent pas à la somme des changements'), number((int)($replay['wrong'] ?? 0)))) ?></strong><?php foreach ((array)($replay['problems'] ?? []) as $line): ?><div><?= e((string)$line) ?></div><?php endforeach; ?></div></div><?php endif; ?>
</section>
<?php endif; ?>
<?php if ($hotfix ? !in_array($build . ':' . $hotfix, $hotfixWithChanges, true) : !in_array($build, $withChanges, true)): ?>
  <div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-equals"></i></div><p><?= e($hotfix
      ? ($noteDays ? t('These hotfixes changed nothing in the client’s data: what Blizzard wrote above was changed on the servers.', 'Ces correctifs n’ont rien changé dans les données du client : ce que Blizzard a écrit ci-dessus a été changé sur les serveurs.') : t('These hotfixes changed nothing the tracker compares.', 'Ces correctifs n’ont rien changé de ce que le tracker compare.'))
      : ($vanillaBuild
      ? sprintf(t('The original game: the changelog starts here. The next build (%s) is compared with it.', 'Le jeu d’origine : le changelog commence ici. Le build suivant (%s) lui est comparé.'), (string)baseline()['first'])
      : ($firstHeld
      ? t('The first build the tracker holds: the changelog starts with the next one.', 'Le premier build que le tracker possède : le changelog commence au suivant.')
      : t('This build has the same game data as the previous one, byte for byte: Blizzard changed the program alone.', 'Ce build a les mêmes données de jeu que le précédent, octet pour octet : Blizzard n’a changé que le programme.')))) ?></p></div>
<?php else: ?>
<div class="chips">
  <a class="<?= $filterType === '' ? 'is-active' : '' ?>" href="<?= e($query(['type' => '', 'p' => ''])) ?>"><?= e(t('All', 'Tout')) ?></a>
  <?php foreach ($summary as $ty => $counts): ?>
    <a class="<?= $filterType === $ty ? 'is-active' : '' ?>" href="<?= e($query(['type' => $ty])) ?>"><i class="fas <?= TYPES[$ty][1] ?>"></i> <?= e(type_label($ty)) ?>
      <span><?php foreach (['added' => '+', 'modified' => '~', 'removed' => '−'] as $k => $sign) if (!empty($counts[$k])) echo '<b class="is-' . $k . '">' . $sign . number($counts[$k]) . '</b>'; ?></span></a>
  <?php endforeach; ?>
</div>
<div class="chips is-small">
  <?php foreach (['' => t('Every change', 'Tous les changements'), 'added' => kind_label('added'), 'modified' => kind_label('modified'), 'removed' => change_label('removed', $hotfix ? 0 : $build)] as $k => $label): ?><a class="<?= $kind === $k ? 'is-active' : '' ?>" href="<?= e($query(['kind' => $k, 'p' => ''])) ?>"><?= e($label) ?></a><?php endforeach; ?>
  <a class="<?= $showInternal ? 'is-active' : '' ?>" href="<?= e($query(['internal' => $showInternal ? '' : 1])) ?>"><i class="fas fa-flask"></i> <?= e(t('Internal / test', 'Interne / test')) ?></a>
  <a href="<?= e($query(['format' => 'csv'])) ?>" title="<?= e(t('Every line these filters show, as a file', 'Toutes les lignes que montrent ces filtres, en fichier')) ?>"><i class="fas fa-file-csv"></i> CSV</a>
</div>

<?php foreach ($grouped as $ty => $items): ?>
<section class="block">
  <header class="block-head"><div><h2><i class="fas <?= TYPES[$ty][1] ?> muted"></i> <?= e(type_label($ty)) ?> <small class="count"><?= number($counted($ty)) ?></small></h2></div>
  <?php if ($filterType === '' && $counted($ty) > $limit): ?><a class="link" href="<?= e($query(['type' => $ty])) ?>"><?= e(t('Show all', 'Tout afficher')) ?> →</a><?php endif; ?></header>
  <ul class="changes">
  <?php foreach (array_slice($items, 0, $limit) as $x): $fields = json_decode($x['fields'], true) ?: []; $wh = wowhead_url($ty, $x); ?>
    <li>
      <span class="kind is-<?= e($x['kind']) ?>"><?= e(change_label($x['kind'], $hotfix ? 0 : $build)) ?></span>
      <div class="res"><?= icon_html($x, $ty) ?><div><?= name_link($x, $ty) ?><?= $x['is_new'] ? ' <em class="tag is-new">' . e(t('New', 'Nouveau')) . '</em>' : '' ?><small>ID <?= (int)$x['id'] ?></small></div></div>
      <?php if ($fields): ?><span class="change-fields"><?php foreach (array_slice($fields, 0, 3, true) as $field => [$before, $after]): ?>
        <?php [$before, $after] = [$shown($before), $shown($after)]; ?><span><em><?= e($fieldLabels[$field] ?? $field) ?></em> <?php if (!is_array($before) && !is_array($after) && mb_strlen((string)$before) < 60 && mb_strlen((string)$after) < 60): ?><del><?= e($before === '' || $before === null ? '∅' : $before) ?></del> → <ins><?= e($after === '' || $after === null ? '∅' : $after) ?></ins><?php else: ?><ins><?= e(t('changed', 'modifié')) ?></ins><?php endif; ?></span>
      <?php endforeach; ?><?= count($fields) > 3 ? '<span class="more">+' . (count($fields) - 3) . '</span>' : '' ?></span><?php else: ?><span></span><?php endif; ?>
      <span class="change-status"><?= $x['status'] ? row_badge($x) : '' ?><?php if ($wh): ?><a class="icon-btn is-small" href="<?= e($wh) ?>" target="_blank" rel="noopener" aria-label="Wowhead"><i class="fas fa-arrow-up-right-from-square"></i></a><?php endif; ?></span>
    </li>
  <?php endforeach; ?>
  </ul>
</section>
<?php endforeach; ?>
<?php if ($pages > 1): ?>
<nav class="pager" aria-label="<?= e(t('Pages', 'Pages')) ?>">
  <?php if ($page > 1): ?><a class="btn is-small" href="<?= e($query(['p' => $page - 1])) ?>"><i class="fas fa-arrow-left"></i> <?= e(t('Previous', 'Précédent')) ?></a><?php else: ?><span></span><?php endif; ?>
  <span class="pager-info"><?= e(sprintf(t('Page %d of %s', 'Page %d sur %s'), $page, number($pages))) ?></span>
  <?php if ($page < $pages): ?><a class="btn is-small" href="<?= e($query(['p' => $page + 1])) ?>"><?= e(t('Next', 'Suivant')) ?> <i class="fas fa-arrow-right"></i></a><?php else: ?><span></span><?php endif; ?>
</nav>
<?php endif; endif; ?>
<?php page_end();
