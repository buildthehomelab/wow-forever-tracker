<?php
// Shared by the PHP tests (php tools/tests/test_*.php, each exits non-zero when a check fails). They need no
// database and no network: a throw-away folder holds a config.ini and whatever files a test writes.
//
//   ft_test_dir()            a new empty temporary folder, removed when the test ends
//   ft_test_boot($ini)       loads app/bootstrap.php with that config.ini (no database is opened until a test asks)
//   ft_test_request(...)     runs the front controller in a child PHP for one request: [status, body]
//   check($ok, $what)        one line per check; ft_test_done() ends the test
if (PHP_SAPI !== 'cli') exit;

$GLOBALS['ft_test_failed'] = 0;
$GLOBALS['ft_test_dirs'] = [];

function ft_test_dir(): string
{
    $dir = sys_get_temp_dir() . '/ft-test-' . getmypid() . '-' . bin2hex(random_bytes(4));
    mkdir($dir, 0700, true);
    $GLOBALS['ft_test_dirs'][] = $dir;
    return $dir;
}

function ft_test_remove(string $dir): void
{
    foreach (array_diff(scandir($dir) ?: [], ['.', '..']) as $name) {
        $path = "$dir/$name";
        is_dir($path) && !is_link($path) ? ft_test_remove($path) : @unlink($path);
    }
    @rmdir($dir);
}
register_shutdown_function(function () { foreach ($GLOBALS['ft_test_dirs'] as $dir) ft_test_remove($dir); });

function ft_test_config(string $ini): string
{
    $path = ft_test_dir() . '/config.ini';
    file_put_contents($path, $ini);
    return $path;
}

function ft_test_boot(string $ini = "[site]\npublic = 1\n"): void
{
    putenv('FOREVER_TRACKER_CONFIG=' . ft_test_config($ini));
    $_SERVER['SCRIPT_NAME'] = '/index.php';
    session_save_path(ft_test_dir());
    require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
}

/** One request through public/index.php in a child PHP (it ends with exit): [HTTP status, body]. */
function ft_test_request(string $uri, string $ini, array $session = []): array
{
    $code = '$_SERVER["REQUEST_URI"] = ' . var_export($uri, true) . '; $_SERVER["SCRIPT_NAME"] = "/index.php"; $_SERVER["REQUEST_METHOD"] = "GET";'
        . 'register_shutdown_function(function () { echo "\nFT-STATUS " . (http_response_code() ?: 200); });'
        . 'session_save_path(' . var_export(ft_test_dir(), true) . ');'
        . ($session ? 'session_name("ft_session"); session_start(); $_SESSION = ' . var_export($session, true) . '; session_write_close(); $_COOKIE["ft_session"] = session_id();' : '')
        . 'require ' . var_export(dirname(__DIR__, 2) . '/public/index.php', true) . ';';
    $out = (string)shell_exec('FOREVER_TRACKER_CONFIG=' . escapeshellarg(ft_test_config($ini)) . ' ' . escapeshellarg(PHP_BINARY) . ' -d display_errors=stderr -r ' . escapeshellarg($code) . ' 2>&1');
    $status = preg_match('/\nFT-STATUS (\d+)$/', $out, $m) ? (int)$m[1] : 0;
    return [$status, (string)preg_replace('/\nFT-STATUS \d+$/', '', $out)];
}

function check($ok, string $what): void
{
    echo ($ok ? 'ok   ' : 'FAIL ') . $what . "\n";
    if (!$ok) $GLOBALS['ft_test_failed']++;
}

function ft_test_done(): void
{
    $failed = $GLOBALS['ft_test_failed'];
    echo $failed ? "$failed check(s) failed\n" : "all checks passed\n";
    exit($failed ? 1 : 0);
}
