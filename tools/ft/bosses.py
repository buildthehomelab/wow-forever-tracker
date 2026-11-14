"""Boss encounters: which of the client's DungeonEncounter rows are a boss of WoW: Forever, and whether the server
has it.

The client lists an old dungeon's bosses more than once: Season of Discovery turned Blackfathom Deeps, Gnomeregan and
the Sunken Temple into raids with their own encounter rows, and later versions added the same fights again under new
ids. Counted one by one they make a working dungeon look unfinished. An encounter is also not always a creature
standing in the instance: a script summons Mutanus, Gahz'rilla or Ramstein, an event has several creatures (The
Seven), and the client misspells a name now and then (Geilhast for Gelihast).
"""
import re

# DungeonEncounter.DifficultyID of Season of Discovery's raid versions of old dungeons (10 and 20 players).
SEASON_DIFFICULTIES = {198, 215}

# Encounters named after an event, not after a creature: the creatures that stand for them (any one is enough).
ALIASES = {
    230: ('High Justice Grimstone',),                               # Ring of Law
    243: ("Doom'rel",),                                             # The Seven
    2791: ('Watchman Doomgrip',),                                   # The Vault
    548: ('Baelog',),                                               # The Lost Dwarves
    478: ('Grand Crusader Dathrohan',),                             # Balnazzar: Dathrohan turns into him
    788: ("Gri'lek", "Hazza'rah", 'Renataki', 'Wushoolay'),         # Edge of Madness
    710: ('Princess Yauj', 'Vem', 'Lord Kri'),                      # Silithid Royalty
    715: ("Emperor Vek'lor", "Emperor Vek'nilash"),                 # Twin Emperors
    1121: ("Thane Korth'azz", 'Lady Blaumeux', 'Sir Zeliek', 'Highlord Mograine', 'Baron Rivendare'),  # The Four Horsemen
}


def normal(name):
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def names(boss_id, boss):
    """The normalised names a creature may carry to be this boss."""
    found = {normal(boss.get('name_en')), normal(boss.get('name'))} | {normal(alias) for alias in ALIASES.get(boss_id, ())}
    return found - {''}


def shadows(bosses):
    """{boss id: ('season', 0) | ('duplicate', the encounter kept)} for the rows that are no boss of their own: the
    Season of Discovery raid versions, and a fight the client lists again on the same map (the lowest id is kept)."""
    out, kept = {}, {}
    for boss_id in sorted(bosses):
        boss = bosses[boss_id]
        if int((boss.get('facts') or {}).get('difficulty') or 0) in SEASON_DIFFICULTIES:
            out[boss_id] = ('season', 0)
            continue
        key = (boss.get('map'), normal(boss.get('name_en') or boss.get('name')))
        if not key[1]:
            continue
        if key in kept:
            out[boss_id] = ('duplicate', kept[key])
        else:
            kept[key] = boss_id
    return out


def same_name(target, name):
    """A creature's name against a boss name: the same, one inside the other (Sneed in Sneed's Shredder), or the same
    letters in another order (the client's Geilhast is the server's Gelihast)."""
    if not target or not name:
        return False
    if target == name:
        return True
    if len(target) >= 5 and target in name:
        return True
    return len(target) >= 6 and len(target) == len(name) and sorted(target) == sorted(name)


def find(boss_id, boss, spawned, templates=(), summoned=(), instance_scripted=False):
    """(creature, how) for a boss, or (None, None).

    spawned: the creatures spawned on the boss's map [{'id', 'name', 'scripted'}]. how = 'spawned'.
    templates: creatures that are not spawned there [{'id', 'name', 'script'}] ('script': a C++ ScriptName).
    A template counts when something brings it in, how = 'summoned': a summon group, a SmartAI summon or a summoning
    spell names it (summoned), or it has a C++ script in an instance that has one too (the instance script places it).
    A template nothing is known to bring in is no boss in the instance: that stays a gap.
    """
    wanted = names(boss_id, boss)
    for npc in spawned:
        name = normal(npc['name'])
        if any(same_name(target, name) for target in wanted):
            return npc, 'spawned'
    for npc in templates:
        name = normal(npc['name'])
        if not any(target == name or (len(target) >= 6 and len(target) == len(name) and sorted(target) == sorted(name)) for target in wanted):
            continue
        if npc['id'] in summoned or (npc.get('script') and instance_scripted):
            return npc, 'summoned'
    return None, None
