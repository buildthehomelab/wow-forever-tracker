<?php
// The Forge › Query takes only statements that read (app/query.php). With FT_TEST_MYSQL=host:port:user:password:db
// it also runs them on that MySQL and checks that a write is refused even where the user may write.
require __DIR__ . '/helpers.php';
$mysql = getenv('FT_TEST_MYSQL');
if ($mysql) {
    [$host, $port, $user, $password, $database] = explode(':', $mysql, 5);
    ft_test_boot("[database]\nhost = \"$host\"\nport = $port\nuser = \"$user\"\npassword = \"$password\"\nworld = \"$database\"\nhotfixes = \"$database\"\ntracker = \"$database\"\n");
} else ft_test_boot();
require FT_APP . '/query.php';

$taken = fn($sql) => is_string(query_check($sql));
check(query_check("  SELECT 1;; ") === 'SELECT 1', 'a SELECT is taken, its semicolons dropped');
check(query_check("/* why */ -- note\n# more\nselect * from creature") === 'select * from creature', 'comments in front are skipped');
foreach (['WITH a AS (SELECT 1) SELECT * FROM a', 'SHOW TABLES', 'EXPLAIN SELECT 1', 'DESCRIBE creature', 'desc creature', 'TABLE creature', 'VALUES ROW(1)'] as $sql) {
    check($taken($sql), "taken: $sql");
}
foreach (['DELETE FROM creature', 'UPDATE creature SET id = 1', 'INSERT INTO creature VALUES (1)', 'DROP TABLE creature', 'SET @a = 1',
          'CALL p()', 'LOCK TABLES creature READ', 'GRANT ALL ON *.* TO x', '/* SELECT */ DELETE FROM creature', '-- SELECT', '',
          'SELECT 1 /*! INTO OUTFILE "/tmp/x" */', "SELECT * FROM creature INTO OUTFILE '/tmp/x'", 'SELECT 1 INTO DUMPFILE "/tmp/x"',
          'SELECT * FROM creature FOR UPDATE', 'SELECT * FROM creature LOCK IN SHARE MODE', 'SELECT * FROM creature FOR SHARE', 'selectx 1', '/* open'] as $sql) {
    check(!$taken($sql), 'refused: ' . ($sql === '' ? '(empty)' : $sql));
}
check(query_text(['id', 'name'], [['1', 'Chicken'], ['620', null]]) ===
    "+-----+---------+\n| id  | name    |\n+-----+---------+\n|   1 | Chicken |\n| 620 |    NULL |\n+-----+---------+\n", 'text table like mysql -t');
check(array_keys(query_databases()) === ['world', 'hotfixes', 'tracker'], 'world, hotfixes and tracker are offered');
check(query_run('auth', 'SELECT 1')['error'] === 'unknown database', 'a database not offered is refused');

if ($mysql) {
    $link = new mysqli($host, $user, $password, $database, (int)$port);
    $link->query('DROP TABLE IF EXISTS ft_query_test');
    $link->query('CREATE TABLE ft_query_test (id INT PRIMARY KEY, name VARCHAR(20))');
    $link->query("INSERT INTO ft_query_test VALUES (1, 'a'), (2, 'b'), (3, NULL)");
    $out = query_run('world', 'SELECT * FROM ft_query_test ORDER BY id');
    check($out['ok'] && $out['columns'] === ['id', 'name'] && count($out['rows']) === 3 && $out['rows'][2][1] === null, 'rows and columns come back');
    $out = query_run('world', 'SELECT * FROM ft_query_test ORDER BY id', 2);
    check($out['ok'] && count($out['rows']) === 2 && $out['truncated'], 'stops at the row limit');
    $out = query_run('world', 'WITH a AS (SELECT 1) DELETE FROM ft_query_test');
    check(!$out['ok'], 'a WITH ... DELETE is refused by the read-only transaction: ' . ($out['error'] ?? ''));
    $out = query_run('world', 'SELECT 1; DELETE FROM ft_query_test');
    check(!$out['ok'], 'a second statement is refused');
    $out = query_run('world', 'SELECT nonsense FROM ft_query_test');
    check(!$out['ok'] && strpos($out['error'], 'nonsense') !== false, 'MySQL errors come back as the error');
    check((int)$link->query('SELECT COUNT(*) FROM ft_query_test')->fetch_row()[0] === 3, 'the table still has its 3 rows');
    $link->query('DROP TABLE ft_query_test');
} else {
    echo "skip MySQL checks (set FT_TEST_MYSQL=host:port:user:password:db)\n";
}
ft_test_done();
