"""Replays a core's world into a scratch database and records which file wrote each row.

The world a server runs is its release dump plus every update file, in the updater's order. Replaying that here, with
triggers that note each insert, update and delete under the file being applied, gives every row its origin: the
release, or the file that created it and the file that last changed it.

An update file is somebody else's SQL. What keeps it inside the scratch database is the MySQL account: the replay
refuses to start with an account that can write anywhere else (check_account). Reading each file first (guard) only
catches mistakes early.

The database is reached through a small object with `query(sql, database)`, `execute(text or bytes, database)` and
`execute_file(path, database)` (tools/ft/sqlio.py has them), so the logic is tested without a server.
"""
import hashlib
import os
import re
import tempfile

LOG, FILES, TABLES, ORIGIN = 'ft_replay_log', 'ft_replay_files', 'ft_replay_tables', 'ft_row_origin'
OWN = (LOG, FILES, TABLES, ORIGIN)
UNTRACKED = ('updates', 'updates_include') + OWN
NAME = re.compile(r'^[A-Za-z0-9_]+$')
KEY_LENGTH = 190
# a dump that picks its own database or runs a client command: one statement on its own line, as mysqldump writes it
DUMP_SELECTS_DATABASE = re.compile(rb'^\s*(?:/\*!\d+\s*)?(?:USE\s+(?:`[^`]+`|[\w$]+)\s*(?:\*/)?\s*;?\s*$|(?:CREATE|DROP)\s+(?:DATABASE|SCHEMA)\b'
                                   rb'|\\[u.!r]|(?:source|connect|system)\s)', re.I)
# the owner of a view, trigger or routine, as mysqldump writes it at the start of a line
DUMP_DEFINER = re.compile(rb'^\s*(?:/\*!\d+\s*)?(?:CREATE\s*(?:\*/\s*/\*!\d+\s*)?)?(?:ALGORITHM\s*=\s*\w+\s+)?DEFINER\s*=', re.I)
DEFINER = re.compile(rb'DEFINER\s*=\s*(?:`[^`]*`|\'[^\']*\'|\w+)\s*@\s*(?:`[^`]*`|\'[^\']*\'|[\w.%-]+)\s?', re.I)
# strings, quoted names, comments, the opening and closing of a versioned comment (its content is code), space, words
TOKEN = re.compile(r"""('(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*"|`(?:[^`]|``)+`|--(?=\s|$)[^\n]*|\#[^\n]*|/\*M?!\d*|\*/(?!\*)|/\*.*?\*/|\s+|[\w$]+|.)""", re.S)
# inside a string, SQL that names a database: a table keyword, then `database`.`table` written without spaces
STRING_NAMES_DATABASE = r'\b(?:FROM|INTO|UPDATE|JOIN|TABLE|TRUNCATE|EXISTS)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?`?%s`?\.`?\w'
ALWAYS_READABLE = {'information_schema'}
# commands the mysql client runs itself (a file, a shell command, another connection): never SQL an update file needs
CLIENT_COMMANDS = {'SOURCE', 'SYSTEM', 'CONNECT', 'TEE', 'NOTEE', 'PAGER', 'NOPAGER', 'EDIT', 'RESETCONNECTION'}
# what an account may hold on other databases and still be the build's account
HARMLESS = {'USAGE', 'SELECT', 'SHOW VIEW', 'SHOW DATABASES', 'PROCESS', 'REPLICATION CLIENT'}
GRANTEE = ("SELECT CONCAT(CHAR(39), LEFT(CURRENT_USER(), CHAR_LENGTH(CURRENT_USER()) - CHAR_LENGTH(SUBSTRING_INDEX(CURRENT_USER(), '@', -1)) - 1), "
           "CHAR(39), '@', CHAR(39), SUBSTRING_INDEX(CURRENT_USER(), '@', -1), CHAR(39)) g")


class ReplayError(Exception):
    pass


def sql_string(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def quote(name):
    return '`' + name.replace('`', '``') + '`'


def check_name(name, protected=()):
    """The scratch database's name: plain, and never one of the server's own databases."""
    if not NAME.match(name or ''):
        raise ReplayError(f'build database name {name!r}: letters, digits and _ only')
    if name.lower() in {p.lower() for p in protected if p} | {'mysql', 'sys', 'information_schema', 'performance_schema'}:
        raise ReplayError(f'build database {name!r} is one of the server\'s own databases: choose another name')
    return name


def check_account(db, build):
    """What the MySQL account could write outside the scratch database, as sentences; empty when nothing.

    This is the replay's protection: no reading of a file's text can promise where its SQL writes, but an account
    that can only write to the scratch database can."""
    grantee = db.query(GRANTEE, 'information_schema')[0]['g']
    who = sql_string(grantee)
    problems = []
    held = {r['p'] for r in db.query(f'SELECT PRIVILEGE_TYPE p FROM information_schema.USER_PRIVILEGES WHERE GRANTEE = {who}', 'information_schema')}
    if not held:        # every account holds at least USAGE: no line means its grants cannot be read here
        return [f'the grants of {grantee} cannot be read, so they cannot be checked']
    everywhere = sorted(held - HARMLESS)
    if everywhere:
        problems.append(f"{grantee} holds {', '.join(everywhere[:6])}{' ...' if len(everywhere) > 6 else ''} on every database")
    elsewhere = {}
    for view in ('SCHEMA_PRIVILEGES', 'TABLE_PRIVILEGES', 'COLUMN_PRIVILEGES'):
        for row in db.query(f'SELECT TABLE_SCHEMA s, PRIVILEGE_TYPE p FROM information_schema.{view} WHERE GRANTEE = {who}', 'information_schema'):
            schema = (row['s'] or '').replace('\\_', '_').replace('\\%', '%')
            if schema.lower() != build.lower() and row['p'] not in HARMLESS:
                elsewhere.setdefault(schema, set()).add(row['p'])
    problems += [f"{grantee} holds {', '.join(sorted(rights)[:6])}{' ...' if len(rights) > 6 else ''} on {schema}"
                 for schema, rights in sorted(elsewhere.items())]
    try:
        role = db.query('SELECT CURRENT_ROLE() r', 'information_schema')[0]['r']
    except RuntimeError:        # a server without roles
        role = None
    try:
        granted = sorted({r['r'] for r in db.query('SELECT ROLE_NAME r FROM information_schema.APPLICABLE_ROLES', 'information_schema') if r['r']})
    except RuntimeError:        # a server without that view
        granted = []
    if role not in (None, '', 'NONE') or granted:
        problems.append(f"{grantee} has a role ({', '.join(granted) or role}): what a role grants is not looked at")
    return problems


def check_server(db):
    """Why an ordinary account cannot create the replay's triggers on this server, as sentences; empty when it can."""
    try:
        row = db.query('SELECT @@log_bin b, @@log_bin_trust_function_creators t', 'information_schema')[0]
    except RuntimeError:
        return []
    if str(row['b']) in ('1', 'ON') and str(row['t']) in ('0', 'OFF'):
        return ['the server writes a binary log and only lets an administrator create triggers: have one run '
                'SET GLOBAL log_bin_trust_function_creators = 1 (and set it in the server\'s configuration)']
    return []


# ------------------------------------------------------------------ reading a file before it runs
def _plain(token):
    return token[1:-1].replace('``', '`') if token.startswith('`') else token


def _is_name(token):
    return token.startswith('`') or (re.fullmatch(r'[\w$]+', token) is not None and not token.isdigit())


def _code(tokens):
    """Positions of the tokens that are code: no space, no comment, no versioned-comment marker."""
    return [i for i, t in enumerate(tokens) if not (t.isspace() or t.startswith(('--', '#', '/*')) or t == '*/')]


def guard(text, build, databases, world_names=('world',)):
    r"""The file's text for the scratch database `build`; raises ReplayError when it plainly reaches outside.

    - `USE`, `CREATE DATABASE` and `DROP DATABASE` are refused, and so are the mysql client's own commands (`source`,
      `system`, `\!`, `\u` ...) and a change of how the server reads quotes (sql_mode ANSI_QUOTES, NO_BACKSLASH_ESCAPES);
    - `` `world`.`creature` `` (the core's default world name, or `world_names`) is pointed at the scratch database;
    - a name qualified with any other database the account can see (`databases`) is refused;
    - a string that holds SQL naming a database (built for PREPARE: "... FROM `world`.`creature`") is refused.
    The content of a versioned comment (/*!50001 ... */) is read as the code it is.

    This catches mistakes early and says why. It is not the protection: SQL built piece by piece at run time cannot
    be read here. The account's rights are (check_account).
    """
    known = {d.lower() for d in databases} | {w.lower() for w in world_names} | {build.lower()}
    ours = {w.lower() for w in world_names} | {build.lower()}
    in_string = re.compile(STRING_NAMES_DATABASE % ('(' + '|'.join(re.escape(d) for d in sorted(known - ALWAYS_READABLE)) + ')'), re.I)
    tokens = TOKEN.findall(text)
    code = _code(tokens)
    out = list(tokens)
    for position, i in enumerate(code):
        token = tokens[i]
        if token[:1] in '\'"':
            named = in_string.search(token) if '.' in token else None
            if named:
                raise ReplayError(f'a string builds SQL that names the database `{named.group(1)}`')
            continue
        upper = token.upper()
        following = tokens[code[position + 1]] if position + 1 < len(code) else ''
        previous = tokens[code[position - 1]] if position else ';'
        # USE is a reserved word: outside an index hint (USE INDEX, USE KEY) it selects a database
        if upper == 'USE' and previous != '@' and following.upper() not in ('INDEX', 'KEY'):
            raise ReplayError(f'it selects a database (USE {_plain(following)})')
        if (token == '\\' and following != 'N') or (upper in CLIENT_COMMANDS and previous == ';'):      # \N is NULL
            raise ReplayError(f'it holds a command of the mysql client ({token}{following})')
        if upper == 'ROLE' and previous.upper() in ('SET', 'DEFAULT'):
            raise ReplayError('it switches roles (SET ROLE)')
        if upper in ('DATABASE', 'SCHEMA') and previous.upper() in ('CREATE', 'DROP', 'ALTER'):
            raise ReplayError(f'it runs {previous.upper()} {upper}')
        if upper == 'SQL_MODE' and following == '=' and position + 2 < len(code):
            value = tokens[code[position + 2]]
            if value.isdigit() or (value[:1] in '\'"' and re.search(r'ANSI|NO_BACKSLASH_ESCAPES', value, re.I)):
                raise ReplayError(f'it changes how quotes are read (sql_mode = {value[:60]})')
        if following == '.' and previous != '.' and _is_name(token):
            database = _plain(token).lower()
            if database in ours:
                out[i] = f'`{build}`'
            elif database in known and database not in ALWAYS_READABLE:
                raise ReplayError(f'it names the database `{_plain(token)}`')
    return ''.join(out)


def structural(text):
    """{table: kinds} of the tables a file changes in ways row triggers cannot see: 'T' emptied with TRUNCATE,
    'R' dropped (and perhaps created again), 'A' altered so that a column is renamed or dropped (or the table is
    renamed), 'a' altered otherwise (a column or an index added or changed)."""
    tokens = TOKEN.findall(text)
    code = [tokens[i] for i in _code(tokens)]
    found = {}

    def table_at(index):
        """(table, next index) of a perhaps database-qualified name."""
        if index < len(code) and _is_name(code[index]):
            if index + 2 < len(code) and code[index + 1] == '.' and _is_name(code[index + 2]):
                return _plain(code[index + 2]), index + 3
            return _plain(code[index]), index + 1
        return None, index

    def listed(index, kind, renames=False):
        while True:
            table, index = table_at(index)
            if table is None:
                return
            found.setdefault(table, set()).add(kind)
            if renames and index < len(code) and code[index].upper() == 'TO':      # RENAME TABLE a TO b, c TO d
                _new, index = table_at(index + 1)
            if index < len(code) and code[index] == ',':
                index += 1
            else:
                return

    def alter_kind(index):
        """How an ALTER TABLE whose clauses start at `index` changes the table, or None when it only switches its
        keys off and on (ALTER TABLE x DISABLE KEYS, as mysqldump writes around its INSERTs)."""
        clauses = []
        while index < len(code) and code[index] != ';':
            clauses.append(code[index].upper())
            index += 1
        if clauses[:2] in (['DISABLE', 'KEYS'], ['ENABLE', 'KEYS']):
            return None
        for position, word in enumerate(clauses):
            following = clauses[position + 1] if position + 1 < len(clauses) else ''
            if word in ('CHANGE', 'RENAME') or (word == 'DROP' and following not in ('INDEX', 'KEY', 'PRIMARY', 'FOREIGN', 'CONSTRAINT', 'CHECK', 'PARTITION')):
                return 'A'
        return 'a'

    for index, token in enumerate(code):
        upper = token.upper()
        words = [c.upper() for c in code[index + 1:index + 4]] + ['', '', '']
        if upper == 'TRUNCATE':
            listed(index + (2 if words[0] == 'TABLE' else 1), 'T')
        elif upper in ('DROP', 'RENAME') and words[0] in ('TABLE', 'TABLES'):
            start = index + 2
            if upper == 'DROP' and words[1:3] == ['IF', 'EXISTS']:
                start += 2
            listed(start, 'R' if upper == 'DROP' else 'A', upper == 'RENAME')
        elif upper == 'ALTER' and (words[0] == 'TABLE' or (words[0] in ('IGNORE', 'ONLINE') and words[1] == 'TABLE')):
            table, rest = table_at(index + (2 if words[0] == 'TABLE' else 3))
            kind = alter_kind(rest) if table else None
            if kind:
                found.setdefault(table, set()).add(kind)
        elif upper == 'CREATE' and words[:3] == ['OR', 'REPLACE', 'TABLE']:
            listed(index + 4, 'R')
        elif upper == 'INDEX' and index and code[index - 1].upper() in ('CREATE', 'DROP', 'UNIQUE', 'FULLTEXT', 'SPATIAL') and words[1] == 'ON':
            listed(index + 3, 'a')
    return found


def check_dump(path):
    """Refuses a release dump that selects or creates a database itself: it would not land in the scratch one.
    Returns True when the dump names the owner of a view or routine (see without_definers)."""
    definers = False
    with open(path, 'rb') as handle:
        for number, line in enumerate(handle, 1):
            if DUMP_SELECTS_DATABASE.match(line[:400]):
                raise ReplayError(f'{os.path.basename(path)} line {number} selects its own database or runs a client command '
                                  f'({line[:60].strip().decode("latin-1")}): remove that line first')
            definers = definers or DUMP_DEFINER.match(line[:400]) is not None
    return definers


def without_definers(path, target):
    """Copies a dump without the owner mysqldump writes on views, triggers and routines (DEFINER=`user`@`host`): only
    an administrator may create them for somebody else, and they then run with that user's rights. Without the
    clause they belong to the account that loads the dump."""
    with open(path, 'rb') as source, open(target, 'wb') as out:
        for line in source:
            if DUMP_DEFINER.match(line[:400]):
                line = DEFINER.sub(b'', line, count=1)
            out.write(line)


# ------------------------------------------------------------------ the updater's order
def collect(folders):
    """{name: (name, path, label)} of every update file under `folders` ([(label, folder)], sub-folders too). The same
    name in two places is an error: the updater would run only one of them."""
    found = {}
    for label, folder in folders:
        if not os.path.isdir(folder):
            raise ReplayError(f'{folder}: no such folder')
        for root, _dirs, names in os.walk(folder):
            for name in names:
                if not name.lower().endswith('.sql'):
                    continue
                if name in found:
                    raise ReplayError(f'{name} is in two places: {found[name][1]} and {os.path.join(root, name)}')
                found[name] = (name, os.path.join(root, name), label)
    return found


def file_sha1s(path):
    """The SHA-1 hashes an updater may have stored for a file: of its bytes, and of its bytes with CRLF read as LF
    (what a Windows build of the updater sees)."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    return {hashlib.sha1(raw).hexdigest().upper(), hashlib.sha1(raw.replace(b'\r\n', b'\n')).hexdigest().upper()}


def plan(folders, applied=None):
    """[(name, path, label)] of the update files to run, in the updater's order: by file name, over every folder.

    `applied` is the release's `updates` table as {name: hash, or None for an archived file}. As the core's updater
    does, a file the release lists is left out when its content still has that hash (or the release recorded none,
    or it is archived), and runs again when it was changed since."""
    applied = applied or {}
    found = collect(folders)
    out = []
    for name in sorted(found):
        if name in applied and (not applied[name] or applied[name].upper() in file_sha1s(found[name][1])):
            continue
        out.append(found[name])
    return out


# ------------------------------------------------------------------ triggers
def trigger_name(kind, table):
    name = f'ftr_{kind}_{table}'
    return name if len(name) <= 64 else f'ftr_{kind}_' + hashlib.sha1(table.encode()).hexdigest()[:24]


def key_expression(row, columns):
    return "LEFT(CONCAT_WS(',', " + ', '.join(f"IFNULL({row}.{quote(c)}, '')" for c in columns) + f'), {KEY_LENGTH})'


def drop_triggers(table):
    return [f'DROP TRIGGER IF EXISTS {quote(trigger_name(kind, table))}' for kind in 'iud']


def trigger_statements(table, key, columns):
    """The three triggers that log a table's row changes under @ft_file, as single statements (no DELIMITER needed).
    An update that leaves every column as it was logs nothing; one that moves a row's key logs the old key as deleted
    and the new one as inserted."""
    new, old = key_expression('NEW', key), key_expression('OLD', key)
    head = f'INSERT INTO {quote(LOG)} (tbl, pk, act, file)'
    literal = sql_string(table)
    # byte for byte: a column's own collation would call 'Quete' and 'Quête', or 'a' and 'A', the same
    same = ' AND '.join(f'CAST(OLD.{quote(c)} AS BINARY) <=> CAST(NEW.{quote(c)} AS BINARY)' for c in columns)
    moved = f'CAST({old} AS BINARY) <> CAST({new} AS BINARY)'
    return drop_triggers(table) + [
        f"CREATE TRIGGER {quote(trigger_name('i', table))} AFTER INSERT ON {quote(table)} FOR EACH ROW "
        f"{head} VALUES ({literal}, {new}, 'I', IFNULL(@ft_file, 0))",
        f"CREATE TRIGGER {quote(trigger_name('u', table))} AFTER UPDATE ON {quote(table)} FOR EACH ROW "
        f"{head} SELECT {literal}, {new}, IF({moved}, 'I', 'U'), IFNULL(@ft_file, 0) FROM DUAL WHERE NOT ({same}) "
        f"UNION ALL SELECT {literal}, {old}, 'D', IFNULL(@ft_file, 0) FROM DUAL WHERE {moved}",
        f"CREATE TRIGGER {quote(trigger_name('d', table))} AFTER DELETE ON {quote(table)} FOR EACH ROW "
        f"{head} VALUES ({literal}, {old}, 'D', IFNULL(@ft_file, 0))"]


def log_rows(table, key, act, number):
    """Logs every row the table holds now, as inserted or deleted by a file."""
    return (f"INSERT INTO {quote(LOG)} (tbl, pk, act, file) SELECT {sql_string(table)}, {key_expression(quote(table), key)}, '{act}', {number} "
            f"FROM {quote(table)}")


def forget_unremoved(table, key, number):
    """Takes back the deletions noted before a file ran for the rows that are still there afterwards and that nothing
    touched since: the file's TRUNCATE or DROP did not happen (it failed first, or sits in a routine nobody called)."""
    log, name = quote(LOG), sql_string(table)
    return (f"DELETE l FROM {log} l "
            f"JOIN (SELECT a.pk FROM (SELECT pk, MAX(seq) m FROM {log} WHERE tbl = {name} GROUP BY pk) a JOIN {log} e ON e.seq = a.m "
            f"WHERE e.file = {number} AND e.act = 'D') last ON last.pk = l.pk "
            f"JOIN (SELECT DISTINCT {key_expression(quote(table), key)} pk FROM {quote(table)}) still "
            f"ON l.pk = CONVERT(still.pk USING utf8mb4) COLLATE utf8mb4_bin "
            f"WHERE l.tbl = {name} AND l.file = {number} AND l.act = 'D'")


def log_event(table, act, number):
    return f"INSERT INTO {quote(LOG)} (tbl, pk, act, file) VALUES ({sql_string(table)}, '*', '{act}', {number})"


def choose_key(indexes, columns):
    """(key columns, exact) for a table: its primary key, else a unique index, else an index named like a primary key,
    else its first index, else its first column. `exact` is False when several rows can share the key."""
    def named(name):
        return [c for _seq, c in sorted(indexes[name]['columns'])]
    if 'PRIMARY' in indexes:
        return named('PRIMARY'), True
    unique = sorted(name for name, index in indexes.items() if index['unique'])
    if unique:
        return named(unique[0]), True
    if indexes:
        preferred = sorted(indexes, key=lambda name: (0 if 'primary' in name.lower() else 1, name))
        return named(preferred[0]), False
    return columns[:1], False


SETUP = [
    f'CREATE TABLE IF NOT EXISTS {quote(FILES)} (id INT NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL, source VARCHAR(64) NOT NULL, '
    "sha256 CHAR(64) NOT NULL, state VARCHAR(16) NOT NULL DEFAULT 'pending', error TEXT NULL, UNIQUE KEY name (name)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    f'CREATE TABLE IF NOT EXISTS {quote(TABLES)} (tbl VARCHAR(64) NOT NULL PRIMARY KEY, key_columns VARCHAR(512) NOT NULL, exact TINYINT NOT NULL) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    # act, per row: I insert, U update, D delete. Per table (pk '*'): R created or rebuilt, T emptied, A altered or renamed
    f'CREATE TABLE IF NOT EXISTS {quote(LOG)} (seq BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, tbl VARCHAR(64) NOT NULL, '
    f'pk VARCHAR({KEY_LENGTH}) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, act CHAR(1) NOT NULL, file INT NOT NULL, KEY row_key (tbl, pk)) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
]
SUMMARISE = [
    f'DROP TABLE IF EXISTS {quote(ORIGIN)}',
    # created: the file that first inserted the row, NULL when the release had it; changed: the last file that
    # touched it; files: how many files touched it; gone: its last change was a delete
    f'CREATE TABLE {quote(ORIGIN)} (tbl VARCHAR(64) NOT NULL, pk VARCHAR({KEY_LENGTH}) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, '
    'created INT NULL, changed INT NOT NULL, files INT NOT NULL, gone TINYINT NOT NULL, PRIMARY KEY (tbl, pk), KEY changed (changed)) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    f"INSERT INTO {quote(ORIGIN)} (tbl, pk, created, changed, files, gone) "
    f"SELECT a.tbl, a.pk, IF(f.act = 'I', f.file, NULL), l.file, a.files, l.act = 'D' "
    f"FROM (SELECT tbl, pk, MIN(seq) lo, MAX(seq) hi, COUNT(DISTINCT file) files FROM {quote(LOG)} WHERE pk <> '*' GROUP BY tbl, pk) a "
    f"JOIN {quote(LOG)} f ON f.seq = a.lo JOIN {quote(LOG)} l ON l.seq = a.hi",
]


def table_keys(db, build):
    """{table: (key columns, exact, all columns)} of every tracked table of the scratch database."""
    name = sql_string(build)
    columns, indexes = {}, {}
    for row in db.query(f"SELECT c.TABLE_NAME t, c.COLUMN_NAME c FROM information_schema.COLUMNS c JOIN information_schema.TABLES x "
                        f"ON x.TABLE_SCHEMA = c.TABLE_SCHEMA AND x.TABLE_NAME = c.TABLE_NAME WHERE c.TABLE_SCHEMA = {name} "
                        f"AND x.TABLE_TYPE = 'BASE TABLE' ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION", build):
        columns.setdefault(row['t'], []).append(row['c'])
    for row in db.query(f"SELECT TABLE_NAME t, INDEX_NAME i, NON_UNIQUE n, SEQ_IN_INDEX s, COLUMN_NAME c FROM information_schema.STATISTICS "
                        f"WHERE TABLE_SCHEMA = {name}", build):
        if row['c'] is None:      # a functional index part has no column
            continue
        index = indexes.setdefault(row['t'], {}).setdefault(row['i'], {'unique': str(row['n']) == '0', 'columns': []})
        index['columns'].append((int(row['s']), row['c']))
    return {table: choose_key(indexes.get(table, {}), cols) + (cols,) for table, cols in columns.items() if table not in UNTRACKED}


def untriggered(db, build):
    """Tracked tables that have no trigger of ours: new, dropped and created again, or altered by the file just run."""
    name = sql_string(build)
    rows = db.query(f"SELECT t.TABLE_NAME t FROM information_schema.TABLES t WHERE t.TABLE_SCHEMA = {name} AND t.TABLE_TYPE = 'BASE TABLE' "
                    f"AND NOT EXISTS (SELECT 1 FROM information_schema.TRIGGERS g WHERE g.TRIGGER_SCHEMA = t.TABLE_SCHEMA "
                    f"AND g.EVENT_OBJECT_TABLE = t.TABLE_NAME AND g.TRIGGER_NAME LIKE 'ftr\\\\_%')", build)
    return sorted({row['t'] for row in rows} - set(UNTRACKED))


def add_triggers(tables, keys):
    statements = []
    for table in tables:
        key, exact, columns = keys[table]
        statements += trigger_statements(table, key, columns)
        statements.append(f"REPLACE INTO {quote(TABLES)} (tbl, key_columns, exact) VALUES ({sql_string(table)}, {sql_string(','.join(key))}, {int(exact)})")
    return statements


def run(db, build, statements):
    if statements:
        db.execute(';\n'.join(statements) + ';\n', build)


# ------------------------------------------------------------------ the replay
def replay(db, build, dump, folders, protected=(), keep_going=False, trust_account=False, log=lambda message: None):
    """Builds the scratch database `build` from the release dump and the update files of `folders` ([(label, folder)]).

    Returns {'files': n, 'failed': [(name, error)], 'rows': n}. With `keep_going` a failing file is recorded and
    the replay goes on; without it the replay stops there, as the core's updater would. `trust_account` skips the
    check of the account's rights: only for a throwaway server that holds nothing else.
    """
    check_name(build, protected)
    definers = check_dump(dump)
    collect(folders)
    visible = [row['d'] for row in db.query('SELECT SCHEMA_NAME d FROM information_schema.SCHEMATA', 'information_schema')]
    if build.lower() in {d.lower() for d in visible}:
        tables = [row['t'] for row in db.query(f"SELECT TABLE_NAME t FROM information_schema.TABLES WHERE LOWER(TABLE_SCHEMA) = {sql_string(build.lower())}",
                                               'information_schema')]
        if tables and FILES not in tables:
            raise ReplayError(f'database {build} exists and was not made by a replay: it is left alone')
    if not trust_account:
        problems = check_account(db, build)
        if problems:
            raise ReplayError('the MySQL account can write outside the scratch database (' + '; '.join(problems) + '). Give the build an account '
                              f'of its own with rights on {build} only ([build] user and password)')
        problems = check_server(db)
        if problems:
            raise ReplayError('; '.join(problems))
    log(f'creating {build}')
    db.execute(f'DROP DATABASE IF EXISTS {quote(build)};\nCREATE DATABASE {quote(build)} CHARACTER SET utf8mb4;\n', 'information_schema')
    run(db, build, SETUP)                                   # first, so an interrupted replay is still known as ours
    log(f'loading {os.path.basename(dump)}')
    if definers:
        with tempfile.TemporaryDirectory() as folder:
            cleaned = os.path.join(folder, os.path.basename(dump))
            without_definers(dump, cleaned)
            db.execute_file(cleaned, build)
    else:
        db.execute_file(dump, build)
    applied = {}
    if db.query("SHOW TABLES LIKE 'updates'", build):
        for row in db.query('SELECT name, hash FROM updates', build):
            applied[row['name']] = row.get('hash') or ''
    files = plan(folders, applied)
    keys = table_keys(db, build)
    run(db, build, add_triggers(untriggered(db, build), keys))
    log(f'{len(files)} update files to run ({len(applied)} listed by the release)')
    failed = []
    for number, (name, path, label) in enumerate(files, 1):
        with open(path, 'rb') as handle:
            raw = handle.read()
        digest = hashlib.sha256(raw).hexdigest()
        if raw.startswith(b'\xef\xbb\xbf'):
            raw = raw[3:]
        text = raw.decode('latin-1')          # bytes kept as they are: only ASCII syntax is read
        before = [f"INSERT INTO {quote(FILES)} (id, name, source, sha256) VALUES ({number}, {sql_string(name)}, {sql_string(label)}, '{digest}')"]
        error, kinds = None, {}
        try:
            safe = guard(text, build, visible)
        except ReplayError as refused:
            error = f'refused: {refused}'
            run(db, build, before)
        else:
            names = {table.lower(): table for table in keys}          # as the server may read them, whatever their case
            for table, k in structural(text).items():
                if table.lower() in names:
                    kinds.setdefault(names[table.lower()], set()).update(k)
            before.append(f'SET @ft_file = {number}')
            for table, k in sorted(kinds.items()):
                if k & {'T', 'R'}:                         # the rows the file is about to remove, which no trigger will see
                    before.append(log_rows(table, keys[table][0], 'D', number))
                if 'A' in k:                               # a column our triggers name may go: follow the table again afterwards
                    before += drop_triggers(table)
            before.append('BEGIN')                         # as the updater does: a failing file takes its row changes back
            try:
                db.execute((';\n'.join(before) + ';\n').encode('utf-8') + safe.encode('latin-1') + b'\nCOMMIT;\n', build)
            except RuntimeError as broke:
                error = str(broke).strip()[:2000]
        fresh = untriggered(db, build)
        if fresh or kinds:
            existed, keys = keys, table_keys(db, build)
            after = []
            for table, k in sorted(kinds.items()):
                if k & {'T', 'R'} and table in keys and table not in fresh:
                    after.append(forget_unremoved(table, keys[table][0], number))
                    if 'T' in k:                           # emptied, when rows it held are gone
                        after.append(f"INSERT INTO {quote(LOG)} (tbl, pk, act, file) SELECT {sql_string(table)}, '*', 'T', {number} FROM DUAL "
                                     f"WHERE EXISTS (SELECT 1 FROM {quote(LOG)} WHERE tbl = {sql_string(table)} AND file = {number} AND act = 'D')")
            for table in fresh:
                k = kinds.get(table, set())
                if table in existed and k <= {'A', 'a'}:   # only altered: its rows are whose they were
                    after.append(log_event(table, 'A', number))
                else:                                       # created, or dropped and created again: its rows are this file's
                    after.append(log_event(table, 'R', number))
                    after.append(log_rows(table, keys[table][0], 'I', number))
            # a key or a column list that changed under triggers that stayed: follow the table by its new ones
            reshaped = [table for table in keys if table in existed and table not in fresh and keys[table] != existed[table]]
            run(db, build, after + add_triggers(fresh + reshaped, keys))
        state = 'failed' if error else 'applied'
        run(db, build, [f"UPDATE {quote(FILES)} SET state = '{state}', error = {sql_string(error) if error else 'NULL'} WHERE id = {number}"])
        if error:
            failed.append((name, error))
            log(f'FAILED {name}: {error[:300]}')
            if not keep_going:
                break
        elif number % 100 == 0:
            log(f'{number} / {len(files)}')
    run(db, build, SUMMARISE)
    rows = int(db.query(f'SELECT COUNT(*) n FROM {quote(ORIGIN)}', build)[0]['n'])
    return {'files': len(files), 'failed': failed, 'rows': rows}


def summary(db, build):
    """[(source label, rows created, rows changed, rows removed)] of a finished replay, by the last file that
    touched each row."""
    rows = db.query(f"SELECT f.source s, SUM(o.created = o.changed AND NOT o.gone) made, "
                    f"SUM((o.created IS NULL OR o.created <> o.changed) AND NOT o.gone) changed, SUM(o.gone) gone "
                    f"FROM {quote(ORIGIN)} o JOIN {quote(FILES)} f ON f.id = o.changed GROUP BY f.source ORDER BY f.source", build)
    return [(r['s'], int(r['made'] or 0), int(r['changed'] or 0), int(r['gone'] or 0)) for r in rows]


def why(db, build, table, key):
    """Where a row comes from: {'key_columns', 'exact', 'origin', 'history': [(act, file name, source)], 'table_events'}.
    `key` is the row's key values in the order of the table's key columns; origin is 'release' or a file name."""
    known = db.query(f'SELECT key_columns, exact FROM {quote(TABLES)} WHERE tbl = {sql_string(table)}', build)
    if not known:
        raise ReplayError(f'{table}: not a table of the replay')
    pk = ','.join(str(part) for part in key)[:KEY_LENGTH]
    select = (f"SELECT l.act a, f.name n, f.source s FROM {quote(LOG)} l LEFT JOIN {quote(FILES)} f ON f.id = l.file "
              f"WHERE l.tbl = {sql_string(table)} AND l.pk = %s ORDER BY l.seq")
    history = [(r['a'], r['n'] or 'outside a file', r['s'] or '') for r in db.query(select % sql_string(pk), build)]
    events = [(r['a'], r['n'] or 'outside a file', r['s'] or '') for r in db.query(select % "'*'", build)]
    origin = history[0][1] if history and history[0][0] == 'I' else 'release'
    if not history:           # nothing logged: the release's row, or no row at all
        columns = known[0]['key_columns'].split(',')
        where = ' AND '.join(f'{quote(c)} = {sql_string(v)}' for c, v in zip(columns, key))
        try:
            there = len(key) == len(columns) and db.query(f'SELECT 1 x FROM {quote(table)} WHERE {where} LIMIT 1', build)
        except RuntimeError:  # the table is gone
            there = False
        if not there:
            origin = 'no such row'
    return {'key_columns': known[0]['key_columns'].split(','), 'exact': str(known[0]['exact']) == '1', 'origin': origin,
            'history': history, 'table_events': events}
