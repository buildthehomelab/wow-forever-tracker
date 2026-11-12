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


class Wowhead:
    def __init__(self, refresh=False, pause=None):
        self.branch = CONFIG.get('wowhead', 'branch', 'forever') or 'forever'
        self.pause = float(pause if pause is not None else CONFIG.get('wowhead', 'pause', '0.4') or 0.4)
        self.refresh = refresh
        self.folder = os.path.join(DATA, 'wowhead')
        self.requests = 0
        self._last = 0.0

    def npc(self, entity_id, ask):
        """An NPC's tooltip data with 'facts' (level, type, rank); an answer cached before facts were kept is asked again."""
        data = self.cached('npc', entity_id)
        if data is not None and ((data.get('missing') and not (ask and self.stale(data))) or 'facts' in data or not ask):
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
        path = self.path(kind, entity_id)
        if os.path.isfile(path):
            try:
                return json.load(open(path, encoding='utf-8'))
            except ValueError:
                return None
        return None

    def stale(self, data):
        """A "Wowhead does not know it" answer older than [wowhead] recheck_days: Wowhead learns what players discover."""
        days = float(CONFIG.get('wowhead', 'recheck_days', '7') or 7)
        return bool(data and data.get('missing') and time.time() - data.get('fetched', 0) > days * 86400)

    def get(self, kind, entity_id, locale=0):
        """The tooltip data, {'missing': True} when Wowhead does not know it, None when it could not be reached."""
        if not self.refresh:
            data = self.cached(kind, entity_id)
            if data is not None and not self.stale(data):
                return data
        data = self._fetch(kind, entity_id, locale)
        if data is not None:
            if kind == 'npc' and data.get('tooltip'):
                data['facts'] = npc_facts(data['tooltip'])
            data.pop('tooltip', None) if kind in ('npc', 'object') else None
            data['fetched'] = int(time.time())
            os.makedirs(os.path.dirname(self.path(kind, entity_id)), exist_ok=True)
            with open(self.path(kind, entity_id), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(',', ':'))
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
