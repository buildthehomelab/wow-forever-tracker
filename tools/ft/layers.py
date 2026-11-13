"""The world build's layers and sources (tools/world/layers.json), and the lock that pins each source's version.

A source belongs to one layer, one witness group and one use:
- `public`: rows made from it may be published (its licence allows it, with its credit line);
- `private`: its values may only reach your own server; it still counts as a witness;
- `reference`: it never gives a row or a value; it only confirms what another source says.

Two sources of one witness group are one witness: the group says whose observations the data really is. A source
compiled from several others lists their groups in `also`.

This module reads no configuration and no database, so it can be imported and tested alone.
"""
import datetime
import fnmatch
import hashlib
import json
import os
import re
import urllib.request

REGISTRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'world', 'layers.json')
USES = ('public', 'private', 'reference')            # from the least to the most restricted
# licences whose rows may be published in a GPL-3.0 data repository, with their credit
PUBLISHABLE = {'GPL-2.0-or-later', 'GPL-3.0', 'CC-BY-4.0', 'MIT', 'game data', 'own'}
# pin type: the fields it needs
PIN_TYPES = {'github-branch': ('repo',), 'github-release': ('repo', 'tag'), 'curseforge': ('project',), 'wago-build': ('product',),
             'url': ('url',), 'replay': (), 'none': ()}
USER_AGENT = 'ForeverTracker (world build)'


class RegistryError(ValueError):
    pass


class Registry:
    def __init__(self, data):
        problems = validate(data)
        if problems:
            raise RegistryError('; '.join(problems))
        self.layers = data['layers']
        self.sources = {source['id']: source for source in data['sources']}
        self.order = {layer['key']: rank for rank, layer in enumerate(self.layers)}
        self.live_from = int(data.get('live_from') or 0)

    def source(self, source_id):
        if source_id not in self.sources:
            raise KeyError(f'unknown source {source_id!r}')
        return self.sources[source_id]

    def rank(self, source_id):
        """Position of the source's layer: a higher layer is asked first."""
        return self.order[self.source(source_id)['layer']]

    def groups(self, source_id):
        """The witness groups a source belongs to: its own, and those of the sources it is compiled from (`also`)."""
        source = self.source(source_id)
        return {source['group'], *source.get('also', [])}

    def witnesses(self, source_ids):
        """How many independent witnesses the sources are. Sources that share a witness group are one witness, and so
        are two sources that each share a group with a third."""
        merged = []
        for groups in (self.groups(s) for s in source_ids):
            for other in [m for m in merged if m & groups]:
                merged.remove(other)
                groups = groups | other
            merged.append(groups)
        return len(merged)

    def witness(self, source_id, part='', build=0):
        """(witness group, recorded on live Forever?) of what a source states.

        A source made of parts that weigh differently says so in `parts`: players' recordings are live, a generated
        list or a hand correction is not, and a part may belong to another witness group than its source (a list
        built from another site's pages is that site's word). A part written "name:detail" is looked up by its name.
        Without parts, a source that says its facts are recordings of play (`recorded`) is live when the fact comes
        from a build of the live game (`live_from` and later); a fact without a build is not, and no other source is."""
        source = self.source(source_id)
        about = (source.get('parts') or {}).get(str(part).partition(':')[0])
        if about is not None:
            return about.get('group', source['group']), about.get('live') is True
        if source.get('parts'):
            return source['group'], False
        return source['group'], source.get('recorded') is True and self.live_from > 0 and bool(build) and build >= self.live_from

    def trusted(self, source_id, part=''):
        """Whether this source's word (or this part's) is enough by itself: marked `trusted` in the registry. That is
        a judgement about a source's record, written down where it can be read and changed, not something worked out."""
        source = self.source(source_id)
        if source.get('parts'):          # a source made of parts is trusted part by part: a part nobody described is not
            about = source['parts'].get(str(part).partition(':')[0])
            return about is not None and about.get('trusted') is True
        return source.get('trusted') is True

    def use(self, source_ids):
        """The most restricted use among the sources that set a value: `public`, `private` or `reference`."""
        uses = [USES.index(self.source(s)['use']) for s in source_ids]
        return USES[max(uses)] if uses else 'reference'

    def publishable(self, value_sources):
        """True when a row whose values come from these sources may go into the public data repository."""
        return bool(value_sources) and self.use(value_sources) == 'public'

    def credits(self, source_ids):
        """Credit lines of the sources, in the registry's order, each once."""
        wanted = {self.source(s)['id'] for s in source_ids}
        return [s['credit'] for s in self.sources.values() if s['id'] in wanted and s.get('credit')]


def validate(data):
    """Problems of a registry, as sentences; an empty list when it is sound."""
    problems = []
    if not isinstance(data, dict) or not isinstance(data.get('layers'), list) or not isinstance(data.get('sources'), list):
        return ['the registry needs a list of layers and a list of sources']
    live_from = data.get('live_from')
    if not isinstance(live_from, int) or isinstance(live_from, bool) or live_from <= 0:
        problems.append('live_from must be the first client build of the live game')
    layer_keys = [layer.get('key') if isinstance(layer, dict) else None for layer in data['layers']]
    if len(set(layer_keys)) != len(layer_keys) or not all(layer_keys):
        problems.append('layers need distinct keys')
    seen = set()
    for source in data['sources']:
        if not isinstance(source, dict):
            problems.append('a source is not an object')
            continue
        sid = source.get('id') or '?'
        if sid in seen:
            problems.append(f'{sid}: listed twice')
        seen.add(sid)
        for field in ('id', 'name', 'layer', 'group', 'licence', 'use', 'pin'):
            if not source.get(field):
                problems.append(f'{sid}: no {field}')
        if source.get('layer') not in layer_keys:
            problems.append(f"{sid}: unknown layer {source.get('layer')!r}")
        if source.get('use') not in USES:
            problems.append(f"{sid}: use must be one of {', '.join(USES)}")
        elif source['use'] == 'public':
            if source.get('licence') not in PUBLISHABLE:
                problems.append(f"{sid}: licence {source.get('licence')!r} does not allow publishing its rows")
            elif source['licence'] not in ('game data', 'own') and not source.get('credit'):
                problems.append(f'{sid}: a published source needs its credit line')
        if not isinstance(source.get('also', []), list):
            problems.append(f'{sid}: also must be a list of witness groups')
        parts = source.get('parts', {})
        if not isinstance(parts, dict) or not all(isinstance(about, dict) for about in parts.values()):
            problems.append(f'{sid}: parts must name each part with its group and whether it is live')
        else:
            for name, about in parts.items():
                if not name or ':' in name:
                    problems.append(f'{sid}: a part is named without ":" ({name!r})')
                if not isinstance(about.get('live', False), bool):
                    problems.append(f'{sid}: part {name}: live is true or false')
                if not isinstance(about.get('trusted', False), bool):
                    problems.append(f'{sid}: part {name}: trusted is true or false')
                if not (isinstance(about.get('group', sid), str) and about.get('group', sid)):
                    problems.append(f'{sid}: part {name}: group is a name')
        if not isinstance(source.get('recorded', False), bool):
            problems.append(f'{sid}: recorded is true or false')
        if not isinstance(source.get('trusted', False), bool):
            problems.append(f'{sid}: trusted is true or false')
        elif source.get('use') == 'reference' and (source.get('trusted') or any(
                isinstance(about, dict) and about.get('trusted') for about in (parts.values() if isinstance(parts, dict) else ()))):
            problems.append(f'{sid}: a source that never gives a row cannot be trusted to give one')
        pin = source.get('pin')
        if not isinstance(pin, dict) or pin.get('type') not in PIN_TYPES:
            problems.append(f"{sid}: unknown pin type {pin.get('type') if isinstance(pin, dict) else pin!r}")
        else:
            problems.extend(f"{sid}: a {pin['type']} pin needs {field}" for field in PIN_TYPES[pin['type']] if not pin.get(field))
    return problems


def load(path=REGISTRY):
    with open(path, encoding='utf-8') as handle:
        return Registry(json.load(handle))


# ------------------------------------------------------------------ pins
def http_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def http_digest(url):
    """(sha256, bytes) of what the address serves."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    digest, size = hashlib.sha256(), 0
    with urllib.request.urlopen(request, timeout=60) as response:
        for chunk in iter(lambda: response.read(1 << 16), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _build_number(version):
    """The build of a client version: its last number ('1.60.1.70938' and '1.60.1.70938-ptr' are 70938). A version
    with fewer than four numbers has none (-1)."""
    numbers = re.findall(r'\d+', str(version))
    return int(numbers[-1]) if len(numbers) >= 4 else -1


def resolve(pin, fetch_json=http_json, fetch_digest=http_digest):
    """The newest version of a source: {'version': ..., ...} or None when the pin type has nothing to look up.

    `fetch_json(url)` and `fetch_digest(url)` are the only network access, so tests pass their own.
    """
    kind = pin.get('type')
    if kind == 'github-branch':
        commit = fetch_json(f"https://api.github.com/repos/{pin['repo']}/commits/{pin.get('branch') or 'HEAD'}")
        return {'version': commit['sha'], 'date': (commit.get('commit', {}).get('committer') or {}).get('date', '')}
    if kind == 'github-release':
        release = fetch_json(f"https://api.github.com/repos/{pin['repo']}/releases/tags/{pin['tag']}")
        assets = [a for a in release.get('assets', []) if fnmatch.fnmatch(a.get('name', ''), pin.get('asset', '*'))]
        if not assets:
            raise LookupError(f"{pin['repo']} {pin['tag']}: no asset named {pin.get('asset', '*')}")
        asset = max(assets, key=lambda a: a.get('updated_at', ''))
        # the file's date is part of the version: some releases rebuild a file under the same name
        return {'version': f"{asset['name']}@{asset.get('updated_at', '')}", 'file': asset['name'], 'date': asset.get('updated_at', ''),
                'url': asset.get('browser_download_url', ''), 'size': asset.get('size', 0)}
    if kind == 'curseforge':
        listing = fetch_json(f"https://www.curseforge.com/api/v1/mods/{pin['project']}/files")
        files = [f for f in listing.get('data', []) if str(f.get('fileName', '')).startswith(pin.get('name', ''))]
        if not files:
            raise LookupError(f"CurseForge project {pin['project']}: no file named {pin.get('name', '')}*")
        newest = max(files, key=lambda f: f.get('id', 0))
        return {'version': str(newest['id']), 'file': newest.get('fileName', ''), 'date': newest.get('dateCreated', '')}
    if kind == 'wago-build':
        builds = fetch_json('https://wago.tools/api/builds').get(pin['product'], [])
        if not builds:
            raise LookupError(f"wago.tools: no build of {pin['product']}")
        newest = max(builds, key=lambda b: _build_number(b.get('version', '')))
        if _build_number(newest.get('version', '')) < 0:
            raise LookupError(f"wago.tools: no build number in the versions of {pin['product']}")
        return {'version': newest['version'], 'date': newest.get('created_at', '')}
    if kind == 'url':
        digest, size = fetch_digest(pin['url'])
        return {'version': digest[:16], 'sha256': digest, 'size': size}
    return None


def pin_all(registry, previous=None, only=None, fetch_json=http_json, fetch_digest=http_digest, now=None):
    """A new lock: every source's newest version. A source that cannot be reached keeps its previous pin, with the
    error noted; `only` limits the lookup to some source ids (the others keep their pins)."""
    previous = (previous or {}).get('sources', {})
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
    out = {}
    for sid, source in registry.sources.items():
        entry = dict(previous.get(sid) or {})
        if only is None or sid in only:
            entry.pop('error', None)
            try:
                found = resolve(source['pin'], fetch_json, fetch_digest)
            except Exception as error:  # one unreachable source must not lose the others' pins
                entry['error'] = f'{type(error).__name__}: {error}'[:200]
            else:
                if found is None:
                    entry = {}                  # nothing to pin (any more): no stale version stays behind
                elif found.get('version') != entry.get('version'):
                    entry = dict(found, pinned=stamp)
        entry.update(licence=source['licence'], use=source['use'], group=source['group'], layer=source['layer'])
        out[sid] = entry
    return {'written': stamp, 'sources': out}


def read_lock(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def write_lock(path, lock):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(lock, handle, indent=1, sort_keys=True)
        handle.write('\n')
    os.replace(temporary, path)


def changed(before, after):
    """Source ids whose pinned version differs between two locks."""
    old, new = (before or {}).get('sources', {}), (after or {}).get('sources', {})
    return sorted(sid for sid in new if new[sid].get('version') != (old.get(sid) or {}).get('version'))
