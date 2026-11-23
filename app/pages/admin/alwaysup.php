<?php
// Always up: creatures that stand in the world all the time when a script or a holiday should bring them in only for
// a while (tools/ft/alwaysup.py fills ft_always_up at each analysis; docs/SPAWNS.md "Always up"). A list to look at:
// nothing is changed from here. ?csv=1 gives the open tab as a CSV file.
$have = table_exists('ft_always_up');
$kinds = [
    'summoned' => [t('Summoned, yet always up', 'Invoqués, pourtant toujours là'), t('A script of yours brings the creature in when a quest or an event calls it (SmartAI, a summon group, an event script, a summoning spell, the core\'s C++), and no reference world keeps it spawned anywhere. Standing for good, it can be killed or talked to without the quest, and the script then summons a second one beside it. The fix is to remove the spawn and leave the script. "Later" creatures came after 3.3.5: no reference can speak for them, only your scripts do, so look before removing.', 'Un de vos scripts fait venir la créature quand une quête ou un événement l\'appelle (SmartAI, groupe d\'invocation, script d\'événement, sort d\'invocation, C++ du noyau), et aucun monde de référence ne la garde placée. Placée pour de bon, on peut la tuer ou lui parler sans la quête, et le script en invoque une seconde à côté. La correction : retirer le placement et garder le script. Les créatures « plus tardives » sont venues après la 3.3.5 : aucune référence ne parle pour elles, seuls vos scripts le font, regardez avant de retirer.')],
    'holiday' => [t('Holiday, yet up all year', 'Fête, pourtant là toute l\'année'), t('The reference worlds spawn the creature only through world events, and either one of your events already holds other spawns of it, or one of those events is a holiday that comes back every year. Its spawns outside any event stand all year. The fix is to put them on the event.', 'Les mondes de référence ne placent la créature que par des événements, et soit un de vos événements tient déjà d\'autres placements d\'elle, soit l\'un de ces événements est une fête annuelle. Ses placements hors événement restent toute l\'année. La correction : les mettre sur l\'événement.')],
];
$kind = isset($kinds[$_GET['kind'] ?? '']) ? $_GET['kind'] : 'summoned';
$later = ($_GET['later'] ?? '') === '1';
$where = 'WHERE kind = ?' . ($kind === 'summoned' ? ' AND later = ?' : '');
$params = $kind === 'summoned' ? [$kind, $later ? 1 : 0] : [$kind];

if ($have && ($_GET['csv'] ?? '') === '1') {
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="always-up-' . $kind . ($later ? '-later' : '') . '.csv"');
    $out = fopen('php://output', 'w');
    fputcsv($out, ['entry', 'name', 'kind', 'later', 'spawns', 'maps', 'guids', 'cause', 'witness']);
    foreach (rows("SELECT * FROM ft_always_up $where ORDER BY spawns DESC, name, entry", $params) as $x) {
        fputcsv($out, [$x['entry'], $x['name'], $x['kind'], $x['later'], $x['spawns'], $x['maps'], $x['guids'], $x['cause'], $x['witness']]);
    }
    exit;
}

$list = $have ? rows("SELECT * FROM ft_always_up $where ORDER BY spawns DESC, name, entry LIMIT 2000", $params) : [];
$counts = ['summoned' => 0, 'holiday' => 0];
$laterCount = 0;
if ($have) {
    foreach (rows('SELECT kind, later, COUNT(*) n FROM ft_always_up GROUP BY kind, later') as $r) {
        if ($r['kind'] === 'summoned' && (int)$r['later']) { $laterCount += (int)$r['n']; continue; }
        if (isset($counts[$r['kind']])) $counts[$r['kind']] += (int)$r['n'];
    }
}
$spawnTotal = $have ? (int)value("SELECT COALESCE(SUM(spawns), 0) FROM ft_always_up $where", $params) : 0;
page_start(t('Always up', 'Toujours là'), 'admin');
?>
<section class="page-head">
  <div class="page-title"><span class="page-icon is-gold"><i class="fas fa-clock"></i></span>
    <div><span class="eyebrow"><a href="<?= e(url('admin')) ?>"><?= e(t('The Forge', 'La Forge')) ?></a></span><h1><?= e(t('Always up', 'Toujours là')) ?></h1>
    <p><?= e(t('Quest creatures, script creatures and holiday creatures that stand in your world all the time when they should come only for a while. Your permanent spawns (on no world event, in no phase) against what your scripts summon and the spawn audit\'s reference worlds. The analysis fills this list. Nothing is changed from here.', 'Créatures de quête, de script et de fête qui se tiennent dans votre monde en permanence alors qu\'elles ne devraient venir qu\'un temps. Vos placements permanents (sans événement, sans phase) face à ce que vos scripts invoquent et aux mondes de référence de l\'audit des placements. L\'analyse remplit cette liste. Rien n\'est modifié d\'ici.')) ?></p></div></div>
</section>
<nav class="tabs">
  <a class="<?= $kind === 'summoned' && !$later ? 'is-active' : '' ?>" href="<?= e(url('admin/alwaysup', ['kind' => 'summoned'])) ?>"><?= e($kinds['summoned'][0]) ?><em><?= number($counts['summoned']) ?></em></a>
  <a class="<?= $kind === 'summoned' && $later ? 'is-active' : '' ?>" href="<?= e(url('admin/alwaysup', ['kind' => 'summoned', 'later' => '1'])) ?>"><?= e(t('Summoned: later creatures', 'Invoqués : créatures plus tardives')) ?><em><?= number($laterCount) ?></em></a>
  <a class="<?= $kind === 'holiday' ? 'is-active' : '' ?>" href="<?= e(url('admin/alwaysup', ['kind' => 'holiday'])) ?>"><?= e($kinds['holiday'][0]) ?><em><?= number($counts['holiday']) ?></em></a>
  <a href="<?= e(url('admin/spawnaudit')) ?>"><i class="fas fa-users-viewfinder"></i><?= e(t('Spawn audit', 'Audit des placements')) ?></a>
</nav>
<p class="tab-desc"><i class="fas fa-circle-info"></i> <?= e($kinds[$kind][1]) ?></p>
<?php if (!$have): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No list yet: the next analysis makes it, after the spawn audit has its reference worlds.', 'Pas encore de liste : la prochaine analyse la fera, une fois que l\'audit des placements a ses mondes de référence.')) ?></p></div><?php else: ?>
<p class="small">
  <strong><?= e(sprintf(t('%s spawns', '%s placements'), number($spawnTotal))) ?></strong> ·
  <a class="link" href="<?= e(url('admin/alwaysup', ['kind' => $kind, 'csv' => '1'] + ($later ? ['later' => '1'] : []))) ?>"><i class="fas fa-download"></i> CSV</a>
</p>
<table class="table">
  <thead><tr><th><?= e(t('Creature', 'Créature')) ?></th><th><?= e(t('Spawns', 'Placements')) ?></th><th><?= e(t('Maps', 'Cartes')) ?></th>
    <th><?= e($kind === 'holiday' ? t('Reference events', 'Événements des références') : t('Brought in by', 'Amenée par')) ?></th><th><?= e(t('Witness', 'Témoin')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <tr>
      <td><strong><?= e($x['name']) ?></strong> <small class="muted">#<?= (int)$x['entry'] ?></small> <a class="link small" href="https://www.wowhead.com/forever/npc=<?= (int)$x['entry'] ?>" target="_blank" rel="noopener">Wowhead</a></td>
      <td><span title="<?= e(substr((string)$x['guids'], 0, 1500)) ?>"><?= number((int)$x['spawns']) ?></span></td>
      <td class="small"><?= e($x['maps']) ?></td>
      <td class="small"><?= e($x['cause']) ?></td>
      <td class="small muted"><?= e($x['witness']) ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
<?php endif; ?>
<?php page_end();
