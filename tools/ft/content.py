"""Official content of one client build, read from its DB2 snapshot, and build-to-build diffs."""
import hashlib
import json
import os
import re

from . import db2, hotfixes
from .config import BUILDS, CONFIG, SCHEMA

# Tables compared build after build (the changelog).
DIFF_TABLES = ['ItemSparse', 'Item', 'ItemEffect', 'ItemXItemEffect', 'SpellName', 'Spell', 'SpellMisc', 'SpellLevels', 'SpellEffect',
               'SkillLine', 'SkillLineAbility', 'Talent', 'TalentTab', 'ChrClasses', 'QuestV2', 'Map', 'MapDifficulty',
               'DungeonEncounter', 'AreaTable', 'Mount', 'Toy', 'BattlePetSpecies', 'Achievement', 'TaxiNodes', 'Creature']
# Extra tables of the latest build used by the tooltips.
TOOLTIP_TABLES = ['ItemSubClass', 'ItemSet', 'ItemSetSpell', 'ItemNameDescription', 'RandPropPoints', 'ItemArmorQuality', 'ItemArmorTotal',
                  'ArmorLocation', 'ItemArmorShield', 'ItemDamageAmmo', 'ItemDamageOneHand', 'ItemDamageOneHandCaster', 'ItemDamageTwoHand',
                  'ItemDamageTwoHandCaster', 'SpellDuration', 'SpellRange', 'SpellCastTimes', 'SpellRadius', 'SpellCooldowns', 'SpellPower',
                  'SpellAuraOptions', 'SpellReagents', 'SpellTotems', 'SpellTargetRestrictions', 'ChrRaces', 'Faction']
# Extra tables of the latest build copied by the Forge into the hotfixes database.
FORGE_TABLES = ['ItemSearchName', 'ItemModifiedAppearance', 'ItemAppearance', 'SpellAuraRestrictions', 'SpellCastingRequirements',
                'SpellCategories', 'SpellClassOptions', 'SpellEquippedItems', 'SpellEmpower', 'SpellInterrupts', 'SpellLabel', 'SpellLearnSpell',
                'SpellReagentsCurrency', 'SpellScaling', 'SpellShapeshift', 'SpellXSpellVisual', 'SpellCategory', 'MountXDisplay',
                'CriteriaTree', 'Criteria']
# The talent trees: Classic 1.60 builds its talents from the trait system (C_ClassTalents), not from Talent/TalentTab.
# Copied by the checkout, so a tree Blizzard changes (a node's ranks, a definition's spell) reaches the server's
# hotfixes database like any other record.
TRAIT_TABLES = ['TraitTree', 'TraitNode', 'TraitNodeEntry', 'TraitDefinition', 'TraitDefinitionEffectPoints', 'TraitEdge',
                'TraitNodeXTraitNodeEntry', 'TraitNodeGroup', 'TraitNodeGroupXTraitNode', 'TraitNodeGroupXTraitCond',
                'TraitNodeGroupXTraitCost', 'TraitNodeXTraitCond', 'TraitNodeXTraitCost', 'TraitNodeEntryXTraitCond',
                'TraitNodeEntryXTraitCost', 'TraitCond', 'TraitCondAccountElement', 'TraitCost', 'TraitCurrency',
                'TraitCurrencySource', 'TraitSubTree', 'TraitSystem', 'TraitTreeLoadout', 'TraitTreeLoadoutEntry',
                'TraitTreeXTraitCost', 'TraitTreeXTraitCurrency',
                # a definition's value per rank is a curve (TraitDefinitionEffectPoints.CurveID): a new rank value is a new curve
                'Curve', 'CurvePoint']
# Extra tables of the latest build used by the locator to turn map percentages into world positions.
MAP_TABLES = ['UiMap', 'UiMapAssignment', 'UiMapGroupMember']
# The flight paths between nodes: a node no path reaches is a point nobody flies to (ft.output.unused_taxi).
FLIGHT_TABLES = ['TaxiPath']
TABLES = DIFF_TABLES + TOOLTIP_TABLES + FORGE_TABLES + MAP_TABLES + TRAIT_TABLES + FLIGHT_TABLES

PROFESSION_CATEGORIES = {9, 11}       # SkillLine.CategoryID: secondary, primary professions
CLASS_CATEGORY, RACIAL_CATEGORY = 7, 12
# The spell categories (a spell's 'sub') players learn or use themselves; every other spell is internal: what an item
# or a creature casts, a trigger, a leftover.
PLAYER_SPELLS = ('class', 'profession', 'racial', 'talent', 'mount', 'pet', 'rune', 'petability')
SCRIPT_EFFECTS, SCRIPT_AURAS = {3, 77}, {4, 226}
SPELL_ATTR0_PASSIVE = 0x40
EFFECT_CREATE_ITEM, EFFECT_LEARN_SPELL = 24, 36
# Blizzard's "do not translate" mark on a name that is not for players ("Test Profession [DNT]")
DO_NOT_TRANSLATE = re.compile(r'\[DNT\]|\(DNT\)|\bDNT\b')


# The table whose row is the resource itself: a resource whose row there exists by hotfix alone is in no build's tables.
OWN_TABLE = {'item': 'ItemSparse', 'spell': 'SpellName', 'quest': 'QuestV2', 'achievement': 'Achievement', 'mount': 'Mount', 'toy': 'Toy',
             'pet': 'BattlePetSpecies', 'taxi': 'TaxiNodes', 'dungeon': 'Map', 'boss': 'DungeonEncounter', 'zone': 'AreaTable', 'talent': 'Talent'}


def hotfix_only(folder):
    """{(kind, id)} of the resources of a snapshot that exist by hotfix alone (after official(folder) read it): thousands
    of WoW: Forever's items are in no client table and reach the client by hotfix. No build's tables say when such a
    resource appeared, so a comparison of two builds cannot call it "added"."""
    added = hotfixes.ADDED.get(folder, {})
    return {(kind, entity_id) for kind, name in OWN_TABLE.items() for entity_id in added.get(name, ())}


def builds():
    found = []
    for name in os.listdir(BUILDS) if os.path.isdir(BUILDS) else []:
        if name.isdigit() and any(os.path.isdir(os.path.join(BUILDS, name, locale)) for locale in ('frFR', 'enUS')):
            meta = os.path.join(BUILDS, name, 'build.json')
            info = {}
            if os.path.isfile(meta):
                with open(meta, encoding='utf-8-sig') as handle:
                    info = json.load(handle)
            found.append({'build': int(name), 'version': info.get('version', f'1.60.1.{name}'), 'date': info.get('date'),
                          'note': info.get('note', ''), 'source': info.get('source', ''), 'dir': os.path.join(BUILDS, name),
                          # an earlier build stored for the changelog holds the compared tables only (ft.client.history)
                          'partial': info.get('tables') == 'changelog',
                          # the original game, stored as the build before the first beta (ft.vanilla)
                          'baseline': info.get('baseline', '')})
    found.sort(key=lambda b: b['build'])
    # The original game counts only as [client] vanilla names it, and only before a build of the game (alone it is
    # nothing to compare): a folder left from another setting (or the setting switched off) is no part of the changelog.
    from . import vanilla
    try:
        choice = vanilla.setting()
    except ValueError:
        choice = None
    real = [b for b in found if not b['baseline']]
    return [b for b in found if not b['baseline'] or (choice and real and b['build'] == choice[2] and b['build'] < real[0]['build'])]


_cache = {}


def table(folder, name, locale='frFR'):
    """Rows of a snapshot table in a locale, or in the other one when the build only has one; [] when absent."""
    if not CONFIG.french():
        locale = 'enUS'  # English only: the frFR tables of a snapshot are never read
    key = (folder, name, locale)
    if key not in _cache:
        path = os.path.join(folder, locale, name + '.db2')
        if not os.path.isfile(path):
            path = os.path.join(folder, 'enUS' if locale == 'frFR' else 'frFR', name + '.db2')
        if os.path.isfile(path):
            source = db2.Table(path, name)
            rows = list(source)
            # Blizzard's hotfixes over the build as it shipped (ft.hotfixes; the public cache is the enUS one)
            _cache[key] = hotfixes.overlay(folder, source, rows) if os.path.basename(os.path.dirname(path)) == 'enUS' else rows
        else:
            _cache[key] = []
    return _cache[key]


def db2_path(folder, name):
    for locale in ('frFR', 'enUS') if CONFIG.french() else ('enUS', 'frFR'):
        path = os.path.join(folder, locale, name + '.db2')
        if os.path.isfile(path):
            return path
    return os.path.join(folder, 'frFR', name + '.db2')


def table_hash(folder, name):
    path = db2_path(folder, name)
    return db2.Table(path, name).table_hash if os.path.isfile(path) else 0


def official(folder, read=None):
    """{type: {id: entity}} with a stable 'facts' dict used for diffs. read: a table's name -> its rows, for content
    that is not stored as the client's own files (ft.vanilla)."""
    t = read or (lambda name: table(folder, name))
    en = lambda name: {r['ID']: r for r in (read(name) if read else table(folder, name, 'enUS'))}
    out = {}

    spell_misc = [r for r in t('SpellMisc') if r['DifficultyID'] == 0]
    icons_spell = {r['SpellID']: r['SpellIconFileDataID'] for r in spell_misc}
    passive = {r['SpellID'] for r in spell_misc if (r.get('Attributes1') or 0) & SPELL_ATTR0_PASSIVE}
    spell_names = {r['ID']: r['Name'] for r in t('SpellName')}
    spell_names_en = {i: r['Name'] for i, r in en('SpellName').items()}
    spell_text = {r['ID']: r for r in t('Spell')}
    spell_levels = {r['SpellID']: r for r in t('SpellLevels') if r['DifficultyID'] == 0}
    effects = {}
    for r in t('SpellEffect'):
        if r['DifficultyID'] == 0:
            effects.setdefault(r['SpellID'], []).append(r)

    # ---- items
    items_base = {r['ID']: r for r in t('Item')}
    names_en = {i: r['Display'] for i, r in en('ItemSparse').items()}
    # the line under an item's name (a Craftsman's Writ's tier: Journeyman, Expert, Artisan), in English; kept beside
    # the facts, not in them, so that no build's changes list it
    try:
        name_desc_en = {i: r['Description'] for i, r in en('ItemNameDescription').items()}
    except (KeyError, OSError, ValueError):
        name_desc_en = {}
    items = {}
    for r in t('ItemSparse'):
        base = items_base.get(r['ID'], {})
        stats = [(r[f'StatModifierBonusStat{i}'], r[f'StatPercentEditor{i}']) for i in range(1, 11) if r[f'StatModifierBonusStat{i}'] not in (-1, 0) or r[f'StatPercentEditor{i}']]
        items[r['ID']] = {'name': r['Display'], 'name_en': names_en.get(r['ID'], ''), 'icon': base.get('IconFileDataID', 0),
                          'quality': r['OverallQualityID'], 'level': r['ItemLevel'], 'req': r['RequiredLevel'],
                          'sub': f"{base.get('ClassID', -1)}:{base.get('SubclassID', -1)}", 'slot': r['InventoryType'],
                          'facts': {'name': r['Display'], 'quality': r['OverallQualityID'], 'ilvl': r['ItemLevel'], 'req': r['RequiredLevel'],
                                    'slot': r['InventoryType'], 'bonding': r['Bonding'], 'set': r['ItemSet'], 'stats': stats,
                                    'sell': r['SellPrice'], 'buy': r['BuyPrice'], 'classes': r['AllowableClass'], 'desc': r['Description'],
                                    'startquest': r['StartQuestID'], 'skill': [r['RequiredSkill'], r['RequiredSkillRank']]}}
        if r['StartQuestID'] and name_desc_en.get(r['ItemNameDescriptionID']):
            items[r['ID']]['namedesc_en'] = name_desc_en[r['ItemNameDescriptionID']]
    out['item'] = items

    # ---- skill lines & abilities (class spells, professions, recipes)
    skill_lines = {r['ID']: r for r in t('SkillLine')}
    skill_lines_en = en('SkillLine')
    abilities = t('SkillLineAbility')
    class_names = {r['ID']: r['Name'] for r in t('ChrClasses')}
    spell_category = {}
    recipes = {}
    creates = {}
    for spell_id, rows in effects.items():
        for e in rows:
            if e['Effect'] == EFFECT_CREATE_ITEM and e['EffectItemType']:
                creates[spell_id] = e['EffectItemType']
    for a in abilities:
        line = skill_lines.get(a['SkillLine'], {})
        category = line.get('CategoryID')
        line_en = skill_lines_en.get(a['SkillLine'], {}).get('DisplayName', '')
        if DO_NOT_TRANSLATE.search(line_en or line.get('DisplayName', '') or ''):
            continue   # a skill line Blizzard marks as not for players ("Test Profession [DNT]"): its spells are no spellbook line
        if line_en == 'Beast Training' or line_en.startswith('Pet -'):
            spell_category.setdefault(a['Spell'], 'petability')  # hunter pet abilities: learned by taming and pet training
        elif category == CLASS_CATEGORY:
            spell_category.setdefault(a['Spell'], 'class')
        elif category == RACIAL_CATEGORY:
            spell_category.setdefault(a['Spell'], 'racial')
        elif category in PROFESSION_CATEGORIES:
            spell_category.setdefault(a['Spell'], 'profession')
            recipes[a['Spell']] = {'name': spell_names.get(a['Spell'], f"#{a['Spell']}"), 'name_en': spell_names_en.get(a['Spell'], ''),
                                   'icon': icons_spell.get(a['Spell'], 0), 'sub': line.get('DisplayName', ''), 'level': a['MinSkillLineRank'],
                                   'auto': a['AcquireMethod'] in (1, 2), 'spell': a['Spell'], 'creates': creates.get(a['Spell'], 0),
                                   'facts': {'skill': a['SkillLine'], 'rank': a['MinSkillLineRank'], 'acquire': a['AcquireMethod'],
                                             'trivial': [a['TrivialSkillLineRankLow'], a['TrivialSkillLineRankHigh']]}}
    out['recipe'] = recipes

    # ---- talents
    tabs = {r['ID']: r for r in t('TalentTab')}
    talents = {}
    for r in t('Talent'):
        ranks = [r[f'SpellRank{i}'] for i in range(1, 10) if r[f'SpellRank{i}']]
        for spell in ranks:
            spell_category[spell] = 'talent'
        first = ranks[0] if ranks else r['SpellID']
        tab = tabs.get(r['TabID'], {})
        class_id = next((c for c in class_names if tab.get('ClassMask', 0) & (1 << (c - 1))), r['ClassID'])
        talents[r['ID']] = {'name': spell_names.get(first, f"#{r['ID']}"), 'name_en': spell_names_en.get(first, ''), 'icon': icons_spell.get(first, 0),
                            'sub': f"{class_names.get(class_id, '?')} · {tab.get('Name', '?')}", 'level': r['TierID'] * 5 + 10, 'ranks': ranks,
                            'facts': {'tab': r['TabID'], 'tier': r['TierID'], 'column': r['ColumnIndex'], 'ranks': ranks,
                                      'prereq': [r['PrereqTalent1'], r['PrereqRank1']],
                                      'desc': [spell_text.get(s, {}).get('Description', '') for s in ranks[:1]]}}
    out['talent'] = talents

    # ---- mounts, toys, pets (collections)
    item_effects = {r['ID']: r for r in t('ItemEffect')}
    item_spells = {}
    teaches = {}  # spell -> items that teach it (official client view)
    learn = {}
    for spell_id, rows in effects.items():
        for e in rows:
            if e['Effect'] == EFFECT_LEARN_SPELL and e['EffectTriggerSpell']:
                learn.setdefault(spell_id, set()).add(e['EffectTriggerSpell'])
    for link in t('ItemXItemEffect'):
        effect = item_effects.get(link['ItemEffectID'])
        if effect:
            item_spells.setdefault(link['ItemID'], set()).add(effect['SpellID'])
            spell_category.setdefault(effect['SpellID'], 'item')
            for target in {effect['SpellID']} | learn.get(effect['SpellID'], set()):
                teaches.setdefault(target, set()).add(link['ItemID'])
    mounts = {}
    mounts_en = en('Mount')
    for r in t('Mount'):
        spell_category[r['SourceSpellID']] = 'mount'
        mounts[r['ID']] = {'name': r['Name'], 'name_en': mounts_en.get(r['ID'], {}).get('Name', ''), 'icon': icons_spell.get(r['SourceSpellID'], 0),
                           'sub': 'Monture', 'spell': r['SourceSpellID'], 'teach': sorted(teaches.get(r['SourceSpellID'], set())),
                           'source': r['SourceText'], 'source_en': mounts_en.get(r['ID'], {}).get('SourceText', ''),
                           'facts': {'name': r['Name'], 'spell': r['SourceSpellID'], 'source': r['SourceText']}}
    toys = {}
    toys_en = en('Toy')
    for r in t('Toy'):
        item = items.get(r['ItemID'], {})
        toys[r['ID']] = {'name': item.get('name', f"#{r['ItemID']}"), 'name_en': item.get('name_en', ''), 'icon': item.get('icon', 0), 'sub': 'Jouet',
                         'item': r['ItemID'], 'source': r['SourceText'], 'source_en': toys_en.get(r['ID'], {}).get('SourceText', ''),
                         'facts': {'item': r['ItemID'], 'source': r['SourceText']}}
    pets = {}
    pets_en = en('BattlePetSpecies')
    creatures = {r['ID']: r for r in t('Creature')}
    for r in t('BattlePetSpecies'):
        spell_category[r['SummonSpellID']] = 'pet'  # companion skill lines sit in the class category
        name = creatures.get(r['CreatureID'], {}).get('Name') or spell_names.get(r['SummonSpellID'], f"#{r['ID']}")
        pets[r['ID']] = {'name': name, 'name_en': spell_names_en.get(r['SummonSpellID'], ''), 'icon': r['IconFileDataID'], 'sub': 'Mascotte',
                         'spell': r['SummonSpellID'], 'creature': r['CreatureID'], 'teach': sorted(teaches.get(r['SummonSpellID'], set())),
                         'source': r['SourceText'], 'source_en': pets_en.get(r['ID'], {}).get('SourceText', ''),
                         'facts': {'creature': r['CreatureID'], 'spell': r['SummonSpellID'], 'source': r['SourceText']}}
    out['mount'], out['toy'], out['pet'] = mounts, toys, pets
    for recipe_id, recipe in recipes.items():
        if teaches.get(recipe_id):
            recipe['teach'] = sorted(teaches[recipe_id])

    # ---- spells (all; player-relevant ones are flagged by category)
    spells = {}
    for spell_id, name in spell_names.items():
        text = spell_text.get(spell_id, {})
        level = spell_levels.get(spell_id, {})
        effect_facts = sorted([(e['EffectIndex'], e['Effect'], e['EffectAura'], e['EffectBasePoints'], e['EffectTriggerSpell']) for e in effects.get(spell_id, [])])
        category = spell_category.get(spell_id, 'other')
        if category == 'class' and spell_names_en.get(spell_id, '').startswith('Engrave'):
            category = 'rune'  # rune engravings sit in class skill lines but are learned from runes
        spells[spell_id] = {'name': name, 'name_en': spell_names_en.get(spell_id, ''), 'icon': icons_spell.get(spell_id, 0),
                            'sub': category, 'level': level.get('BaseLevel', 0) or level.get('SpellLevel', 0),
                            'scriptable': any(e['Effect'] in SCRIPT_EFFECTS or e['EffectAura'] in SCRIPT_AURAS for e in effects.get(spell_id, [])),
                            'passive': spell_id in passive,
                            'teach': sorted(teaches.get(spell_id, ())) if category in ('class', 'profession', 'rune') else [],
                            'facts': {'name': name, 'rank': text.get('NameSubtext', ''), 'desc': text.get('Description', ''),
                                      'aura': text.get('AuraDescription', ''), 'effects': effect_facts, 'level': level.get('BaseLevel', 0)}}
    out['spell'] = spells

    # ---- quests (ids only in the client; names come from the server or Wowhead)
    out['quest'] = {r['ID']: {'facts': {}} for r in t('QuestV2')}

    # ---- instances, bosses, zones
    maps = {r['ID']: r for r in t('Map')}
    maps_en = en('Map')
    difficulty_players = {}
    for r in t('MapDifficulty'):
        difficulty_players[r['MapID']] = max(difficulty_players.get(r['MapID'], 0), r['MaxPlayers'])
    kinds = {1: 'Donjon', 2: 'Raid', 3: 'Champ de bataille', 4: 'Arène'}
    dungeons = {}
    for map_id, r in maps.items():
        if r['InstanceType'] in kinds:
            dungeons[map_id] = {'name': r['MapName'], 'name_en': maps_en.get(map_id, {}).get('MapName', ''), 'sub': kinds[r['InstanceType']],
                                'level': difficulty_players.get(map_id, r['MaxPlayers']), 'kind': r['InstanceType'], 'directory': r['Directory'],
                                'parent': r['CorpseMapID'] if r['CorpseMapID'] >= 0 else max(r['ParentMapID'], 0),
                                'facts': {'name': r['MapName'], 'type': r['InstanceType'], 'players': difficulty_players.get(map_id, r['MaxPlayers']),
                                          'area': r['AreaTableID'], 'parent': r['ParentMapID']}}
    out['dungeon'] = dungeons
    encounters_en = en('DungeonEncounter')
    bosses = {}
    for r in t('DungeonEncounter'):
        bosses[r['ID']] = {'name': r['Name'], 'name_en': encounters_en.get(r['ID'], {}).get('Name', ''), 'map': r['MapID'],
                           'sub': maps.get(r['MapID'], {}).get('MapName', f"#{r['MapID']}"), 'level': r['OrderIndex'],
                           'facts': {'name': r['Name'], 'map': r['MapID'], 'order': r['OrderIndex'], 'difficulty': r['DifficultyID']}}
    out['boss'] = bosses
    areas_en = en('AreaTable')
    zones = {}
    for r in t('AreaTable'):
        continent = maps.get(r['ContinentID'], {})
        if r['ParentAreaID'] == 0 and continent and continent.get('InstanceType') == 0 and r['AreaName']:
            zones[r['ID']] = {'name': r['AreaName'], 'name_en': areas_en.get(r['ID'], {}).get('AreaName', ''), 'map': r['ContinentID'],
                              'sub': continent.get('MapName', ''), 'level': r['ExplorationLevel'],
                              'facts': {'name': r['AreaName'], 'map': r['ContinentID'], 'flags': r['Flags1'], 'faction': r['FactionGroupMask']}}
    out['zone'] = zones

    # ---- achievements, flight points
    achievements_en = en('Achievement')
    out['achievement'] = {r['ID']: {'name': r['Title'], 'name_en': achievements_en.get(r['ID'], {}).get('Title', ''), 'icon': r['IconFileID'],
                                    'sub': f"{r['Points']} pts", 'level': r['Points'], 'reward': r['Reward'], 'reward_item': r['RewardItemID'],
                                    'facts': {'title': r['Title'], 'desc': r['Description'], 'points': r['Points'], 'reward': r['Reward'],
                                              'category': r['Category'], 'item': r['RewardItemID']}} for r in t('Achievement')}
    taxi_en = en('TaxiNodes')
    # how many flight paths start or end at each node; None when the snapshot has no TaxiPath (read from 2026-11-27 on)
    taxi_paths = t('TaxiPath')
    path_count = {}
    for r in taxi_paths:
        for end in (r['FromTaxiNode'], r['ToTaxiNode']):
            path_count[end] = path_count.get(end, 0) + 1
    out['taxi'] = {r['ID']: {'name': r['Name'], 'name_en': taxi_en.get(r['ID'], {}).get('Name', ''), 'map': r['ContinentID'],
                             'sub': maps.get(r['ContinentID'], {}).get('MapName', ''), 'pos': [round(r['PosX'], 1), round(r['PosY'], 1), round(r['PosZ'], 1)],
                             # a node without a bit in the character's list of known flight points is never learned:
                             # no flight master opens it (the druids' flights out of Nighthaven, quest flights)
                             'learned': bool(r.get('CharacterBitNumber', 1)),
                             # kept out of 'facts' so the changelog does not see every node change the day it is read
                             'paths': path_count.get(r['ID'], 0) if taxi_paths else None,
                             'facts': {'name': r['Name'], 'map': r['ContinentID'], 'pos': [round(r['PosX']), round(r['PosY'])], 'flags': r['Flags']}}
                   for r in t('TaxiNodes') if r['Name']}

    out['_meta'] = {'item_spells': item_spells, 'hidden': {}}
    for name in ('ItemSparse', 'SpellName', 'QuestV2', 'Map', 'Achievement', 'Mount'):
        path = db2_path(folder, name)
        if os.path.isfile(path):
            tb = db2.Table(path, name)
            list(tb)
            out['_meta']['hidden'][name] = tb.hidden_records
    return out


def fingerprint(facts):
    return hashlib.sha1(json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def diff_builds(previous, current):
    """[(type, id, kind, changed_fields)]"""
    changes = []
    for kind in current:
        if kind.startswith('_'):
            continue
        old, new = previous.get(kind, {}), current[kind]
        for entity_id in new.keys() - old.keys():
            changes.append((kind, entity_id, 'added', {}))
        for entity_id in old.keys() - new.keys():
            changes.append((kind, entity_id, 'removed', {}))
        for entity_id in new.keys() & old.keys():
            before, after = old[entity_id]['facts'], new[entity_id]['facts']
            if fingerprint(before) != fingerprint(after):
                fields = {key: [before.get(key), after.get(key)] for key in set(before) | set(after) if before.get(key) != after.get(key)}
                changes.append((kind, entity_id, 'modified', fields))
    return changes


# ---------------------------------------------------------------- a build's changelog, kept once it is worked out
# Reading a build's tables takes the better part of a minute, and with the changelog going back to the first beta
# there are thirty of them. Two stored builds never change, so neither does what one changed against the other: it is
# kept in the newer build's folder and read back while both are as they were.
KEPT = 'changelog.json'
_mark = []


def code_mark():
    """What the kept changelogs depend on besides the builds: how a table is read and what is compared."""
    if not _mark:
        seen = hashlib.sha1()
        here = os.path.dirname(os.path.abspath(__file__))
        for path in [os.path.join(here, name) for name in ('content.py', 'db2.py', 'hotfixes.py')] + [SCHEMA]:
            try:
                with open(path, 'rb') as handle:
                    seen.update(handle.read())
            except OSError:
                seen.update(path.encode())
        _mark.append(seen.hexdigest()[:16])
    return _mark[0]


_hashed = {}


def state(build, with_hotfixes=True):
    """What a build's compared tables hold and which hotfixes stand over them. Two builds in the same state have the
    same official content: Blizzard often ships a build that changes the program alone. with_hotfixes False: the
    tables alone (a step from one kept hotfix cache to the next names its two caches itself)."""
    seen = hashlib.sha1()
    for locale in ('enUS', 'frFR'):
        for name in DIFF_TABLES:
            # .csv: the original game's tables, kept as they were downloaded (ft.vanilla)
            for path in [os.path.join(build['dir'], locale, name + kind) for kind in (('.csv',) if build.get('baseline') else ('.db2',))]:
                try:
                    stat = os.stat(path)
                    key = (path, stat.st_size, stat.st_mtime_ns)
                    if key not in _hashed:
                        with open(path, 'rb') as handle:
                            _hashed[key] = hashlib.sha1(handle.read()).hexdigest()
                    seen.update(f'{locale}/{name}:{_hashed[key]};'.encode())
                except OSError:
                    pass
    if not with_hotfixes:
        return seen.hexdigest()[:16]
    _found, origin = hotfixes.cached(build['dir'])
    over = hotfixes.source(build['dir'] if origin is None else os.path.join(os.path.dirname(os.path.normpath(build['dir'])), str(origin)))
    try:
        stat = os.stat(over)
        key = (over, stat.st_size, stat.st_mtime_ns)
        if key not in _hashed:
            # the cache's own bytes: the newest cache and the same cache kept compressed are one state
            _hashed[key] = hashlib.sha256(hotfixes._read(over)).hexdigest()
        seen.update(f'hotfixes:{origin}:{_hashed[key]}'.encode())
    except (OSError, TypeError, EOFError, ValueError):
        pass
    return seen.hexdigest()[:16]


def signature(build):
    """A build as it stands, for what was kept of it: its number, its state, and whether French is read."""
    return f"{build['build']}:{int(CONFIG.french())}:{state(build)}"


def kept(build, before):
    """What digest() kept for this build against the one before it; None when there is nothing, or when a build, its
    hotfixes or the way they are read is no longer what it was."""
    return kept_as(build, [code_mark(), signature(build), signature(before) if before else ''])


def kept_as(build, mark, path=None):
    """What was kept in a build's folder under this mark; None when there is nothing, or it was kept under another."""
    try:
        with open(path or os.path.join(build['dir'], KEPT), encoding='utf-8') as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and found.get('mark') == mark else None


def digest(build, current, before=None, previous=None):
    """What the analysis needs of a build besides the newest one's content: how many resources of each kind, what
    changed against the build before ([kind, id, change, fields, name], every change: also the resources that exist by
    hotfix alone, named in 'alone'), and for the first build the ids of everything it has. current, previous: the
    official() of the build and of the one before. Kept in the build's folder (kept)."""
    return keep(build, before, work_out(build, current, before, previous))


def work_out(build, current, before=None, previous=None, alone=True):
    """What digest() keeps, not kept yet. alone: name the resources that exist by hotfix alone (a step from one hotfix
    cache to the next names none: what a later cache adds, it adds that day)."""
    out = {'counts': {kind: len(entities) for kind, entities in current.items() if not kind.startswith('_')}}
    if before is None:
        out['ids'] = {kind: sorted(entities) for kind, entities in current.items() if not kind.startswith('_')}
        changed = [(kind, entity_id) for kind, ids in out['ids'].items() for entity_id in ids]
    else:
        alone = hotfix_only(build['dir']) if alone else set()
        out['changes'] = [[kind, entity_id, change, fields, (current.get(kind, {}).get(entity_id) or previous.get(kind, {}).get(entity_id) or {}).get('name', '')]
                          for kind, entity_id, change, fields in diff_builds(previous, current)]
        out['alone'] = sorted([kind, entity_id] for kind, entity_id, change, _fields, _name in out['changes'] if change == 'added' and (kind, entity_id) in alone)
        changed = [(kind, entity_id) for kind, entity_id, change, _fields, _name in out['changes'] if change != 'removed']
    # what each resource this build brought or changed looks like afterwards, as a fingerprint: the replay (replay())
    # follows them from the first build to the newest
    out['prints'] = {}
    for kind, entity_id in changed:
        out['prints'].setdefault(kind, {})[str(entity_id)] = fingerprint(current[kind][entity_id].get('facts'))
    return out


def keep(build, before, out):
    """Writes what was worked out of a build into its folder, and returns it as it will be read back."""
    return keep_as(build, [code_mark(), signature(build), signature(before) if before else ''], out)


def keep_as(build, mark, out, path=None):
    """Writes something worked out of a build into its folder under a mark, and returns it as it will be read back.
    path: another file than the build's changelog.json (a step from one hotfix cache to the next)."""
    out = {'mark': mark, **out}
    try:
        path = path or os.path.join(build['dir'], KEPT)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(f'{path}.{os.getpid()}.tmp', 'w', encoding='utf-8') as handle:
            json.dump(out, handle, ensure_ascii=False, default=str)
        os.replace(f'{path}.{os.getpid()}.tmp', path)
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)   # the same shapes whether it was kept or just made
    except OSError:
        return json.loads(json.dumps(out, ensure_ascii=False, default=str))   # a folder that cannot be written: worked out again next time


def forget(folder):
    """Drops the rows read from a build's tables: thirty builds do not fit in memory at once."""
    for key in [key for key in _cache if key[0] == folder]:
        del _cache[key]


def view(folder, entry):
    """Lets a kept hotfix cache stand over a build (None: the newest), forgetting the rows read under another."""
    before = hotfixes._pinned.get(folder)
    hotfixes.pin(folder, entry)
    if hotfixes._pinned.get(folder) != before:
        forget(folder)


def step_file(build, entry):
    """Where the step to a kept hotfix cache is kept: next to the cache, in the build's hotfix history."""
    return os.path.join(build['dir'], hotfixes.HISTORY, entry['file'].split('.')[0] + '.changelog.json')


def changelog(build_list, log=lambda text: None, read=None, own=None, origin=None, caches=None, show=None):
    """Every build against the one before it, oldest first.

    Returns (the newest build's official content, changes, first_seen, changed_in, by_hotfix, more): changes as
    (build, build before, kind, id, change, fields, name); first_seen and changed_in {(kind, id): build}; by_hotfix
    {kind: count} of the resources that exist by hotfix alone and were not called "added"; more: {'baseline': what is
    known of the original game's step or None, 'replay': replay(), 'minor': {(build, kind, id)} of the removals that
    are of no interest to players, 'builds': the builds the changelog is about (the list without an original game
    that could not be compared)}. Each build of the list gets its 'counts'.

    When the list starts with the original game (ft.vanilla), the first build of the game is compared with it
    (ft.vanilla.step) and everything the original game already had is "first seen" there.

    Blizzard's hotfixes: a build with more than one hotfix cache kept (ft.hotfixes.history) is compared with the build
    before as it stood with the first of them, and each later cache is a step of its own (dated the day it was
    downloaded): what it changed against the cache before. They are more['hotfixes'] ({'build', 'hotfix' (1, 2, ...),
    'version', 'date', 'records', 'counts'}) and more['hotfix_changes'] ((build, hotfix, kind, id, change, fields,
    name)); the analysis goes on with the newest cache.

    read: a build's folder -> its official(); own: a folder -> its snapshot has the hotfixes of its own build;
    origin: the step from the original game, as ft.vanilla.step; caches: a folder -> its kept hotfix caches, oldest
    first; show: (folder, cache or None) -> lets that cache stand over the build (all five for tests)."""
    read, own = read or official, own or hotfixes.has_own
    caches, show = caches or hotfixes.history, show or view
    chain = [b for b in build_list if not b.get('baseline')]     # a baseline is never read as a build of the game
    base = build_list[0] if chain and build_list[0].get('baseline') else None
    if not chain:
        raise ValueError('no build of the game is stored')
    changes, first_seen, changed_in, by_hotfix = [], {}, {}, {}
    loaded = {}      # build -> its official content: the newest build's, and the two being compared

    twin = {}        # build -> the earliest build before it in the same state: its content is that one's

    newest = {}      # build -> the sha of its newest hotfix cache kept (None: none kept)
    hotfix_steps, hotfix_changes = [], []

    def key(b, entry):
        return (b['build'], entry['sha'] if entry else newest.get(b['build']))

    def load_at(b, entry):
        """The official content of a build under one of its kept hotfix caches (None: the newest)."""
        at = key(b, entry)
        if at not in loaded:
            show(b['dir'], entry)
            log(f"official content of build {b['build']}" + (f" with the hotfixes of {entry['read']}" if entry else ''))
            loaded[at] = read(b['dir'])
        return loaded[at]

    def load(b):
        return load_at(twin.get(b['build'], b), None)
    quiet = None     # the first of the builds in a row, up to the one before, whose hotfixes were never stored
    read_back = same = 0
    steps = []       # (build, what was kept of it), oldest first: what the replay follows
    late = {}        # build -> {(kind, id)}: there by hotfix alone, known "since" the game's first build
    try:
        for index, b in enumerate(chain):
            before = chain[index - 1] if index else None
            kept_caches = caches(b['dir']) or []
            if base is not None and index == 0:
                # the game's first build is compared with the original game as it stands today (ft.vanilla.step reads it
                # with its newest hotfixes): its caches are no steps of their own
                kept_caches = kept_caches[-1:]
            newest[b['build']] = kept_caches[-1]['sha'] if kept_caches else None
            # with several hotfix caches kept, the build is compared as it stood with the first one; each later one is a
            # step of its own (below). The newest cache is never pinned: it is the build as the analysis reads it.
            first = kept_caches[0] if len(kept_caches) > 1 else None
            show(b['dir'], first)
            # what a build changed against the one before never changes once both are stored: it is kept
            found = kept(b, before)
            read_back += found is not None
            if before is not None and state(b) == state(before):
                # a build that changed the program alone: the same tables, byte for byte, under the same hotfixes
                if b is not chain[-1]:   # the newest build is always read from its own folder: the analysis works on it
                    twin[b['build']] = twin.get(before['build'], before)
                if found is None:
                    found = keep(b, before, {'counts': before['counts'], 'changes': [], 'alone': [], 'prints': {}})
                    same += 1
            if found is None:
                found = digest(b, load_at(b, first) if first else load(b), before, load(before) if before else None)
                show(b['dir'], first)
            b['counts'] = found['counts']
            steps.append((b['build'], found))
            for kind, ids in (found.get('ids') or {}).items():
                for entity_id in ids:
                    first_seen.setdefault((kind, entity_id), b['build'])
            if before is not None:
                # A resource that exists by hotfix alone is in no build's tables. Compared with a build whose hotfixes were
                # never stored, it would read "added in this build", five thousand items at once, although nothing says
                # when it appeared: it is not listed as a change, and it counts as known since the first of the builds in
                # a row without their hotfixes (with the beta's builds stored: since the first of them).
                quiet = (quiet or before['build']) if not own(before['dir']) else None
                alone = {(kind, entity_id) for kind, entity_id in found.get('alone') or []} if quiet else set()
                for kind, entity_id, change, fields, name in found.get('changes') or []:
                    if change == 'added':
                        first_seen.setdefault((kind, entity_id), b['build'])
                        if (kind, entity_id) in alone:
                            first_seen[(kind, entity_id)] = min(first_seen[(kind, entity_id)], quiet)
                            by_hotfix[kind] = by_hotfix.get(kind, 0) + 1
                            if quiet == chain[0]['build']:
                                late.setdefault(b['build'], {})[(kind, entity_id)] = ((found.get('prints') or {}).get(kind) or {}).get(str(entity_id), '')
                            continue
                    changes.append((b['build'], before['build'], kind, entity_id, change, fields, name))
                    changed_in[(kind, entity_id)] = b['build']
            # each later hotfix cache: what it changed against the one before, kept next to it
            for number in range(1, len(kept_caches)):
                earlier, entry = kept_caches[number - 1], kept_caches[number]
                last = number == len(kept_caches) - 1
                # the build's tables and the two caches: nothing to read back but a few hashes
                mark = [code_mark(), f"{b['build']}:{int(CONFIG.french())}:{state(b, False)}", earlier['sha'], entry['sha']]
                path = step_file(b, entry)
                step = kept_as(b, mark, path)
                if step is None:
                    after = load_at(b, None if last else entry)
                    step = keep_as(b, mark, work_out(b, after, b, load_at(b, earlier), alone=False), path)
                    # two caches of a build at most are held: the next step starts from this one
                    for at in [at for at in loaded if at[0] == b['build'] and at != key(b, None if last else entry)]:
                        del loaded[at]
                    forget(b['dir'])
                steps.append((b['build'], step))   # the replay follows every step, one that changed nothing too
                if not step.get('changes') and not (entry.get('window') or {}).get('days'):
                    continue   # a new cache that changed nothing the tracker compares, on days nobody wrote about: no entry
                hotfix_steps.append({'build': b['build'], 'hotfix': number, 'version': b.get('version', ''), 'date': entry.get('read'),
                                     'records': entry.get('records', 0), 'counts': step['counts'], 'source': 'hotfix',
                                     # the days it covers, when ft.dating worked them out from the builds
                                     'window': entry.get('window')})
                for kind, entity_id, change, fields, name in step.get('changes') or []:
                    if change == 'added':
                        first_seen.setdefault((kind, entity_id), b['build'])
                    hotfix_changes.append((b['build'], number, kind, entity_id, change, fields, name))
                    changed_in[(kind, entity_id)] = b['build']
            show(b['dir'], None)
            held = key(twin.get(b['build'], b), None)
            for at in [at for at in loaded if at != held]:
                forget(next(x['dir'] for x in chain if x['build'] == at[0]))
                del loaded[at]
    finally:
        for b in chain:   # a failure halfway leaves no build under an older cache
            show(b['dir'], None)
    content = load(chain[-1])
    if read_back:
        log(f'{read_back} of {len(chain)} builds: changelog read back as kept (the builds have not changed)')
    if same:
        log(f'{same} build(s) have the tables of the build before, byte for byte: no data change, not read')
    if hotfix_steps:
        log(f'{len(hotfix_steps)} hotfix update(s) after their build: ' + ', '.join(f"{h['build']} on {h['date']}" for h in hotfix_steps))
    more = {'baseline': None, 'replay': None, 'minor': set(), 'builds': chain, 'hotfixes': hotfix_steps, 'hotfix_changes': hotfix_changes}
    start = None
    if base is not None:
        # the game's first build against the original game. It comes last: only now is it known which resources are
        # there by hotfix alone "since the first build", and those are compared as their hotfix stands
        if origin is None:
            from . import vanilla
            origin = vanilla.step
        start = origin(base, chain, late, load, log)
        base['counts'] = start['counts']
        # what the step read of the first build is not needed any more (the newest build's is: the analysis works on it)
        held = key(twin.get(chain[-1]['build'], chain[-1]), None)
        for at in [at for at in loaded if at != held]:
            forget(next(x['dir'] for x in chain if x['build'] == at[0]))
            del loaded[at]
    if start is not None and not start.get('compared', True):
        # the two could not be compared (ft.vanilla.step says why in the log): the changelog starts at the first build
        start = None
    if start is not None:
        first = chain[0]['build']
        # "first seen in the original game": what it had and the game's first build has too (in its tables, or by a
        # hotfix alone). What the first build lacked and a later one brought is first seen in that later build.
        held = {(kind, entity_id) for kind, ids in (steps[0][1].get('ids') or {}).items() for entity_id in ids}
        held |= {(kind, entity_id) for kind, entity_id in start.get('alone') or []}
        old = {(kind, entity_id) for kind, ids in start['ids'].items() for entity_id in ids}
        for found_key in old & held & first_seen.keys():
            first_seen[found_key] = base['build']
        listed = [(first, base['build'], kind, entity_id, change, fields, name) for kind, entity_id, change, fields, name in start['changes']]
        for _build, _before, kind, entity_id, change, _fields, _name in listed:
            if change != 'removed':
                changed_in.setdefault((kind, entity_id), first)
        changes = listed + changes
        more['minor'] = {(first, kind, entity_id) for kind, entity_id in start.get('minor') or []}
        more['baseline'] = {'build': base['build'], 'version': base.get('version', ''), 'first': first, 'hidden': start.get('hidden') or {},
                            'alone': len(start.get('alone') or [])}
        more['builds'] = [base] + chain
    more['replay'] = replay((base['build'], start) if start else None, steps, content)
    return content, changes, first_seen, changed_in, by_hotfix, more


def replay(origin, steps, final):
    """The double check: start from the first thing stored, apply what every build after it is said to have added,
    changed and removed, and see whether that gives the newest build. It does when no step is missing and none says
    something else than the builds do.

    origin: (build, the original game's step as ft.vanilla.step kept it) or None; steps: [(build, what digest() kept)]
    oldest first; final: the newest build's official content. Returns {'from', 'to', 'steps', 'ok', 'kinds': {kind:
    {'start', 'added', 'alone', 'removed', 'end', 'now'}}, 'problems': [sentences, the first few], 'wrong': how many}.

    Ids are followed from the very start. From the game's first build on, each resource's content is followed too, as
    the fingerprint digest() kept of it: a resource no build says it changed must still be what the first build had."""
    have, tally, problems = {}, {}, []
    wrong = 0

    def problem(text):
        nonlocal wrong
        wrong += 1
        if len(problems) < 12:
            problems.append(text)

    def count(kind, what, n=1):
        tally.setdefault(kind, {'start': 0, 'added': 0, 'alone': 0, 'removed': 0})[what] += n
    if not steps:
        return None
    first_build, first = steps[0]
    known = set()   # there by hotfix alone and already in the original game: "added" later without being new
    if origin:
        start_build, start = origin
        for kind, ids in start['ids'].items():
            have[kind] = dict.fromkeys(ids)
            count(kind, 'start', len(ids))
        known = {(kind, entity_id) for kind, entity_id in start.get('alone') or []}
        for kind, entity_id, change, _fields, _name in start['changes']:
            there = have.setdefault(kind, {})
            if change == 'added':
                if entity_id in there:
                    problem(f'{kind} {entity_id}: build {first_build} adds it, the original game had it')
                there[entity_id] = None
                count(kind, 'added')
            elif change == 'removed':
                if there.pop(entity_id, 0) == 0:
                    problem(f'{kind} {entity_id}: build {first_build} removes it, the original game did not have it')
                count(kind, 'removed')
        for kind in set(have) | set(first.get('ids') or {}):
            reached = {entity_id for entity_id in have.get(kind, {}) if (kind, entity_id) not in known}
            there = set((first.get('ids') or {}).get(kind) or [])
            for entity_id in sorted(reached ^ there)[:3]:
                problem(f'{kind} {entity_id}: ' + (f'build {first_build} has it and the step from the original game does not give it' if entity_id in there
                                                 else f'the step from the original game gives it and build {first_build} does not have it'))
            wrong += max(0, len(reached ^ there) - 3)
            have[kind] = {**{entity_id: None for entity_id in have.get(kind, {}) if (kind, entity_id) in known}, **dict.fromkeys(there)}
    else:
        start_build = first_build
        for kind, ids in (first.get('ids') or {}).items():
            have[kind] = dict.fromkeys(ids)
            count(kind, 'start', len(ids))
    for kind, prints in (first.get('prints') or {}).items():
        for entity_id, mark in prints.items():
            if int(entity_id) in have.get(kind, {}):
                have[kind][int(entity_id)] = mark
    for build, found in steps[1:]:
        alone = {(kind, entity_id) for kind, entity_id in found.get('alone') or []}
        prints = found.get('prints') or {}
        for kind, entity_id, change, _fields, _name in found.get('changes') or []:
            there = have.setdefault(kind, {})
            mark = (prints.get(kind) or {}).get(str(entity_id))
            if change == 'added':
                if (kind, entity_id) in known and entity_id in there:
                    known.discard((kind, entity_id))        # the original game's, now with its hotfix: no addition
                else:
                    if entity_id in there:
                        problem(f'{kind} {entity_id}: build {build} adds it, the build before had it')
                    count(kind, 'alone' if (kind, entity_id) in alone else 'added')
                there[entity_id] = mark
            elif change == 'removed':
                if entity_id not in there:
                    problem(f'{kind} {entity_id}: build {build} removes it, the build before did not have it')
                there.pop(entity_id, None)
                count(kind, 'removed')
            else:
                if entity_id not in there:
                    problem(f'{kind} {entity_id}: build {build} changes it, the build before did not have it')
                there[entity_id] = mark
    kinds = {}
    for kind in sorted(set(have) | {kind for kind in final if not kind.startswith('_')}):
        now, reached = final.get(kind, {}), have.get(kind, {})
        for entity_id in sorted(set(now) ^ set(reached))[:3]:
            problem(f'{kind} {entity_id}: ' + ('the newest build has it and no build added it' if entity_id in now else 'no build removed it and the newest build does not have it'))
        wrong += max(0, len(set(now) ^ set(reached)) - 3)
        differ = [entity_id for entity_id in set(now) & set(reached) if reached[entity_id] is not None and reached[entity_id] != fingerprint(now[entity_id].get('facts'))]
        for entity_id in sorted(differ)[:3]:
            problem(f'{kind} {entity_id}: it is not what the builds\' changes add up to')
        wrong += max(0, len(differ) - 3)
        kinds[kind] = {**tally.get(kind, {'start': 0, 'added': 0, 'alone': 0, 'removed': 0}), 'end': len(reached), 'now': len(now)}
    return {'from': start_build, 'to': steps[-1][0], 'steps': len(steps) - (0 if origin else 1), 'ok': not wrong, 'kinds': kinds,
            'problems': problems, 'wrong': wrong}


def replay_lines(more):
    """What the changelog's double check found, as lines for the analysis log."""
    lines = []
    base, found = more.get('baseline'), more.get('replay')
    if base:
        hidden = sum(int(n) for n in (base.get('hidden') or {}).values())
        lines.append(f"the original game ({base['version']}) is the changelog's start: build {base['first']} is compared with it"
                     + (f"; {base['alone']} of its resources are in no table and compared as their hotfix stands" if base.get('alone') else '')
                     + (f"; {hidden} records of build {base['first']} are still encrypted" if hidden else ''))
    if found:
        start = 'the original game' if base and found['from'] == base['build'] else f"build {found['from']}"
        total = sum(kind['now'] for kind in found['kinds'].values())
        if found['ok']:
            lines.append(f"replay: {start} and the changes of {found['steps']} build(s) give build {found['to']} exactly ({total} resources)")
        else:
            lines.append(f"replay: {start} and the changes of {found['steps']} build(s) do NOT give build {found['to']}: {found['wrong']} resource(s) differ")
            lines += ['replay: ' + text for text in found['problems']]
    return lines
