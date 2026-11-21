<?php
// Extras: what the server's world holds that the live game does not (tools/ft/extras.py fills ft_world_extras at each
// analysis). A list to look at: nothing is changed from here. ?sql=1 gives the removals it is sure enough to write
// (stacked copies, and the old twins standing beside a spawn of their live entry) as an update file to review.
const EXTRAS_TWIN_YARDS = 15;   // tools/ft/extras.py TWIN_YARDS
$have = table_exists('ft_world_extras');
$issues = [
    'twin' => [t('Old twin', 'Ancien jumeau'), t('The server spawns a creature the live server never sent to a client; live uses another entry of the same name (often Forever\'s copy of a Classic creature). A spawn within 15 yards of a spawn of the live entry (same map, phase and events) is listed by its guid: that one creature stands twice, and the removals take it. The others are listed by entry and left alone.', 'Le serveur place une créature que le serveur officiel n’a jamais envoyée ; le jeu utilise une autre entrée du même nom.')],
    'stacked' => [t('Stacked', 'Empilés'), t('Two spawns of the same name on one spot, in the same phase and the same world events, neither in a pool: one model inside another. The one to keep is named.', 'Deux placements du même nom au même endroit, même phase et mêmes événements, hors pool. Celui à garder est indiqué.')],
    'crowded' => [t('Crowded', 'Surpeuplé'), t('Far more spots of a creature than the live game shows in that place (the most any witness gives: Wowhead\'s Forever map, QuestieDB\'s player traces, EG Link\'s sightings), and than Classic had (QuestieDB). A pool counts as one spot, a pack on one spot once.', 'Bien plus de placements que le jeu officiel n’en montre (Wowhead, traces QuestieDB, EG Link) et que Classic n’en avait (QuestieDB). Un pool compte pour un placement.')],
    'invented' => [t('Invented', 'Inventé'), t('A creature nothing outside the server knows (not in the client, never recorded, not on Wowhead), or the server\'s own entry (an id from 1,000,000 up): a stand-in an import made where the real data was missing. Never removed: until the real entry is found, removing a stand-in leaves a hole. Objects below 1,000,000 are not judged: Wowhead does not list chairs, lamps or doors.', 'Une créature que rien hors du serveur ne connaît, ou une entrée propre au serveur (id dès 1 000 000) qui remplace une donnée manquante. Jamais supprimée.')],
    'giver' => [t('Quest giver', 'Donneur de quête'), t('The server has it give or take a quest that live players only saw others give or take. Weaker: a second giver may simply not have been recorded.', 'Le serveur lui fait donner ou rendre une quête que les joueurs n’ont vue que chez d’autres.')],
];
$issue = isset($issues[$_GET['issue'] ?? '']) ? $_GET['issue'] : 'twin';
$kind = in_array($_GET['kind'] ?? '', ['npc', 'go'], true) ? $_GET['kind'] : '';

if ($have && ($_GET['sql'] ?? '') === '1') {
    $out = ["-- Extras the tracker is sure enough to remove (" . date('Y-m-d H:i') . "): review before applying.", ''];
    foreach (['npc' => ['creature', 0], 'go' => ['gameobject', 1]] as $k => [$table, $type]) {
        $guids = array_map('intval', array_column(rows("SELECT guid FROM ft_world_extras WHERE issue = 'stacked' AND kind = ? AND guid IS NOT NULL ORDER BY guid", [$k]), 'guid'));
        if ($guids) {
            $list = implode(',', $guids);
            $out[] = "-- $table: " . count($guids) . " stacked copies";
            $out[] = "DELETE FROM `{$table}_addon` WHERE `guid` IN ($list);";
            $out[] = "DELETE FROM `spawn_group` WHERE `spawnType` = $type AND `spawnId` IN ($list);";
            $out[] = "DELETE FROM `$table` WHERE `guid` IN ($list);";
            $out[] = '';
        }
    }
    // old twins: only the spawns the analysis found within TWIN_YARDS of a spawn of their live entry (guid set). The
    // file checks it again when it runs: a spawn goes only while it still holds its old entry and a spawn of the live
    // entry still stands that close on its map, so a world changed since the analysis loses nothing it should keep.
    $twins = rows("SELECT guid, entry, name, live, note FROM ft_world_extras WHERE issue = 'twin' AND kind = 'npc' AND guid IS NOT NULL ORDER BY entry, guid");
    if ($twins) {
        $out[] = '-- creature: ' . count($twins) . ' old twins standing within ' . EXTRAS_TWIN_YARDS . ' yards of a spawn of their live entry';
        $out[] = 'DROP TEMPORARY TABLE IF EXISTS `ft_old_twins`;';
        $out[] = 'CREATE TEMPORARY TABLE `ft_old_twins` (`guid` bigint unsigned NOT NULL PRIMARY KEY, `old_id` int unsigned NOT NULL, `live_id` int unsigned NOT NULL);';
        $values = [];
        foreach ($twins as $i => $x) {
            $live = (int)strtok((string)$x['live'], ',');
            $values[] = '(' . (int)$x['guid'] . ', ' . (int)$x['entry'] . ', ' . $live . ')' . ($i === count($twins) - 1 ? ';' : ',')
                . ' -- ' . str_replace(["\n", "\r"], ' ', (string)$x['name']) . ': ' . str_replace(["\n", "\r"], ' ', (string)$x['note']);
        }
        $out[] = 'INSERT IGNORE INTO `ft_old_twins` (`guid`, `old_id`, `live_id`) VALUES';
        array_push($out, ...$values);
        $yards2 = EXTRAS_TWIN_YARDS * EXTRAS_TWIN_YARDS;
        $out[] = 'DROP TEMPORARY TABLE IF EXISTS `ft_old_twins_go`;';
        $out[] = 'CREATE TEMPORARY TABLE `ft_old_twins_go` (`guid` bigint unsigned NOT NULL PRIMARY KEY);';
        $out[] = "INSERT IGNORE INTO `ft_old_twins_go` (`guid`) SELECT c.`guid` FROM `ft_old_twins` t"
            . " JOIN `creature` c ON c.`guid` = t.`guid` AND c.`id` = t.`old_id`"
            . " JOIN `creature` x ON x.`id` = t.`live_id` AND x.`map` = c.`map` AND x.`guid` <> c.`guid`"
            . " AND (x.`position_x` - c.`position_x`) * (x.`position_x` - c.`position_x`) + (x.`position_y` - c.`position_y`) * (x.`position_y` - c.`position_y`)"
            . " + (x.`position_z` - c.`position_z`) * (x.`position_z` - c.`position_z`) <= $yards2;";
        $out[] = 'DELETE g FROM `game_event_creature` g JOIN `ft_old_twins_go` t ON t.`guid` = g.`guid`;';
        $out[] = 'DELETE a FROM `creature_addon` a JOIN `ft_old_twins_go` t ON t.`guid` = a.`guid`;';
        $out[] = 'DELETE p FROM `pool_members` p JOIN `ft_old_twins_go` t ON t.`guid` = p.`spawnId` WHERE p.`type` = 0;';
        $out[] = 'DELETE s FROM `spawn_group` s JOIN `ft_old_twins_go` t ON t.`guid` = s.`spawnId` WHERE s.`spawnType` = 0;';
        $out[] = 'DELETE f FROM `creature_formations` f JOIN `ft_old_twins_go` t ON t.`guid` = f.`memberGUID`;';
        $out[] = 'DELETE c FROM `creature` c JOIN `ft_old_twins_go` t ON t.`guid` = c.`guid`;';
        $out[] = 'DROP TEMPORARY TABLE `ft_old_twins_go`;';
        $out[] = 'DROP TEMPORARY TABLE `ft_old_twins`;';
        $out[] = '';
    }
    $left = (int)value("SELECT COUNT(*) FROM ft_world_extras WHERE issue = 'twin' AND guid IS NULL");
    if ($left) $out[] = "-- not here: $left old twin entries whose spawns stand nowhere near a live spawn, or whose live entry the server does not spawn (the Extras page lists them)";
    header('Content-Type: text/plain; charset=utf-8');
    header('Content-Disposition: attachment; filename="world-extras-removals.sql"');
    echo implode("\n", $out), "\n";
    exit;
}

$where = 'WHERE issue = ?' . ($kind ? ' AND kind = ?' : '');
$params = $kind ? [$issue, $kind] : [$issue];
$list = $have ? rows("SELECT * FROM ft_world_extras $where ORDER BY name, entry, guid LIMIT 3000", $params) : [];
$total = $have ? (int)value("SELECT COUNT(*) FROM ft_world_extras $where", $params) : 0;
$counts = [];
foreach ($issues as $key => $_) $counts[$key] = $have ? (int)value('SELECT COUNT(*) FROM ft_world_extras WHERE issue = ?', [$key]) : 0;
$wowhead = fn($k, $id) => 'https://www.wowhead.com/forever/' . ($k === 'go' ? 'object' : 'npc') . '=' . (int)$id;
page_start(t('Extras', 'En trop'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-clone"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Extras', 'En trop')) ?></h1>
    <p><?= e(t('What your server\'s world holds that the live game does not: the other way round from every other page. Each finding needs a witness that something else stands in its place (players\' EG Link recordings, Wowhead\'s Forever map): that nobody recorded a thing is never enough. The analysis fills this list. Nothing is changed from here.', 'Ce que le monde de votre serveur contient et que le jeu officiel n’a pas. Rien n’est modifié ici.')) ?></p></div></div>
</section>
<nav class="tabs">
  <?php foreach ($issues as $key => [$label]): ?>
  <a class="<?= $issue === $key ? 'is-active' : '' ?>" href="<?= e(url('admin/extras', ['issue' => $key])) ?>"><?= e($label) ?><em><?= number($counts[$key]) ?></em></a>
  <?php endforeach; ?>
  <a href="<?= e(url('admin/checks')) ?>"><i class="fas fa-scale-balanced"></i><?= e(t('Checks', 'Contrôles')) ?></a>
</nav>
<p class="tab-desc"><i class="fas fa-circle-info"></i> <?= e($issues[$issue][1]) ?></p>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No list yet: it is made by the next analysis (it needs an EG Link import).', 'Pas encore de liste : la prochaine analyse la fera (il faut un import EG Link).')) ?></p></div><?php else: ?>
<p class="small">
  <a class="link" href="<?= e(url('admin/extras', ['issue' => $issue])) ?>"><?= e(t('All', 'Tout')) ?></a> ·
  <a class="link" href="<?= e(url('admin/extras', ['issue' => $issue, 'kind' => 'npc'])) ?>"><?= e(t('Creatures', 'Créatures')) ?></a> ·
  <a class="link" href="<?= e(url('admin/extras', ['issue' => $issue, 'kind' => 'go'])) ?>"><?= e(t('Objects', 'Objets')) ?></a> ·
  <a class="link" href="<?= e(url('admin/extras', ['sql' => '1'])) ?>"><i class="fas fa-download"></i> <?= e(t('Removals as SQL (stacked + old twins)', 'Suppressions en SQL')) ?></a>
  <?php if ($total > count($list)): ?> · <span class="muted"><?= e(sprintf(t('first %s of %s', '%s premiers sur %s'), number(count($list)), number($total))) ?></span><?php endif; ?>
</p>
<table class="table">
  <thead><tr><th><?= e(t('Entry', 'Entrée')) ?></th><th><?= e(t('Where', 'Où')) ?></th><th><?= e(t('Server', 'Serveur')) ?></th><th><?= e(t('Live', 'Officiel')) ?></th><th><?= e(t('Finding', 'Constat')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <tr>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted"><?= e($x['kind'] === 'go' ? t('object', 'objet') : t('creature', 'créature')) ?> #<?= (int)$x['entry'] ?></small> <a class="link small" href="<?= e($wowhead($x['kind'], $x['entry'])) ?>" target="_blank" rel="noopener">Wowhead</a></td>
      <td class="small"><?php if ($x['guid'] !== null): ?>guid <?= (int)$x['guid'] ?><br><?php endif; ?><?php if ($x['map'] !== null): ?><?= e(t('map', 'carte')) ?> <?= (int)$x['map'] ?><?php if ($x['x'] !== null): ?> · <?= e(sprintf('%.1f %.1f %.1f', $x['x'], $x['y'], $x['z'])) ?><?php endif; ?><?php endif; ?></td>
      <td><?= $x['server'] === null ? '—' : number($x['server']) ?></td>
      <td class="small"><?php foreach (array_filter(explode(',', (string)$x['live'])) as $id): ?><?php if ($issue === 'crowded'): ?><?= e($id) ?> <?= e(t('at most on live', 'au plus en jeu')) ?><?php elseif ($issue === 'giver'): ?>#<?= (int)$id ?> <?php else: ?><a class="link" href="<?= e($wowhead($x['kind'], $id)) ?>" target="_blank" rel="noopener">#<?= (int)$id ?></a> <?php endif; ?><?php endforeach; ?></td>
      <td class="small"><?= e($x['note']) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>
<?php page_end();
