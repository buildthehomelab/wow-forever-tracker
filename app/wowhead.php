<?php
// Wowhead's public Forever tooltips from PHP, sharing the analysis' cache (data/wowhead/<kind>/<id>.json, the format
// of tools/ft/wowhead.py), politely: one request at a time, a pause between requests, every answer kept.
//
//   wowhead_spell_level(id)     "Requires level N" of a spell (trainer rows NorgannonDB gives no level for)
//   wowhead_quest_import()      quest enders named in Wowhead's quest summaries ("... then return to Hamish Bergwort
//                               in the Tower of Azora"), as an import card, for quests the server has no ender for
require_once FT_APP . '/imports.php';

const WOWHEAD_PAUSE = 0.4;        // seconds between requests
const WOWHEAD_MAX_ASK = 500;      // new requests per run (a web request must end); the cache makes the next run go on

/** Tooltip data, ['missing' => true] when Wowhead does not know it, null when not cached and not asked (or unreachable). */
function wowhead_get(string $kind, int $id, bool $ask = true): ?array
{
    static $last = 0.0, $asked = 0;
    $path = FT_ROOT . "/data/wowhead/$kind/$id.json";
    if (is_file($path)) {
        $data = json_decode((string)file_get_contents($path), true) ?: null;
        // "Wowhead does not know it" expires ([wowhead] recheck_days): Wowhead learns what players discover
        $stale = $data && !empty($data['missing']) && time() - (int)($data['fetched'] ?? 0) > (float)(config('wowhead', 'recheck_days', 7) ?: 7) * 86400;
        if (!$stale || !$ask) return $data;
    }
    if (!$ask || $asked >= WOWHEAD_MAX_ASK) return null;
    $wait = WOWHEAD_PAUSE - (microtime(true) - $last);
    if ($wait > 0) usleep((int)($wait * 1e6));
    $last = microtime(true); $asked++;
    $context = stream_context_create(['http' => ['timeout' => 20, 'ignore_errors' => true,
        'header' => "User-Agent: ForeverTracker/1.1 (private server admin tool)\r\nAccept: application/json\r\n"]]);
    $body = @file_get_contents('https://nether.wowhead.com/' . (config('wowhead', 'branch', 'forever') ?: 'forever') . "/tooltip/$kind/$id?locale=0", false, $context);
    $status = 0;
    foreach ($http_response_header ?? [] as $h) if (preg_match('#^HTTP/\S+ (\d+)#', $h, $m)) $status = (int)$m[1];
    if ($status === 404) $data = ['missing' => true];
    elseif ($status !== 200 || $body === false) return null;   // asked again next time
    else {
        $data = json_decode($body, true);
        if (!is_array($data) || !empty($data['error']) || empty($data['name'])) $data = ['missing' => true];
    }
    $data['fetched'] = time();
    @mkdir(dirname($path), 0775, true);
    file_put_contents($path, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
    return $data;
}

function wowhead_text(?array $data): string
{
    return trim(preg_replace('/\s+/', ' ', html_entity_decode(strip_tags(str_replace('<', ' <', (string)($data['tooltip'] ?? ''))), ENT_QUOTES | ENT_HTML5)));
}

/** The level a spell needs ("Requires level N"), 0 when Wowhead does not say. */
function wowhead_spell_level(int $spell, bool $ask = true): int
{
    return preg_match('/Requires level (\d+)/', wowhead_text(wowhead_get('spell', $spell, $ask)), $m) ? (int)$m[1] : 0;
}

/** The NPC a quest summary sends the player back to ("return to X at ...", "bring ... to X in ..."), or ''. */
function wowhead_quest_ender_name(string $text): string
{
    $verbs = '(?:[Rr]eturn|[Rr]eport(?: back)?|[Ss]peak|[Tt]alk|(?:[Bb]ring|[Tt]ake|[Dd]eliver|[Gg]ive|[Ss]how)\b[^.]*?)';
    if (!preg_match('/' . $verbs . ' to ((?:[A-Z][\w\'\-]*)(?: (?:[A-Z][\w\'\-]*|the|of|von|van|de))*)(?=(?: (?:at|in|on|near|inside|outside|within|atop|aboard)\b|[,.!;]|$))/u', $text, $m)) return '';
    $name = preg_replace('/ (?:the|of|von|van|de)$/', '', $m[1]);
    return in_array($name, ['You', 'Your'], true) ? '' : $name;
}

/** The official quests of the last analysis that are not internal: [id => true]. */
function official_quests(): array
{
    $out = [];
    foreach (rows("SELECT id FROM ft_entities WHERE type = 'quest' AND internal = 0") as $r) $out[(int)$r['id']] = true;
    return $out;
}

/** Quest enders from Wowhead's quest summaries, for the official quests the server has no ender for, as an import card. */
function wowhead_quest_import(): array
{
    import_schema();
    $quests = rows('SELECT q.ID, q.LogTitle FROM quest_template q WHERE NOT EXISTS (SELECT 1 FROM creature_questender e WHERE e.quest = q.ID)
        AND NOT EXISTS (SELECT 1 FROM gameobject_questender g WHERE g.quest = q.ID) ORDER BY q.ID', [], 'world');
    // only the client's own quests: the server's quest_template also holds the quests of other versions of the game
    $official = official_quests();
    $quests = array_values(array_filter($quests, fn ($q) => isset($official[(int)$q['ID']])));
    $left = ['not_looked_up_yet' => 0, 'not_on_wowhead' => 0, 'no_ender_named' => 0, 'name_not_on_server' => 0, 'name_not_unique' => 0];
    $named = [];
    foreach ($quests as $q) {
        $data = wowhead_get('quest', (int)$q['ID']);
        if ($data === null) { $left['not_looked_up_yet']++; continue; }
        if (!empty($data['missing'])) { $left['not_on_wowhead']++; continue; }
        $name = wowhead_quest_ender_name(wowhead_text($data));
        if ($name === '') { $left['no_ender_named']++; continue; }
        $named[(int)$q['ID']] = $name;
    }
    // a name counts only when exactly one spawned creature carries it
    $byName = [];
    foreach (array_chunk(array_values(array_unique($named)), 500) as $chunk) {
        $marks = implode(',', array_fill(0, count($chunk), '?'));
        foreach (rows("SELECT ct.entry, ct.name FROM creature_template ct WHERE ct.name IN ($marks) AND EXISTS (SELECT 1 FROM creature c WHERE c.id = ct.entry)", $chunk, 'world') as $r) $byName[$r['name']][] = (int)$r['entry'];
    }
    $build = (int)(meta()['client_build'] ?? 0);
    $rows = [];
    foreach ($named as $quest => $name) {
        $entries = $byName[$name] ?? [];
        if (!$entries) { $left['name_not_on_server']++; continue; }
        if (count($entries) > 1) { $left['name_not_unique']++; continue; }
        $rows[] = [$entries[0], $quest, $build];
    }
    $left = array_filter($left);
    if (!$rows) return ['ok' => false, 'id' => 0, 'counts' => [], 'ignored' => $left,
        'message' => t('Wowhead names no ender this server can use yet.', 'Wowhead ne nomme aucun valideur utilisable par ce serveur.') . ($left['not_looked_up_yet'] ?? 0 ? ' ' . sprintf(t('%d quest(s) not looked up yet: run it again.', '%d quête(s) pas encore consultées : relancez.'), $left['not_looked_up_yet']) : '')];
    $columns = array_values(array_intersect(['id', 'quest', 'VerifiedBuild'], import_columns('world', 'creature_questender')));
    $tables = ['creature_questender' => ['db' => 'world', 'columns' => $columns, 'groups' => [['columns' => $columns, 'rows' => array_map(fn($r) => array_slice($r, 0, count($columns)), $rows)]]]];
    $counts = ['creature_questender' => count($rows)];
    $name = 'Wowhead quest enders ' . date('Y-m-d');
    rows('INSERT INTO ft_imports (name, file, admin, counts, ignored) VALUES (?, ?, ?, ?, ?)', [$name, 'wowhead-quest-enders', (string)(admin()['name'] ?? 'cli'), json_encode($counts), json_encode($left)]);
    $id = (int)db()->insert_id;
    @mkdir(import_dir() . '/parsed', 0775, true);
    file_put_contents(import_dir() . "/parsed/$id.json", json_encode(['tables' => $tables], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE));
    import_index($id, $tables);
    return ['ok' => true, 'id' => $id, 'counts' => $counts, 'ignored' => $left, 'bad' => 0, 'statements' => 0,
            'message' => sprintf(t('%s: %d quest ender(s) named by Wowhead.', '%s : %d valideur(s) nommés par Wowhead.'), $name, count($rows))
                . (($left['not_looked_up_yet'] ?? 0) ? ' ' . sprintf(t('%d quest(s) not looked up yet: run it again for the rest.', '%d quête(s) pas encore consultées : relancez pour la suite.'), $left['not_looked_up_yet']) : '')];
}
