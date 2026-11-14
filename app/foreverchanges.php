<?php
// Reference-only addon data, refreshed into ft_world_facts. Never an apply card.
require_once FT_APP . '/sources.php';

function foreverchanges_import(): array
{
    $python = (string)config('tools', 'python', PHP_OS_FAMILY === 'Windows' ? 'python' : 'python3');
    $command = escapeshellarg($python) . ' -X utf8 -u ' . escapeshellarg(FT_ROOT . '/tools/foreverchanges-import.py');
    // Use the same config selected by the website, including an external container config.
    putenv('FOREVER_TRACKER_CONFIG=' . config_path());
    passthru($command, $status);
    return ['ok' => $status === 0, 'message' => $status === 0
        ? t('ForeverChanges references loaded. Open a matching resource to review its evidence.', 'Références ForeverChanges chargées. Ouvrez une ressource correspondante pour examiner ses données.')
        : t('ForeverChanges refresh failed; see the log above. Previously loaded references remain available.', 'Échec de l’actualisation ForeverChanges ; consultez le journal ci-dessus. Les références précédentes restent disponibles.')];
}

function foreverchanges_status(): ?array
{
    return table_exists('ft_world_sources') ? row("SELECT * FROM ft_world_sources WHERE source = 'foreverchanges'") : null;
}

function foreverchanges_references(string $type, int $id): array
{
    if (!is_admin() || !table_exists('ft_world_facts')) return [];
    return rows("SELECT build, data FROM ft_world_facts WHERE source = 'foreverchanges' AND kind = 'reference' AND subject_kind = ? AND subject = ? ORDER BY build DESC", [$type, $id]);
}
