// Wowhead page crawler: reads the pages of Wowhead's WoW Forever database slowly, from a browser tab.
//
// Wowhead answers page requests from scripts with 403, and a browser that asks too fast with a block of several
// minutes. So this runs inside a tab that is already on a Wowhead page (same-origin fetch), one page every 20 or so
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
      const emit = line => { line = line.replace(/\[tooltip[^\]]*\][\s\S]*?\[\/tooltip\]/g, '').replace(/\[span[^\]]*\]|\[\/span\]/g, '').replace(/\[url=([^\]\s]*)[^\]]*\][\s\S]*?\[\/url\]/g, '[url=$1]').replace(/\s+/g, ' ').trim(); if (line && line.length <= 300) lines.push(line); };
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

  // ------------------------------------------------------------------ the pace (pure)
  //
  // Wowhead does not say its limit; it blocks an address for about eight minutes when it asks too much. So the pace
  // is learned: it speeds up a little after each run of clean pages and slows down a lot after a block (the way TCP
  // finds a link's speed), and it remembers the pace a block came at, so it settles just above it instead of running
  // into it again. That memory fades slowly, so a limit that was raised is found too. A network error is no block: the
  // page is asked again after a growing wait, and the pace only eases when such errors keep coming.

  const PACE = {
    start: 30000,          // ms between two pages at first
    fastest: 8000,         // never faster than this
    slowest: 180000,       // never slower than this
    speedUpEvery: 15,      // clean pages in a row before a step faster
    speedUp: 0.92,         // ... of this much
    slowDown: 1.6,         // after a block
    margin: 1.2,           // stay this much slower than the pace a block came at
    fadeEvery: 60,         // clean pages at that margin before the remembered block pace fades ...
    fade: 0.95,            // ... by this much
    blockWait: 8.5 * 60000,
    longestBlockWait: 34 * 60000,
    errorWait: 15000,      // after a network error, doubled while they follow each other
    longestErrorWait: 10 * 60000,
  };

  /** A new pacer state, or the one kept from an earlier run. */
  function pacer(kept) {
    const p = Object.assign({ gap: PACE.start, blockedAt: 0, clean: 0, atMargin: 0, blocks: 0, errors: 0 }, kept || {});
    p.gap = Math.min(PACE.slowest, Math.max(PACE.fastest, Number(p.gap) || PACE.start));
    return p;
  }

  /** What an answer is: 'page' (a Wowhead page, or Wowhead saying it has none), 'block' (Wowhead refuses this address
   *  for a while), 'slow' (asked to slow down), 'error' (the network or Wowhead had a problem: ask again later). */
  function classify(httpStatus, bytes, record) {
    if (httpStatus === 405 || httpStatus === 403) return 'block';
    if (httpStatus === 429) return 'slow';
    if (!httpStatus || httpStatus >= 500 || httpStatus === 408) return 'error';
    if (record && record.status === 'blocked') return httpStatus === 200 ? 'error' : 'block';   // a short or foreign answer
    if (record && record.status === 'odd') return 'error';
    return 'page';
  }

  /** The pacer after an answer: {p, wait}: the new state, and how long to wait before anything else (ms). */
  function paced(p, answer, now = Date.now()) {
    p = Object.assign({}, p);
    let wait = 0;
    if (answer === 'page') {
      p.errors = 0; p.blocks = 0;
      const floor = Math.max(PACE.fastest, p.blockedAt * PACE.margin);
      if (++p.clean >= PACE.speedUpEvery) { p.clean = 0; p.gap = Math.max(floor, Math.round(p.gap * PACE.speedUp)); }
      // running at the margin for a long while: what blocked once may have been a busy hour, try a little closer
      if (p.blockedAt && p.gap <= floor * 1.01 && ++p.atMargin >= PACE.fadeEvery) { p.atMargin = 0; p.blockedAt = Math.round(p.blockedAt * PACE.fade); }
    } else if (answer === 'block') {
      p.blockedAt = Math.max(p.blockedAt * PACE.fade, p.gap);   // the pace that ran into it
      p.gap = Math.min(PACE.slowest, Math.round(p.gap * PACE.slowDown));
      p.clean = 0; p.atMargin = 0;
      wait = Math.min(PACE.blockWait * 2 ** p.blocks, PACE.longestBlockWait);
      p.blocks++;
    } else if (answer === 'slow') {
      p.gap = Math.min(PACE.slowest, Math.round(p.gap * 1.3)); p.clean = 0;
      wait = 60000;
    } else {
      // the network: wait longer each time; when it keeps failing the pace eases too (an overloaded line)
      wait = Math.min(PACE.errorWait * 2 ** p.errors, PACE.longestErrorWait);
      if (++p.errors % 3 === 0) p.gap = Math.min(PACE.slowest, Math.round(p.gap * 1.2));
      p.clean = 0;
    }
    return { p, wait };
  }

  const api = { VERSION, PACE, readLiteral, facts, listviews, quickFacts, pageInfo, mapper, questSeries, extract, pacer, classify, paced };
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
    pace: pacer(store.get('pace', null)), // the learned pace (see paced()), kept between runs
    jitter: 0.15,                         // each wait is the pace, give or take this share
    nextSlot: 0,                          // when the next request to Wowhead may leave, the page's own ones included
    blockedUntil: store.get('blockedUntil', 0),
    tries: {},                            // network errors per page in this run
    fetched: 0, pageRequests: 0, running: false, last: null, startedAt: 0, lastAt: 0, note: '', log: [],
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  // Wowhead counts the requests from this address, whoever in the tab makes them. So every fetch of this tab to
  // Wowhead itself waits its turn in one line: the crawler's pages and anything the page asks its own host for.
  // Requests to other hosts (the page's bot-check service among them) pass untouched.
  const pageFetch = root.__whcFetch || (root.__whcFetch = root.fetch.bind(root));
  async function turn() {
    const now = Date.now();
    const at = Math.max(now, state.nextSlot);
    state.nextSlot = at + state.pace.gap * (1 + (Math.random() * 2 - 1) * state.jitter);
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

  /** Reads one page: {answer, record?, note}. A page that does not come within a minute is a network error. */
  async function one(key) {
    const [kind, idText] = key.split(':');
    const id = Number(idText);
    let response, html;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 60000);
    try {
      await turn();
      if (!state.running) return { answer: 'stopped' };
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return { answer: 'error', note: 'offline' };
      response = await pageFetch('/' + BRANCH + '/' + kind + '=' + id, { credentials: 'same-origin', redirect: 'follow', signal: abort.signal });
      html = await response.text();
    } catch (error) {
      return { answer: 'error', note: error && error.name === 'AbortError' ? 'no answer within a minute' : String(error) };
    } finally { clearTimeout(timer); }
    const record = extract(kind, id, html, response.status, response.url);
    const answer = classify(response.status, html.length, record);
    // a page this reader does not understand, three times: kept as 'odd' so that the queue goes on
    const giveUp = answer === 'error' && record.status === 'odd' && (state.tries[key] || 0) >= 2;
    if (answer !== 'page' && !giveUp) return { answer, note: 'HTTP ' + response.status + ', ' + html.length + ' bytes' };
    record.key = key;
    record.fetched = Math.floor(Date.now() / 1000);
    await pages('readwrite', s => s.put(record));
    return { answer: 'page', record };
  }

  function note(text) {
    state.note = new Date().toLocaleTimeString() + ' ' + text;
    state.log.push(state.note);
    if (state.log.length > 50) state.log.shift();
  }

  async function run() {
    if (state.running) return;
    state.running = true; state.startedAt = Date.now(); store.set('run', true);
    while (state.running && state.queue.length) {
      const left = state.blockedUntil - Date.now();
      if (left > 0) { await sleep(Math.min(left, 30000)); continue; }
      const key = state.queue[0];
      const result = await one(key);
      if (result.answer === 'stopped') break;
      state.last = key + ' ' + (result.record ? result.record.status : result.answer); state.lastAt = Date.now();
      const before = state.pace.gap;
      const { p, wait } = paced(state.pace, result.answer);
      state.pace = p; store.set('pace', p);
      if (result.answer === 'page') {
        delete state.tries[key];
        state.fetched++;
        state.queue.shift(); store.set('queue', state.queue);
        if (p.gap < before) note('pace ' + Math.round(before / 1000) + ' -> ' + Math.round(p.gap / 1000) + ' s');
        continue;
      }
      state.blockedUntil = Date.now() + wait;
      store.set('blockedUntil', state.blockedUntil);
      if (result.answer === 'block' || result.answer === 'slow') {
        note(result.answer + ' (' + result.note + '): waiting ' + Math.round(wait / 60000) + ' min, pace ' + Math.round(before / 1000) + ' -> ' + Math.round(p.gap / 1000) + ' s');
      } else {
        // the network: the page is asked again after the wait, the queue keeps its order
        state.tries[key] = (state.tries[key] || 0) + 1;
        note('network (' + result.note + '): asking again in ' + Math.round(wait / 1000) + ' s');
      }
    }
    if (!state.queue.length) { store.set('run', false); state.note = state.note || 'queue done'; }
    state.running = false;
  }

  async function status() {
    const all = await pages('readonly', s => s.getAll());
    const counts = {};
    for (const p of all) { const k = p.kind + ' ' + p.status; counts[k] = (counts[k] || 0) + 1; }
    const minutes = (Date.now() - state.startedAt) / 60000;
    const left = state.queue.length * state.pace.gap / 3600000;
    return {
      running: state.running, queued: state.queue.length, read: counts, thisRun: state.fetched,
      perMinute: state.startedAt && minutes > 0.5 ? Math.round(state.fetched / minutes * 10) / 10 : null,
      paceSeconds: Math.round(state.pace.gap / 100) / 10, blockedAtSeconds: state.pace.blockedAt ? Math.round(state.pace.blockedAt / 100) / 10 : null,
      hoursLeft: Math.round(left * 10) / 10,
      pageRequests: state.pageRequests, last: state.last, secondsSinceLast: state.lastAt ? Math.round((Date.now() - state.lastAt) / 1000) : null,
      waitingFor: state.blockedUntil > Date.now() ? Math.round((state.blockedUntil - Date.now()) / 1000) + ' s' : null, note: state.note,
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
    add, status, lines, save, state, extract, PACE,
    log: () => state.log.slice(),
    start: () => { state.note = ''; run(); return 'started'; },
    stop: () => { state.running = false; store.set('run', false); return 'stopping after the request in flight'; },
    // sets the pace by hand; it goes on learning from there. pace(30, true) also forgets the remembered block pace
    pace: (seconds, forget) => { state.pace = pacer(Object.assign({}, state.pace, { gap: Number(seconds) * 1000, clean: 0 }, forget ? { blockedAt: 0 } : {})); store.set('pace', state.pace); return state.pace; },
    clearQueue: () => { state.queue = []; store.set('queue', []); },
    forget: key => pages('readwrite', s => s.delete(key)),
  };
  // back on the network: no need to wait out the rest of a network error's pause
  if (typeof addEventListener === 'function') addEventListener('online', () => { if (state.pace.errors) state.blockedUntil = Math.min(state.blockedUntil, Date.now() + 5000); });
  // a reload in the middle of a crawl: go on by itself
  if (store.get('run', false) && state.queue.length) run();
})(typeof window !== 'undefined' ? window : globalThis);
