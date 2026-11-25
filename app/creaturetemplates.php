<?php
// Creature templates (docs/SOURCES.md, "Creature templates"): the creature_template rows (with their difficulty,
// model and level rows) of the creatures that a gap link names and the server has no template for. A gap link is an
// open fact of a source's last snapshot (ft_source_facts, app/snapshots.php): a creature drops or sells a gap item,
// gives a quest without a giver or takes one without an ender. Without the template no card can write the link.
//
// The row comes from Icy Veins' record of the creature (ft_source_answers: source 'icyveins', feed 'api', kind 'npc'):
// its type, family, class, rank, subname, type flags, health and power multipliers, movement and its models
// (children.npc_display). Wowhead's Forever page (source 'wowhead', feed 'page', branch 'forever') is the second
// witness (its model and name) and gives the level and how each side sees the creature (Quick Facts "React").
//
// No source gives a creature's faction template. It is picked from how Wowhead says each side sees the creature,
// with the client's FactionTemplate table (data/faction-templates.json, written by the analysis: ft.sides), in this
// order: the faction of a creature of the same name on the server that both sides see the same way (live re-added
// several Season of Discovery creatures under new numbers: Gishah, Elaine Compton); else a template of the
// reputation faction Wowhead names ("Faction: Azeroth Commerce Authority") that both sides see that way; else the
// template the server's spawned creatures use most among those both sides see that way. A creature whose page shows
// no reaction is left out (the user's decision of 2026-11-25: reaction is the evidence, nothing else is guessed).
require_once FT_APP . '/sources.php';
require_once FT_APP . '/snapshots.php';
require_once FT_APP . '/sourceanswers.php';

/** How Wowhead colours a side in "React": q2 friendly, q10 hostile, q (no number) neutral. */
const CREATURE_TEMPLATE_REACTION = ['q2' => 'friendly', 'q10' => 'hostile', 'q' => 'neutral'];
/** npcflag bits the links give: a quest giver or ender, a vendor. */
const CREATURE_TEMPLATE_QUESTGIVER = 2;
const CREATURE_TEMPLATE_VENDOR = 128;

function creature_templates_file(): string { return FT_ROOT . '/data/faction-templates.json'; }

/**
 * The creatures gap links name: [entry => [fact => true]]. $facts: [[fact, entity, target]] of kind 'npc'; $gaps:
 * source_gaps(). A drop or a sale counts for a gap item, a start for a quest without a giver, an end for a quest
 * without an ender.
 */
function creature_templates_links(iterable $facts, array $gaps): array
{
    $gap = ['drop' => $gaps['items'] ?? [], 'sell' => $gaps['items'] ?? [], 'start' => $gaps['noGiver'] ?? [], 'end' => $gaps['noEnder'] ?? []];
    $out = [];
    foreach ($facts as $f) {
        [$fact, $entity, $target] = array_values((array)$f) + [null, 0, 0];
        if ((int)$entity <= 0 || !isset($gap[$fact][(int)$target])) continue;
        $out[(int)$entity][$fact] = true;
    }
    ksort($out);
    return $out;
}

/** How each side sees a creature, from Wowhead's Quick Facts: ['Alliance' => 'friendly', ...]; a side not shown is absent. */
function creature_template_reaction(array $quick): array
{
    $out = [];
    foreach ($quick as $line) {
        if (!is_string($line) || !str_starts_with(trim($line), 'React')) continue;
        preg_match_all('#\[color=(q\d*)\]\s*([AH])\s*\[/color\]#', $line, $m, PREG_SET_ORDER);
        foreach ($m as [, $colour, $side]) if (isset(CREATURE_TEMPLATE_REACTION[$colour])) $out[$side === 'A' ? 'Alliance' : 'Horde'] = CREATURE_TEMPLATE_REACTION[$colour];
    }
    return $out;
}

/** The reputation faction Wowhead's Quick Facts name ("Faction: [url=/forever/faction=2586/...]"), or 0. */
function creature_template_rep_faction(array $quick): int
{
    foreach ($quick as $line) if (is_string($line) && preg_match('#^Faction:.*?faction=(\d+)#', trim($line), $m)) return (int)$m[1];
    return 0;
}

/** [min, max] level from Wowhead's Quick Facts ("Level: 30", "Level: 57 - 58"), or null ("??", none). */
function creature_template_levels(array $quick): ?array
{
    foreach ($quick as $line) {
        if (is_string($line) && preg_match('#^Level:\s*(\d+)(?:\s*-\s*(\d+))?\s*$#', trim($line), $m)) {
            $lo = (int)$m[1]; $hi = isset($m[2]) && $m[2] !== '' ? (int)$m[2] : $lo;
            return $lo > 0 && $hi >= $lo ? [$lo, $hi] : null;
        }
    }
    return null;
}

/** Whether a faction table row ([faction, alliance, horde, used]) shows each side as $reaction says. */
function creature_template_fits(array $row, array $reaction): bool
{
    foreach ($reaction as $side => $stance) if (($side === 'Alliance' ? $row[1] : $row[2]) !== $stance) return false;
    return (bool)$reaction;
}

/**
 * The faction template for a creature, and how it was found: [template, 'same_name'|'rep_faction'|'reaction'] or
 * [0, reason]. $table: {template: [faction, alliance, horde, used]}; $sameName: [template => count] of the server's
 * creatures of that name.
 */
function creature_template_faction(array $reaction, int $repFaction, array $sameName, array $table): array
{
    if (!$reaction) return [0, 'creature_template_no_reaction'];
    $best = function (array $candidates) {
        if (!$candidates) return 0;
        uksort($candidates, fn($a, $b) => [$candidates[$b], $a] <=> [$candidates[$a], $b]);
        return (int)array_key_first($candidates);
    };
    $named = [];
    foreach ($sameName as $tid => $n) if (isset($table[$tid]) && creature_template_fits($table[$tid], $reaction)) $named[$tid] = (int)$n;
    if ($pick = $best($named)) return [$pick, 'same_name'];
    if ($repFaction) {
        $rep = [];
        foreach ($table as $tid => $row) if ((int)$row[0] === $repFaction && creature_template_fits($row, $reaction)) $rep[$tid] = (int)$row[3];
        return ($pick = $best($rep)) ? [$pick, 'rep_faction'] : [0, 'creature_template_no_faction'];
    }
    $any = [];
    foreach ($table as $tid => $row) if (creature_template_fits($row, $reaction) && (int)$row[3] > 0) $any[$tid] = (int)$row[3];
    return ($pick = $best($any)) ? [$pick, 'reaction'] : [0, 'creature_template_no_faction'];
}

/**
 * The rows of one creature: [['creature_template' => [row], 'creature_template_difficulty' => [row],
 * 'creature_template_model' => [rows], 'creature_classic_level' => [row]], null] or [null, reason].
 * $links: the facts naming it ([fact => true]); $icy, $page: its answers; $table, $sameName: creature_template_faction.
 */
function creature_template_rows(int $entry, array $links, ?array $icy, ?array $page, array $table, array $sameName, int $build = 0): array
{
    $data = $icy['data'] ?? null;
    if (is_string($data)) $data = json_decode($data, true);
    if (!$icy || ($icy['status'] ?? 'found') !== 'found' || !is_array($data) || !is_array($data['entity'] ?? null)) return [null, 'creature_template_no_record'];
    $e = $data['entity'];
    $name = is_string($e['name'] ?? null) ? trim($e['name']) : '';
    $displays = array_values(array_filter((array)($data['children']['npc_display'] ?? []), fn($d) => is_array($d) && (int)($d['display_id'] ?? 0) > 0));
    if ($name === '' || !is_int($e['type_id'] ?? null) || !$displays) return [null, 'creature_template_incomplete'];
    $pageData = $page['data'] ?? null;
    if (is_string($pageData)) $pageData = json_decode($pageData, true);
    if (!$page || ($page['status'] ?? 'found') !== 'found' || !is_array($pageData) || ($pageData['status'] ?? 'ok') !== 'ok') return [null, 'creature_template_no_witness'];
    $models = array_map('intval', array_filter((array)($pageData['model'] ?? []), 'is_int'));
    $pageName = is_string($page['name'] ?? null) ? trim($page['name']) : '';
    if (!$models) return [null, 'creature_template_no_witness'];
    if (!array_intersect(array_map(fn($d) => (int)$d['display_id'], $displays), $models) || ($pageName !== '' && mb_strtolower($pageName) !== mb_strtolower($name))) return [null, 'creature_template_witness_differs'];
    $quick = (array)($pageData['quick'] ?? []);
    $levels = creature_template_levels($quick);
    if (!$levels) return [null, 'creature_template_no_level'];
    [$faction, $how] = creature_template_faction(creature_template_reaction($quick), creature_template_rep_faction($quick), $sameName, $table);
    if (!$faction) return [null, $how];
    $num = fn($k, $d) => isset($e[$k]) && is_numeric($e[$k]) ? $e[$k] + 0 : $d;
    $npcflag = (isset($links['start']) || isset($links['end']) ? CREATURE_TEMPLATE_QUESTGIVER : 0) | (isset($links['sell']) ? CREATURE_TEMPLATE_VENDOR : 0);
    $template = ['entry' => $entry, 'name' => mb_substr($name, 0, 100), 'subname' => is_string($e['description'] ?? null) ? mb_substr($e['description'], 0, 100) : '',
        'RequiredExpansion' => (int)$num('required_expansion', 0), 'faction' => $faction, 'npcflag' => $npcflag, 'speed_walk' => 1.0, 'speed_run' => 1.14286, 'scale' => 1.0,
        'Classification' => (int)$num('classification', 0), 'BaseAttackTime' => 2000, 'RangeAttackTime' => 2000, 'unit_class' => (int)$num('unit_class', 1) ?: 1,
        'unit_flags' => 0, 'unit_flags2' => 2048, 'family' => (int)$num('family_id', 0), 'type' => (int)$e['type_id'], 'movementId' => (int)$num('movement_info_id', 0),
        'RegenHealth' => 1, 'VerifiedBuild' => $build];
    $difficulty = ['Entry' => $entry, 'DifficultyID' => 0, 'HealthScalingExpansion' => (int)$num('health_scaling_expansion', 0), 'HealthModifier' => (float)$num('health_multiplier', 1),
        'ManaModifier' => (float)$num('power_multiplier', 1), 'CreatureDifficultyID' => (int)$num('difficulty_id', 0), 'TypeFlags' => (int)$num('flags', 0),
        'TypeFlags2' => (int)$num('flags_2', 0), 'TypeFlags3' => (int)$num('flags_3', 0), 'VerifiedBuild' => $build];
    $even = !array_filter($displays, fn($d) => (float)($d['probability'] ?? 0) > 0);
    $models = [];
    foreach ($displays as $i => $d) $models[] = ['CreatureID' => $entry, 'Idx' => (int)($d['order_index'] ?? $i), 'CreatureDisplayID' => (int)$d['display_id'],
        'DisplayScale' => (float)($d['scale'] ?? 1) ?: 1.0, 'Probability' => $even ? 1.0 : (float)($d['probability'] ?? 0), 'VerifiedBuild' => $build];
    return [['creature_template' => [$template], 'creature_template_difficulty' => [$difficulty], 'creature_template_model' => $models,
        'creature_classic_level' => [['entry' => $entry, 'level_min' => $levels[0], 'level_max' => $levels[1]]], 'how' => $how], null];
}

/** The faction table the analysis wrote: {template: [faction, alliance, horde, used]}, [] without one. */
function creature_templates_factions(?string $file = null): array
{
    $raw = json_decode((string)@file_get_contents($file ?? creature_templates_file()), true);
    $out = [];
    foreach ((array)($raw['templates'] ?? []) as $tid => $row) if (is_array($row) && count($row) >= 4) $out[(int)$tid] = [(int)$row[0], (string)$row[1], (string)$row[2], (int)$row[3]];
    return $out;
}

/** The import card of the creature templates the gap links want ("Icy Veins creatures"). */
function creature_templates_import(): array
{
    if ($e = source_check()) return $e;
    $table = creature_templates_factions();
    if (!$table) return ['ok' => false, 'message' => t('The faction table is not written yet: run the analysis again (it writes data/faction-templates.json).', 'La table des factions n’est pas encore écrite : relancez l’analyse (elle écrit data/faction-templates.json).')];
    snapshot_schema();
    $gaps = source_gaps();
    $facts = rows("SELECT f.fact, f.entity, f.target FROM ft_source_facts f JOIN (SELECT source, MAX(id) id FROM ft_source_snapshots GROUP BY source) l"
        . " ON l.source = f.source AND f.last_snapshot = l.id WHERE f.kind = 'npc' AND f.fact IN ('drop', 'sell', 'start', 'end')");
    $links = creature_templates_links($facts, $gaps);
    unset($facts);
    foreach (array_chunk(array_keys($links), 1000) as $chunk) {
        foreach (rows('SELECT entry FROM creature_template WHERE entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) unset($links[(int)$r['entry']]);
    }
    if (!$links) return ['ok' => false, 'id' => 0, 'counts' => [], 'ignored' => [],
        'message' => t('Every creature a gap link names has a template on this server.', 'Chaque PNJ qu’un lien de manque nomme a un modèle sur ce serveur.')];
    $icy = object_templates_answers_of('icyveins', 'api', 'npc', array_keys($links));
    $pages = object_templates_answers_of('wowhead', 'page', 'npc', array_keys($links), 'forever');
    // the server's creatures of the same names, with their faction templates
    $names = [];
    foreach ($icy as $entry => $a) if (is_string($a['name'] ?? null) && $a['name'] !== '') $names[$entry] = $a['name'];
    $sameName = [];
    foreach (array_chunk(array_values(array_unique($names)), 500) as $chunk) {
        $marks = implode(',', array_fill(0, count($chunk), '?'));
        foreach (rows("SELECT name, faction, COUNT(*) n FROM creature_template WHERE name IN ($marks) GROUP BY name, faction", $chunk, 'world') as $r) $sameName[mb_strtolower($r['name'])][(int)$r['faction']] = (int)$r['n'];
    }
    $build = (int)(meta()['client_build'] ?? 0);
    $rows = []; $left = []; $newest = 0;
    foreach ($links as $entry => $linked) {
        [$made, $why] = creature_template_rows((int)$entry, $linked, $icy[$entry] ?? null, $pages[$entry] ?? null, $table, $sameName[mb_strtolower($names[$entry] ?? '')] ?? [], $build);
        if (!$made) { $left[$why] = ($left[$why] ?? 0) + 1; continue; }
        $left['creature_template_faction_' . $made['how']] = ($left['creature_template_faction_' . $made['how']] ?? 0) + 1;
        unset($made['how']);
        foreach ($made as $t => $list) $rows[$t] = array_merge($rows[$t] ?? [], $list);
        $newest = max($newest, (int)($icy[$entry]['at'] ?? 0));
    }
    $tables = [];
    foreach ($rows as $t => $list) {
        if (!$list || !table_exists($t, 'world')) continue;
        $use = array_values(array_intersect(array_keys($list[0]), import_columns('world', $t)));
        $tables[$t] = ['db' => 'world', 'columns' => $use, 'groups' => [['columns' => $use, 'rows' => array_map(fn($r) => array_map(fn($c) => $r[$c], $use), $list)]]];
    }
    $date = date('Y-m-d', $newest ?: time());
    $label = SOURCES['icyveins'][0] . ' ' . t('creatures', 'PNJ') . ' ' . $date;
    return source_card('icyveins', $label, 'icyveins-creatures@' . $date . '-' . $newest, $tables, $left, [], 'icyveins-creatures');
}

/** The answers of one source's kind for some ids: [id => {status, name, data, at}] (object_templates_answers). */
function object_templates_answers_of(string $source, string $feed, string $kind, array $ids, string $branch = ''): array
{
    require_once FT_APP . '/objecttemplates.php';
    return object_templates_answers($source, $feed, $kind, $ids, $branch);
}
