<?php
// Forever Tracker: configuration, database, language, session and shared helpers.
declare(strict_types=1);

const FT_VERSION = '1.3.3';
define('FT_ROOT', dirname(__DIR__));
define('FT_APP', __DIR__);

/** The commit this copy was built from: the COMMIT file the Docker image carries (docs/DOCKER.md), '' without one. */
function build_commit(?string $file = null): string
{
    $commit = trim((string)@file_get_contents($file ?? FT_ROOT . '/COMMIT'));
    return preg_match('/^[0-9a-f]{7,64}$/i', $commit) ? strtolower($commit) : '';
}

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
ini_set('display_errors', '0');

// ------------------------------------------------------------------ configuration
function config_all(): array
{
    static $config = null;
    if ($config === null) {
        $path = config_path();
        if (!is_file($path)) {
            if (defined('FT_SETUP')) return $config = [];  // the setup wizard runs before there is a configuration
            if (PHP_SAPI !== 'cli' && setup_allowed_here()) { header('Location: ' . base_path() . 'setup', true, 302); exit; }
            fail_page('Configuration missing', 'Open /setup from this computer, or copy config.sample.ini to config.ini and fill in your database settings.');
        }
        $config = parse_ini_file($path, true, INI_SCANNER_TYPED) ?: [];
    }
    return $config;
}
function config(string $section, string $key, $default = null) { return config_all()[$section][$key] ?? $default; }
function config_path(): string { return getenv('FOREVER_TRACKER_CONFIG') ?: FT_ROOT . '/config.ini'; }
/** The setup wizard answers requests from this computer only (it can read and write the server's settings). */
function setup_allowed_here(): bool
{
    $ip = (string)($_SERVER['REMOTE_ADDR'] ?? '');
    return in_array($ip, ['127.0.0.1', '::1', '::ffff:127.0.0.1'], true) && empty($_SERVER['HTTP_X_FORWARDED_FOR']);
}

function fail_page(string $title, string $message, int $code = 500): void
{
    http_response_code($code);
    echo '<!doctype html><meta charset="utf-8"><title>' . htmlspecialchars($title) . '</title><body style="font:16px system-ui;background:#09090f;color:#e9e7f2;display:grid;place-items:center;min-height:100vh;margin:0">'
        . '<div style="max-width:520px;padding:32px;border:1px solid #2a2838;border-radius:16px;background:#12121b"><h1 style="margin-top:0;font-size:22px">' . htmlspecialchars($title) . '</h1><p style="color:#a7a4b8">' . htmlspecialchars($message) . '</p></div>';
    exit;
}

// ------------------------------------------------------------------ session and language
session_name('ft_session');
session_set_cookie_params(['lifetime' => 0, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax', 'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off']);
session_start();

/** The interface languages of [site] languages ("en,fr" by default; "en" or "fr" alone hides the switch). */
function languages(): array
{
    $list = array_values(array_intersect(array_map('trim', explode(',', (string)config('site', 'languages', 'en,fr'))), ['en', 'fr']));
    return $list ?: ['en', 'fr'];
}
function lang(): string
{
    static $lang = null;
    if ($lang !== null) return $lang;
    if (count(languages()) === 1) return $lang = languages()[0];
    $wanted = $_GET['lang'] ?? $_COOKIE['ft_lang'] ?? null;
    if (isset($_GET['lang']) && in_array($_GET['lang'], ['en', 'fr'], true)) {
        setcookie('ft_lang', $_GET['lang'], ['expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax']);
    }
    if (!in_array($wanted, ['en', 'fr'], true)) {
        $wanted = (string)config('site', 'default_language', 'en');
        if (!in_array($wanted, ['en', 'fr'], true)) $wanted = 'en';
    }
    return $lang = $wanted;
}
function fr(): bool { return lang() === 'fr'; }
/** English and French text: the visitor's language wins. */
function t(string $en, string $fr): string { return fr() ? $fr : $en; }
function e($value): string { return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8'); }
/** A {"en": …, "fr": …} value from the analysis (or a plain string) in the visitor's language. */
function tr($value): string
{
    if (is_array($value)) return (string)($value[lang()] ?? $value['fr'] ?? $value['en'] ?? '');
    return (string)$value;
}
function number($value, int $decimals = 0): string { return number_format((float)$value, $decimals, fr() ? ',' : '.', fr() ? ' ' : ','); }

// ------------------------------------------------------------------ URLs
function base_path(): string
{
    static $base = null;
    if ($base === null) {
        $script = str_replace('\\', '/', $_SERVER['SCRIPT_NAME'] ?? '/index.php');
        $base = rtrim(str_replace('\\', '/', dirname($script)), '/') . '/';  // dirname('/index.php') is '\' on Windows
    }
    return $base;
}
function url(string $path = '', array $query = []): string
{
    $query = array_filter($query, fn($v) => $v !== '' && $v !== null && $v !== false);
    return base_path() . ltrim($path, '/') . ($query ? '?' . http_build_query($query) : '');
}
function asset(string $path): string
{
    $file = FT_ROOT . '/public/assets/' . $path;
    return base_path() . 'assets/' . $path . '?v=' . (is_file($file) ? filemtime($file) : FT_VERSION);
}
function entry_url(string $type, int $id): string { return url($type . '/' . $id); }
function redirect(string $to): void { header('Location: ' . $to, true, 303); exit; }

// ------------------------------------------------------------------ database
function db(string $name = 'tracker'): mysqli
{
    static $links = [];
    if (!isset($links[$name])) {
        $database = (string)config('database', $name, $name);
        try {
            $link = new mysqli((string)config('database', 'host', '127.0.0.1'), (string)config('database', 'user', ''), (string)config('database', 'password', ''),
                $database, (int)config('database', 'port', 3306));
        } catch (mysqli_sql_exception $e) {
            error_log('Forever Tracker: ' . $e->getMessage());
            fail_page('Database unavailable', 'The tracker cannot reach its database. Check the [database] section of config.ini.');
        }
        $link->set_charset('utf8mb4');
        $links[$name] = $link;
    }
    return $links[$name];
}
/** Prepared statement on a database; returns every row. */
function rows(string $sql, array $params = [], string $database = 'tracker'): array
{
    $statement = db($database)->prepare($sql);
    if ($params) {
        $types = '';
        foreach ($params as $param) $types .= is_int($param) ? 'i' : (is_float($param) ? 'd' : 's');
        $statement->bind_param($types, ...$params);
    }
    $statement->execute();
    $result = $statement->get_result();
    $out = $result ? $result->fetch_all(MYSQLI_ASSOC) : [];
    $statement->close();
    return $out;
}
function row(string $sql, array $params = [], string $database = 'tracker'): ?array { return rows($sql, $params, $database)[0] ?? null; }
function value(string $sql, array $params = [], string $database = 'tracker')
{
    $first = row($sql, $params, $database);
    return $first ? reset($first) : null;
}
function table_exists(string $table, string $database = 'tracker'): bool
{
    static $cache = [];
    $key = $database . '.' . $table;
    if (!isset($cache[$key])) {
        $cache[$key] = (bool)value('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = ?', [$table], $database);
    }
    return $cache[$key];
}

/** What the last analysis says of itself (ft_meta). $use: a made-up one, for the tests. */
function meta(?array $use = null): array
{
    static $meta = null;
    if ($use !== null) $meta = $use;
    if ($meta !== null) return $meta;
    $meta = [];
    if (!table_exists('ft_meta')) return $meta;
    foreach (rows('SELECT k, v FROM ft_meta') as $r) $meta[$r['k']] = json_decode($r['v'], true);
    return $meta;
}
function ready(): bool { return meta() !== [] && table_exists('ft_entities'); }
function builds(): array
{
    static $builds = null;
    return $builds ??= ready() ? rows('SELECT build, version, released, note, source, is_server, counts FROM ft_builds' . (hotfix_entries() ? ' WHERE hotfix = 0' : '') . ' ORDER BY build DESC') : [];
}
/** The analysis keeps Blizzard's hotfixes as entries of their own (ft_builds.hotfix, ft_changes.hotfix: schema 5). */
function hotfix_entries(): bool { return (int)(meta()['schema'] ?? 0) >= 5; }
/**
 * The hotfix updates after their build, newest first: one for each day a new hotfix cache changed something
 * (tools/ft/hotfixes.py, docs/CLIENT.md). Rows of ft_builds with hotfix 1, 2, ...; released = the day it was read.
 */
function hotfix_updates(): array
{
    static $found = null;
    return $found ??= ready() && hotfix_entries() ? rows('SELECT build, hotfix, version, released, note, source, is_server, counts FROM ft_builds WHERE hotfix > 0 ORDER BY build DESC, hotfix DESC') : [];
}
/** SQL on ft_changes (alias like "c."): the changes of a build itself (0) or of one of its hotfix updates. */
function hotfix_is(int $hotfix, string $alias = ''): string { return hotfix_entries() ? " AND {$alias}hotfix = " . $hotfix : ''; }
/**
 * The days a hotfix entry covers, when the analysis dated it from the builds (tools/ft/dating.py): ['from', 'until',
 * 'days' (the hotfix days written notes name in it), 'rows', 'next' (the build that carried its hotfixes)], [] when not.
 */
function hotfix_window(array $update): array
{
    $found = (meta()['hotfix_windows'] ?? [])[(int)$update['build'] . ':' . (int)$update['hotfix']] ?? [];
    return is_array($found) ? $found : [];
}
/** "Hotfixes of Nov 15", or "Hotfixes of Nov 10–12" for an entry that covers several days. */
function hotfix_name(array $update, ?array $window = null): string
{
    $window ??= hotfix_window($update);
    $from = (string)($window['from'] ?? $update['released'] ?? ''); $until = (string)($window['until'] ?? $from);
    if ($from === '') return sprintf(t('Hotfixes of %s', 'Correctifs du %s'), '#' . (int)$update['hotfix']);
    $a = strtotime($from); $b = strtotime($until ?: $from);
    if ($until === '' || $until === $from || $b <= $a) return sprintf(t('Hotfixes of %s', 'Correctifs du %s'), date(t('M j', 'd/m'), $a));
    $same = date('Ym', $a) === date('Ym', $b);
    return sprintf(t('Hotfixes of %s–%s', 'Correctifs du %s au %s'), date(t('M j', 'd/m'), $a), $same && !fr() ? date('j', $b) : date(t('M j', 'd/m'), $b));
}
/**
 * What was written about the game day by day (tools/ft/notes.py, docs/CLIENT.md): Blizzard's blue posts first (its
 * hotfix notes, a day at a time, and its other posts), then Icy Veins' hotfix articles, then ForeverChanges' patch
 * notes where neither has the day.
 * ['days' => [day => ['blizzard' => ['sections', 'urls'], 'posts' => [ids], 'iv' => [['title', 'url', 'sections']],
 *   'fc' => note]], 'builds' => [build => note],
 * 'posts' => [id => post]]
 */
function timeline_notes(?string $folder = null): array
{
    static $cached = [];
    $folder ??= FT_ROOT . '/data/notes';
    if (isset($cached[$folder])) return $cached[$folder];
    $read = fn(string $file) => json_decode((string)@file_get_contents($folder . '/' . $file), true) ?: [];
    $notes = ['days' => [], 'builds' => [], 'posts' => []];
    $day = function (string $at) use (&$notes) {
        $notes['days'][$at] ??= ['blizzard' => ['sections' => [], 'urls' => []], 'posts' => [], 'iv' => [], 'ivBuild' => [], 'fc' => null];
    };
    foreach ((array)($read('blizzard.json')['posts'] ?? []) as $post) {
        if (!is_array($post) || empty($post['id'])) continue;
        $notes['posts'][(int)$post['id']] = $post;
        $posted = substr((string)($post['date'] ?? ''), 0, 10);
        if ($posted !== '') { $day($posted); $notes['days'][$posted]['posts'][] = (int)$post['id']; }
        if (empty($post['hotfixes'])) continue;
        // Blizzard edits its first post to hold every day and posts each day again: a line is kept once
        foreach ((array)($post['days'] ?? []) as $named) {
            $at = (string)($named['day'] ?? ''); if ($at === '') continue;
            $day($at);
            $into = &$notes['days'][$at]['blizzard'];
            if (!in_array($post['url'], $into['urls'], true)) $into['urls'][] = (string)$post['url'];
            foreach ((array)($named['sections'] ?? []) as $section) {
                $name = (string)($section['name'] ?? '');
                if (!isset($into['sections'][$name])) $into['sections'][$name] = [];
                foreach ((array)($section['lines'] ?? []) as $line) {
                    $text = (string)($line['text'] ?? '');
                    if ($text !== '' && !in_array($text, array_column($into['sections'][$name], 'text'), true)) $into['sections'][$name][] = ['text' => $text, 'mark' => (string)($line['mark'] ?? '')];
                }
            }
            unset($into);
        }
    }
    // Icy Veins' hotfix articles: Blizzard's notes as Icy Veins quoted them, a day at a time
    foreach ((array)($read('icyveins.json')['notes'] ?? []) as $article) {
        if (!is_array($article) || empty($article['day'])) continue;
        $named = (array)($article['days'] ?? []) ?: [['day' => $article['day'], 'sections' => []]];
        foreach ($named as $one) {
            $at = (string)($one['day'] ?? ''); if ($at === '') continue;
            $day($at);
            $sections = [];
            foreach ((array)($one['sections'] ?? []) as $section) $sections[(string)$section['name']] = (array)$section['lines'];
            // development and patch notes are a build's notes: shown with the build released that day, not as a hotfix day
            $notes['days'][$at][($article['kind'] ?? '') === 'build' ? 'ivBuild' : 'iv'][] = ['title' => (string)($article['title'] ?? ''), 'url' => (string)($article['url'] ?? ''), 'sections' => $sections];
        }
    }
    foreach ((array)($read('foreverchanges.json')['notes'] ?? []) as $note) {
        if (!is_array($note)) continue;
        if (($note['kind'] ?? '') === 'build' && !empty($note['build'])) $notes['builds'][(int)$note['build']] = $note;
        elseif (!empty($note['day'])) { $day((string)$note['day']); $notes['days'][(string)$note['day']]['fc'] = $note; }
    }
    ksort($notes['days']);
    return $cached[$folder] = $notes;
}
/** The days of a hotfix entry that something was written about, oldest first. */
function hotfix_days(array $update): array
{
    $window = hotfix_window($update);
    $from = (string)($window['from'] ?? $update['released'] ?? ''); $until = (string)($window['until'] ?? $from);
    if ($from === '') return [];
    $days = timeline_notes()['days'];
    // a day counts when something was written about it as such: a build's own notes alone do not make a hotfix day
    return array_values(array_filter(array_keys($days), fn($d) => $d >= $from && $d <= $until
        && ($days[$d]['blizzard']['sections'] || $days[$d]['iv'] || $days[$d]['fc'] || $days[$d]['posts'])));
}
/** Which source a day's notes come from: 'blizzard', 'iv' (Icy Veins), 'fc' (ForeverChanges) or '' when none has lines. */
function day_source(string $day): string
{
    $entry = timeline_notes()['days'][$day] ?? null;
    if (!$entry) return '';
    if ($entry['blizzard']['sections']) return 'blizzard';
    foreach ($entry['iv'] as $article) if ($article['sections']) return 'iv';
    return $entry['fc'] ? 'fc' : '';
}
/** A day's notes as sections [name => [['text', 'mark']]]: Blizzard's when it posted them, else Icy Veins', else ForeverChanges'. */
function day_sections(string $day): array
{
    $entry = timeline_notes()['days'][$day] ?? null;
    if (!$entry) return [];
    if ($entry['blizzard']['sections']) return $entry['blizzard']['sections'];
    $out = [];
    foreach ($entry['iv'] as $article) foreach ($article['sections'] as $name => $lines) {
        foreach ($lines as $line) if (!in_array($line['text'] ?? '', array_column($out[$name] ?? [], 'text'), true)) $out[$name][] = $line;
    }
    if ($out) return $out;
    foreach ((array)($entry['fc']['sections'] ?? []) as $section) $out[(string)$section['name']] = (array)$section['lines'];
    return $out;
}
/** The topics of some days' notes, most lines first: ['Classes' => 41, 'Items' => 10, ...]. */
/**
 * Headings that say how a post is laid out, not what part of the game changed: no topic on a card. A heading-less post
 * ('Notes'), a change log, known or fixed issues, forum rules, and a sentence in bold (it ends in a stop or a colon).
 */
const NOTES_NOT_TOPICS = '/^(notes|general|change ?log|changes and updates|bug ?fixes|resolved issues|what blizzard said too|customer support|how to\\b.*)$|known issues|new to this build|[.:!?]\\s*$/iu';
function notes_topics(array $days): array
{
    $count = [];
    foreach ($days as $day) foreach (day_sections($day) as $name => $lines) {
        if (mb_strlen((string)$name) > 32 || preg_match(NOTES_NOT_TOPICS, (string)$name)) continue;
        $count[$name] = ($count[$name] ?? 0) + count($lines);
    }
    arsort($count);
    return $count;
}
/** A build of the beta: stored from a product of that name (tools/ft/client.py, history). */
function build_is_beta(array $build): bool
{
    return stripos((string)($build['source'] ?? ''), 'beta') !== false;
}
/**
 * The original game as the changelog's start (tools/ft/vanilla.py, docs/VANILLA.md): ['build', 'version', 'first' (the
 * game's first build, compared with it), 'hidden', 'alone'], [] when it is not stored.
 */
function baseline(): array
{
    $found = meta()['baseline'] ?? [];
    return is_array($found) && !empty($found['build']) ? $found : [];
}
function build_is_vanilla(array $build): bool { return baseline() && (int)($build['build'] ?? 0) === (int)baseline()['build']; }
/** A build compared with the original game: the game's first build, when the original game is stored. */
function from_vanilla(int $build): bool { return baseline() && $build === (int)baseline()['first']; }
/** "build 70938", or "the original game" for what patch 1.12 already had. */
function build_name(int $build): string
{
    return baseline() && $build === (int)baseline()['build'] ? t('the original game (1.12)', 'le jeu d’origine (1.12)') : t('build', 'build') . ' ' . $build;
}
/**
 * A change's word on the page of a build. Against the original game "removed" cannot be said: what the original game
 * had and WoW: Forever's data does not is what Blizzard took out, and also what is not released yet.
 */
function change_label(string $kind, int $build): string
{
    return $kind === 'removed' && from_vanilla($build) ? t('Not in Forever', 'Absent de Forever') : kind_label($kind);
}
/** SQL on ft_changes (alias like "c."): the removals worth showing, once the analysis marks the others. */
function changes_shown(string $alias = ''): string { return (int)(meta()['schema'] ?? 0) >= 4 ? " AND {$alias}internal = 0" : ''; }

// ------------------------------------------------------------------ resource types
/** type => [path, icon, English, French, English description, French description, Wowhead kind] */
const TYPES = [
    'dungeon' => ['dungeons', 'fa-dungeon', 'Dungeons & raids', 'Donjons & raids', 'Instances, battlegrounds and arenas of the official client.', 'Instances, champs de bataille et arènes du client officiel.', null],
    'boss' => ['bosses', 'fa-skull', 'Bosses', 'Boss', 'Every boss encounter of every instance.', 'Chaque rencontre de boss de chaque instance.', null],
    'zone' => ['zones', 'fa-map', 'Zones', 'Zones', 'Open-world zones: creatures, quests, graveyards.', 'Zones du monde : PNJ, quêtes, cimetières.', 'zone'],
    'quest' => ['quests', 'fa-scroll', 'Quests', 'Quêtes', 'Official quests and whether they can be done.', 'Les quêtes officielles et leur faisabilité.', 'quest'],
    'item' => ['items', 'fa-gem', 'Items', 'Objets', 'Every item and how players obtain it.', 'Chaque objet et sa source d’obtention.', 'item'],
    'spell' => ['spells', 'fa-wand-sparkles', 'Spells', 'Sorts', 'Class, racial, profession and mount spells.', 'Sorts de classe, raciaux, de métier et de monture.', 'spell'],
    'talent' => ['talents', 'fa-sitemap', 'Talents', 'Talents', 'Talent trees and their ranks.', 'Arbres de talents et leurs rangs.', 'spell'],
    'recipe' => ['recipes', 'fa-hammer', 'Recipes', 'Recettes', 'Profession recipes and how they are learned.', 'Recettes de métier et leur apprentissage.', 'spell'],
    'mount' => ['mounts', 'fa-horse', 'Mounts', 'Montures', 'The mount collection.', 'La collection de montures.', 'spell'],
    'pet' => ['pets', 'fa-paw', 'Pets', 'Mascottes', 'Companion pets.', 'Mascottes de compagnie.', 'spell'],
    'toy' => ['toys', 'fa-puzzle-piece', 'Toys', 'Jouets', 'The toy box.', 'Le coffre à jouets.', 'item'],
    'achievement' => ['achievements', 'fa-trophy', 'Achievements', 'Hauts faits', 'Achievements and their rewards.', 'Hauts faits et leurs récompenses.', 'achievement'],
    'taxi' => ['flights', 'fa-feather', 'Flight points', 'Points de vol', 'Flight paths and their flight masters.', 'Trajets aériens et maîtres de vol.', null],
];
const PRIORITY = ['dungeon', 'boss', 'zone', 'quest', 'taxi', 'talent', 'spell', 'recipe', 'mount', 'pet', 'toy', 'achievement', 'item'];
function type_label(string $type): string { return isset(TYPES[$type]) ? t(TYPES[$type][2], TYPES[$type][3]) : $type; }
function type_desc(string $type): string { return isset(TYPES[$type]) ? t(TYPES[$type][4], TYPES[$type][5]) : ''; }
function type_url(string $type, array $query = []): string { return url(TYPES[$type][0] ?? '', $query); }
/** Category written by the analysis (class, profession, Donjon, Raid…) in the visitor's language. */
function sub_label(string $sub): string
{
    $labels = ['class' => t('Class', 'Classe'), 'profession' => t('Profession', 'Métier'), 'racial' => t('Racial', 'Racial'), 'talent' => 'Talent',
        'mount' => t('Mount', 'Monture'), 'pet' => t('Pet', 'Mascotte'), 'rune' => t('Rune engraving', 'Gravure de rune'), 'petability' => t('Pet ability', 'Technique de familier'),
        'item' => t('Item use', 'Utilisation d’objet'), 'other' => t('Other', 'Autre'), 'Monture' => t('Mount', 'Monture'), 'Mascotte' => t('Pet', 'Mascotte'), 'Jouet' => t('Toy', 'Jouet'),
        'Donjon' => t('Dungeon', 'Donjon'), 'Raid' => 'Raid', 'Champ de bataille' => t('Battleground', 'Champ de bataille'), 'Arène' => t('Arena', 'Arène')];
    return $labels[$sub] ?? $sub;
}
function status_label(string $status): string
{
    return ['ok' => t('Available', 'Disponible'), 'partial' => t('Incomplete', 'Incomplet'), 'missing' => t('Missing', 'Manquant')][$status] ?? $status;
}
function status_badge(string $status, ?int $score = null): string
{
    return '<span class="badge is-' . e($status) . '"><i></i>' . e(status_label($status)) . ($score !== null && $status === 'partial' ? ' <b>' . $score . '%</b>' : '') . '</span>';
}

// ------------------------------------------------------------------ release phases (docs/PHASES.md)
/** The release phases of the last analysis, numbered from 1: [n => ['key', 'name', 'opens', 'source', 'counts']]. */
function phases(): array
{
    static $list = null;
    if ($list !== null) return $list;
    $list = [];
    foreach (array_values((array)(meta()['phases'] ?? [])) as $i => $p) if (is_array($p) && isset($p['key'])) $list[$i + 1] = $p;
    return $list;
}
/** Numbers of the phases not open yet. [phases] current decides when set: "all", "none", or a phase key or number that
 *  opens it and every phase before it. Otherwise each phase opens on its own date; one with no date stays closed and
 *  does not hold back a later one that has a date. */
function closed_phases(): array
{
    static $closed = null;
    if ($closed !== null) return $closed;
    $list = phases();
    // config.ini is read with INI_SCANNER_TYPED: an unquoted none / off / no arrives as false, yes / on / true as true
    $raw = config('phases', 'current', '');
    $current = $raw === false ? 'none' : ($raw === true ? '' : strtolower(trim((string)$raw)));
    $upTo = null;
    if ($current === 'all') $upTo = count($list);
    elseif ($current === 'none') $upTo = 0;
    elseif ($current !== '' && ctype_digit($current)) $upTo = min((int)$current, count($list));
    elseif ($current !== '') {
        foreach ($list as $n => $p) if (strtolower((string)$p['key']) === $current) $upTo = $n;
        if ($upTo === null) error_log("Forever Tracker: [phases] current = \"$current\" names no phase; the phases' dates decide");
    }
    $today = date('Y-m-d');
    $closed = [];
    foreach ($list as $n => $p) {
        $open = $upTo !== null ? $n <= $upTo : (!empty($p['opens']) && (string)$p['opens'] <= $today);
        if (!$open) $closed[] = $n;
    }
    return $closed;
}
/** ", phase" for SELECT lists, once an analysis has written the column (schema 3). */
function phase_column(string $alias = ''): string { return (int)(meta()['schema'] ?? 0) >= 3 ? ", {$alias}phase" : ''; }
function phases_pending(): bool { return closed_phases() !== []; }
/** The resource waits for a phase that is not open yet (and the server does not provide it already). */
function is_later(array $row): bool { return in_array((int)($row['phase'] ?? 0), closed_phases(), true) && ($row['status'] ?? '') !== 'ok'; }
/** SQL conditions on ft_entities (alias like "e."): open now, or waiting for a phase not open yet. */
function released_sql(string $alias = ''): string { return phases_pending() ? "{$alias}phase NOT IN (" . implode(',', closed_phases()) . ')' : '1'; }
function later_sql(string $alias = ''): string { return phases_pending() ? "{$alias}phase IN (" . implode(',', closed_phases()) . ')' : '0'; }
function phase_when(array $p): string
{
    return !empty($p['opens']) ? sprintf(t('opens %s', 'ouvre le %s'), date(t('M j, Y', 'd/m/Y'), strtotime((string)$p['opens']))) : t('date not announced', 'date non annoncée');
}
function phase_title(int $n): string
{
    $p = phases()[$n] ?? null;
    return $p ? (string)$p['name'] . ' · ' . phase_when($p) : '';
}
/** status_badge(), or a "Later" badge naming the phase for what a later phase opens. */
function row_badge(array $row, bool $score = true): string
{
    if (!is_later($row)) return status_badge((string)$row['status'], $score ? (int)$row['score'] : null);
    $name = (string)(phases()[(int)$row['phase']]['name'] ?? '');
    return '<span class="badge is-later" title="' . e(t('Later', 'Plus tard') . ' · ' . phase_title((int)$row['phase'])) . '"><i class="fas fa-hourglass-half"></i>' . e($name !== '' ? $name : t('Later', 'Plus tard')) . '</span>';
}
/** [status, label] for the JSON APIs: "later" for what a later phase opens. */
function row_status(array $row): array { return is_later($row) ? ['later', t('Later', 'Plus tard')] : [(string)$row['status'], status_label((string)$row['status'])]; }
function kind_label(string $kind): string
{
    return ['added' => t('Added', 'Ajouté'), 'modified' => t('Changed', 'Modifié'), 'removed' => t('Removed', 'Supprimé')][$kind] ?? $kind;
}

/** Check codes of the analysis: label and how to fix a failure. */
function check_info(string $code): array
{
    $info = [
        'core' => [t('Known to the core', 'Connu du core'), t('The server data lacks it: copy the official record with the Forge (hotfixes), or re-extract the current client DB2 into the server data.', 'Les données du serveur ne l’ont pas : copiez l’enregistrement officiel avec la Forge (hotfixes), ou ré-extrayez les DB2 du client actuel dans les données du serveur.')],
        'source' => [t('Obtainable in game', 'Obtenable en jeu'), t('Give it a source: creature or object loot, npc_vendor (the Forge can add it to a vendor), a quest reward or a learnable craft.', 'Donnez-lui une source : butin de PNJ ou d’objet, npc_vendor (la Forge peut l’ajouter à un marchand), une récompense de quête ou un artisanat apprenable.')],
        'contents' => [t('Has contents', 'A un contenu'), t('Give the item item_loot_template rows, or money in item_template_addon (MinMoneyLoot, MaxMoneyLoot).', 'Donnez à l’objet des lignes item_loot_template, ou de l’argent dans item_template_addon (MinMoneyLoot, MaxMoneyLoot).')],
        'price' => [t('Price kept', 'Prix conservé'), t('Set the free vendor row’s ExtendedCost to the cost the other vendors ask.', 'Mettez sur la ligne gratuite l’ExtendedCost que demandent les autres marchands.')],
        'learn' => [t('Learnable', 'Apprenable'), t('Teach it at a spawned trainer (the Forge does it), reward it from a quest (RewardSpell) or make its recipe item obtainable.', 'Enseignez-le chez un entraîneur placé (la Forge le fait), en récompense de quête (RewardSpell) ou rendez son objet-recette obtenable.')],
        'script' => [t('Spell script', 'Script du sort'), t('Its dummy or script effect does nothing until code runs it: write a SpellScript and bind it in spell_script_names, or handle the spell in the core. A check named by the core’s C++ may be another use of the id: test it in game.', 'Son effet « dummy » ou « script » ne fait rien tant qu’aucun code ne l’exécute : écrivez un SpellScript et liez-le dans spell_script_names, ou gérez le sort dans le core. Un sort nommé par le C++ du core peut l’être pour un autre usage : testez-le en jeu.')],
        'proc' => [t('Procs', 'Déclenchement'), t('The aura acts only when it procs: add a spell_proc row for it (ProcFlags, chance): the core builds a proc only from that row or the client’s SpellAuraOptions.ProcTypeMask.', 'L’aura n’agit que lorsqu’elle se déclenche : ajoutez-lui une ligne spell_proc (ProcFlags, chance) : le core ne construit un déclenchement qu’à partir de cette ligne ou de SpellAuraOptions.ProcTypeMask du client.')],
        'ranks' => [t('Rank spells known', 'Rangs connus'), t('The server lacks some rank spells: copy them with the Forge or update the server DB2.', 'Le serveur n’a pas certains sorts de rang : copiez-les avec la Forge ou mettez à jour les DB2 du serveur.')],
        'talent_script' => [t('Script', 'Script'), t('A rank’s dummy or script effect does nothing until code runs it: write a SpellScript and bind it in spell_script_names, or handle the spell in the core.', 'L’effet « dummy » ou « script » d’un rang ne fait rien tant qu’aucun code ne l’exécute : écrivez un SpellScript et liez-le dans spell_script_names, ou gérez le sort dans le core.')],
        'quest_row' => [t('Quest data', 'Données de quête'), t('The core has no quest_template row: create the quest (title, objectives, rewards), quest_objectives and its giver and ender.', 'Le core n’a pas de ligne quest_template : créez la quête (titre, objectifs, récompenses), quest_objectives et ses donneur et valideur.')],
        'starter' => [t('Quest giver', 'Donneur de quête'), t('Link a spawned creature or object in creature_queststarter / gameobject_queststarter.', 'Liez un PNJ ou objet placé dans creature_queststarter / gameobject_queststarter.')],
        'ender' => [t('Quest ender', 'Valideur de quête'), t('Link a spawned creature or object in creature_questender / gameobject_questender.', 'Liez un PNJ ou objet placé dans creature_questender / gameobject_questender.')],
        'objectives' => [t('Objectives achievable', 'Objectifs réalisables'), t('Spawn the objective targets, or give the required items a source (creature_questitem, loot).', 'Placez les cibles des objectifs, ou donnez une source aux objets requis (creature_questitem, butin).')],
        'enabled' => [t('Enabled', 'Activé'), t('Remove the entry from the disables table once it is ready.', 'Retirez l’entrée de la table disables quand le contenu est prêt.')],
        'terrain' => [t('Terrain extracted', 'Terrain extrait'), t('Run mapextractor and the vmap tools on the current client, then copy maps and vmaps to the server data.', 'Lancez mapextractor et les outils vmap sur le client actuel, puis copiez maps et vmaps dans les données du serveur.')],
        'mmaps' => [t('Navigation (mmaps)', 'Navigation (mmaps)'), t('Generate the navigation mesh with mmaps_generator for this map.', 'Générez le maillage de navigation avec mmaps_generator pour cette carte.')],
        'instance_template' => ['instance_template', t('Add the instance_template row so the instance can be created (the Forge does it).', 'Ajoutez la ligne instance_template pour que l’instance puisse être créée (la Forge le fait).')],
        'entrance' => [t('Entrance', 'Entrée'), t('Add an areatrigger_teleport pointing to a world_safe_locs entry inside this map.', 'Ajoutez un areatrigger_teleport vers une entrée world_safe_locs dans cette carte.')],
        'battleground' => [t('Battleground declared', 'Champ de bataille déclaré'), t('Declare it in battleground_template.', 'Déclarez-le dans battleground_template.')],
        'spawns' => [t('Creatures spawned', 'PNJ placés'), t('Spawn the creatures (creature table): The Forge › Spawns finds where they stand.', 'Placez les créatures (table creature) : La Forge › Placements trouve où elles se trouvent.')],
        'bosses' => [t('Bosses present', 'Boss présents'), t('Spawn each boss of the instance; the Bosses page lists the missing ones.', 'Placez chaque boss de l’instance ; la page Boss liste ceux qui manquent.')],
        'boss_spawn' => [t('Boss spawned', 'Boss placé'), t('Create or reuse the boss creature_template and spawn it in the instance.', 'Créez ou réutilisez le creature_template du boss et placez-le dans l’instance.')],
        'boss_script' => [t('Scripted fight', 'Combat scripté'), t('Give the boss its mechanics: a C++ ScriptName or SmartAI.', 'Donnez ses mécaniques au boss : un ScriptName C++ ou SmartAI.')],
        'texts' => [t('Quest text', 'Texte de quête'), t('Write the missing text: quest_template (QuestDescription, LogDescription), quest_offer_reward (RewardText) or quest_request_items (CompletionText).', 'Écrivez le texte manquant : quest_template (QuestDescription, LogDescription), quest_offer_reward (RewardText) ou quest_request_items (CompletionText).')],
        'side' => [t('Offered to the right side', 'Proposée au bon camp'), t('Compare quest_template.AllowableRaces with the side players of the live game got the quest on (their reports, Imports › ForeverChanges). Nothing changes it by itself: a server may offer a quest more widely on purpose.', 'Comparez quest_template.AllowableRaces avec le camp pour lequel les joueurs ont eu la quête en jeu (leurs rapports, Imports › ForeverChanges). Rien ne le modifie tout seul : un serveur peut proposer une quête plus largement exprès.')],
        'boss_placed' => [t('Placed by a script', 'Placé par un script'), t('Enter the instance and see that the boss appears; when the core’s scripts change, run tools/make_summoned.py again.', 'Entrez dans l’instance et vérifiez que le boss apparaît ; quand les scripts du core changent, relancez tools/make_summoned.py.')],
        'zone_quests' => [t('Zone quests', 'Quêtes de la zone'), t('Open the quests of this zone filtered “To do” to see what blocks them.', 'Ouvrez les quêtes de la zone filtrées « À faire » pour voir ce qui les bloque.')],
        'graveyard' => [t('Graveyard', 'Cimetière'), t('Add a graveyard_zone row linking a graveyard (world_safe_locs) to this zone.', 'Ajoutez une ligne graveyard_zone reliant un cimetière (world_safe_locs) à cette zone.')],
        'reward' => [t('Reward', 'Récompense'), t('Add the title or item in achievement_reward.', 'Ajoutez le titre ou l’objet dans achievement_reward.')],
        'flightmaster' => [t('Flight master spawned', 'Maître de vol placé'), t('Spawn a flight master (npcflag 8192) next to the node.', 'Placez un maître de vol (npcflag 8192) près du point.')],
        'obtainable' => [t('Obtainable', 'Obtenable'), t('Sell or drop the item that teaches it (the Forge can add it to a vendor), or teach it at a trainer.', 'Vendez ou faites tomber l’objet qui l’apprend (la Forge peut l’ajouter à un marchand), ou enseignez-le chez un entraîneur.')],
    ];
    return $info[$code] ?? [$code, ''];
}
function check_label(array $check): string { return isset($check['code']) ? check_info($check['code'])[0] : (string)($check['label'] ?? ''); }
function failing_checks(array $checks): array { return array_values(array_filter($checks, fn($c) => !$c['ok'] && (float)$c['w'] > 0)); }

/** Resources whose French or English name contains $q (or with that ID), best matches first. */
function search_entities(string $q, int $limit = 40): array
{
    if ($q === '' || !ready()) return [];
    if (ctype_digit($q)) {
        return rows("SELECT type, id, name, name_en, icon, quality, status, score, internal, is_new" . phase_column() . " FROM ft_entities WHERE id = ? ORDER BY internal, FIELD(type,'dungeon','zone','quest','item','spell') LIMIT ?", [(int)$q, $limit]);
    }
    $like = '%' . addcslashes($q, '%_\\') . '%';
    return rows("SELECT type, id, name, name_en, icon, quality, status, score, internal, is_new" . phase_column() . ", (name = ? OR name_en = ?) exact, (name LIKE ? OR name_en LIKE ?) prefix
        FROM ft_entities WHERE (name LIKE ? OR name_en LIKE ?) ORDER BY internal, exact DESC, prefix DESC,
        FIELD(type,'dungeon','boss','zone','quest','mount','pet','toy','talent','recipe','spell','item','achievement','taxi'), CHAR_LENGTH(name) LIMIT ?",
        [$q, $q, addcslashes($q, '%_\\') . '%', addcslashes($q, '%_\\') . '%', $like, $like, $limit]);
}

// ------------------------------------------------------------------ icons
function icon_url(string $icon, string $size = 'medium'): string
{
    return 'https://wow.zamimg.com/images/wow/icons/' . $size . '/' . rawurlencode(strtolower($icon)) . '.jpg';
}
/** The icon of a resource; hovering it shows the in-game tooltip. */
function icon_html(array $row, string $type, string $size = 'medium', bool $tooltip = true): string
{
    $quality = (int)($row['quality'] ?? -1);
    $class = 'ic' . ($size === 'large' ? ' is-large' : '') . ($quality >= 0 ? ' q' . $quality : '');
    $attr = $tooltip && isset($row['id']) ? ' data-tt="' . e($type . ':' . (int)$row['id']) . '"' : '';
    $glyph = '<i class="fas ' . e(TYPES[$type][1] ?? 'fa-circle') . '" aria-hidden="true"></i>';
    if (!empty($row['icon']) && !str_starts_with((string)$row['icon'], 'unknown_')) {
        return '<span class="' . $class . '"' . $attr . '><img src="' . e(icon_url((string)$row['icon'], $size)) . '" alt="" loading="lazy" onerror="this.remove()">' . $glyph . '</span>';
    }
    return '<span class="' . $class . ' is-glyph"' . $attr . '>' . $glyph . '</span>';
}
function wowhead_url(string $type, array $row): ?string
{
    $kind = TYPES[$type][6] ?? null;
    $data = is_array($row['data'] ?? null) ? $row['data'] : (json_decode((string)($row['data'] ?? '{}'), true) ?: []);
    $id = (int)$row['id'];
    if ($type === 'talent') $id = (int)($data['ranks'][0] ?? 0);
    if (in_array($type, ['mount', 'pet'], true)) $id = (int)($data['spell'] ?? 0);
    if ($type === 'toy') $id = (int)($data['item'] ?? 0);
    if (!$kind || !$id) return null;
    return 'https://www.wowhead.com/forever/' . (fr() ? 'fr/' : '') . $kind . '=' . $id;
}
/** A resource's name in the visitor's language (the other language when it has no translation). */
function display_name(array $row): string
{
    $fr = (string)($row['name'] ?? ''); $en = (string)($row['name_en'] ?? '');
    $name = fr() ? ($fr ?: $en) : ($en ?: $fr);
    return $name !== '' ? $name : '#' . (int)($row['id'] ?? 0);
}
/** The name in the other language, or '' when it is the same. */
function other_name(array $row): string
{
    $other = fr() ? (string)($row['name_en'] ?? '') : (string)($row['name'] ?? '');
    return $other !== '' && $other !== display_name($row) ? $other : '';
}
/** Name link with the resource's tooltip. */
function name_link(array $row, string $type): string
{
    $quality = $type === 'item' || $type === 'toy' ? ' q' . (int)($row['quality'] ?? 1) : '';
    return '<a class="name' . $quality . '" href="' . e(entry_url($type, (int)$row['id'])) . '" data-tt="' . e($type . ':' . (int)$row['id']) . '">' . e(display_name($row)) . '</a>';
}
function ring(int $percent, int $size = 120, string $class = ''): string
{
    $radius = 52; $circumference = 2 * M_PI * $radius;
    return '<svg class="ring ' . e($class) . '" viewBox="0 0 120 120" width="' . $size . '" height="' . $size . '" role="img" aria-label="' . $percent . '%">'
        . '<circle cx="60" cy="60" r="' . $radius . '" class="ring-track"/>'
        . '<circle cx="60" cy="60" r="' . $radius . '" class="ring-value" stroke-dasharray="' . round($circumference * $percent / 100, 1) . ' ' . round($circumference, 1) . '"/></svg>';
}

// ------------------------------------------------------------------ administrators
function admin(): ?array
{
    static $checked = false;
    if (($_SESSION['ft_admin']['via'] ?? '') === 'website' && !defined('FT_HOST_IDENTITY')) {
        unset($_SESSION['ft_admin']);  // logged out of the website
    }
    if (empty($_SESSION['ft_admin']) && !$checked && defined('FT_HOST_IDENTITY')) {
        // Mounted in a website (e.g. Forever CMS) whose logged-in staff are administrators here too.
        $checked = true;
        $host = FT_HOST_IDENTITY;
        $account = row('SELECT id FROM account WHERE id = ? AND username = ?', [(int)$host['account'], (string)$host['username']], 'auth');
        if ($account) {
            $level = (int)value('SELECT MAX(SecurityLevel) FROM account_access WHERE AccountID = ?', [(int)$account['id']], 'auth');
            if (!empty($host['site_admin']) || $level >= (int)config('admin', 'gm_level', 3)) {
                $_SESSION['ft_admin'] = ['name' => (string)$host['name'], 'via' => 'website', 'level' => $level];
            }
        }
    }
    return $_SESSION['ft_admin'] ?? null;
}
function is_admin(): bool { return admin() !== null; }
/** A private tracker ([site] public = 0) seen by a visitor who is not an administrator: only the login page shows,
 *  and nothing of the analysis with it (no coverage, no build numbers, no dates, no API answers). */
function site_private(): bool { return !config('site', 'public', 1) && !is_admin(); }
function require_admin(): void
{
    if (!is_admin()) redirect(url('login', ['next' => $_SERVER['REQUEST_URI'] ?? '']));
}
function csrf_token(): string
{
    if (empty($_SESSION['ft_csrf'])) $_SESSION['ft_csrf'] = bin2hex(random_bytes(32));
    return $_SESSION['ft_csrf'];
}
function csrf_ok(?string $token): bool { return is_string($token) && hash_equals(csrf_token(), $token); }
function json_out($data, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    // logs of tools may hold bytes of the console code page: substitute them instead of failing silently
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}
