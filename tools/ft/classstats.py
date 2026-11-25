"""What every race and class combination of the server gets from its base stats, level by level, through the core's
Classic 1.60 formulas (wow-trinitycore-everlake src/server/game/Entities/Unit/StatSystem.cpp: OCTRegenHPPerSpirit,
OCTRegenMPPerSpirit, UpdateAttackPowerAndDamage), naked and unbuffed. A report: nothing is changed by it.

Why: the formulas are fitted to the vanilla races. A race whose stat offsets fall outside them (High Order Skyborne, -3
Spirit) can get nothing from one of them without any table being wrong: a level 4 Skyborne warrior regained no health out
of combat (2026-11-24). This lists where a formula gives nothing, or far less than the other races of the class.

Keep these formulas in step with the core: they are copies, not read from it."""

STATS = ('str', 'agi', 'sta', 'inte', 'spi')
CLASS_NAMES = {1: 'Warrior', 2: 'Paladin', 3: 'Hunter', 4: 'Rogue', 5: 'Priest', 6: 'Death Knight', 7: 'Shaman', 8: 'Mage', 9: 'Warlock',
               10: 'Monk', 11: 'Druid', 12: 'Demon Hunter', 13: 'Evoker'}
RACE_NAMES = {1: 'Human', 2: 'Orc', 3: 'Dwarf', 4: 'Night Elf', 5: 'Undead', 6: 'Tauren', 7: 'Gnome', 8: 'Troll', 9: 'Goblin', 10: 'Blood Elf',
              11: 'Draenei', 22: 'Worgen', 24: 'Pandaren', 25: 'Pandaren (Alliance)', 26: 'Pandaren (Horde)', 95: 'High Order Skyborne',
              96: 'Windshaper Skyborne'}
DWARF = 3
VANILLA_RACES = (1, 2, 3, 4, 5, 6, 7, 8)
MANA_CLASSES = {2, 3, 5, 7, 8, 9, 11}
MELEE_CLASSES = {1, 2, 3, 4, 7, 11}   # classes that fight with their weapon: melee attack power is theirs
CLASSIC_CLASSES = {1, 2, 3, 4, 5, 7, 8, 9, 11}   # the classes the Classic formulas know: the others (Death Knight, Monk...) are not made on Forever


def hp_regen(cls, spirit):
    """Health a 2 second tick out of combat from Spirit (ClassicOCTRegenHP), never below 0."""
    f = {11: (0.11, 1.0), 8: (0.11, 1.0), 3: (0.43, -5.5), 2: (0.25, 0.0), 5: (0.15, 1.4), 4: (0.84, -13.0), 7: (0.28, -3.6),
         9: (0.12, 1.5), 1: (1.26, -22.6)}.get(cls)
    return max(0.0, spirit * f[0] + f[1]) if f else 0.0


def hp_regen_floored(cls, spirit, dwarf_spirit):
    """hp_regen with the core's floor (core #144): never less than a Dwarf of the class and level gets from its base Spirit."""
    regen = hp_regen(cls, spirit)
    if dwarf_spirit and dwarf_spirit > 0:
        regen = max(regen, hp_regen(cls, dwarf_spirit))
    return regen


def mana_regen(cls, spirit):
    """Mana a second from Spirit (OCTRegenMPPerSpirit); 0 for a class without mana."""
    return 6.25 + spirit / 8.0 if cls in MANA_CLASSES else 0.0


def melee_ap(cls, level, s):
    """Base melee attack power (UpdateAttackPowerAndDamage, not ranged, caster form), never below 0."""
    if cls in (1, 2):
        v = level * 3 + s['str'] * 2 - 20
    elif cls in (3, 4):
        v = level * 2 + s['str'] + s['agi'] - 20
    elif cls == 7:
        v = level * 2 + s['str'] * 2 - 20
    elif cls == 11:
        v = s['str'] * 2 - 20
    else:
        v = s['str'] - 10
    return max(0, v)


def ranged_ap(cls, level, s):
    """Base ranged attack power, never below 0."""
    if cls == 3:
        v = level * 2 + s['agi'] * 2 - 10
    elif cls in (1, 4):
        v = level + s['agi'] - 10
    else:
        v = s['agi'] - 10
    return max(0, v)


def stats_at(class_levels, race_offsets, race, cls, level):
    """The naked base stats of a race and class at a level: the class's row plus the race's offsets; None without a row."""
    base = class_levels.get((cls, level))
    if base is None:
        return None
    off = race_offsets.get(race, {})
    return {k: base[k] + off.get(k, 0) for k in STATS}


def _runs(levels):
    """[3, 4, 5, 9] -> [(3, 5), (9, 9)]."""
    out = []
    for lv in sorted(levels):
        if out and lv == out[-1][1] + 1:
            out[-1] = (out[-1][0], lv)
        else:
            out.append((lv, lv))
    return out


def playable(combos, races):
    """The combinations players can make on Forever: a race the realm offers from the start (races: race_unlock_requirement
    rows at expansion 0; None = every race) and a class the Classic formulas know."""
    return {(r, c) for r, c in combos if c in CLASSIC_CLASSES and (races is None or r in races)}


def check(combos, class_levels, race_offsets, max_level=60, low_share=0.5):
    """Findings for every (race, class) in combos: [(race, class, issue, level_from, level_to, value, note), ...].

    class_levels: {(class, level): {'str', 'agi', 'sta', 'inte', 'spi'}}; race_offsets: {race: {stat: offset}}.
    Issues: 'stat' (a base stat at 0 or below), 'hp_regen' (no health out of combat: under 1 a tick), 'hp_regen_low' (under
    low_share of the lowest vanilla race of the class at that level), 'mana_regen', 'melee_ap' (0 for a weapon class),
    'ranged_ap' (0 for a hunter). Consecutive levels with the same issue are one finding."""
    found = {}
    for race, cls in sorted(combos):
        for level in range(1, max_level + 1):
            s = stats_at(class_levels, race_offsets, race, cls, level)
            if s is None:
                continue
            dwarf = stats_at(class_levels, race_offsets, DWARF, cls, level) if (DWARF, cls) in combos else None
            hp = hp_regen_floored(cls, s['spi'], dwarf['spi'] if dwarf else 0)
            vanilla = [hp_regen_floored(cls, v['spi'], dwarf['spi'] if dwarf else 0)
                       for v in (stats_at(class_levels, race_offsets, r, cls, level) for r in VANILLA_RACES if (r, cls) in combos) if v]
            issues = {}
            for k in STATS:
                if s[k] <= 0:
                    issues[f'stat:{k}'] = (s[k], f'{k} {s[k]}')
            if cls in CLASS_NAMES and hp_regen(cls, 1000) > 0:   # a class the formulas know
                if hp < 1:
                    issues['hp_regen'] = (round(hp, 2), f'{hp:.2f} health a tick out of combat (Spirit {s["spi"]})')
                elif vanilla and hp < low_share * min(vanilla):
                    issues['hp_regen_low'] = (round(hp, 2), f'{hp:.2f} health a tick, the vanilla races of the class get {min(vanilla):.2f} or more')
            if cls in MANA_CLASSES and mana_regen(cls, s['spi']) <= 0:
                issues['mana_regen'] = (mana_regen(cls, s['spi']), 'no mana regeneration')
            if cls in MELEE_CLASSES and melee_ap(cls, level, s) <= 0:
                issues['melee_ap'] = (0, f'no melee attack power (Strength {s["str"]}, Agility {s["agi"]})')
            if cls == 3 and ranged_ap(cls, level, s) <= 0:
                issues['ranged_ap'] = (0, f'no ranged attack power (Agility {s["agi"]})')
            for issue, (value, note) in issues.items():
                found.setdefault((race, cls, issue), []).append((level, value, note))
    out = []
    for (race, cls, issue), hits in sorted(found.items()):
        by_level = {lv: (v, n) for lv, v, n in hits}
        for lo, hi in _runs(by_level):
            value, note = by_level[lo]
            out.append((race, cls, issue.split(':')[0], lo, hi, value, note))
    return out


def label(race, cls):
    return f'{RACE_NAMES.get(race, f"race {race}")} {CLASS_NAMES.get(cls, f"class {cls}")}'
