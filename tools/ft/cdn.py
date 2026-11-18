"""The official client's files straight from Blizzard's CDN, by file data id (the TACT protocol).

The tracker's official list is the client's own tables. Read only from the server's extracted copy, it is as old as
the build the server runs; Blizzard ships a new build every few weeks. This asks Blizzard's servers the way the
game's launcher does, with no game account and no install:

  version server   which build is live, and the CDN hosts            us.patch.battle.net:1119/<product>/versions
  build config     names the build's root and encoding files
  root             file data id -> content key (the MD5 of the file)
  encoding         content key -> encoded key (the name of the stored, compressed file)
  archive indexes  encoded key -> archive, offset, size
  archive          one ranged request for the file, stored as BLTE (zlib chunks, a few encrypted)

The first use of a build downloads its encoding file (about 190 MB) and its archive indexes (about 125 MB) and joins
them into <cache>/tact/<build config>.sqlite: a few minutes. After that a file is one lookup and one request. Every
file is checked against its content key, so a wrong byte anywhere above fails loudly.

Adapted from tools/tact/tact.py of wow-project-everlake (same authors).
"""
import bisect
import concurrent.futures
import hashlib
import http.client
import json
import os
import re
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
import zlib

VERSIONS = "http://us.patch.battle.net:1119/%s/%s"
KEYS = "https://raw.githubusercontent.com/wowdev/TACTKeys/master/WoW.txt"
# The keys Blizzard handed out by hotfix in any region, as wago.tools collects them from players' caches: a key can
# reach EU, Korea, Taiwan or China, or one uploader, before the US cache this tracker reads and before the list above.
WAGO_TABLE = "https://wago.tools/db2/%s/csv?product=%s"
UA = {"User-Agent": "ForeverTracker/1.3 (private server admin tool)"}
ENUS = 0x2  # root locale flag
LOW_VIOLENCE = 0x80  # root content flag: the censored copy of a file
NO_NAME_HASH = 0x10000000  # root content flag: the block has no name hashes
LOOSE = -1  # archive number of a file stored on its own
PAUSE = 3   # seconds before the hosts are asked a second time for a file none of them gave


class Encrypted(Exception):
    """A file (or part of one) under a key nobody has published: unreleased content."""


class Gone(RuntimeError):
    """The CDN says it does not have the file (403, 404): a build long replaced is taken off, host by host."""


def get(url, headers=None, tries=5):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}),
                                        timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            if getattr(e, "code", 0) in (403, 404):
                raise Gone("%s: %s" % (url, e))
            if attempt == tries - 1:
                raise RuntimeError("%s: %s" % (url, e))
            time.sleep(1 + 2 * attempt)


# --- BLTE --------------------------------------------------------------------------------------

def salsa20(key, nonce, data):
    """Salsa20/20 with a 16-byte key and an 8-byte nonce, as TACT uses it."""
    c = struct.unpack("<4I", b"expand 16-byte k")
    k = struct.unpack("<4I", key)
    n = struct.unpack("<2I", nonce)
    mask, stream = 0xFFFFFFFF, bytearray()
    for block in range((len(data) + 63) // 64):
        s = (c[0], k[0], k[1], k[2], k[3], c[1], n[0], n[1], block & mask, block >> 32,
             c[2], k[0], k[1], k[2], k[3], c[3])
        x = list(s)
        for _ in range(10):
            for a, b, e, d in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11),
                               (0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
                t = (x[a] + x[d]) & mask
                x[b] ^= (t << 7 | t >> 25) & mask
                t = (x[b] + x[a]) & mask
                x[e] ^= (t << 9 | t >> 23) & mask
                t = (x[e] + x[b]) & mask
                x[d] ^= (t << 13 | t >> 19) & mask
                t = (x[d] + x[e]) & mask
                x[a] ^= (t << 18 | t >> 14) & mask
        stream += struct.pack("<16I", *((x[i] + s[i]) & mask for i in range(16)))
    return bytes(a ^ b for a, b in zip(data, stream))


def blte_chunk(chunk, index, keys, absent=None, plain_size=None):
    """One chunk decoded. absent: a list; with it, a chunk under a key nobody has published becomes plain_size zero
    bytes (as the game's own tools leave it) and its key name is added to the list, instead of raising Encrypted."""
    mode = chunk[:1]
    if mode == b"N":
        return chunk[1:]
    if mode == b"Z":
        return zlib.decompress(chunk[1:])
    if mode == b"F":
        return blte(chunk[1:], keys, absent)
    if mode == b"E":
        n = chunk[1]
        name = chunk[2:2 + n][::-1].hex().upper()
        iv_size = chunk[2 + n]
        iv = bytearray(chunk[3 + n:3 + n + iv_size].ljust(8, b"\0"))
        kind = chunk[3 + n + iv_size:4 + n + iv_size]
        key = keys.get(name) if keys else None
        if key is None:
            if absent is not None and plain_size is not None:
                absent.append(name)
                return bytes(plain_size)
            raise Encrypted(name)
        if kind != b"S":
            raise ValueError("BLTE cipher %r" % kind)
        for k in range(4):  # each chunk has its own nonce: the file's, mixed with the chunk number
            iv[k] ^= (index >> (8 * k)) & 0xFF
        return blte_chunk(salsa20(key, bytes(iv), chunk[4 + n + iv_size:]), index, keys, absent, plain_size)
    raise ValueError("BLTE chunk mode %r" % mode)


def blte(data, keys=None, absent=None):
    """Decode a stored file. keys: {key name: 16 bytes} for the encrypted chunks. absent: see blte_chunk (the chunk
    table gives each chunk's plain size, so a chunk that cannot be read still takes its place)."""
    if data[:4] != b"BLTE":
        raise ValueError("not a BLTE file")
    header = struct.unpack_from(">I", data, 4)[0]
    if not header:
        return blte_chunk(data[8:], 0, keys)
    flags, count = data[8], int.from_bytes(data[9:12], "big")
    entry = 40 if flags & 0x10 else 24
    out, at = [], header
    for i in range(count):
        size, plain = struct.unpack_from(">II", data, 12 + i * entry)
        out.append(blte_chunk(data[at:at + size], i, keys, absent, plain))
        at += size
    return b"".join(out)


# --- tables ------------------------------------------------------------------------------------

def table(text):
    """A version server answer: rows of a pipe-separated table as dicts."""
    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    head = [h.split("!")[0] for h in lines[0].split("|")]
    return [dict(zip(head, l.split("|"))) for l in lines[1:]]


def config(text):
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition(" = ")
        if sep:
            out[key] = value.split()
    return out


def encoding_entries(data):
    """(content key, encoded key) for every file of the build."""
    if data[:2] != b"EN":
        raise ValueError("not an encoding file")
    _ver, ckey_size, ekey_size, page_kb, _epage_kb, pages, _epages, _unk, espec = struct.unpack_from(
        ">BBBHHIIBI", data, 2)
    at = 22 + espec + pages * (ckey_size + 16)
    for p in range(pages):
        o, end = at + p * page_kb * 1024, at + (p + 1) * page_kb * 1024
        while o + 6 + ckey_size <= end and data[o]:
            count = data[o]
            yield data[o + 6:o + 6 + ckey_size], data[o + 6 + ckey_size:o + 6 + ckey_size + ekey_size]
            o += 6 + ckey_size + count * ekey_size


def index_entries(data):
    """(encoded key, size, offset) of an archive index; a loose file index has offset 0."""
    _ver, _a, _b, block_kb, off_size, size_size, key_size, sum_size, count = struct.unpack_from(
        "<8BI", data, len(data) - 20)
    if key_size != 16 or size_size != 4 or off_size not in (0, 4) or sum_size != 8:
        raise ValueError("unknown archive index layout")
    entry, block = key_size + size_size + off_size, block_kb * 1024
    fmt = ">16sII" if off_size else ">16sI"
    for b in range((len(data) - 28) // (block + key_size + sum_size)):
        usable = block - block % entry
        for row in struct.iter_unpack(fmt, data[b * block:b * block + usable]):
            if not count:
                return
            if row[0] == bytes(16):
                break
            count -= 1
            yield row if off_size else (row[0], row[1], 0)


def root_entries(data):
    """(file data id, content key) for the enUS files, the uncensored copy first."""
    if data[:4] != b"TSFM":
        raise ValueError("not a root file")
    # Since 10.1.7 the header starts with its own size and a version; before, with the counts.
    first, second = struct.unpack_from("<II", data, 4)
    if first < 100:
        at, version = first, second
        total, named = struct.unpack_from("<II", data, 12)
    else:
        at, version, total, named = 12, 1, first, second
    blocks = []
    while at < len(data):
        if version >= 2:
            count, locale, f1, f2, f3 = struct.unpack_from("<IIIIB", data, at)
            flags, at = f1 | f2 | (f3 << 17), at + 17
        else:
            count, flags, locale = struct.unpack_from("<III", data, at)
            at += 12
        blocks.append((flags, locale, count, at))
        at += count * 20
        if not (total != named and flags & NO_NAME_HASH):
            at += count * 8
    if at != len(data):
        raise ValueError("root file layout not understood (version %d)" % version)
    for flags, locale, count, at in sorted(blocks, key=lambda b: bool(b[0] & LOW_VIOLENCE)):
        if not locale & ENUS:
            continue
        fdid = -1
        for i, delta in enumerate(struct.unpack_from("<%di" % count, data, at)):
            fdid += delta + 1
            yield fdid, data[at + count * 4 + i * 16:at + count * 4 + i * 16 + 16]


# --- a build -----------------------------------------------------------------------------------

class Tact:
    def __init__(self, cache, product="wowf", refresh=False, log=print):
        self.dir = os.path.join(cache, "tact")
        self.log = log
        self.product = product
        os.makedirs(self.dir, exist_ok=True)
        pin = os.path.join(self.dir, "build.txt")
        if refresh or not os.path.exists(pin):
            v = next(r for r in table(get(VERSIONS % (product, "versions")).decode()) if r["Region"] == "us")
            c = next(r for r in table(get(VERSIONS % (product, "cdns")).decode()) if r["Name"] == "us")
            with open(pin, "w") as f:
                f.write("\n".join((v["BuildConfig"], v["CDNConfig"], v["VersionsName"], c["Path"], c["Hosts"])) + "\n")
        self.build, self.cdn, self.version, self.path, hosts = open(pin).read().splitlines()[:5]
        self.hosts = hosts.split()
        self.lock = threading.Lock()
        self.keys = None
        self.extra_keys = {}   # {key name: 16 bytes} from another source than the published list (Blizzard's hotfixes)
        self.absent = {}   # file data id -> names of the keys its unreadable parts are under (read(partial=True))
        db = os.path.join(self.dir, self.build + ".sqlite")
        if not os.path.exists(db):
            self.index(db)
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.archives = [r[0] for r in self.db.execute("SELECT hash FROM archives ORDER BY id")]

    def url(self, kind, name, suffix="", host=None):
        return "http://%s/%s/%s/%s/%s/%s%s" % (host or self.hosts[0], self.path, kind, name[:2], name[2:4], name, suffix)

    def fetch(self, kind, name, suffix="", headers=None):
        """A CDN file (or the part of it the headers ask for) from the first host that gives it. The hosts do not all
        keep an old build's files, one that says "not here" may say otherwise a moment later, and one of them closes
        the line on some parts of some archives: each is asked twice before the file counts as gone or out of reach,
        and the host that answered is asked first from then on."""
        last = None
        for again in range(2):
            for host in list(self.hosts):
                try:
                    data = get(self.url(kind, name, suffix, host), headers, tries=1)
                    if host != self.hosts[0]:
                        self.hosts = [host] + [other for other in self.hosts if other != host]
                    return data
                except Gone as e:
                    last = last if isinstance(last, RuntimeError) and not isinstance(last, Gone) else e
                except RuntimeError as e:
                    last = e
            if not again:
                time.sleep(PAUSE)
        raise last

    def stored(self, kind, name, suffix=""):
        """A whole CDN file, kept in the cache."""
        path = os.path.join(self.dir, kind, name + suffix)
        if os.path.exists(path):
            return open(path, "rb").read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = self.fetch(kind, name, suffix)
        tmp = "%s.%d.part" % (path, threading.get_ident())
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return data

    def index(self, path):
        """Build the lookup database of this build: file data id -> where its bytes are."""
        log = self.log
        log("tact: indexing build %s (once per build, a few minutes)" % self.version)
        build = config(self.stored("config", self.build).decode())
        cdn = config(self.stored("config", self.cdn).decode())
        tmp = path + ".part"
        if os.path.exists(tmp):
            os.remove(tmp)
        db = sqlite3.connect(tmp)
        db.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;"
                         "CREATE TABLE enc (ckey BLOB PRIMARY KEY, ekey BLOB) WITHOUT ROWID;"
                         "CREATE TABLE idx (ekey BLOB PRIMARY KEY, archive INTEGER, offset INTEGER, size INTEGER)"
                         " WITHOUT ROWID;"
                         "CREATE TABLE root (fdid INTEGER PRIMARY KEY, ckey BLOB);"
                         "CREATE TABLE archives (id INTEGER PRIMARY KEY, hash TEXT);"
                         "CREATE TABLE files (fdid INTEGER PRIMARY KEY, ckey BLOB, ekey BLOB, archive INTEGER,"
                         " offset INTEGER, size INTEGER);")
        log("tact: encoding file (%d MB)" % (int(build["encoding-size"][1]) >> 20))
        db.executemany("INSERT OR IGNORE INTO enc VALUES (?, ?)",
                       encoding_entries(blte(self.stored("data", build["encoding"][1]))))
        archives = cdn["archives"]
        log("tact: %d archive indexes" % len(archives))
        db.executemany("INSERT INTO archives VALUES (?, ?)", enumerate(archives))
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            for n, data in enumerate(ex.map(lambda h: self.stored("data", h, ".index"), archives)):
                db.executemany("INSERT OR IGNORE INTO idx VALUES (?, ?, ?, ?)",
                               ((e, n, off, size) for e, size, off in index_entries(data)))
        for name in cdn.get("file-index", []):
            db.executemany("INSERT OR IGNORE INTO idx VALUES (?, ?, 0, ?)",
                           ((e, LOOSE, size) for e, size, _off in index_entries(self.stored("data", name, ".index"))))
        row = db.execute("SELECT i.ekey, archive, offset, size FROM enc e JOIN idx i ON i.ekey = e.ekey"
                         " WHERE e.ckey = ?", (bytes.fromhex(build["root"][0]),)).fetchone()
        if not row:
            raise RuntimeError("the build's root file is in no archive")
        self.archives = archives
        log("tact: root file")
        db.executemany("INSERT OR IGNORE INTO root VALUES (?, ?)", root_entries(blte(self.raw(*row))))
        db.executescript("INSERT INTO files SELECT r.fdid, r.ckey, i.ekey, i.archive, i.offset, i.size FROM root r"
                         " JOIN enc e ON e.ckey = r.ckey JOIN idx i ON i.ekey = e.ekey;"
                         "DROP TABLE enc; DROP TABLE idx; DROP TABLE root; VACUUM;")
        count = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        db.commit()
        db.close()
        os.replace(tmp, path)
        log("tact: %d files indexed" % count)

    def raw(self, ekey, archive, offset, size):
        """The stored (BLTE) bytes of one file."""
        if archive == LOOSE:
            return self.fetch("data", ekey.hex())
        data = self.fetch("data", self.archives[archive], headers={"Range": "bytes=%d-%d" % (offset, offset + size - 1)})
        if len(data) != size:
            raise RuntimeError("archive %s: asked for %d bytes, got %d" % (self.archives[archive], size, len(data)))
        return data

    def read(self, fdid, partial=False):
        """A file's bytes. KeyError: not in this build. Encrypted: no published key.

        partial: a file with parts under unpublished keys (a table's sections of unreleased content) is returned with
        those parts as zero bytes, as the game's own tools leave them; self.absent[fdid] then names the keys. Such a
        file cannot be checked against its content key."""
        with self.lock:
            row = self.db.execute("SELECT ckey, ekey, archive, offset, size FROM files WHERE fdid = ?",
                                  (int(fdid),)).fetchone()
        if not row:
            raise KeyError("file %s is not in build %s" % (fdid, self.version))
        return self.decoded(fdid, self.raw(*row[1:]), row[0], partial)

    def decoded(self, fdid, raw, ckey, partial=False):
        """The plain bytes of a stored file, checked against its content key (see read)."""
        try:
            data = blte(raw)
        except Encrypted:
            with self.lock:
                if self.keys is None:
                    path = os.path.join(self.dir, "keys.txt")
                    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 86400:
                        text = get(KEYS)
                        extra = "".join("%s %s\n" % (name, key.hex().upper()) for name, key in sorted(wago_keys(self.product).items()))
                        open(path, "wb").write(text + b"\n" + extra.encode())
                    self.keys = {}
                    for line in open(path).read().split("\n"):
                        parts = line.split()
                        if len(parts) >= 2 and len(parts[1]) == 32:
                            self.keys[parts[0].upper()] = bytes.fromhex(parts[1])
                    self.keys.update({str(name).upper(): key for name, key in self.extra_keys.items()})
            if partial:
                absent = []
                data = blte(raw, self.keys, absent)
                if absent:
                    self.absent[int(fdid)] = sorted(set(absent))
                    return data
            else:
                data = blte(raw, self.keys)
        if hashlib.md5(data).digest() != ckey:
            raise RuntimeError("file %s doesn't match its content key" % fdid)
        return data


# --- an earlier build, read sparingly -----------------------------------------------------------

BUILDS = "https://wago.tools/api/builds"
HEX = re.compile(r"[0-9a-f]{32}")


def builds(products, url=None, fetch=None):
    """Every build Blizzard shipped of these products, oldest first:
    [{'build', 'version', 'config', 'cdn', 'date', 'product'}].

    Blizzard's version server names the live build only. Which builds came before, and the two config files that
    name each of them on the CDN, is kept by wago.tools; the files themselves are still Blizzard's and are read from
    Blizzard's CDN. products: {product: version prefix} ('': every version). A build two products had (the last beta
    builds were the first live ones) is listed once, under the product that had it first. fetch: url -> bytes."""
    listed = json.loads((fetch or get)(url or BUILDS))
    found = {}
    for product, prefix in products.items():
        for row in (listed.get(product) or []) if isinstance(listed, dict) else []:
            version, day = str(row.get("version") or ""), str(row.get("created_at") or "")[:10]
            names = str(row.get("build_config") or "").lower(), str(row.get("cdn_config") or "").lower()
            # what goes into an address or a file name is taken only in the shape it must have
            if (not re.fullmatch(r"\d+(\.\d+){3}", version) or not version.startswith(prefix) or row.get("is_bgdl")
                    or not all(HEX.fullmatch(name) for name in names)):
                continue
            entry = {"build": int(version.rsplit(".", 1)[-1]), "version": version, "config": names[0], "cdn": names[1],
                     "date": day if re.fullmatch(r"\d{4}-\d\d-\d\d", day) else "", "product": product}
            known = found.get(entry["build"])
            if known is None or (entry["date"] and entry["date"] < (known["date"] or "9")):
                found[entry["build"]] = entry
    return [found[build] for build in sorted(found)]


def index_find(data, wanted):
    """{encoded key: (size, offset)} for the wanted keys an archive index holds (offset 0 in a loose file index).
    The index is sorted: the block is found by its first key, never the whole index read."""
    _ver, _a, _b, block_kb, off_size, size_size, key_size, sum_size, _count = struct.unpack_from(
        "<8BI", data, len(data) - 20)
    if key_size != 16 or size_size != 4 or off_size not in (0, 4) or sum_size != 8:
        raise ValueError("unknown archive index layout")
    entry, block = key_size + size_size + off_size, block_kb * 1024
    firsts = [data[b * block:b * block + 16] for b in range((len(data) - 28) // (block + key_size + sum_size))]
    out = {}
    for key in wanted:
        b = bisect.bisect_right(firsts, key) - 1
        at = data.find(key, b * block, (b + 1) * block) if b >= 0 else -1
        while at >= 0 and (at - b * block) % entry:   # the same bytes inside another entry
            at = data.find(key, at + 1, (b + 1) * block)
        if at >= 0:
            size, offset = struct.unpack_from(">II", data, at + 16) if off_size else (struct.unpack_from(">I", data, at + 16)[0], 0)
            out[key] = (size, offset)
    return out


class Earlier(Tact):
    """A build that is no longer live, named by its two config files (builds()), read for a handful of files.

    The live build is indexed whole (Tact): every file of it, a few hundred MB, once. For the changelog of thirty
    earlier builds that would be gigabytes. This reads only what the files asked for need: the encoding file's page
    table and the few pages that hold their keys (ranged requests into it: its pages are stored plain), the root file,
    and the archive indexes, which the builds share and which are kept in the cache between them. A file is checked
    against its content key exactly as in Tact.

    pin: {'config', 'cdn', 'version'}. prepare(file data ids) first, then read()."""

    def __init__(self, cache, pin, product="wowf", log=print):
        self.dir = os.path.join(cache, "tact")
        self.log = log
        self.product = product
        os.makedirs(self.dir, exist_ok=True)
        where = next(r for r in table(get(VERSIONS % (product, "cdns")).decode()) if r["Name"] == "us")
        self.build, self.cdn, self.version = pin["config"], pin["cdn"], pin["version"]
        self.path, self.hosts = where["Path"], where["Hosts"].split()
        self.lock = threading.Lock()
        self.keys = None
        self.extra_keys = {}
        self.absent = {}
        self.where = {}   # file data id -> (content key, encoded key, archive, offset, size)
        build, cdn = config(self.stored("config", self.build).decode()), config(self.stored("config", self.cdn).decode())
        self.root = bytes.fromhex(build["root"][0])
        self.archives, self.loose = cdn["archives"], cdn.get("file-index", [])
        self.encoding = build["encoding"][1]
        head = self.part(0, 4096)
        size = struct.unpack_from(">I", head, 4)[0] if head[:4] == b"BLTE" else 0
        if not size:
            raise RuntimeError("the encoding file of build %s has no chunk table: it cannot be read in parts" % self.version)
        if size > len(head):
            head = self.part(0, size)
        entry = 40 if head[8] & 0x10 else 24
        self.chunks, at, plain_at = [], size, 0   # (where it is stored, stored size, where its plain bytes start, plain size)
        for i in range(int.from_bytes(head[9:12], "big")):
            stored, plain = struct.unpack_from(">II", head, 12 + i * entry)
            self.chunks.append((at, stored, plain_at, plain))
            at, plain_at = at + stored, plain_at + plain
        self.whole = {}   # chunk number -> its plain bytes, for a chunk that had to be decoded whole
        self.modes = {}
        start = self.plain(0, 22)
        if start[:2] != b"EN":
            raise ValueError("not an encoding file")
        _ver, self.ckey_size, self.ekey_size, page_kb, _epage_kb, pages, _epages, _unk, espec = struct.unpack_from(">BBBHHIIBI", start, 2)
        if self.ckey_size != 16 or self.ekey_size != 16:
            raise ValueError("unknown encoding file layout")
        self.page = page_kb * 1024
        listing = self.plain(22 + espec, pages * 32)   # each page's first content key and the MD5 of the page
        self.firsts = [listing[p * 32:p * 32 + 16] for p in range(pages)]
        self.sums = [listing[p * 32 + 16:p * 32 + 32] for p in range(pages)]
        self.pages_at = 22 + espec + pages * 32

    def part(self, offset, size):
        """size stored bytes of the encoding file from offset (fewer at its end)."""
        return self.fetch("data", self.encoding, headers={"Range": "bytes=%d-%d" % (offset, offset + size - 1)})

    def plain(self, offset, size):
        """size plain bytes of the encoding file from offset, asking the CDN for no more than they need."""
        out = []
        for number, (at, stored, plain_at, plain) in enumerate(self.chunks):
            first, last = max(offset, plain_at), min(offset + size, plain_at + plain)
            if first >= last:
                continue
            if number not in self.modes:
                self.modes[number] = self.part(at, 1)[:1]
            if self.modes[number] == b"N":   # stored as it is, after the mode byte: only the bytes asked for
                piece = self.part(at + 1 + first - plain_at, last - first)
            else:
                if number not in self.whole:
                    self.whole[number] = blte_chunk(self.part(at, stored), number, None)
                piece = self.whole[number][first - plain_at:last - plain_at]
            if len(piece) != last - first:
                raise RuntimeError("encoding file of build %s: asked for %d bytes, got %d" % (self.version, last - first, len(piece)))
            out.append(piece)
        return b"".join(out)

    def encoded(self, ckeys):
        """{content key: encoded key} from the encoding file's pages, each page checked against its MD5."""
        by_page = {}
        for ckey in ckeys:
            page = bisect.bisect_right(self.firsts, ckey) - 1
            if page >= 0:
                by_page.setdefault(page, []).append(ckey)

        def read(page):
            data = self.plain(self.pages_at + page * self.page, self.page)
            if hashlib.md5(data).digest() != self.sums[page]:
                raise RuntimeError("encoding file of build %s: page %d doesn't match its checksum" % (self.version, page))
            return page, data
        out = {}
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            for page, data in ex.map(read, sorted(by_page)):
                wanted, o = set(by_page[page]), 0
                while o + 22 <= len(data) and data[o]:
                    count = data[o]
                    if data[o + 6:o + 22] in wanted:
                        out[data[o + 6:o + 22]] = data[o + 22:o + 38]
                    o += 22 + count * 16
        return out

    def located(self, ekeys):
        """{encoded key: (archive, offset, size)} from the archive indexes (kept in the cache: the builds share them)."""
        wanted, out = set(ekeys), {}
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            for number, data in enumerate(ex.map(lambda h: self.stored("data", h, ".index"), self.archives)):
                for ekey, (size, offset) in index_find(data, wanted - out.keys()).items():
                    out[ekey] = (number, offset, size)
        for name in self.loose:
            for ekey, (size, _offset) in index_find(self.stored("data", name, ".index"), wanted - out.keys()).items():
                out[ekey] = (LOOSE, 0, size)
        return out

    def prepare(self, fdids):
        """Finds where the bytes of these files are; a file the build does not have is left out (read: KeyError)."""
        wanted = {int(fdid) for fdid in fdids}
        self.log("tact: build %s: root file" % self.version)
        root = self.encoded([self.root]).get(self.root)
        place = self.located([root]).get(root) if root else None
        if not place:
            raise RuntimeError("the root file of build %s is in no archive" % self.version)
        data = blte(self.raw(root, *place))
        if hashlib.md5(data).digest() != self.root:
            raise RuntimeError("the root file of build %s doesn't match its content key" % self.version)
        ckeys = {}
        for fdid, ckey in root_entries(data):
            if fdid in wanted:
                ckeys.setdefault(fdid, ckey)   # the uncensored copy comes first
        del data
        ekeys = self.encoded(ckeys.values())
        places = self.located(ekeys.values())
        for fdid, ckey in ckeys.items():
            ekey = ekeys.get(ckey)
            if ekey in places:
                self.where[fdid] = (ckey, ekey) + places[ekey]
        self.log("tact: build %s: %d of %d files found" % (self.version, len(self.where), len(wanted)))

    def read(self, fdid, partial=False):
        row = self.where.get(int(fdid))
        if not row:
            raise KeyError("file %s is not in build %s" % (fdid, self.version))
        return self.decoded(fdid, self.raw(*row[1:]), row[0], partial)


def published_keys(product="wowf"):
    """{key name: 16 bytes} of every key published so far: wowdev's TACTKeys list, then the keys wago.tools saw handed
    out by hotfix in any region (wago_keys). Blizzard ships unreleased content encrypted and hands the key out when it
    opens: the lists grow with time. RuntimeError when TACTKeys cannot be read."""
    keys = {}
    for line in get(KEYS).decode("utf-8", "replace").split("\n"):
        parts = line.split()
        if len(parts) >= 2 and len(parts[1]) == 32:
            try:
                keys[parts[0].upper()] = bytes.fromhex(parts[1])
            except ValueError:
                pass
    for name, key in wago_keys(product).items():
        keys.setdefault(name, key)
    return keys


def wago_keys(product="wowf", fetch=None):
    """{key name: 16 bytes} from wago.tools' TactKey table of the product (every region's hotfixes merged), named
    through its TactKeyLookup table (a key's 8-byte name, stored low byte first). {} when wago cannot be read: it only
    adds to the published list. fetch: url -> bytes (tests)."""
    fetch = fetch or get
    try:
        keys = _csv_rows(fetch(WAGO_TABLE % ("TactKey", product)))
        names = _csv_rows(fetch(WAGO_TABLE % ("TactKeyLookup", product)))
    except (RuntimeError, ValueError, UnicodeDecodeError):
        return {}
    named = {}
    for row in names:
        try:
            named[int(row["ID"])] = bytes(int(row["TACTID_%d" % i]) & 0xFF for i in range(8))[::-1].hex().upper()
        except (KeyError, ValueError):
            continue
    out = {}
    for row in keys:
        try:
            number = int(row["ID"])
            key = bytes(int(row["Key_%d" % i]) & 0xFF for i in range(16))
        except (KeyError, ValueError):
            continue
        if number in named and any(key):
            out[named[number]] = key
    return out


def _csv_rows(blob):
    import csv
    import io
    return list(csv.DictReader(io.StringIO(blob.decode("utf-8"))))


def live(product="wowf", region="us"):
    """What Blizzard's version server says is live: {'build': 70938, 'version': '1.60.1.70938', 'config': ...}."""
    row = next(r for r in table(get(VERSIONS % (product, "versions")).decode()) if r["Region"] == region)
    version = row["VersionsName"]
    return {"build": int(row.get("BuildId") or version.rsplit(".", 1)[-1]), "version": version, "config": row["BuildConfig"]}
