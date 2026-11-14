<?php
// GET api/tooltip/<type>/<id>: in-game tooltip data plus the server status, for the hover tooltips.
$type = $parts[2];
$id = (int)$parts[3];
if (!isset(TYPES[$type]) || !ready()) json_out(['error' => 'not found'], 404);
$entity = row('SELECT type, id, name, name_en, icon, quality, status, score, checks, is_new' . phase_column() . ' FROM ft_entities WHERE type = ? AND id = ?', [$type, $id]);
if (!$entity) json_out(['error' => 'not found'], 404);
$tip = table_exists('ft_tooltips') ? value('SELECT tip FROM ft_tooltips WHERE type = ? AND id = ?', [$type, $id]) : null;
$fails = array_map(fn($c) => check_label($c), failing_checks(json_decode($entity['checks'], true) ?: []));
header('Cache-Control: public, max-age=300');
json_out([
    'tip' => $tip ? json_decode($tip, true) : ['k' => $type, 'n' => ['fr' => $entity['name'], 'en' => $entity['name_en'] ?: $entity['name']]],
    'icon' => $entity['icon'] && !str_starts_with($entity['icon'], 'unknown_') ? icon_url($entity['icon'], 'large') : '',
    'type' => type_label($type),
    'status' => row_status($entity)[0],
    'statusLabel' => row_status($entity)[1],
    'phase' => is_later($entity) ? phase_title((int)$entity['phase']) : '',
    'score' => (int)$entity['score'],
    'fails' => $fails,
    'new' => (bool)$entity['is_new'],
]);
