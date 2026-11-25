<?php
// Object templates (docs/SOURCES.md, "Object templates"): a gameobject_template row for each object that a gap link
// names and the server has no template for. A gap link is an open fact of a source's last snapshot (ft_source_facts,
// app/snapshots.php) that an object drops a gap item, gives a quest without a giver or takes one without an ender.
// Without the template no card can write that link: source_tables() leaves it out ('object_no_loot', 'quest_unknown').
//
// The row comes from Icy Veins' record of the object (ft_source_answers: source 'icyveins', feed 'api', kind
// 'gameobject'): its entity's type_id, display_id, scale, content_tuning_id, lock_id and props (props[n] is Data<n>,
// as the client's GameObjects table holds them). Wowhead's Forever page of the object (source 'wowhead', feed 'page',
// branch 'forever') is the second witness: its model must be the record's display, and its name, when the page keeps
// one, the record's name. A row is written only when every field is there and the witness agrees; anything else is
// left out with its reason. Nothing is guessed, and nothing is asked of a source here: both are read from the table.
require_once FT_APP . '/sources.php';
require_once FT_APP . '/snapshots.php';
require_once FT_APP . '/sourceanswers.php';

/** The Data columns of gameobject_template (Data0..Data34). */
const OBJECT_TEMPLATE_DATA = 35;
/** The least props a record must have: Data0..Data33 (Data34 is 0 when a record stops before it). */
const OBJECT_TEMPLATE_PROPS_MIN = 34;
/** The entity fields a record must have (content_tuning_id and lock_id may be null: the object has none). */
const OBJECT_TEMPLATE_FIELDS = ['name', 'type_id', 'display_id', 'scale', 'content_tuning_id', 'lock_id', 'props'];

/**
 * The objects gap links name: [entry => [fact:target, ...]]. $facts: [[fact, entity, target]] of kind 'go' (open
 * facts of each source's last snapshot); $gaps: source_gaps(). A drop counts for a gap item, a start for a quest
 * without a giver, an end for a quest without an ender. Templates are not looked at here.
 */
function object_templates_links(iterable $facts, array $gaps): array
{
    $gap = ['drop' => $gaps['items'] ?? [], 'start' => $gaps['noGiver'] ?? [], 'end' => $gaps['noEnder'] ?? []];
    $out = [];
    foreach ($facts as $f) {
        [$fact, $entity, $target] = array_values((array)$f) + [null, 0, 0];
        $entity = (int)$entity; $target = (int)$target;
        if ($entity <= 0 || !isset($gap[$fact][$target])) continue;
        $out[$entity][$fact . ':' . $target] = true;
    }
    ksort($out);
    return array_map(fn($links) => array_keys($links), $out);
}

/** A whole number that fits an INT column: the client keeps Data as 32 bits, so a value past 2^31 is a negative one. */
function object_template_int($v): ?int
{
    if (is_int($v)) $n = $v;
    elseif (is_float($v) && floor($v) === $v) $n = (int)$v;
    elseif (is_string($v) && preg_match('/^-?\d+$/', $v)) $n = (int)$v;
    else return null;
    if ($n > 4294967295 || $n < -2147483648) return null;
    return $n > 2147483647 ? $n - 4294967296 : $n;
}

/**
 * The gameobject_template row of $entry, or the reason there is none: [row, null] or [null, reason].
 * $icy: Icy Veins' answer ({status, data}: data as the table keeps it, {entity: {...}}), null when there is none;
 * $page: Wowhead's Forever page ({status, name, data}: data with its model list), null when there is none.
 * Reasons: object_template_no_record, object_template_incomplete, object_template_no_witness, object_template_witness_differs.
 */
function object_template_row(int $entry, ?array $icy, ?array $page, int $build = 0): array
{
    $data = $icy['data'] ?? null;
    if (is_string($data)) $data = json_decode($data, true);
    if (!$icy || ($icy['status'] ?? 'found') !== 'found' || !is_array($data) || !is_array($data['entity'] ?? null)) return [null, 'object_template_no_record'];
    $e = $data['entity'];
    foreach (OBJECT_TEMPLATE_FIELDS as $field) if (!array_key_exists($field, $e)) return [null, 'object_template_incomplete'];
    $name = is_string($e['name']) ? trim($e['name']) : '';
    $type = object_template_int($e['type_id']);
    $display = object_template_int($e['display_id']);
    $scale = is_int($e['scale']) || is_float($e['scale']) ? (float)$e['scale'] : null;
    $tuning = $e['content_tuning_id'] === null ? 0 : object_template_int($e['content_tuning_id']);
    $lock = $e['lock_id'] === null ? 0 : object_template_int($e['lock_id']);
    $props = is_array($e['props']) && array_is_list($e['props']) ? array_map('object_template_int', $e['props']) : [];
    if ($name === '' || $type === null || $type < 0 || $type > 255 || $display === null || $display < 0 || $scale === null || $scale <= 0
        || $tuning === null || $tuning < 0 || $lock === null || $lock < 0 || count($props) < OBJECT_TEMPLATE_PROPS_MIN || in_array(null, $props, true)) return [null, 'object_template_incomplete'];
    // the second witness: Wowhead's Forever page shows the same model, and the same name when it keeps one
    $pageData = $page['data'] ?? null;
    if (is_string($pageData)) $pageData = json_decode($pageData, true);
    if (!$page || ($page['status'] ?? 'found') !== 'found' || !is_array($pageData) || ($pageData['status'] ?? 'ok') !== 'ok') return [null, 'object_template_no_witness'];
    $models = array_map('intval', array_filter((array)($pageData['model'] ?? []), 'is_int'));
    $pageName = is_string($page['name'] ?? null) ? trim($page['name']) : '';
    if (!$models) return [null, 'object_template_no_witness'];
    if (!in_array($display, $models, true) || ($pageName !== '' && mb_strtolower($pageName) !== mb_strtolower($name))) return [null, 'object_template_witness_differs'];
    $row = ['entry' => $entry, 'type' => $type, 'displayId' => $display, 'name' => mb_substr($name, 0, 200),
        'IconName' => is_string($e['cursor_name'] ?? null) ? mb_substr($e['cursor_name'], 0, 100) : '',
        'castBarCaption' => is_string($e['cast_bar_caption'] ?? null) ? mb_substr($e['cast_bar_caption'], 0, 100) : '',
        'unk1' => '', 'size' => $scale];
    for ($n = 0; $n < OBJECT_TEMPLATE_DATA; $n++) $row["Data$n"] = $props[$n] ?? 0;
    $row += ['ContentTuningId' => $tuning, 'RequiredLevel' => 0, 'AIName' => '', 'ScriptName' => '', 'VerifiedBuild' => $build];
    return [$row, null];
}

/**
 * Rows for the wanted objects ($links: object_templates_links, less those the server has a template for) from the
 * answers ($icy, $pages: [entry => answer]). Returns [rows, left out: [reason => count]].
 */
function object_templates_rows(array $links, array $icy, array $pages, int $build = 0): array
{
    $rows = []; $left = [];
    foreach (array_keys($links) as $entry) {
        [$row, $why] = object_template_row((int)$entry, $icy[$entry] ?? null, $pages[$entry] ?? null, $build);
        if ($row) $rows[] = $row;
        else $left[$why] = ($left[$why] ?? 0) + 1;
    }
    return [$rows, $left];
}

/** The answers of one source's kind for some ids: [id => {status, name, data, at}]. */
function object_templates_answers(string $source, string $feed, string $kind, array $ids, string $branch = ''): array
{
    $out = [];
    if (!$ids || !table_exists(SOURCE_ANSWERS_TABLE)) return $out;
    foreach (array_chunk(array_values(array_unique(array_map('intval', $ids))), 1000) as $chunk) {
        $sql = 'SELECT id, status, name, data, UNIX_TIMESTAMP(fetched_at) at FROM ' . SOURCE_ANSWERS_TABLE . ' WHERE source = ? AND feed = ? AND kind = ?'
            . ($branch !== '' ? ' AND branch = ?' : '') . ' AND id IN (' . implode(',', $chunk) . ')';
        foreach (rows($sql, array_merge([$source, $feed, $kind], $branch !== '' ? [$branch] : [])) as $r) $out[(int)$r['id']] = $r;
    }
    return $out;
}

/** The import card of the object templates the gap links want ("Icy Veins objects"). */
function object_templates_import(): array
{
    if ($e = source_check()) return $e;
    snapshot_schema();
    $gaps = source_gaps();
    $facts = rows("SELECT f.fact, f.entity, f.target FROM ft_source_facts f JOIN (SELECT source, MAX(id) id FROM ft_source_snapshots GROUP BY source) l"
        . " ON l.source = f.source AND f.last_snapshot = l.id WHERE f.kind = 'go' AND f.fact IN ('drop', 'start', 'end')");
    $links = object_templates_links($facts, $gaps);
    unset($facts);
    // only the objects the server has no template for
    foreach (array_chunk(array_keys($links), 1000) as $chunk) {
        foreach (rows('SELECT entry FROM gameobject_template WHERE entry IN (' . implode(',', $chunk) . ')', [], 'world') as $r) unset($links[(int)$r['entry']]);
    }
    if (!$links) return ['ok' => false, 'id' => 0, 'counts' => [], 'ignored' => [],
        'message' => t('Every object a gap link names has a template on this server.', 'Chaque objet du monde qu’un lien de manque nomme a un modèle sur ce serveur.')];
    $icy = object_templates_answers('icyveins', 'api', 'gameobject', array_keys($links));
    $pages = object_templates_answers('wowhead', 'page', 'object', array_keys($links), 'forever');
    [$rows, $left] = object_templates_rows($links, $icy, $pages, (int)(meta()['client_build'] ?? 0));
    $newest = 0;
    foreach ($rows as $r) $newest = max($newest, (int)($icy[$r['entry']]['at'] ?? 0));
    $date = date('Y-m-d', $newest ?: time());
    $tables = [];
    if ($rows && table_exists('gameobject_template', 'world')) {
        $use = array_values(array_intersect(array_keys($rows[0]), import_columns('world', 'gameobject_template')));
        $tables['gameobject_template'] = ['db' => 'world', 'columns' => $use, 'groups' => [['columns' => $use, 'rows' => array_map(fn($r) => array_map(fn($c) => $r[$c], $use), $rows)]]];
    }
    $label = SOURCES['icyveins'][0] . ' ' . t('objects', 'objets du monde') . ' ' . $date;
    return source_card('icyveins', $label, 'icyveins-objects@' . $date . '-' . $newest, $tables, $left, [], 'icyveins-objects');
}
