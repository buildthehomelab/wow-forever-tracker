# Docker

ForeverTracker runs in one container: Apache and PHP 8.3 for the website, Python 3 and the `mysql` client for the
analysis. There is no launcher and no setup wizard: the container writes `config.ini` from its environment on every
start, and runs the first analysis by itself.

```bash
cp docker-compose.example.yml docker-compose.yml   # then fill in your values
docker compose up -d --build
docker compose logs -f tracker                     # the first analysis takes a few minutes
```

Open `http://127.0.0.1:8090/`.

## What it needs

| | |
|---|---|
| MySQL | A user that can read `world`, `hotfixes` and `auth` (`auth.realmlist`, and `battlenet_accounts`, `account`, `account_access` for game master logins) and write the tracker's own database. The Forge also needs write access to `world` and `hotfixes`: without it, it still previews the SQL, and applying fails. |
| Server data | Your server's data folder mounted at `/server/data`: `dbc/<locale>` (the DB2 files the worldserver loads), `maps`, `vmaps`, `mmaps`. |
| Official DB2 files | The client build's DB2 files, for the snapshot. When your server's DB2 files come from that same client build (extracted with `mapextractor`), they are the official ones and nothing else is needed. Otherwise extract them (`mapextractor -e 2`) into a folder, mount it, and point `FT_CLIENT_DBC` at it. |

The MySQL user, for a server whose databases are `world`, `hotfixes` and `auth`:

```sql
CREATE DATABASE IF NOT EXISTS forever_tracker DEFAULT CHARACTER SET utf8mb4;
CREATE USER 'tracker'@'%' IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON forever_tracker.* TO 'tracker'@'%';
GRANT SELECT ON world.* TO 'tracker'@'%';
GRANT SELECT ON hotfixes.* TO 'tracker'@'%';
GRANT SELECT ON auth.realmlist TO 'tracker'@'%';
GRANT SELECT ON auth.battlenet_accounts TO 'tracker'@'%';
GRANT SELECT ON auth.account TO 'tracker'@'%';
GRANT SELECT ON auth.account_access TO 'tracker'@'%';
-- the Forge: GRANT SELECT, INSERT, UPDATE, DELETE ON world.* TO 'tracker'@'%'; (and on hotfixes.*)
```

A good use of the two kinds of access: point `FT_DB_WORLD` and `FT_DB_HOTFIXES` at a test copy of your databases with
write access, and keep the live ones read-only.

## At start

1. `config.ini` is written from the environment below (readable by the web server only). The setup wizard is not
   used; changes go in the environment.
2. In the background, once MySQL answers: the client build is `FT_BUILD`, or the highest `gamebuild` of
   `auth.realmlist`. When that build has no snapshot yet in the data volume, the container stores it
   (`tracker.py snapshot`), analyses (`tracker.py analyse`) and runs the locator (`tracker.py locate`). The progress
   is in `docker compose logs` and in the Forge, like *Run again*.
3. Apache starts at once; pages fill in when the analysis is done.

A new client build on the server therefore gets its own snapshot, and the changelog compares it with the previous
one. Later runs: *Run again* in the Forge, or `docker compose exec -u www-data tracker python3 tools/tracker.py analyse`.

## Environment

| Variable | Default | |
|---|---|---|
| `FT_DB_HOST`, `FT_DB_PORT` | `mysql`, `3306` | MySQL |
| `FT_DB_USER`, `FT_DB_PASSWORD` | `tracker`, *required* | MySQL user |
| `FT_DB_TRACKER` | `forever_tracker` | Database of the tracker's `ft_*` tables |
| `FT_DB_WORLD`, `FT_DB_HOTFIXES`, `FT_DB_AUTH` | `world`, `hotfixes`, `auth` | Your server's databases |
| `FT_SERVER_DATA` | `/server/data` | Server data folder inside the container |
| `FT_DBC_LOCALE` | `enUS` | Locale folder of the DB2 files (`enUS` or `frFR`) |
| `FT_CLIENT_DBC` | `$FT_SERVER_DATA/dbc` | Official DB2 files for the snapshot (a folder with `<locale>` sub-folders, or flat) |
| `FT_BUILD` | from `auth.realmlist` | Client build of the server data |
| `FT_ANALYSE_ON_START` | `new-build` | `new-build`: only for a build without a snapshot; `always`; `never` |
| `FT_WOWHEAD` | `1` | `0`: the analysis does not ask Wowhead's public tooltips for the names of new quests the server lacks, nor check the items players cannot get and the new trainer spells (the first check of ~7,000 items takes about an hour, then it is cached) |
| `FT_LOCATE` | `1` | `0`: no locator after the first analysis (it asks Wowhead's public tooltips, slowly) |
| `FT_ADMIN_USER`, `FT_ADMIN_PASSWORD` | `admin`, empty | Local administrator; empty password: game masters only |
| `FT_GM_LEVEL` | `3` | GM level a game account needs to log in as an administrator |
| `FT_VENDOR_ENTRY` | `0` | Default vendor the Forge proposes |
| `FT_PUBLIC` | `1` | `0`: only administrators see the tracker |
| `FT_LANGUAGE` | `en` | `en` or `fr`: the default interface language |
| `FT_LANGUAGES` | `en,fr` | `en`: English only, everywhere (no French names or language switch); `fr`: French only. A change analyses again at the next start |
| `FT_SITE_NAME`, `FT_HOME_URL`, `FT_HOME_LABEL`, `FT_REPOSITORY_URL` | | `[site]` of [CONFIGURATION.md](CONFIGURATION.md) |
| `FT_RA_HOST`, `FT_RA_PORT`, `FT_RA_USER`, `FT_RA_PASSWORD` | empty, `3443` | Remote console for spawns ([SPAWNS.md](SPAWNS.md)) |
| `FT_WOWHEAD_RECHECK_DAYS` | `7` | Days after which a "Wowhead does not know it" answer is asked again (Forever keeps content for players to discover; Wowhead learns it later). *Run again* in the Forge asks Wowhead too while `FT_WOWHEAD` is 1 |
| `FT_WOWHEAD_BRANCH`, `FT_WOWHEAD_PAUSE` | `forever`, `0.4` | Locator |
| `FT_FORGE_TRAINER_GUESS` | `1` | `0`: no trainer fixes guessed from the client's skill lines; trainer spells come from imports (NorgannonDB) only. A change re-analyses once |
| `FT_NORGANNONDB_COMMIT` | empty | NorgannonDB commit the import reads (empty: the tested one) |
| `FT_FORGE_TRAINER_SKIP_IDS` | empty | Spell ids and ranges the Forge never offers at trainers (`400000-499999, 12345`); a change re-analyses once at the next start |

Values may not contain a double quote.

## Not in the container

- The Windows launcher (`ForeverTracker.exe`, the `.bat` files) and the setup wizard.
- ForeverScribe notes: they are read from the SavedVariables of a game client on the same computer, and the
  container has none. World data files in WowPacketParser's SQL format import as usual (Forge, *Imports*).
- Installing the ForeverForge addon from the Forge (no game client in the container): copy `addon/ForeverForge` into
  your client's `Interface/AddOns` yourself.
