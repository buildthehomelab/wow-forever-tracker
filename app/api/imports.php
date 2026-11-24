<?php
// POST api/imports (administrators): upload or import a WowPacketParser SQL file or a ForeverScribe file, preview, apply, delete;
// apply the imported sources of items; import the game client's ForeverScribe files that changed (sync); import NorgannonDB.
require_once FT_APP . '/imports.php';
if (!is_admin()) json_out(['error' => t('Administrators only.', 'Réservé aux administrateurs.')], 403);
$upload = !empty($_FILES['file']);
$input = $upload ? $_POST : (json_decode((string)file_get_contents('php://input'), true) ?: []);
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !csrf_ok($_SERVER['HTTP_X_CSRF_TOKEN'] ?? ($input['csrf'] ?? null))) json_out(['error' => t('Session expired, reload the page.', 'Session expirée, rechargez la page.')], 400);
import_schema();
forge_schema();
@set_time_limit(0);
$dir = import_dir();
@mkdir($dir, 0775, true);

if ($upload) {
    $file = $_FILES['file'];
    if ($file['error'] !== UPLOAD_ERR_OK) {
        json_out(['ok' => false, 'message' => in_array($file['error'], [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true)
            ? sprintf(t('The file is larger than PHP accepts (%s): copy it into %s instead and import it from the list.', 'Le fichier dépasse ce que PHP accepte (%s) : copiez-le plutôt dans %s et importez-le depuis la liste.'), ini_get('upload_max_filesize'), $dir)
            : t('Upload failed.', 'Échec de l’envoi.')]);
    }
    $name = preg_replace('/[^\w.\- ]+/u', '_', basename((string)$file['name'])) ?: 'import.sql';
    if (preg_match('/\.jsonl$/i', $name)) {
        // pages the Wowhead crawler read in a browser tab (tools/wowhead-pages/crawler.js, WHC.save()): into the cache,
        // then an import card from the whole cache
        require_once FT_APP . '/wowheadpages.php';
        try { $merged = wowhead_pages_merge((string)file_get_contents($file['tmp_name'])); }
        catch (RuntimeException $e) { json_out(['ok' => false, 'message' => t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]); }
        if (!$merged['new'] && !$merged['newer'] && !$merged['older']) json_out(['ok' => false, 'message' => t('That file holds no page the Wowhead crawler saved.', 'Ce fichier ne contient aucune page enregistrée par le crawler Wowhead.')]);
        $card = wowhead_pages_import();
        $card['message'] = sprintf(t('%d new page(s), %d newer, %d older than the ones kept, %d line(s) that are no page.', '%d nouvelle(s) page(s), %d plus récente(s), %d plus ancienne(s) que celles conservées, %d ligne(s) qui ne sont pas des pages.'),
            $merged['new'], $merged['newer'], $merged['older'], $merged['not_a_page']) . ' ' . ($card['message'] ?? '');
        $card['ok'] = true;   // the pages are kept even when the card has nothing new
        json_out($card);
    }
    if (preg_match('/\.cdbpack$/i', $name)) {
        // a pack of the original game's database (tools/vmangos_pack.py or tools/classicdb_pack.py): kept as that
        // source's one pack, and read at once. The pack names its source.
        require_once FT_APP . '/sources.php';
        $raw = (string)@file_get_contents($file['tmp_name']);
        $made = substr($raw, 0, 2) === "\x1f\x8b" ? json_decode((string)@gzdecode($raw), true) : null;
        if (!is_array($made)) json_out(['ok' => false, 'message' => t('That is not a pack made by tools/vmangos_pack.py or tools/classicdb_pack.py.', 'Ce n’est pas un paquet créé par tools/vmangos_pack.py ou tools/classicdb_pack.py.')]);
        $source = classicdb_pack_source($made);
        $pack = classicdb_pack($source);
        @mkdir(dirname($pack), 0775, true);
        if (!move_uploaded_file($file['tmp_name'], $pack)) json_out(['ok' => false, 'message' => t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]);
        // the whole pack in the answers table (app/sourceanswers.php)
        require_once FT_APP . '/sourceanswers.php';
        source_answers_version_try($source);
        json_out(classicdb_import($source));
    }
    if (!preg_match('/\.(sql|lua)$/i', $name)) json_out(['ok' => false, 'message' => t('Send a .sql file in WowPacketParser\'s format, or ForeverScribe.lua.', 'Envoyez un fichier .sql au format de WowPacketParser, ou ForeverScribe.lua.')]);
    $target = $dir . '/' . date('Ymd-His') . '-' . $name;
    move_uploaded_file($file['tmp_name'], $target);
    json_out(import_auto_apply(import_file($target, pathinfo($name, PATHINFO_FILENAME))));
}

$id = (int)($input['id'] ?? 0);
// a table, or "table.column": a column whose values a source measured again
$tables = array_values(array_filter((array)($input['tables'] ?? []), fn($t) => is_string($t) && preg_match('/^\w+(\.\w+)?$/', $t)));
$action = (string)($input['action'] ?? '');
switch ($action) {
    case 'import':
        $file = basename((string)($input['file'] ?? ''));
        if ($file === '' || !is_file("$dir/$file")) json_out(['ok' => false, 'message' => t('File not found.', 'Fichier introuvable.')]);
        json_out(import_auto_apply(import_file("$dir/$file", pathinfo($file, PATHINFO_FILENAME))));
    case 'scribe_install':
    case 'scribe_zip':
        // the ForeverScribe addon, into the game client of [client] path or as a zip
        require_once FT_APP . '/spawns.php';
        $files = [];
        foreach (glob(FT_ROOT . '/addon/ForeverScribe/*') ?: [] as $path) $files['ForeverScribe/' . basename($path)] = (string)file_get_contents($path);
        if ($input['action'] === 'scribe_zip') json_out(['ok' => true, 'zip' => base64_encode(spawn_zip($files)), 'name' => 'ForeverScribe.zip']);
        $target = spawn_client_addons();
        if ($target === '') json_out(['ok' => false, 'message' => t('Game client not found: set [client] path in config.ini (the folder with _classic_beta_ or Wow.exe), or download the addon.', 'Client du jeu introuvable : renseignez [client] path dans config.ini (le dossier contenant _classic_beta_ ou Wow.exe), ou téléchargez l’addon.')]);
        foreach ($files as $name => $content) {
            @mkdir(dirname($target . '/' . $name), 0775, true);
            if (file_put_contents($target . '/' . $name, $content) === false) json_out(['ok' => false, 'message' => sprintf(t('Cannot write %s.', 'Impossible d’écrire %s.'), $target . '/' . $name)]);
        }
        json_out(['ok' => true, 'message' => sprintf(t('ForeverScribe installed in %s. Restart the game or /reload.', 'ForeverScribe installé dans %s. Relancez le jeu ou /reload.'), $target)]);
    case 'wowhead_quests':
        require_once FT_APP . '/wowhead.php';
        json_out(wowhead_quest_import());
    case 'refresh_sources':
        // every answer a source gave so far is asked again at the next run (nothing is asked now, nothing is deleted)
        require_once FT_APP . '/wowhead.php';
        $at = source_refresh_all();
        json_out($at ? ['ok' => true, 'message' => t('Done: every source is asked again at its next run. Run the analysis again (Wowhead), then the imports. The first runs take as long as the very first ones did.', 'Fait : chaque source sera réinterrogée à sa prochaine exécution. Relancez l’analyse (Wowhead), puis les imports. Les premières exécutions durent autant que les toutes premières.')]
            : ['ok' => false, 'message' => t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]);
    case 'snapshot_card':
        // a source's card from its last snapshot: nothing is downloaded or asked
        require_once FT_APP . '/sources.php';
        json_out(snapshot_card((string)($input['source'] ?? '')));
    case 'snapshot_cards':
        require_once FT_APP . '/sources.php';
        $cards = snapshot_cards();
        $made = array_filter($cards, fn($c) => !empty($c['id']));
        json_out(['ok' => (bool)$cards, 'id' => count($made), 'replaced' => array_sum(array_map(fn($c) => (int)($c['replaced'] ?? 0), $cards)),
            'message' => $cards ? sprintf(t('%d card(s) made from the database, %d source(s) with nothing new for the server.', '%d carte(s) faite(s) depuis la base, %d source(s) sans rien de neuf pour le serveur.'), count($made), count($cards) - count($made))
                : t('No source has a snapshot yet: import each once from the source.', 'Aucune source n’a encore d’instantané : importez chacune une fois depuis la source.')]);
    case 'norgannon':
        require_once FT_APP . '/norgannon.php';
        json_out(norgannon_import());
    case 'questie':
        require_once FT_APP . '/questie.php';
        json_out(questie_import());
    case 'source_eglink':
        require_once FT_APP . '/sources.php';
        json_out(eglink_import());
    case 'source_wiki':
        // about seventy requests, one a second: in the background
        require_once FT_APP . '/sources.php';
        json_out(source_start('wiki'));
    case 'source_foreverdb':
        require_once FT_APP . '/sources.php';
        json_out(foreverdb_import());
    case 'wowhead_crawler':
    case 'wowhead_crawler_full':
        // the browser crawler with the pages this tracker wants next already queued: nothing is asked of Wowhead here.
        // The full one also reads the whole database of Forever and Classic after them (docs/WOWHEAD-PAGES.md)
        require_once FT_APP . '/wowheadpages.php';
        if (!table_exists('ft_entities')) json_out(['ok' => false, 'message' => t('Run the analysis first: the crawler reads the pages of its gaps.', 'Lancez d’abord l’analyse : le crawler lit les pages de ses manques.')]);
        $queue = wowhead_pages_queue();
        $full = ($input['action'] ?? '') === 'wowhead_crawler_full';
        json_out(['ok' => true, 'file' => base64_encode(wowhead_pages_crawler($queue, $full)), 'name' => $full ? 'wowhead-crawler-full.js' : 'wowhead-crawler.js', 'type' => 'text/javascript',
                  'message' => sprintf(t('%d item page(s) and %d quest page(s) queued, then %d npc and %d object page(s) with missing data.', '%d page(s) d’objets et %d page(s) de quêtes en file, puis %d pages de PNJ et %d d’objets du monde aux données manquantes.'), count($queue['item']), count($queue['quest']), count($queue['npc'] ?? []), count($queue['object'] ?? []))
                      . ($full ? ' ' . t('Then every list of Forever and Classic, and the pages they name.', 'Puis toutes les listes de Forever et Classic, et les pages qu’elles nomment.') : '')]);
    case 'wowhead_extension':
        // the Chrome extension, with this tracker's address and its key inside: a crawl that starts by itself
        require_once FT_APP . '/wowheadpages.php';
        $origin = wowhead_extension_origin();
        if ($origin === null) json_out(['ok' => false, 'message' => t('This request has no usable address to give the extension.', 'Cette requête n’a pas d’adresse utilisable pour l’extension.')]);
        try { $key = wowhead_extension_key(true); }
        catch (RuntimeException $e) { json_out(['ok' => false, 'message' => t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]); }
        json_out(['ok' => true, 'file' => base64_encode(wowhead_extension_zip($origin, $key)), 'name' => 'wowhead-crawl.zip', 'type' => 'application/zip',
                  'message' => sprintf(t('Unzip it, then in Chrome: chrome://extensions › Developer mode › Load unpacked › the wowhead-crawl folder. It calls this tracker at %s.', 'Décompressez-la, puis dans Chrome : chrome://extensions › Mode développeur › Charger l’extension non empaquetée › le dossier wowhead-crawl. Elle appelle ce tracker à %s.'), $origin)]);
    case 'wowhead_wanted':
        // pages asked for first (a dungeon being built): {kind, ids, replace}; the next crawler load reads them first
        require_once FT_APP . '/wowheadpages.php';
        try { $all = wowhead_wanted_set((string)($input['kind'] ?? ''), array_slice((array)($input['ids'] ?? []), 0, WOWHEAD_WANTED_MAX), !empty($input['replace'])); }
        catch (InvalidArgumentException $e) { json_out(['ok' => false, 'message' => t('Unknown kind of page.', 'Type de page inconnu.')]); }
        catch (RuntimeException $e) { json_out(['ok' => false, 'message' => t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]); }
        json_out(['ok' => true, 'wanted' => $all, 'queued' => wowhead_pages_queue()['wanted'] ?? []]);
    case 'wowhead_pages_get':
        // the kept pages of some ids, as the crawler sent them (ids and counts only)
        require_once FT_APP . '/wowheadpages.php';
        $kind = (string)($input['kind'] ?? '');
        if (!in_array($kind, WOWHEAD_PAGES_KINDS, true)) json_out(['ok' => false, 'message' => t('Unknown kind of page.', 'Type de page inconnu.')]);
        json_out(['ok' => true, 'pages' => wowhead_pages_get($kind, array_slice((array)($input['ids'] ?? []), 0, 1000))]);
    case 'wowhead_push':
        // pages a crawl in a linked tab sent (The Forge › Crawl): kept, and the cards made again when due
        require_once FT_APP . '/wowheadpages.php';
        $lines = array_slice(array_values(array_filter((array)($input['lines'] ?? []), 'is_string')), 0, 500);
        try { $got = wowhead_pages_append($lines); }
        catch (RuntimeException $e) { json_out(['ok' => false, 'message' => t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]); }
        [$said, $card] = $got['pages'] ? wowhead_pages_cards_due(!empty($input['card'])) : ['', 0];
        json_out(['ok' => true, 'pages' => $got['pages'], 'not_a_page' => $got['not_a_page'], 'card' => $card, 'message' => $said]);
    case 'source_wowhead':
        // the pages kept in the cache (tools/wowhead-pages): nothing is asked of Wowhead here
        require_once FT_APP . '/wowheadpages.php';
        json_out(wowhead_pages_import());
    case 'source_wowheadclassic':
        // Classic's pages kept in the cache: drops where Forever's own pages count too few
        require_once FT_APP . '/wowheadpages.php';
        json_out(wowhead_pages_classic_import());
    case 'source_wowheadcomments':
        // what players' comments on the pages in the cache link to: givers, enders, vendors and drops still missing
        require_once FT_APP . '/wowheadpages.php';
        json_out(wowhead_comments_import());
    case 'source_foreverchanges':
        // a visit of the site, in the background (minutes to an hour): its card appears when it is done
        require_once FT_APP . '/sources.php';
        json_out(source_start('foreverchanges'));
    case 'source_classicdb':
    case 'source_vmangos':
        require_once FT_APP . '/sources.php';
        json_out(classicdb_import($action === 'source_vmangos' ? 'vmangos' : 'classicdb'));
    case 'source_classicdb_holiday':
    case 'source_vmangos_holiday':
        // a holiday's spawns from the pack (CLASSICDB_HOLIDAYS): the button names the holiday
        require_once FT_APP . '/sources.php';
        json_out(classicdb_holiday_import((string)($input['source'] ?? ''), $action === 'source_vmangos_holiday' ? 'vmangos' : 'classicdb'));
    case 'source_atlasloot':
        // a few seconds (EG Link's first download longer); the same lock as the container's check, so they never overlap
        require_once FT_APP . '/atlasloot.php';
        $lock = source_lock('atlasloot');
        if (!$lock) json_out(['ok' => false, 'message' => $lock === null ? t('AtlasLoot is already being imported.', 'AtlasLoot est déjà en cours d’import.') : t('The data folder cannot be written to.', 'Le dossier data n’est pas accessible en écriture.')]);
        try { $out = atlasloot_import(); } finally { source_unlock($lock); }
        json_out($out);
    case 'source_icyveins':
        // about an hour the first time (two lookups a second): in the background
        require_once FT_APP . '/sources.php';
        json_out(source_start('icyveins'));
    case 'sync':
        require_once FT_APP . '/collector.php';
        $report = collector_sync(!empty($input['apply']) && !empty($input['confirm']));
        json_out(['ok' => true, 'report' => $report, 'message' => $report ? implode(' · ', $report) : t('No new ForeverScribe notes in the game folder.', 'Aucune nouvelle note ForeverScribe dans le dossier du jeu.')]);
    case 'preview':
        $built = import_build($id, $tables);
        if (!(int)$built['rows']) import_mark($id, false, true);
        json_out(['ok' => true, 'rows' => $built['rows'], 'skipped' => $built['skipped'], 'tables' => $built['tables'], 'warnings' => $built['warnings'], 'count' => 1,
                  'apply' => forge_script($built['plans'], 'apply'), 'rollback' => forge_script($built['plans'], 'rollback'), 'databases' => array_keys($built['plans'])]);
    case 'apply':
        if (empty($input['confirm'])) json_out(['error' => t('Confirmation missing.', 'Confirmation manquante.')], 400);
        json_out(import_apply($id, $tables, [], !empty($input['stopped'])));
    case 'delete':
        import_delete($id);
        json_out(['ok' => true]);
    case 'items':
        // the imported sources of the chosen items, from every import that has them
        if (empty($input['confirm'])) json_out(['error' => t('Confirmation missing.', 'Confirmation manquante.')], 400);
        $items = array_values(array_filter(array_map('intval', (array)($input['items'] ?? []))));
        if (!$items) json_out(['ok' => false, 'message' => t('Nothing selected.', 'Rien de sélectionné.')]);
        $byImport = [];
        foreach (rows('SELECT DISTINCT import_id, item FROM ft_import_items WHERE item IN (' . implode(',', $items) . ')') as $r) $byImport[(int)$r['import_id']][] = (int)$r['item'];
        if (!$byImport) json_out(['ok' => false, 'message' => t('No imported file has these items: import WowPacketParser files first (The Forge > Imports).', 'Aucun fichier importé ne contient ces objets : importez d’abord des fichiers WowPacketParser (La Forge > Imports).')]);
        $written = 0; $logs = []; $messages = [];
        foreach ($byImport as $importId => $list) {
            $result = import_apply($importId, [], $list);
            if (!$result['ok']) { $messages[] = '#' . $importId . ': ' . ($result['message'] ?? ''); continue; }
            $written += (int)$result['rows'];
            if (!empty($result['log'])) $logs[] = $result['log'];
            if (!empty($result['message'])) $messages[] = $result['message'];
        }
        json_out(['ok' => $written > 0 || !$messages, 'rows' => $written, 'logs' => $logs, 'message' => implode(' ', $messages),
                  'items' => array_map(fn($i) => ['type' => 'item', 'id' => $i, 'kind' => 'vendor'], array_merge(...array_values($byImport)))]);
}
json_out(['error' => 'unknown action'], 400);
