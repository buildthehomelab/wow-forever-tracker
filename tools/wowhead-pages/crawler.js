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
  // every number of a page is kept (a page costs seconds of a slow crawl, a byte of disk costs nothing): a tab is cut
  // only past this many rows
  const MAX_ROWS = 20000;

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
        // a literal that goes on as an expression ([].concat(...), {...}.x): the whole is an expression
        const next = space(text, i);
        if (next < text.length && !',}]'.includes(text[next])) { value = SKIPPED; i = skipExpression(text, next); }
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

  /** The Listview configs of a page, three ways Wowhead writes them: `new Listview({...})` as JavaScript or as JSON
   *  (data inline, or `data: someVariable` declared earlier as `var someVariable = [...]`), and a list page's
   *  `<script type="application/json" id="data.page.listPage.listviews">[{...}]</script>`. */
  function configs(html) {
    const out = [];
    const start = /new Listview\(\s*\{/g;
    for (let m; (m = start.exec(html));) {
      let config;
      try { config = readLiteral(html, m.index + m[0].length - 1)[0]; } catch (error) { continue; }
      if (!config || typeof config !== 'object') continue;
      if (config.data === undefined) {
        const named = new RegExp('\\bdata\\s*:\\s*([A-Za-z_$][\\w$]*)\\s*[,}]').exec(html.slice(m.index, m.index + 4000));
        const at = named ? html.search(new RegExp('\\b(?:var|let|const)\\s+' + named[1].replace(/\$/g, '\\$') + '\\s*=\\s*\\[')) : -1;
        if (at >= 0) { try { config.data = readLiteral(html, html.indexOf('[', at))[0]; } catch (error) { /* left without rows */ } }
      }
      out.push(config);
    }
    const json = /<script type="application\/json" id="data\.page\.listPage\.listviews">([\s\S]*?)<\/script>/.exec(html);
    if (json) {
      try { const list = JSON.parse(json[1]); for (const config of Array.isArray(list) ? list : [list]) if (config && typeof config === 'object') out.push(config); } catch (error) { /* not read */ }
    }
    return out;
  }

  /** How many rows a Listview says there are in all ("15,596 NPCs found (1,000 displayed)"), and whether it shows
   *  fewer. */
  function counted(config, shown) {
    let found = typeof config.totalCount === 'number' ? config.totalCount : typeof config._totalCount === 'number' ? config._totalCount : null;
    const note = typeof config.note === 'string' ? /^\s*(\d[\d,]*)\s/.exec(config.note) : null;
    if (found === null && note) found = Number(note[1].replace(/,/g, ''));
    return { found: found ?? shown, truncated: !!config._truncated || (found !== null && found > shown) };
  }

  /** The tabs of a page: {id: {template, rows, total?}}. */
  function listviews(html) {
    const tabs = {};
    for (const config of configs(html)) {
      const id = typeof config.id === 'string' ? config.id : null;
      const template = typeof config.template === 'string' ? config.template : '';
      if (!id || NOT_DATA.has(template) || !/^[\w-]{1,60}$/.test(id) || !Array.isArray(config.data)) continue;
      const data = config.data;
      const rows = data.slice(0, MAX_ROWS).map(facts).filter(r => r && typeof r === 'object' && !Array.isArray(r));
      const tab = { template, rows };
      if (data.length > MAX_ROWS) tab.total = data.length;
      const { found } = counted(config, data.length);
      if (found > rows.length) tab.total = found;
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

  // ------------------------------------------------------------------ list pages and the whole database (pure)
  //
  // A list page (/forever/npcs) shows at most 1,000 rows of a search and says how many it found. Filtered by an id
  // range (?filter=37:37;2:4;1:20000, "ID >= 1 and ID <= 20000") a list is whole when it found no more than it shows;
  // when it is cut, its range is split and asked again. So the lists name every id Wowhead has, a few hundred pages
  // for a whole branch, and the pages of the things are read after.

  /** The lists the whole crawl reads, in this order: the kind of page each row is, the filter criterion of the id
   *  (the list page names it too, see idCriterion), the highest id the first range asks for. */
  const LISTS = {
    npcs: { kind: 'npc', cr: 37, top: 400000 },
    objects: { kind: 'object', cr: 15, top: 800000 },
    quests: { kind: 'quest', cr: 30, top: 120000 },
    items: { kind: 'item', cr: 151, top: 400000 },
  };
  const LAST_ID = 2147483647;
  const PER_LIST = 1000;

  /** The filter criterion a list page names for "ID" (Filter.init's criteria), or null. */
  function idCriterion(html) {
    const at = html.indexOf('Filter.init(');
    const m = at < 0 ? null : /\{[^{}]*?"name"\s*:\s*"ID"[^{}]*\}/.exec(html.slice(at, at + 300000));
    const id = m && /"id"\s*:\s*(\d+)/.exec(m[0]);
    return id ? Number(id[1]) : null;
  }

  /** The query of a list page for ids lo..hi (both kept); lo..LAST_ID is asked as "ID >= lo" only. */
  function rangeQuery(list, cr, lo, hi) {
    return hi >= LAST_ID ? `${list}?filter=${cr};2;${lo}` : `${list}?filter=${cr}:${cr};2:4;${lo}:${hi}`;
  }

  /** {list, cr, lo, hi} of a query rangeQuery made, or of a bare list ('npcs': the whole list, no range yet). */
  function parseQuery(query) {
    const bare = /^([a-z-]+)$/.exec(query);
    if (bare) return { list: bare[1], cr: null, lo: null, hi: null };
    const two = /^([a-z-]+)\?filter=(\d+):\2;2:4;(\d+):(\d+)$/.exec(query);
    if (two) return { list: two[1], cr: Number(two[2]), lo: Number(two[3]), hi: Number(two[4]) };
    const one = /^([a-z-]+)\?filter=(\d+);2;(\d+)$/.exec(query);
    if (one) return { list: one[1], cr: Number(one[2]), lo: Number(one[3]), hi: LAST_ID };
    return null;
  }

  /** A list page as a record: {kind: 'list', query, status, rows, found, truncated, cr}. */
  function extractList(query, html, httpStatus) {
    const record = { kind: 'list', query, v: VERSION };
    if (httpStatus !== 200 || html.length < 5000 || !/wowhead/i.test(html)) return Object.assign(record, { status: 'blocked', http: httpStatus, bytes: html.length });
    const q = parseQuery(query);
    const main = configs(html).find(c => c && Array.isArray(c.data) && typeof c.template === 'string' && !NOT_DATA.has(c.template) && c.template !== 'generic-model');
    // a search that found nothing shows no list at all; a page that is no list page is not understood
    if (!main && !/Filter\.init|listPage|"ID"/.test(html)) return Object.assign(record, { status: 'odd', bytes: html.length });
    const data = main ? main.data : [];
    const rows = [];
    // every number of a row, as on a page: an item's stats too
    for (const row of data) {
      const kept = facts(row);
      if (kept && typeof kept === 'object' && !Array.isArray(kept) && typeof kept.id === 'number' && kept.id > 0) rows.push(kept);
    }
    let { found, truncated } = main ? counted(main, data.length) : { found: 0, truncated: false };
    // a range with nothing in it: Wowhead drops the filter and shows its whole list instead. A row outside the range
    // says so, and the range is empty
    if (q && q.lo !== null && rows.some(r => r.id < q.lo || r.id > q.hi)) { rows.length = 0; found = 0; truncated = false; }
    return Object.assign(record, { status: 'ok', rows, found, truncated, cr: idCriterion(html) ?? (q && q.cr) ?? (LISTS[q && q.list] || {}).cr ?? null });
  }

  /** The queries a cut list is split into: ranges of about 800 ids found each, at least two. A bare list starts at
   *  1..top, and top+1 and up is asked on its own. Nothing when the range cannot be split. */
  function splitList(record) {
    const q = parseQuery(record.query);
    if (!q || !record.truncated) return [];
    const cr = record.cr || (LISTS[q.list] || {}).cr;
    if (!cr) return [];
    let lo = q.lo, hi = q.hi;
    const out = [];
    if (lo === null) {
      lo = 1; hi = (LISTS[q.list] || {}).top || 400000;
      out.push(rangeQuery(q.list, cr, hi + 1, LAST_ID));
    } else if (hi >= LAST_ID) {
      // ids beyond the top: split up to the highest id seen, then the rest
      const seen = Math.max(lo, ...record.rows.map(r => r.id));
      out.push(rangeQuery(q.list, cr, seen + 1, LAST_ID));
      hi = seen;
    }
    if (hi <= lo) return out;
    const parts = Math.min(hi - lo + 1, Math.max(2, Math.ceil(record.found / (PER_LIST * 0.8))));
    const width = Math.ceil((hi - lo + 1) / parts);
    const ranges = [];
    for (let a = lo; a <= hi; a += width) ranges.push(rangeQuery(q.list, cr, a, Math.min(hi, a + width - 1)));
    return ranges.concat(out);
  }

  /** The pages worth reading of a whole list's rows: every npc, object and quest; of items, those whose page says
   *  more than the npc, object and quest pages do (a source other than crafted 1, drop 2, quest 4, vendor 5:
   *  fishing, gathering, containers ...). `only` (a Set): only these ids (Classic: the ids Forever has too). */
  function detailsOf(record, only) {
    const q = parseQuery(record.query);
    const list = q && LISTS[q.list];
    if (!list || record.status !== 'ok' || record.truncated) return [];
    const ids = [];
    for (const row of record.rows) {
      if (only && !only.has(row.id)) continue;
      if (list.kind === 'item' && !(Array.isArray(row.source) && row.source.some(s => ![1, 2, 4, 5].includes(s)))) continue;
      ids.push(row.id);
    }
    return { kind: list.kind, ids };
  }

  /** Whether a Forever page already holds what its Classic page would add: a loot tab with counts of at least 50
   *  looted corpses or opened chests; for a quest, any page at all. A Classic page is read only when not. */
  function richEnough(record) {
    if (!record || record.status !== 'ok') return false;
    if (record.kind === 'quest') return true;
    return Object.values(record.tabs || {}).some(tab => (tab.rows || []).some(row => typeof row.outof === 'number' && row.outof >= 50));
  }

  /** The npc and object pages an item or quest page names that are worth reading soon, as Forever queue keys: the
   *  creatures that drop the item (unless 15 or more do: a world drop), sell it, the chests and nodes it comes from,
   *  the creature or object that starts or ends the quest. Their own pages count better, and a new drop row from an npc
   *  page waits for the item's page anyway. */
  function namedBy(record) {
    if (!record || record.status !== 'ok') return [];
    const out = [];
    const tabs = record.tabs || {};
    if (record.kind === 'item') {
      const wanted = { 'dropped-by': 'npc', 'sold-by': 'npc', 'contained-in-object': 'object', 'mined-from-object': 'object', 'gathered-from-object': 'object' };
      for (const [tab, kind] of Object.entries(wanted)) {
        const rows = (tabs[tab] && tabs[tab].rows) || [];
        if (tab === 'dropped-by' && Math.max(rows.length, (tabs[tab] && tabs[tab].total) || 0) >= 15) continue;
        for (const row of rows) if (Number.isInteger(row.id) && row.id > 0) out.push(kind + ':' + row.id);
      }
    }
    if (record.kind === 'quest') {
      for (const line of record.quick || []) {
        if (!/^(Start|End)\s*:/i.test(line)) continue;
        for (const m of line.matchAll(/\/(npc|object)=(\d+)/g)) out.push(m[1] + ':' + Number(m[2]));
      }
    }
    return [...new Set(out)];
  }

  /** How much a page is worth, most first: the queue is always in this order. The tracker says which pages are which
   *  (Download the crawler); a page nobody named is 'bulk' (Forever) or 'classic'. */
  const TIERS = {
    list: 0,       // the lists: they name everything else
    gap: 1,        // an item a quest, recipe, mount, toy or spell waits for; a quest without giver or ender
    named: 2,      // a creature, vendor or chest a tier-1 page names
    missing: 3,    // a creature or object of the server whose data is missing (no stock, no loot, no trainer list)
    gapOther: 4,   // an item that only lacks a source
    namedOther: 5, // what a tier-4 page names
    bulk: 6,       // the rest of Forever: the rows the server has, measured again
    classic: 8,    // Classic: only where Forever's counts are thin
  };
  const defaultTier = key => /^(classic\/)?list:/.test(key) ? TIERS.list : key.startsWith('classic/') ? TIERS.classic : TIERS.bulk;
  const tierOf = (tiers, key) => (tiers && key in tiers ? tiers[key] : defaultTier(key));
  /** Where a page of $tier goes: after every page worth as much or more. */
  function insertAt(queue, tiers, tier) {
    const i = queue.findIndex(k => tierOf(tiers, k) > tier);
    return i < 0 ? queue.length : i;
  }
  /** What the pages a page names are worth: the tier after its own, for the gaps; nothing (left where they are) else. */
  const namedTier = tier => tier <= TIERS.gap ? TIERS.named : tier <= TIERS.gapOther ? TIERS.namedOther : null;

  /** A queue key: [branch/]kind:id, or [branch/]list:query. No branch is Forever. */
  function parseKey(key) {
    const m = /^(?:([a-z-]+)\/)?([a-z]+):(.+)$/.exec(key);
    if (!m) return null;
    const branch = m[1] || 'forever';
    if (m[2] === 'list') return { branch, kind: 'list', query: m[3], path: '/' + branch + '/' + m[3] };
    const id = Number(m[3]);
    return Number.isInteger(id) && id > 0 ? { branch, kind: m[2], id, path: '/' + branch + '/' + m[2] + '=' + id } : null;
  }
  const keyOf = (branch, kind, idOrQuery) => (branch === 'forever' ? '' : branch + '/') + kind + ':' + idOrQuery;

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

  const api = { namedBy, TIERS, defaultTier, tierOf, insertAt, namedTier, VERSION, PACE, LISTS, readLiteral, facts, listviews, quickFacts, pageInfo, mapper, questSeries, extract, extractList, idCriterion, rangeQuery, parseQuery, splitList, detailsOf, richEnough, parseKey, keyOf, pacer, classify, paced };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  // ------------------------------------------------------------------ the crawl (browser only)

  const BRANCHES = /^(forever|classic)$/;
  const KINDS = /^(item|npc|quest|object|spell|zone|faction|itemset)$/;
  const store = {
    get: (key, fallback) => { try { const v = localStorage.getItem('whc.' + key); return v === null ? fallback : JSON.parse(v); } catch (error) { return fallback; } },
    set: (key, value) => { try { localStorage.setItem('whc.' + key, JSON.stringify(value)); } catch (error) { /* full or blocked */ } },
  };
  const state = {
    queue: [],                            // keys ('item:123', 'classic/npc:7', 'list:npcs'), in order; kept in IndexedDB
    tiers: {},                            // key => tier, for the pages the tracker or a gap's page made worth more
    pace: pacer(store.get('pace', null)), // the learned pace (see paced()), kept between runs
    jitter: 0.15,                         // each wait is the pace, give or take this share
    nextSlot: 0,                          // when the next request to Wowhead may leave, the page's own ones included
    blockedUntil: store.get('blockedUntil', 0),
    tries: {},                            // network errors per page in this run
    fetched: 0, skipped: 0, pageRequests: 0, running: false, last: null, startedAt: 0, lastAt: 0, note: '', log: [],
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

  // IndexedDB "whc": store "pages" holds what was read (key = the queue key), store "meta" the queue and the ids
  // each branch's lists named. A whole crawl is tens of thousands of keys: more than localStorage holds.
  let opening = null;
  function db() {
    return opening ??= new Promise((resolve, reject) => {
      const request = indexedDB.open('whc', 2);
      request.onupgradeneeded = () => {
        const handle = request.result;
        if (!handle.objectStoreNames.contains('pages')) handle.createObjectStore('pages', { keyPath: 'key' });
        if (!handle.objectStoreNames.contains('meta')) handle.createObjectStore('meta');
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  async function tx(name, mode, work) {
    const handle = await db();
    return new Promise((resolve, reject) => {
      const t = handle.transaction(name, mode);
      const request = work(t.objectStore(name));
      t.oncomplete = () => resolve(request && request.result);
      t.onerror = t.onabort = () => reject(t.error);
    });
  }
  const pages = (mode, work) => tx('pages', mode, work);
  const meta = {
    get: key => tx('meta', 'readonly', s => s.get(key)),
    set: (key, value) => tx('meta', 'readwrite', s => s.put(value, key)),
  };
  let saving = null, saveAgain = false;
  /** Keeps the queue; writes coalesce, so a page every few seconds is one write each. */
  function keepQueue() {
    if (saving) { saveAgain = true; return saving; }
    saving = meta.set('queue', state.queue).catch(() => {}).then(() => { saving = null; if (saveAgain) { saveAgain = false; return keepQueue(); } });
    return saving;
  }
  const ready = (async () => {
    const kept = await meta.get('queue');
    // a crawler before 2026-11-15 kept its queue in localStorage
    const old = store.get('queue', null);
    state.queue = Array.isArray(kept) ? kept : Array.isArray(old) ? old : [];
    const tiers = await meta.get('tiers');
    state.tiers = tiers && typeof tiers === 'object' ? tiers : {};
    if (old) { try { localStorage.removeItem('whc.queue'); } catch (error) { /* blocked */ } await keepQueue(); }
  })();

  /** Puts keys in the queue: at its end, or {first: true} at its head (in their order). Keys already queued, and
   *  pages already read unless {again: true}, are left out. */
  async function enqueue(keys, options = {}) {
    await ready;
    const have = options.again ? new Set() : new Set(await pages('readonly', s => s.getAllKeys()));
    const queued = new Set(state.queue);
    const fresh = [];
    for (const key of keys) if (parseKey(key) && !queued.has(key) && !have.has(key)) { queued.add(key); fresh.push(key); }
    if (options.first) state.queue.unshift(...fresh);
    else {
      // each after every page worth as much: a Forever page before the Classic ones already queued
      const byTier = new Map();
      for (const key of fresh) { const t = tierOf(state.tiers, key); if (!byTier.has(t)) byTier.set(t, []); byTier.get(t).push(key); }
      for (const t of [...byTier.keys()].sort((a, b) => a - b)) state.queue.splice(insertAt(state.queue, state.tiers, t), 0, ...byTier.get(t));
    }
    await keepQueue();
    return { added: fresh.length, queued: state.queue.length };
  }

  /** Makes pages worth $tier (a TIERS name or number) and moves them there, in their order: after every page worth as
   *  much or more. A page already worth more stays where it is; pages not queued yet are queued, pages read are not. */
  async function prioritize(keys, tier = TIERS.named) {
    await ready;
    if (typeof tier === 'string') tier = TIERS[tier];
    if (!Number.isInteger(tier)) throw new Error('unknown tier');
    const have = new Set(await pages('readonly', s => s.getAllKeys()));
    const queued = new Set(state.queue);
    const want = [...new Set(keys)].filter(k => parseKey(k) && !have.has(k) && !(queued.has(k) && tierOf(state.tiers, k) <= tier));
    if (!want.length) return { moved: 0, queued: state.queue.length };
    const set = new Set(want);
    state.queue = state.queue.filter(k => !set.has(k));
    for (const key of want) state.tiers[key] = tier;
    state.queue.splice(insertAt(state.queue, state.tiers, tier), 0, ...want);
    await keepQueue();
    await meta.set('tiers', state.tiers).catch(() => {});
    return { moved: want.length, queued: state.queue.length };
  }

  /** Adds pages: add('item', [1, 2]), add('npc', [7], {branch: 'classic'}). */
  async function add(kind, ids, options = {}) {
    const branch = options.branch || 'forever';
    if (!KINDS.test(kind) || !BRANCHES.test(branch)) throw new Error('unknown kind or branch ' + branch + '/' + kind);
    return enqueue(ids.filter(id => Number.isInteger(Number(id)) && Number(id) > 0).map(id => keyOf(branch, kind, Number(id))), options);
  }

  /** The whole database: every list of each branch first (a few hundred pages), then the page of every npc, object
   *  and quest, and of the items whose page adds something (see detailsOf). Classic after Forever, and of Classic
   *  only the ids Forever has too whose Forever page lacks loot counts (see richEnough). The lists go ahead of
   *  whatever was queued; the pages they name go after it. */
  async function full(options = {}) {
    const branches = (options.branches || ['forever', 'classic']).filter(b => BRANCHES.test(b));
    const lists = (options.lists || Object.keys(LISTS)).filter(l => LISTS[l]);
    store.set('plan', { branches, lists, at: Date.now() });
    const keys = [];
    for (const branch of branches) for (const list of lists) keys.push(keyOf(branch, 'list', list));
    return enqueue(keys, { first: true, again: options.again });
  }

  /** After a list page: a cut list is split (the parts go to the head of the queue); a whole one adds its ids to the
   *  branch's set and queues the pages it names. */
  async function afterList(record, branch) {
    const parts = splitList(record);
    if (parts.length) { await enqueue(parts.map(q => keyOf(branch, 'list', q)), { first: true }); return parts.length + ' parts'; }
    const q = parseQuery(record.query);
    const list = q && LISTS[q.list];
    if (!list || record.truncated) return 'kept';
    const named = new Set((await meta.get('ids:' + branch + ':' + list.kind)) || []);
    for (const row of record.rows) named.add(row.id);
    await meta.set('ids:' + branch + ':' + list.kind, [...named]);
    if (!store.get('plan', null)) return record.rows.length + ' ids';
    const only = branch === 'forever' ? null : new Set((await meta.get('ids:forever:' + list.kind)) || []);
    const details = detailsOf(record, only);
    const added = await enqueue(details.ids.map(id => keyOf(branch, details.kind, id)));
    return record.rows.length + ' ids, ' + added.added + ' pages queued';
  }

  /** Reads one page: {answer, record?, note}. A page that does not come within a minute is a network error. */
  async function one(key) {
    const k = parseKey(key);
    if (!k) return { answer: 'skip', note: 'not a key' };
    // a Classic page whose Forever page already says enough is not asked
    if (k.branch !== 'forever' && k.kind !== 'list') {
      const forever = await pages('readonly', s => s.get(keyOf('forever', k.kind, k.id)));
      if (richEnough(forever)) return { answer: 'skip', note: 'Forever has it' };
    }
    let response, html;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 60000);
    try {
      await turn();
      if (!state.running) return { answer: 'stopped' };
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return { answer: 'error', note: 'offline' };
      response = await pageFetch(k.path, { credentials: 'same-origin', redirect: 'follow', signal: abort.signal });
      html = await response.text();
    } catch (error) {
      return { answer: 'error', note: error && error.name === 'AbortError' ? 'no answer within a minute' : String(error) };
    } finally { clearTimeout(timer); }
    const record = k.kind === 'list' ? extractList(k.query, html, response.status) : extract(k.kind, k.id, html, response.status, response.url);
    if (k.branch !== 'forever') record.branch = k.branch;
    const answer = classify(response.status, html.length, record);
    // a page this reader does not understand, three times: kept as 'odd' so that the queue goes on
    const giveUp = answer === 'error' && record.status === 'odd' && (state.tries[key] || 0) >= 2;
    if (answer !== 'page' && !giveUp) return { answer, note: 'HTTP ' + response.status + ', ' + html.length + ' bytes' };
    record.key = key;
    record.fetched = Math.floor(Date.now() / 1000);
    await pages('readwrite', s => s.put(record));
    let said = '';
    if (k.kind === 'list' && record.status === 'ok') said = await afterList(record, k.branch);
    // what a gap's page names comes next: the creatures and chests of an item, who gives or takes a quest
    const worth = k.branch === 'forever' && (k.kind === 'item' || k.kind === 'quest') ? namedTier(tierOf(state.tiers, key)) : null;
    if (worth !== null) {
      const moved = await prioritize(namedBy(record), worth);
      if (moved.moved) said = moved.moved + ' npc and object pages moved up to tier ' + worth;
    }
    return { answer: 'page', record, note: said };
  }

  function note(text) {
    state.note = new Date().toLocaleTimeString() + ' ' + text;
    state.log.push(state.note);
    if (state.log.length > 50) state.log.shift();
  }

  async function run() {
    await ready;
    if (state.running) return;
    state.running = true; state.startedAt = Date.now(); store.set('run', true);
    while (state.running && state.queue.length) {
      const left = state.blockedUntil - Date.now();
      if (left > 0) { await sleep(Math.min(left, 30000)); continue; }
      const key = state.queue[0];
      // a page this crawler cannot handle must not end the crawl unseen: it is asked again later, as after a network
      // error, and the log says why
      let result;
      try { result = await one(key); }
      catch (error) {
        const why = 'this crawler failed on ' + key + ': ' + (error && error.message || error);
        // the third time: set aside (WHC.state.failed), so that one page cannot hold up the queue
        if ((state.tries[key] || 0) >= 2) { note(why + ' (set aside)'); state.failed = (state.failed || []).concat(key); delete state.tries[key]; result = { answer: 'skip' }; }
        else result = { answer: 'error', note: why };
      }
      if (result.answer === 'stopped') break;
      if (result.answer === 'skip') { state.skipped++; const at = state.queue.indexOf(key); if (at >= 0) state.queue.splice(at, 1); keepQueue(); continue; }
      state.last = key + ' ' + (result.record ? result.record.status : result.answer); state.lastAt = Date.now();
      const before = state.pace.gap;
      const { p, wait } = paced(state.pace, result.answer);
      state.pace = p; store.set('pace', p);
      if (result.answer === 'page') {
        delete state.tries[key];
        state.fetched++;
        // a list may have put its parts at the head: take this key out where it is
        const at = state.queue.indexOf(key);
        if (at >= 0) state.queue.splice(at, 1);
        keepQueue();
        if (result.note) note(key + ': ' + result.note);
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

  const shelf = key => { const k = parseKey(key); return k ? (k.branch === 'forever' ? '' : k.branch + ' ') + k.kind : '?'; };

  async function status() {
    await ready;
    const counts = {};
    for (const key of await pages('readonly', s => s.getAllKeys())) counts[shelf(key)] = (counts[shelf(key)] || 0) + 1;
    const queued = {};
    for (const key of state.queue) queued[shelf(key)] = (queued[shelf(key)] || 0) + 1;
    const byTier = {};
    for (const key of state.queue) { const t = tierOf(state.tiers, key); byTier[t] = (byTier[t] || 0) + 1; }
    const minutes = (Date.now() - state.startedAt) / 60000;
    const left = state.queue.length * state.pace.gap / 3600000;
    return {
      running: state.running, queued: state.queue.length, queuedByKind: queued, queuedByTier: byTier, read: counts, thisRun: state.fetched, skipped: state.skipped,
      perMinute: state.startedAt && minutes > 0.5 ? Math.round(state.fetched / minutes * 10) / 10 : null,
      paceSeconds: Math.round(state.pace.gap / 100) / 10, blockedAtSeconds: state.pace.blockedAt ? Math.round(state.pace.blockedAt / 100) / 10 : null,
      hoursLeft: Math.round(left * 10) / 10, plan: store.get('plan', null),
      pageRequests: state.pageRequests, last: state.last, secondsSinceLast: state.lastAt ? Math.round((Date.now() - state.lastAt) / 1000) : null,
      waitingFor: state.blockedUntil > Date.now() ? Math.round((state.blockedUntil - Date.now()) / 1000) + ' s' : null, note: state.note,
    };
  }

  /** The pages read, one JSON line each, sorted by key; {kind, branch, since} narrow it. Read with a cursor, so that
   *  a whole crawl is never all in memory as objects at once. */
  async function lines(options = {}) {
    const handle = await db();
    const out = [];
    await new Promise((resolve, reject) => {
      const request = handle.transaction('pages', 'readonly').objectStore('pages').openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return resolve();
        const p = cursor.value;
        if ((!options.kind || p.kind === options.kind) && (!options.branch || (p.branch || 'forever') === options.branch) && (!options.since || p.fetched >= options.since)) {
          const { key, ...rest } = p;
          out.push([key, JSON.stringify(rest)]);
        }
        cursor.continue();
      };
      request.onerror = () => reject(request.error);
    });
    return out.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0).map(x => x[1]);
  }

  /** Downloads the pages read as wowhead-pages.jsonl (the Imports page and tools/wowhead_pages.py merge read it). */
  async function save(options = {}) {
    const text = (await lines(options)).join('\n') + '\n';
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([text], { type: 'application/x-ndjson' }));
    link.download = options.name || 'wowhead-pages.jsonl';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    return { pages: text.split('\n').length - 1, bytes: text.length };
  }

  /** Downloads only the pages read since the last saveNew() (all, the first time): a long crawl in parts. */
  async function saveNew(options = {}) {
    const since = store.get('savedAt', 0);
    const now = Math.floor(Date.now() / 1000);
    const name = options.name || 'wowhead-pages-' + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '') + '.jsonl';
    const saved = await save(Object.assign({}, options, { since, name }));
    store.set('savedAt', now);
    return saved;
  }

  root.WHC = {
    add, full, prioritize, TIERS, status, lines, save, saveNew, state, extract, PACE,
    log: () => state.log.slice(),
    start: () => { state.note = ''; run(); return 'started'; },
    stop: () => { state.running = false; store.set('run', false); return 'stopping after the request in flight'; },
    // sets the pace by hand; it goes on learning from there. pace(30, true) also forgets the remembered block pace
    pace: (seconds, forget) => { state.pace = pacer(Object.assign({}, state.pace, { gap: Number(seconds) * 1000, clean: 0 }, forget ? { blockedAt: 0 } : {})); store.set('pace', state.pace); return state.pace; },
    clearQueue: async () => { await ready; state.queue = []; await keepQueue(); },
    forget: key => pages('readwrite', s => s.delete(key)),
  };
  // back on the network: no need to wait out the rest of a network error's pause
  if (typeof addEventListener === 'function') addEventListener('online', () => { if (state.pace.errors) state.blockedUntil = Math.min(state.blockedUntil, Date.now() + 5000); });
  // a reload in the middle of a crawl: go on by itself
  ready.then(() => { if (store.get('run', false) && state.queue.length) run(); });
})(typeof window !== 'undefined' ? window : globalThis);
