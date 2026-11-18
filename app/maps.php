<?php
// Official zone maps for the Forge's Spawns page: where the locator's positions stand, drawn on the game's own map.
//
// The analysis (and the locator) write data/ui-maps.json from the client's UiMap tables (tools/ft/geo.py export):
// for every zone and continent map, the world rectangle each part of it draws. A world position (map, x, y) is put
// on the map of the zone it stands in; the picture itself is the game's map art as wago.tools generates it
// ([client] map_images), downloaded once per build and kept in data/maps.

const MAPS_IMAGES = 'https://wago.tools/api/map/{id}?product={product}&explored=1';   // with towns and roads
const MAPS_MAX_BYTES = 16 * 1024 * 1024;
const MAPS_RETRY_AFTER = 86400;   // a picture that could not be had is asked for again a day later

function maps_file(): string { return FT_ROOT . '/data/ui-maps.json'; }
function maps_dir(): string { return FT_ROOT . '/data/maps'; }

/** {'build': int|null, 'maps': {id: {'name', 'type', 'rects': [[map, x1, y1, x2, y2, u1, v1, u2, v2, area]]}}} or the empty set. */
function maps_ui(?string $path = null): array
{
    static $cache = [];
    $path ??= maps_file();
    if (!array_key_exists($path, $cache)) {
        $data = is_file($path) ? json_decode((string)file_get_contents($path), true) : null;
        $cache[$path] = is_array($data) && is_array($data['maps'] ?? null) ? $data : ['build' => null, 'maps' => []];
    }
    return $cache[$path];
}

/**
 * The map a world position is drawn on, and where: [ui map id, u, v] in 0..1, or null when no zone or continent map
 * holds it (dungeons, or a map the client draws no picture for). A zone map wins over a continent; of two zones, the
 * one whose part stands for the spawn's zone (AreaTable id) wins, then the smaller rectangle (a city over its zone).
 */
function maps_place(int $map, float $x, float $y, ?int $zone = null, ?array $ui = null): ?array
{
    $best = null;
    foreach (($ui ?? maps_ui())['maps'] as $id => $info) {
        foreach ($info['rects'] as $r) {
            [$m, $x1, $y1, $x2, $y2, $u1, $v1, $u2, $v2] = $r;
            if ((int)$m !== $map || $x < $x1 || $x > $x2 || $y < $y1 || $y > $y2 || $x2 <= $x1 || $y2 <= $y1) continue;
            $rank = [(int)$info['type'] === 3 ? 0 : 1, $zone && (int)($r[9] ?? 0) === $zone ? 0 : 1, ($x2 - $x1) * ($y2 - $y1)];
            if ($best !== null && $rank >= $best[0]) continue;
            $u = $u1 + ($y2 - $y) / ($y2 - $y1) * ($u2 - $u1);
            $v = $v1 + ($x2 - $x) / ($x2 - $x1) * ($v2 - $v1);
            $best = [$rank, [(int)$id, round($u, 5), round($v, 5)]];
        }
    }
    return $best[1] ?? null;
}

/**
 * The picture for a spawn's points: the map that holds most of them, with the points on it.
 * ['map' => id, 'name' => string, 'pins' => [[u, v], ...], 'elsewhere' => points on other maps] or null.
 * $points: the locator's [x, y, z, ...] on world map $map.
 */
function maps_pins(?int $map, array $points, ?int $zone = null, ?array $ui = null): ?array
{
    if ($map === null || !$points) return null;
    $ui ??= maps_ui();
    $on = [];
    foreach ($points as $p) {
        if (!is_array($p) || !isset($p[0], $p[1])) continue;
        $placed = maps_place($map, (float)$p[0], (float)$p[1], $zone, $ui);
        if ($placed) $on[$placed[0]][] = [$placed[1], $placed[2]];
    }
    if (!$on) return null;
    uasort($on, fn($a, $b) => count($b) <=> count($a));
    $id = (int)array_key_first($on);
    return ['map' => $id, 'name' => (string)($ui['maps'][$id]['name'] ?? ''), 'pins' => $on[$id],
            'elsewhere' => count($points) - count($on[$id])];
}

/** The address a map's picture comes from, or '' when pictures are off ([client] map_images = "off"). */
function maps_source(int $id): string
{
    $template = trim((string)config('client', 'map_images', ''));
    if ($template === 'off') return '';
    $product = trim((string)config('client', 'product', 'wowf')) ?: 'wowf';
    return strtr($template !== '' ? $template : MAPS_IMAGES, ['{id}' => (string)$id, '{product}' => rawurlencode($product)]);
}

/**
 * The cached picture of a zone map (a PNG file), downloaded on first use; null when it is not a map the client draws
 * or it cannot be had. $get: url -> [status, body] and $dir: the folder of pictures, for tests.
 */
function maps_image(int $id, ?callable $get = null, ?array $ui = null, ?string $dir = null): ?string
{
    $ui ??= maps_ui();
    if (!isset($ui['maps'][(string)$id])) return null;   // only the client's own maps: never an address from the request
    $folder = ($dir ?? maps_dir()) . '/' . ((int)($ui['build'] ?? 0) ?: 'any');
    $path = "$folder/$id.png";
    if (is_file($path)) return $path;
    $failed = "$folder/$id.failed";
    if (is_file($failed) && time() - (int)filemtime($failed) < MAPS_RETRY_AFTER) return null;
    $url = maps_source($id);
    if ($url === '') return null;
    [$status, $body] = ($get ?? 'maps_download')($url);
    @mkdir($folder, 0775, true);
    if ($status !== 200 || !is_string($body) || strlen($body) > MAPS_MAX_BYTES || strncmp($body, "\x89PNG\r\n\x1a\n", 8) !== 0) {
        @touch($failed);
        return null;
    }
    $scratch = "$path." . getmypid() . '.tmp';
    if (@file_put_contents($scratch, $body) === false || !@rename($scratch, $path)) { @unlink($scratch); return null; }
    @unlink($failed);
    return $path;
}

function maps_download(string $url): array
{
    $context = stream_context_create(['http' => ['timeout' => 30, 'ignore_errors' => true,
        'header' => "User-Agent: ForeverTracker/1.3 (private server admin tool)\r\nAccept: image/png\r\n"]]);
    $body = @file_get_contents($url, false, $context, 0, MAPS_MAX_BYTES + 1);
    $status = 0;
    foreach ($http_response_header ?? [] as $h) if (preg_match('#^HTTP/\S+ (\d+)#', $h, $m)) $status = (int)$m[1];
    return [$status, $body === false ? null : $body];
}

/** Answers admin/map?id=N with the picture (cached a week in the browser), or 404. */
function maps_serve(int $id): void
{
    $path = maps_image($id);
    if ($path === null) {
        http_response_code(404);
        header('Content-Type: text/plain; charset=utf-8');
        echo 'No map picture.';
        return;
    }
    header('Content-Type: image/png');
    header('Content-Length: ' . filesize($path));
    header('Cache-Control: private, max-age=604800');
    header('X-Content-Type-Options: nosniff');
    readfile($path);
}
