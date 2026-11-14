"""Boss encounters: which of the client's DungeonEncounter rows are a boss of WoW: Forever, and whether the server
has it.

The client lists an old dungeon's bosses more than once: Season of Discovery turned Blackfathom Deeps, Gnomeregan and
the Sunken Temple into raids with their own encounter rows, and later versions added the same fights again under new
ids. Counted one by one they make a working dungeon look unfinished. An encounter is also not always a creature
standing in the instance: a script summons Mutanus, Gahz'rilla or Ramstein, an event has several creatures (The
Seven), and the client misspells a name now and then (Geilhast for Gelihast).

The surest link is the core's own: its instance scripts say which creature is which encounter
(tools/world/summoned.json, 'encounters'). Names are compared only where no script says it.
"""
import difflib
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


def words(name):
    """A name as whole words, a possessive dropped: "Sneed's Shredder" -> ['sneed', 'shredder']."""
    return [re.sub(r"'s$", '', w).replace("'", '') for w in re.findall(r"[a-z0-9']+", (name or '').lower())]


def titles(boss_id, boss):
    """The names a creature may carry to be this boss, as written."""
    found = [boss.get('name_en'), boss.get('name'), *ALIASES.get(boss_id, ())]
    return [name for i, name in enumerate(found) if name and normal(name) and name not in found[:i]]


def names(boss_id, boss):
    """The same, normalised."""
    return {normal(name) for name in titles(boss_id, boss)}


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


def same_letters(target, name):
    """The same letters in another order (the client's Geilhast is the server's Gelihast)."""
    return len(target) >= 6 and len(target) == len(name) and sorted(target) == sorted(name)


def close_name(title, name):
    """A creature's name against a boss name that is not the same: the boss's words inside the creature's (Sneed in
    Sneed's Shredder, never Hakkar in Hakkari Priest or Onyxia in Onyxian Warder), the same letters in another order,
    or a long name one or two letters off (Ras Frostwhisperer for Ras Frostwhisper)."""
    target, other = normal(title), normal(name)
    if not target or not other:
        return False
    if same_letters(target, other):
        return True
    wanted, got = words(title), words(name)
    if len(target) >= 5 and wanted and any(got[i:i + len(wanted)] == wanted for i in range(len(got) - len(wanted) + 1)):
        return True
    return min(len(target), len(other)) >= 10 and difflib.SequenceMatcher(None, target, other).ratio() >= 0.92


def same_name(target, name):
    """Kept for callers that hold normalised names only: the same, or the same letters in another order."""
    return bool(target and name) and (target == name or same_letters(target, name))


def find(boss_id, boss, spawned, templates=(), summoned=(), instance_scripted=False, bound=()):
    """(creature, how) for a boss, or (None, None).

    spawned: the creatures spawned on the boss's map [{'id', 'name', 'scripted'}].
    templates: creatures that are not spawned there [{'id', 'name', 'script'}] ('script': a C++ ScriptName).
    bound: the creature entries the core's instance script counts as this encounter.

    how:
      'spawned'   it stands in the instance: the creature the instance script names, else one of that exact name,
                  else one whose name is close (an exact name always wins: C'Thun before Eye of C'Thun).
      'summoned'  not spawned, and known to be brought in: the instance script names it as this encounter, or a
                  summon group, a SmartAI summon, a summoning spell or a C++ script summons it.
      'scripted'  not spawned and nothing is known to summon it, but it has a C++ script in an instance that has one
                  too. The instance script most likely places it; that is a guess the report says aloud.
    A template nothing brings in is no boss in the instance: that stays a gap.
    """
    bound = set(bound)
    for npc in spawned:
        if npc['id'] in bound:
            return npc, 'spawned'
    wanted = titles(boss_id, boss)
    exact = {normal(title) for title in wanted}
    for npc in spawned:
        if normal(npc['name']) in exact:
            return npc, 'spawned'
    for npc in spawned:
        if any(close_name(title, npc['name']) for title in wanted):
            return npc, 'spawned'
    for npc in templates:
        if npc['id'] in bound:
            return npc, 'summoned'
    guess = None
    for npc in templates:
        name = normal(npc['name'])
        if not any(target == name or same_letters(target, name) for target in exact):
            continue
        if npc['id'] in summoned:
            return npc, 'summoned'
        if guess is None and npc.get('script') and instance_scripted:
            guess = npc
    return (guess, 'scripted') if guess else (None, None)
