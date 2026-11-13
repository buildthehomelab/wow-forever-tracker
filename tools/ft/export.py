"""The world build's export: the decisions that are ready, written as update files for a data repository.

`world resolve` stores what the world should hold and does not (ft/resolve.py). This module turns the decisions with
the verdict `add` into the kind of file the core's updater applies from sql/custom/world, one per export and set:

    <out>/sql/world/YYYY_MM_DD_NNN_world_everlake_build.sql            what may be published
    <private out>/sql/world/YYYY_MM_DD_NNN_world_everlake_build_private.sql   what only an unlicensed source states
    <folder>/build/<the file's name>.json                              which decision each row carries, and why

The rules a file follows:

- Running it again changes nothing, and it never changes a row it did not add: each table's rows go through a
  temporary stage table and only the missing ones are inserted.
- A row goes in only while the world is as the decision saw it: its NPC or object and its quest exist, nothing else
  holds its place, and no earlier file added it before (a row the server's owners took out stays out).
- Every row it adds is recorded in the server's ledger `everlake_import_rows` (table, key, file, the rule that passed
  it and the sources that state it), and carries `VerifiedBuild` 0: it is not a recording of the server.
- Before a file is written its statements run twice on the replayed world, inside a transaction that is rolled back:
  a row the world refuses is left out and reported, and a second run that adds anything stops the export.
- A decision an earlier export in the same folder already carries is not written again.

What is written today: the quest starters and enders of NPCs and objects, and vendor items whose price a recording
of the live game shows to be money. Everything else that is ready is held back with its reason (quest rows and NPC
templates are not written yet, and what waits for them waits with them).

This module reads no configuration. Databases are reached through objects with `query(sql, database)`.
"""
import collections
import hashlib
import json
import os
import re

from . import facts, replay, resolve

LEDGER, STAGE, CHECK = 'everlake_import_rows', 'everlake_build_stage', 'everlake_build_check'
LEDGER_DDL = (
    "CREATE TABLE IF NOT EXISTS `everlake_import_rows` (\n"
    "  `tbl` varchar(64) NOT NULL COMMENT 'world table of the row',\n"
    "  `k1` bigint NOT NULL COMMENT 'the row''s key, in the table''s primary key order',\n"
    "  `k2` bigint NOT NULL DEFAULT '0',\n"
    "  `k3` bigint NOT NULL DEFAULT '0',\n"
    "  `k4` bigint NOT NULL DEFAULT '0',\n"
    "  `file` varchar(200) NOT NULL COMMENT 'the update file that added the row',\n"
    "  `note` varchar(255) NOT NULL DEFAULT '' COMMENT 'the sources that gave it',\n"
    "  PRIMARY KEY (`tbl`, `k1`, `k2`, `k3`, `k4`),\n"
    "  KEY `file` (`file`)\n"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Rows the Everlake world import added'")
FIRST, LAST = 950, 999                    # the day's numbers of build files: after every other file of the day
NAME = re.compile(r'^(\d{4}_\d{2}_\d{2})_(\d{3})_world_everlake_build(_private)?\.sql\Z')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}\Z')
SETS = ('public', 'private')
RELATIONS = {('gives', 'npc'): 'creature_queststarter', ('takes', 'npc'): 'creature_questender',
             ('gives', 'object'): 'gameobject_queststarter', ('takes', 'object'): 'gameobject_questender'}
VENDOR = 'npc_vendor'
ORDER = ('creature_queststarter', 'creature_questender', 'gameobject_queststarter', 'gameobject_questender', VENDOR)
QUESTGIVER_FLAG, VENDOR_FLAG, QUESTGIVER_OBJECT = 2, 128, 2
BATCH = 200
REFUSED = ('the replayed world does not take it: it holds the row by now, an earlier file added it and it was taken out since, '
           'or something else holds its place')

Row = collections.namedtuple('Row', 'table key note comment allowed decision')
Held = collections.namedtuple('Held', 'decision reason')


class ExportError(Exception):
    pass


# ------------------------------------------------------------------ what can be written
def label(witness):
    return witness['source'] + (':' + witness['part'] if witness.get('part') else '') + (f"@{witness['build']}" if witness.get('build') else '')


def named(decision, allowed):
    """The witnesses a row of this set may name. A file that may be published names only sources that may be: a
    private or reference source that also witnessed the row stays out of the file, its note and its manifest."""
    return [w for w in decision['witnesses'] if allowed == 'private' or w.get('use') == 'public']


def note(decision, allowed='private'):
    """The ledger's note of a row: the rule that passed it and who states it."""
    return (decision['rule'] + ': ' + ', '.join(label(w) for w in named(decision, allowed)))[:255]


def priced(windows):
    """(why the item cannot be written as a plain vendor row, or '', whose word the price is: public or private).

    `windows` are the recordings of the vendor's window that list the item, as (use, build, listings). The newest
    recording a publishable source made gives the row, else the newest private one; a newer private recording that
    says otherwise holds it back. A plain row says "sold for money, in endless supply": it is only written when the
    recording says exactly that."""
    def read(listings):
        if not isinstance(listings, list) or not listings or not all(isinstance(entry, dict) for entry in listings):
            return 'its recording cannot be read'
        if len(listings) > 1:
            return 'the vendor lists it more than once: one row cannot say that'
        entry = listings[0]
        if entry.get('costItems') or entry.get('bartered'):
            return 'it costs items or a currency: the extended cost is not known'
        if entry.get('limited') or entry.get('stockMax'):
            return 'its stock is limited: the restock time is not known'
        if not isinstance(entry.get('costs'), dict) or not entry['costs']:
            return 'its recording shows no price'
        return ''

    newest = {use: max((w for w in windows if w[0] == use), key=lambda w: w[1], default=None) for use in ('public', 'private')}
    if not newest['public'] and not newest['private']:
        return 'no recording of the live game shows what it costs', 'public'
    whose = 'public' if newest['public'] else 'private'
    reason = read(newest[whose][2])
    if not reason and whose == 'public' and newest['private'] and newest['private'][1] > newest['public'][1]:
        reason = read(newest['private'][2])           # a newer recording says otherwise: it may not give the row, it can hold it back
    return reason, whose


def plan(ready, world, prices, extra):
    """(rows to write, what is held back) for the decisions that are ready.

    `ready` are stored decisions (dicts) with the verdict add; `world` is resolve.load_world's; `prices` is
    {(npc, item): [(use, build, listings)]}; `extra` holds what only the export asks the world: `borrowed` (the
    vendors whose list another vendor borrows), `quest_objects` (the objects of the quest giver kind) and `names`."""
    rows, held = [], []
    names = extra.get('names', {})

    def name(kind, number):
        return names.get((kind, number)) or f'{kind} {number}'

    def leftover(kind, number):          # the world's own row reads like a developer's leftover: it needs a person before anything hangs on it
        return bool(resolve.INTERNAL.search(names.get((kind, number)) or ''))

    for d in ready:
        kind, subject_kind, subject, other = d['kind'], d['subject_kind'], d['subject'], d['object']
        if kind == 'quest':
            held.append(Held(d, 'quest rows are not written yet'))
        elif kind == 'npc':
            held.append(Held(d, 'NPC templates are not written yet'))
        elif subject_kind == 'npc' and subject not in world['npcs']:
            held.append(Held(d, 'it waits for its NPC: NPC templates are not written yet'))
        elif leftover(subject_kind, subject):
            held.append(Held(d, f"the world's {'NPC' if subject_kind == 'npc' else subject_kind} reads like a developer's leftover: for a person"))
        elif kind in ('gives', 'takes') and leftover('quest', other):
            held.append(Held(d, "the world's quest reads like a developer's leftover: for a person"))
        elif (kind, subject_kind) in RELATIONS:
            if other not in world['quests']:
                held.append(Held(d, 'it waits for its quest: quest rows are not written yet'))
            elif subject_kind == 'object' and subject not in world['objects']:
                held.append(Held(d, 'its object has no template'))
            elif subject_kind == 'object' and subject not in extra['quest_objects']:
                held.append(Held(d, 'its object is not of the quest giver kind'))
            else:
                verb = 'gives' if kind == 'gives' else 'takes'
                rows.append(Row(RELATIONS[(kind, subject_kind)], (subject, other), note(d, d['allowed']),
                                f"{name(subject_kind, subject)} {verb} {name('quest', other)}", d['allowed'], d))
        elif kind == 'sells' and subject_kind == 'npc':
            reason, whose = priced(prices.get((subject, other), []))
            if subject in extra['borrowed']:
                reason = 'other vendors borrow its list: a row here would reach them too'
            if reason:
                held.append(Held(d, reason))
            else:
                allowed = 'private' if 'private' in (d['allowed'], whose) else 'public'
                rows.append(Row(VENDOR, (subject, other, 0, 1), note(d, allowed), f"{name('npc', subject)} sells {name('item', other)}", allowed, d))
        else:
            held.append(Held(d, 'no writer for this kind of decision'))
    return rows, held


# ------------------------------------------------------------------ the file
def quote(name):
    return '`' + name.replace('`', '``') + '`'


def comment(text):
    return re.sub(r'[\x00-\x1f\x7f]+', ' ', str(text))[:160].strip()


def literal(text):
    """A string for the file, read the same whatever the server's sql_mode: no backslash, no control character, a quote
    written twice."""
    return "'" + re.sub(r'[\x00-\x1f\x7f]+', ' ', str(text)).replace('\\', '/').replace("'", "''") + "'"


def staged(columns, rows):
    """The statements that fill the stage table: one line per row, its meaning beside it."""
    out = [f"CREATE TEMPORARY TABLE {quote(STAGE)} (`n` INT NOT NULL PRIMARY KEY, "
           + ', '.join(f'{quote(c)} BIGINT NOT NULL' for c in columns) + ", `note` VARCHAR(255) NOT NULL, `missing` TINYINT NOT NULL DEFAULT 0)"]
    head = f"INSERT INTO {quote(STAGE)} (`n`, {', '.join(quote(c) for c in columns)}, `note`) VALUES\n"
    for start in range(0, len(rows), BATCH):
        lines = []
        for offset, (values, text, about) in enumerate(rows[start:start + BATCH]):
            last = start + offset == min(start + BATCH, len(rows)) - 1
            lines.append(f"({start + offset + 1}, {', '.join(str(int(v)) for v in values)}, {literal(text)}){'' if last else ','} -- {comment(about)}")
        out.append(head + '\n'.join(lines) + '\n')            # the line break keeps the statement's end out of the last comment
    return out


def ledger(table, keys, file):
    columns = ', '.join(f'`k{i + 1}`' for i in range(len(keys)))
    return (f"INSERT INTO {quote(LEDGER)} (`tbl`, {columns}, `file`, `note`) SELECT {literal(table)}, {', '.join(keys)}, "
            f"{literal(file)}, s.`note` FROM {quote(STAGE)} s WHERE s.`missing` = 1")


def never_again(table, keys):
    return (f"NOT EXISTS (SELECT 1 FROM {quote(LEDGER)} r WHERE r.`tbl` = {literal(table)} AND "
            + ' AND '.join(f'r.`k{i + 1}` = {key}' for i, key in enumerate(keys)) + ')')


def relation_block(table, rows, file):
    """A quest starter or ender table: the pair goes in while it is missing, its NPC or object and its quest exist, and
    no file added it before. An NPC that gets its first quest this way also gets the quest giver flag."""
    creature = table.startswith('creature_')
    parent = ("EXISTS (SELECT 1 FROM `creature_template` c WHERE c.`entry` = s.`id`)" if creature else
              f"EXISTS (SELECT 1 FROM `gameobject_template` g WHERE g.`entry` = s.`id` AND g.`type` = {QUESTGIVER_OBJECT})")
    out = staged(('id', 'quest'), [(row.key, row.note, row.comment) for row in rows])
    out.append(f"UPDATE {quote(STAGE)} s SET s.`missing` = 1 WHERE NOT EXISTS (SELECT 1 FROM {quote(table)} t WHERE t.`id` = s.`id` AND t.`quest` = s.`quest`) "
               f"AND {never_again(table, ('s.`id`', 's.`quest`'))} AND {parent} AND EXISTS (SELECT 1 FROM `quest_template` q WHERE q.`ID` = s.`quest`)")
    out.append(f"INSERT INTO {quote(table)} (`id`, `quest`, `VerifiedBuild`) SELECT s.`id`, s.`quest`, 0 FROM {quote(STAGE)} s WHERE s.`missing` = 1 ORDER BY s.`n`")
    if creature:
        out.append(f"UPDATE `creature_template` c JOIN {quote(STAGE)} s ON s.`id` = c.`entry` SET c.`npcflag` = c.`npcflag` | {QUESTGIVER_FLAG} "
                   f"WHERE s.`missing` = 1 AND (c.`npcflag` & {QUESTGIVER_FLAG}) = 0")
    out += [ledger(table, ('s.`id`', 's.`quest`'), file), f'DROP TEMPORARY TABLE {quote(STAGE)}']
    return out


def vendor_block(rows, file):
    """Vendor items sold for money in endless supply: the item goes in while the vendor does not list it at any
    price, nobody borrows the vendor's list, and no file added it before. Slots continue after the vendor's last one,
    counted when the file runs. A vendor that gets its first item this way also gets the vendor flag."""
    seq, lines = collections.Counter(), []
    for row in rows:
        seq[row.key[0]] += 1
        lines.append(((row.key[0], seq[row.key[0]], row.key[1]), row.note, row.comment))
    out = staged(('entry', 'seq', 'item'), lines)
    out.append(f"UPDATE {quote(STAGE)} s SET s.`missing` = 1 WHERE NOT EXISTS (SELECT 1 FROM `npc_vendor` t WHERE t.`entry` = s.`entry` AND t.`item` = s.`item` AND t.`type` = 1) "
               f"AND {never_again(VENDOR, ('s.`entry`', 's.`item`', '0', '1'))} "
               f"AND NOT EXISTS (SELECT 1 FROM `npc_vendor` b WHERE b.`item` = -s.`entry`) AND EXISTS (SELECT 1 FROM `creature_template` c WHERE c.`entry` = s.`entry`)")
    out.append("INSERT INTO `npc_vendor` (`entry`, `slot`, `item`, `maxcount`, `incrtime`, `ExtendedCost`, `type`, `PlayerConditionID`, `IgnoreFiltering`, `VerifiedBuild`) "
               "SELECT s.`entry`, (SELECT COALESCE(MAX(v.`slot`), 0) FROM `npc_vendor` v WHERE v.`entry` = s.`entry`) + s.`seq`, s.`item`, 0, 0, 0, 1, 0, 0, 0 "
               f"FROM {quote(STAGE)} s WHERE s.`missing` = 1 ORDER BY s.`n`")
    out.append(f"UPDATE `creature_template` c JOIN {quote(STAGE)} s ON s.`entry` = c.`entry` SET c.`npcflag` = c.`npcflag` | {VENDOR_FLAG} "
               f"WHERE s.`missing` = 1 AND (c.`npcflag` & {VENDOR_FLAG}) = 0")
    out += [ledger(VENDOR, ('s.`entry`', 's.`item`', '0', '1'), file), f'DROP TEMPORARY TABLE {quote(STAGE)}']
    return out


def body(rows, file):
    """The statements that add the rows, table by table, without the transaction around them."""
    out = []
    for table in ORDER:
        mine = sorted((row for row in rows if row.table == table), key=lambda row: row.key)
        if mine:
            out += vendor_block(mine, file) if table == VENDOR else relation_block(table, mine, file)
    return out


def counts(rows):
    by = collections.Counter(row.table for row in rows)
    return ', '.join(f'{by[table]} {table}' for table in ORDER if by[table])


def text(file, rows, pins, credits, against, private=False):
    """The whole update file."""
    head = [f'-- World build: {len(rows)} rows the server world lacks ({counts(rows)})',
            f"-- {file}: generated by the ForeverTracker (python tools/tracker.py world export) from {'' if private else 'public '}WoW Forever data.",
            '-- Sources (pins): ' + comment(', '.join(f'{source} {str(pin)[:20]}' for source, pin in sorted(pins.items()))),
            f'-- Written against the replayed world: {comment(against)}.']
    if private:
        head.append('-- PRIVATE SET: these rows rest on a source without a licence to publish. Not for a public repository.')
    head += [f'-- {comment(line)}' for line in credits]
    head += ['-- Game names and text belong to Blizzard Entertainment.',
             '-- Each row is recorded in `everlake_import_rows` with the rule that passed it and the sources that state it.',
             '-- Never edit this file once it is deployed (the updater would run it and every later custom file again):',
             '-- a later fix is a new file. Running it again changes nothing.']
    return '\n'.join(head) + '\n' + LEDGER_DDL + ';\nSTART TRANSACTION;\n' + ';\n'.join(body(rows, file)) + ';\nCOMMIT;\n'


# ------------------------------------------------------------------ names, numbers, earlier exports
def file_name(date, number, private=False):
    """The public file sorts before the private one of the same export ('.' comes before '_'), as it must: a private
    row may need a public one, never the other way round."""
    if not DATE.match(date):
        raise ExportError(f'{date}: write the date as YYYY-MM-DD')
    return f"{date.replace('-', '_')}_{number:03d}_world_everlake_build{'_private' if private else ''}.sql"


def next_number(folders, date):
    """The day's next free number, the same for both sets. A number is used once a file or a manifest carries it: the
    file may have moved on to the data repository while its manifest stayed."""
    if not DATE.match(date):
        raise ExportError(f'{date}: write the date as YYYY-MM-DD')
    day, used = date.replace('-', '_'), set()
    for folder in folders:
        for path, ending in ((os.path.join(folder, 'sql', 'world'), ''), (os.path.join(folder, 'build'), '.json')):
            for entry in os.listdir(path) if os.path.isdir(path) else ():
                match = NAME.match(entry[:-len(ending)] + '.sql' if ending and entry.endswith(ending) else entry)
                if match and match.group(1) == day:
                    used.add(int(match.group(2)))
    number = max(used | {FIRST - 1}) + 1
    if number > LAST:
        raise ExportError(f'{date}: every number from {FIRST} to {LAST} is used: export again tomorrow, or with --date')
    return number


def carried(folders):
    """{(table, key): file} of the rows the earlier exports in these folders carry, from their manifests."""
    out = {}
    for folder in folders:
        path = os.path.join(folder, 'build')
        for entry in sorted(os.listdir(path)) if os.path.isdir(path) else ():
            if not entry.endswith('.json') or not NAME.match(entry[:-5] + '.sql'):          # only the manifests of build files
                continue
            try:
                with open(os.path.join(path, entry), encoding='utf-8') as handle:
                    manifest = json.load(handle)
                for row in manifest['rows']:
                    out[(row['table'], tuple(int(k) for k in row['key']))] = manifest['file']
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ExportError(f'{os.path.join(path, entry)} is not an export manifest ({error}): repair or remove it first')
    return out


def manifest(file, content, kind, rows, pins, against, held):
    return {'file': file, 'sha1': hashlib.sha1(content.encode('utf-8')).hexdigest(), 'set': kind,
            'generator': 'ForeverTracker: python tools/tracker.py world export', 'sources': dict(sorted(pins.items())), 'world': against,
            'rows': [{'table': row.table, 'key': list(row.key), 'kind': row.decision['kind'], 'rule': row.decision['rule'],
                      'witnesses': [label(w) for w in named(row.decision, kind)], 'says': row.comment}
                     for row in sorted(rows, key=lambda row: (ORDER.index(row.table), row.key))],
            'held_back': dict(sorted(collections.Counter(h.reason for h in held).items()))}


# ------------------------------------------------------------------ reading both sides
def load_ready(db, database='tracker'):
    out = []
    for row in db.query(f"SELECT * FROM {resolve.DECISIONS} WHERE verdict = 'add' ORDER BY kind, subject_kind, subject, object", database):
        row.update(subject=int(row['subject']), object=int(row['object']), witnesses=json.loads(row['witnesses']))
        out.append(row)
    return out


def load_prices(db, registry, database='tracker'):
    """{(npc, item): [(use, build, listings)]}: the recordings of the live game that show a vendor's window."""
    out = collections.defaultdict(list)
    for row in db.query(f"SELECT source, subject, object, build, data FROM {facts.FACTS} WHERE kind = 'sells' AND subject_kind = 'npc'", database):
        if row['source'] not in registry.sources:
            continue
        use, build = registry.source(row['source'])['use'], int(row['build'])
        if use == 'reference' or not registry.witness(row['source'], '', build)[1]:
            continue
        try:
            listings = json.loads(row['data']).get('listings')
        except (ValueError, AttributeError):
            listings = None
        out[(int(row['subject']), int(row['object']))].append((use, build, listings))
    return out


def load_pins(db, sources, database='tracker'):
    wanted = ', '.join(facts.sql_value(s) for s in sorted(sources)) or "''"
    return {row['source']: row['pin'] for row in db.query(f'SELECT source, pin FROM {facts.SOURCES} WHERE source IN ({wanted})', database)}


def load_extra(db, build, ready, tracker=None, registry=None, database='tracker'):
    """What only the export asks: the vendors whose list is borrowed, the quest giver objects, and the names of what
    the ready decisions speak of (item names come from the vendor recordings of sources that may be published: the
    world database holds none)."""
    numbers = lambda sql: {int(next(iter(row.values()))) for row in db.query(sql, build)}
    names = {}
    ids = collections.defaultdict(set)
    for d in ready:
        ids[d['subject_kind']].add(d['subject'])
        ids['quest' if d['kind'] in ('gives', 'takes') else 'item' if d['kind'] == 'sells' else ''].add(d['object'])
    for kind, sql in (('npc', 'SELECT entry id, name FROM creature_template WHERE entry IN ({})'),
                      ('object', 'SELECT entry id, name FROM gameobject_template WHERE entry IN ({})'),
                      ('quest', 'SELECT ID id, LogTitle name FROM quest_template WHERE ID IN ({})')):
        wanted = sorted(ids[kind])
        for start in range(0, len(wanted), 2000):
            for row in db.query(sql.format(', '.join(map(str, wanted[start:start + 2000]))), build):
                names[(kind, int(row['id']))] = row['name'] or ''
    if tracker is not None and ids['item']:
        for row in tracker.query(f"SELECT source, object id, JSON_UNQUOTE(JSON_EXTRACT(data, '$.listings[0].name')) name FROM {facts.FACTS} "
                                 f"WHERE kind = 'sells' AND JSON_EXTRACT(data, '$.listings[0].name') IS NOT NULL ORDER BY source, build", database):
            public = registry is not None and row['source'] in registry.sources and registry.source(row['source'])['use'] == 'public'
            if public and int(row['id']) in ids['item'] and row['name'] not in (None, 'null'):
                names[('item', int(row['id']))] = row['name']
    return {'borrowed': numbers('SELECT DISTINCT -item FROM npc_vendor WHERE item < 0'),
            'quest_objects': numbers(f'SELECT entry FROM gameobject_template WHERE type = {QUESTGIVER_OBJECT}'), 'names': names}


def replayed(db, build):
    """What the replayed world is made of, for the file's header and manifest: {'files': n, 'newest': name}."""
    rows = db.query(f"SELECT COUNT(*) n, MAX(name) newest FROM {replay.FILES} WHERE state = 'applied'", build)
    return {'files': int(rows[0]['n']), 'newest': rows[0]['newest'] or ''}


# ------------------------------------------------------------------ the trial on the replayed world
def trial(db, build, files):
    """Runs the statements of `files` ([(file name, rows)], in the order the updater would) twice on the replayed
    world, inside a transaction that is rolled back. Returns {file: the (table, key) it added on the first run}.
    Raises ExportError when the second run changes anything, when a row went in unrecorded, or when the world is
    not what it was once the transaction is rolled back."""
    tables = [table for table in ORDER if any(row.table == table for _file, rows in files for row in rows)]
    if not tables:
        return {file: set() for file, _rows in files}
    names = ', '.join(literal(file) for file, _rows in files)
    has_ledger = bool(db.query(f"SHOW TABLES LIKE '{LEDGER}'", build))
    # what is measured before, between and after the runs: the rows of each table, and the two flags the file may set
    measures = [(table, f'SELECT COUNT(*) FROM {quote(table)}') for table in tables]
    measures.append(('creature_template flags', f'SELECT COALESCE(SUM(`npcflag` & {QUESTGIVER_FLAG | VENDOR_FLAG}), 0) FROM `creature_template`'))
    kept = {label: int(next(iter(db.query(sql, build)[0].values()))) for label, sql in measures}
    script = []
    if has_ledger:
        known = sorted(row['file'] for row in db.query(f'SELECT DISTINCT file FROM {quote(LEDGER)} WHERE file IN ({names})', build))
        if known:                           # two different files of one name: the updater would run the second as a changed first
            raise ExportError(f"the world already applied a file named {known[0]}: export under another --date")
        kept[LEDGER] = int(db.query(f'SELECT COUNT(*) n FROM {quote(LEDGER)}', build)[0]['n'])
    else:                                   # a world no import file has reached yet: a stand-in for the trial
        script.append(LEDGER_DDL.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE'))
    script += [f'CREATE TEMPORARY TABLE {quote(CHECK)} (step INT NOT NULL, tbl VARCHAR(64) NOT NULL, a BIGINT NOT NULL, b BIGINT NOT NULL DEFAULT 0, '
               'c BIGINT NOT NULL DEFAULT 0, d BIGINT NOT NULL DEFAULT 0, file VARCHAR(200) NOT NULL DEFAULT \'\')', 'START TRANSACTION']
    count = lambda step: [f"INSERT INTO {quote(CHECK)} (step, tbl, a) {sql.replace('SELECT ', f'SELECT {step}, {literal(label)}, ', 1)}" for label, sql in measures]
    run = [statement for file, rows in files for statement in body(rows, file)]
    script += count(0) + run + count(1) + run + count(2)
    script += [f"INSERT INTO {quote(CHECK)} (step, tbl, a, b, c, d, file) SELECT 9, tbl, k1, k2, k3, k4, file FROM {quote(LEDGER)} WHERE file IN ({names})",
               f'SELECT step, tbl, a, b, c, d, file FROM {quote(CHECK)} ORDER BY step, tbl', 'ROLLBACK']
    try:
        result = db.script(';\n'.join(script) + ';\n', build)
    except RuntimeError as error:
        raise ExportError(f'the replayed world refuses the file: {str(error).strip()}')
    finally:                                # whatever happened, the world must be what it was: a table that does not roll back would keep the rows
        after = {label: int(next(iter(db.query(sql, build)[0].values()))) for label, sql in measures}
        if has_ledger:
            after[LEDGER] = int(db.query(f'SELECT COUNT(*) n FROM {quote(LEDGER)}', build)[0]['n'])
        left = ', '.join(f'{label} {kept[label]} -> {after[label]}' for label in kept if kept[label] != after[label])
        if left:
            raise ExportError(f'THE TRIAL CHANGED THE REPLAYED WORLD ({left}): a table there does not roll back. Replay the world again before anything else')
    seen = {step: {row['tbl']: int(row['a']) for row in result if int(row['step']) == step} for step in (0, 1, 2)}
    if seen[1] != seen[2]:
        moved = ', '.join(f'{t} {seen[1][t]} -> {seen[2][t]}' for t in seen[1] if seen[1][t] != seen[2].get(t))
        raise ExportError(f'running the file a second time changed the world ({moved}): nothing is written')
    added = {file: set() for file, _rows in files}
    width = {table: 4 if table == VENDOR else 2 for table in ORDER}
    for row in result:
        if int(row['step']) == 9:
            key = tuple(int(row[c]) for c in 'abcd')[:width[row['tbl']]]
            added[row['file']].add((row['tbl'], key))
    for table in tables:                    # every row the tables gained is in the ledger: nothing went in unrecorded
        gained, recorded = seen[1][table] - seen[0][table], sum(1 for keys in added.values() for t, _key in keys if t == table)
        if gained != recorded:
            raise ExportError(f'{table} gained {gained} rows and the ledger records {recorded}: nothing is written')
    return added


def export(db, build, tracker, registry, world, folders, date, write=True, database='tracker'):
    """Plans, tries and writes one export. `folders` is {'public': folder, 'private': folder}. Returns a dict:
    files ({set: (path, rows)}), held ([Held]), earlier (how many rows an earlier export carries), refused ([Row])."""
    ready = load_ready(tracker, database)
    extra = load_extra(db, build, ready, tracker, registry, database)
    rows, held = plan(ready, world, load_prices(tracker, registry, database), extra)
    before = carried(folders.values())
    earlier = [row for row in rows if (row.table, row.key) in before]
    rows = sorted((row for row in rows if (row.table, row.key) not in before), key=lambda row: (ORDER.index(row.table), row.key))      # the file's order
    number = next_number(folders.values(), date)
    names = {kind: file_name(date, number, kind == 'private') for kind in SETS}
    split = lambda: [(names[kind], [row for row in rows if row.allowed == kind]) for kind in SETS]
    added = trial(db, build, split())
    refused = [row for row in rows if (row.table, row.key) not in added[names[row.allowed]]]
    if refused:                             # the world is not as the decision saw it (an earlier file added the row and it was taken out since)
        rows = [row for row in rows if row not in refused]
        held += [Held(row.decision, REFUSED) for row in refused]
        added = trial(db, build, split())
        if any((row.table, row.key) not in added[names[row.allowed]] for row in rows):
            raise ExportError('the replayed world refuses rows it accepted a moment ago: nothing is written')
    against = replayed(db, build)
    files, writes = {}, []
    for kind, (file, mine) in zip(SETS, split()):
        if not mine:
            continue
        sources = {w['source'] for row in mine for w in named(row.decision, kind)}
        pins = load_pins(tracker, sources, database)
        content = text(file, mine, pins, registry.credits(sorted(sources)), f"{against['files']} update files, the newest {against['newest']}", kind == 'private')
        path = os.path.join(folders[kind], 'sql', 'world', file)
        about = json.dumps(manifest(file, content, kind, mine, pins, against, held), indent=1, sort_keys=True, ensure_ascii=False) + '\n'
        writes += [(path, content), (os.path.join(folders[kind], 'build', file[:-4] + '.json'), about)]
        files[kind] = (path, mine)
    if write:
        taken = [path for path, _data in writes if os.path.lexists(path)]
        if taken:                           # checked for every file before the first is written: never half an export
            raise ExportError(f'{taken[0]} exists: a written file is never replaced')
        done = []
        try:
            for path, data in writes:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'x', encoding='utf-8', newline='\n') as handle:
                    handle.write(data)
                done.append(path)
        except OSError as error:
            for path in done:               # a file without its manifest would be exported again: all of them or none
                os.remove(path)
            raise ExportError(f'{error}: nothing is left written')
    return {'files': files, 'held': held, 'earlier': earlier, 'refused': refused}
