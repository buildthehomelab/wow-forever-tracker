<?php
// Administrator login: game accounts (Battle.net e-mail + password, checked the way the login server does)
// with a GM level, or local administrators declared in config.ini ([admins] name = "password hash").

/** Battle.net account SRP6 (auth.battlenet_accounts salt/verifier), versions 1 and 2. */
final class FtBnetSrp6
{
    private const N1 = '86A7F6DEEB306CE519770FE37D556F29944132554DED0BD68205E27F3231FEF5A10108238A3150C59CAF7B0B6478691C13A6ACF5E1B5ADAFD4A943D4A21A142B800E8A55F8BFBAC700EB77A7235EE5A609E350EA9FC19F10D921C2FA832E4461B7125D38D254A0BE873DFC27858ACB3F8B9F258461E4373BC3A6C2A9634324AB';
    private const N2 = 'AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050A37329CBB4A099ED8193E0757767A13DD52312AB4B03310DCD7F48A9DA04FD50E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B855F97993EC975EEAA80D740ADBF4FF747359D041D5C33EA71D281E446B14773BCA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87748544523B524B0D57D5EA77A2775D2ECFA032CFBDBF52FB3786160279004E57AE6AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DBFBB694B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E4AFF73';

    public static function verifier(string $email, string $password, string $salt, int $version): string
    {
        $name = strtoupper(hash('sha256', strtoupper(trim($email))));
        if ($version === 1) {
            $password = strtoupper(substr($password, 0, 16));
            $x = gmp_import(hash('sha256', $salt . hash('sha256', $name . ':' . $password, true), true), 1, GMP_LSW_FIRST);
            $n = gmp_init(self::N1, 16);
            $length = 128;
        } else {
            $bytes = hash_pbkdf2('sha512', $name . ':' . $password, $salt, 15000, 64, true);
            $x = gmp_import($bytes, 1, GMP_MSW_FIRST);
            if (ord($bytes[0]) & 0x80) $x = gmp_sub($x, gmp_pow(2, 512));  // the server reads the bytes as a signed number
            $n = gmp_init(self::N2, 16);
            $x = gmp_mod($x, gmp_sub($n, 1));
            $length = 256;
        }
        return str_pad(gmp_export(gmp_powm(gmp_init(2), $x, $n), 1, GMP_LSW_FIRST), $length, "\0", STR_PAD_RIGHT);
    }
}

// ------------------------------------------------------------------ failed logins per client address
// Counted on the server (data/login-attempts.json), not in the visitor's session: a session is the visitor's to throw
// away, and with it went the count.
const LOGIN_MAX_ATTEMPTS = 8;     // logins one address may fail ...
const LOGIN_WINDOW = 600;         // ... in this many seconds
const LOGIN_MAX_CLIENTS = 5000;   // addresses remembered at once (the oldest go first)

/** Who a login attempt is counted against: the address the web server saw (REMOTE_ADDR; never a forwarded header,
 *  which the client writes itself). An IPv6 client owns a whole /64, so it is counted by that. Behind a reverse
 *  proxy every visitor shares the proxy's address, and the limit with it. */
function login_client(?string $address = null): string
{
    $packed = @inet_pton((string)($address ?? $_SERVER['REMOTE_ADDR'] ?? ''));
    if ($packed === false) return 'unknown';
    if (strlen($packed) === 16) {
        if (str_starts_with($packed, str_repeat("\0", 10) . "\xff\xff")) return (string)inet_ntop(substr($packed, 12));   // IPv4 seen through IPv6
        return inet_ntop(substr($packed, 0, 8) . str_repeat("\0", 8)) . '/64';
    }
    return (string)inet_ntop($packed);
}

function login_attempts_file(): string { return FT_ROOT . '/data/login-attempts.json'; }

/** [client => [times]] of the last 10 minutes; older entries (and anything that is not a time) are dropped. */
function login_attempts_read(string $path, int $now): array
{
    $data = is_file($path) ? json_decode((string)@file_get_contents($path), true) : null;
    $out = [];
    foreach (is_array($data) ? $data : [] as $client => $times) {
        $times = array_values(array_filter((array)$times, fn($t) => is_int($t) && $t > $now - LOGIN_WINDOW && $t <= $now));
        if ($times) $out[(string)$client] = $times;
    }
    return $out;
}

/** Rewrites the file whole: beside itself, then renamed, so a reader never sees half of it. */
function login_attempts_write(string $path, array $all): void
{
    if (count($all) > LOGIN_MAX_CLIENTS) {
        uasort($all, fn($a, $b) => max($b) <=> max($a));
        $all = array_slice($all, 0, LOGIN_MAX_CLIENTS, true);
    }
    $tmp = $path . '.' . getmypid() . '.tmp';
    if (@file_put_contents($tmp, json_encode($all)) !== false && @chmod($tmp, 0600) && @rename($tmp, $path)) return;
    @unlink($tmp);
    error_log('Forever Tracker: cannot write ' . $path . ': failed logins are not counted');
}

/** Runs $change on the counts with the file locked (two logins at once must not lose each other's attempt). */
function login_attempts_change(?string $path, ?int $now, callable $change)
{
    $path ??= login_attempts_file(); $now ??= time();
    $lock = @fopen($path . '.lock', 'c');
    if ($lock) flock($lock, LOCK_EX);
    try {
        $all = login_attempts_read($path, $now);
        $before = $all;
        $result = $change($all, $now);
        if ($all !== $before) login_attempts_write($path, $all);
        return $result;
    } finally {
        if ($lock) { flock($lock, LOCK_UN); fclose($lock); }
    }
}

/** Counts one login attempt of $client and says whether it may go on: false once 8 were made in 10 minutes (that
 *  one is not counted). Counted before the password is checked, so attempts sent at the same moment cannot all slip
 *  under the limit; a login that succeeds forgets them (login_attempts_clear). */
function login_attempt(string $client, ?string $path = null, ?int $now = null): bool
{
    return login_attempts_change($path, $now, function (array &$all, int $now) use ($client): bool {
        if (count($all[$client] ?? []) >= LOGIN_MAX_ATTEMPTS) return false;
        $all[$client][] = $now;
        return true;
    });
}

function login_attempts_clear(string $client, ?string $path = null, ?int $now = null): void
{
    login_attempts_change($path, $now, function (array &$all) use ($client): bool { unset($all[$client]); return true; });
}

/** Returns ['name' => …, 'via' => …] or null, with $error set. */
function admin_login(string $login, string $password, ?string &$error = null): ?array
{
    $login = trim($login);
    $admins = config_all()['admins'] ?? [];
    if (isset($admins[$login]) && password_verify($password, (string)$admins[$login])) {
        return ['name' => $login, 'via' => 'local'];
    }
    if (!str_contains($login, '@')) {
        password_verify($password, '$2y$10$usesomesillystringfore7hnbRJHxXVLeakoG8K30oukPsA.ztMG');  // same cost as a real check
        $error = t('Unknown administrator or wrong password.', 'Administrateur inconnu ou mot de passe incorrect.');
        return null;
    }
    if (!function_exists('gmp_init')) {
        $error = t('Game account login needs the PHP gmp extension.', 'La connexion par compte de jeu nécessite l’extension PHP gmp.');
        return null;
    }
    $bnet = row('SELECT id, email, srp_version, salt, verifier, locked FROM battlenet_accounts WHERE email = ? LIMIT 1', [strtoupper($login)], 'auth');
    $computed = FtBnetSrp6::verifier($login, $password, $bnet['salt'] ?? str_repeat("\0", 32), (int)($bnet['srp_version'] ?? 2));
    if (!$bnet || !hash_equals(rtrim((string)$bnet['verifier'], "\0"), rtrim($computed, "\0"))) {
        $error = t('Wrong e-mail or password.', 'E-mail ou mot de passe incorrect.');
        return null;
    }
    $level = (int)value('SELECT MAX(aa.SecurityLevel) FROM account a JOIN account_access aa ON aa.AccountID = a.id WHERE a.battlenet_account = ?', [(int)$bnet['id']], 'auth');
    if ($level < (int)config('admin', 'gm_level', 3)) {
        $error = t('This account is not a game master of the required level.', 'Ce compte n’est pas maître du jeu au niveau requis.');
        return null;
    }
    return ['name' => strtolower($login), 'via' => 'gm', 'level' => $level];
}
