#!/bin/sh
# ForeverTracker container start (docs/DOCKER.md):
#   1. writes config.ini from the FT_* environment (every start, so the environment is the only place to change it)
#   2. in the background, when the server's client build has no snapshot yet: snapshot, analyse, then the locator
#   3. runs the command (Apache)
set -eu

ROOT=/opt/forever-tracker
CONFIG="$ROOT/config.ini"
DATA="$ROOT/data"
SERVER_DATA="${FT_SERVER_DATA:-/server/data}"
LOCALE="${FT_DBC_LOCALE:-enUS}"

say() { echo "[forever-tracker] $*"; }

# config.ini quotes every value: a " or a line break inside one would break the file
for var in FT_LANGUAGES FT_DB_HOST FT_DB_USER FT_DB_PASSWORD FT_DB_TRACKER FT_DB_WORLD FT_DB_HOTFIXES FT_DB_AUTH FT_BUILD_DB FT_BUILD_USER FT_BUILD_PASSWORD FT_SITE_NAME \
           FT_ADMIN_USER FT_ADMIN_PASSWORD FT_RA_HOST FT_RA_USER FT_RA_PASSWORD FT_HOME_URL FT_HOME_LABEL FT_SERVER_DATA FT_CLIENT_DBC FT_PHASE FT_PHASES_FILE; do
    eval "value=\${$var:-}"
    case "$value" in
        *\"*|*'
'*) say "ERROR: $var must not contain a double quote or a line break"; exit 1 ;;
    esac
done
case "${FT_ADMIN_USER:-admin}" in
    *[!A-Za-z0-9_.-]*) say "ERROR: FT_ADMIN_USER may hold only letters, digits, _ . -"; exit 1 ;;
esac
: "${FT_DB_PASSWORD:?set FT_DB_PASSWORD}"

admins=""
if [ -n "${FT_ADMIN_PASSWORD:-}" ]; then
    hash="$(php -r 'echo password_hash(getenv("FT_ADMIN_PASSWORD"), PASSWORD_DEFAULT);')"
    admins="${FT_ADMIN_USER:-admin} = \"$hash\""
else
    say "no FT_ADMIN_PASSWORD: only game masters (Battle.net login, GM level ${FT_GM_LEVEL:-3}+) can open the Forge"
fi

umask 027
cat > "$CONFIG" <<EOF
; Written by docker/entrypoint.sh from the container's environment on every start: change the environment, not this file.
[site]
name = "${FT_SITE_NAME:-Forever Tracker}"
default_language = "${FT_LANGUAGE:-en}"
languages = "${FT_LANGUAGES:-en,fr}"
public = ${FT_PUBLIC:-1}
home_url = "${FT_HOME_URL:-}"
home_label = "${FT_HOME_LABEL:-}"
repository_url = "${FT_REPOSITORY_URL:-}"

[tools]
python = "python3"

[database]
host = "${FT_DB_HOST:-mysql}"
port = ${FT_DB_PORT:-3306}
user = "${FT_DB_USER:-tracker}"
password = "${FT_DB_PASSWORD}"
tracker = "${FT_DB_TRACKER:-forever_tracker}"
world = "${FT_DB_WORLD:-world}"
hotfixes = "${FT_DB_HOTFIXES:-hotfixes}"
auth = "${FT_DB_AUTH:-auth}"

[build]
database = "${FT_BUILD_DB:-ft_world_build}"
user = "${FT_BUILD_USER:-}"
password = "${FT_BUILD_PASSWORD:-}"

[server]
root = "$SERVER_DATA"
dbc = "dbc/$LOCALE"
maps = "maps"
vmaps = "vmaps"
mmaps = "mmaps"
build = ${FT_BUILD:-0}
build_file = ""
mysql = "/usr/bin/mysql"

[console]
host = "${FT_RA_HOST:-}"
port = ${FT_RA_PORT:-3443}
user = "${FT_RA_USER:-}"
password = "${FT_RA_PASSWORD:-}"

[client]
path = ""

[forge]
trainer_skip_ids = "${FT_FORGE_TRAINER_SKIP_IDS:-}"
trainer_guess = ${FT_FORGE_TRAINER_GUESS:-1}

[icyveins]
max = ${FT_ICYVEINS_MAX:-20000}

[atlasloot]
guess = ${FT_ATLASLOOT_GUESS:-1}

[norgannondb]
commit = "${FT_NORGANNONDB_COMMIT:-}"

[wowhead]
branch = "${FT_WOWHEAD_BRANCH:-forever}"
pause = ${FT_WOWHEAD_PAUSE:-0.4}
analyse = ${FT_WOWHEAD:-1}
recheck_days = ${FT_WOWHEAD_RECHECK_DAYS:-7}

[collector]
auto_apply = 0

[phases]
file = "${FT_PHASES_FILE:-}"
current = "${FT_PHASE:-}"

[admin]
gm_level = ${FT_GM_LEVEL:-3}
vendor_entry = ${FT_VENDOR_ENTRY:-0}

[admins]
$admins
EOF
chown root:www-data "$CONFIG"
chmod 640 "$CONFIG"
umask 022
chown www-data:www-data "$DATA"
say "config.ini written (database ${FT_DB_USER:-tracker}@${FT_DB_HOST:-mysql}, world ${FT_DB_WORLD:-world}, hotfixes ${FT_DB_HOTFIXES:-hotfixes})"

# no import survives a restart: a lock left by one would grey out its button
rm -f "$DATA"/source-*.running

as_www() { setpriv --reuid=www-data --regid=www-data --init-groups -- "$@"; }

# The first analysis (and a new snapshot each time the server moves to another client build), in the background so
# the website is up at once. It writes the log the Forge's "Run again" reads, so the site shows it running.
first_run() {
    cnf="$(mktemp)"
    printf '[client]\nhost=%s\nport=%s\nuser=%s\npassword="%s"\n' "${FT_DB_HOST:-mysql}" "${FT_DB_PORT:-3306}" \
        "${FT_DB_USER:-tracker}" "$FT_DB_PASSWORD" > "$cnf"
    tries=0
    until mysql --defaults-extra-file="$cnf" -N -e 'SELECT 1' >/dev/null 2>&1; do
        tries=$((tries + 1))
        if [ "$tries" -ge 60 ]; then
            say "MySQL at ${FT_DB_HOST:-mysql} still unreachable after 5 minutes: no analysis this start"
            mysql --defaults-extra-file="$cnf" -N -e 'SELECT 1' 2>&1 | sed 's/^/[forever-tracker] /' || true
            rm -f "$cnf"; return
        fi
        sleep 5
    done
    build="${FT_BUILD:-0}"
    if [ "$build" = "0" ]; then
        build="$(mysql --defaults-extra-file="$cnf" -N -e "SELECT COALESCE(MAX(gamebuild), 0) FROM \`${FT_DB_AUTH:-auth}\`.realmlist" 2>/dev/null || echo 0)"
    fi
    rm -f "$cnf"
    if [ -z "$build" ] || [ "$build" = "0" ]; then
        say "client build unknown (set FT_BUILD, or the user needs SELECT on ${FT_DB_AUTH:-auth}.realmlist): no analysis"; return
    fi
    languages="${FT_LANGUAGES:-en,fr}"
    # Bumped when a new image analyses differently (2: "new in Forever" against the Classic Era client; 3: trainer fixes
    # skip talents and FT_FORGE_TRAINER_SKIP_IDS, which is part of the marker too; 4: Wowhead checks new items and
    # trainer spells; 5: every item players cannot get, Season of Discovery ones included; 6: items
    # Wowhead does not know stay visible, creature checks; 7: release phases, the phase list's checksum is part of the marker; 8: Season of Discovery
    # instances and their bosses go to Internal / test; 9: bosses counted once and found when a script summons them,
    # battlegrounds, flight points nobody flies from, placeholder mounts; 10: what the core's scripts summon counts as
    # present, quest text is checked, real names no longer read as test names): the stored
    # analysis is then redone once at the next start.
    # the phase list's contents count, not only its name: a new image may ship new dates or raids
    phases_file="${FT_PHASES_FILE:-tools/phases/forever.json}"
    case "$phases_file" in none) ;; /*) ;; *) phases_file="$ROOT/$phases_file" ;; esac
    phases_sum="$( [ -f "$phases_file" ] && sha1sum "$phases_file" | cut -c1-12 || echo "$phases_file")"
    marker="$languages analysis=10 phases=$phases_sum skip=${FT_FORGE_TRAINER_SKIP_IDS:-} guess=${FT_FORGE_TRAINER_GUESS:-1}"
    if [ -d "$DATA/builds/$build" ]; then
        if [ "$(cat "$DATA/languages" 2>/dev/null || true)" != "$marker" ]; then
            say "languages or analysis changed ($marker): analysing again"
        elif [ "${FT_ANALYSE_ON_START:-new-build}" != "always" ]; then
            say "build $build already stored: no analysis at start (the Forge's Run again, or FT_ANALYSE_ON_START=always)"; return
        fi
        steps="analyse"
    else
        client_dbc="${FT_CLIENT_DBC:-$SERVER_DATA/dbc}"
        if [ ! -f "$client_dbc/$LOCALE/SpellName.db2" ] && [ ! -f "$client_dbc/SpellName.db2" ]; then
            say "no official DB2 files in $client_dbc (SpellName.db2): mount them or set FT_CLIENT_DBC"; return
        fi
        steps="snapshot analyse"
    fi
    [ "${FT_LOCATE:-1}" = "1" ] && steps="$steps locate"
    log="$DATA/analysis.log"
    for step in $steps; do
        date +%s > "$DATA/analysis.state"; chown www-data:www-data "$DATA/analysis.state"
        : > "$log"; chown www-data:www-data "$log"
        say "build $build: $step (log in data/analysis.log)"
        case "$step" in
            snapshot) set -- snapshot --dbc "$client_dbc" --build "$build" --locale "$LOCALE" --source container ;;
            analyse) if [ "${FT_WOWHEAD:-1}" = "1" ]; then set -- analyse --wowhead; else set -- analyse; fi ;;
            *) set -- "$step" ;;
        esac
        if as_www python3 -X utf8 -u "$ROOT/tools/tracker.py" "$@" >> "$log" 2>&1; then ok=1; else ok=0; fi
        echo FT-END >> "$log"
        tail -n 3 "$log" | sed 's/^/[forever-tracker]   /'
        if [ "$ok" = "0" ]; then say "$step failed: stopping here (full log: data/analysis.log)"; return; fi
        [ "$step" = "analyse" ] && echo "$marker" > "$DATA/languages"
    done
    say "build $build: done"
}

if [ "${FT_ANALYSE_ON_START:-new-build}" != "never" ]; then
    first_run &
fi

# AtlasLoot Classic Forever is updated almost daily on CurseForge: every FT_ATLASLOOT_EVERY_HOURS (0 = never) the
# newest file is checked and, when it is new, imported as a card for the last analysis' gaps (nothing is applied). The
# import waits by itself while an analysis runs; a lock younger than 15 minutes is a run still going (the website's).
atlasloot_watch() {
    case "${FT_ATLASLOOT_EVERY_HOURS:-6}" in ''|*[!0-9]*|?????*) say "FT_ATLASLOOT_EVERY_HOURS must be a whole number up to 9999: no AtlasLoot check"; return ;; esac
    hours="$(expr "${FT_ATLASLOOT_EVERY_HOURS:-6}" + 0 || true)"   # expr exits 1 when the sum is 0
    if [ "$hours" -eq 0 ]; then say "FT_ATLASLOOT_EVERY_HOURS=0: no AtlasLoot check"; return; fi
    log="$DATA/source-atlasloot.log"
    sleep 900
    while :; do
        nap=$((hours * 3600))
        if [ -z "$(find "$DATA" -maxdepth 1 -name source-atlasloot.running -mmin -15 2>/dev/null)" ]; then
            if as_www sh -c 'php "$1" atlasloot --if-new > "$2" 2>&1' sh "$ROOT/tools/source-import.php" "$log"; then rc=0; else rc=$?; fi
            tail -n 1 "$log" 2>/dev/null | sed 's/^/[forever-tracker] AtlasLoot: /'
            [ "$rc" -eq 3 ] && nap=900   # an analysis was running: again in 15 minutes
        else
            nap=900                       # the website's import is running
        fi
        sleep "$nap"
    done
}
atlasloot_watch &

exec docker-php-entrypoint "$@"
