<?php
// Exercise the production template with synthetic data and no DB or web session.
$folder = sys_get_temp_dir() . '/ft-fc-' . bin2hex(random_bytes(8));
mkdir($folder);
file_put_contents($folder . '/foreverchanges.php', '<?php');
define('FT_APP', $folder);
function foreverchanges_references(string $type, int $id): array {
    return [
        // a record as an older load stored it (the pack's whole header on every record), and as it is stored now
        ['source' => 'foreverchanges', 'build' => 70888, 'data' => json_encode(['pack' => ['version' => 'fixture'],
            'archive_sha256' => str_repeat('a', 64), 'datasets' => ['item_hint' => [['hint' => '<script>alert(1)</script>']]]])],
        ['source' => 'foreverchanges', 'build' => 70888, 'data' => json_encode(['pack' => 'slim-fixture', 'datasets' => ['item_hint' => [['hint' => 'x']]]])],
        // read from a page: no build, the day it was read, a link only to the site itself
        ['source' => 'foreverchanges-pages', 'build' => 0, 'data' => json_encode(['read' => '2026-11-13', 'page' => 'https://foreverchanges.pro/item/100/fixture',
            'datasets' => ['item_page' => [['sources' => [['name' => '<b>Vendor</b>', 'price' => 901]]]]]])],
        ['source' => 'foreverchanges-pages', 'build' => 0, 'data' => json_encode(['read' => '2026-11-13', 'page' => 'javascript:alert(1)', 'datasets' => []])],
    ];
}
function foreverchanges_status(string $source = 'foreverchanges'): ?array { return ['pin' => 'feedfacefeedface']; }
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
        if (!str_contains($html, 'slim-fixture') || !str_contains($html, 'feedfacefeedface')) throw new RuntimeException('missing pack version or archive pin of a slim record');
        if (!str_contains($html, '2026-11-13') || !str_contains($html, $locale === 'en' ? 'The page names no build' : 'aucun build')) throw new RuntimeException('a page record must say when it was read and that it has no build');
        if (substr_count($html, 'href="https://foreverchanges.pro/item/100/fixture"') !== 1 || str_contains($html, 'javascript:')) throw new RuntimeException('only a link to the site itself may be shown');
        if (str_contains($html, '<b>Vendor</b>')) throw new RuntimeException('unescaped page text');
    }
    echo "ForeverChanges panel: escaped source text and provenance labels verified in English and French.\n";
} finally {
    unlink($folder . '/foreverchanges.php');
    rmdir($folder);
}
