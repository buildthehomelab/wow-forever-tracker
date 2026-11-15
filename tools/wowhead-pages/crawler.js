// Wowhead page crawler: reads the pages of Wowhead's WoW Forever database slowly, from a browser tab.
//
// Wowhead answers page requests from scripts with 403, and a browser that asks too fast with a block of several
// minutes. So this runs inside a tab that is already on a Wowhead page (same-origin fetch), one page every few
// seconds, and keeps only facts: the Quick Facts lines and the rows of each tab (who drops, who sells, ...) with their
// numbers. No name, no description, no comment is kept. What it read stays in the tab's IndexedDB, so a reload, a
// block or a closed tab loses nothing: load this file again and call WHC.start().
//
//   1. open https://www.wowhead.com/forever in a tab, open the console, paste this file
//   2. WHC.add('item', [213127, 216616]); WHC.start()
//   3. WHC.status()                       how far it is, and until when it waits after a block
//   4. WHC.save()                         downloads wowhead-pages.jsonl, one page a line
//   5. python tools/wowhead_pages.py merge wowhead-pages.jsonl      into tools/wowhead-pages/cache/
//
// docs/WOWHEAD-PAGES.md says what the pace is and why. The functions that read a page are pure and are also
// loaded by Node for the tests (tools/tests/test_wowhead_crawl.mjs).
(function (root) {
  'use strict';

  const VERSION = 1;                 // of what a page record holds: raise it when extract() keeps more
  const SKIPPED = Symbol('expression');
  // tabs that hold what users wrote or uploaded, never game data
  const NOT_DATA = new Set(['comment', 'screenshot', 'video', 'commentpreview', 'replypreview', 'guide', 'forumpost', 'topic', 'user']);
  const MAX_ROWS = 2000;

  // ------------------------------------------------------------------ reading a page (pure)

  /** Skips a JavaScript expression that is no literal (WH.TERMS.droppedby, function () {...}): to the next ',', '}'
   *  or ']' outside brackets and strings. Returns the index after it. */
  function skipExpression(text, i) {
    let depth = 0;
    for (; i < text.length; i++) {
      const c = text[i];
      if (c === '"' || c === "'" || c === '`') { i = readString(text, i)[1] - 1; continue; }
      if (c === '(' || c === '[' || c === '{') depth++;
      else if (c === ')' || c === ']' || c === '}') { if (depth === 0) return i; depth--; }
      else if (c === ',' && depth === 0) return i;
    }
    return i;
  }

  function readString(text, i) {
    const quote = text[i];
    let out = '';
    for (i++; i < text.length; i++) {
      const c = text[i];
      if (c === quote) return [out, i + 1];
      if (c !== '\\') { out += c; continue; }
      const n = text[++i];
      if (n === 'u') { out += String.fromCharCode(parseInt(text.substr(i + 1, 4), 16)); i += 4; }
      else if (n === 'x') { out += String.fromCharCode(parseInt(text.substr(i + 1, 2), 16)); i += 2; }
      else out += ({ n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', v: '\v', 0: '\0' })[n] ?? n;
    }
    throw new Error('string not closed');
  }

  const space = (text, i) => { while (i < text.length && /\s/.test(text[i])) i++; return i; };
  const NUMBER = /-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/y;
  const WORD = /[A-Za-z_$][\w$]*/y;
  const WORDS = { true: true, false: false, null: null, undefined: null, NaN: null };

  /** Reads the JavaScript literal at text[i]: objects (keys quoted or bare), arrays, strings, numbers, true, false,
   *  null. A value that is an expression is skipped and read as SKIPPED. Returns [value, index after]. */
  function readLiteral(text, i) {
    i = space(text, i);
    const c = text[i];
    if (c === '{' || c === '[') {
      const close = c === '{' ? '}' : ']';
      const out = c === '{' ? {} : [];
      for (i = space(text, i + 1); ; i = space(text, i)) {
        if (i >= text.length) throw new Error('bracket not closed');
        if (text[i] === close) return [out, i + 1];
        if (text[i] === ',') { i++; continue; }
        let key = null;
        if (c === '{') {
          if (text[i] === '"' || text[i] === "'") [key, i] = readString(text, i);
          else { const from = i; while (i < text.length && /[\w$]/.test(text[i])) i++; key = text.slice(from, i); }
          i = space(text, i);
          if (text[i] !== ':' || key === '') throw new Error('no key at ' + i);
          i++;
        }
        let value;
        [value, i] = readLiteral(text, i);
        if (c === '{') { if (value !== SKIPPED) out[key] = value; } else out.push(value === SKIPPED ? null : value);
      }
    }
    if (c === '"' || c === "'") {
      const [value, after] = readString(text, i);
      // "a" + b is an expression, not a string
      const next = space(text, after);
      return text[next] === '+' ? [SKIPPED, skipExpression(text, next)] : [value, after];
    }
    NUMBER.lastIndex = i;
    const number = NUMBER.exec(text);
    if (number) {
      const next = space(text, NUMBER.lastIndex);
      if (next >= text.length || ',}]'.includes(text[next])) return [Number(number[0]), NUMBER.lastIndex];
    }
    WORD.lastIndex = i;
    const word = WORD.exec(text);
    if (word && word[0] in WORDS) {
      const next = space(text, WORD.lastIndex);
      if (next >= text.length || ',}]'.includes(text[next])) return [WORDS[word[0]], WORD.lastIndex];
    }
    return [SKIPPED, skipExpression(text, i)];
  }

  /** What is kept of a row: numbers, true/false, and whatever holds them. Text is dropped (null inside a list, so
   *  that positions keep their meaning); text that is only a number is kept as that number. */
  function facts(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value === 'boolean' || value === null) return value;
    if (typeof value === 'string') return /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : undefined;
    if (Array.isArray(value)) return value.map(v => { const f = facts(v); return f === undefined ? null : f; });
    if (value && typeof value === 'object') {
      const out = {};
      for (const key of Object.keys(value)) { const f = facts(value[key]); if (f !== undefined) out[key] = f; }
      return out;
    }
    return undefined;
  }

  /** The tabs of a page: {id: {template, rows}} from every `new Listview({...})`. */
  function listviews(html) {
    const tabs = {};
    const start = /new Listview\(\s*\{/g;
    for (let m; (m = start.exec(html));) {
      let config;
      try { config = readLiteral(html, m.index + m[0].length - 1)[0]; } catch (error) { continue; }
      const id = typeof config.id === 'string' ? config.id : null;
      const template = typeof config.template === 'string' ? config.template : '';
      if (!id || NOT_DATA.has(template) || !/^[\w-]{1,60}$/.test(id)) continue;
      let data = config.data;
      if (data === undefined) {
        // data: someVariable, declared earlier as `var someVariable = [...]`
        const named = new RegExp('\\bdata\\s*:\\s*([A-Za-z_$][\\w$]*)\\s*[,}]').exec(html.slice(m.index, m.index + 4000));
        const at = named ? html.search(new RegExp('\\b(?:var|let|const)\\s+' + named[1].replace(/\$/g, '\\$') + '\\s*=\\s*\\[')) : -1;
        if (at >= 0) { try { data = readLiteral(html, html.indexOf('[', at))[0]; } catch (error) { data = undefined; } }
      }
      if (!Array.isArray(data)) continue;
      const rows = data.slice(0, MAX_ROWS).map(facts).filter(r => r && typeof r === 'object' && !Array.isArray(r));
      const tab = { template, rows };
      if (data.length > MAX_ROWS) tab.total = data.length;
      const extra = facts(config._totalCount);
      if (typeof extra === 'number' && extra > rows.length) tab.total = extra;
      tabs[id] = tab;
    }
    return tabs;
  }

  /** The Quick Facts lines ("Level: 13", "Start: [url=/forever/npc=123]"), link texts removed. */
  function quickFacts(html) {
    const call = /printHtml\(\s*(["'])/g;
    for (let m; (m = call.exec(html));) {
      let text, after;
      try { [text, after] = readString(html, m.index + m[0].length - 1); } catch (error) { continue; }
      if (!/^\s*,\s*["']infobox-contents-0["']/.test(html.slice(after, after + 60))) continue;
      // a line is the text of one [li]; a [li] that opens a list of its own gives its label first, then its children
      const lines = [];
      const open = [];
      const emit = line => { line = line.replace(/\[url=([^\]\s]*)[^\]]*\][\s\S]*?\[\/url\]/g, '[url=$1]').replace(/\s+/g, ' ').trim(); if (line && line.length <= 300) lines.push(line); };
      for (const part of text.split(/(\[li[^\]]*\]|\[\/li\]|\[ul[^\]]*\]|\[\/ul\])/)) {
        if (/^\[li/.test(part)) open.push('');
        else if (part === '[/li]') { if (open.length) emit(open.pop()); }
        else if (/^\[ul/.test(part)) { if (open.length) { emit(open[open.length - 1]); open[open.length - 1] = ''; } }
        else if (part !== '[/ul]' && open.length) open[open.length - 1] += part;
      }
      return lines;
    }
    return [];
  }

  /** What the page says it is: {type, typeId} of g_pageInfo, or null. */
  function pageInfo(html) {
    const m = /g_pageInfo\s*=\s*\{/.exec(html);
    if (!m) return null;
    try {
      const info = facts(readLiteral(html, m.index + m[0].length - 1)[0]);
      return info && typeof info.typeId === 'number' ? { type: info.type ?? null, typeId: info.typeId } : null;
    } catch (error) { return null; }
  }

  /** Where the page places things on its maps: g_mapperData's numbers ({zone: [{count, coords: [[x, y]...]}]}), or null. */
  function mapper(html) {
    const m = /\bg_mapperData\s*=\s*\{/.exec(html);
    if (!m) return null;
    try { const data = facts(readLiteral(html, m.index + m[0].length - 1)[0]); return data && Object.keys(data).length ? data : null; } catch (error) { return null; }
  }

  /** The ids a quest page links to in its rewards and its series: {series: [quest...], links: {item: [...], ...}}.
   *  Only read for quests: the series is a table of quest links in the Quick Facts column. */
  function questSeries(html) {
    const m = /\[table class=series\]([\s\S]*?)\[\\?\/table\]/.exec(html);
    if (!m) return null;
    const ids = [];
    const step = /\[(?:url=[^\]]*?\/quest=(\d+)|b\])/g;
    // a step is either a link to another quest or, in bold, the quest of this page (0 here: the reader knows its id)
    for (let s; (s = step.exec(m[1]));) ids.push(s[1] ? Number(s[1]) : 0);
    return ids.length ? ids : null;
  }

  /**
   * One page as a record: {kind, id, v, status: 'ok', quick, tabs, map?, series?}; status 'missing' when Wowhead has
   * no such page (the answer is another page, or none); 'blocked' when the answer is no Wowhead page at all; 'odd'
   * when it is a Wowhead page this reader does not understand.
   */
  function extract(kind, id, html, httpStatus, finalUrl) {
    const record = { kind, id, v: VERSION };
    const info = pageInfo(html);
    if (httpStatus === 404 || /[?&]notFound=/.test(finalUrl || '')) return Object.assign(record, { status: 'missing' });
    if (httpStatus !== 200 || html.length < 5000 || !/wowhead/i.test(html)) return Object.assign(record, { status: 'blocked', http: httpStatus, bytes: html.length });
    if (info && info.typeId !== id) return Object.assign(record, { status: 'missing' });   // sent on to another page
    // a Wowhead page that does not say what it is: kept as 'odd' and counted, never read as "Wowhead has no such page"
    if (!info) return Object.assign(record, { status: 'odd', bytes: html.length });
    record.status = 'ok';
    record.quick = quickFacts(html);
    record.tabs = listviews(html);
    const map = mapper(html);
    if (map) record.map = map;
    if (kind === 'quest') { const series = questSeries(html); if (series) record.series = series; }
    return record;
  }

  const api = { VERSION, readLiteral, facts, listviews, quickFacts, pageInfo, mapper, questSeries, extract };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  // ------------------------------------------------------------------ the crawl (browser only)

  const BRANCH = (location.pathname.match(/^\/([a-z-]+)(?:\/|$)/) || [])[1] || 'forever';
  const KINDS = /^(item|npc|quest|object|spell|zone|faction|itemset)$/;
  const store = {
    get: (key, fallback) => { try { const v = localStorage.getItem('whc.' + key); return v === null ? fallback : JSON.parse(v); } catch (error) { return fallback; } },
    set: (key, value) => { try { localStorage.setItem('whc.' + key, JSON.stringify(value)); } catch (error) { /* full or blocked: the queue then lives in memory only */ } },
  };
  const state = {
    queue: store.get('queue', []),        // 'item:123', in order
    gap: store.get('gap', 11000),         // ms between two requests, plus up to `jitter`
    jitter: 3000,
    nextSlot: 0,                          // when the next request to Wowhead may leave, the page's own ones included
    blockWait: 8.5 * 60000,               // after a block; doubled while blocks follow each other, 34 min at most
    blockedUntil: store.get('blockedUntil', 0),
    blocks: 0, errors: 0, fetched: 0, skipped: 0, pageRequests: 0, running: false, last: null, startedAt: 0, lastAt: 0, note: '',
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  // Wowhead counts every request from this address, and its own page keeps asking for things in the background. So
  // every fetch of this tab to Wowhead waits its turn in one line: the crawler's pages and the page's own requests.
  const pageFetch = root.__whcFetch || (root.__whcFetch = root.fetch.bind(root));
  async function turn() {
    const now = Date.now();
    const at = Math.max(now, state.nextSlot);
    state.nextSlot = at + state.gap + Math.random() * state.jitter;
    if (at > now) await sleep(at - now);
  }
  root.fetch = async function (input, init) {
    let own = false;
    try { own = new URL(typeof input === 'string' ? input : input.url, location.href).origin === location.origin; } catch (error) { /* not a URL: let fetch say so */ }
    if (own) { state.pageRequests++; await turn(); }
    return pageFetch(input, init);
  };

  let opening = null;
  function db() {
    return opening ??= new Promise((resolve, reject) => {
      const request = indexedDB.open('whc', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('pages', { keyPath: 'key' });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  async function pages(mode, work) {
    const handle = await db();
    return new Promise((resolve, reject) => {
      const tx = handle.transaction('pages', mode);
      const request = work(tx.objectStore('pages'));
      tx.oncomplete = () => resolve(request && request.result);
      tx.onerror = tx.onabort = () => reject(tx.error);
    });
  }

  /** Adds pages to the queue: add('item', [1, 2]). Pages already read are skipped unless {again: true}. */
  async function add(kind, ids, options = {}) {
    if (!KINDS.test(kind)) throw new Error('unknown kind ' + kind);
    const have = options.again ? new Set() : new Set(await pages('readonly', s => s.getAllKeys()));
    const queued = new Set(state.queue);
    let added = 0;
    for (const id of ids) {
      const key = kind + ':' + Number(id);
      if (!Number.isInteger(Number(id)) || Number(id) <= 0 || queued.has(key) || have.has(key)) continue;
      queued.add(key); added++;
      if (options.first) state.queue.splice(added - 1, 0, key); else state.queue.push(key);
    }
    store.set('queue', state.queue);
    return { added, queued: state.queue.length };
  }

  async function one(key) {
    const [kind, idText] = key.split(':');
    const id = Number(idText);
    let response, html;
    try {
      await turn();
      response = await pageFetch('/' + BRANCH + '/' + kind + '=' + id, { credentials: 'same-origin', redirect: 'follow' });
      html = await response.text();
    } catch (error) { return { status: 'error', note: String(error) }; }
    const record = extract(kind, id, html, response.status, response.url);
    if (record.status === 'blocked') return record;
    record.key = key;
    record.fetched = Math.floor(Date.now() / 1000);
    await pages('readwrite', s => s.put(record));
    return record;
  }

  async function run() {
    if (state.running) return;
    state.running = true; state.startedAt = Date.now(); store.set('run', true);
    while (state.running && state.queue.length) {
      const wait = state.blockedUntil - Date.now();
      if (wait > 0) { await sleep(Math.min(wait, 30000)); continue; }
      const key = state.queue[0];
      const result = await one(key);
      state.last = key + ' ' + result.status; state.lastAt = Date.now();
      if (result.status === 'blocked') {
        state.blocks++;
        state.blockedUntil = Date.now() + Math.min(state.blockWait * 2 ** (state.blocks - 1), 34 * 60000);
        store.set('blockedUntil', state.blockedUntil);
        state.note = 'blocked (HTTP ' + result.http + ', ' + result.bytes + ' bytes) at ' + new Date().toLocaleTimeString();
        continue;
      }
      if (result.status === 'error') {
        // no answer: the page goes to the end of the queue; ten in a row and the crawl stops by itself
        if (++state.errors >= 10) { state.note = 'stopped: ten requests in a row got no answer (' + result.note + ')'; break; }
        state.queue.push(state.queue.shift());
        await sleep(30000);
        continue;
      }
      state.errors = 0; state.blocks = 0; state.fetched++;
      state.queue.shift(); store.set('queue', state.queue);
    }
    if (!state.queue.length) { store.set('run', false); state.note = state.note || 'queue done'; }
    state.running = false;
  }

  async function status() {
    const all = await pages('readonly', s => s.getAll());
    const counts = {};
    for (const p of all) { const k = p.kind + ' ' + p.status; counts[k] = (counts[k] || 0) + 1; }
    const minutes = (Date.now() - state.startedAt) / 60000;
    return {
      running: state.running, queued: state.queue.length, read: counts, thisRun: state.fetched,
      perMinute: state.startedAt && minutes > 0.5 ? Math.round(state.fetched / minutes * 10) / 10 : null,
      pageRequests: state.pageRequests, last: state.last, secondsSinceLast: state.lastAt ? Math.round((Date.now() - state.lastAt) / 1000) : null,
      blockedFor: state.blockedUntil > Date.now() ? Math.round((state.blockedUntil - Date.now()) / 1000) + ' s' : null, note: state.note,
    };
  }

  /** The pages read, one JSON line each, sorted by kind and id; {kind, since} narrow it. */
  async function lines(options = {}) {
    const all = (await pages('readonly', s => s.getAll()))
      .filter(p => (!options.kind || p.kind === options.kind) && (!options.since || p.fetched >= options.since))
      .sort((a, b) => a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : a.id - b.id);
    return all.map(p => { const { key, ...rest } = p; return JSON.stringify(rest); });
  }

  /** Downloads the pages read as wowhead-pages.jsonl (tools/wowhead_pages.py merge reads it). */
  async function save(options = {}) {
    const text = (await lines(options)).join('\n') + '\n';
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([text], { type: 'application/x-ndjson' }));
    link.download = options.name || 'wowhead-pages.jsonl';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    return { pages: text.split('\n').length - 1, bytes: text.length };
  }

  root.WHC = {
    add, status, lines, save, state, extract,
    start: () => { state.note = ''; run(); return 'started'; },
    stop: () => { state.running = false; store.set('run', false); return 'stopping after the request in flight'; },
    pace: seconds => { state.gap = Math.max(4, Number(seconds)) * 1000; store.set('gap', state.gap); return state.gap; },   // under 10 gets blocked
    clearQueue: () => { state.queue = []; store.set('queue', []); },
    forget: key => pages('readwrite', s => s.delete(key)),
  };
  // a reload in the middle of a crawl: go on by itself
  if (store.get('run', false) && state.queue.length) run();
})(typeof window !== 'undefined' ? window : globalThis);
