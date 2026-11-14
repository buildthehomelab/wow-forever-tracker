"""Creatures and world objects that are in the game without a spawn row: something brings them in.

Two places know it. The world database: a SmartAI summon, a summon group, an event script. And the core's C++ scripts,
read once into tools/world/summoned.json (tools/make_summoned.py): `instance->SummonCreature(NPC_GANDLING, ...)` has
no trace in any table. The same file says which creature each instance script counts as which boss encounter.

A summoned creature is as present as a spawned one for what it drops, sells, starts and ends: Reginald Windsor walks
into Stormwind when his quest calls him, and spawning him for good would be the mistake.
"""
import json
import os

from . import sqlio

FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'world', 'summoned.json')

SMART_SUMMON_CREATURE = 12   # smart_scripts.action_type: action_param1 is the creature
SMART_SUMMON_GO = 50         # action_param1 is the world object
EVENT_SUMMON_CREATURE = 10   # event_scripts.command: datalong is the creature


def core(path=None):
    """{'creatures': {entry: script}, 'objects': {entry: script}, 'encounters': {encounter id: [creature entries]}}
    from the core's scripts; empty when the file is missing or unreadable (the analysis then knows the database's
    summons only)."""
    out = {'creatures': {}, 'objects': {}, 'encounters': {}, 'commit': ''}
    try:
        with open(path or FILE, encoding='utf-8') as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return out
    try:
        out['creatures'] = {int(k): str(v) for k, v in (raw.get('creatures') or {}).items()}
        out['objects'] = {int(k): str(v) for k, v in (raw.get('objects') or {}).items()}
        out['encounters'] = {int(k): [int(x) for x in v] for k, v in (raw.get('encounters') or {}).items()}
        out['commit'] = str(raw.get('commit') or '')
    except (AttributeError, TypeError, ValueError):
        return {'creatures': {}, 'objects': {}, 'encounters': {}, 'commit': ''}
    return out


def database():
    """(creature entries, world object entries) the world database summons."""
    ints = lambda sql: {int(x) for x in sqlio.column(sql) if x is not None and int(x) > 0}
    creatures = ints(f'SELECT action_param1 FROM smart_scripts WHERE action_type = {SMART_SUMMON_CREATURE}')
    objects = ints(f'SELECT action_param1 FROM smart_scripts WHERE action_type = {SMART_SUMMON_GO}')
    if sqlio.has_table('creature_summon_groups'):
        creatures |= ints('SELECT entry FROM creature_summon_groups')
    if sqlio.has_table('event_scripts'):
        creatures |= ints(f'SELECT datalong FROM event_scripts WHERE command = {EVENT_SUMMON_CREATURE}')
    return creatures, objects


def known(spell_summons=()):
    """(creatures, objects, core lists): everything known to be brought in, from the database, the core's scripts and
    the summoning spells the caller read from the server's DB2 files."""
    lists = core()
    creatures, objects = database()
    return creatures | set(lists['creatures']) | set(spell_summons), objects | set(lists['objects']), lists
