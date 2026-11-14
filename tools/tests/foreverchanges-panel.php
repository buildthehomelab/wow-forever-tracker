<?php
// Exercise the production template with synthetic data and no DB or web session.
$folder = sys_get_temp_dir() . '/ft-fc-' . bin2hex(random_bytes(8));
mkdir($folder);
file_put_contents($folder . '/foreverchanges.php', '<?php');
define('FT_APP', $folder);
function foreverchanges_references(string $type, int $id): array {
    return [['build' => 70888, 'data' => json_encode(['pack' => ['version' => 'fixture'],
        'archive_sha256' => str_repeat('a', 64), 'datasets' => ['item_hint' => [['hint' => '<script>alert(1)</script>']]]])]];
}
function t(string $en, string $fr): string { return ($GLOBALS['locale'] ?? 'en') === 'fr' ? $fr : $en; }
function e($value): string { return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8'); }
function meta(): array { return ['client_build' => 70938]; }
$type = 'item'; $id = 100;
try {
    foreach (['en', 'fr'] as $locale) {
        ob_start();
        require dirname(__DIR__, 2) . '/app/pages/admin/_foreverchanges.php';
        $html = ob_get_clean();
        if (str_contains($html, '<script>') || !str_contains($html, '&lt;script&gt;')) throw new RuntimeException('unescaped source text');
        if (!str_contains($html, '70888') || !str_contains($html, 'fixture')) throw new RuntimeException('missing pack provenance');
        if (!str_contains($html, $locale === 'en' ? 'Different from the current analysis build' : 'Différent du build')) throw new RuntimeException('missing build mismatch label');
    }
    echo "ForeverChanges panel: escaped source text and provenance labels verified in English and French.\n";
} finally {
    unlink($folder . '/foreverchanges.php');
    rmdir($folder);
}
