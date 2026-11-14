<?php
// The footer's build commit comes from the COMMIT file the Docker image carries (build_commit(), app/bootstrap.php):
// a commit hash or nothing, whatever the file holds.
require __DIR__ . '/helpers.php';
ft_test_boot();

$dir = ft_test_dir();
$with = function (string $content) use ($dir): string { file_put_contents("$dir/COMMIT", $content); return build_commit("$dir/COMMIT"); };

check(build_commit("$dir/missing") === '', 'no COMMIT file: nothing');
check($with("\n") === '' && $with('') === '', 'an empty build argument: nothing');
check($with("d3072c9e5b1f4a6c8d7e9f0a1b2c3d4e5f6a7b8c\n") === 'd3072c9e5b1f4a6c8d7e9f0a1b2c3d4e5f6a7b8c', 'a full hash is kept');
check($with("D3072C9\n") === 'd3072c9', 'a short hash too, in lower case');
check($with('main') === '' && $with('<script>alert(1)</script>') === '' && $with("d3072c9 dirty") === '', 'anything that is not a hash: nothing');
check(substr($with('d3072c9e5b1f4a6c8d7e9f0a1b2c3d4e5f6a7b8c'), 0, 8) === 'd3072c9e', 'the footer shows its first 8 characters');

ft_test_done();
