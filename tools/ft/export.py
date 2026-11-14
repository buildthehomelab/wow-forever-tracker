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

What is written today: the templates of NPCs that are friendly to players (ft/npcs.py: what the NPC looks like from
the record the server sent, its level from a source that states it, its faction a stand-in by side), quests
(ft/quests.py: the quest's row from the record, its objectives, levels, money and reward spells, and what its NPC
says at the turn-in where the live game's recordings have it in one wording), the quest starters
and enders of NPCs and objects, and vendor items sold for money in endless supply: a recording of the live game
shows it, or, where nobody recorded the vendor's window, the world's other vendors all sell the item that way.
Everything else that is ready is held back with its reason, and what waits for it waits with it.

This module reads no configuration. Databases are reached through objects with `query(sql, database)`.
"""
import collections
import hashlib
import json
import os
import re

from . import facts, npcs, quests, replay, resolve

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
VENDOR, QUEST, NPC = 'npc_vendor', 'quest_template', 'creature_template'
ORDER = (NPC, QUEST, 'creature_queststarter', 'creature_questender', 'gameobject_queststarter', 'gameobject_questender', VENDOR)     # what others need comes first
QUESTS, OBJECTIVES, NPCS, MODELS = 'everlake_build_quests', 'everlake_build_objectives', 'everlake_build_npcs', 'everlake_build_models'
NPC_CHILDREN = (('creature_template_difficulty', 'Entry', ('Entry', 'DifficultyID')), ('creature_template_model', 'CreatureID', ('CreatureID', 'Idx')),
                ('creature_classic_level', 'entry', ('entry',)))
# the tables a quest's own rows go to, with the column that names the quest and the key the ledger records
CHILDREN = (('quest_objectives', 'QuestID', ('ID',)), ('quest_classic_level', 'ID', ('ID',)), ('quest_template_classic_level', 'ID', ('ID', 'LevelType')),
            ('quest_classic_money', 'ID', ('ID',)), ('quest_reward_display_spell', 'QuestID', ('QuestID', 'Idx')), ('quest_template_addon', 'ID', ('ID',)))
# what the quest's NPC says when it is handed in and while it is not done yet: (table, the moment a recording calls it, the text's column).
# These come with a quest where a recording has them, and a quest is not refused for a text the world holds already.
TEXTS = (('quest_offer_reward', 'complete', 'RewardText'), ('quest_request_items', 'progress', 'CompletionText'))
# the tables with a VerifiedBuild column: 0, not a recording
VERIFIED = (QUEST, 'quest_objectives', 'quest_reward_display_spell', NPC, 'creature_template_difficulty', 'creature_template_model',
            'quest_offer_reward', 'quest_request_items')
KEYS = dict({table: 2 for table in ORDER}, **{QUEST: 1, NPC: 1, VENDOR: 4}, **{table: len(key) for table, _parent, key in CHILDREN + NPC_CHILDREN}, **{table: 1 for table, _moment, _column in TEXTS})
QUESTGIVER_FLAG, VENDOR_FLAG, QUESTGIVER_OBJECT = 2, 128, 2
# MySQL 8's default sql_mode, the one the core's updater applies update files in (its own connection, the server's default).
STRICT_MODE = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'
BATCH = 200
REFUSED = ('the replayed world does not take it: it holds the row by now, an earlier file added it and it was taken out since, '
           'or something else holds its place')

Row = collections.namedtuple('Row', 'table key note comment allowed decision data', defaults=(None,))
# how one vendor of the world lists an item: for money in endless supply (plain) or not; real = a spawned vendor, not a leftover
Listing = collections.namedtuple('Listing', 'npc plain real')
NO_RECORDING = 'no recording of the live game shows what it costs'
NOT_PLAIN = ('the vendor lists it more than once: one row cannot say that', 'it costs items or a currency: the extended cost is not known',
             'its stock is limited: the restock time is not known')
Held = collections.namedtuple('Held', 'decision reason')


def grouped(reason):
    """A reason without the one thing it names in brackets, for counting."""
    return re.sub(r' \([^()]*\)$', '', reason)


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


def listed(listings):
    """Why a recording of a vendor's window does not show the item as a plain sale, or ''."""
    if not isinstance(listings, list) or not listings or not all(isinstance(entry, dict) for entry in listings):
        return 'its recording cannot be read'
    if len(listings) > 1:
        return NOT_PLAIN[0]
    entry = listings[0]
    if entry.get('costItems') or entry.get('bartered'):
        return NOT_PLAIN[1]
    if entry.get('limited') or entry.get('stockMax'):
        return NOT_PLAIN[2]
    if not isinstance(entry.get('costs'), dict) or not entry['costs']:
        return 'its recording shows no price'
    return ''


def priced(windows):
    """(why a recording does not make the item a plain vendor row, or '', whose word the price is: public or private).

    `windows` are the recordings of the vendor's window that list the item, as (use, build, listings); only those of
    the live game by a source that may give rows count here (use public or private). The newest recording a
    publishable source made gives the row, else the newest private one; a newer private recording that says otherwise
    holds it back. A plain row says "sold for money, in endless supply": a recording gives it only when it says
    exactly that. With no recording, plan() asks the world's other vendors (elsewhere)."""
    newest = {use: max((w for w in windows if w[0] == use), key=lambda w: w[1], default=None) for use in ('public', 'private')}
    if not newest['public'] and not newest['private']:
        return NO_RECORDING, 'public'
    whose = 'public' if newest['public'] else 'private'
    reason = listed(newest[whose][2])
    if not reason and whose == 'public' and newest['private'] and newest['private'][1] > newest['public'][1]:
        reason = listed(newest['private'][2])         # a newer recording says otherwise: it may not give the row, it can hold it back
    return reason, whose


def said_before(windows):
    """What the newest recording that may not give a row (one from before the live game, or a reference's) says
    against a plain sale, or ''. It cannot give the row; it can keep the world's other vendors from giving it."""
    newest = max((w for w in windows if w[0] == 'other'), key=lambda w: w[1], default=None)
    reason = listed(newest[2]) if newest else ''
    return reason if reason in NOT_PLAIN else ''


def elsewhere(listings, vendor):
    """(why the world's other vendors do not say how the item is sold, or '', how many of them sell it).

    `listings` are the world's own vendor rows of the item (Listing), without the rows an export added. An item no
    recording shows the price of is still written as a plain row when the world already sells it: at least one other
    vendor that players can reach sells it, and every other vendor that lists it, reachable or not, does so for money,
    in endless supply. Measured on the world's own rows, a vendor's row is plain 13,252 times out of 13,270 when the
    item's other vendors say so."""
    others = [entry for entry in listings if entry.npc != vendor]
    real = {entry.npc for entry in others if entry.real}
    if not real:
        return NO_RECORDING + ', and no other vendor players can reach sells it', 0
    if not all(entry.plain for entry in others):
        return NO_RECORDING + ', and other vendors sell it for a currency, with a condition or in limited stock', 0
    return '', len(real)


def npc_row(decision, known, extra):
    """(Row, '') for an NPC that is ready, or (None, why it cannot be written). `known` is what load_npcs found for
    it: its record, its level and whom it is friendly to. `extra['model_info']` holds the display ids the world can
    show (creature_model_info): an NPC whose model is not among them could not be loaded."""
    npc = decision['subject']
    if not known or known.get('record') is None:
        return None, 'no record a row may be written from'
    friendly_to, whose = npcs.side(known.get('stated'), known.get('reactions'), known.get('talked'), known.get('fought', False), known.get('against', ()))
    if not friendly_to:
        return None, whose
    if not known.get('level'):
        return None, 'nothing states its level'
    made, problems = npcs.rows(npc, known['record'], known['level'][:2], friendly_to)
    if problems:
        return None, 'its record cannot be written: ' + problems[0]
    unknown = [model['CreatureDisplayID'] for model in made.models if model['CreatureDisplayID'] not in extra.get('model_info', ())]
    if unknown:
        return None, f"the world has no size for its model: creature_model_info (display {unknown[0]})"
    allowed = 'private' if 'private' in (decision['allowed'], known['use']) else 'public'
    data = {'npc': made, 'record': f"{known['source']}@{known['build']}", 'side': friendly_to, 'side_how': whose, 'side_from': known['side_source'] if whose == 'questie' else known['seen_source'],
            'level_from': known['level'][2]}
    data['sources'] = {known['source'], data['side_from'], data['level_from']} | ({known['seen_source']} if known.get('talked') is not None else set())
    return Row(NPC, (npc,), note(decision, allowed), made.template['name'], allowed, decision, data), ''


def quest_row(decision, known, world, arriving=()):
    """(Row, '') for a quest that is ready, or (None, why it cannot be written). `known` is what load_quests found
    for it: the record a row may be written from, and what QuestieDB adds. `arriving` holds the NPCs written with it."""
    quest = decision['subject']
    if not known:
        return None, 'no record a row may be written from'
    made, problems = quests.rows(quest, known['record'])
    if problems:
        return None, 'its record cannot be written: ' + problems[0]
    for kind, label_, there in (('npc', 'NPC', world['npcs']), ('object', 'object', world['objects'])):
        lacking = [number for number in quests.targets(made)[kind] if number not in there and not (kind == 'npc' and number in arriving)]
        if lacking:
            return None, f'an objective needs an {label_} that has no template ({label_} {lacking[0]})'
    allowed = 'private' if 'private' in (decision['allowed'], known['use']) else 'public'
    previous = known.get('previous', 0)
    addon = {'AllowableClasses': known.get('classes') or made.classes, 'PrevQuestID': previous if previous in world['quests'] else 0}
    stated = bool(known.get('classes') or addon['PrevQuestID'])                  # QuestieDB's word is in the row: it is named as a source
    texts, texts_from = {}, {}                       # the texts the recordings have, from a source this row may name
    for table, moment, _column in TEXTS:
        heard = (known.get('texts') or {}).get(moment)
        if heard and (allowed == 'private' or heard['use'] == 'public'):
            text, _why = quests.said(heard['wordings'])
            if text:
                texts[table], texts_from[table] = text, (heard['source'], heard['build'])
    data = {'quest': made, 'addon': addon if any(addon.values()) else None, 'record': f"{known['source']}@{known['build']}", 'texts': texts,
            'texts_from': {table: f'{source}@{build}' for table, (source, build) in texts_from.items()},
            'needs': [number for number in quests.targets(made)['npc'] if number not in world['npcs']],          # the NPCs written with it that it cannot do without
            'sources': {known['source']} | ({known['addon_source']} if stated else set()) | {source for source, _build in texts_from.values()},
            'from_questiedb': {key: value for key, value in (('AllowableClasses', known.get('classes', 0)), ('PrevQuestID', addon['PrevQuestID'])) if value}}
    return Row(QUEST, (quest,), note(decision, allowed), made.template['LogTitle'], allowed, decision, data), ''


def plan(ready, world, prices, extra, records=None, creatures=None):
    """(rows to write, what is held back) for the decisions that are ready.

    `ready` are stored decisions (dicts) with the verdict add; `world` is resolve.load_world's; `prices` is
    {(npc, item): [(use, build, listings)]}; `extra` holds what only the export asks the world: `borrowed` (the
    vendors whose list another vendor borrows), `quest_objects` (the objects of the quest giver kind), `sold` (how the
    world's vendors list an item: {item: [Listing]}) and `names`;
    `records` is load_quests' {quest: what a row may be written from}, `creatures` load_npcs' the same for NPCs.

    A quest is written with a giver and an ender or not at all, and a pair with its quest or not at all: a quest whose
    givers all wait (for an NPC template) waits with them, and so do its other pairs."""
    rows, held = [], []
    names = dict(extra.get('names', {}))
    arriving = {}                        # the NPCs that can be written: what waits for one of them comes with it
    for d in ready:
        if d['kind'] == 'npc':
            row, why = npc_row(d, (creatures or {}).get(d['subject']), extra)
            if row:
                arriving[d['subject']] = row
                names[('npc', d['subject'])] = row.comment
            else:
                held.append(Held(d, why))
    coming = {}                          # the quests that can be written, before their givers and enders are looked at
    for d in ready:
        if d['kind'] == 'quest':
            row, why = quest_row(d, (records or {}).get(d['subject']), world, arriving)
            if row:
                coming[d['subject']] = row
                names[('quest', d['subject'])] = row.comment
            else:
                held.append(Held(d, why))
    seen = collections.Counter(o['ID'] for row in coming.values() for o in row.data['quest'].objectives)
    for quest, row in list(coming.items()):          # two records that claim one objective id: neither is written
        if any(seen[o['ID']] > 1 for o in row.data['quest'].objectives):
            held.append(Held(coming.pop(quest).decision, 'an objective id of its record is also another quest\'s'))

    def name(kind, number):
        return names.get((kind, number)) or f'{kind} {number}'

    def leftover(kind, number):          # the world's own row reads like a developer's leftover: it needs a person before anything hangs on it
        return bool(resolve.INTERNAL.search(names.get((kind, number)) or ''))

    for d in ready:
        kind, subject_kind, subject, other = d['kind'], d['subject_kind'], d['subject'], d['object']
        if kind in ('quest', 'npc'):
            continue
        elif subject_kind == 'npc' and subject not in world['npcs'] and subject not in arriving:
            held.append(Held(d, 'it waits for its NPC, which is held back'))
        elif leftover(subject_kind, subject):
            held.append(Held(d, f"the world's {'NPC' if subject_kind == 'npc' else subject_kind} reads like a developer's leftover: for a person"))
        elif kind in ('gives', 'takes') and leftover('quest', other):
            held.append(Held(d, "the world's quest reads like a developer's leftover: for a person"))
        elif (kind, subject_kind) in RELATIONS:
            if other not in world['quests'] and other not in coming:
                held.append(Held(d, 'it waits for its quest, which is held back'))
            elif subject_kind == 'object' and subject not in world['objects']:
                held.append(Held(d, 'its object has no template'))
            elif subject_kind == 'object' and subject not in extra['quest_objects']:
                held.append(Held(d, 'its object is not of the quest giver kind'))
            else:
                verb = 'gives' if kind == 'gives' else 'takes'
                rows.append(Row(RELATIONS[(kind, subject_kind)], (subject, other), note(d, d['allowed']),
                                f"{name(subject_kind, subject)} {verb} {name('quest', other)}", d['allowed'], d))
        elif kind == 'sells' and subject_kind == 'npc':
            windows = prices.get((subject, other), [])
            reason, whose = priced(windows)
            sold = 'a recording of the live game shows it sold for money, in endless supply'
            if reason == NO_RECORDING or (not reason and whose == 'private'):
                # nobody recorded this vendor's window, or only a source that may not be published did: how the world's
                # other vendors sell the item, unless an earlier recording of this vendor says it is not a plain sale
                why, vendors = elsewhere(extra.get('sold', {}).get(other, ()), subject)
                before = said_before(windows)
                if not why and before:
                    why = f'{NO_RECORDING}, and an earlier recording says: {before}'
                if reason == NO_RECORDING or not why:
                    reason, whose = why, 'public'
                    sold = f"no recording: the world's other vendors of it ({vendors}) all sell it for money, in endless supply"
            if subject in extra['borrowed']:
                reason = 'other vendors borrow its list: a row here would reach them too'
            if reason:
                held.append(Held(d, reason))
            else:
                allowed = 'private' if 'private' in (d['allowed'], whose) else 'public'
                rows.append(Row(VENDOR, (subject, other, 0, 1), note(d, allowed), f"{name('npc', subject)} sells {name('item', other)}", allowed, d, {'sold': sold}))
        else:
            held.append(Held(d, 'no writer for this kind of decision'))
    rows, dropped = settle([arriving[npc] for npc in sorted(arriving)] + [coming[quest] for quest in sorted(coming)] + rows, world)
    return rows, held + [Held(row.decision, why) for row, why in dropped]


def settle(rows, world, present=()):
    """(the rows that can stand together, [(row, why it cannot)]). A quest needs someone who gives it and someone who
    takes it, a pair needs its quest, and what may be published must not need what may not:

    - a quest with no giver or no ender among the world's pairs and the rows is dropped, and its pairs with it;
    - a quest whose only givers (or enders) are private is private itself, and so is every pair of a private quest;
    - what needs an NPC that is written with it (its quest pairs, its vendor items, a quest with an objective on it)
      is dropped when the NPC is, and private when the NPC is.

    `present` holds the (table, key) of rows an earlier export carries: they reach the world before this file."""
    rows, dropped = list(rows), []
    there = {'giver': {quest for _kind, _subject, quest in world.get('gives', ())}, 'ender': {quest for _kind, _subject, quest in world.get('takes', ())}}
    for table, key in present:
        if table in RELATIONS.values():
            there['giver' if 'starter' in table else 'ender'].add(key[1])
    known = set(world['quests']) | {key[0] for table, key in present if table == QUEST}
    standing = set(world['npcs']) | {key[0] for table, key in present if table == NPC}
    private = lambda row: row._replace(allowed='private', note=note(row.decision, 'private'))

    def needed(row):                     # the NPCs a row cannot do without, other than the world's own
        if row.table == QUEST:
            return [number for number in row.data.get('needs', ()) if number not in standing]
        return [row.key[0]] if (row.table == VENDOR or row.table.startswith('creature_quest')) and row.key[0] not in standing else []
    while True:
        written, kept, changed = {row.key[0]: row.allowed for row in rows if row.table == NPC}, [], False
        for row in rows:                 # first what hangs on an NPC: it goes where the NPC goes, or nowhere
            lacking = [number for number in needed(row) if number not in written]
            if lacking:
                dropped.append((row, 'it waits for its NPC, which is held back' if row.table != QUEST else f'an objective needs an NPC that is held back (NPC {lacking[0]})'))
                changed = True
                continue
            if row.allowed == 'public' and any(written[number] == 'private' for number in needed(row)):
                row, changed = private(row), True
            kept.append(row)
        rows = kept
        sides = {(role, anyone): set(there[role]) for role in ('giver', 'ender') for anyone in (True, False)}
        for row in rows:
            if row.table in RELATIONS.values():
                role = 'giver' if 'starter' in row.table else 'ender'
                sides[(role, True)].add(row.key[1])
                if row.allowed == 'public':
                    sides[(role, False)].add(row.key[1])
        kept, written = [], {}
        for row in rows:
            if row.table != QUEST:
                kept.append(row)
                continue
            lacking = [role for role in ('giver', 'ender') if row.key[0] not in sides[(role, True)]]
            if lacking:
                dropped.append((row, f'no {lacking[0]} of it can be written yet'))
                changed = True
                continue
            if row.allowed == 'public' and any(row.key[0] not in sides[(role, False)] for role in ('giver', 'ender')):
                row, changed = private(row), True
            written[row.key[0]] = row.allowed
            kept.append(row)
        rows = []
        for row in kept:
            if row.table in RELATIONS.values() and row.key[1] not in known:
                if row.key[1] not in written:
                    dropped.append((row, 'it waits for its quest, which is held back'))
                    changed = True
                    continue
                if written[row.key[1]] == 'private' and row.allowed == 'public':
                    row, changed = private(row), True
            rows.append(row)
        if not changed:
            return rows, dropped


# ------------------------------------------------------------------ the file
def quote(name):
    return '`' + name.replace('`', '``') + '`'


def comment(text):
    return re.sub(r'[\x00-\x1f\x7f]+', ' ', str(text))[:160].strip()


def literal(text):
    """A string for the file, read the same whatever the server's sql_mode: no backslash, no control character, a quote
    written twice."""
    return "'" + re.sub(r'[\x00-\x1f\x7f]+', ' ', str(text)).replace('\\', '/').replace("'", "''") + "'"


def text_literal(value):
    """A text for the file, kept to the character: line breaks and backslashes are written as CHAR(), so the text is
    the same under any sql_mode and whatever a repository does to the file's own line ends."""
    parts, codes = [], []
    for piece in re.split(r'([\x00-\x1f\x7f\\])', str(value)):
        if len(piece) == 1 and (piece < ' ' or piece in '\x7f\\'):
            if piece != '\x00':
                codes.append(str(ord(piece)))
            continue
        if not piece:
            continue
        if codes:
            parts.append(f"CHAR({', '.join(codes)} USING utf8mb4)")
            codes = []
        parts.append("'" + piece.replace("'", "''") + "'")
    if codes:
        parts.append(f"CHAR({', '.join(codes)} USING utf8mb4)")
    return parts[0] if len(parts) == 1 and parts[0].startswith("'") else f"CONCAT({', '.join(parts)})" if parts else "''"


def value_literal(value):
    if isinstance(value, bool):
        raise ExportError('a yes or no where a number or a text belongs')
    if value is None:
        return 'NULL'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return text_literal(value)


def staged_like(stage, table, records, extra='', about=None):
    """The statements that make a stage table with the columns of `table` that `records` (dicts of one shape) name,
    typed as the world types them, and fill it. `extra` declares more columns; `about` gives each line's note (the
    stage then has a `note` column) and comment."""
    columns = list(records[0])
    # Every column `extra` declares needs a default, `n` too: under MySQL's strict mode (the server's default, and the mode the
    # core's updater applies files in) CREATE TABLE ... SELECT refuses a NOT NULL column without one, even when it copies no row.
    out = [f"CREATE TEMPORARY TABLE {quote(stage)} (`n` INT NOT NULL DEFAULT 0 PRIMARY KEY{extra}) SELECT {', '.join(quote(c) for c in columns)} FROM {quote(table)} WHERE 0"]
    head = f"INSERT INTO {quote(stage)} (`n`, {', '.join(quote(c) for c in columns)}{', `note`' if about else ''}) VALUES\n"
    for start in range(0, len(records), BATCH):
        lines = []
        for offset, record in enumerate(records[start:start + BATCH]):
            if list(record) != columns:
                raise ExportError(f'{table}: two rows of one block name different columns')
            index = start + offset
            line = f"({index + 1}, {', '.join(value_literal(v) for v in record.values())}{', ' + literal(about[index][0]) if about else ''})"
            lines.append(line + ('' if index == min(start + BATCH, len(records)) - 1 else ',') + (f' -- {comment(about[index][1])}' if about else ''))
        out.append(head + '\n'.join(lines) + '\n')
    return out


def quest_block(rows, file):
    """The quests: each goes in whole or not at all. A quest is taken while the world has no row of it in any of its
    tables, none of its objective ids is another quest's, and no file added it before; then its own rows follow."""
    made = [row.data['quest'] for row in rows]
    out = staged_like(QUESTS, QUEST, [quest.template for quest in made], ", `note` VARCHAR(255) NOT NULL DEFAULT '', `missing` TINYINT NOT NULL DEFAULT 0",
                      [(row.note, row.comment) for row in rows])
    children = {
        'quest_objectives': [objective for quest in made for objective in quest.objectives],
        'quest_classic_level': [collections.OrderedDict(ID=q.template['ID'], QuestLevel=q.level[0], MinLevel=q.level[1], MaxLevel=0) for q in made],
        'quest_template_classic_level': [collections.OrderedDict(ID=q.template['ID'], LevelType=quests.LEVEL_TYPE, QuestLevel=q.level[0]) for q in made],
        'quest_classic_money': [collections.OrderedDict(ID=q.template['ID'], RewardMoney=q.money, RewardMoneyMaxLevel=0) for q in made if q.money],
        'quest_reward_display_spell': [collections.OrderedDict(QuestID=q.template['ID'], Idx=index, SpellID=spell, PlayerConditionID=0, Type=kind)
                                       for q in made for index, (spell, kind) in enumerate(q.spells)],
        'quest_template_addon': [collections.OrderedDict(ID=row.key[0], **row.data['addon']) for row in rows if row.data['addon']],
    }
    # No statement reads a stage table or the ledger twice: MySQL cannot reopen a temporary table, and a trial's ledger may be one.
    keyed = ', '.join(literal(table) for table in (QUEST,) + tuple(table for table, _column, _key in CHILDREN if table != 'quest_objectives'))
    free = [f"NOT EXISTS (SELECT 1 FROM {quote(QUEST)} t WHERE t.`ID` = s.`ID`)",
            f"NOT EXISTS (SELECT 1 FROM {quote(LEDGER)} r WHERE r.`tbl` IN ({keyed}) AND r.`k1` = s.`ID`)"]          # no file added it, or a row of it, before
    free += [f"NOT EXISTS (SELECT 1 FROM {quote(table)} c WHERE c.{quote(column)} = s.`ID`)" for table, column, _key in CHILDREN]
    if children['quest_objectives']:              # none of its objective ids is another quest's, now or in a file's past
        out += staged_like(OBJECTIVES, 'quest_objectives', children['quest_objectives'], ', `taken` TINYINT NOT NULL DEFAULT 0')
        out.append(f"UPDATE {quote(OBJECTIVES)} p SET p.`taken` = 1 WHERE EXISTS (SELECT 1 FROM `quest_objectives` o WHERE o.`ID` = p.`ID`) "
                   f"OR EXISTS (SELECT 1 FROM {quote(LEDGER)} r WHERE r.`tbl` = 'quest_objectives' AND r.`k1` = p.`ID`)")
        # nor does an objective name an NPC or an object the world has no template of (an NPC of this file went in above, or did not)
        out.append(f"UPDATE {quote(OBJECTIVES)} p SET p.`taken` = 1 WHERE (p.`Type` IN (0, 3) AND p.`ObjectID` > 0 AND NOT EXISTS (SELECT 1 FROM `creature_template` c WHERE c.`entry` = p.`ObjectID`)) "
                   f"OR (p.`Type` = 2 AND p.`ObjectID` > 0 AND NOT EXISTS (SELECT 1 FROM `gameobject_template` g WHERE g.`entry` = p.`ObjectID`))")
        free.append(f"NOT EXISTS (SELECT 1 FROM {quote(OBJECTIVES)} p WHERE p.`QuestID` = s.`ID` AND p.`taken` = 1)")
    out.append(f"UPDATE {quote(QUESTS)} s SET s.`missing` = 1 WHERE " + ' AND '.join(free))
    columns = ', '.join(quote(c) for c in made[0].template)
    out.append(f"INSERT INTO {quote(QUEST)} ({columns}, `VerifiedBuild`) SELECT {columns}, 0 FROM {quote(QUESTS)} s WHERE s.`missing` = 1 ORDER BY s.`n`")
    out.append(f"INSERT INTO {quote(LEDGER)} (`tbl`, `k1`, `file`, `note`) SELECT {literal(QUEST)}, s.`ID`, {literal(file)}, s.`note` FROM {quote(QUESTS)} s WHERE s.`missing` = 1")
    out += brought(CHILDREN, children, QUESTS, 'ID', {'quest_objectives': OBJECTIVES}, file)
    for table, _moment, column in TEXTS:              # a text goes in for a quest this file added, unless the world holds one or a file added one before
        records = [collections.OrderedDict((('ID', row.key[0]), (column, row.data['texts'][table]))) for row in rows if row.data.get('texts', {}).get(table)]
        if not records:
            continue
        out += staged_like(STAGE, table, records, ', `free` TINYINT NOT NULL DEFAULT 0')
        out.append(f"UPDATE {quote(STAGE)} p JOIN {quote(QUESTS)} s ON s.`ID` = p.`ID` SET p.`free` = 1 WHERE s.`missing` = 1 "
                   f"AND NOT EXISTS (SELECT 1 FROM {quote(table)} c WHERE c.`ID` = p.`ID`) "
                   f"AND NOT EXISTS (SELECT 1 FROM {quote(LEDGER)} r WHERE r.`tbl` = {literal(table)} AND r.`k1` = p.`ID`)")
        out.append(f"INSERT INTO {quote(table)} (`ID`, {quote(column)}, `VerifiedBuild`) SELECT p.`ID`, p.{quote(column)}, 0 FROM {quote(STAGE)} p WHERE p.`free` = 1 ORDER BY p.`n`")
        out.append(f"INSERT INTO {quote(LEDGER)} (`tbl`, `k1`, `file`, `note`) SELECT {literal(table)}, p.`ID`, {literal(file)}, s.`note` "
                   f"FROM {quote(STAGE)} p JOIN {quote(QUESTS)} s ON s.`ID` = p.`ID` WHERE p.`free` = 1")
        out.append(f'DROP TEMPORARY TABLE {quote(STAGE)}')
    out.append(f'DROP TEMPORARY TABLE {quote(QUESTS)}')
    return out


def brought(tables, children, parents, parent_key, staged_before, file):
    """The statements that add the rows a quest or an NPC brings with it: each child table's rows go in for the
    parents this file added (`missing` in the parents' stage), and are recorded under the parent's note.
    `staged_before` names the stage tables that exist already ({table: stage})."""
    out = []
    for table, column, key in tables:
        records = children[table]
        if not records:
            continue
        stage = staged_before.get(table, STAGE)
        if table not in staged_before:
            out += staged_like(STAGE, table, records)
        names = ', '.join(quote(c) for c in records[0])
        taken = f"FROM {quote(stage)} p JOIN {quote(parents)} s ON s.{quote(parent_key)} = p.{quote(column)} WHERE s.`missing` = 1"
        out.append(f"INSERT INTO {quote(table)} ({names}{', `VerifiedBuild`' if table in VERIFIED else ''}) "
                   f"SELECT {', '.join('p.' + quote(c) for c in records[0])}{', 0' if table in VERIFIED else ''} {taken} ORDER BY p.`n`")
        out.append(f"INSERT INTO {quote(LEDGER)} (`tbl`, {', '.join(f'`k{i + 1}`' for i in range(len(key)))}, `file`, `note`) "
                   f"SELECT {literal(table)}, {', '.join('p.' + quote(c) for c in key)}, {literal(file)}, s.`note` {taken}")
        out.append(f'DROP TEMPORARY TABLE {quote(stage)}')
    return out


def npc_block(rows, file):
    """The NPC templates: each goes in whole or not at all. An NPC is taken while the world has no row of it in any of
    its tables, the world can show every one of its models (creature_model_info), and no file added it before."""
    made = [row.data['npc'] for row in rows]
    out = staged_like(NPCS, NPC, [npc.template for npc in made], ", `note` VARCHAR(255) NOT NULL DEFAULT '', `missing` TINYINT NOT NULL DEFAULT 0",
                      [(row.note, row.comment) for row in rows])
    children = {'creature_template_difficulty': [npc.difficulty for npc in made], 'creature_template_model': [model for npc in made for model in npc.models],
                'creature_classic_level': [collections.OrderedDict(entry=npc.template['entry'], level_min=npc.level[0], level_max=npc.level[1]) for npc in made]}
    out += staged_like(MODELS, 'creature_template_model', children['creature_template_model'], ', `unknown` TINYINT NOT NULL DEFAULT 0')
    out.append(f"UPDATE {quote(MODELS)} p SET p.`unknown` = 1 WHERE NOT EXISTS (SELECT 1 FROM `creature_model_info` i WHERE i.`DisplayID` = p.`CreatureDisplayID`)")
    keyed = ', '.join(literal(table) for table in (NPC,) + tuple(table for table, _column, _key in NPC_CHILDREN))
    free = [f"NOT EXISTS (SELECT 1 FROM {quote(NPC)} t WHERE t.`entry` = s.`entry`)",
            f"NOT EXISTS (SELECT 1 FROM {quote(LEDGER)} r WHERE r.`tbl` IN ({keyed}) AND r.`k1` = s.`entry`)"]
    free += [f"NOT EXISTS (SELECT 1 FROM {quote(table)} c WHERE c.{quote(column)} = s.`entry`)" for table, column, _key in NPC_CHILDREN]
    free.append(f"NOT EXISTS (SELECT 1 FROM {quote(MODELS)} p WHERE p.`CreatureID` = s.`entry` AND p.`unknown` = 1)")
    out.append(f"UPDATE {quote(NPCS)} s SET s.`missing` = 1 WHERE " + ' AND '.join(free))
    columns = ', '.join(quote(c) for c in made[0].template)
    out.append(f"INSERT INTO {quote(NPC)} ({columns}, `VerifiedBuild`) SELECT {columns}, 0 FROM {quote(NPCS)} s WHERE s.`missing` = 1 ORDER BY s.`n`")
    out.append(f"INSERT INTO {quote(LEDGER)} (`tbl`, `k1`, `file`, `note`) SELECT {literal(NPC)}, s.`entry`, {literal(file)}, s.`note` FROM {quote(NPCS)} s WHERE s.`missing` = 1")
    out += brought(NPC_CHILDREN, children, NPCS, 'entry', {'creature_template_model': MODELS}, file)
    out.append(f'DROP TEMPORARY TABLE {quote(NPCS)}')
    return out


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
            out += (npc_block if table == NPC else quest_block if table == QUEST else vendor_block if table == VENDOR else lambda r, f: relation_block(table, r, f))(mine, file)
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
            'rows': [dict({'table': row.table, 'key': list(row.key), 'kind': row.decision['kind'], 'rule': row.decision['rule'],
                           'witnesses': [label(w) for w in named(row.decision, kind)], 'says': row.comment}, **described(row))
                     for row in sorted(rows, key=lambda row: (ORDER.index(row.table), row.key))],
            'left_to_defaults': (list(npcs.LEFT) if any(row.table == NPC for row in rows) else []) + (list(quests.LEFT) if any(row.table == QUEST for row in rows) else []),
            'held_back': dict(sorted(collections.Counter(grouped(h.reason) for h in held).items()))}


def described(row):
    """What the manifest adds for a row that brings rows of its own: where a quest's values come from, and how many
    rows of each table come with it."""
    if row.table == NPC:
        npc = row.data['npc']
        return {'record': row.data['record'], 'side': row.data['side'], 'side_from': f"{row.data['side_from']}: {row.data['side_how']}", 'faction': npc.template['faction'],
                'level': list(npc.level), 'level_from': row.data['level_from'], 'models': len(npc.models), 'unread': list(npc.unread)}
    if row.table == VENDOR:
        return {'sold': row.data['sold']} if row.data else {}
    if row.table != QUEST:
        return {}
    quest, addon = row.data['quest'], row.data['addon']
    return {'record': row.data['record'], 'with': {'quest_objectives': len(quest.objectives), 'quest_reward_display_spell': len(quest.spells),
                                                  'quest_classic_money': int(bool(quest.money)), 'quest_template_addon': int(bool(addon))},
            'texts': dict(sorted(row.data['texts_from'].items())),          # each goes in unless the world holds a text there already
            'from_questiedb': row.data['from_questiedb'], 'classes': (addon or {}).get('AllowableClasses', 0), 'unread': list(quest.unread)}


# ------------------------------------------------------------------ reading both sides
def load_ready(db, database='tracker'):
    out = []
    for row in db.query(f"SELECT * FROM {resolve.DECISIONS} WHERE verdict = 'add' ORDER BY kind, subject_kind, subject, object", database):
        row.update(subject=int(row['subject']), object=int(row['object']), witnesses=json.loads(row['witnesses']))
        out.append(row)
    return out


def load_prices(db, registry, database='tracker'):
    """{(npc, item): [(use, build, listings)]}: the recordings that show a vendor's window. `use` is the source's
    (public, private) for a recording of the live game, and 'other' for one that may not give a row: a reference's, or
    one from before the live game."""
    out = collections.defaultdict(list)
    for row in db.query(f"SELECT source, subject, object, build, data FROM {facts.FACTS} WHERE kind = 'sells' AND subject_kind = 'npc'", database):
        if row['source'] not in registry.sources:
            continue
        use, build = registry.source(row['source'])['use'], int(row['build'])
        if use == 'reference' or not registry.witness(row['source'], '', build)[1]:
            use = 'other'                            # a reference's, or from before the live game: it gives no row
        try:
            listings = json.loads(row['data']).get('listings')
        except (ValueError, AttributeError):
            listings = None
        out[(int(row['subject']), int(row['object']))].append((use, build, listings))
    return out


def load_quests(db, registry, wanted, database='tracker'):
    """{quest: {'use', 'source', 'build', 'record', what QuestieDB adds: 'classes', 'previous', 'addon_source', and
    'texts': {moment: {'use', 'source', 'build', 'wordings'}}, what was said in the quest's windows} for
    the quests in `wanted`. A moment's wordings are all that the sources of one use recorded on the live game, over
    every build (the publishable sources', else the private ones'), under the newest recording's source and build: a
    text that reads otherwise on another build is not one text. The record is the newest one a source that may give rows recorded on the live game, a
    publishable source first. QuestieDB (a publishable source's entry) adds what no record holds: the classes the
    quest is for, and the one quest that must be done before it; its hand fix is read after its generated list."""
    out, best = {}, {}
    wanted = sorted(wanted)
    for start in range(0, len(wanted), 2000):
        ids = ', '.join(map(str, wanted[start:start + 2000]))
        for row in db.query(f"SELECT source, subject, build, data FROM {facts.FACTS} WHERE kind = 'quest' AND subject_kind = 'quest' AND subject IN ({ids})", database):
            if row['source'] not in registry.sources:
                continue
            use, build, quest = registry.source(row['source'])['use'], int(row['build']), int(row['subject'])
            if use == 'reference' or not registry.witness(row['source'], '', build)[1]:
                continue
            rank = (use == 'public', build, row['source'])
            if quest not in best or rank > best[quest]:
                try:
                    record = json.loads(row['data'])
                except ValueError:
                    record = None
                best[quest], out[quest] = rank, {'use': use, 'source': row['source'], 'build': build, 'record': record}
        heard = {}
        for row in db.query(f"SELECT source, subject, build, data FROM {facts.FACTS} WHERE kind = 'text' AND subject_kind = 'quest' AND subject IN ({ids})", database):
            quest = int(row['subject'])
            if quest not in out or row['source'] not in registry.sources:
                continue
            use, build = registry.source(row['source'])['use'], int(row['build'])
            if use == 'reference' or not registry.witness(row['source'], '', build)[1]:
                continue
            try:
                said = json.loads(row['data'])
            except ValueError:
                continue
            for moment, lines in (said.items() if isinstance(said, dict) else ()):
                # what the window showed, not the quest cache's copy of the offer (that is the record's description already)
                wordings = [line['text'] for line in lines if isinstance(line, dict) and isinstance(line.get('text'), str) and not line.get('template')] \
                    if isinstance(lines, list) else []
                if wordings:
                    said_so = heard.setdefault((quest, moment, use), {'newest': (-1, ''), 'wordings': []})
                    said_so['newest'] = max(said_so['newest'], (build, row['source']))
                    said_so['wordings'] += wordings
        for (quest, moment, use), said_so in sorted(heard.items(), key=lambda item: item[0][2] == 'public'):        # a publishable source's word last: it stands
            out[quest].setdefault('texts', {})[moment] = {'use': use, 'source': said_so['newest'][1], 'build': said_so['newest'][0], 'wordings': said_so['wordings']}
        for row in db.query(f"SELECT source, subject, data FROM {facts.FACTS} WHERE kind = 'entry' AND subject_kind = 'quest' AND subject IN ({ids}) "
                            f"ORDER BY source, build", database):
            quest = int(row['subject'])
            if quest not in out or row['source'] not in registry.sources or registry.source(row['source'])['use'] != 'public':
                continue
            try:
                parts = json.loads(row['data']).get('parts')
            except (ValueError, AttributeError):
                continue
            for part in ('generated', 'fix'):
                fields = parts.get(part) if isinstance(parts, dict) else None
                if not isinstance(fields, dict):
                    continue
                number = lambda value: isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2 ** 32
                if 'requiredClasses' in fields:          # a part that names the field replaces it: with its value, or with nothing when that is not a class mask
                    out[quest].update(classes=fields['requiredClasses'] if number(fields['requiredClasses']) else 0, addon_source=row['source'])
                if 'preQuestSingle' in fields:           # one quest before it is a row's PrevQuestID; none, or one of several, is not
                    before = fields['preQuestSingle']
                    single = isinstance(before, list) and len(before) == 1 and number(before[0])
                    out[quest].update(previous=before[0] if single else 0, addon_source=row['source'])
    return out


def load_npcs(db, registry, wanted, database='tracker'):
    """{npc: what an NPC's rows may be written from} for the NPCs in `wanted`:

    - `record`, `use`, `source`, `build`: the newest creature record a source that may give rows recorded on the live
      game, a publishable source first;
    - `talked`: the side the newest recording of a player opening its window gives it ('' when none), absent when no
      publishable source recorded one; `reactions`: how players of each side saw it, every sighting together;
      `seen_source`: whose recordings those are;
    - `fought`: a sighting on the live game says players killed or fought it; `against`: the sides a source that may
      not give rows saw it below neutral. Both only ever hold an NPC back, so any source that records play counts;
    - `stated`, `side_source`: QuestieDB's friendlyToFaction (a publishable source's entry; its players' recordings
      are read after its generated list and its hand fix last, and a part that names the field replaces it);
    - `level`: (min, max, whose word): QuestieDB's, else the levels players saw it at."""
    out, best, seen = {}, {}, {}
    wanted = sorted(wanted)
    number = lambda value, high: isinstance(value, int) and not isinstance(value, bool) and 0 < value <= high
    for start in range(0, len(wanted), 2000):
        ids = ', '.join(map(str, wanted[start:start + 2000]))
        for row in db.query(f"SELECT source, kind, subject, build, data FROM {facts.FACTS} WHERE kind IN ('creature', 'seen', 'talked') AND subject_kind = 'npc' "
                            f"AND subject IN ({ids}) ORDER BY source, build", database):
            if row['source'] not in registry.sources:
                continue
            use, build, npc = registry.source(row['source'])['use'], int(row['build']), int(row['subject'])
            if use == 'reference' or not registry.witness(row['source'], '', build)[1]:
                continue
            try:
                data = json.loads(row['data'])
            except ValueError:
                data = None
            if row['kind'] == 'creature':
                rank = (use == 'public', build, row['source'])
                if npc not in best or rank > best[npc]:
                    best[npc] = rank
                    out.setdefault(npc, {}).update(use=use, source=row['source'], build=build, record=data)
                continue
            if not isinstance(data, dict):
                continue
            mine = seen.setdefault(npc, {'reactions': {}, 'levels': set(), 'against': set(), 'fought': False, 'source': ''})
            reactions = data['reactions'] if isinstance(data.get('reactions'), dict) else {}
            if row['kind'] == 'seen' and (data.get('deaths') or data.get('xp') or data.get('combatLog')):
                mine['fought'] = True
            if use != 'public':                      # a source that may not give rows can still say "not a friend"
                mine['against'] |= {who[0] for who, values in reactions.items() if who in ('Alliance', 'Horde') and isinstance(values, list)
                                    and any(isinstance(v, int) and not isinstance(v, bool) and v < npcs.NEUTRAL for v in values)}
                continue
            mine['source'] = row['source']
            if row['kind'] == 'talked':              # rows come oldest first: the newest recording's side stays
                mine['talked'] = data['side'] if data.get('side') in ('Alliance', 'Horde') else ''
            for who, values in reactions.items():
                if isinstance(values, list):
                    mine['reactions'].setdefault(who, []).extend(values)
            levels = data.get('levels')
            for level in levels if isinstance(levels, (dict, list)) else ():
                if number(level, 255) or (isinstance(level, str) and re.fullmatch(r'[0-9]{1,3}', level) and 0 < int(level) <= 255):
                    mine['levels'].add(int(level))
        for row in db.query(f"SELECT source, subject, data FROM {facts.FACTS} WHERE kind = 'entry' AND subject_kind = 'npc' AND subject IN ({ids}) "
                            f"ORDER BY source, build", database):
            npc = int(row['subject'])
            if npc not in out or row['source'] not in registry.sources or registry.source(row['source'])['use'] != 'public':
                continue
            try:
                parts = json.loads(row['data']).get('parts')
            except (ValueError, AttributeError):
                continue
            for part in ('generated', 'trace', 'fix'):
                fields = parts.get(part) if isinstance(parts, dict) else None
                if not isinstance(fields, dict):
                    continue
                if 'friendlyToFaction' in fields:
                    out[npc].update(stated=fields['friendlyToFaction'], side_source=row['source'])
                if 'minLevel' in fields or 'maxLevel' in fields:
                    low, high = fields.get('minLevel'), fields.get('maxLevel')
                    out[npc]['level'] = (low, high, row['source']) if number(low, 255) and number(high, 255) and low <= high else None
    for npc, known in out.items():
        mine = seen.get(npc)
        if mine:
            known.update(reactions=mine['reactions'], seen_source=mine['source'], fought=mine['fought'], against=sorted(mine['against']))
            if 'talked' in mine:
                known['talked'] = mine['talked']
            if not known.get('level') and mine['levels'] and mine['source']:
                known['level'] = (min(mine['levels']), max(mine['levels']), mine['source'])
    return {npc: known for npc, known in out.items() if 'record' in known}


def load_model_info(db, build, creatures):
    """The display ids among the NPCs' models that the world can show (it has their size in creature_model_info)."""
    wanted = sorted({display['displayId'] for known in creatures.values() if isinstance(known.get('record'), dict)
                     for display in (known['record'].get('displays') if isinstance(known['record'].get('displays'), list) else ()) if isinstance(display, dict)
                     and isinstance(display.get('displayId'), int) and not isinstance(display.get('displayId'), bool) and 0 < display['displayId'] < 2 ** 32})
    out = set()
    for start in range(0, len(wanted), 2000):
        out |= {int(row['DisplayID']) for row in db.query(f"SELECT DisplayID FROM creature_model_info WHERE DisplayID IN ({', '.join(map(str, wanted[start:start + 2000]))})", build)}
    return out


def load_pins(db, sources, database='tracker'):
    wanted = ', '.join(facts.sql_value(s) for s in sorted(sources)) or "''"
    return {row['source']: row['pin'] for row in db.query(f'SELECT source, pin FROM {facts.SOURCES} WHERE source IN ({wanted})', database)}


def load_extra(db, build, ready, tracker=None, registry=None, database='tracker'):
    """What only the export asks: the vendors whose list is borrowed, the quest giver objects, how the world's vendors
    list the items the ready decisions sell (`sold`: {item: [Listing]}), and the names of what
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
    sold = collections.defaultdict(list)                 # how the world's vendors list the items the ready decisions sell
    wanted = sorted({d['object'] for d in ready if d['kind'] == 'sells' and d['object'] > 0})
    plain = "({0}.ExtendedCost = 0 AND {0}.maxcount = 0 AND {0}.incrtime = 0 AND {0}.PlayerConditionID = 0 AND COALESCE({0}.BonusListIDs, '') = '') plain"
    has = lambda table: bool(wanted) and bool(db.query(f"SHOW TABLES LIKE '{table}'", build))
    # a row an export added is not the world's own word: the rule must not rest on what it wrote itself
    own = f"AND NOT EXISTS (SELECT 1 FROM {quote(LEDGER)} l WHERE l.tbl = '{VENDOR}' AND l.k1 = v.entry AND l.k2 = v.item) " if has(LEDGER) else ''
    events = has('game_event_npc_vendor')
    for start in range(0, len(wanted), 2000):
        ids = ', '.join(map(str, wanted[start:start + 2000]))
        for row in db.query(
                f"SELECT v.item, v.entry, {plain.format('v')}, COALESCE(t.name, '') name, COALESCE(t.npcflag, 0) & {VENDOR_FLAG} vendor, "
                "EXISTS (SELECT 1 FROM creature c WHERE c.id = v.entry) spawned "
                f"FROM npc_vendor v LEFT JOIN creature_template t ON t.entry = v.entry WHERE v.type = 1 AND v.item IN ({ids}) {own}", build):
            real = int(row['vendor']) and int(row['spawned']) and row['name'] and not resolve.INTERNAL.search(row['name'])
            sold[int(row['item'])].append(Listing(int(row['entry']), bool(int(row['plain'])), bool(real)))
        if events:                                       # sold during an event only: it says how the item is sold, not that it can be bought today
            for row in db.query(f"SELECT g.item, c.id entry, {plain.format('g')} FROM game_event_npc_vendor g JOIN creature c ON c.guid = g.guid "
                                f"WHERE g.type = 1 AND g.item IN ({ids})", build):
                sold[int(row['item'])].append(Listing(int(row['entry']), bool(int(row['plain'])), False))
    return {'borrowed': numbers('SELECT DISTINCT -item FROM npc_vendor WHERE item < 0'),
            'quest_objects': numbers(f'SELECT entry FROM gameobject_template WHERE type = {QUESTGIVER_OBJECT}'), 'names': names, 'sold': dict(sold)}


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
    if QUEST in tables:
        tables += [table for table, _quest, _key in CHILDREN]
        tables += [table for table, _moment, _column in TEXTS                 # only where a quest brings a text: an older world may lack the tables
                   if any(row.table == QUEST and row.data['texts'].get(table) for _file, rows in files for row in rows)]
    if NPC in tables:
        tables += [table for table, _npc, _key in NPC_CHILDREN]
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
    # The core's updater applies files over its own connection in the server's default mode, which is strict on MySQL 8: the
    # trial runs in that mode whatever this account's session would get, so a statement the realm refuses fails here first.
    script.insert(0, f"SET SESSION sql_mode = {literal(STRICT_MODE)}")
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
    for row in result:
        if int(row['step']) == 9:
            key = tuple(int(row[c]) for c in 'abcd')[:KEYS[row['tbl']]]
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
    records = load_quests(tracker, registry, {d['subject'] for d in ready if d['kind'] == 'quest'}, database)
    creatures = load_npcs(tracker, registry, {d['subject'] for d in ready if d['kind'] == 'npc'}, database)
    extra['model_info'] = load_model_info(db, build, creatures)
    rows, held = plan(ready, world, load_prices(tracker, registry, database), extra, records, creatures)
    before = carried(folders.values())
    earlier = [row for row in rows if (row.table, row.key) in before]
    rows = [row for row in rows if (row.table, row.key) not in before]
    number = next_number(folders.values(), date)
    names = {kind: file_name(date, number, kind == 'private') for kind in SETS}
    split = lambda: [(names[kind], sorted((row for row in rows if row.allowed == kind), key=lambda row: (ORDER.index(row.table), row.key))) for kind in SETS]
    refused = []
    for _round in range(6):                 # what the world does not take is left out, and with it what cannot stand without it; then tried again
        rows, dropped = settle(rows, world, set(before))
        held += [Held(row.decision, why) for row, why in dropped]
        added = trial(db, build, split())
        missed = [row for row in rows if (row.table, row.key) not in added[names[row.allowed]]]
        if not missed:
            break
        refused += missed
        rows = [row for row in rows if row not in missed]
        held += [Held(row.decision, REFUSED) for row in missed]
    else:
        raise ExportError('the replayed world keeps refusing rows it accepted a moment ago: nothing is written')
    against = replayed(db, build)
    files, writes = {}, []
    for kind, (file, mine) in zip(SETS, split()):
        if not mine:
            continue
        sources = {w['source'] for row in mine for w in named(row.decision, kind)} | {source for row in mine if row.data for source in row.data.get('sources', ())}
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
