<?php
// A private tracker ([site] public = 0) shows a visitor the login page and nothing else: the API answers 403, and
// the login page carries no coverage, build number or analysis date. No database is configured here, so a page that
// still asked for those would fail with "Database unavailable".
require __DIR__ . '/helpers.php';

$private = "[site]\npublic = 0\nname = \"Test Tracker\"\n[database]\nhost = \"127.0.0.1\"\nport = 1\n";

foreach (['/api/search?q=sword', '/api/tooltip/item/19019', '/api/forge', '/api/imports', '/api/nothing'] as $uri) {
    [$status, $body] = ft_test_request($uri, $private);
    $json = json_decode($body, true);
    check($status === 403 && is_array($json) && isset($json['error']) && count($json) === 1, "private, visitor: $uri answers 403 JSON and nothing else");
}

[$status, $body] = ft_test_request('/login', $private);
check($status === 200 && str_contains($body, 'name="password"') && str_contains($body, 'name="csrf" value="'), 'private, visitor: the login page shows its form with a CSRF token');
check(str_contains($body, 'class="brand"') && str_contains($body, 'data-theme-toggle'), 'private, visitor: brand and theme switch stay');
foreach (['mini-bar', 'pill-count', 'build-chips', 'top-status', 'is-resources', 'data-palette-open', 'id="palette"', 'Analysis of', 'Database unavailable'] as $leak) {
    check(!str_contains($body, $leak), "private, visitor: the login page has no \"$leak\"");
}

[$status, $body] = ft_test_request('/items', $private);
check($status === 303 && $body === '', 'private, visitor: a page redirects to the login page');

// the same visitor on a public tracker, and an administrator on the private one, get past the gate (and then
// stop at the database this test does not have)
[$status, $body] = ft_test_request('/api/search?q=sword', str_replace('public = 0', 'public = 1', $private));
check($status !== 403, 'public, visitor: the API is not closed');
[$status, $body] = ft_test_request('/api/search?q=sword', $private, ['ft_admin' => ['name' => 'admin', 'via' => 'local']]);
check($status !== 403, 'private, administrator: the API is not closed');

ft_test_done();
