"""python -m unittest discover -s tools/tests

The last class needs a MySQL server: it runs when FT_TEST_CONFIG names a config.ini whose [database] user may create
and drop databases and accounts (a throwaway server), and is skipped otherwise.
"""
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import replay  # noqa: E402

DATABASES = ['information_schema', 'world', 'world_ptr', 'hotfixes', 'auth', 'characters', '335_world', 'ft_build']


def guard(text, build='ft_build'):
    return replay.guard(text, build, DATABASES)


class Guard(unittest.TestCase):
    def refused(self, *texts):
        for text in texts:
            with self.assertRaises(replay.ReplayError, msg=text):
                guard(text)

    def test_plain_file_is_unchanged(self):
        text = ("-- a comment naming world.creature\nDELETE FROM `creature` WHERE `guid` = 5;\n"
                "INSERT INTO creature_template (entry, name) VALUES (1, 'Use the world.map; it''s `fine`');\n"
                "UPDATE creature c JOIN creature_template t ON t.entry = c.id SET c.map = 1 WHERE t.entry = 1;\n")
        self.assertEqual(guard(text), text)

    def test_world_schema_is_pointed_at_the_scratch_database(self):
        self.assertEqual(guard('DELETE FROM `world`.`creature` WHERE guid = 1;'), 'DELETE FROM `ft_build`.`creature` WHERE guid = 1;')
        self.assertEqual(guard('INSERT INTO world.updates (name) VALUES (1);'), 'INSERT INTO `ft_build`.updates (name) VALUES (1);')
        self.assertEqual(guard('SELECT WORLD . creature.guid FROM x;'), 'SELECT `ft_build` . creature.guid FROM x;')

    def test_another_database_is_refused(self):
        self.refused('UPDATE world_ptr.creature SET map = 1;', 'DELETE FROM `auth`.`account`;', 'INSERT INTO hotfixes.item_sparse VALUES (1);',
                     'SELECT * FROM characters . characters;', 'DELETE FROM 335_world.creature;', 'DELETE FROM auth.')

    def test_alias_and_column_references_are_not_databases(self):
        text = 'UPDATE creature c, gameobject g SET c.map = g.map WHERE c.guid = g.guid AND c.auth = 1 AND g.x > 1.5;'
        self.assertEqual(guard(text), text)

    def test_information_schema_may_be_read(self):
        text = "SET @n = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE());"
        self.assertEqual(guard(text), text)

    def test_selecting_or_creating_a_database_is_refused(self):
        self.refused('USE world_ptr;\nDELETE FROM creature;', 'DELETE FROM creature;\nuse `auth`;', 'CREATE DATABASE x;',
                     'DROP SCHEMA IF EXISTS world;', 'USE 335_world;', 'USE "auth";', 'use\n`auth`',
                     'DELIMITER $$\nUSE world_ptr$$\nDELETE FROM creature$$', 'DELETE FROM creature\nUSE auth')

    def test_versioned_comments_are_read_as_code(self):
        self.assertEqual(guard('/*!40101 SET NAMES utf8 */;\n/*!50001 DELETE FROM world.creature */;'),
                         '/*!40101 SET NAMES utf8 */;\n/*!50001 DELETE FROM `ft_build`.creature */;')
        self.refused('/*!50001 DELETE FROM auth.account */;', '/*!40000 DROP DATABASE IF EXISTS `world`*/;', 'USE /*!50001 auth */;',
                     '/*!50001 USE */ auth;', 'DELETE FROM auth/*!50001 .account */;', '/*!50001 DELETE FROM auth.*/account;',
                     "/*!50001 SELECT '*/' */;\nUSE auth;\nDELETE FROM account;\n-- '", '/*M!100100 DELETE FROM auth.account */;')

    def test_client_commands_are_refused(self):
        self.refused('\\u world_ptr\nDELETE FROM creature;', 'DELETE FROM creature;\nsource /tmp/x.sql;', 'SELECT 1;\n\\! rm -rf /',
                     'system ls', 'DELETE FROM creature; \\. /tmp/x.sql', 'connect world_ptr;')
        fine = "INSERT INTO t (note) VALUES ('C:\\\\path \\n source x'), ('system');\nUPDATE t SET source = 1 WHERE `system` = 2;"
        self.assertEqual(guard(fine), fine)

    def test_a_change_of_how_quotes_are_read_is_refused(self):
        self.refused("SET sql_mode = 'ANSI_QUOTES';", "SET SESSION sql_mode='NO_BACKSLASH_ESCAPES,STRICT_ALL_TABLES';", 'SET @@sql_mode = 4;')
        fine = "/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;\nSET sql_mode = @OLD_SQL_MODE;"
        self.assertEqual(guard(fine), fine)

    def test_the_word_use_in_data_or_as_a_column_is_fine(self):
        text = ("INSERT INTO t (`use`, note) VALUES (1, 'USE world_ptr;');\nUPDATE t SET `use` = 2, use_count = 1;\n"
                "SELECT * FROM creature USE INDEX (idx_map) WHERE map = 1;\nSELECT * FROM creature use key (PRIMARY);\nSET @use = 1;")
        self.assertEqual(guard(text), text)

    def test_other_things_that_only_look_dangerous(self):
        text = ("INSERT INTO t VALUES (1, \\N, 'x');\nUPDATE t SET a = b*/*it's*/2, note = 'see world.map' WHERE c = 1;\n"
                "SELECT * FROM t FORCE INDEX (i) IGNORE INDEX (j);\nINSERT INTO t VALUES (1) ON DUPLICATE KEY UPDATE a = 2;")
        self.assertEqual(guard(text), text)

    def test_switching_roles_is_refused(self):
        self.refused('SET ROLE ALL;', "set role 'admin';", 'SET DEFAULT ROLE ALL TO CURRENT_USER();')

    def test_a_string_that_builds_sql_for_another_database_is_refused(self):
        self.refused("SET @s = 'DELETE FROM world_ptr.creature';\nPREPARE p FROM @s;\nEXECUTE p;",
                     "SET @s = CONCAT('ALTER TABLE `world`.`creature` ADD COLUMN x INT');")
        fine = "SET @s = 'ALTER TABLE creature ADD COLUMN x INT';\nSET @t = 'SELECT 1 FROM information_schema.TABLES';"
        self.assertEqual(guard(fine), fine)

    def test_prose_that_mentions_a_database_name_is_fine(self):
        text = ("UPDATE quest_template SET LogDescription = 'Travel the world.Then return from the auth.or to me. Back into world. The end.' "
                "WHERE ID = 1;")
        self.assertEqual(guard(text), text)

    def test_bytes_survive_the_round_trip(self):
        raw = "INSERT INTO t VALUES ('Qu\u00eate \u2014 fran\u00e7ais', 'world');".encode('utf-8')
        self.assertEqual(guard(raw.decode('latin-1')).encode('latin-1'), raw)

    def test_build_name_must_be_safe_and_not_a_server_database(self):
        self.assertEqual(replay.check_name('ft_world_build', ['world', 'auth']), 'ft_world_build')
        for name in ('world', 'World', 'mysql', 'a-b', 'a`b', '', 'x; DROP'):
            with self.assertRaises(replay.ReplayError, msg=name):
                replay.check_name(name, ['world', 'auth'])


class Structural(unittest.TestCase):
    def test_finds_what_triggers_cannot_see(self):
        text = ("TRUNCATE TABLE `spell_proc`;\ntruncate creature_text;\n-- TRUNCATE no;\nINSERT INTO t VALUES ('TRUNCATE x');\nTRUNCATE TABLE world.pool;\n"
                "/*!50001 TRUNCATE TABLE versioned */;\nDROP TABLE IF EXISTS `a`, b;\nDROP TEMPORARY TABLE tmp;\nALTER TABLE creature ADD COLUMN x INT;\n"
                "RENAME TABLE old_one TO new_one, old_two TO new_two;\nDROP TABLE spell_proc;\nCREATE TABLE fresh (a INT);")
        self.assertEqual(replay.structural(text), {
            'spell_proc': {'T', 'R'}, 'creature_text': {'T'}, 'pool': {'T'}, 'versioned': {'T'}, 'a': {'R'}, 'b': {'R'}, 'creature': {'a'},
            'old_one': {'A'}, 'old_two': {'A'}})

    def test_alter_table_by_what_it_does_to_the_columns(self):
        text = ("/*!40000 ALTER TABLE `dumped` DISABLE KEYS */;\nINSERT INTO dumped VALUES (1);\n/*!40000 ALTER TABLE `dumped` ENABLE KEYS */;\n"
                "ALTER TABLE added ADD COLUMN x INT, ADD INDEX idx_x (x);\nALTER TABLE retyped MODIFY x BIGINT, DROP INDEX idx_x, DROP PRIMARY KEY;\n"
                "ALTER TABLE renamed CHANGE guid spawnId INT;\nALTER TABLE `shorter` DROP COLUMN x;\nALTER TABLE shorter2 DROP `y`;\n"
                "ALTER TABLE moved RENAME TO elsewhere;\nALTER IGNORE TABLE maria ADD y INT;\nCREATE INDEX idx_a ON indexed (a);\n"
                "CREATE UNIQUE INDEX idx_b ON indexed2 (b);\nDROP INDEX idx_a ON unindexed;\nDROP TABLES gone1, gone2;\nCREATE OR REPLACE TABLE rebuilt (a INT);")
        self.assertEqual(replay.structural(text), {
            'added': {'a'}, 'retyped': {'a'}, 'renamed': {'A'}, 'shorter': {'A'}, 'shorter2': {'A'}, 'moved': {'A'}, 'maria': {'a'},
            'indexed': {'a'}, 'indexed2': {'a'}, 'unindexed': {'a'}, 'gone1': {'R'}, 'gone2': {'R'}, 'rebuilt': {'R'}})


class Dump(unittest.TestCase):
    def check(self, text):
        with tempfile.NamedTemporaryFile('wb', suffix='.sql', delete=False) as handle:
            handle.write(text.encode('utf-8'))
        try:
            replay.check_dump(handle.name)
        finally:
            os.unlink(handle.name)

    def test_a_plain_dump_passes(self):
        self.check("-- MySQL dump\n/*!40101 SET NAMES utf8mb4 */;\nDROP TABLE IF EXISTS `creature`;\nCREATE TABLE `creature` (`guid` int);\n"
                   "INSERT INTO `creature` VALUES (1),\n(2);\nINSERT INTO t VALUES ('Use the stone;');\n")

    def test_a_dump_that_selects_its_database_is_refused(self):
        for line in ('USE `world`;', 'USE world', 'USE `my-world`;', '/*!40000 USE world */;', '\\u world', 'connect world', 'source x.sql',
                     'CREATE DATABASE IF NOT EXISTS `world` /*!40100 DEFAULT CHARACTER SET utf8mb4 */;',
                     '/*!32312 CREATE DATABASE IF NOT EXISTS `world`*/;', 'DROP DATABASE world;',
                     'CREATE DATABASE w; INSERT INTO t VALUES (' + '1,' * 300 + '1);'):
            with self.assertRaises(replay.ReplayError, msg=line):
                self.check('-- dump\n' + line + '\nCREATE TABLE t (a int);\n')


class Definers(unittest.TestCase):
    DUMP = ("CREATE TABLE t (a int);\nINSERT INTO t VALUES ('DEFINER=`root`@`localhost` in data');\n/*!50001 CREATE ALGORITHM=UNDEFINED */\n"
            "/*!50013 DEFINER=`root`@`localhost` SQL SECURITY DEFINER */\n/*!50001 VIEW `v` AS select 1 */;\n"
            "/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`%`*/ /*!50003 TRIGGER x BEFORE INSERT ON t FOR EACH ROW SET NEW.a = 1 */;\n"
            "CREATE DEFINER='admin'@'10.0.0.%' PROCEDURE p() SELECT 1;\n")

    def test_owners_are_found_and_removed_outside_data(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = os.path.join(folder, 'dump.sql'), os.path.join(folder, 'clean.sql')
            with open(source, 'w') as handle:
                handle.write(self.DUMP)
            self.assertTrue(replay.check_dump(source))
            replay.without_definers(source, target)
            with open(target) as handle:
                cleaned = handle.read()
            self.assertEqual(cleaned, (
                "CREATE TABLE t (a int);\nINSERT INTO t VALUES ('DEFINER=`root`@`localhost` in data');\n/*!50001 CREATE ALGORITHM=UNDEFINED */\n"
                "/*!50013 SQL SECURITY DEFINER */\n/*!50001 VIEW `v` AS select 1 */;\n"
                "/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER x BEFORE INSERT ON t FOR EACH ROW SET NEW.a = 1 */;\n"
                "CREATE PROCEDURE p() SELECT 1;\n"))
            with open(source, 'w') as handle:
                handle.write("CREATE TABLE t (a int);\nINSERT INTO t VALUES ('DEFINER=`root`@`localhost`');\n")
            self.assertFalse(replay.check_dump(source))


class Plan(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for path in ('updates/master/2026_10_20_00_world.sql', 'updates/master/2026_10_01_00_world.sql', 'custom/2026_10_15_50_world_a.sql',
                     'custom/readme.txt', 'data/2026_10_15_100_world_b.sql', 'data/2026_10_14_00_world_c.sql'):
            full = os.path.join(self.folder.name, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w') as handle:
                handle.write('-- ' + path)
        self.folders = [(label, os.path.join(self.folder.name, label)) for label in ('updates', 'custom', 'data')]

    def names(self, applied=None):
        return [(name, label) for name, _path, label in replay.plan(self.folders, applied)]

    def sha1(self, path):
        return hashlib.sha1(('-- ' + path).encode()).hexdigest()

    def test_name_order_across_folders(self):
        self.assertEqual(self.names(), [
            ('2026_10_01_00_world.sql', 'updates'), ('2026_10_14_00_world_c.sql', 'data'), ('2026_10_15_100_world_b.sql', 'data'),
            ('2026_10_15_50_world_a.sql', 'custom'), ('2026_10_20_00_world.sql', 'updates')])

    def test_a_listed_file_is_left_out_only_while_its_content_is_the_same(self):
        same = {'2026_10_01_00_world.sql': self.sha1('updates/master/2026_10_01_00_world.sql').upper(),      # as the updater stores it
                '2026_10_14_00_world_c.sql': self.sha1('data/2026_10_14_00_world_c.sql'),
                '2026_10_15_50_world_a.sql': '', '2026_10_20_00_world.sql': ''}                               # no hash recorded
        self.assertEqual(self.names(same), [('2026_10_15_100_world_b.sql', 'data')])
        changed = dict(same, **{'2026_10_01_00_world.sql': 'F' * 40})
        self.assertEqual(self.names(changed), [('2026_10_01_00_world.sql', 'updates'), ('2026_10_15_100_world_b.sql', 'data')])

    def test_a_hash_made_on_windows_counts_too(self):
        path = os.path.join(self.folder.name, 'data', '2026_10_14_00_world_c.sql')
        with open(path, 'wb') as handle:
            handle.write(b"INSERT INTO t VALUES ('two\r\nlines');\r\n")
        as_windows_read_it = hashlib.sha1(b"INSERT INTO t VALUES ('two\nlines');\n").hexdigest().upper()
        self.assertNotIn(('2026_10_14_00_world_c.sql', 'data'), self.names({'2026_10_14_00_world_c.sql': as_windows_read_it}))
        self.assertIn(('2026_10_14_00_world_c.sql', 'data'), self.names({'2026_10_14_00_world_c.sql': 'C' * 40}))

    def test_one_name_in_two_folders_is_an_error(self):
        open(os.path.join(self.folder.name, 'data', '2026_10_15_50_world_a.sql'), 'w').close()
        with self.assertRaises(replay.ReplayError):
            replay.plan(self.folders)

    def test_a_missing_folder_is_an_error(self):
        with self.assertRaises(replay.ReplayError):
            replay.plan([('x', os.path.join(self.folder.name, 'nowhere'))])


class Keys(unittest.TestCase):
    def test_key_choice(self):
        index = lambda unique, *columns: {'unique': unique, 'columns': [(i + 1, c) for i, c in enumerate(columns)]}
        self.assertEqual(replay.choose_key({'PRIMARY': index(True, 'guid'), 'idx_map': index(False, 'map')}, ['guid', 'id', 'map']), (['guid'], True))
        self.assertEqual(replay.choose_key({'uk': index(True, 'b', 'a'), 'idx': index(False, 'c')}, ['a', 'b', 'c']), (['b', 'a'], True))
        self.assertEqual(replay.choose_key({'idx_item': index(False, 'Item'), 'idx_primary': index(False, 'Entry', 'ItemType', 'Item')},
                                           ['Entry', 'ItemType', 'Item']), (['Entry', 'ItemType', 'Item'], False))
        self.assertEqual(replay.choose_key({}, ['id', 'delay', 'command']), (['id'], False))
        out_of_order = {'PRIMARY': {'unique': True, 'columns': [(2, 'b'), (1, 'a')]}}
        self.assertEqual(replay.choose_key(out_of_order, ['a', 'b']), (['a', 'b'], True))

    def test_trigger_names_fit(self):
        self.assertEqual(replay.trigger_name('i', 'creature'), 'ftr_i_creature')
        long_name = 'x' * 64
        self.assertLessEqual(len(replay.trigger_name('u', long_name)), 64)
        self.assertNotEqual(replay.trigger_name('u', long_name), replay.trigger_name('u', 'y' * 64))

    def test_trigger_statements(self):
        statements = replay.trigger_statements("creature`s", ['guid', 'Item'], ['guid', 'Item', 'map'])
        self.assertEqual(len(statements), 6)
        self.assertTrue(all(';' not in s for s in statements))
        insert, update, delete = statements[3:]
        self.assertIn('AFTER INSERT ON `creature``s`', insert)
        self.assertIn("LEFT(CONCAT_WS(',', IFNULL(NEW.`guid`, ''), IFNULL(NEW.`Item`, '')), 190)", insert)
        self.assertIn("'creature`s'", insert)
        self.assertIn('WHERE NOT (CAST(OLD.`guid` AS BINARY) <=> CAST(NEW.`guid` AS BINARY) AND CAST(OLD.`Item` AS BINARY) <=> CAST(NEW.`Item` AS BINARY) '
                      'AND CAST(OLD.`map` AS BINARY) <=> CAST(NEW.`map` AS BINARY))', update)
        self.assertIn('UNION ALL', update)
        self.assertIn('AFTER DELETE', delete)


class FakeDb:
    """Answers what replay() asks and keeps what it runs."""
    def __init__(self, fail=(), global_rights=('USAGE',), schema_rights=(), role='NONE', roles=(), log_bin=('0', '0')):
        self.ran, self.fail, self.triggered = [], set(fail), set()
        self.tables = ['creature', 'updates']
        self.global_rights, self.schema_rights, self.role, self.roles, self.log_bin = global_rights, schema_rights, role, roles, log_bin

    def query(self, sql, database):
        if sql == replay.GRANTEE:
            return [{'g': "'tracker'@'%'"}]
        if 'USER_PRIVILEGES' in sql:
            return [{'p': p} for p in self.global_rights]
        if 'SCHEMA_PRIVILEGES' in sql:
            return [{'s': s, 'p': p} for s, p in self.schema_rights]
        if 'TABLE_PRIVILEGES' in sql or 'COLUMN_PRIVILEGES' in sql:
            return []
        if 'CURRENT_ROLE' in sql:
            if self.role is RuntimeError:
                raise RuntimeError('FUNCTION CURRENT_ROLE does not exist')
            return [{'r': self.role}]
        if 'APPLICABLE_ROLES' in sql:
            if self.roles is RuntimeError:
                raise RuntimeError("Unknown table 'APPLICABLE_ROLES'")
            return [{'r': r} for r in self.roles]
        if '@@log_bin' in sql:
            return [{'b': self.log_bin[0], 't': self.log_bin[1]}]
        if 'SCHEMATA' in sql:
            return [{'d': d} for d in DATABASES if d != 'ft_build']
        if "SHOW TABLES LIKE 'updates'" in sql:
            return [{'t': 'updates'}]
        if sql.startswith('SELECT name, hash FROM updates'):
            return [{'name': 'old.sql', 'hash': ''}]
        if 'information_schema.COLUMNS' in sql:
            return [{'t': t, 'c': 'guid'} for t in self.tables]
        if 'information_schema.STATISTICS' in sql:
            return [{'t': 'creature', 'i': 'PRIMARY', 'n': '0', 's': '1', 'c': 'guid'}]
        if 'information_schema.TRIGGERS' in sql:
            return [{'t': t} for t in self.tables if t not in self.triggered]
        if 'information_schema.TABLES' in sql:
            return [{'t': t} for t in self.tables]
        if 'COUNT(*) n' in sql:
            return [{'n': '3'}]
        raise AssertionError(sql)

    def execute(self, sql, database):
        text = sql.decode('latin-1') if isinstance(sql, bytes) else sql
        self.ran.append((database, text))
        for name in self.fail:
            if name in text and 'SET @ft_file' in text:
                raise RuntimeError('ERROR 1146 (42S02) at line 1: Table missing')
        if 'CREATE TABLE fresh' in text and 'SET @ft_file' in text:
            self.tables.append('fresh')
        for table in self.tables:
            if f'DROP TRIGGER IF EXISTS `ftr_i_{table}`;\nDROP' in text and f'AFTER INSERT ON `{table}`' not in text:
                self.triggered.discard(table)
            if f'AFTER INSERT ON `{table}`' in text:
                self.triggered.add(table)

    def execute_file(self, path, database):
        self.ran.append((database, 'FILE ' + os.path.basename(path)))


class Account(unittest.TestCase):
    def test_an_account_that_only_writes_the_scratch_database_passes(self):
        db = FakeDb(global_rights=['USAGE'], schema_rights=[('ft\\_build', 'INSERT'), ('ft\\_build', 'DROP'), ('world', 'SELECT')])
        self.assertEqual(replay.check_account(db, 'ft_build'), [])
        self.assertEqual(replay.check_account(FakeDb(role=RuntimeError, roles=RuntimeError), 'ft_build'), [])     # a server without roles
        self.assertEqual(replay.check_account(FakeDb(role=None), 'ft_build'), [])

    def test_grants_that_cannot_be_read_do_not_pass(self):
        problems = replay.check_account(FakeDb(global_rights=()), 'ft_build')
        self.assertEqual(len(problems), 1)
        self.assertIn('cannot be read', problems[0])

    def test_a_right_to_lock_or_reference_other_tables_is_not_harmless(self):
        db = FakeDb(schema_rights=[('world', 'SELECT'), ('world', 'LOCK TABLES'), ('world', 'REFERENCES')])
        self.assertEqual(replay.check_account(db, 'ft_build'), ["'tracker'@'%' holds LOCK TABLES, REFERENCES on world"])

    def test_a_server_that_keeps_triggers_for_administrators(self):
        self.assertEqual(replay.check_server(FakeDb()), [])
        self.assertEqual(replay.check_server(FakeDb(log_bin=('1', '1'))), [])
        self.assertIn('log_bin_trust_function_creators', replay.check_server(FakeDb(log_bin=('1', '0')))[0])
        db = FakeDb(log_bin=('ON', 'OFF'))
        with self.assertRaises(replay.ReplayError):
            replay.replay(db, 'ft_build', __file__, [('x', os.path.dirname(__file__))])
        self.assertEqual(db.ran, [])

    def test_rights_elsewhere_are_named(self):
        db = FakeDb(schema_rights=[('ft_build', 'INSERT'), ('world_ptr', 'INSERT'), ('world_ptr', 'DELETE'), ('world', 'SELECT')])
        problems = replay.check_account(db, 'ft_build')
        self.assertEqual(problems, ["'tracker'@'%' holds DELETE, INSERT on world_ptr"])
        self.assertIn('on every database', replay.check_account(FakeDb(global_rights=['SELECT', 'INSERT', 'FILE']), 'ft_build')[0])
        self.assertIn('role', replay.check_account(FakeDb(role='`admin`@`%`'), 'ft_build')[0])
        self.assertIn('builder', replay.check_account(FakeDb(roles=['builder']), 'ft_build')[0])          # granted, even when not active


class Loop(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dump = self.write('TDB_full_world.sql', 'CREATE TABLE creature (guid int);\n')
        os.makedirs(os.path.join(self.folder.name, 'custom'))
        self.write('custom/a_first.sql', '\ufeffDELETE FROM world.creature WHERE guid = 1;\n')
        self.write('custom/b_second.sql', 'TRUNCATE TABLE creature;\nCREATE TABLE fresh (guid int);\n')
        self.write('custom/c_third.sql', 'UPDATE world_ptr.creature SET guid = 2; -- b_marker\n')
        self.write('custom/old.sql', 'DELETE FROM creature;\n')
        self.folders = [('core custom', os.path.join(self.folder.name, 'custom'))]

    def write(self, name, text):
        path = os.path.join(self.folder.name, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def test_order_guard_events_and_stop(self):
        db = FakeDb()
        result = replay.replay(db, 'ft_build', self.dump, self.folders, protected=['world', 'auth'])
        ran = [text for _db, text in db.ran]
        self.assertEqual(db.ran[0], ('information_schema', 'DROP DATABASE IF EXISTS `ft_build`;\nCREATE DATABASE `ft_build` CHARACTER SET utf8mb4;\n'))
        self.assertIn('CREATE TABLE IF NOT EXISTS `ft_replay_files`', ran[1])                                   # before the dump: the mark that it is ours
        self.assertEqual(ran[2], 'FILE TDB_full_world.sql')
        first = next(t for t in ran if 'SET @ft_file = 1;' in t)
        self.assertTrue(first.startswith("INSERT INTO `ft_replay_files` (id, name, source, sha256) VALUES (1, 'a_first.sql', 'core custom', '"))
        # BOM gone, schema pointed here, and in one transaction as the updater runs a file
        self.assertTrue(first.endswith("');\nSET @ft_file = 1;\nBEGIN;\nDELETE FROM `ft_build`.creature WHERE guid = 1;\n\nCOMMIT;\n"))
        second = next(t for t in ran if 'SET @ft_file = 2;' in t)
        # the rows TRUNCATE is about to remove are logged as deleted before the file runs
        self.assertIn("SELECT 'creature', LEFT(CONCAT_WS(',', IFNULL(`creature`.`guid`, '')), 190), 'D', 2 FROM `creature`;\nBEGIN;\nTRUNCATE TABLE creature;",
                      second)
        # afterwards, a deletion noted for a row that is still there is taken back, and the table counts as emptied when rows are gone
        cleanup = next(t for t in ran if t.startswith('DELETE l FROM `ft_replay_log` l'))
        self.assertIn("l.tbl = 'creature' AND l.file = 2 AND l.act = 'D'", cleanup)
        self.assertIn("SELECT 'creature', '*', 'T', 2 FROM DUAL WHERE EXISTS", cleanup)
        after = next(t for t in ran if "VALUES ('fresh', '*', 'R', 2)" in t)                                      # the table file 2 created
        self.assertIn("SELECT 'fresh', LEFT(CONCAT_WS(',', IFNULL(`fresh`.`guid`, '')), 190), 'I', 2 FROM `fresh`", after)
        self.assertIn('AFTER INSERT ON `fresh`', after)
        self.assertFalse(any('SET @ft_file = 3;' in t for t in ran))                                              # refused before it ran
        self.assertTrue(any(t.startswith("INSERT INTO `ft_replay_files`") and "'c_third.sql'" in t for t in ran))  # but listed
        self.assertFalse(any("'old.sql'" in t for t in ran))                                                      # the release had it
        self.assertEqual([name for name, _e in result['failed']], ['c_third.sql'])
        self.assertIn('world_ptr', result['failed'][0][1])
        self.assertTrue(any("state = 'failed'" in t and 'id = 3' in t for t in ran))
        self.assertTrue(any('CREATE TABLE `ft_row_origin`' in t for t in ran))
        self.assertEqual((result['files'], result['rows']), (3, 3))
        self.assertTrue(all(database in ('ft_build', 'information_schema') for database, _t in db.ran))

    def test_an_altered_table_is_followed_again_without_new_rows(self):
        self.write('custom/b_second.sql', 'ALTER TABLE creature CHANGE guid spawnId int;\nUPDATE creature SET spawnId = 2;\n')
        self.write('custom/c_third.sql', 'DELETE FROM creature;\n')
        db = FakeDb()
        replay.replay(db, 'ft_build', self.dump, self.folders)
        ran = [text for _db, text in db.ran]
        second = next(t for t in ran if 'SET @ft_file = 2;' in t)
        self.assertIn('SET @ft_file = 2;\nDROP TRIGGER IF EXISTS `ftr_i_creature`;', second)                      # no trigger can break on the renamed key
        after = next(t for t in ran if "VALUES ('creature', '*', 'A', 2)" in t)
        self.assertNotIn("'I', 2 FROM `creature`", after)
        self.assertIn('AFTER INSERT ON `creature`', after)

    def test_table_names_are_matched_whatever_their_case(self):
        self.write('custom/b_second.sql', 'TRUNCATE TABLE Creature;\n')
        self.write('custom/c_third.sql', 'DELETE FROM creature;\n')
        db = FakeDb()
        replay.replay(db, 'ft_build', self.dump, self.folders)
        second = next(t for _d, t in db.ran if 'SET @ft_file = 2;' in t)
        self.assertIn("'D', 2 FROM `creature`", second)

    def test_switching_keys_off_and_on_keeps_the_triggers(self):
        self.write('custom/b_second.sql', '/*!40000 ALTER TABLE `creature` DISABLE KEYS */;\nINSERT INTO creature VALUES (9);\n'
                                          '/*!40000 ALTER TABLE `creature` ENABLE KEYS */;\n')
        self.write('custom/c_third.sql', 'ALTER TABLE creature ADD COLUMN x INT;\n')
        db = FakeDb()
        replay.replay(db, 'ft_build', self.dump, self.folders)
        ran = [t for _d, t in db.ran]
        self.assertFalse(any('DROP TRIGGER' in t for t in ran if 'SET @ft_file' in t))                      # neither file loses its triggers
        self.assertFalse(any("'*', 'A'" in t for t in ran))

    def test_a_failing_file_stops_unless_told_to_go_on(self):
        self.write('custom/c_third.sql', 'UPDATE creature SET guid = 2;\n')
        self.write('custom/a_first.sql', 'DELETE FROM creature; -- a_marker\n')
        stopped = FakeDb(fail=['a_marker'])
        result = replay.replay(stopped, 'ft_build', self.dump, self.folders)
        self.assertEqual(len(result['failed']), 1)
        self.assertFalse(any('SET @ft_file = 2;' in t for _d, t in stopped.ran))
        going = FakeDb(fail=['a_marker'])
        result = replay.replay(going, 'ft_build', self.dump, self.folders, keep_going=True)
        self.assertEqual(len(result['failed']), 1)
        self.assertTrue(any('SET @ft_file = 3;' in t for _d, t in going.ran))

    def test_refuses_an_account_that_can_write_elsewhere(self):
        db = FakeDb(schema_rights=[('world_ptr', 'UPDATE')])
        with self.assertRaises(replay.ReplayError) as refused:
            replay.replay(db, 'ft_build', self.dump, self.folders)
        self.assertIn('world_ptr', str(refused.exception))
        self.assertEqual(db.ran, [])
        replay.replay(db, 'ft_build', self.dump, self.folders, trust_account=True)
        self.assertTrue(db.ran)

    def test_refuses_a_database_it_did_not_make(self):
        class Taken(FakeDb):
            def query(self, sql, database):
                if 'SCHEMATA' in sql:
                    return [{'d': 'FT_Build'}]                      # found whatever its case
                if 'information_schema.TABLES' in sql:
                    return [{'t': 'creature'}]
                return super().query(sql, database)
        db = Taken()
        with self.assertRaises(replay.ReplayError):
            replay.replay(db, 'ft_build', self.dump, self.folders)
        self.assertEqual(db.ran, [])

    def test_refuses_bad_input_before_anything_runs(self):
        db = FakeDb()
        with self.assertRaises(replay.ReplayError):
            replay.replay(db, 'world', self.dump, self.folders, protected=['world'])
        with self.assertRaises(replay.ReplayError):
            replay.replay(db, 'ft_build', self.dump, [('x', os.path.join(self.folder.name, 'nowhere'))])
        with self.assertRaises(replay.ReplayError):
            replay.replay(db, 'ft_build', self.write('bad.sql', 'USE `world`;\n'), self.folders)
        self.assertEqual(db.ran, [])


@unittest.skipUnless(os.environ.get('FT_TEST_CONFIG'), 'set FT_TEST_CONFIG to a config.ini of a throwaway MySQL server')
class OnMySQL(unittest.TestCase):
    BUILD, USER, OTHER = 'ft_replay_selftest', 'ft_replay_selftest', 'ft_replay_selftest_other'
    F_AGAIN, F_UPDATES, F_IMPORT = '2026_01_02_00_world.sql', '2026_02_01_00_world.sql', '2026_02_03_00_world_import.sql'
    F_FIX, F_REBUILD, F_LATE = '2026_02_05_00_world_fix.sql', '2026_02_07_00_world_rebuild.sql', '2026_02_09_00_world_late.sql'
    F_BROKEN = '2026_02_08_00_world_broken.sql'

    @classmethod
    def setUpClass(cls):
        os.environ['FOREVER_TRACKER_CONFIG'] = os.environ['FT_TEST_CONFIG']
        from ft import sqlio
        cls.admin = sqlio
        cls.folder = tempfile.TemporaryDirectory()
        root = cls.folder.name

        def write(name, text):
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(text)
            return path
        listed = "DELETE FROM creature;  -- in the release with this content: must not run\n"
        write('core/sql/updates/world/master/2026_01_01_00_world.sql', listed)
        write('core/sql/updates/world/master/' + cls.F_AGAIN, "UPDATE creature_template SET name = 'Grey Wolf' WHERE entry = 1;  -- changed since the release\n")

        cls.dump = write('TDB_full_world.sql', f"""
CREATE TABLE updates (name varchar(200) NOT NULL PRIMARY KEY, hash char(40) DEFAULT '', state enum('RELEASED','ARCHIVED') NOT NULL DEFAULT 'RELEASED');
INSERT INTO updates VALUES ('2026_01_01_00_world.sql', '{hashlib.sha1(listed.encode()).hexdigest().upper()}', 'RELEASED'),
  ('{cls.F_AGAIN}', '{'A' * 40}', 'RELEASED');
CREATE TABLE creature_template (entry int NOT NULL PRIMARY KEY, name varchar(100), VerifiedBuild int NOT NULL DEFAULT 0);
INSERT INTO creature_template VALUES (1, 'Wolf', 12340), (2, 'Boar', 12340), (3, 'Bear', 70124), (5, 'Deer', 12340);
CREATE TABLE creature (guid int NOT NULL PRIMARY KEY, id int NOT NULL, map int NOT NULL);
INSERT INTO creature VALUES (10, 1, 0), (11, 2, 0), (12, 3, 1), (14, 3, 1);
CREATE TABLE creature_loot_template (Entry int NOT NULL, ItemType int NOT NULL DEFAULT 0, Item int NOT NULL, Chance float, KEY idx_primary (Entry, ItemType, Item));
INSERT INTO creature_loot_template VALUES (1, 0, 100, 50), (1, 0, 101, 5);
CREATE TABLE event_scripts (id int, delay int);
INSERT INTO event_scripts VALUES (7, 0);
""")
        write('core/sql/updates/world/master/' + cls.F_UPDATES,
              "DELETE FROM `creature_template` WHERE `entry` IN (2, 4);\nINSERT INTO `creature_template` VALUES (2, 'Wild Boar', 70862), (4, 'Raptor', 70862);\n"
              "UPDATE creature SET map = 1 WHERE guid = 10;\nUPDATE creature SET map = 0 WHERE guid = 11;\nDELETE FROM creature WHERE guid = 14;\n"
              "UPDATE creature_template SET name = 'BEAR' WHERE entry = 3;\n")
        write('data/' + cls.F_BROKEN, "INSERT INTO classic_missing_too VALUES (1);\nTRUNCATE TABLE creature_template;\n")
        write('data/' + cls.F_IMPORT, "UPDATE creature_template SET name = 'Great Raptor' WHERE entry = 4;\nINSERT INTO classic_missing VALUES (1);\n")
        write('core/sql/custom/world/' + cls.F_FIX,
              "INSERT INTO world.creature VALUES (20, 4, 1);\nUPDATE creature SET guid = 13 WHERE guid = 12;\n"
              "INSERT INTO creature_loot_template VALUES (1, 0, 102, 1);\nINSERT INTO event_scripts VALUES (7, 5), (8, 0);\n"
              "CREATE TABLE classic_extra (id int NOT NULL PRIMARY KEY, v int);\nINSERT INTO classic_extra VALUES (1, 1);\n")
        write('core/sql/custom/world/' + cls.F_REBUILD,
              "DROP TABLE IF EXISTS creature_loot_template;\nCREATE TABLE creature_loot_template (Entry int NOT NULL, ItemType int NOT NULL DEFAULT 0, "
              "Item int NOT NULL, Chance float, KEY idx_primary (Entry, ItemType, Item));\nINSERT INTO creature_loot_template VALUES (1, 0, 100, 60), (2, 0, 200, 10);\n"
              "ALTER TABLE creature CHANGE guid spawnId int NOT NULL;\nUPDATE creature SET map = 5 WHERE spawnId = 10;\n")
        write('data/' + cls.F_LATE, "INSERT INTO classic_extra VALUES (2, 2);\nTRUNCATE TABLE event_scripts;\nUPDATE creature SET map = 6 WHERE spawnId = 20;\n")
        cls.folders = [('core updates', os.path.join(root, 'core/sql/updates/world')), ('core custom', os.path.join(root, 'core/sql/custom/world')),
                       ('data repository', os.path.join(root, 'data'))]
        # the build's own account: every right on the scratch database, none elsewhere
        sqlio.execute(f"DROP DATABASE IF EXISTS `{cls.BUILD}`;\nDROP USER IF EXISTS '{cls.USER}'@'%';\nCREATE USER '{cls.USER}'@'%' IDENTIFIED BY 'selftest';\n"
                      f"GRANT ALL ON `{cls.BUILD}`.* TO '{cls.USER}'@'%';\n", 'information_schema')
        cls.db = sqlio.Account(cls.USER, 'selftest')
        cls.result = replay.replay(cls.db, cls.BUILD, cls.dump, cls.folders, keep_going=True)

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(f"DROP DATABASE IF EXISTS `{cls.BUILD}`;\nDROP USER IF EXISTS '{cls.USER}'@'%';\n", 'information_schema')
        cls.folder.cleanup()

    def why(self, table, *key):
        return replay.why(self.db, self.BUILD, table, key)

    def acts(self, table, *key):
        return [(a, n) for a, n, _s in self.why(table, *key)['history']]

    def test_the_account_check_on_a_real_server(self):
        self.assertEqual(replay.check_account(self.db, self.BUILD), [])
        self.assertTrue(replay.check_account(self.admin, self.BUILD))            # the throwaway server's administrator can write everywhere
        self.admin.execute(f"GRANT INSERT, SELECT ON `{self.OTHER}`.* TO '{self.USER}'@'%';", 'information_schema')
        try:
            problems = replay.check_account(self.db, self.BUILD)
            self.assertEqual(len(problems), 1)
            self.assertIn(f'INSERT on {self.OTHER}', problems[0])
        finally:
            self.admin.execute(f"REVOKE INSERT, SELECT ON `{self.OTHER}`.* FROM '{self.USER}'@'%';", 'information_schema')

    def test_files_and_the_failure(self):
        self.assertEqual(self.result['files'], 7)
        self.assertEqual([name for name, _e in self.result['failed']], [self.F_IMPORT, self.F_BROKEN])
        self.assertIn('classic_missing', self.result['failed'][0][1])
        states = {r['name']: r['state'] for r in self.db.query('SELECT name, state FROM ft_replay_files', self.BUILD)}
        self.assertEqual(states[self.F_IMPORT], 'failed')
        self.assertEqual(states[self.F_FIX], 'applied')
        self.assertNotIn('2026_01_01_00_world.sql', states)       # same content as the release listed
        self.assertIn(self.F_AGAIN, states)                       # changed since the release: run again, as the updater would
        self.assertEqual(self.db.query('SELECT COUNT(*) n FROM creature', self.BUILD), [{'n': '4'}])

    def test_release_rows_keep_their_origin(self):
        self.assertEqual(self.why('creature_template', 5), {'key_columns': ['entry'], 'exact': True, 'origin': 'release', 'history': [], 'table_events': []})
        self.assertEqual(self.why('creature_template', 999)['origin'], 'no such row')
        self.assertEqual((self.why('creature_template', 1)['origin'], self.acts('creature_template', 1)), ('release', [('U', self.F_AGAIN)]))
        # deleted and inserted again by one file: still the release's row
        self.assertEqual((self.why('creature_template', 2)['origin'], self.acts('creature_template', 2)),
                         ('release', [('D', self.F_UPDATES), ('I', self.F_UPDATES)]))

    def test_an_update_that_changes_nothing_is_not_a_change(self):
        self.assertEqual(self.acts('creature', 11), [])

    def test_a_change_of_case_only_is_a_change(self):
        self.assertEqual(self.acts('creature_template', 3), [('U', self.F_UPDATES)])

    def test_a_failing_file_takes_its_row_changes_back_as_under_the_updater(self):
        self.assertEqual(self.db.query('SELECT name FROM creature_template WHERE entry = 4', self.BUILD), [{'name': 'Raptor'}])
        self.assertEqual(self.acts('creature_template', 4), [('I', self.F_UPDATES)])

    def test_a_truncate_that_never_ran_removes_nothing(self):
        self.assertEqual(self.db.query('SELECT COUNT(*) n FROM creature_template', self.BUILD), [{'n': '5'}])
        self.assertEqual(self.acts('creature_template', 5), [])
        self.assertEqual(self.acts('creature_template', 2), [('D', self.F_UPDATES), ('I', self.F_UPDATES)])
        gone = self.db.query("SELECT COUNT(*) n FROM ft_row_origin WHERE tbl = 'creature_template' AND gone", self.BUILD)
        self.assertEqual(gone, [{'n': '0'}])

    def test_new_rows_name_their_file_and_later_changes(self):
        raptor = self.why('creature_template', 4)
        self.assertEqual((raptor['origin'], raptor['history']), (self.F_UPDATES, [('I', self.F_UPDATES, 'core updates')]))
        self.assertEqual(self.why('creature', 20)['origin'], self.F_FIX)            # written as world.creature
        self.assertEqual(self.db.query('SELECT id FROM creature WHERE spawnId = 20', self.BUILD), [{'id': '4'}])

    def test_deleted_and_moved_rows(self):
        self.assertEqual(self.acts('creature', 14), [('D', self.F_UPDATES)])
        self.assertEqual(self.acts('creature', 12), [('D', self.F_FIX)])
        self.assertEqual(self.why('creature', 13)['origin'], self.F_FIX)
        origin = {(r['tbl'], r['pk']): r for r in self.db.query('SELECT * FROM ft_row_origin', self.BUILD)}
        self.assertEqual(origin[('creature', '14')]['gone'], '1')
        self.assertEqual((origin[('creature', '10')]['created'], origin[('creature', '10')]['gone']), (None, '0'))
        self.assertEqual(origin[('creature', '20')]['files'], '2')
        self.assertNotIn(('creature', '11'), origin)

    def test_an_altered_table_is_followed_under_its_new_key(self):
        self.assertEqual(self.db.query("SELECT key_columns FROM ft_replay_tables WHERE tbl = 'creature'", self.BUILD), [{'key_columns': 'spawnId'}])
        moved = self.why('creature', 10)
        self.assertEqual([(a, n) for a, n, _s in moved['table_events']], [('A', self.F_REBUILD)])
        self.assertEqual(self.acts('creature', 10), [('U', self.F_UPDATES)])        # the altering file's own UPDATE is not followed
        self.assertEqual(self.db.query('SELECT map FROM creature WHERE spawnId = 10', self.BUILD), [{'map': '5'}])
        self.assertEqual(self.acts('creature', 20), [('I', self.F_FIX), ('U', self.F_LATE)])

    def test_a_table_dropped_and_created_again(self):
        kept = self.why('creature_loot_template', 1, 0, 100)
        self.assertEqual((kept['exact'], kept['key_columns'], kept['origin']), (False, ['Entry', 'ItemType', 'Item'], 'release'))
        self.assertEqual(self.acts('creature_loot_template', 1, 0, 100), [('D', self.F_REBUILD), ('I', self.F_REBUILD)])
        self.assertEqual([(a, n) for a, n, _s in kept['table_events']], [('R', self.F_REBUILD)])
        self.assertEqual(self.why('creature_loot_template', 2, 0, 200)['origin'], self.F_REBUILD)
        self.assertEqual(self.acts('creature_loot_template', 1, 0, 101), [('D', self.F_REBUILD)])
        self.assertEqual(self.acts('creature_loot_template', 1, 0, 102), [('I', self.F_FIX), ('D', self.F_REBUILD)])

    def test_a_truncated_table(self):
        script = self.why('event_scripts', 7)
        self.assertEqual((script['exact'], script['key_columns']), (False, ['id']))
        self.assertEqual([a for a, _n, _s in script['table_events']], ['T'])
        self.assertEqual(self.acts('event_scripts', 7), [('I', self.F_FIX), ('D', self.F_LATE), ('D', self.F_LATE)])
        self.assertEqual(self.acts('event_scripts', 8), [('I', self.F_FIX), ('D', self.F_LATE)])

    def test_a_table_a_file_creates_is_tracked_with_its_rows(self):
        first = self.why('classic_extra', 1)
        self.assertEqual((first['origin'], self.acts('classic_extra', 1)), (self.F_FIX, [('I', self.F_FIX)]))
        self.assertEqual([(a, n) for a, n, _s in first['table_events']], [('R', self.F_FIX)])
        self.assertEqual(self.acts('classic_extra', 2), [('I', self.F_LATE)])

    def test_summary(self):
        by_label = {label: (made, changed, gone) for label, made, changed, gone in replay.summary(self.db, self.BUILD)}
        self.assertEqual(by_label, {'core updates': (1, 4, 1), 'core custom': (3, 1, 3), 'data repository': (1, 1, 2)})

    def test_unknown_table(self):
        with self.assertRaises(replay.ReplayError):
            self.why('ft_replay_log', 1)


if __name__ == '__main__':
    unittest.main()
