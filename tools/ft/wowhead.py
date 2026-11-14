"""Wowhead's public Forever tooltip service (the one its tooltip script uses), politely: one request at a
time, a pause between requests, and every answer cached on disk so a resource is only asked for once.

    wh = Wowhead()
    wh.get('npc', 1365)   -> {'name': 'Goli Krumn', 'map': {'zone': 1537, 'coords': {'0': [[29.2, 60.0], ...]}}, ...}

Answers are kept in data/wowhead/<kind>/<id>.json; {"missing": true} records a resource Wowhead does not know.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from .config import CONFIG, DATA

URL = 'https://nether.wowhead.com/{branch}/tooltip/{kind}/{id}?locale={locale}'
AGENT = 'ForeverTracker/1.1 (private server admin tool; https://github.com/filinodz/ForeverTracker)'


GIVE_UP_AFTER = 10   # lookups in a row that could not be reached: Wowhead is down or has blocked us, stop asking


def save_json(path, data, **options):
    """Writes a JSON file whole or not at all: a restart in the middle of a write must not leave half a cache, which
    would stop every later analysis at the first read."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    scratch = f'{path}.{os.getpid()}.tmp'
    with open(scratch, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, **options)
    os.replace(scratch, path)


def load_json(path, default):
    """A JSON file, or `default` when it is missing or cut short (an older version's unfinished write)."""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def recheck_days():
    return float(CONFIG.get('wowhead', 'recheck_days', '7') or 7)


def refresh_days():
    """How long an answer is believed before it is asked again ([wowhead] refresh_days; 0: for good). Wowhead corrects a
    level, moves a spawn point, drops a "may not be in WoW: Forever" note: an answer kept for good never learns it."""
    try:
        return max(0.0, float(CONFIG.get('wowhead', 'refresh_days', '30') or 0))
    except ValueError:
        return 30.0


def spread(entity_id):
    """Between 0.75 and 1.25, fixed for an id: answers fetched in one run do not all come due on the same day."""
    return 0.75 + (int(entity_id or 0) * 2654435761 % 1000) / 2000


REFRESH_FILE = os.path.join(DATA, 'sources-refresh')
_epoch = None


def refresh_epoch():
    """The moment "ask every source again" was pressed (data/sources-refresh, a Unix time; app/wowhead.php writes it):
    every answer older than that is asked again, whatever its age. 0 when it never was."""
    global _epoch
    if _epoch is None:
        try:
            with open(REFRESH_FILE, encoding='utf-8') as handle:
                _epoch = float(handle.read().strip() or 0)
        except (OSError, ValueError):
            _epoch = 0.0
    return _epoch


def is_stale(fetched, missing, entity_id=0, now=None, epoch=None, refresh=None, recheck=None):
    """An answer fetched at `fetched` is to be asked again: it is older than the last "ask every source again"; or it
    is "Wowhead does not know it" and older than [wowhead] recheck_days (Wowhead learns what players discover); or it
    is an answer older than [wowhead] refresh_days, give or take a quarter by id."""
    now = time.time() if now is None else now
    epoch = refresh_epoch() if epoch is None else epoch
    if fetched < epoch:
        return True
    age = now - fetched
    if missing:
        return age > (recheck_days() if recheck is None else recheck) * 86400
    days = refresh_days() if refresh is None else refresh
    return days > 0 and age > days * 86400 * spread(entity_id)


class Wowhead:
    def __init__(self, refresh=False, pause=None):
        self.branch = CONFIG.get('wowhead', 'branch', 'forever') or 'forever'
        self.pause = float(pause if pause is not None else CONFIG.get('wowhead', 'pause', '0.4') or 0.4)
        self.refresh = refresh
        self.folder = os.path.join(DATA, 'wowhead')
        self.requests = 0
        self.reasked = 0       # answers that were on disk and were asked again
        self.changed = 0       # ... and came back different
        self.unreached = 0     # lookups in a row without an answer
        self.gave_up = False   # too many of them: the rest of this run uses the cache only
        self._last = 0.0

    def npc(self, entity_id, ask):
        """An NPC's tooltip data with 'facts' (level, type, rank); an answer cached before facts were kept is asked again."""
        data = self.cached('npc', entity_id)
        if data is not None and (not ask or ((data.get('missing') or 'facts' in data) and not self.stale(data, entity_id))):
            return data
        if not ask:
            return None
        refresh, self.refresh = self.refresh, True
        try:
            return self.get('npc', entity_id)
        finally:
            self.refresh = refresh

    def path(self, kind, entity_id):
        return os.path.join(self.folder, kind, f'{int(entity_id)}.json')

    def cached(self, kind, entity_id):
        data = load_json(self.path(kind, entity_id), {})
        return data or None

    def stale(self, data, entity_id=0):
        """The answer on disk is to be asked again (is_stale): too old for what it says, or older than the last "ask
        every source again"."""
        return bool(data) and is_stale(data.get('fetched', 0), bool(data.get('missing')), entity_id)

    def summary(self):
        """"N answer(s) asked again, M changed" for the log, or '' when none was."""
        return f'{self.reasked} answer(s) asked again, {self.changed} changed' if self.reasked else ''

    def get(self, kind, entity_id, locale=0):
        """The tooltip data, {'missing': True} when Wowhead does not know it; when it cannot be reached, the last
        answer kept on disk, else None. After GIVE_UP_AFTER lookups in a row without an answer the run stops asking."""
        cached = self.cached(kind, entity_id)
        if not self.refresh and cached is not None and not self.stale(cached, entity_id):
            return cached
        if self.gave_up:
            return cached   # an old answer is better than none
        data = self._fetch(kind, entity_id, locale)
        self.unreached = 0 if data is not None else self.unreached + 1
        if self.unreached >= GIVE_UP_AFTER:
            self.gave_up = True
            print(time.strftime('%H:%M:%S'), f'wowhead: {GIVE_UP_AFTER} lookups in a row got no answer (down, or it has blocked this address): '
                  'no more lookups in this run, the cache is used. Run the analysis again later.', flush=True)
        if data is None:
            return cached
        if kind == 'npc' and data.get('tooltip'):
            data['facts'] = npc_facts(data['tooltip'])
        data.pop('tooltip', None) if kind in ('npc', 'object') else None
        if cached is not None:
            self.reasked += 1
            same = lambda d: {k: v for k, v in d.items() if k != 'fetched'}
            self.changed += same(cached) != same(data)
        data['fetched'] = int(time.time())
        save_json(self.path(kind, entity_id), data, separators=(',', ':'))
        return data

    def _fetch(self, kind, entity_id, locale):
        url = URL.format(branch=self.branch, kind=kind, id=int(entity_id), locale=locale)
        for attempt in range(4):
            wait = self.pause - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.requests += 1
            try:
                request = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.loads(response.read().decode('utf-8'))
                if not data or data.get('error') or not data.get('name'):
                    return {'missing': True}
                return data
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return {'missing': True}
                if error.code in (429, 503):
                    time.sleep(5 * (attempt + 1))  # asked to slow down
                    continue
                return None
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                time.sleep(2 * (attempt + 1))
        return None


# Wowhead's Forever tooltips end with this line for what Season of Discovery added and Forever may not have.
SEASON_NOTE = 'May not be in WoW: Forever'


def verdict(data):
    """'unknown' (Wowhead's Forever database lacks it), 'season' (marked as a Season of Discovery leftover),
    'forever', or None when Wowhead could not be asked."""
    if data is None:
        return None
    if data.get('missing'):
        return 'unknown'
    return 'season' if SEASON_NOTE in (data.get('tooltip') or '') else 'forever'


# "Level 30 Humanoid (Normal)", "Level 24 - 25 Beast (Elite)", "Level ?? Dragonkin (Boss)"
NPC_LINE = re.compile(r'Level\s+(\?\?|\d+)(?:\s*-\s*(\d+))?\s+(.*?)\s*\((Normal|Elite|Rare Elite|Rare|Boss)\)')
# creature_template.Classification
RANKS = {'Normal': 0, 'Elite': 1, 'Rare Elite': 2, 'Boss': 3, 'Rare': 4}


def npc_facts(tooltip):
    """{'min', 'max', 'type', 'rank'} from an NPC tooltip (levels None for "??"), or None when the line is not there."""
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tooltip or ''))
    m = NPC_LINE.search(text)
    if not m:
        return None
    low = None if m.group(1) == '??' else int(m.group(1))
    high = int(m.group(2)) if m.group(2) else low
    return {'min': low, 'max': high, 'type': m.group(3).strip(), 'rank': RANKS[m.group(4)]}
