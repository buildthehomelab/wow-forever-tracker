"""Tiny MySQL access through the mysql command-line client (no Python driver needed)."""
import os
import re
import shutil
import subprocess
import tempfile

from .config import CONFIG


def _mysql():
    configured = CONFIG.server_path('mysql')
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which('mysql')
    if not found:
        raise SystemExit('mysql client not found: set [server] mysql in config.ini.')
    return found


def _client_file(account=None):
    """`account` is (user, password) of another MySQL account on the same server; None: the one of [database]."""
    user, password = account or (CONFIG.get('database', 'user'), CONFIG.get('database', 'password'))
    quoted = lambda value: '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'      # a # or a space would cut a bare value short
    handle = tempfile.NamedTemporaryFile('w', suffix='.cnf', delete=False, encoding='utf-8')
    handle.write('[client]\n'
                 f"host={CONFIG.get('database', 'host', '127.0.0.1')}\n"
                 f"port={CONFIG.get('database', 'port', '3306')}\n"
                 f"user={quoted(user)}\n"
                 f"password={quoted(password)}\n"
                 'default-character-set=utf8mb4\n')
    handle.close()
    return handle.name


_ESCAPE = re.compile(r'\\(.)', re.S)
_ESCAPES = {'t': '\t', 'n': '\n', '0': '\0', '\\': '\\'}


def _unescape(value):
    if value == 'NULL':
        return None
    # in one pass: replacing "\n" before "\\" would turn an escaped backslash followed by an n into a line break
    return _ESCAPE.sub(lambda match: _ESCAPES.get(match.group(1), match.group(0)), value)


def query(sql, database='world', account=None):
    """Rows as dicts (values are str or None). `database` is a key of [database] or a real name."""
    cnf = _client_file(account)
    try:
        result = subprocess.run([_mysql(), f'--defaults-extra-file={cnf}', '--batch', CONFIG.db(database), '-e', sql], capture_output=True)
        if result.returncode:
            raise RuntimeError(f"{sql[:120]}: {result.stderr.decode('utf-8', 'replace').strip()}")
        out = result.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')
    finally:
        os.unlink(cnf)
    lines = out.split('\n')
    if not lines or not lines[0]:
        return []
    header = lines[0].split('\t')
    return [dict(zip(header, map(_unescape, line.split('\t')))) for line in lines[1:] if line]


def script(sql, database, account=None):
    """Runs our own statements through the client's standard input and returns the rows of what they select, as query
    does: for a script too long for a command line. The client stops at the first statement that fails."""
    cnf = _client_file(account)
    try:
        result = subprocess.run([_mysql(), f'--defaults-extra-file={cnf}', '--batch', CONFIG.db(database)], input=sql.encode('utf-8'), capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip())
        out = result.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')
    finally:
        os.unlink(cnf)
    lines = out.split('\n')
    if not lines or not lines[0]:
        return []
    header = lines[0].split('\t')
    return [dict(zip(header, map(_unescape, line.split('\t')))) for line in lines[1:] if line]


def column(sql, database='world'):
    return [next(iter(row.values())) for row in query(sql, database)]


def has_table(name, database='world'):
    return bool(query(f"SHOW TABLES LIKE '{name}'", database))


def execute_file(path, database, account=None, binary=False):
    """`binary`: the file's bytes reach the server as they are and the client's own commands (source, system ...) are off."""
    cnf = _client_file(account)
    try:
        with open(path, 'rb') as handle:
            command = [_mysql(), f'--defaults-extra-file={cnf}'] + (['--binary-mode'] if binary else []) + [CONFIG.db(database)]
            result = subprocess.run(command, stdin=handle, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    finally:
        os.unlink(cnf)


def execute(sql, database, account=None):
    """Runs statements through the client's standard input. Text is our own SQL. Bytes are a file's content: they run
    in the client's binary mode, where the bytes reach the server as they are and the client's own commands (source,
    system ...) are off; DELIMITER still works."""
    cnf = _client_file(account)
    try:
        binary = isinstance(sql, bytes)
        command = [_mysql(), f'--defaults-extra-file={cnf}'] + (['--binary-mode'] if binary else []) + [CONFIG.db(database)]
        result = subprocess.run(command, input=sql if binary else sql.encode('utf-8'), capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    finally:
        os.unlink(cnf)


class Account:
    """The same calls under another MySQL account of the same server (the world build's own), for code that takes a
    database object. A file is always run in binary mode."""
    def __init__(self, user='', password=''):
        self.account = (user, password) if user else None

    def query(self, sql, database):
        return query(sql, database, self.account)

    def execute(self, sql, database):
        return execute(sql, database, self.account)

    def script(self, sql, database):
        return script(sql, database, self.account)

    def execute_file(self, path, database):
        return execute_file(path, database, self.account, binary=True)


def escape(value):
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if value == value else '0'
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r').replace('\0', '\\0') + "'"
