"""What the server provides: its DB2 files, the hotfixes and world databases and the map files."""
import json
import os
import re

from . import corespells, db2, sqlio, summons
from .config import CONFIG, DATA
from .content import EFFECT_CREATE_ITEM, EFFECT_LEARN_SPELL

NPCFLAG_FLIGHTMASTER = 8192
EFFECT_SUMMON = 28   # SpellEffect.Effect: EffectMiscValue1 is the creature
EFFECT_KILL_CREDIT = (90, 134)   # SpellEffect.Effect: kill credit of the creature EffectMiscValue1 (personal, party)
ACQUIRE_NEVER = 3   # SkillLineAbility.AcquireMethod: the core's NeverLearned
ITEM_FLAG_HAS_LOOT = 0x4   # ItemSparse Flags[0]: the item opens as loot (ITEM_FLAG_HAS_LOOT)
EFFECT_APPLY_AURA, AURA_DUMMY = 6, 4   # SpellEffect.Effect / EffectAura: a seal's dummy aura names its judgement in its points
AURA_CHANNEL_DEATH_ITEM = 86   # SPELL_AURA_CHANNEL_DEATH_ITEM (the core's SpellAuraDefines.h): EffectItemType made when the target dies
SMART_ACTIVATE_TAXI = 52   # smart_scripts.action_type: action_param1 is the TaxiPath
AREATRIGGER_ACTION_TELEPORT = 2   # areatrigger_template_actions.ActionType: ActionParam is a world_safe_locs ID


def log(message):
    import time
    print(time.strftime('%H:%M:%S'), message, flush=True)


DBC = None  # the server's DB2 folder, checked by server_dbc()


def server_dbc():
    """The server's DB2 folder; stops the analysis with a clear message when config.ini does not lead to it."""
    global DBC
    if DBC:
        return DBC
    folder, configured = CONFIG.dbc_folder()
    if not folder:
        raise SystemExit(
            f"No DB2 file of your server was found in [server] dbc = {configured or '(empty)'}.\n"
            "Set [server] root and dbc in config.ini to the folder that contains the server's .db2 files "
            "(SpellName.db2, ItemSparse.db2...), for example root = \"C:/WoW/Server\" and dbc = \"data/dbc/enUS\".\n"
            "Without them every resource would look unknown to the core.")
    if os.path.normcase(folder) != os.path.normcase(configured or ''):
        log(f'warning: no DB2 file in [server] dbc = {configured}; using {folder} (fix config.ini)')
    DBC = folder
    return DBC


def server_db2(name):
    path = os.path.join(server_dbc(), name + '.db2')
    return list(db2.Table(path, name)) if os.path.isfile(path) else []


def tree_spells(read):
    """Spells a talent or perk tree grants: the spell of every TraitDefinition that sits on a node of a tree (WoW:
    Forever's class trees and Legacy perks are trait trees; the Talent table only holds the original game's)."""
    definitions = {r['ID']: r['SpellID'] for r in read('TraitDefinition')}
    entries = {r['ID']: r['TraitDefinitionID'] for r in read('TraitNodeEntry')}
    nodes = {r['ID'] for r in read('TraitNode')}
    return {definitions.get(entries.get(link['TraitNodeEntryID']), 0) for link in read('TraitNodeXTraitNodeEntry') if link['TraitNodeID'] in nodes} - {0}


# Where an object keeps its conversation menu, by object type (GameObjectTemplate::GetGossipMenuId of the core): a
# quest giver in Data3, a spell focus in Data10, a goober in Data19, an assist action in Data2.
GO_MENU_COLUMN = {2: 'Data3', 8: 'Data10', 10: 'Data19', 64: 'Data2'}
# SmartAI: the event of a conversation choice (menu, option) and the actions that cast a spell
SMART_GOSSIP_SELECT = 62
SMART_CASTS = (11, 85, 86, 134)   # CAST, SELF_CAST, CROSS_CAST, INVOKER_CAST: the spell is action_param1
# A choice may run a timed action list instead (source_type 9, its rows' entryorguid is the list's id), whose rows cast:
# CALL_TIMED_ACTIONLIST (the list is action_param1), CALL_RANDOM_TIMED_ACTIONLIST (one of action_param1..6),
# CALL_RANDOM_RANGE_TIMED_ACTIONLIST (one from action_param1 to action_param2). Gloom'rel teaches Smelt Dark Iron so.
SMART_CALL_LIST, SMART_CALL_RANDOM_LIST, SMART_CALL_RANGE_LIST = 80, 87, 88
SMART_TIMED_LIST = 9
# A row's `link` names the row (same entryorguid and source_type) that runs right after it; that row's event is LINK.
# Gloom'rel's choice only closes the window and links to the row that calls the timed list.
SMART_LINK = 61


def linked_choices(rows):
    """The conversation choices of SmartAI rows with the actions of every row they link to, as choice_spells() takes
    them: [(source_type, entryorguid, menu, option, action_type, [action_param1..6])]. rows: dicts of smart_scripts
    rows (source_type, entryorguid, id, link, event_type, event_param1, event_param2, action_type, action_param1..6)
    with event GOSSIP_SELECT or LINK."""
    by_id = {(int(r['source_type']), int(r['entryorguid']), int(r['id'])): r for r in rows}
    out = []
    for r in rows:
        if int(r['event_type']) != SMART_GOSSIP_SELECT:
            continue
        source, guid = int(r['source_type']), int(r['entryorguid'])
        seen, row = set(), r
        while row is not None and int(row['id']) not in seen:
            seen.add(int(row['id']))
            out.append((source, guid, int(r['event_param1'] or 0), int(r['event_param2'] or 0), int(row['action_type']),
                        [row.get(f'action_param{i}') or 0 for i in range(1, 7)]))
            following = by_id.get((source, guid, int(row.get('link') or 0))) if int(row.get('link') or 0) else None
            row = following if following is not None and int(following['event_type']) == SMART_LINK else None
    return out
# The core's own C++ scripts that teach a spell in a conversation (a creature) or on use (an object), by script name:
# (kind, the spells they cast on the player). Only scripts read in the realm's core and found to work on WoW: Forever.
# Knot Thimblejack, the engineering transporters and Omarion work from core fork PR 60 (f6bb68c6) on: before it, Knot
# asked for quest 5518 rewarded and "complete" at once, the transporters checked skill line 2506 (not in the Forever
# client), and Omarion cast pattern spells the client lacks (all but Icebane Breastplate).
CORE_TEACHERS = {
    'boss_gloomrel': ('npc', {14894}),   # Gloom'rel, Blackrock Depths: Learn Smelt Dark Iron
    # Knot Thimblejack, Dire Maul (quest 5518 turned in, skill 275): Learn Gordok Ogre Suit (tailoring, leatherworking)
    'classic_npc_knot_thimblejack': ('npc', {22814, 22816}),
    # Zap Farflinger, Jhordy Lapforge (Engineering 260, Goblin / Gnomish Engineer): the Everlook and Gadgetzan transporters
    'npc_engineering_tele_trinket': ('npc', {23490, 23491}),
    # Master Craftsman Omarion, Naxxramas (Argent Dawn Revered or Exalted, skill 300): Classic's learn spells of his 13
    # recipes (28245, the plans' own spell, before the fix)
    'classic_mob_craftsman_omarion': ('npc', set(range(28251, 28264)) | {28245}),
    # Schematic: Field Repair Bot 74A, Blackrock Depths: used at Engineering 300, Learn Field Repair Bot 74A
    'classic_go_field_repair_bot_74A': ('go', {22864}),
}


def conversation_casts(creature_menus, object_menus, options, smart, scripts):
    """[(kind, entry, spell)]: the spells a conversation with a creature ('npc') or an object ('go') casts on the player.
    creature_menus / object_menus: [(entry, menu)] the menus a template opens with; options: [(menu, option, next menu)];
    smart: [(kind, entry, menu, option, spell)] SmartAI choices of templates that run SmartAI; scripts: [(kind, entry,
    script name)] of creatures and objects (CORE_TEACHERS of that kind teach whatever their menus). A choice counts when its menu is one the template's conversation reaches and the
    option is in that menu."""
    leads, exists = {}, set()
    for menu, option, following in options:
        exists.add((menu, option))
        if following:
            leads.setdefault(menu, set()).add(following)
    reach = {}

    def reached(roots):
        seen, todo = set(), list(roots)
        while todo:
            menu = todo.pop()
            if menu and menu not in seen:
                seen.add(menu)
                todo.extend(leads.get(menu, ()))
        return seen
    for kind, rows in (('npc', creature_menus), ('go', object_menus)):
        roots = {}
        for entry, menu in rows:
            roots.setdefault(entry, set()).add(menu)
        for entry, menus in roots.items():
            reach[(kind, entry)] = reached(menus)
    found = set()
    for kind, entry, menu, option, spell in smart:
        if spell and menu in reach.get((kind, entry), ()) and (menu, option) in exists:
            found.add((kind, entry, spell))
    for kind, entry, name in scripts:
        teaches = CORE_TEACHERS.get(name)
        if teaches and teaches[0] == kind:
            found.update((kind, entry, spell) for spell in teaches[1])
    return sorted(found)


def choice_spells(choices, lists):
    """[(source_type, entryorguid, menu, option, spell)]: what each SmartAI conversation choice casts, itself or through
    a timed action list it calls (a random one counts: each may be the one that runs). choices: [(source_type,
    entryorguid, menu, option, action_type, [action_param1..6])]; lists: {list id: {spells its rows cast}}."""
    out = set()
    for source, guid, menu, option, action, params in choices:
        params = [int(p or 0) for p in params] + [0] * 6
        if action in SMART_CASTS:
            spells = {params[0]}
        elif action == SMART_CALL_LIST:
            spells = lists.get(params[0], set())
        elif action == SMART_CALL_RANDOM_LIST:
            spells = set().union(*(lists.get(p, set()) for p in params[:6] if p))
        elif action == SMART_CALL_RANGE_LIST and 0 < params[0] <= params[1] and params[1] - params[0] <= 1000:
            spells = set().union(*(lists.get(p, set()) for p in range(params[0], params[1] + 1)))
        else:
            spells = set()
        out.update((source, guid, menu, option, spell) for spell in spells if spell)
    return sorted(out)


SMART_KILLED_MONSTER = 33   # smart_scripts.action_type: CALL_KILLEDMONSTER, the credit creature is action_param1
SMART_TARGET_SELF = 1
# smart_scripts.action_type FOLLOW: the scripted creature follows its target, and when it reaches the creature
# action_param3 the core gives the credit action_param4 (action_param5 0 = as a kill): the Escaped Sheep 265962 led back
# to Mirt 248419 (Ewe Wandered Off)
SMART_FOLLOW = 29


# the template column of the spell a world object casts on the player who uses it, by gameobject type (the core's
# GameObjectTemplate): a goober's spell (Data10), a spellcaster's (Data0), a trap's (Data3)
OBJECT_SPELL_COLUMN = {10: 'Data10', 22: 'Data0', 6: 'Data3'}


def object_credits(objects, credit_spells, effects, depth=3):
    """{credit creature: {object entries}}: the world objects whose own spell (OBJECT_SPELL_COLUMN), or a spell it
    triggers (EffectTriggerSpell, up to depth steps), has a kill-credit effect for that creature (credit_spells:
    {credit: {spells}}): using the object gives the credit (the Old Dinghy of Aeonas's Secret Refuge, the Deadwood
    Cauldrons). objects: (entry, spell) pairs; effects: SpellEffect dicts (SpellID, EffectTriggerSpell)."""
    triggers = {}
    for e in effects:
        if e['EffectTriggerSpell'] and e['EffectTriggerSpell'] != e['SpellID']:
            triggers.setdefault(e['SpellID'], set()).add(e['EffectTriggerSpell'])
    gives = {}
    for credit, spells in credit_spells.items():
        for spell in spells:
            gives.setdefault(spell, set()).add(credit)
    out = {}
    for entry, spell in objects:
        reach, edge = {spell}, {spell}
        for _ in range(depth):
            edge = {t for s in edge for t in triggers.get(s, ())} - reach
            reach |= edge
        for s in reach:
            for credit in gives.get(s, ()):
                out.setdefault(credit, set()).add(entry)
    return out


def smart_credits(rows, credit_spells, entry_of=None):
    """{credit creature: {(kind, entry)}}: the creatures ('npc') and world objects ('go') whose SmartAI gives a kill
    credit to a player: CALL_KILLEDMONSTER, FOLLOW to a creature that ends in a credit, or a cast of a spell with a kill-credit effect (credit_spells: {credit:
    {spells}}), at a target other than the scripted thing itself. A timed action list counts for every script that
    calls it. rows: smart_scripts dicts (entryorguid, source_type, action_type, action_param1..6, target_type);
    entry_of: {(kind, -guid): entry} for one spawn's own script (a negative entryorguid)."""
    entry_of = entry_of or {}
    gives = {}
    for credit, spells in credit_spells.items():
        for spell in spells:
            gives.setdefault(spell, set()).add(credit)
    kinds = {0: 'npc', 1: 'go'}
    credits_of, callers = {}, {}
    for r in rows:
        source, guid, action = int(r['source_type']), int(r['entryorguid']), int(r['action_type'])
        params = [int(r.get(f'action_param{i}') or 0) for i in range(1, 7)]
        if source in kinds:
            owner = (kinds[source], guid if guid > 0 else entry_of.get((kinds[source], guid)))
        elif source == SMART_TIMED_LIST:
            owner = ('list', guid)
        else:
            continue
        if owner[1] is None:
            continue
        if action == SMART_CALL_LIST:
            callers.setdefault(params[0], set()).add(owner)
        elif action == SMART_CALL_RANDOM_LIST:
            for p in params:
                p and callers.setdefault(p, set()).add(owner)
        elif action == SMART_CALL_RANGE_LIST and 0 < params[0] <= params[1] and params[1] - params[0] <= 1000:
            for p in range(params[0], params[1] + 1):
                callers.setdefault(p, set()).add(owner)
        if int(r.get('target_type') or 0) == SMART_TARGET_SELF:
            continue
        found = {params[0]} if action == SMART_KILLED_MONSTER and params[0] else gives.get(params[0], set()) if action in SMART_CASTS else set()
        if action == SMART_FOLLOW and params[2] and params[3] and not params[4]:
            found = {params[3]}
        for credit in found:
            credits_of.setdefault(owner, set()).add(credit)
    out = {}
    for owner, credits in credits_of.items():
        owners, todo, seen = set(), [owner], set()
        while todo:
            o = todo.pop()
            if o in seen:
                continue
            seen.add(o)
            if o[0] == 'list':
                todo.extend(callers.get(o[1], ()))
            else:
                owners.add(o)
        for credit in credits:
            out.setdefault(credit, set()).update(owners)
    return out


AREATRIGGER_ACTION_CAST = 0   # areatrigger_template_actions.ActionType: cast ActionParam on the unit that enters


def spawned_trigger_casts(q, has_table):
    """[{AreaTriggerId, ActionParam}]: the spells the area triggers spawned in the world (an `areatrigger` row, through
    its create properties) cast on who enters them."""
    if not all(has_table(t) for t in ('areatrigger', 'areatrigger_create_properties', 'areatrigger_template_actions')):
        return []
    return q(f"SELECT DISTINCT a.AreaTriggerId, a.ActionParam FROM areatrigger_template_actions a "
             f"JOIN areatrigger_create_properties p ON p.AreaTriggerId = a.AreaTriggerId AND p.IsAreatriggerCustom = a.IsCustom "
             f"JOIN areatrigger s ON s.AreaTriggerCreatePropertiesId = p.Id AND s.IsCustom = p.IsCustom "
             f"WHERE a.ActionType = {AREATRIGGER_ACTION_CAST} AND a.ActionParam > 0")


def spellclick_casts(q, has_table):
    """[(npc entry, spell)]: the spells creatures make whoever clicks them cast (npc_spellclick_spells)."""
    if not has_table('npc_spellclick_spells'):
        return []
    return [(int(r['npc_entry']), int(r['spell_id'])) for r in q('SELECT DISTINCT npc_entry, spell_id FROM npc_spellclick_spells WHERE spell_id > 0')]


def read_conversations(q, has_table):
    """conversation_casts() from the world database."""
    whole = lambda v: int(v or 0)
    if has_table('creature_template_gossip'):
        creature_menus = [(whole(r['CreatureID']), whole(r['MenuID'])) for r in q('SELECT CreatureID, MenuID FROM creature_template_gossip')]
    elif sqlio.has_column('creature_template', 'gossip_menu_id'):
        creature_menus = [(whole(r['entry']), whole(r['gossip_menu_id'])) for r in q('SELECT entry, gossip_menu_id FROM creature_template WHERE gossip_menu_id > 0')]
    else:
        creature_menus = []
    object_menus = []
    for kind, column in GO_MENU_COLUMN.items():
        object_menus += [(whole(r['entry']), whole(r['menu'])) for r in q(f'SELECT entry, {column} menu FROM gameobject_template WHERE type = {kind} AND {column} > 0')]
    options = [(whole(r['MenuID']), whole(r['OptionID']), whole(r['ActionMenuID'])) for r in q('SELECT MenuID, OptionID, ActionMenuID FROM gossip_menu_option')]
    smart = []
    if has_table('smart_scripts'):
        # every choice row and every LINK row (a choice's own action may only close the window and link on)
        choices = linked_choices(q(f"SELECT entryorguid, source_type, id, link, event_type, event_param1, event_param2, action_type, action_param1, "
                                   f"action_param2, action_param3, action_param4, action_param5, action_param6 FROM smart_scripts "
                                   f"WHERE event_type IN ({SMART_GOSSIP_SELECT}, {SMART_LINK}) AND source_type IN (0, 1)"))
        lists = {}
        if any(c[4] not in SMART_CASTS for c in choices):
            for r in q(f"SELECT entryorguid, action_param1 FROM smart_scripts WHERE source_type = {SMART_TIMED_LIST} "
                       f"AND action_type IN ({','.join(map(str, SMART_CASTS))}) AND action_param1 > 0"):
                lists.setdefault(int(r['entryorguid']), set()).add(whole(r['action_param1']))
        rows = [{'source_type': source, 'entryorguid': guid, 'event_param1': menu, 'event_param2': option, 'action_param1': spell}
                for source, guid, menu, option, spell in choice_spells(choices, lists)]
        # a negative entryorguid is one spawn's script: its template's entry
        spawns = {('npc', -int(r['entryorguid'])) if int(r['source_type']) == 0 else ('go', -int(r['entryorguid'])) for r in rows if int(r['entryorguid']) < 0}
        entry_of = {}
        for kind, table in (('npc', 'creature'), ('go', 'gameobject')):
            guids = sorted(guid for k, guid in spawns if k == kind)
            for start in range(0, len(guids), 1000):
                for r in q(f"SELECT guid, id FROM {table} WHERE guid IN ({','.join(map(str, guids[start:start + 1000]))})"):
                    entry_of[(kind, int(r['guid']))] = int(r['id'])
        smart_ai = {('npc', int(v)) for v in sqlio.column("SELECT entry FROM creature_template WHERE AIName = 'SmartAI'")} | \
                   {('go', int(v)) for v in sqlio.column("SELECT entry FROM gameobject_template WHERE AIName = 'SmartGameObjectAI'")}
        for r in rows:
            kind = 'npc' if int(r['source_type']) == 0 else 'go'
            raw = int(r['entryorguid'])
            entry = raw if raw > 0 else entry_of.get((kind, -raw), 0)
            if (kind, entry) in smart_ai:
                smart.append((kind, entry, whole(r['event_param1']), whole(r['event_param2']), whole(r['action_param1'])))
    names = ','.join(sqlio.escape(name) for name in CORE_TEACHERS)
    scripts = [('npc', whole(r['entry']), r['ScriptName']) for r in q(f'SELECT entry, ScriptName FROM creature_template WHERE ScriptName IN ({names})')]
    scripts += [('go', whole(r['entry']), r['ScriptName']) for r in q(f'SELECT entry, ScriptName FROM gameobject_template WHERE ScriptName IN ({names})')]
    return conversation_casts(creature_menus, object_menus, options, smart, scripts)


def vendor_items(rows):
    """[(vendor, item)] with the borrowed lists written out: a negative item in npc_vendor is another vendor's entry,
    whose whole stock this vendor sells too (the core follows it the same way, a list inside a list included)."""
    stock, borrows = {}, {}
    for vendor, item in rows:
        (stock if item > 0 else borrows).setdefault(vendor, set()).add(abs(item))
    out = []
    for vendor in set(stock) | set(borrows):
        items, seen, todo = set(), set(), [vendor]
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            items |= stock.get(current, set())
            todo.extend(borrows.get(current, ()))
        out.extend((vendor, item) for item in sorted(items))
    return out


TURN_IN_HEADING = re.compile(r'(?:Progress|Completion)\n')


def page_has_turn_in_words(text):
    """Whether a Wowhead quest page's text (the crawler's whole page) holds a Progress or a Completion section after
    its Description heading (app/wowheadpages.php wowhead_pages_turn_in_text reads the same)."""
    at = re.search(r'(?:^|\n)Description\n', text or '')
    rest = (text or '')[at.end():] if at else (text or '')
    return bool(TURN_IN_HEADING.search(rest))


def quests_without_turn_in_words():
    """{quest} whose Forever page the crawler kept whole and that shows no turn-in words; empty when the answers table
    is not there (a tracker without the crawl)."""
    try:
        if not sqlio.has_table('ft_source_answers', 'tracker'):
            return set()
        rows = sqlio.query("SELECT id, JSON_UNQUOTE(JSON_EXTRACT(whole, '$.text')) words FROM ft_source_answers WHERE source = 'wowhead' "
                           "AND feed = 'page' AND kind = 'quest' AND branch = 'forever' AND status = 'found' AND whole IS NOT NULL", 'tracker')
    except RuntimeError as error:
        log(f'the Wowhead quest pages cannot be read ({error}): turn-in words are asked of every quest')
        return set()
    return {int(r['id']) for r in rows if r.get('words') and not page_has_turn_in_words(r['words'])}


def report_sides(path=None):
    """{quest: {'Alliance', 'Horde'}} from the players' reports the website keeps (data/foreverchanges/pack.fcpack),
    for the quests its players saw; {} without a pack, or with one that cannot be read."""
    from . import reports
    path = path or os.path.join(DATA, 'foreverchanges', 'pack.fcpack')
    if not os.path.isfile(path):
        return {}
    try:
        return reports.quest_sides(reports.load(path))
    except (OSError, ValueError, EOFError, KeyError):
        log('the ForeverChanges pack cannot be read: quest sides are not checked')
        return {}


def zone_rectangles(assignments):
    """The world rectangle each zone's map draws, from UiMapAssignment rows, in the shape the zone rule reads:
    [{'assignments': [{'area', 'map', 'region': (min x, min y, max x, max y)}]}]. A row that names no zone (a
    continent's map, a dungeon floor) says nothing about a zone and is left out."""
    out = []
    for row in assignments:
        if not row.get('AreaID'):
            continue
        xs, ys = (row['Region1X'], row['Region2X']), (row['Region1Y'], row['Region2Y'])
        out.append({'assignments': [{'area': row['AreaID'], 'map': row['MapID'], 'region': (min(xs), min(ys), max(xs), max(ys))}]})
    return out


def used_spells(item_spells, effects, script_casts=None):
    """{spell: {item}}: what using an item casts, the spells those trigger included (a learn effect teaches its spell,
    it casts nothing). The Empty Leaden Collection Phial fills itself into the Full one, the Heated Ancient Blade
    becomes the Treated one: the item a spell of these creates is made by using an item. script_casts ({spell:
    {spells}}) adds what a spell's C++ script casts (the Bending Shinbone 8856 casts 8854 or 8855). The keys of
    item_spells need not be items: a world object's ('go', entry) works the same."""
    triggers = {}
    for e in effects:
        if e['EffectTriggerSpell'] and e['EffectTriggerSpell'] != e['SpellID'] and e['Effect'] != EFFECT_LEARN_SPELL:
            triggers.setdefault(e['SpellID'], set()).add(e['EffectTriggerSpell'])
    for spell, targets in (script_casts or {}).items():
        triggers.setdefault(spell, set()).update(set(targets) - {spell})
    used = {}
    for item_id, spells in item_spells.items():
        todo, seen = list(spells), set()
        while todo:
            spell = todo.pop()
            if spell not in seen:
                seen.add(spell)
                todo.extend(triggers.get(spell, ()))
        for spell in seen:
            used.setdefault(spell, set()).add(item_id)
    return used


def server_state():
    log(f'server: DB2 of the running server ({server_dbc()})')
    for key in ('maps', 'vmaps'):
        if not (CONFIG.server_path(key) and os.path.isdir(CONFIG.server_path(key))):
            log(f'warning: [server] {key} = {CONFIG.server_path(key) or "(empty)"} does not exist: instances and zones will look unextracted')
    ctx = {}
    srv = server_db2
    ids = lambda name: {r['ID'] for r in srv(name)}
    hot = lambda name: {int(x) for x in sqlio.column(f'SELECT ID FROM {name}', 'hotfixes')} if sqlio.has_table(name, 'hotfixes') else set()
    ctx['known'] = {
        'item': ids('ItemSparse') | hot('item_sparse'), 'spell': ids('SpellName') | hot('spell_name'), 'talent': ids('Talent') | hot('talent'),
        'quest': ids('QuestV2') | hot('quest_v2'), 'dungeon': ids('Map') | hot('map'), 'boss': ids('DungeonEncounter') | hot('dungeon_encounter'),
        'zone': ids('AreaTable') | hot('area_table'), 'achievement': ids('Achievement') | hot('achievement'), 'taxi': ids('TaxiNodes') | hot('taxi_nodes'),
        'mount': ids('Mount') | hot('mount'), 'toy': ids('Toy') | hot('toy'), 'pet': ids('BattlePetSpecies') | hot('battle_pet_species'),
        'recipe': {r['Spell'] for r in srv('SkillLineAbility')} | {int(x) for x in sqlio.column('SELECT Spell FROM skill_line_ability', 'hotfixes')},
    }
    learn, creates, spell_summons, cast_by, credit_spells = {}, {}, set(), {}, {}
    spell_effects = srv('SpellEffect')
    for e in spell_effects:
        if e['Effect'] == EFFECT_LEARN_SPELL and e['EffectTriggerSpell']:
            learn.setdefault(e['SpellID'], set()).add(e['EffectTriggerSpell'])
        elif e['EffectTriggerSpell'] and e['EffectTriggerSpell'] != e['SpellID']:
            cast_by.setdefault(e['EffectTriggerSpell'], e['SpellID'])
        if e['Effect'] == EFFECT_CREATE_ITEM and e['EffectItemType']:
            creates.setdefault(e['EffectItemType'], set()).add(e['SpellID'])
        # an aura that makes its item when the target dies under it (Drain Soul's Soul Shard 6265)
        if e.get('EffectAura') == AURA_CHANNEL_DEATH_ITEM and e['EffectItemType']:
            creates.setdefault(e['EffectItemType'], set()).add(e['SpellID'])
        if e['Effect'] == EFFECT_SUMMON and e['EffectMiscValue1'] > 0:
            spell_summons.add(e['EffectMiscValue1'])
        if e['Effect'] in EFFECT_KILL_CREDIT and e['EffectMiscValue1'] > 0:
            credit_spells.setdefault(e['EffectMiscValue1'], set()).add(e['SpellID'])
    effects = {r['ID']: r['SpellID'] for r in srv('ItemEffect')}
    for row in sqlio.query('SELECT ID, SpellID FROM item_effect', 'hotfixes'):
        effects[int(row['ID'])] = int(row['SpellID'])
    item_spells = {}
    links = srv('ItemXItemEffect') + [{'ItemID': int(r['ItemID']), 'ItemEffectID': int(r['ItemEffectID'])} for r in sqlio.query('SELECT ItemID, ItemEffectID FROM item_x_item_effect', 'hotfixes')]
    for link in links:
        if link['ItemEffectID'] in effects:
            item_spells.setdefault(link['ItemID'], set()).add(effects[link['ItemEffectID']])
    teaches = {}
    for item_id, spells in item_spells.items():
        for spell in spells:
            for target in {spell} | learn.get(spell, set()):
                teaches.setdefault(target, set()).add(item_id)
    ctx['creates'], ctx['teaches'], ctx['item_spells'] = creates, teaches, item_spells
    ctx['used_spells'] = used_spells(item_spells, spell_effects)
    ctx['credit_spells'] = credit_spells
    # {spell: reagent items}: an item made from the same cards as one players get, by a spell nothing casts, is an unused
    # copy of it (ft.rules: Forever's second Portals Deck 235275 beside the classic 19277)
    reagent_rows = srv('SpellReagents')
    if sqlio.has_table('spell_reagents', 'hotfixes'):
        reagent_rows = reagent_rows + sqlio.query('SELECT * FROM spell_reagents', 'hotfixes')
    spell_reagents = {}
    for r in reagent_rows:
        items = frozenset(int(r.get(f'Reagent{i}') or 0) for i in range(1, 9)) - {0}
        if items:
            spell_reagents[int(r['SpellID'])] = items
    ctx['spell_reagents'] = spell_reagents
    ctx['auto_learn'] = {r['Spell'] for r in srv('SkillLineAbility') if r['AcquireMethod'] in (1, 2)}
    acquire, lines = {}, {}
    for r in srv('SkillLineAbility'):
        acquire.setdefault(r['Spell'], set()).add(r['AcquireMethod'])
        lines.setdefault(r['Spell'], set()).add(r['SkillLine'])
    # A seal's dummy aura names the judgement it unleashes in its points (Seal of Fury 20163: 20183, Judgement of Fury):
    # the judgement is cast, not learned. Only when both are of the same skill line, so a dummy's plain number (487
    # damage) never reads as a spell.
    for e in spell_effects:
        target = int(e['EffectBasePoints'] or 0) if e['Effect'] == EFFECT_APPLY_AURA and e['EffectAura'] == AURA_DUMMY else 0
        if target > 0 and target != e['SpellID'] and lines.get(target, set()) & lines.get(e['SpellID'], set()):
            cast_by.setdefault(target, e['SpellID'])
    # How the game data itself says a spell reaches a player without a trainer: every skill line listing it marks it
    # "never learned" (something else applies it), another spell casts it, a talent or perk tree grants it, or learning
    # one spell teaches another (a learn effect, or SpellLearnSpell: the core reads both).
    ctx['never_learned'] = {spell for spell, methods in acquire.items() if methods == {ACQUIRE_NEVER}}
    ctx['cast_by'] = cast_by
    ctx['tree_spells'] = tree_spells(srv)
    taught = {(source, target) for source, targets in learn.items() for target in targets}
    taught |= {(r['SpellID'], r['LearnSpellID']) for r in srv('SpellLearnSpell') if r['SpellID'] and r['LearnSpellID']}
    if sqlio.has_table('spell_learn_spell', 'hotfixes'):
        taught |= {(int(r['SpellID']), int(r['LearnSpellID'])) for r in sqlio.query('SELECT SpellID, LearnSpellID FROM spell_learn_spell', 'hotfixes')}
    ctx['spell_teaches'] = taught
    ctx['spell_ids'] = {r['ID'] for r in srv('SpellName')} | {r['SpellID'] for r in srv('SpellMisc')}
    # the item that starts a quest: ItemSparse.db2, then hotfixes.item_sparse (a hotfix row replaces the file's for its
    # item: the Forever items 277556-277558 that start 97270, 99233 and 99234 are hotfixes only)
    starts = {r['ID']: r['StartQuestID'] for r in srv('ItemSparse')}
    if sqlio.has_table('item_sparse', 'hotfixes'):
        for r in sqlio.query('SELECT ID, StartQuestID FROM item_sparse ORDER BY VerifiedBuild', 'hotfixes'):
            starts[int(r['ID'])] = int(r['StartQuestID'] or 0)
    ctx['start_quest_item'] = {quest: item for item, quest in sorted(starts.items()) if quest}
    # items that open as loot (ItemSparse Flags[0] 0x4 HAS_LOOT: the Coin Pouches, lockboxes) and items a player can
    # hold only one of (MaxCount 1: the core keeps such a quest item on accept), the file's then the hotfix's
    sparse = {r['ID']: (int(r.get('Flags1') or 0), int(r.get('MaxCount') or 0)) for r in srv('ItemSparse')}
    if sqlio.has_table('item_sparse', 'hotfixes'):
        try:
            for r in sqlio.query('SELECT ID, Flags1, MaxCount FROM item_sparse ORDER BY VerifiedBuild', 'hotfixes'):
                sparse[int(r['ID'])] = (int(r['Flags1'] or 0), int(r['MaxCount'] or 0))
        except Exception:   # an older hotfixes schema without the columns: the file's values stand
            pass
    ctx['item_has_loot'] = {item for item, (flags, _) in sparse.items() if flags & ITEM_FLAG_HAS_LOOT}

    log('server: world database')
    q = sqlio.query
    ints = lambda sql, db='world': {int(x) for x in sqlio.column(sql, db) if x is not None}
    ctx['spawned_npc'] = ints('SELECT DISTINCT id FROM creature')
    ctx['spawned_go'] = ints('SELECT DISTINCT id FROM gameobject')
    npc_maps = {}
    for row in q('SELECT c.map, c.id, COUNT(*) n, ct.name, ct.ScriptName, ct.AIName FROM creature c JOIN creature_template ct ON ct.entry = c.id GROUP BY c.map, c.id'):
        npc_maps.setdefault(int(row['map']), []).append({'id': int(row['id']), 'n': int(row['n']), 'name': row['name'] or '',
                                                          'scripted': bool(row['ScriptName']) or row['AIName'] == 'SmartAI'})
    ctx['npc_maps'] = npc_maps
    # Creatures and world objects something brings into the world without a spawn row (ft.summons): the database's
    # summons, the summoning spells, and what the core's C++ scripts summon. With the creatures an instance script
    # names as a boss encounter and the unspawned ones that have a C++ script, they are the bosses a script places
    # (ft.bosses); for loot, vendors and quests a summoned creature is as present as a spawned one (ft.rules).
    summoned, summoned_go, core = summons.known(spell_summons)
    ctx['summoned_npc'], ctx['summoned_go'] = summoned, summoned_go
    ctx['spell_summons'] = spell_summons   # the creatures a summoning spell brings in (the always-up check names them)
    ctx['encounter_npc'] = core['encounters']
    ctx['summon_script'] = core['creatures']
    ctx['script_credits'] = set(core.get('credits', {}))   # kill credits a C++ script gives (Arathi Basin's bases)
    bound = {entry for entries in core['encounters'].values() for entry in entries}
    ctx['unspawned_npc'] = [{'id': int(r['entry']), 'name': r['name'] or '', 'script': bool(r['ScriptName'])}
                            for r in q("SELECT ct.entry, ct.name, ct.ScriptName FROM creature_template ct WHERE NOT EXISTS (SELECT 1 FROM creature c WHERE c.id = ct.entry)")
                            if r['ScriptName'] or int(r['entry']) in summoned or int(r['entry']) in bound]
    # A kill objective may name a credit creature nobody spawns: the creatures that give that credit when they die.
    kill_credit = {}
    for r in q('SELECT entry, KillCredit1, KillCredit2 FROM creature_template WHERE KillCredit1 <> 0 OR KillCredit2 <> 0'):
        for credit in {int(r['KillCredit1'] or 0), int(r['KillCredit2'] or 0)} - {0}:
            kill_credit.setdefault(credit, set()).add(int(r['entry']))
    ctx['kill_credit'] = kill_credit
    # kill credits the database's own scripts give (SmartAI): the Tarantula Eggs of Alther's Mill, Ott, Ayessa
    if sqlio.has_table('smart_scripts'):
        rows = q(f"SELECT entryorguid, source_type, action_type, action_param1, action_param2, action_param3, action_param4, action_param5, "
                 f"action_param6, target_type FROM smart_scripts WHERE source_type IN (0, 1, {SMART_TIMED_LIST}) "
                 f"AND action_type IN ({SMART_KILLED_MONSTER}, {SMART_FOLLOW}, {','.join(map(str, SMART_CASTS))}, {SMART_CALL_LIST}, {SMART_CALL_RANDOM_LIST}, {SMART_CALL_RANGE_LIST})")
        entry_of = {}
        for kind, table, source in (('npc', 'creature', 0), ('go', 'gameobject', 1)):
            guids = sorted({-int(r['entryorguid']) for r in rows if int(r['entryorguid']) < 0 and int(r['source_type']) == source})
            if guids:
                for r in q(f"SELECT guid, id FROM {table} WHERE guid IN ({','.join(map(str, guids))})"):
                    entry_of[(kind, -int(r['guid']))] = int(r['id'])
        ctx['smart_credits'] = smart_credits(rows, credit_spells, entry_of)
    # kill credits a world object's own spell gives when used
    objects = [(int(r['entry']), int(r['spell'])) for type_, column in OBJECT_SPELL_COLUMN.items()
               for r in q(f'SELECT entry, {column} spell FROM gameobject_template WHERE type = {type_} AND {column} > 0')]
    ctx['object_credits'] = object_credits(objects, credit_spells, spell_effects)
    ctx['go_counts'] = {int(r['map']): int(r['n']) for r in q('SELECT map, COUNT(*) n FROM gameobject GROUP BY map')}
    ctx['spawns'] = [(int(r['map']), float(r['x']), float(r['y']), int(r['id'])) for r in q('SELECT map, position_x x, position_y y, id FROM creature WHERE map IN (0,1) OR map >= 2000')]
    ctx['flight_spawns'] = [(int(r['map']), float(r['x']), float(r['y'])) for r in q(f'SELECT c.map, c.position_x x, c.position_y y FROM creature c JOIN creature_template ct ON ct.entry=c.id WHERE ct.npcflag & {NPCFLAG_FLIGHTMASTER}')]
    # Flight points without a flight master: an NPC's script puts the player on the path (the druids' flights out of
    # Moonglade). The nodes a SmartAI "activate taxi" path leaves from.
    script_paths = ints(f'SELECT action_param1 FROM smart_scripts WHERE action_type = {SMART_ACTIVATE_TAXI}')
    ctx['script_taxi_nodes'] = {r['FromTaxiNode'] for r in srv('TaxiPath') if r['ID'] in script_paths}

    quests = {}
    # HasText: the giver's words or the objectives text, as a flag (the texts themselves would be most of the memory)
    for row in q("SELECT ID, LogTitle, QuestType, QuestSortID, QuestInfoID, Flags, AllowableRaces, StartItem, RewardSpell, RewardDisplaySpell1, RewardDisplaySpell2, RewardDisplaySpell3, "
                 "(COALESCE(QuestDescription, '') <> '' OR COALESCE(LogDescription, '') <> '') HasText, "
                 + ', '.join([f'RewardItem{i}' for i in range(1, 5)] + [f'RewardChoiceItemID{i}' for i in range(1, 7)]) + ' FROM quest_template'):
        quests[int(row['ID'])] = row
    # Which side each quest is for, as players reported it (a ForeverChanges pack sent on the Imports page)
    ctx['report_sides'] = report_sides()
    # What the NPC says at the turn-in: the reward text, or the "have you got it?" text of a quest that asks for items.
    ctx['quest_turn_in_text'] = ints("SELECT ID FROM quest_offer_reward WHERE COALESCE(RewardText, '') <> ''") | \
        ints("SELECT ID FROM quest_request_items WHERE COALESCE(CompletionText, '') <> ''")
    # Quests whose Wowhead page, read whole (crawler record v3: its text), shows no Progress and no Completion words:
    # the live game says nothing at their turn-in, so no turn-in text is asked of them (the 'texts' check).
    ctx['quest_no_official_turn_in'] = quests_without_turn_in_words()
    # The spells a quest shows as its reward: the core reads this table, not quest_template's three columns.
    display_spells = {}
    if sqlio.has_table('quest_reward_display_spell'):
        for r in q('SELECT QuestID, SpellID FROM quest_reward_display_spell WHERE SpellID > 0'):
            display_spells.setdefault(int(r['QuestID']), set()).add(int(r['SpellID']))
    ctx['quest_display_spells'] = display_spells
    ctx['quest_fr'] = {int(r['ID']): r['LogTitle'] for r in q("SELECT ID, LogTitle FROM quest_template_locale WHERE locale='frFR'") if r['LogTitle']} \
        if CONFIG.french() else {}
    ctx['quest_level'] = {int(r['ID']): (int(r['QuestLevel'] or 0), int(r['MinLevel'] or 0)) for r in q('SELECT ID, QuestLevel, MinLevel FROM quest_classic_level')} if sqlio.has_table('quest_classic_level') else {}
    ctx['quests'] = quests
    pairs = lambda sql: [(int(a), int(b)) for a, b in (tuple(r.values()) for r in q(sql))]
    ctx['q_start_npc'] = pairs('SELECT id, quest FROM creature_queststarter')
    ctx['q_end_npc'] = pairs('SELECT id, quest FROM creature_questender')
    ctx['q_start_go'] = pairs('SELECT id, quest FROM gameobject_queststarter')
    ctx['q_end_go'] = pairs('SELECT id, quest FROM gameobject_questender')
    # names of the creatures that give or take quests: a giver live replaced is found by its name (ft.rules)
    ctx['quest_npc_names'] = {int(r['entry']): r['name'] or '' for r in q(
        'SELECT entry, name FROM creature_template WHERE entry IN (SELECT id FROM creature_queststarter UNION SELECT id FROM creature_questender)')}
    ctx['objectives'] = [(int(r['QuestID']), int(r['Type']), int(r['ObjectID']), int(r['Amount'])) for r in q('SELECT QuestID, Type, ObjectID, Amount FROM quest_objectives')]
    ctx['quest_items_npc'] = pairs('SELECT CreatureEntry, ItemId FROM creature_questitem')
    ctx['quest_items_go'] = pairs('SELECT GameObjectEntry, ItemId FROM gameobject_questitem')
    disabled = {}
    for r in q('SELECT sourceType, entry FROM disables'):
        disabled.setdefault(int(r['sourceType']), set()).add(int(r['entry']))
    ctx['disabled'] = disabled

    log('server: loot, vendors and trainers')
    loot = {}
    for name in ('creature', 'gameobject', 'item', 'reference', 'pickpocketing', 'skinning', 'fishing', 'disenchant', 'prospecting', 'milling', 'spell', 'mail'):
        # ItemType: 0 item, 1 reference to reference_loot_template (Item = its Entry), 2 currency
        rows = q(f'SELECT Entry, ItemType, Item FROM {name}_loot_template')
        loot[name] = [(int(r['Entry']), int(r['ItemType'] or 0), int(r['Item']), int(r['Item']) if int(r['ItemType'] or 0) == 1 else 0) for r in rows]
    ctx['loot'] = loot
    # items that open with money of their own (item_template_addon MinMoneyLoot/MaxMoneyLoot: the core rolls it when
    # the item is opened, SpellHandler HandleOpenItemOpcode)
    ctx['item_money'] = ints('SELECT Id FROM item_template_addon WHERE MaxMoneyLoot > 0') if sqlio.has_table('item_template_addon') else set()
    ctx['npc_loot'] = [(int(r['Entry']), int(r['LootID'] or 0), int(r['PickPocketLootID'] or 0), int(r['SkinLootID'] or 0))
                       for r in q('SELECT Entry, LootID, PickPocketLootID, SkinLootID FROM creature_template_difficulty WHERE DifficultyID IN (0,1)')]
    # (entry, type, loot id) of each chest and fishing hole. A chest has three loot ids the core fills: chestLoot (Data1),
    # chestPersonalLoot (Data30, each player's own: the supply cart that teaches Recipe: Plated Armorfish) and
    # chestPushLoot (Data33, put straight into the bags); one row for each it has.
    ctx['go_loot'] = []
    for r in q('SELECT entry, type, Data1, Data30, Data33 FROM gameobject_template WHERE type IN (3, 25)'):
        ids = [r['Data1']] + ([r['Data30'], r['Data33']] if int(r['type']) == 3 else [])
        ctx['go_loot'] += [(int(r['entry']), int(r['type']), int(i)) for i in dict.fromkeys(int(x or 0) for x in ids) if i] \
            or [(int(r['entry']), int(r['type']), 0)]
    ctx['vendors'] = vendor_items(pairs('SELECT entry, item FROM npc_vendor WHERE type = 1'))
    # {item: {(vendor, ExtendedCost)}}: an item one vendor sells for currencies and another hands out for its money
    # price alone (ExtendedCost 0) is a lost price (ft.rules 'price')
    # A row whose ExtendedCost is in neither ItemExtendedCost.db2 nor its hotfixes is dropped by the core on load
    # (ObjectMgr::IsVendorItemValid "wrong ExtendedCost, ignore"), so it asks nothing: the PvP tabards' old TBC honor
    # rows (1003, 1006, 1007, 202, 2969) beside their gold-price rows. With no ItemExtendedCost.db2 every row counts.
    known_costs = ids('ItemExtendedCost') | hot('item_extended_cost')
    vendor_costs = {}
    for r in q('SELECT entry, item, ExtendedCost FROM npc_vendor WHERE type = 1 AND item > 0'):
        cost = int(r['ExtendedCost'] or 0)
        if cost and known_costs and cost not in known_costs:
            continue
        vendor_costs.setdefault(int(r['item']), set()).add((int(r['entry']), cost))
    ctx['vendor_costs'] = vendor_costs
    ctx['trainer_rows'] = [{k: int(v or 0) for k, v in r.items()} for r in q('SELECT TrainerId, SpellId, MoneyCost, ReqSkillLine, ReqSkillRank, ReqAbility1, ReqLevel FROM trainer_spell')]
    ctx['trainer_spells'] = [(r['TrainerId'], r['SpellId']) for r in ctx['trainer_rows']]
    ctx['trainers'] = pairs('SELECT CreatureID, TrainerID FROM creature_trainer')
    ctx['shop_items'] = ints('SELECT Param1 FROM shop_product_action WHERE Action = 1') if sqlio.has_table('shop_product_action') else set()
    # the Black Market Auction House's stock (TrinityCore blackmarket_template): (seller npc, item)
    ctx['blackmarket_items'] = pairs('SELECT sellerNpc, itemEntry FROM blackmarket_template') if sqlio.has_table('blackmarket_template') else []
    ctx['create_spells'] = (ints('SELECT Spell FROM playercreateinfo_spell_custom') if sqlio.has_table('playercreateinfo_spell_custom') else set()) | \
                           (ints('SELECT spell FROM playercreateinfo_cast_spell') if sqlio.has_table('playercreateinfo_cast_spell') else set())
    ctx['learn_chain'] = pairs('SELECT entry, SpellID FROM spell_learn_spell')
    ctx['conversation_casts'] = read_conversations(q, sqlio.has_table)
    ctx['pet_training'] = (ints('SELECT SpellId FROM classic_pet_spell_training_points') if sqlio.has_table('classic_pet_spell_training_points') else set()) | \
                          ints('SELECT Spell FROM creature_template_spell')
    # Which spells something handles: a SpellScript bound in spell_script_names (a negative id binds every rank, as the
    # core reads it), and an aura's proc setup: a spell_proc row or the client's proc flags (SpellAuraOptions).
    chains = corespells.rank_chains(srv('SkillLineAbility'))
    bound = {}
    for r in q('SELECT spell_id, ScriptName FROM spell_script_names'):
        for spell in corespells.expand(int(r['spell_id']), chains):
            bound.setdefault(spell, set()).add(r['ScriptName'] or '')
    ctx['spell_scripts'] = bound
    # What the core's C++ scripts cast (summoned.json casts, by script name): a spell script's casts follow its spell
    # like a trigger (using the Bending Shinbone 7131 casts 8856, whose script casts 8854 or 8855: the Dragonmaw
    # Shinbone); a creature's or object's script casts on the player who talks to it or uses it (Jaina's gossip casts
    # her autograph 23122, the Tablet of the Seven 15065). world_casts: {spell: {('npc'|'go', entry)}}, with a world
    # object's own spell (OBJECT_SPELL_COLUMN: the Windfury Cone's 412365) and what those trigger.
    casts = core.get('casts', {})
    script_triggers = {}
    for spell, names in bound.items():
        for name in names:
            script_triggers.setdefault(spell, set()).update(casts.get(name, ()))
    ctx['used_spells'] = used_spells(item_spells, spell_effects, script_triggers)
    holders = {}
    for entry, spell in objects:
        holders.setdefault(('go', entry), set()).add(spell)
    for kind, table in (('npc', 'creature_template'), ('go', 'gameobject_template')):
        for r in q(f"SELECT entry, ScriptName FROM {table} WHERE ScriptName <> ''"):
            if casts.get(r['ScriptName']):
                holders.setdefault((kind, int(r['entry'])), set()).update(casts[r['ScriptName']])
    # what a conversation casts on the player makes items too (SmartAI on a menu choice: Trevan Rol's gossip casts
    # Trevan's Weapon Notes 1280553, the note of A Moon-Kissed Blade)
    for kind, entry, spell in ctx['conversation_casts']:
        holders.setdefault((kind, entry), set()).add(spell)
    # and what a spawned area trigger casts on whoever walks in (areatrigger_template_actions, ActionType 0 = cast):
    # the Well of Eternity trigger 42773 casts Cleanse Heart 1293359 (Power Wash). ('at', id): only spawned ones.
    for r in spawned_trigger_casts(q, sqlio.has_table):
        holders.setdefault(('at', int(r['AreaTriggerId'])), set()).add(int(r['ActionParam']))
    # and what a creature makes its clicker cast (npc_spellclick_spells): Break Chain 1263364 on a Gelkis Captive 253431
    # (Saving Our Own), Planting Seed 1246989 on Sunderbark's corpse 248709 (The Dying Ancients)
    for entry, spell in spellclick_casts(q, sqlio.has_table):
        holders.setdefault(('npc', entry), set()).add(spell)
    ctx['world_casts'] = used_spells(holders, spell_effects, script_triggers)
    ctx['scripted_spells'] = set(bound) | {abs(int(x)) for x in sqlio.column('SELECT spell_id FROM spell_script_names')}
    ctx['spell_procs'] = {spell for x in sqlio.column('SELECT SpellId FROM spell_proc') for spell in corespells.expand(int(x), chains)}
    options = {r['SpellID']: r['ProcTypeMask1'] or r['ProcTypeMask2'] for r in srv('SpellAuraOptions')
               if r['ProcTypeMask1'] or r['ProcTypeMask2']}
    if sqlio.has_table('spell_aura_options', 'hotfixes'):
        for r in sqlio.query('SELECT SpellID, ProcTypeMask1, ProcTypeMask2 FROM spell_aura_options', 'hotfixes'):
            if int(r['ProcTypeMask1'] or 0) or int(r['ProcTypeMask2'] or 0):
                options[int(r['SpellID'])] = 1
    ctx['client_procs'] = set(options)
    ctx['core_spells'] = corespells.load()
    ctx['reviewed_dummies'] = corespells.reviewed()
    # a creature's or object's SmartAI that reacts to being hit by a spell (SMART_EVENT_SPELLHIT, _SPELLHIT_TARGET):
    # what a quest item's dummy spell does is often written there, on its target
    ctx['smart_spellhit'] = {int(x) for x in sqlio.column('SELECT DISTINCT event_param1 FROM smart_scripts WHERE event_type IN (8, 31)')
                             if x is not None and int(x) > 0} if sqlio.has_table('smart_scripts') else set()
    # spells whose aura a condition asks for (CONDITION_AURA, 1): {spell: how many conditions}
    ctx['aura_conditions'] = {int(r['spell']): int(r['n']) for r in sqlio.query(
        'SELECT ConditionValue1 spell, COUNT(*) n FROM conditions WHERE ConditionTypeOrReference = 1 AND ConditionValue1 > 0 GROUP BY ConditionValue1')} \
        if sqlio.has_table('conditions') else {}
    ctx['achievement_rewards'] = ints('SELECT ID FROM achievement_reward')
    # Achievements that pay a talent or perk currency (a Legacy Point): the core counts the achievement itself as the
    # source (TraitCurrencySource), no achievement_reward row is involved.
    ctx['achievement_currency'] = {r['AchievementID'] for r in srv('TraitCurrencySource') if r['AchievementID'] and r['Amount'] > 0}
    if sqlio.has_table('trait_currency_source', 'hotfixes'):
        ctx['achievement_currency'] |= ints('SELECT AchievementID FROM trait_currency_source WHERE AchievementID > 0 AND Amount > 0', 'hotfixes')
    ctx['graveyards'] = ints('SELECT GhostZone FROM graveyard_zone')

    ctx['instance_template'] = {int(r['map']): r['script'] for r in q('SELECT map, script FROM instance_template')}
    safe_map = {int(r['ID']): int(r['MapID']) for r in q('SELECT ID, MapID FROM world_safe_locs')}
    ctx['entrances'] = {safe_map.get(int(r['PortLocID'])) for r in q('SELECT PortLocID FROM areatrigger_teleport')}
    # A server-side area trigger placed in the world whose action teleports to a safe location (ActionType 2: the
    # fork's own dungeon portals, Hall of Thanes and the others), and a map a C++ script teleports into (ft.summons)
    if sqlio.has_table('areatrigger') and sqlio.has_table('areatrigger_template_actions') and sqlio.has_table('areatrigger_create_properties'):
        ctx['entrances'] |= {safe_map.get(int(r['ActionParam'])) for r in q(
            'SELECT act.ActionParam FROM areatrigger a JOIN areatrigger_create_properties p ON p.Id = a.AreaTriggerCreatePropertiesId '
            'AND p.IsCustom = a.IsCustom JOIN areatrigger_template_actions act ON act.AreaTriggerId = p.AreaTriggerId '
            f'AND act.IsCustom = p.IsAreatriggerCustom WHERE act.ActionType = {AREATRIGGER_ACTION_TELEPORT}')}
    ctx['entrances'] |= set(core['teleports'])
    ctx['entrances'].discard(None)
    declared = ints('SELECT ID FROM battleground_template')
    ctx['battlegrounds'] = {r['MapID'] for r in srv('BattlemasterListXMap') if r['BattlemasterListID'] in declared}
    listing = lambda key: os.listdir(CONFIG.server_path(key)) if CONFIG.server_path(key) and os.path.isdir(CONFIG.server_path(key)) else []
    tiles = {}
    for name in listing('maps'):
        if name.endswith('.map') and name[:4].isdigit():
            tiles[int(name[:4])] = tiles.get(int(name[:4]), 0) + 1
    ctx['map_tiles'] = tiles
    ctx['mmaps'] = {int(n[:4]) for n in listing('mmaps') if n.endswith('.mmap') and n[:4].isdigit()}
    ctx['vmaps'] = {int(n) for n in listing('vmaps') if n.isdigit()}
    # Areas a map of the game draws: a zone players walk in. "Crafting" is an area too, but only a heading quests are
    # sorted under, and it has no graveyard to ask for.
    ctx['mapped_zones'] = {r['AreaID'] for r in srv('UiMapAssignment') if r['AreaID']}
    world_map = os.path.join(DATA, 'world-map.json')
    try:
        ctx['ui_maps'] = json.load(open(world_map, encoding='utf-8'))['maps']
    except (OSError, ValueError, KeyError):
        # no such file (nothing writes one any more): the zones' rectangles are in the game's own table
        ctx['ui_maps'] = zone_rectangles(srv('UiMapAssignment'))
    return ctx
