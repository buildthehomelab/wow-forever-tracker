<?php
// Every file a source gives, kept once (docs/SNAPSHOTS.md, "Every file once").
//
// A source that publishes versions (EG Link's commits, ForeverDB.net's releases, NorgannonDB's commits) mostly repeats
// itself: a new version changes a few files of hundreds. Each importer kept its own folder per version and downloaded
// every file it read again for each, and only those files. Now every file of a version is kept, each once, named by
// its content (data/sources/blobs/<key>): a version's folder (data/eglink/<commit>/...) is made of links to those
// files, so a new version downloads only what changed, and the folders keep the layout every reader (the website and
// tools/tracker.py) already knows. Nothing here is ever in the repository: data/ is not committed.

function store_dir(): string { return $GLOBALS['ft_store_dir'] ?? FT_ROOT . '/data/sources/blobs'; }   // the tests set their own

/** A file's key: 'git-<sha1>' (as GitHub names a file: the hash of "blob <size>\0" and its bytes) or 'sha256-<hex>'. */
function store_key(string $kind, string $body): string
{
    return $kind === 'git' ? 'git-' . sha1('blob ' . strlen($body) . "\0" . $body) : 'sha256-' . hash('sha256', $body);
}

function store_valid_key(string $key): bool { return (bool)preg_match('/^(git-[0-9a-f]{40}|sha256-[0-9a-f]{64})$/', $key); }

function store_path(string $key): string
{
    $hash = substr($key, strpos($key, '-') + 1);
    return store_dir() . '/' . substr($hash, 0, 2) . '/' . $key;
}

function store_has(string $key): bool { return store_valid_key($key) && is_file(store_path($key)); }

/** Keeps $body as the file $key names, after checking that it is that file. '' or what went wrong. */
function store_put(string $key, string $body): string
{
    if (!store_valid_key($key)) return 'not a file key';
    if (store_key(str_starts_with($key, 'git-') ? 'git' : 'sha256', $body) !== $key) return t('the file is not the one named', 'le fichier n’est pas celui annoncé');
    if (is_file(store_path($key))) return '';
    return source_keep(store_path($key), $body);
}

/** Puts the kept file $key at $dest (a link to it: no second copy; a copy where links cannot be made). */
function store_link(string $key, string $dest): bool
{
    $from = store_path($key);
    if (!is_file($from)) return false;
    if (is_file($dest) && @fileinode($dest) === @fileinode($from)) return true;
    @mkdir(dirname($dest), 0775, true);
    $part = $dest . '.' . getmypid() . '.link';
    @unlink($part);
    if (!@link($from, $part) && !@copy($from, $part)) return false;
    if (@rename($part, $dest)) return true;
    @unlink($part);
    return false;
}

/**
 * Makes $dir hold $files ([relative path => [key, url]]): a file kept already is linked, one already at its place is
 * taken into the store when it is the file named (folders downloaded before the store), the others are downloaded,
 * checked against their key and kept. [downloaded, linked, error or ''].
 */
function store_fill(string $dir, array $files, ?callable $progress = null): array
{
    $downloaded = 0; $linked = 0;
    foreach ($files as $rel => [$key, $url]) {
        if (!store_valid_key($key) || !preg_match('#^[\w.\-]+(/[\w.\-]+)*$#', $rel) || str_contains($rel, '..')) continue;   // a name we did not expect never becomes a path
        $dest = "$dir/$rel";
        if (!store_has($key) && is_file($dest)) {
            $body = (string)file_get_contents($dest);
            if (store_key(str_starts_with($key, 'git-') ? 'git' : 'sha256', $body) === $key) store_put($key, $body);
        }
        if (!store_has($key)) {
            [$status, $body, $length] = source_http($url, 120);
            if ($status !== 200) return [$downloaded, $linked, sprintf(t('%s: %s', '%s : %s'), $url, $status ? "HTTP $status" : t('no answer', 'pas de réponse'))];
            if ($length !== null && strlen($body) !== $length) return [$downloaded, $linked, sprintf(t('%s came cut short', '%s est arrivé tronqué'), $url)];
            if (($problem = store_put($key, $body)) !== '') return [$downloaded, $linked, "$url: $problem"];
            $downloaded++;
            if ($progress && $downloaded % 25 === 0) $progress("$downloaded files downloaded");
        }
        if (!store_link($key, $dest)) return [$downloaded, $linked, sprintf(t('%s cannot be written', '%s ne peut pas être écrit'), $dest)];
        $linked++;
    }
    // what the folder is made of, for whoever wants to know which files a version changed
    @file_put_contents("$dir/.files.json", json_encode(array_map(fn($f) => $f[0], $files), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
    return [$downloaded, $linked, ''];
}

/**
 * Every file of a GitHub repository at $commit, as store_fill() takes them. $place maps a path in the repository to its
 * place in the folder (null: not kept). [files, error or ''].
 */
function store_github_files(string $repo, string $commit, callable $place): array
{
    if (!preg_match('/^[0-9a-f]{40}$/', $commit) || !preg_match('#^[\w.\-]+/[\w.\-]+$#', $repo)) return [[], 'not a commit'];
    [$status, $body] = source_http("https://api.github.com/repos/$repo/git/trees/$commit?recursive=1", 60);
    $tree = $status === 200 ? json_decode($body, true) : null;
    if (!is_array($tree) || !isset($tree['tree'])) return [[], sprintf(t('GitHub did not list %s (%s).', 'GitHub n’a pas listé %s (%s).'), $repo, $status ? "HTTP $status" : t('no answer', 'pas de réponse'))];
    if (!empty($tree['truncated'])) return [[], sprintf(t('GitHub listed %s only in part.', 'GitHub n’a listé %s qu’en partie.'), $repo)];
    $files = [];
    foreach ($tree['tree'] as $entry) {
        if (($entry['type'] ?? '') !== 'blob' || !preg_match('/^[0-9a-f]{40}$/', (string)($entry['sha'] ?? ''))) continue;
        $rel = $place((string)$entry['path']);
        if ($rel === null) continue;
        $files[$rel] = ['git-' . $entry['sha'], "https://raw.githubusercontent.com/$repo/$commit/" . implode('/', array_map('rawurlencode', explode('/', (string)$entry['path'])))];
    }
    return [$files, ''];
}

/** A repository's data folder at the top of the version folder, everything else under _repo/ (its README, its tools). */
function store_place_data(string $data): callable
{
    return function (string $path) use ($data): ?string {
        if (str_starts_with($path, "$data/")) return substr($path, strlen($data) + 1);
        return '_repo/' . $path;
    };
}
