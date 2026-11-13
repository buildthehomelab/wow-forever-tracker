"""The rules: what the facts, weighed, say the server's world should hold and does not.

The replayed world (tools/ft/replay.py) is the base. The facts (tools/ft/facts.py) are claims. A rule turns the
claims about one thing into a decision, and every decision keeps its reasons:

    verdict   add      the world should hold it, and everything it needs is there
              hold     the world should hold it, but something it needs is missing (named in `needs`)
              review   the facts are not enough to decide: a person looks
    rule      the name of the rule that gave the verdict
    allowed   public or private: whether a source that may be published states it (docs/WORLD-BUILD.md)
    witnesses who says so: source, part, client build, samples, witness group, recorded on live or not, trusted
              by itself or not

What the world already holds is not decided again (it is counted as agreed), and nothing is ever removed because no
source mentions it: that nobody recorded something is not evidence that it is gone.

Rules, by the kind of thing:

- who gives a quest, who takes it, what a vendor sells (`gives`, `takes`, `sells`):
    seen-live        a recording on the live game states it: add
    trusted-source   no live recording, but a source the registry trusts by itself states it (QuestieDB's
                     generated list: Wowhead's data, reviewed and shipped by Questie): add
    two-witnesses    neither, but two independent witnesses state it: add. Two parts of one source, or two
                     sources of one witness group, are one witness
    one-claim        one witness's word, not recorded on live: review
    reference-only   only sources that may never give a row state it: review
    removed-by-hand  a source's hand correction takes the claim back: review
    item-starts      an item starts the quest: that is the item's own data, not followed here: review
  It needs its quest and its NPC or object to exist in the world. A pair whose only missing piece is a quest that
  is itself ready to add is ready too: it comes with its quest.
- a quest the world lacks (`quest`):
    record-seen-live   the server sent the quest's record to a client of the live game, and a source that may give
                       rows recorded it: the quest exists. It is added once a giver and an ender pass the rules
                       above and exist in the world
    record-not-live    its record was only seen before the live game: review
    looks-internal     its name reads like a developer's leftover ("[DNT]", "zzOLD", "UNUSED", "REUSE ME"): review

This module reads no configuration. The databases are reached through objects with `query(sql, database)`.
"""
import collections
import json
import re

from . import facts

DECISIONS, RESOLVED = 'ft_world_decisions', 'ft_world_resolved'
SCHEMA = [
    f'CREATE TABLE IF NOT EXISTS {DECISIONS} (kind VARCHAR(16) NOT NULL, subject_kind VARCHAR(8) NOT NULL, subject INT UNSIGNED NOT NULL, '
    'object INT UNSIGNED NOT NULL DEFAULT 0, verdict VARCHAR(8) NOT NULL, rule VARCHAR(24) NOT NULL, allowed VARCHAR(12) NOT NULL, '
    'name VARCHAR(255) NOT NULL DEFAULT \'\', needs TEXT NOT NULL, notes TEXT NOT NULL, witnesses MEDIUMTEXT NOT NULL, '
    'PRIMARY KEY (kind, subject_kind, subject, object), KEY by_verdict (verdict, kind)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    f'CREATE TABLE IF NOT EXISTS {RESOLVED} (id TINYINT NOT NULL PRIMARY KEY, resolved_at DATETIME NOT NULL, summary MEDIUMTEXT NOT NULL) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
]
PAIRS = ('gives', 'takes', 'sells')
INTERNAL = re.compile(r'^\s*[\[<(]|^\s*zz|UNUSED|DEPRECATED|REUSE|\bDNT\b|\bNYI\b|\bTEST\b|\btest quest\b', re.I)
Evidence = collections.namedtuple('Evidence', 'source part build samples group live use trusted', defaults=(False,))
Decision = collections.namedtuple('Decision', 'kind subject_kind subject object verdict rule allowed name needs notes witnesses')


# ------------------------------------------------------------------ weighing
def evidence(registry, source, build, samples, data):
    """What one stored fact is worth as witnesses: one per part for a source made of parts, else one."""
    about = registry.source(source)
    parts = data.get('parts') if isinstance(data, dict) and about.get('parts') else None
    if isinstance(parts, dict) and parts:
        out = []
        for part in parts:
            group, live = registry.witness(source, part)
            out.append(Evidence(source, part, 0, 1 if live else 0, group, live, about['use'], registry.trusted(source, part)))
        return out
    group, live = registry.witness(source, '', build)
    return [Evidence(source, '', build, samples, group, live, about['use'], registry.trusted(source))]


def strongest(witnesses):
    """One witness per source and part: the live one, then the newest build, then the most samples."""
    best = {}
    for witness in witnesses:
        key = (witness.source, witness.part)
        if key not in best or (witness.live, witness.build, witness.samples) > (best[key].live, best[key].build, best[key].samples):
            best[key] = witness
    return sorted(best.values(), key=lambda w: (not w.live, w.source, w.part))


def independent(registry, witnesses):
    """How many independent witnesses these are. The parts of one source are one witness, and so are sources that
    share a witness group: their own, the group a part really belongs to, or one of the sources they are compiled
    from."""
    merged = []
    for source in sorted({w.source for w in witnesses}):
        groups = set(registry.groups(source)) | {w.group for w in witnesses if w.source == source}
        for other in [m for m in merged if m & groups]:
            merged.remove(other)
            groups |= other
        merged.append(groups)
    return len(merged)


def weigh(registry, witnesses):
    """(verdict, rule, allowed) for a claim that something is so, from who states it.

    `allowed` is public when a source that may be published states the claim: the row can then be written from that
    source, whoever else witnessed it. A source that may never give a row can confirm a claim, not carry it."""
    giving = [w for w in witnesses if w.use != 'reference']
    if not giving:
        return 'review', 'reference-only', 'private'
    allowed = 'public' if any(w.use == 'public' for w in giving) else 'private'
    if any(w.live for w in giving):
        return 'add', 'seen-live', allowed
    if any(w.trusted for w in giving):
        return 'add', 'trusted-source', allowed
    if independent(registry, witnesses) >= 2:
        return 'add', 'two-witnesses', allowed
    return 'review', 'one-claim', allowed


def decide_pairs(registry, kind, claims, world, removed=()):
    """Decisions for the claims of one kind the world does not hold yet.

    `claims` is {(subject_kind, subject, object): [Evidence]}; `world` is what replay gave (see load_world);
    `removed` holds the claims a hand correction takes back. Returns (decisions, how many the world already holds)."""
    out, agreed = [], 0
    for (subject_kind, subject, other), witnesses in sorted(claims.items()):
        if (subject_kind, subject, other) in world[kind]:
            agreed += 1
            continue
        witnesses = strongest(witnesses)
        verdict, rule, allowed = weigh(registry, witnesses)
        needs, notes = [], []
        if subject_kind == 'item':
            verdict, rule = 'review', 'item-starts'
        elif (subject_kind, subject, other) in removed:
            verdict, rule = 'review', 'removed-by-hand'
        if subject_kind == 'npc' and subject not in world['npcs']:
            needs.append(f'NPC {subject} has no template')
        if subject_kind == 'object' and subject not in world['objects']:
            needs.append(f'object {subject} has no template')
        if kind in ('gives', 'takes') and other not in world['quests']:
            needs.append(f'quest {other} is not in the world')
        if subject_kind == 'npc' and subject in world['npcs'] and subject not in world['npcs_spawned']:
            notes.append(f'NPC {subject} is not spawned')
        if subject_kind == 'object' and subject in world['objects'] and subject not in world['objects_spawned']:
            notes.append(f'object {subject} is not spawned')
        if verdict == 'add' and needs:
            verdict = 'hold'
        out.append(Decision(kind, subject_kind, subject, other, verdict, rule, allowed, '', needs, notes, witnesses))
    return out, agreed


def decide_quests(records, gives, takes, world):
    """Decisions for the quests the world lacks.

    `records` is {quest: (name, [Evidence of its record])}; `gives` and `takes` are the decisions of decide_pairs
    plus what the world holds, as {quest: [(subject_kind, subject, verdict, allowed)]}."""
    out = []
    for quest, (name, witnesses) in sorted(records.items()):
        if quest in world['quests']:
            continue
        witnesses = strongest(witnesses)
        giving = [w for w in witnesses if w.use != 'reference']         # the record's values come from one of these
        allowed = 'public' if any(w.live and w.use == 'public' for w in giving) or (
            not any(w.live for w in giving) and any(w.use == 'public' for w in giving)) else 'private'
        if INTERNAL.search(name or ''):
            verdict, rule = 'review', 'looks-internal'
        elif any(w.live for w in giving):
            verdict, rule = 'add', 'record-seen-live'
        else:
            verdict, rule = 'review', 'record-not-live'
        needs, notes = [], []
        for role, sides in (('giver', sorted(gives.get(quest, []))), ('ender', sorted(takes.get(quest, [])))):
            things = [s for s in sides if s[0] != 'item']
            sure = [s for s in things if s[2] in ('add', 'hold', 'held')]         # passes a rule, whatever else it needs
            there = [s for s in sure if s[1] in world['npcs' if s[0] == 'npc' else 'objects']]
            if not sides:
                needs.append(f'no {role} known')
            elif not things:
                needs.append(f'an item starts it ({", ".join(str(s[1]) for s in sides[:4])}): not followed here')
            elif not sure:
                needs.append(f'its {role} is one claim only: ' + ', '.join(f'{s[0]} {s[1]}' for s in things[:4]))
            elif not there:
                needs.append(f'its {role} has no template: ' + ', '.join(f'{s[0]} {s[1]}' for s in sure[:4]))
            else:
                if not any(s[1] in world['npcs_spawned' if s[0] == 'npc' else 'objects_spawned'] for s in there):
                    notes.append(f'its {role} is not spawned: ' + ', '.join(f'{s[0]} {s[1]}' for s in there[:4]))
                notes.append(f'{role}: ' + ', '.join(f'{s[0]} {s[1]}' for s in there[:6]))
                if all(s[3] == 'private' for s in there):
                    allowed = 'private'
        if verdict == 'add' and needs:
            verdict = 'hold'
        out.append(Decision('quest', 'quest', quest, 0, verdict, rule, allowed, name, needs, notes, witnesses))
    return out


def resolve(registry, world, claims, records, removed=None):
    """(decisions, summary) from both sides. The summary keeps the kinds in the order they were decided."""
    removed = removed or {}
    pairs, summary = [], collections.OrderedDict()
    by_quest = {'gives': collections.defaultdict(list), 'takes': collections.defaultdict(list)}
    agreed = {}
    for kind in PAIRS:
        made, agreed[kind] = decide_pairs(registry, kind, claims.get(kind, {}), world, removed.get(kind, ()))
        pairs += made
        if kind in by_quest:
            for subject_kind, subject, quest in world[kind]:
                by_quest[kind][quest].append((subject_kind, subject, 'held', 'public'))
            for d in made:
                by_quest[kind][d.object].append((d.subject_kind, d.subject, d.verdict, d.allowed))
    quests = decide_quests(records, by_quest['gives'], by_quest['takes'], world)
    ready = {d.subject for d in quests if d.verdict == 'add'}
    for index, d in enumerate(pairs):              # a pair that only waits for a quest that is ready comes with it
        if d.verdict == 'hold' and d.kind in by_quest and d.object in ready and d.needs == [f'quest {d.object} is not in the world']:
            pairs[index] = d._replace(verdict='add', needs=[], notes=d.notes + [f'comes with quest {d.object}'])
    for kind in PAIRS:
        summary[kind] = dict(collections.Counter(d.verdict for d in pairs if d.kind == kind), agreed=agreed[kind])
    summary['quest'] = dict(collections.Counter(d.verdict for d in quests), agreed=sum(1 for q in records if q in world['quests']))
    return pairs + quests, summary


# ------------------------------------------------------------------ reading both sides
def load_world(db, build):
    """What the replayed world holds, as sets: the things, where they stand, and their relations.

    A vendor's list counts the lists it borrows (a negative item names another vendor's list), and what an NPC
    sells, gives or takes only during a game event counts too: the world holds those rows."""
    tables = {next(iter(row.values())) for row in db.query('SHOW TABLES', build)}

    def numbers(sql):
        return {int(next(iter(row.values()))) for row in db.query(sql, build)}

    def pairs(kind, sql, needs=()):
        if not set(needs) <= tables:
            return set()
        return {(kind, int(row['a']), int(row['b'])) for row in db.query(sql, build)}

    items = "type = 1 AND " if db.query("SHOW COLUMNS FROM npc_vendor LIKE 'type'", build) else ''
    own, borrowed = collections.defaultdict(set), collections.defaultdict(set)
    for _kind, npc, item in pairs('npc', f'SELECT entry a, item b FROM npc_vendor WHERE {items}item > 0'):
        own[npc].add(item)
    for row in db.query('SELECT entry a, item b FROM npc_vendor WHERE item < 0', build):
        borrowed[int(row['a'])].add(-int(row['b']))

    def stock(npc, seen=()):
        found = set(own.get(npc, ()))
        for other in borrowed.get(npc, ()):
            if other not in seen:
                found |= stock(other, seen + (npc,))
        return found
    sells = {('npc', npc, item) for npc in set(own) | set(borrowed) for item in stock(npc)}
    sells |= pairs('npc', f'SELECT c.id a, v.item b FROM game_event_npc_vendor v JOIN creature c ON c.guid = v.guid WHERE v.item > 0',
                   ('game_event_npc_vendor',))
    return {
        'quests': numbers('SELECT ID FROM quest_template'),
        'npcs': numbers('SELECT entry FROM creature_template'), 'npcs_spawned': numbers('SELECT DISTINCT id FROM creature'),
        'objects': numbers('SELECT entry FROM gameobject_template'), 'objects_spawned': numbers('SELECT DISTINCT id FROM gameobject'),
        'gives': pairs('npc', 'SELECT id a, quest b FROM creature_queststarter') | pairs('object', 'SELECT id a, quest b FROM gameobject_queststarter')
        | pairs('npc', 'SELECT id a, quest b FROM game_event_creature_quest', ('game_event_creature_quest',))
        | pairs('object', 'SELECT id a, quest b FROM game_event_gameobject_quest', ('game_event_gameobject_quest',)),
        'takes': pairs('npc', 'SELECT id a, quest b FROM creature_questender') | pairs('object', 'SELECT id a, quest b FROM gameobject_questender'),
        'sells': sells,
    }


def load_claims(db, registry, database='tracker'):
    """({kind: {(subject_kind, subject, object): [Evidence]}} for the pair kinds, {quest: (name, [Evidence])},
    {kind: the claims a hand correction takes back})."""
    claims = {kind: collections.defaultdict(list) for kind in PAIRS}
    kinds = ', '.join(facts.sql_value(kind) for kind in PAIRS)
    for row in db.query(f'SELECT source, kind, subject_kind, subject, object, build, samples, data FROM {facts.FACTS} WHERE kind IN ({kinds})', database):
        if row['source'] not in registry.sources:
            continue
        try:
            data = json.loads(row['data'])
        except ValueError:
            data = {}
        claims[row['kind']][(row['subject_kind'], int(row['subject']), int(row['object']))] += evidence(
            registry, row['source'], int(row['build']), int(row['samples']), data)
    records = {}
    for row in db.query(f"SELECT source, subject, build, samples, JSON_UNQUOTE(JSON_EXTRACT(data, '$.title')) title FROM {facts.FACTS} "
                        f"WHERE kind = 'quest' ORDER BY build", database):
        if row['source'] not in registry.sources:
            continue
        name, witnesses = records.get(int(row['subject']), ('', []))
        title = row['title'] if row['title'] not in (None, 'null') else ''
        records[int(row['subject'])] = (title or name, witnesses + evidence(registry, row['source'], int(row['build']), int(row['samples']), {}))
    removed = {kind: set() for kind in PAIRS}
    for row in db.query(f"SELECT subject_kind, subject, data FROM {facts.FACTS} WHERE kind = 'entry' AND data LIKE '%\\_remove%'", database):
        try:
            parts = json.loads(row['data']).get('parts', {})
        except ValueError:
            continue
        for kind, pair in taken_back(row['subject_kind'], int(row['subject']), parts):
            removed[kind].add(pair)
    return claims, records, removed


def taken_back(entity, subject, parts):
    """The claims an entry's `_remove` corrections take back, as (kind, (subject_kind, subject, object))."""
    for entry in parts.values() if isinstance(parts, dict) else ():
        for field, (kind, entity_is_subject, other) in facts.QUESTIE_RELATIONS.get(entity, {}).items():
            value = entry.get(field + '_remove') if isinstance(entry, dict) else None
            if kind not in PAIRS or not isinstance(value, list):
                continue
            lists = [(other[i], ids) for i, ids in enumerate(value[:len(other)])] if isinstance(other, tuple) else [(other, value)]
            for other_kind, ids in lists:
                for one in ids if isinstance(ids, list) else ():
                    if isinstance(one, int) and not isinstance(one, bool):
                        yield kind, ((entity, subject, one) if entity_is_subject else (other_kind, one, subject))


# ------------------------------------------------------------------ storing
def write_sql(path, decisions, summary, now='NOW()', batch=400):
    """Writes the statements that replace every decision, all or nothing."""
    head = f'INSERT INTO {DECISIONS} (kind, subject_kind, subject, object, verdict, rule, allowed, name, needs, notes, witnesses) VALUES\n'
    dump = lambda value, sort=True: json.dumps(value, ensure_ascii=True, sort_keys=sort, separators=(',', ':'))
    with open(path, 'w', encoding='utf-8', errors='replace', newline='\n') as out:
        out.write("SET NAMES utf8mb4;\nSET SESSION sql_mode = 'STRICT_ALL_TABLES';\n" + ';\n'.join(SCHEMA) + f';\nSTART TRANSACTION;\nDELETE FROM {DECISIONS};\n')
        rows = []
        for d in decisions:
            rows.append('(' + ', '.join(facts.sql_value(v) for v in (
                d.kind, d.subject_kind, d.subject, d.object, d.verdict, d.rule, d.allowed, d.name[:255], dump(d.needs), dump(d.notes),
                dump([w._asdict() for w in d.witnesses]))) + ')')
            if len(rows) >= batch:
                out.write(head + ',\n'.join(rows) + ';\n')
                rows = []
        if rows:
            out.write(head + ',\n'.join(rows) + ';\n')
        out.write(f'REPLACE INTO {RESOLVED} (id, resolved_at, summary) VALUES (1, {now}, {facts.sql_value(dump(list(summary.items()), False))});\nCOMMIT;\n')


def stored_summary(db, database='tracker'):
    """(when, {kind: {verdict: count, 'agreed': count}}, in the order decided) of the last resolve, or (None, {})."""
    if not db.query(f"SHOW TABLES LIKE '{RESOLVED}'", database):
        return None, {}
    rows = db.query(f'SELECT resolved_at, summary FROM {RESOLVED} WHERE id = 1', database)
    return (rows[0]['resolved_at'], collections.OrderedDict(json.loads(rows[0]['summary']))) if rows else (None, {})


def stored(db, kind, verdict=None, limit=50, database='tracker'):
    """(stored decisions of a kind as dicts with needs, notes and witnesses read back, how many there are in all)."""
    if not db.query(f"SHOW TABLES LIKE '{DECISIONS}'", database):
        return [], 0
    where = f'kind = {facts.sql_value(kind)}' + (f' AND verdict = {facts.sql_value(verdict)}' if verdict else '')
    total = int(db.query(f'SELECT COUNT(*) n FROM {DECISIONS} WHERE {where}', database)[0]['n'])
    out = []
    for row in db.query(f'SELECT * FROM {DECISIONS} WHERE {where} ORDER BY subject, object LIMIT {max(1, int(limit))}', database):
        row.update(subject=int(row['subject']), object=int(row['object']), needs=json.loads(row['needs']), notes=json.loads(row['notes']),
                   witnesses=json.loads(row['witnesses']))
        out.append(row)
    return out, total
