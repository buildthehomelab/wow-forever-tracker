"""Availability rules: one list of weighted checks per resource. Labels come from the check code
(translated by the website); details are given in English and French."""
import math

from . import bosses, corespells, reports
from .extras import normal as normal_name
from .output import named_internal
from .baseline import NEW_FROM
from .server import log


# Spell effects and auras that do nothing without code (a SpellScript or the core's C++): SPELL_EFFECT_DUMMY and
# SPELL_EFFECT_SCRIPT_EFFECT; SPELL_AURA_DUMMY and SPELL_AURA_PERIODIC_DUMMY; and a proc aura with no spell to trigger.
CODE_EFFECTS, CODE_AURAS = {3, 77}, {4, 226}
# Auras that act only when they proc (SPELL_AURA_PROC_TRIGGER_SPELL, _PROC_TRIGGER_DAMAGE, _PROC_TRIGGER_SPELL_WITH_VALUE):
# the core builds their proc from the client's flags (SpellAuraOptions.ProcTypeMask) or a spell_proc row, never otherwise.
PROC_AURAS = {42, 43, 231}
TRIGGER_AURAS = {42, 231}


def L(en, fr):
    return {'en': en, 'fr': fr}


def check(ok, code, detail=None, weight=1):
    return {'ok': bool(ok), 'code': code, 'detail': detail or L('', ''), 'w': weight}


def join(parts):
    """[L(...), ...] -> L(', '.join(en), ', '.join(fr))"""
    return L(', '.join(p['en'] for p in parts), ', '.join(p['fr'] for p in parts))


SOURCES = {
    'loot': L('Creature loot', 'Butin de PNJ'), 'object': L('Chest / world object', 'Coffre / objet du monde'),
    'pickpocket': L('Pickpocketing', 'Vol à la tire'), 'skinning': L('Skinning / gathering', 'Dépeçage / récolte'),
    'fishing': L('Fishing', 'Pêche'), 'mail': L('Mail', 'Courrier'), 'disenchant': L('Disenchanting', 'Désenchantement'),
    'prospecting': L('Prospecting', 'Prospection'), 'milling': L('Milling', 'Broyage'), 'questdrop': L('Quest loot', 'Butin de quête'),
    'vendor': L('Vendor', 'Marchand'), 'shop': L('Shop', 'Boutique'), 'blackmarket': L('Black Market', 'Marché noir'), 'container': L('Container content', 'Contenu d’un conteneur'),
    'quest': L('Quest reward', 'Récompense de quête'), 'craft': L('Crafting', 'Artisanat'),
    'questgive': L('Given when a quest is accepted', 'Donné à l’acceptation d’une quête'),
    'use': L('Made by using an item', 'Fait en utilisant un objet'),
    'talk': L('Given in a conversation', 'Donné lors d’une conversation'),
}


# The Eastern Plaguelands towers: the flight master is there only while a faction holds the tower (the world PvP
# script places it), so no spawn row is expected.
TOWER_TAXI = {84, 85, 86, 87}
QUEST_TYPE_AUTOCOMPLETE = 0   # quest_template.QuestType: handed in without being accepted, so no giver's text
# Quests the official game shows without one of its texts, checked by hand (2026-11-19): nothing to copy, so the
# missing text is no gap. Giver's text: Wowhead Forever's page opens on the progress or completion text (Dragonslayer's
# Helm and Shield, An Apple Treat, the paladin lessons, Research Access, An Unfortunate End, the Legacy Rewards).
# Turn-in text: neither Wowhead Forever nor VMaNGOS's newest row has one (The Black Box, Vimes's Report, Alterac
# Valley's Korrak and Defusing the Threat, To Serve Kum'isha).
NO_OFFICIAL_GIVER_TEXT = {78132, 78133, 91738, 94773, 94817, 94818, 97286, 98372, 96339, 96340, 96341, 96342}
NO_OFFICIAL_TURN_IN_TEXT = {708, 1288, 7181, 7202, 7367, 7368, 93685}
# Items the core's own C++ scripts hand over when a player casts one of these spells, checked by hand (2026-11-19): no
# data row links the spell to the item, so the analysis cannot see it. Create Healthstone (6201, 6202, 5699, 11729,
# 11730) is a script effect in the client; the core's warlock script (classic_talent_warl_create_healthstone) creates
# the plain healthstone or, with Improved Healthstone rank 1 or 2, its stronger copy.
SCRIPT_CREATES = {
    5512: {6201}, 19004: {6201}, 19005: {6201},       # Minor Healthstone
    5511: {6202}, 19006: {6202}, 19007: {6202},       # Lesser Healthstone
    5509: {5699}, 19008: {5699}, 19009: {5699},       # Healthstone
    5510: {11729}, 19010: {11729}, 19011: {11729},    # Greater Healthstone
    9421: {11730}, 19012: {11730}, 19013: {11730},    # Major Healthstone
}


def evaluate_all(content, ctx):
    log('evaluating availability')
    known = ctx['known']
    # In the world: spawned, or brought in by a script, a summon group or a spell (ft.summons). Trainers stay with
    # the spawned ones: nobody trains at a creature that is there for a minute.
    npc_placed, go_placed = ctx['spawned_npc'], ctx['spawned_go']
    npc_spawned, go_spawned = npc_placed | ctx.get('summoned_npc', set()), go_placed | ctx.get('summoned_go', set())
    kill_credit = ctx.get('kill_credit', {})

    trainer_npcs = {}
    for npc, trainer in ctx['trainers']:
        if npc in npc_placed:
            trainer_npcs.setdefault(trainer, set()).add(npc)
    ctx['trainer_npcs'] = trainer_npcs
    trained = {spell for trainer, spell in ctx['trainer_spells'] if trainer in trainer_npcs}
    trained_any = {spell for _, spell in ctx['trainer_spells']}

    # ---- item sources as a fixed point (loot references, containers, quest rewards, crafts)
    references = {}
    for entry, kind, item, ref in ctx['loot']['reference']:
        references.setdefault(entry, []).append((kind, item, ref))

    def expand(rows):
        out, stack, seen = set(), list(rows), set()
        while stack:
            kind, item, ref = stack.pop()
            if ref and ref not in seen:
                seen.add(ref)
                stack.extend(references.get(ref, []))
            elif kind == 0 and item:
                out.add(item)
        return out

    def table_items(name, entries=None):
        grouped = {}
        for entry, kind, item, ref in ctx['loot'][name]:
            if entries is None or entry in entries:
                grouped.setdefault(entry, []).append((kind, item, ref))
        return {entry: expand(rows) for entry, rows in grouped.items()}

    npc_loot_ids, pick_ids, skin_ids = set(), set(), set()
    for npc, loot_id, pick, skin in ctx['npc_loot']:
        if npc in npc_spawned:
            loot_id and npc_loot_ids.add(loot_id)
            pick and pick_ids.add(pick)
            skin and skin_ids.add(skin)
    go_loot_ids = {data for entry, _type, data in ctx['go_loot'] if entry in go_spawned and data}
    sources = {}

    def add(items, code):
        for item in items:
            sources.setdefault(item, set()).add(code)

    for items in table_items('creature', npc_loot_ids).values():
        add(items, 'loot')
    for items in table_items('gameobject', go_loot_ids).values():
        add(items, 'object')
    for items in table_items('pickpocketing', pick_ids).values():
        add(items, 'pickpocket')
    for items in table_items('skinning', skin_ids).values():
        add(items, 'skinning')
    for name in ('fishing', 'mail', 'disenchant', 'prospecting', 'milling'):
        for items in table_items(name).values():
            add(items, name)
    add({item for npc, item in ctx['quest_items_npc'] if npc in npc_spawned} | {item for go, item in ctx['quest_items_go'] if go in go_spawned}, 'questdrop')
    add({item for npc, item in ctx['vendors'] if npc in npc_spawned}, 'vendor')
    add(ctx['shop_items'], 'shop')
    add({item for npc, item in ctx.get('blackmarket_items', ()) if npc in npc_spawned}, 'blackmarket')
    loot_unplaced = set()
    for items in table_items('creature').values():
        loot_unplaced |= items
    vendor_unplaced = {item for _, item in ctx['vendors']}

    container_items = table_items('item')
    spell_loot = table_items('spell')
    quests = content['quest']
    starters, enders = {}, {}
    for npc, quest in ctx['q_start_npc']:
        starters.setdefault(quest, []).append(('npc', npc, npc in npc_spawned))
    for go, quest in ctx['q_start_go']:
        starters.setdefault(quest, []).append(('go', go, go in go_spawned))
    for npc, quest in ctx['q_end_npc']:
        enders.setdefault(quest, []).append(('npc', npc, npc in npc_spawned))
    for go, quest in ctx['q_end_go']:
        enders.setdefault(quest, []).append(('go', go, go in go_spawned))
    objectives = {}
    for quest, kind, obj, amount in ctx['objectives']:
        objectives.setdefault(quest, []).append((kind, obj, amount))
    disabled_quests = ctx['disabled'].get(1, set())
    # Quest givers live replaced: a creature no spawn or summon brings in, that the live server never sent to a client,
    # while it did send a creature of the same name the server spawns (an old twin, ft.extras: the Classic Mokvar 16012
    # against Forever's 230317). A quest only such givers offer is not given on WoW: Forever: live's copy offers its
    # own quests. Without live records (no EG Link recording) nothing counts as replaced.
    live_npcs = ctx.get('live_npcs') or {}
    replaced_by = {}
    if live_npcs:
        spawned_by_name = {}
        for npcs_ in ctx['npc_maps'].values():
            for n in npcs_:
                if n['id'] in live_npcs:
                    spawned_by_name.setdefault(normal_name(n['name']), set()).add(n['id'])
        for npc, name in ctx.get('quest_npc_names', {}).items():
            if npc in live_npcs or npc in npc_spawned or not normal_name(name):
                continue
            live_copy = spawned_by_name.get(normal_name(name))
            if live_copy:
                replaced_by[npc] = sorted(live_copy)
    # The quests only replaced givers give, or only replaced givers take: not given on WoW: Forever, whatever gives
    # them on this server now. The imports read this (meta not_given_quests) and propose no giver for them: Wowhead's
    # pages inherit the Classic givers (Anthion for the old Anthion's Parting Words), and a card that filled that gap
    # was applied on its own, rolled back, and made again at the next source refresh.
    def all_replaced(links):
        return bool(links) and all(kind == 'npc' and npc in replaced_by for kind, npc, _ in links)
    ctx['not_given_quests'] = {quest for quest in quests
                               if all_replaced(enders.get(quest, [])) or all_replaced(starters.get(quest, []))}

    # learning one spell teaches another (spell_learn_spell, SpellLearnSpell, a learn effect), rank after rank
    chain = {}
    for source, target in list(ctx['learn_chain']) + list(ctx.get('spell_teaches', ())):
        chain.setdefault(source, set()).add(target)
    # taught in a conversation: a spawned NPC or object whose conversation casts a spell that teaches it (a learn
    # effect, rank after rank). ft.server.read_conversations: SmartAI on a menu choice and the rows and timed lists it
    # runs, or one of the core's own scripts. The spell cast is not learned itself: a conversation also casts buffs,
    # teleports and the like on the player.
    cast = {}
    for kind, entry, spell in ctx.get('conversation_casts', ()):
        if entry in (npc_placed if kind == 'npc' else go_placed):
            cast.setdefault(spell, set()).add((kind, entry))
    talked = {}
    todo = [(spell, who) for spell, who in cast.items()]
    while todo:
        spell, who = todo.pop()
        for target in chain.get(spell, set()):
            if not talked.get(target, set()) >= who:
                talked.setdefault(target, set()).update(who)
                todo.append((target, talked[target]))

    available_quests = set()
    tree_spells = ctx.get('tree_spells', set())

    def reward_spells(quests_):
        spells = set()
        for quest in quests_:
            row = ctx['quests'].get(quest, {})
            spells |= {int(row.get(k) or 0) for k in ('RewardSpell', 'RewardDisplaySpell1', 'RewardDisplaySpell2', 'RewardDisplaySpell3')} - {0}
            spells |= ctx.get('quest_display_spells', {}).get(quest, set())
        return spells

    def learned(have):
        """Spells players learn: trainers, auto-learned and starting spells, talent trees, conversations, the reward
        spells of quests they can do and the recipes they hold, then whatever those teach (learn effects, rank after
        rank). Used inside the passes too, so a recipe a quest's reward spell teaches (Research Access 97286 teaching
        Study, which makes the Bundle of Scrolls) counts as a craft source."""
        spells = trained | ctx['auto_learn'] | reward_spells(available_quests) | ctx['create_spells'] | tree_spells | set(talked) | \
            {spell for spell, items in ctx['teaches'].items() if items & have}
        todo = [spell for spell in spells if spell in chain]
        while todo:
            for target in chain[todo.pop()] - spells:
                spells.add(target)
                if target in chain:
                    todo.append(target)
        return spells

    previous_state = None
    for _round in range(40):  # long quest chains (reward -> item -> next quest) need several passes
        state = (len(available_quests), len(sources), sum(len(v) for v in sources.values()))
        if state == previous_state:
            break
        previous_state = state
        obtainable = set(sources)
        for container, items in container_items.items():
            if container in obtainable:
                add(items, 'container')
        for quest in available_quests:
            row = ctx['quests'].get(quest, {})
            add({int(row.get(f'RewardItem{i}') or 0) for i in range(1, 5)} - {0}, 'quest')
            add({int(row.get(f'RewardChoiceItemID{i}') or 0) for i in range(1, 7)} - {0}, 'quest')
            add({int(row.get('StartItem') or 0)} - {0}, 'questgive')   # the package the giver hands over on accept
        learnable = learned(set(sources))
        for item, spells in ctx['creates'].items():
            if spells & learnable:
                add([item], 'craft')
        for spell, items in spell_loot.items():
            if spell in learnable:
                add(items, 'craft')
        # made by one of the core's scripts when a spell players learn is cast (SCRIPT_CREATES: the healthstones)
        for item, spells in SCRIPT_CREATES.items():
            if spells & learnable:
                add([item], 'craft')
        # handed over in a conversation: a choice makes the player cast a spell that creates the item (the Spirit of
        # Azuregos's Magical Ledger)
        for item, spells in ctx['creates'].items():
            if spells & cast.keys():
                add([item], 'talk')
        # made by using an item players hold: the spell it casts (or one that spell triggers) creates it
        held = set(sources)
        for item, spells in ctx['creates'].items():
            if any(ctx.get('used_spells', {}).get(spell, set()) & held for spell in spells):
                add([item], 'use')
        obtainable = set(sources)
        # every quest the server has, not only the official list's: the client's QuestV2 leaves out many quests live
        # Forever runs (Lunar Festival's Festive Recipes, WRIGGLE.), and what they hand out is still in players' hands
        for quest in ctx['quests']:
            if quest not in disabled_quests:
                start_ok = any(s[2] for s in starters.get(quest, [])) or ctx['start_quest_item'].get(quest) in obtainable
                end_ok = any(e[2] for e in enders.get(quest, []))
                if start_ok and end_ok:
                    available_quests.add(quest)
    obtainable = set(sources)
    quest_spells = reward_spells(available_quests)
    learnable = learned(obtainable)
    granted = ctx['granted_spells'] = set()   # spells of a player's skill lines that nobody learns: the writer lists them as internal
    # What the original game taught anywhere (trainers, quests, conversations: the Classic database pack), with what
    # those spells teach; None without a pack
    classic_taught = None
    if ctx.get('classic_taught') is not None:
        classic_taught, todo = set(ctx['classic_taught']), list(ctx['classic_taught'])
        while todo:
            for target in chain.get(todo.pop(), set()) - classic_taught:
                classic_taught.add(target)
                todo.append(target)
    season = ctx.get('season') or (lambda kind, entity_id: False)
    never_given = ctx.get('classic_never_given') or set()   # items the original game gave out nowhere (Classic database pack)
    # what WoW: Forever made itself (neither the original game nor the Classic Era client has it): the original game's
    # database cannot say it was never taught
    forever_made = ctx.get('forever_made') or (lambda kind, entity_id: False)

    def reach(spells):
        seen, todo = set(spells), list(spells)
        while todo:
            for target in chain.get(todo.pop(), set()) - seen:
                seen.add(target)
                todo.append(target)
        return seen

    # {spell: the quests whose turn-in taught it in the original game}, the learn effects followed
    classic_quests = {}
    for taught_spell, ids in (ctx.get('classic_quest_taught') or {}).items():
        for target in reach({taught_spell}):
            classic_quests.setdefault(target, set()).update(ids)

    def reward_changed(spell_id):
        """The quests that taught it in the original game, when the realm has every one of them and each now rewards
        something else (Badlands Reagent Run II 2501 teaches Greater Mender's Potion where it taught Restorative
        Potion): WoW: Forever changed the reward. None otherwise."""
        ids = classic_quests.get(spell_id)
        if not ids or any(q not in ctx['quests'] for q in ids):
            return None
        now = reward_spells(ids)
        return None if not now or spell_id in reach(now) else sorted(ids)
    # What a spell that cannot be learned yet is waiting for, by the realm's own data: the quest that rewards it (itself or
    # the spell that teaches it) and cannot be done yet, the trainer that lists it and is not spawned.
    reward_quests = {}
    for quest, row in ctx['quests'].items():
        if quest in available_quests or quest in disabled_quests:
            continue
        rewards = {int(row.get(k) or 0) for k in ('RewardSpell', 'RewardDisplaySpell1', 'RewardDisplaySpell2', 'RewardDisplaySpell3')} - {0}
        rewards |= ctx.get('quest_display_spells', {}).get(quest, set())
        seen, todo = set(rewards), list(rewards)
        while todo:
            for target in chain.get(todo.pop(), set()) - seen:
                seen.add(target)
                todo.append(target)
        for spell in seen:
            reward_quests.setdefault(spell, set()).add(quest)
    trainer_holders = {}
    holders = {}
    for npc, trainer in ctx['trainers']:
        holders.setdefault(trainer, set()).add(npc)
    for trainer, spell in ctx['trainer_spells']:
        trainer_holders.setdefault(spell, set()).update(holders.get(trainer, ()))

    def in_conversation(spell_id):
        """'taught in a conversation (NPC 14338)' when a spawned NPC or object teaches it by talking, else None."""
        who = sorted(talked.get(spell_id, ()))
        if not who:
            return None
        names = ', '.join(('NPC ' if kind == 'npc' else 'object ') + str(entry) for kind, entry in who[:3]) + ('…' if len(who) > 3 else '')
        names_fr = ', '.join(('PNJ ' if kind == 'npc' else 'objet ') + str(entry) for kind, entry in who[:3]) + ('…' if len(who) > 3 else '')
        return L(f'taught in a conversation ({names})', f'enseigné dans une conversation ({names_fr})')

    def waiting_for(spell_id, items):
        """Why a spell nothing teaches yet is not learnable, as precisely as the realm's data says it."""
        some = lambda ids: ', '.join(map(str, sorted(ids)[:3])) + ('…' if len(ids) > 3 else '')
        if spell_id in trained_any:
            npcs = trainer_holders.get(spell_id)
            if npcs:
                return L(f'Trainer {some(npcs)} has it but is not spawned.', f'L’entraîneur {some(npcs)} l’enseigne mais n’est pas placé.')
            return L('A trainer list has it, but no creature uses that list.', 'Une liste d’entraîneur le contient, mais aucun PNJ ne l’utilise.')
        if spell_id in reward_quests:
            quests_ = reward_quests[spell_id]
            return L(f'Reward of quest {some(quests_)}, which players cannot do yet.', f'Récompense de la quête {some(quests_)}, que les joueurs ne peuvent pas encore faire.')
        if items:
            return L(f'Taught by item {some(items)}, which players cannot get.', f'Appris par l’objet {some(items)}, que les joueurs ne peuvent pas obtenir.')
        return None
    ctx['obtainable'], ctx['learnable'], ctx['item_sources'] = obtainable, learnable, sources
    # Items nothing gives whose only way in is a spell no trainer, quest or conversation teaches and nothing casts: for
    # each, the items that teach or cast those spells (a recipe, a deck's cards). ft.output files such an item with
    # its teachers when every one of them is a test item or a Season of Discovery leftover: no way in is left.
    teachers_only = {}
    for item_id, spells in ctx['creates'].items():
        if item_id in sources or item_id in SCRIPT_CREATES:
            continue
        if any(s in learnable or s in trained_any or s in reward_quests or s in talked or s in cast for s in spells):
            continue
        teachers = set()
        for spell in spells:
            teachers |= ctx['teaches'].get(spell, set()) | ctx.get('used_spells', {}).get(spell, set())
        if teachers:
            teachers_only[item_id] = teachers
    ctx['teachers_only'] = teachers_only
    # Unused copies: an item nothing gives, made only by spells nothing teaches, trains, rewards or casts, while an item
    # of the same name players get is made from the same reagents. Forever's client carries a second Portals Deck
    # (235275, spell 1216291) beside the classic 19277 (spell 23680): both take the Ace through Eight of Portals, but
    # the cards cast 23680, so players combine them into 19277. Nothing is missing.
    spell_reagents = ctx.get('spell_reagents') or {}
    items_ = content.get('item', {})

    def item_name(item_id):
        row = items_.get(item_id) or {}
        return normal_name(row.get('name_en') or row.get('name') or '')

    made_from = {}   # (name, reagents) -> items players get, made by a spell from those reagents
    for item_id, spells in ctx['creates'].items():
        if item_id in sources and item_name(item_id):
            for spell in spells:
                if spell in spell_reagents:
                    made_from.setdefault((item_name(item_id), spell_reagents[spell]), set()).add(item_id)
    unused_copies = {}
    for item_id, spells in ctx['creates'].items():
        if item_id in sources or item_id in SCRIPT_CREATES or not item_name(item_id):
            continue
        if any(s in learnable or s in trained_any or s in reward_quests or s in talked or s in cast or ctx['teaches'].get(s)
               or ctx.get('used_spells', {}).get(s) for s in spells):
            continue
        twins = set()
        for spell in spells:
            if spell in spell_reagents:
                twins |= made_from.get((item_name(item_id), spell_reagents[spell]), set())
        if twins - {item_id}:
            unused_copies[item_id] = twins - {item_id}
    ctx['unused_copies'] = unused_copies
    results = {}
    # Items only quests live no longer gives reward (ctx not_given_quests: the old Anthion's Parting Words and Just
    # Compensation, whose Mokvar and Deliana live replaced): live hands out its own copies instead (the 841xx quests'
    # Tier 0.5 boxes, with pieces of new ids), so nothing is missing. Only when no other quest on the server rewards it
    # and no loot, vendor or recipe has it. A quest the server's disables table switches off (the Burning Crusade copies
    # of the chain, 10492-10499) is no other way in.
    not_given_rewards, rewarded_elsewhere = {}, set()
    for quest, row in ctx['quests'].items():
        items = ({int(row.get(f'RewardItem{i}') or 0) for i in range(1, 5)}
                 | {int(row.get(f'RewardChoiceItemID{i}') or 0) for i in range(1, 7)}) - {0}
        if quest in ctx['not_given_quests']:
            for item in items:
                not_given_rewards.setdefault(item, set()).add(quest)
        elif quest not in disabled_quests:
            rewarded_elsewhere |= items
    for item in rewarded_elsewhere | loot_unplaced | vendor_unplaced | set(ctx['creates']):
        not_given_rewards.pop(item, None)

    def item_result(item_id, entity):
        checks = [check(item_id in known['item'], 'core', L('In the server DB2 or in hotfixes.item_sparse.', 'Présent dans les DB2 du serveur ou dans hotfixes.item_sparse.'), 2)]
        found = sorted(sources.get(item_id, []))
        if found:
            checks.append(check(True, 'source', join([SOURCES[s] for s in found]), 3))
        elif item_id in not_given_rewards:
            olds = sorted(not_given_rewards[item_id])
            some = ', '.join(map(str, olds[:3])) + ('…' if len(olds) > 3 else '')
            checks.append(check(True, 'source', L(
                f'Not given on WoW: Forever: only quest {some} rewards it, which live no longer gives (its giver was replaced).',
                f'Pas donné sur WoW: Forever : seule la quête {some} le donne, que le jeu officiel ne propose plus (son PNJ a été remplacé).'), 3))
        elif item_id in unused_copies:
            twins = ', '.join(map(str, sorted(unused_copies[item_id])))
            checks.append(check(True, 'source', L(
                f'Unused copy: players get item {twins} of the same name, made from the same reagents; nothing casts the spell that makes this one.',
                f'Copie inutilisée : les joueurs obtiennent l’objet {twins} du même nom, fait des mêmes composants ; rien ne lance le sort qui fait celui-ci.'), 3))
        else:
            hint = []
            if item_id in loot_unplaced:
                hint.append(L('loot of a creature that is not spawned', 'butin d’un PNJ non placé'))
            if item_id in vendor_unplaced:
                hint.append(L('sold by a creature that is not spawned', 'vendu par un PNJ non placé'))
            if item_id in ctx['creates']:
                hint.append(L('recipe that cannot be learned', 'recette non apprenable'))
            detail = L('Inactive source: ' + join(hint)['en'], 'Source existante mais inactive : ' + join(hint)['fr']) if hint else \
                L('No source: loot, vendor, quest, craft or shop.', 'Aucune source : butin, marchand, quête, artisanat ou boutique.')
            checks.append(check(False, 'source', detail, 3))
        return checks

    # ---- does anything run a spell's effect: a SpellScript, the core's C++, the aura's proc setup
    core = ctx.get('core_spells') or {}
    core_known = bool(core.get('known'))
    core_ids, core_scripts, proc_scripts = core.get('spells', {}), core.get('scripts', {}), core.get('proc_scripts', set())
    trigger_auras = core.get('trigger_auras', set())
    periodic_scripts = core.get('periodic_scripts', set())
    core_at = f" ({core['commit']})" if core.get('commit') else ''
    bound = ctx.get('spell_scripts', {})
    item_casters = {}
    for item_id, spells in ctx.get('item_spells', {}).items():
        for spell in spells:
            item_casters.setdefault(spell, set()).add(item_id)

    def code_effect(e):
        return e[1] in CODE_EFFECTS or e[2] in CODE_AURAS or (e[2] in TRIGGER_AURAS and not e[4])

    def needs_code(entity):
        """Whether one of the spell's effects does nothing without code: a dummy or script effect, a dummy aura, or a
        proc aura with no spell to trigger."""
        effects = (entity.get('facts') or {}).get('effects')
        if effects is None:
            return bool(entity.get('scriptable'))
        return any(code_effect(e) for e in effects)

    def is_its_mechanic(entity, talent):
        """Whether the code-dependent effect is what the spell is for, so that nothing handling it means the spell
        does nothing. A talent's dummy is its mechanic. Another spell's counts only when every effect it has needs
        code: a dummy beside a real effect (a teleport's, a poison's, Mind Control's) is often a client hook. A passive
        spell whose only such effect is a one-off dummy effect, no dummy aura, is a marker (Horse Riding, Engineering
        Specialization): it runs once when learned and needs nothing."""
        effects = [e for e in (entity.get('facts') or {}).get('effects') or () if e[1]]
        if not effects:
            return bool(entity.get('scriptable')) and talent
        coded = [e for e in effects if code_effect(e)]
        if not coded:
            return False
        if entity.get('passive') and all(not e[2] for e in coded):
            return False
        return talent or len(coded) == len(effects)

    def dummy_aura_works(spell_id, entity):
        """How the core makes use of a spell whose only code effects are dummy auras, or None: conditions that ask for
        the aura (the Argent Dawn Commission 17670: Scourgestones drop for whoever wears it), or the dummy aura's own
        trigger spell, which the core casts when the aura procs (AuraEffect::HandleProcTriggerSpellAuraProc: Fist of Stone
        1294794 restoring mana)."""
        coded = [e for e in (entity.get('facts') or {}).get('effects') or () if code_effect(e)]
        if not coded or any(e[2] != 4 for e in coded):
            return None
        conditions = ctx.get('aura_conditions', {}).get(spell_id, 0)
        if conditions:
            return L(f'Conditions read its aura ({conditions} of them: what drops, shows or can be done while it is on).',
                     f'Des conditions lisent son aura ({conditions} : ce qui tombe, s’affiche ou se fait tant qu’elle est active).')
        procs = spell_id in ctx.get('spell_procs', ()) or spell_id in (ctx.get('client_procs') or ())
        if procs and all(e[4] for e in coded):
            spells = ', '.join(str(e[4]) for e in coded)
            return L(f'The core casts its dummy aura’s trigger spell ({spells}) when the aura procs.',
                     f'Le core lance le sort déclenché de son aura « dummy » ({spells}) quand l’aura se déclenche.')
        return None

    def handler(spell_id, learned=False, entity=None):
        """(handled, how): a bound SpellScript the core registers, or the core's C++ naming the spell. For a spell
        players learn, a creature's or instance's script naming its id does not count: that is what the creature
        casts, or another spell's id (Remorseless Attacks 14144 is The Beast's Fire Blast constant)."""
        names = sorted(n for n in bound.get(spell_id, ()) if not core_known or n in core_scripts)
        if names or (not core_known and spell_id in ctx['scripted_spells']):
            return True, L('SpellScript: ' + ', '.join(names), 'SpellScript : ' + ', '.join(names)) if names else L('SpellScript present', 'SpellScript présent')
        if spell_id in core_ids and (not learned or corespells.spell_file(core_ids[spell_id])):
            return True, L(f'Named by the core’s C++: {core_ids[spell_id]}', f'Nommé par le C++ du core : {core_ids[spell_id]}')
        if spell_id in ctx.get('smart_spellhit', ()):
            return True, L('A SmartAI reacts to being hit by it (smart_scripts).', 'Un SmartAI réagit quand il est touché par ce sort (smart_scripts).')
        if spell_id in ctx.get('reviewed_dummies', {}):
            return True, ctx['reviewed_dummies'][spell_id]
        works = dummy_aura_works(spell_id, entity) if entity is not None else None
        if works:
            return True, works
        orphans = sorted(bound.get(spell_id, ()))
        if orphans:
            return False, L(f"spell_script_names binds {', '.join(orphans)}, which the core{core_at} does not register: the effect does nothing.",
                            f"spell_script_names lie {', '.join(orphans)}, que le core{core_at} n’enregistre pas : l’effet ne fait rien.")
        return False, L(f'Nothing handles its dummy/script effect: no SpellScript in spell_script_names, and the core’s C++{core_at} does not name it.',
                        f'Rien ne gère son effet « dummy »/« script » : aucun SpellScript dans spell_script_names, et le C++ du core{core_at} ne le nomme pas.')

    def spell_handling(spell_id, entity, player, learned=False):
        """The script and proc checks of a spell. A player's spell is counted once the core's C++ was read
        (tools/world/core_spells.json); anyone else's only shows the hint."""
        out = []
        counted = player and core_known and spell_id in known['spell'] and is_its_mechanic(entity, entity.get('sub') == 'talent')
        if needs_code(entity):
            ok, detail = handler(spell_id, learned, entity)
            if not counted:
                detail = L('To check: a dummy/script effect often needs a SpellScript (spell_script_names).',
                           'À vérifier : effet « dummy »/« script », un SpellScript est souvent nécessaire (spell_script_names).') if not ok else detail
            out.append(check(ok, 'script', detail, 2 if counted else 0))
        effects = (entity.get('facts') or {}).get('effects') or ()
        proc_aura = any(e[2] in PROC_AURAS for e in effects)
        proc_script = sorted(n for n in bound.get(spell_id, ()) if n in proc_scripts)
        # a script that makes the aura periodic runs it on a timer: the aura's proc is not what it relies on
        timer_script = sorted(n for n in bound.get(spell_id, ()) if n in periodic_scripts and n not in proc_scripts)
        if player and spell_id in known['spell'] and (proc_aura or proc_script) and ctx.get('client_procs') is not None:
            if spell_id in ctx.get('spell_procs', ()):
                out.append(check(True, 'proc', L('Procs: spell_proc row.', 'Se déclenche : ligne spell_proc.'), 2))
            elif spell_id in ctx['client_procs'] and (not trigger_auras or any(e[2] in trigger_auras for e in effects)):
                out.append(check(True, 'proc', L('Procs: the client’s proc flags (SpellAuraOptions).', 'Se déclenche : indicateurs de déclenchement du client (SpellAuraOptions).'), 2))
            elif timer_script and not proc_script:
                out.append(check(True, 'proc', L(f"Runs on a timer: its script {', '.join(timer_script)} makes the aura periodic, so it needs no proc.",
                                                 f"Agit sur minuterie : son script {', '.join(timer_script)} rend l’aura périodique, aucun déclenchement n’est nécessaire."), 2))
            else:
                what = L(f"its script {', '.join(proc_script)} waits for a proc", f"son script {', '.join(proc_script)} attend un déclenchement") if proc_script \
                    else L('its aura triggers on a proc', 'son aura agit sur déclenchement')
                if spell_id in ctx['client_procs']:
                    # the core builds a proc from the client's flags only for an aura of its isTriggerAura list
                    why = L('the client’s proc flags are ignored, as none of its auras is one the core builds a proc for',
                            'les indicateurs du client sont ignorés, aucune de ses auras n’étant de celles pour lesquelles le core construit un déclenchement')
                else:
                    why = L('no client proc flags (SpellAuraOptions.ProcTypeMask)', 'aucun indicateur du client (SpellAuraOptions.ProcTypeMask)')
                out.append(check(False, 'proc', L(f"Never procs: {what['en']}, but it has no spell_proc row and {why['en']}.",
                                                  f"Ne se déclenche jamais : {what['fr']}, mais il n’a pas de ligne spell_proc et {why['fr']}."), 2))
        return out

    def spell_result(spell_id, entity):
        checks = [check(spell_id in known['spell'], 'core', L('In the server SpellName.db2 or hotfixes.spell_name.', 'Présent dans SpellName.db2 du serveur ou hotfixes.spell_name.'), 2)]
        category = entity['sub']
        taught = False
        if category in ('class', 'profession', 'racial', 'talent', 'mount', 'rune', 'pet'):
            how = []
            if spell_id in trained:
                how.append(L('trainer', 'entraîneur'))
            if spell_id in ctx['auto_learn'] or spell_id in ctx['create_spells']:
                how.append(L('learned automatically', 'appris automatiquement'))
            if spell_id in quest_spells:
                how.append(L('quest reward', 'récompense de quête'))
            if spell_id in ctx['pet_training']:
                how.append(L('pet (training or creature spell)', 'familier (entraînement ou sort de PNJ)'))
            if spell_id in tree_spells and category != 'talent':
                how.append(L('talent or perk tree', 'arbre de talents ou d’avantages'))
            if in_conversation(spell_id):
                how.append(in_conversation(spell_id))
            if spell_id in learnable and not how:
                how.append(L('learned through another spell', 'appris via un autre sort'))
            items = ctx['teaches'].get(spell_id, set())
            if items & obtainable:
                how.append(L('obtainable item', 'objet obtenable'))
            if category == 'talent':
                how.append(L('talent', 'talent'))
            taught = bool(how)
            if not how and spell_id not in trained_any and spell_id not in reward_quests:
                # Not content of WoW: Forever: a Season of Discovery addition only Season items teach, or an original
                # spell nothing teaches that the original game taught nowhere either (a proc, a passive, an old talent
                # rank, what an item casts)
                if season('spell', spell_id) and all(season('item', item) for item in items):
                    how.append(L('Not learned: a Season of Discovery addition to the Classic Era client, which nothing on WoW: Forever teaches.',
                                 'Non appris : un ajout de Season of Discovery au client Classic Era, que rien n’enseigne sur WoW: Forever.'))
                elif classic_taught is not None and not items and not season('spell', spell_id) and spell_id < NEW_FROM['spell'] \
                        and spell_id not in classic_taught and not forever_made('spell', spell_id):
                    how.append(L('Not learned: nothing teaches it, and the original game taught it nowhere either (Classic database).',
                                 'Non appris : rien ne l’enseigne, et le jeu d’origine ne l’enseignait nulle part non plus (base Classic).'))
                elif items and not season('spell', spell_id) and spell_id < NEW_FROM['spell'] and spell_id not in (classic_taught or ()) \
                        and all(item in never_given for item in items) and not forever_made('spell', spell_id):
                    how.append(L('Not learned: only items the original game never gave out teach it (Classic database).',
                                 'Non appris : seuls des objets que le jeu d’origine ne donnait nulle part l’enseignent (base Classic).'))
                elif reward_changed(spell_id):
                    ids = ', '.join(map(str, reward_changed(spell_id)))
                    how.append(L(f'Not learned: quest {ids} taught it in the original game, and WoW: Forever changed its reward (Classic database).',
                                 f'Non appris : la quête {ids} l’enseignait dans le jeu d’origine, et WoW: Forever a changé sa récompense (base Classic).'))
                if how:
                    granted.add(spell_id)
            waiting = None if how else waiting_for(spell_id, items)
            if how:
                detail = join(how)
            elif waiting:
                detail = waiting
            else:
                # The game data says nobody learns it: it is what another ability does, not a line of the spellbook.
                caster = ctx.get('cast_by', {}).get(spell_id)
                if spell_id in ctx.get('never_learned', ()):
                    how.append(L('Not learned: the game data marks it as never learned (another ability or an item applies it).',
                                 'Non appris : les données du jeu le marquent « jamais appris » (une autre capacité ou un objet l’applique).'))
                elif caster:
                    how.append(L(f'Not learned: spell {caster} casts it.', f'Non appris : le sort {caster} le lance.'))
                if how:
                    granted.add(spell_id)
                detail = how[0] if how else L('No trainer, automatic learning or item.', 'Ni entraîneur, ni apprentissage automatique, ni objet.')
            checks.append(check(bool(how), 'learn', detail, 2))
        # A player's spell (one players learn, or one an obtainable item casts) whose effect needs code: it counts.
        # Anyone else's (a creature's, an internal trigger) stays a hint.
        player = taught or bool(item_casters.get(spell_id, set()) & obtainable)
        checks.extend(spell_handling(spell_id, entity, player, taught))
        return checks

    def talent_result(talent_id, entity):
        checks = [check(talent_id in known['talent'], 'core', L('In the server Talent.db2.', 'Présent dans Talent.db2 du serveur.'), 2)]
        missing = [s for s in entity['ranks'] if s in content['spell'] and s not in known['spell'] and s not in ctx['spell_ids']]
        checks.append(check(not missing, 'ranks', L(f"Missing spells: {', '.join(map(str, missing))}", f"Sorts manquants : {', '.join(map(str, missing))}") if missing
                            else L(f"{len(entity['ranks'])} rank(s)", f"{len(entity['ranks'])} rang(s)"), 2))
        scriptable = [s for s in entity['ranks'] if is_its_mechanic(content['spell'].get(s, {}), True)]
        if scriptable:
            unscripted = [s for s in scriptable if not handler(s, True)[0]]
            weight = 2 if core_known else 0
            checks.append(check(not unscripted, 'talent_script', L('Nothing handles the dummy/script effect of rank(s) ' + ', '.join(map(str, unscripted))
                                                                   + ': no SpellScript in spell_script_names, and the core’s C++ does not name them.',
                                                                   'Rien ne gère l’effet « dummy »/« script » des rangs ' + ', '.join(map(str, unscripted))
                                                                   + ' : aucun SpellScript dans spell_script_names, et le C++ du core ne les nomme pas.') if unscripted
                                else L('SpellScript or core C++ present', 'SpellScript ou C++ du core présent'), weight))
        return checks

    def quest_result(quest_id, entity):
        row = ctx['quests'].get(quest_id)
        checks = [check(quest_id in known['quest'], 'core', L('Server QuestV2.db2 or hotfixes.quest_v2.', 'QuestV2.db2 du serveur ou hotfixes.quest_v2.'), 1),
                  check(row is not None, 'quest_row', L('quest_template row (title, rewards, objectives).', 'Ligne quest_template (titre, récompenses, objectifs).'), 3)]
        if row is None:
            return checks
        start = starters.get(quest_id, [])
        item_start = ctx['start_quest_item'].get(quest_id)
        start_ok = any(s[2] for s in start) or item_start in obtainable
        def listing(rows, en_prefix, fr_prefix):
            en = ', '.join(f"{r[1]}{'' if r[2] else ' (not spawned)'}" for r in rows)
            fr = ', '.join(f"{r[1]}{'' if r[2] else ' (non placé)'}" for r in rows)
            return (en_prefix + en if en else ''), (fr_prefix + fr if fr else '')
        if start and not start_ok and not item_start and all(s[0] == 'npc' and s[1] in replaced_by for s in start):
            olds = sorted({s[1] for s in start})
            lives = sorted({e for npc in olds for e in replaced_by[npc]})
            some = lambda ids: ', '.join(map(str, ids[:3])) + ('…' if len(ids) > 3 else '')
            checks.append(check(True, 'starter', L(
                f'Not given on WoW: Forever: only NPC {some(olds)} gives it, which live replaced with {some(lives)}; '
                'live’s copy does not give this quest.',
                f'Non donnée sur WoW: Forever : seul le PNJ {some(olds)} la donne, que le jeu a remplacé par {some(lives)} ; '
                'cette copie ne donne pas cette quête.'), 2))
            return checks
        # Nobody gives it any more and only givers live replaced take it (the old Mokvar's and Deliana's quests once
        # the server stopped offering them): the same. Not a missing giver for an import to fill.
        takers = enders.get(quest_id, [])
        if not start and not item_start and takers and all(e[0] == 'npc' and e[1] in replaced_by for e in takers):
            olds = sorted({e[1] for e in takers})
            lives = sorted({x for npc in olds for x in replaced_by[npc]})
            some = lambda ids: ', '.join(map(str, ids[:3])) + ('…' if len(ids) > 3 else '')
            checks.append(check(True, 'starter', L(
                f'Not given on WoW: Forever: nobody gives it, and only NPC {some(olds)} takes it, which live replaced with '
                f'{some(lives)}; live’s copy does not take this quest.',
                f'Non donnée sur WoW: Forever : personne ne la donne, et seul le PNJ {some(olds)} la reprend, que le jeu a '
                f'remplacé par {some(lives)} ; cette copie ne la reprend pas.'), 2))
            return checks
        is_npc = bool(start) and start[0][0] == 'npc'
        en, fr = listing(start, 'NPC ' if is_npc else 'Object ', 'PNJ ' if is_npc else 'Objet ')
        if item_start:
            en = (en + ' · ' if en else '') + f"item {item_start}{'' if item_start in obtainable else ' (not obtainable)'}"
            fr = (fr + ' · ' if fr else '') + f"objet {item_start}{'' if item_start in obtainable else ' (non obtenable)'}"
        checks.append(check(start_ok, 'starter', L(en or 'No quest giver (creature/gameobject_queststarter).', fr or 'Aucun donneur (creature/gameobject_queststarter).'), 2))
        end = enders.get(quest_id, [])
        en, fr = listing(end, '', '')
        checks.append(check(any(e[2] for e in end), 'ender', L(en or 'No quest ender.', fr or 'Aucun valideur.'), 2))
        problems = []
        for kind, obj, amount in objectives.get(quest_id, []):
            # a creature the objective only counts (a credit marker) is credited by a spell; one an item players hold
            # casts when used gives the credit wherever the quest says (the Forever quest items that mark a spot)
            credited = any(ctx.get('used_spells', {}).get(spell, set()) & obtainable for spell in ctx.get('credit_spells', {}).get(obj, ())) \
                or obj in ctx.get('script_credits', ()) \
                or any(entry in (npc_spawned if kind_ == 'npc' else go_spawned) for kind_, entry in ctx.get('smart_credits', {}).get(obj, ())) \
                or bool(ctx.get('object_credits', {}).get(obj, set()) & go_spawned)
            if kind == 0 and obj not in npc_spawned and not (kill_credit.get(obj, set()) & npc_spawned) and not credited:
                problems.append(L(f'creature {obj} not spawned', f'PNJ {obj} non placé'))
            elif kind == 1 and obj not in obtainable and obj != int(row.get('StartItem') or 0):
                problems.append(L(f'item {obj} not obtainable', f'objet {obj} non obtenable'))
            elif kind == 2 and obj not in go_spawned:
                problems.append(L(f'object {obj} not spawned', f'objet du monde {obj} non placé'))
        if objectives.get(quest_id):
            count = len(objectives[quest_id])
            detail = L('; '.join(p['en'] for p in problems[:4]), '; '.join(p['fr'] for p in problems[:4])) if problems else L(f'{count} objective(s)', f'{count} objectif(s)')
            checks.append(check(not problems, 'objectives', detail, 2))
        if quest_id in disabled_quests:
            checks.append(check(False, 'enabled', L('Disabled in the disables table.', 'Désactivée dans la table disables.'), 3))
        # The words: a quest that works with an empty window is not finished. Only what every such quest shows is
        # asked for: the giver's text (a quest taken from a giver; an auto-complete one has none by design) and the
        # turn-in text (a quest handed in to someone).
        lacking = []
        if start and int(row.get('QuestType') or 0) != QUEST_TYPE_AUTOCOMPLETE and not int(row.get('HasText') or 0) \
                and quest_id not in NO_OFFICIAL_GIVER_TEXT:
            lacking.append(L('no quest text (description, objectives)', 'pas de texte de quête (description, objectifs)'))
        if end and quest_id not in ctx.get('quest_turn_in_text', ()) and quest_id not in NO_OFFICIAL_TURN_IN_TEXT \
                and quest_id not in ctx.get('quest_no_official_turn_in', ()):
            lacking.append(L('no turn-in text (quest_offer_reward, quest_request_items)', 'pas de texte de rendu (quest_offer_reward, quest_request_items)'))
        if start or end:
            checks.append(check(not lacking, 'texts', join(lacking) if lacking else L('Quest text and turn-in text', 'Texte de quête et texte de rendu'), 1))
        # Whose quest it is. Most quests are offered to every race and it is their giver's faction that keeps one side
        # out, so "everyone" on the server against "the Horde" in players' reports is no finding (it is what the live
        # server itself answers for hundreds of them). Only a quest the server keeps to one side is asked about: that
        # side must be one players on live got it on.
        told = ctx.get('report_sides', {}).get(quest_id)
        ours = reports.allowed_sides(row.get('AllowableRaces')) if told else set()
        if told and len(ours) == 1:
            words = lambda sides, fr=False: (' et ' if fr else ' and ').join(('l’Alliance' if fr and s == 'Alliance' else 'la Horde' if fr else 'the ' + s) for s in sorted(sides))
            checks.append(check(bool(ours & told), 'side', L(f"Kept to {words(ours)} on the server; players on live got it as {words(told)}.",
                                                            f"Réservée à {words(ours, True)} sur le serveur ; en jeu, les joueurs l’ont eue pour {words(told, True)}."), 1))
        return checks

    boxes = {}
    for ui in ctx['ui_maps']:
        for a in ui.get('assignments', []):
            if a.get('area'):
                boxes.setdefault(a['area'], []).append((a['map'], a['region']))
    zone_spawns = {}
    for zone_id, regions in boxes.items():
        count = 0
        for map_id, (min_x, min_y, max_x, max_y) in regions:
            count += sum(1 for m, x, y, _ in ctx['spawns'] if m == map_id and min_x <= x <= max_x and min_y <= y <= max_y)
        zone_spawns[zone_id] = count

    official_quests_by_zone = {}
    for quest_id in quests:
        row = ctx['quests'].get(quest_id)
        # a developer's leftover ("<UNUSED>", "[DNT]") is filed under Internal / test, not counted against its zone
        if row and int(row['QuestSortID'] or 0) > 0 and not named_internal(row.get('LogTitle')):
            official_quests_by_zone.setdefault(int(row['QuestSortID']), []).append(quest_id)

    # Rows of the client that are no boss of their own (Season of Discovery's raid versions, the same fight listed
    # again): they do not count among an instance's bosses, and the analysis files them under Internal / test.
    shadows = bosses.shadows(content['boss'])
    for boss_id, (reason, kept) in shadows.items():
        content['boss'][boss_id]['shadow'] = {'reason': reason, 'kept': kept}

    def boss_match(boss_id, boss, map_id):
        return bosses.find(boss_id, boss, ctx['npc_maps'].get(map_id, []), ctx.get('unspawned_npc', ()), ctx.get('summoned_npc', ()),
                           bool(ctx['instance_template'].get(map_id)), ctx.get('encounter_npc', {}).get(boss_id, ()))

    def dungeon_result(map_id, entity):
        kind = entity['kind']
        tiles = ctx['map_tiles'].get(map_id, 0)
        vmap = map_id in ctx['vmaps']
        checks = [check(map_id in known['dungeon'], 'core', L('Server Map.db2.', 'Map.db2 du serveur.'), 1),
                  check(tiles > 0 or vmap, 'terrain', L(f"{tiles} .map tile(s), vmaps {'yes' if vmap else 'no'}", f"{tiles} tuile(s) .map, vmaps {'oui' if vmap else 'non'}"), 2),
                  check(map_id in ctx['mmaps'], 'mmaps', L('Advised: without mmaps creatures move in straight lines.', 'Conseillé : sans mmaps les PNJ se déplacent en ligne droite.'), 0)]
        if kind in (1, 2):
            script = ctx['instance_template'].get(map_id)
            checks.append(check(script is not None, 'instance_template', L(script or 'Row present', script or 'Ligne présente') if script is not None else L('No row: the instance cannot be created.', 'Aucune ligne : l’instance ne peut pas être créée.'), 2))
            checks.append(check(map_id in ctx['entrances'], 'entrance', L('An entrance teleports into this map (areatrigger_teleport, a server area trigger or a script).', 'Une entrée téléporte dans cette carte (areatrigger_teleport, un déclencheur serveur ou un script).') if map_id in ctx['entrances']
                                else L('No entrance teleporter.', 'Aucun téléporteur d’entrée.'), 2))
        else:
            checks.append(check(map_id in ctx['battlegrounds'] or kind == 4, 'battleground', L('battleground_template', 'battleground_template'), 2))
        npcs = ctx['npc_maps'].get(map_id, [])
        spawned = sum(n['n'] for n in npcs)
        objects = ctx['go_counts'].get(map_id, 0)
        # a battleground is mostly flags, gates and graveyards: Warsong Gulch has five creatures and works
        populated = spawned >= 10 if kind in (1, 2) else spawned + objects >= 10
        checks.append(check(populated, 'spawns', L(f'{spawned} creatures, {objects} world objects', f'{spawned} PNJ, {objects} objets du monde'), 3))
        encounters = [(i, b) for i, b in content['boss'].items() if b['map'] == map_id and i not in shadows]
        if encounters:
            found = sum(1 for i, b in encounters if boss_match(i, b, map_id)[0])
            checks.append(check(found == len(encounters), 'bosses', L(f'{found} / {len(encounters)} bosses found among the spawned creatures', f'{found} / {len(encounters)} boss trouvés parmi les PNJ placés'), 3))
        if map_id in ctx['disabled'].get(2, set()):
            checks.append(check(False, 'enabled', L('Map disabled in disables.', 'Carte désactivée dans disables.'), 3))
        return checks

    def boss_result(boss_id, entity):
        npc, how = boss_match(boss_id, entity, entity['map'])
        if how in ('summoned', 'scripted'):
            detail = L(f"Not spawned: a script brings in creature {npc['id']} “{npc['name']}”", f"Non placé : un script fait apparaître le PNJ {npc['id']} « {npc['name']} »")
        elif npc:
            detail = L(f"Creature {npc['id']} “{npc['name']}”", f"PNJ {npc['id']} « {npc['name']} »")
        else:
            detail = L('No spawned creature of that name in the instance.', 'Aucun PNJ placé de ce nom dans l’instance.')
        checks = [check(npc is not None, 'boss_spawn', detail, 3)]
        if how == 'spawned':
            checks.append(check(npc['scripted'], 'boss_script', L('ScriptName or SmartAI', 'ScriptName ou SmartAI') if npc['scripted']
                                else L('No script: the boss has no mechanics.', 'Pas de script : le boss n’a pas ses mécaniques.'), 2))
        elif how == 'scripted':
            # weight 0: said aloud, not counted. Nothing names what summons it; its own script and the instance's are the only sign.
            checks.append(check(False, 'boss_placed', L('To check in game: no summon of it is known, only its C++ script in a scripted instance.',
                                                        'À vérifier en jeu : aucune invocation connue, seulement son script C++ dans une instance scriptée.'), 0))
        return checks

    def zone_result(zone_id, entity):
        map_id = entity['map']
        entity['weak'] = zone_id not in boxes and not official_quests_by_zone.get(zone_id)
        # a map with no ground tiles, only buildings (the Deeprun Tram), has its terrain in the vmaps alone
        tiles, vmap = ctx['map_tiles'].get(map_id, 0), map_id in ctx['vmaps']
        checks = [check(tiles > 0 or vmap, 'terrain', L(f"map {map_id}: {tiles} .map tile(s), vmaps {'yes' if vmap else 'no'}",
                                                        f"carte {map_id} : {tiles} tuile(s) .map, vmaps {'oui' if vmap else 'non'}"), 1)]
        if zone_id in boxes:
            n = zone_spawns.get(zone_id, 0)
            checks.append(check(n >= 20, 'spawns', L(f'≈{n} creatures inside the zone', f'≈{n} PNJ dans l’emprise de la zone'), 3))
        # the quests WoW: Forever does not give (the old Tier 0.5 and Tier 3 quests of Ironforge and Orgrimmar, whose Forever
        # copies are other quests) are no quest of the zone's; one players cannot take now but whose own check passes (given
        # by an item, by an event) is not the zone's gap either
        zone_quests = [qid for qid in official_quests_by_zone.get(zone_id, []) if qid not in ctx['not_given_quests']]
        if zone_quests:
            ready = sum(1 for qid in zone_quests if qid in available_quests or results.get(('quest', qid), ('',))[0] == 'ok')
            checks.append(check(ready >= len(zone_quests) * 0.8, 'zone_quests', L(f'{ready} / {len(zone_quests)} quests can be done', f'{ready} / {len(zone_quests)} quêtes faisables'), 3))
        # a graveyard for a zone a map draws; without the map data every zone is asked, as before
        mapped = ctx.get('mapped_zones') or ()
        if not mapped or zone_id in mapped:
            checks.append(check(zone_id in ctx['graveyards'], 'graveyard', L('graveyard_zone', 'graveyard_zone'), 1))
        return checks

    def recipe_result(spell_id, entity):
        how = []
        if spell_id in trained:
            how.append(L('trainer', 'entraîneur'))
        if entity.get('auto') or spell_id in ctx['auto_learn']:
            how.append(L('learned automatically', 'appris automatiquement'))
        teach = ctx['teaches'].get(spell_id, set())
        if teach & obtainable:
            how.append(L('obtainable recipe', 'recette obtenable'))
        if in_conversation(spell_id):
            how.append(in_conversation(spell_id))
        if spell_id in learnable and not how:
            how.append(L('learned through another spell', 'appris via un autre sort'))
        if how:
            detail = join(how)
        else:
            detail = waiting_for(spell_id, teach) or L('No trainer and no recipe.', 'Ni entraîneur ni recette.')
        return [check(spell_id in known['spell'], 'core', L('', ''), 1), check(bool(how), 'learn', detail, 3)]

    def collection_spell(spell_id):
        """How players learn a mount's or a pet's spell, by the same rules as the spell's own line: a trainer, an item
        players can get, a quest reward (the paladin's and the warlock's class mounts), automatic learning, a talent or
        perk tree, a conversation, or another spell that teaches it."""
        how = []
        if spell_id in trained:
            how.append(L('trainer', 'entraîneur'))
        items = ctx['teaches'].get(spell_id, set())
        if items & obtainable:
            ids = ', '.join(map(str, sorted(items & obtainable)[:3]))
            how.append(L('obtainable item ' + ids, 'objet obtenable ' + ids))
        if spell_id in quest_spells:
            how.append(L('quest reward', 'récompense de quête'))
        if spell_id in ctx['auto_learn'] or spell_id in ctx['create_spells']:
            how.append(L('learned automatically', 'appris automatiquement'))
        if spell_id in tree_spells:
            how.append(L('talent or perk tree', 'arbre de talents ou d’avantages'))
        if in_conversation(spell_id):
            how.append(in_conversation(spell_id))
        if spell_id in learnable and not how:
            how.append(L('learned through another spell', 'appris via un autre sort'))
        return how, items

    def mount_result(mount_id, entity):
        how, items = collection_spell(entity['spell'])
        if how:
            detail = join(how)
        elif items:
            ids = ', '.join(map(str, sorted(items)[:3]))
            detail = L('Item exists but cannot be obtained: ' + ids, 'Objet existant mais non obtenable : ' + ids)
        else:
            detail = waiting_for(entity['spell'], items) or L('No item and no trainer.', 'Aucun objet ni entraîneur.')
        return [check(mount_id in known['mount'], 'core', L('Server Mount.db2.', 'Mount.db2 du serveur.'), 1), check(bool(how), 'obtainable', detail, 3)]

    def pet_result(pet_id, entity):
        how, items = collection_spell(entity['spell'])
        return [check(pet_id in known['pet'], 'core', L('', ''), 1),
                check(bool(how), 'obtainable', join(how) if how else L('No obtainable item teaches this pet.', 'Aucun objet obtenable n’apprend cette mascotte.'), 3)]

    def toy_result(toy_id, entity):
        item = entity['item']
        found = sorted(sources.get(item, []))
        return [check(toy_id in known['toy'], 'core', L('', ''), 1),
                check(item in obtainable, 'obtainable', join([SOURCES[s] for s in found]) if found else L(f'Item {item} has no source.', f'L’objet {item} n’a aucune source.'), 3)]

    def achievement_result(ach_id, entity):
        checks = [check(ach_id in known['achievement'], 'core', L('Server Achievement.db2 or hotfixes.', 'Achievement.db2 du serveur ou hotfixes.'), 2)]
        if entity.get('reward') or entity.get('reward_item'):
            if ach_id in ctx['achievement_rewards']:
                checks.append(check(True, 'reward', L('achievement_reward (title / item by mail).', 'achievement_reward (titre / objet par courrier).'), 2))
            elif ach_id in ctx.get('achievement_currency', ()) and not entity.get('reward_item'):
                # "Earn 1 Legacy Point.": the trait system pays it once the achievement is earned
                checks.append(check(True, 'reward', L('A talent or perk point: the core counts the achievement itself (TraitCurrencySource), no achievement_reward row.',
                                                      'Un point de talent ou d’avantage : le cœur compte le haut fait lui-même (TraitCurrencySource), sans ligne achievement_reward.'), 2))
            else:
                checks.append(check(False, 'reward', L('achievement_reward (title / item by mail).', 'achievement_reward (titre / objet par courrier).'), 2))
        return checks

    def taxi_result(node_id, entity):
        x, y = entity['pos'][0], entity['pos'][1]
        near = min((math.hypot(fx - x, fy - y) for m, fx, fy in ctx['flight_spawns'] if m == entity['map']), default=None)
        detail = L(f'{near:.0f} yd away', f'à {near:.0f} m') if near is not None and near < 5000 else L('No flight master nearby.', 'Aucun maître de vol à proximité.')
        held = node_id in TOWER_TAXI
        if held:
            detail = L('Its flight master appears while a faction holds the tower.', 'Son maître de vol apparaît quand une faction tient la tour.')
        elif not entity.get('learned', True) and not (near is not None and near < 60):
            held = True   # the client keeps no "known" bit for it: players never learn it, so no flight master opens it
            detail = L('No flight master: players never learn this point (an NPC or a quest starts flights from here).',
                       'Pas de maître de vol : les joueurs n’apprennent jamais ce point (un PNJ ou une quête lance les vols depuis ici).')
        elif node_id in ctx.get('script_taxi_nodes', ()) and not (near is not None and near < 60):
            held = True   # no flight master by design: an NPC's script starts the flight (the druids' flights out of Moonglade)
            detail = L('No flight master: an NPC’s script starts the flight from here.', 'Pas de maître de vol : le script d’un PNJ lance le vol depuis ici.')
        return [check(node_id in known['taxi'], 'core', L('Server TaxiNodes.db2.', 'TaxiNodes.db2 du serveur.'), 1),
                check(held or (near is not None and near < 60), 'flightmaster', detail, 3)]

    rules = {'item': item_result, 'spell': spell_result, 'talent': talent_result, 'quest': quest_result, 'dungeon': dungeon_result,
             'boss': boss_result, 'zone': zone_result, 'recipe': recipe_result, 'mount': mount_result, 'pet': pet_result, 'toy': toy_result,
             'achievement': achievement_result, 'taxi': taxi_result}
    for kind, rule in rules.items():
        for entity_id, entity in content.get(kind, {}).items():
            checks = rule(entity_id, entity)
            total = sum(c['w'] for c in checks)
            score = round(100 * sum(c['w'] for c in checks if c['ok']) / total) if total else 0
            status = 'ok' if score == 100 else ('missing' if score < 35 else 'partial')
            results[(kind, entity_id)] = (status, score, checks)
    ctx['available_quests'] = available_quests
    return results
