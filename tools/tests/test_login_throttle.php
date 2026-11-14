<?php
// Failed logins are counted per client address in a file on the server (app/auth.php): 8 in 10 minutes, whatever the
// visitor does with its session cookie.
require __DIR__ . '/helpers.php';
ft_test_boot();
require FT_APP . '/auth.php';

$path = ft_test_dir() . '/login-attempts.json';
$now = 1800000000;

// who is counted
check(login_client('203.0.113.7') === '203.0.113.7', 'an IPv4 client is counted by its address');
check(login_client('::ffff:203.0.113.7') === '203.0.113.7', 'IPv4 seen through IPv6 is the same client');
check(login_client('2001:db8:1:2:aaaa:bbbb:cccc:dddd') === '2001:db8:1:2::/64' && login_client('2001:db8:1:2::1') === '2001:db8:1:2::/64', 'an IPv6 client is counted by its /64');
check(login_client('2001:db8:1:3::1') !== login_client('2001:db8:1:2::1'), 'another /64 is another client');
check(login_client('not an address') === 'unknown' && login_client('') === 'unknown', 'no usable address: one shared count');
$_SERVER['REMOTE_ADDR'] = '198.51.100.9'; $_SERVER['HTTP_X_FORWARDED_FOR'] = '203.0.113.99';
check(login_client() === '198.51.100.9', 'REMOTE_ADDR counts, a forwarded header does not');

// the limit
$allowed = 0;
for ($i = 0; $i < 12; $i++) if (login_attempt('203.0.113.7', $path, $now + $i)) $allowed++;
check($allowed === LOGIN_MAX_ATTEMPTS && LOGIN_MAX_ATTEMPTS === 8, '8 attempts pass, the following ones are refused');
check(count(json_decode((string)file_get_contents($path), true)['203.0.113.7']) === 8, 'a refused attempt is not counted');
check(login_attempt('203.0.113.8', $path, $now + 20), 'another address is not held back');
check(!login_attempt('203.0.113.7', $path, $now + LOGIN_WINDOW - 1), 'still refused just before the 10 minutes are over');
check(login_attempt('203.0.113.7', $path, $now + LOGIN_WINDOW + 1), 'the oldest attempts fall out after 10 minutes');
check((fileperms($path) & 0777) === 0600, 'the file is readable by the web server only');
check(glob(dirname($path) . '/*.tmp') === [], 'no temporary file is left behind');

// a login that succeeds forgets the client's attempts; old entries are pruned on the way
login_attempts_clear('203.0.113.7', $path, $now + LOGIN_WINDOW + 30);
$data = json_decode((string)file_get_contents($path), true);
check(!isset($data['203.0.113.7']), 'a successful login forgets its client');
check(!isset($data['203.0.113.8']), 'entries older than 10 minutes are pruned when the file is written');
check(login_attempt('203.0.113.7', $path, $now + LOGIN_WINDOW + 31), 'and that client may try again');

// a damaged file is no reason to lock everyone out, or in
file_put_contents($path, '{"203.0.113.7": [17');
check(login_attempt('203.0.113.7', $path, $now), 'a damaged file counts as empty');
check(is_array(json_decode((string)file_get_contents($path), true)), 'and is rewritten whole');
file_put_contents($path, json_encode(['203.0.113.7' => ['x', $now + 999999, null, [1]], 'y' => 5]));
check(login_attempts_read($path, $now) === [], 'entries that are not past times are dropped');

ft_test_done();
