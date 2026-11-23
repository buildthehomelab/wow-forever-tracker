<?php
// Checks: the server's data compared with Wowhead's Forever tooltips. A ticked difference takes Wowhead's value through
// the Forge: previewed as SQL, applied in a transaction, kept in the history with its rollback.
require_once FT_APP . '/forge.php';
$have = table_exists('ft_npc_checks');
$kinds = ['level' => t('Level', 'Niveau'), 'rank' => t('Rank', 'Rang'), 'faction' => t('Faction', 'Faction'), 'sides' => t('Shown to one side', 'Montré à un seul camp'), 'discount' => t('Vendor reputation', 'Réputation du marchand')];
$issue = isset($kinds[$_GET['issue'] ?? '']) ? $_GET['issue'] : '';
// quests whose item rewards are handed out another way than on the live game (ft.rewardkinds): their own table and tab
$rewards = ($_GET['issue'] ?? '') === 'rewards';
$haveQuests = table_exists('ft_quest_checks');
$questKinds = ['all' => t('Live gives them all', 'Le jeu les donne tous'), 'choice' => t('Live offers a choice', 'Le jeu propose un choix'), 'twice' => t('Given and offered', 'Donné et proposé')];
$questList = $rewards && $haveQuests ? rows('SELECT * FROM ft_quest_checks ORDER BY quest LIMIT 2000') : [];
$questCount = $haveQuests ? (int)value('SELECT COUNT(*) FROM ft_quest_checks') : 0;
/** "19991,19992x5" as [[item, count], …]. */
$pairs = fn(?string $list) => array_map(fn($part) => [(int)$part, (int)(explode('x', $part)[1] ?? 1)], array_filter(explode(',', (string)$list), 'strlen'));
$itemNames = [];
if ($questList) {
    $ids = [];
    foreach ($questList as $x) foreach (['gives', 'offers', 'live_gives', 'live_offers'] as $column) foreach ($pairs($x[$column]) as [$item]) $ids[$item] = true;
    foreach (array_chunk(array_keys($ids), 500) as $chunk) {
        foreach (rows("SELECT id, name, name_en FROM ft_entities WHERE type = 'item' AND id IN (" . implode(',', array_map('intval', $chunk)) . ')') as $r) $itemNames[(int)$r['id']] = lang() === 'en' && $r['name_en'] !== '' ? $r['name_en'] : $r['name'];
    }
}
$itemList = function (?string $list) use ($pairs, &$itemNames): string {
    if ($list === null) return '<span class="muted">' . e(t('no record', 'pas d’enregistrement')) . '</span>';
    $out = [];
    foreach ($pairs($list) as [$item, $count]) $out[] = '<a class="link" href="' . e(entry_url('item', $item)) . '">' . e($itemNames[$item] ?? ('#' . $item)) . '</a>' . ($count > 1 ? ' ×' . $count : '');
    return $out ? implode('<br>', $out) : '<span class="muted">—</span>';
};
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
  <a class="<?= $rewards ? 'is-active' : '' ?>" href="<?= e(url('admin/checks', ['issue' => 'rewards'])) ?>"><?= e(t('Quest rewards', 'Récompenses de quête')) ?><em><?= number($questCount) ?></em></a>
</nav>
<?php if ($rewards): ?>
<?php if (!$haveQuests): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-hourglass-half"></i></div><p><?= e(t('No check yet: run the analysis.', 'Pas encore de contrôle : lancez l’analyse.')) ?></p></div><?php else: ?>
<div class="alert"><i class="fas fa-gift"></i><div><?= e(t('Quests that hand out their item rewards another way than the live game. A quest either gives its items outright (all of them) or offers them as a choice (the player takes one). Forever turned many of Classic’s choices into "you get them all". The live game is what players’ recordings (EG Link) show, from the commit Import EG Link last read. "Given and offered": the server gives an item and offers the same item as a choice, so the player is given it and picks it as well. Nothing to tick here: Import EG Link puts these changes on its card (it moves each item to the list the live game names it in), and they are applied from there.', 'Quêtes qui distribuent leurs objets autrement que le jeu officiel. Une quête donne ses objets d’office (tous) ou les propose au choix (le joueur en prend un). Forever a changé beaucoup de choix de Classic en « vous les recevez tous ». Le jeu officiel est ce que montrent les enregistrements des joueurs (EG Link), du commit lu par le dernier Import EG Link. « Donné et proposé » : le serveur donne un objet et propose le même au choix, le joueur le reçoit donc et le choisit en plus. Rien à cocher ici : Import EG Link met ces changements sur sa carte (chaque objet va dans la liste où le jeu officiel le nomme), et ils s’appliquent depuis là.')) ?></div></div>
<?php if (!$questList): ?><div class="empty-state is-inline"><div class="empty-icon"><i class="fas fa-check"></i></div><p><?= e(t('Every quest hands out its items as the live game does.', 'Chaque quête distribue ses objets comme le jeu officiel.')) ?></p></div><?php else: ?>
<div class="table-scroll">
<table class="table is-forge quest-rewards">
  <thead><tr><th><?= e(t('Quest', 'Quête')) ?></th><th><?= e(t('Server gives', 'Le serveur donne')) ?></th><th><?= e(t('Server offers (choose one)', 'Le serveur propose (un au choix)')) ?></th><th><?= e(t('Live gives', 'Le jeu donne')) ?></th><th><?= e(t('Live offers (choose one)', 'Le jeu propose (un au choix)')) ?></th><th><?= e(t('Finding', 'Constat')) ?></th></tr></thead>
  <tbody>
  <?php foreach ($questList as $x): $note = trim((string)$x['note']); ?>
    <tr>
      <td><a class="link" href="<?= e(entry_url('quest', (int)$x['quest'])) ?>"><strong><?= e($x['name'] !== '' ? $x['name'] : '#' . (int)$x['quest']) ?></strong></a> <small class="muted">#<?= (int)$x['quest'] ?></small>
        <?php if ((int)$x['live_build']): ?><br><small class="muted"><?= e(sprintf(t('recorded on build %d', 'enregistrée sur le build %d'), (int)$x['live_build'])) ?></small><?php endif; ?></td>
      <td class="items" data-label="<?= e(t('Server gives', 'Le serveur donne')) ?>"><?= $itemList($x['gives']) ?></td><td class="items" data-label="<?= e(t('Server offers (choose one)', 'Le serveur propose (un au choix)')) ?>"><?= $itemList($x['offers']) ?></td>
      <td class="items" data-label="<?= e(t('Live gives', 'Le jeu donne')) ?>"><?= $itemList($x['live_gives']) ?></td><td class="items" data-label="<?= e(t('Live offers (choose one)', 'Le jeu propose (un au choix)')) ?>"><?= $itemList($x['live_offers']) ?></td>
      <td class="finding"><?php foreach (explode(',', (string)$x['issues']) as $kind): ?><span class="tag is-plain"><?= e($questKinds[$kind] ?? $kind) ?></span> <?php endforeach; ?>
        <?php if ($note !== ''): ?><br><small class="check-note"><?= e($note) ?></small><?php endif; ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table>
</div>
<?php endif; endif; ?>
<?php else: ?>
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
<?php endif; ?>
<div class="action-bar" data-action-bar hidden>
  <div class="action-count"><strong data-selected-count>0</strong> <span><?= e(t('selected', 'sélectionnée(s)')) ?></span></div>
  <button class="btn is-small" type="button" data-forge-preview-selection><i class="fas fa-eye"></i> <?= e(t('Preview SQL', 'Voir le SQL')) ?></button>
  <button class="btn is-small" type="button" data-forge-download><i class="fas fa-download"></i> .sql</button>
  <button class="btn is-small is-gold" type="button" data-forge-apply-selection><i class="fas fa-bolt"></i> <?= e(t('Take Wowhead’s values', 'Prendre les valeurs de Wowhead')) ?></button>
</div>
<?php require FT_APP . '/pages/admin/_modals.php'; ?>
<?php page_end();
