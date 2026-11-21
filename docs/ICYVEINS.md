# What Icy Veins' WoW Forever database holds

An audit of [db.icy-veins.com/wow-forever](https://db.icy-veins.com/wow-forever) made on 2026-11-15, and what the
tracker does with each part. The site's pages are built from a JSON API, which is what the tracker reads:

- `GET /api/catalog/wowf/<kind>?limit=200&page=N` lists a kind (200 per page at most): `{total, pages, rows: [{id, name}]}`.
  Without an API key only the first 10,000 rows of a list are given (HTTP 400 "page N is beyond the first 10,000
  rows; narrow the filters or sort, or use an API key", seen 2026-11-15). `&dir=desc` lists from the other end, so
  every kind up to 20,000 rows is listed whole; items (about 32,000) are completed from what the NPCs, objects and
  quests name.
- `GET /api/catalog/wowf/<kind>/<id>` is one answer: `entity` (the client's row), `children`, `relations`, plus link
  metadata, tooltips and a change history.
- `GET /api/catalog/wowf/types` lists the kinds and how many of each.

Every answer is kept twice: in the mirror (`data/icyveins/<kind>/<id>.json.gz`: `type`, `id`, `entity`, `children`,
`relations`, what the cards read) and, whole, in the tracker's database (`ft_source_answers`, `source = 'icyveins'`:
the mirror's record as `data`, the whole answer with its link metadata, tooltips and change history as `whole`). See
[The answers table](SOURCES.md#the-answers-table).

    -- what Icy Veins changed this week
    SELECT kind, id, name, changed_at FROM ft_source_answers WHERE source = 'icyveins' AND changed_at > first_seen AND changed_at >= NOW() - INTERVAL 7 DAY;
    -- what else a whole answer holds besides the mirror's parts
    SELECT JSON_KEYS(whole) FROM ft_source_answers WHERE source = 'icyveins' AND kind = 'npc' AND id = 448;

The HTML pages sit behind a Cloudflare check; the API does not. robots.txt allows everything; no licence is stated, so
the data stays a reference for your own server.

## The kinds

| Kind | Count | Player recordings (`addon_*`) | In the mirror |
|---|---:|---|---|
| npc | 15,955 | drops, loot (coin), sells, trains, services, quests, levels, points, gossip | yes |
| gameobject | 10,455 | contains, gathers, loot, points, quests, services | yes |
| quest | 7,092 | givers, dialog (turn-in words), leads to | yes |
| item | 31,974 | dropped by, sold by, gathered from | yes |
| zone | 1,404 | NPCs and objects seen there | yes |
| flight-path | 101 | (routes from the client) | yes |
| ui-map | 60 | (zones) | yes |
| spell, achievement, item-set, faction, emote, race, skill, title, mount, battle-pet, … | | none: the client's own tables | no (the tracker reads the client) |

## What each recording holds, and where it goes

| Recording | Fields | Tracker |
|---|---|---|
| npc `addon_drops`, item `addon_dropped_by` | item, chance (0..1), stack, quest-only flag, **spell_id** (0 corpse, 8613/8617/8618/10768 Skinning, 2575/2366 Mining and Herb Gathering on a creature, 921 Pick Pocket) | `creature_loot_template`, `skinning_loot_template`, `pickpocketing_loot_template`; quest-only = `QuestRequired 1` |
| gameobject `addon_contains` | item, chance, stack (chests, ore veins, herbs) | `gameobject_loot_template` |
| gameobject `addon_gathers`, item `addon_gathered_from` | gather kind (mine, herb, skin, fish, unlock), container item | containers (clams, lockboxes) kept: no chance recorded |
| npc `addon_sells`, item `addon_sold_by` | item, price, stock left, cost items / currencies, still sold | `npc_vendor` (money only) |
| npc `addon_trains` | spell, cost, level, rank; for professions the skill and the rank it needs (`details`: skillLine, skillRank) | `trainer_spell` (with `ReqSkillLine` / `ReqSkillRank` for recipes), only from NPCs whose services include training |
| npc `addon_services` | service number (5 vendor, 6 flight master, 7 trainer, 8 banker, 18 spirit healer, 20 innkeeper; others not decoded yet), repair | `creature_template.npcflag` bits the creature lacks |
| quest `addon_givers`, npc/gameobject `addon_quests` | who starts, who ends | `creature_` / `gameobject_queststarter` / `questender` |
| quest `addon_dialog` | kind (complete, progress), speaker, text | `quest_offer_reward`, `quest_request_items` (quests without a row) |
| npc/gameobject `addon_points` | UiMap, x/y in thousandths, via (talk, loot, sight), players, reports, last build | the locator, where Wowhead gives no position |
| npc `addon_levels` | UiMap, level min/max | kept, not compared yet |
| npc/gameobject `addon_loot` | spell, average coin, first/last build | kept, not compared yet |
| npc `addon_gossip` | text, option texts, ids, icons | kept, not compared yet |
| quest `addon_leads_to` | the quests players took next from the same NPC | kept |
| zone `addon_npcs`, `addon_objects` | ids seen, points, services | kept |

Two things in the recordings need care. A drop names the spell that looted it: before 2026-11-15 the tracker wrote
skinned leather and hides as corpse loot (Light Leather alone has 786 skinning rows); rows an earlier card applied that
way stay in `creature_loot_template` until removed by hand. And the recording gives bankers,
innkeepers and spirit healers the trainer list of whoever a player spoke to before: a trainer list counts only from an
NPC that offers training.
