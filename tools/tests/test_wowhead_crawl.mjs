// node tools/tests/test_wowhead_crawl.mjs
//
// What the browser crawler (tools/wowhead-pages/crawler.js) keeps of a page: the tabs' numbers, the Quick Facts
// lines, never a name or a comment; and how it tells "Wowhead has no such page" from a block.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const crawler = createRequire(import.meta.url)(join(here, '..', 'wowhead-pages', 'crawler.js'));
const html = readFileSync(join(here, 'fixtures', 'wowhead-item.html'), 'utf8');
let passed = 0;
const test = (name, run) => { run(); passed++; console.log('ok   ' + name); };

test('a literal with bare keys, both quotes, escapes and expressions', () => {
  const text = `{a: 1, 'b': "x\\"y", c: [1, -2.5, 'z'], d: WH.f({q: ']'}, [1]), e: function () { return {}; }, f: true, g: "a" + b, h: null,}`;
  const [value, after] = crawler.readLiteral(text + ', next', 0);
  assert.deepEqual(value, { a: 1, b: 'x"y', c: [1, -2.5, 'z'], f: true, h: null });
  assert.equal(after, text.length);
});

test('only numbers are kept of a row', () => {
  assert.deepEqual(crawler.facts({ id: 5, name: 'Text', cost: [0, [[1901, 30]], 'x'], deep: { n: '12', s: 'no' }, on: true }),
    { id: 5, cost: [0, [[1901, 30]], null], deep: { n: 12 }, on: true });
});

const page = crawler.extract('item', 216616, html, 200, 'https://www.wowhead.com/forever/item=216616/fixture-item');

test('a page: its tabs with counts, vendors with stock and cost', () => {
  assert.equal(page.status, 'ok');
  assert.deepEqual(Object.keys(page.tabs).sort(), ['contained-in-object', 'dropped-by', 'reward-from-q', 'sold-by']);
  assert.deepEqual(page.tabs['dropped-by'], { template: 'npc', rows: [
    { classification: 1, id: 939, location: [33], maxlevel: 38, minlevel: 37, react: [-1, -1], type: 7, count: 57, outof: 460 },
    { id: 978, boss: true, count: 27, outof: 490 }] });
  assert.deepEqual(page.tabs['sold-by'].rows, [{ id: 3413, stock: -1, cost: [1500] }, { id: 3414, stock: 2, cost: [0, [[1901, 30]], [[20558, 3]]] }]);
  assert.deepEqual(page.tabs['contained-in-object'].rows, [{ id: 9001, count: 3, outof: 40 }]);   // data: a variable declared earlier
  assert.deepEqual(page.tabs['reward-from-q'].rows, []);
});

test('no name and no comment is kept anywhere', () => {
  const kept = JSON.stringify(page);
  for (const text of ['Kurzen', 'Vendor', 'Quoted', 'never kept', 'someone', 'Fixture Item', 'Shared Row']) assert.ok(!kept.includes(text), text);
});

test('the Quick Facts lines, a nested list as its label then its children, link texts removed', () => {
  assert.deepEqual(page.quick, ['Level: 13', 'Added in patch 1.60.1', 'Requires:', '[url=/forever/quest=77]', 'Sell Price: [money=125]']);
});

test('map pins are kept as numbers', () => {
  assert.deepEqual(page.map, { 33: [{ count: 2, coords: [[41.2, 9.4], [42, 10]] }] });
});

test('no such page, another page, a block, and a page it does not understand', () => {
  assert.equal(crawler.extract('item', 5, html, 404, '').status, 'missing');
  assert.equal(crawler.extract('item', 5, html, 200, 'https://www.wowhead.com/forever/items?notFound=5').status, 'missing');
  assert.equal(crawler.extract('item', 5, html, 200, '').status, 'missing');            // the page of item 216616 came back
  assert.deepEqual(crawler.extract('item', 5, '<html>blocked</html>', 405, ''), { kind: 'item', id: 5, v: crawler.VERSION, status: 'blocked', http: 405, bytes: 20 });
  assert.equal(crawler.extract('item', 5, 'short', 200, '').status, 'blocked');
  assert.equal(crawler.extract('item', 5, html.replace('g_pageInfo', 'g_other'), 200, '').status, 'odd');
});

test('a quest series: the quests before and after, 0 for the page itself', () => {
  const quest = '<script>var g_pageInfo = {type: 5, typeId: 20};WH.markup.printHtml("[ul][li]Start: [url=\\/forever\\/npc=7]X[\\/url][\\/li][\\/ul]", "infobox-contents-0");'
    + 'WH.markup.printHtml("[table class=series][tr][td]1.[\\/td][td][url=\\/forever\\/quest=10]A[\\/url][\\/td][\\/tr][tr][td]2.[\\/td][td][b]B[\\/b][\\/td][\\/tr][tr][td]3.[\\/td][td][url=\\/forever\\/quest=30]C[\\/url][\\/td][\\/tr][\\/table]", "x");</script> wowhead ' + 'x'.repeat(6000);
  const record = crawler.extract('quest', 20, quest, 200, '');
  assert.deepEqual(record.series, [10, 0, 30]);
  assert.deepEqual(record.quick, ['Start: [url=/forever/npc=7]']);
  const tip = crawler.quickFacts('WH.markup.printHtml("[ul][li][tooltip name=x1]Consumed when used[\\/tooltip][span tooltip=x1 class=tip]Consumable[\\/span][\\/li][\\/ul]", "infobox-contents-0");');
  assert.deepEqual(tip, ['Consumable']);
});

// ------------------------------------------------------------------ the pace
const run = (p, answers) => { const waits = []; for (const a of answers) { const r = crawler.paced(p, a); p = r.p; waits.push(r.wait); } return [p, waits]; };
const pages = n => Array(n).fill('page');

test('clean pages speed it up, step by step, never past the fastest', () => {
  let [p] = run(crawler.pacer(), pages(15));
  assert.equal(p.gap, Math.round(30000 * 0.92));
  [p] = run(p, pages(15 * 60));
  assert.equal(p.gap, crawler.PACE.fastest);
});

test('a block slows it down, waits, and remembers the pace it came at', () => {
  let [p] = run(crawler.pacer({ gap: 12000 }), []);
  let waits;
  [p, waits] = run(p, ['block']);
  assert.deepEqual([p.gap, p.blockedAt, waits[0]], [19200, 12000, 8.5 * 60000]);
  [p, waits] = run(p, ['block']);                       // straight after: twice the wait
  assert.equal(waits[0], 17 * 60000);
  [p] = run(p, pages(15 * 40));                         // then it settles above the remembered pace, not at the fastest
  assert.ok(p.gap >= Math.round(p.blockedAt * crawler.PACE.margin) && p.gap < 19200 * 1.6, String(p.gap));
});

test('the remembered block pace fades after a long clean run at the margin', () => {
  let [p] = run(crawler.pacer({ gap: 14400, blockedAt: 12000 }), pages(crawler.PACE.fadeEvery));
  assert.equal(p.blockedAt, 11400);
});

test('network errors wait longer each time, ease the pace every third, and are no block', () => {
  let [p, waits] = run(crawler.pacer({ gap: 20000 }), ['error', 'error', 'error', 'error']);
  assert.deepEqual(waits, [15000, 30000, 60000, 120000]);
  assert.deepEqual([p.gap, p.blockedAt], [24000, 0]);
  [p, waits] = run(p, Array(10).fill('error'));
  assert.equal(waits.at(-1), crawler.PACE.longestErrorWait);
  [p] = run(p, ['page']);
  assert.equal(p.errors, 0);
});

test('answers: a block, slow down, a network problem, a page', () => {
  assert.equal(crawler.classify(405, 2120, { status: 'blocked' }), 'block');
  assert.equal(crawler.classify(403, 900, { status: 'blocked' }), 'block');
  assert.equal(crawler.classify(429, 100, { status: 'blocked' }), 'slow');
  assert.equal(crawler.classify(502, 100, { status: 'blocked' }), 'error');
  assert.equal(crawler.classify(0, 0, null), 'error');
  assert.equal(crawler.classify(200, 300, { status: 'blocked' }), 'error');   // a cut or foreign answer
  assert.equal(crawler.classify(200, 90000, { status: 'odd' }), 'error');
  assert.equal(crawler.classify(200, 90000, { status: 'ok' }), 'page');
  assert.equal(crawler.classify(404, 9000, { status: 'missing' }), 'page');
});

test('a kept pace outside the limits is brought back inside them', () => {
  assert.equal(crawler.pacer({ gap: 1 }).gap, crawler.PACE.fastest);
  assert.equal(crawler.pacer({ gap: 'x' }).gap, crawler.PACE.start);
  assert.equal(crawler.pacer({ gap: 10 ** 9 }).gap, crawler.PACE.slowest);
});

// ------------------------------------------------------------------ list pages and the whole database
const pad = ' wowhead ' + 'x'.repeat(6000);
const filterInit = 'Filter.init({"page":"npcs","criteria":[{"id":12,"name":"Level"},{"id":37,"options":[[2,">="],[4,"<="]],"name":"ID","num":true}]});';

test('a literal that goes on as an expression is skipped whole', () => {
  const [value] = crawler.readLiteral('{a: 1, extraCols: [].concat(F.x([151], 0)), b: {c: 2}.c, d: 3}', 0);
  assert.deepEqual(value, { a: 1, d: 3 });
});

test('a list page in each of the three ways Wowhead writes one', () => {
  const js = `<script>var listviewitems = [{"id":260166,"name":"Club","quality":2,"source":[4],"sourcemore":[{"n":"Feardred","t":5,"ti":86777}],"dps":40.3,"appearances":{"0":[717884,""]}}];
new Listview({template: 'item', id: 'items', extraCols: [].concat(Filter.cols([151], 0)), note: "8,599 items found (1,000 displayed) - Try filtering", _truncated: 1, data: listviewitems});
new Listview({template: 'generic-model', id: 'itemsgallery', data: listviewitems});</script>` + pad;
  const a = crawler.extractList('items?filter=151;2;200000', js, 200);
  assert.equal(a.status, 'ok'); assert.equal(a.found, 8599); assert.equal(a.truncated, true); assert.equal(a.cr, 151);
  assert.deepEqual(a.rows, [{ id: 260166, quality: 2, source: [4], sourcemore: [{ t: 5, ti: 86777 }], dps: 40.3, appearances: { 0: [717884, null] } }]);   // every number, no name
  const json = `<script>${filterInit}new Listview({"_truncated":1,"note":"15,596 NPCs found (1,000 displayed)","id":"npcs","template":"npc","data":[{"id":263380,"name":"Ghostmaw","minlevel":42,"maxlevel":42,"location":[16591],"react":[-1,-1],"envChange":{"status":"new"}}]});</script>` + pad;
  const b = crawler.extractList('npcs', json, 200);
  assert.deepEqual([b.found, b.truncated, b.cr], [15596, true, 37]);
  assert.deepEqual(b.rows, [{ id: 263380, minlevel: 42, maxlevel: 42, location: [16591], react: [-1, -1], envChange: {} }]);
  const tag = `<script type="application/json" id="data.page.listPage.listviews">[{"id":"objects","template":"object","data":[{"id":105174,"name":"Chest","type":3,"location":[1519]}],"note":"1 object found","totalCount":1}]</script>` + pad;
  const c = crawler.extractList('objects?filter=15:15;2:4;1:200000', tag, 200);
  assert.deepEqual([c.found, c.truncated, c.cr, c.rows], [1, false, 15, [{ id: 105174, type: 3, location: [1519] }]]);
  assert.ok(!JSON.stringify([a, b, c]).match(/Club|Ghostmaw|Chest|Feardred/));
});

test('a list that found nothing, a block, and a page that is no list', () => {
  assert.deepEqual(crawler.extractList('npcs?filter=37:37;2:4;5:9', `<script>${filterInit}</script>` + pad, 200).rows, []);
  assert.equal(crawler.extractList('npcs', 'blocked', 405).status, 'blocked');
  assert.equal(crawler.extractList('npcs', '<p>news</p>' + pad, 200).status, 'odd');
});

test('ranges: the queries, read back', () => {
  assert.equal(crawler.rangeQuery('npcs', 37, 1, 20000), 'npcs?filter=37:37;2:4;1:20000');
  assert.equal(crawler.rangeQuery('npcs', 37, 400001, 2147483647), 'npcs?filter=37;2;400001');
  assert.deepEqual(crawler.parseQuery('npcs?filter=37:37;2:4;1:20000'), { list: 'npcs', cr: 37, lo: 1, hi: 20000 });
  assert.deepEqual(crawler.parseQuery('npcs?filter=37;2;400001'), { list: 'npcs', cr: 37, lo: 400001, hi: 2147483647 });
  assert.deepEqual(crawler.parseQuery('npcs'), { list: 'npcs', cr: null, lo: null, hi: null });
  assert.equal(crawler.parseQuery('npcs?filter=1;1;1'), null);
});

test('a cut list is split into ranges that cover it, a whole one is not', () => {
  const bare = crawler.splitList({ query: 'npcs', truncated: true, found: 15596, cr: 37, rows: [] });
  assert.equal(bare.length, 21);                                   // 20 ranges of 1..400000, and 400001 up
  assert.equal(bare[0], 'npcs?filter=37:37;2:4;1:20000');
  assert.equal(bare[19], 'npcs?filter=37:37;2:4;380001:400000');
  assert.equal(bare[20], 'npcs?filter=37;2;400001');
  const part = crawler.splitList({ query: 'npcs?filter=37:37;2:4;1:20000', truncated: true, found: 1500, cr: 37, rows: [] });
  assert.deepEqual(part, ['npcs?filter=37:37;2:4;1:10000', 'npcs?filter=37:37;2:4;10001:20000']);
  const tail = crawler.splitList({ query: 'npcs?filter=37;2;400001', truncated: true, found: 1200, cr: 37, rows: [{ id: 400500 }, { id: 401000 }] });
  assert.deepEqual(tail, ['npcs?filter=37:37;2:4;400001:400500', 'npcs?filter=37:37;2:4;400501:401000', 'npcs?filter=37;2;401001']);
  assert.deepEqual(crawler.splitList({ query: 'npcs?filter=37:37;2:4;1:20000', truncated: false, found: 10, rows: [] }), []);
  assert.deepEqual(crawler.splitList({ query: 'npcs?filter=37:37;2:4;7:7', truncated: true, found: 1001, cr: 37, rows: [] }), []);
});

test('the pages a whole list names: all npcs, items only for what their page adds, Classic only the shared ids', () => {
  const npcs = { query: 'npcs?filter=37:37;2:4;1:9', status: 'ok', truncated: false, rows: [{ id: 1 }, { id: 2 }, { id: 3 }] };
  assert.deepEqual(crawler.detailsOf(npcs), { kind: 'npc', ids: [1, 2, 3] });
  assert.deepEqual(crawler.detailsOf(npcs, new Set([2])), { kind: 'npc', ids: [2] });
  const items = { query: 'items?filter=151:151;2:4;1:9', status: 'ok', truncated: false, rows: [{ id: 1, source: [2] }, { id: 2, source: [5, 16] }, { id: 3 }, { id: 4, source: [1, 4] }] };
  assert.deepEqual(crawler.detailsOf(items), { kind: 'item', ids: [2] });
  assert.deepEqual(crawler.detailsOf(Object.assign({}, npcs, { truncated: true })), []);
});

test('a Classic page is asked only when the Forever page lacks loot counts', () => {
  assert.equal(crawler.richEnough(null), false);
  assert.equal(crawler.richEnough({ kind: 'npc', status: 'ok', tabs: { drops: { rows: [{ id: 5, count: 3, outof: 20 }] } } }), false);
  assert.equal(crawler.richEnough({ kind: 'npc', status: 'ok', tabs: { drops: { rows: [{ id: 5, count: 30, outof: 200 }] } } }), true);
  assert.equal(crawler.richEnough({ kind: 'quest', status: 'ok', tabs: {} }), true);
  assert.equal(crawler.richEnough({ kind: 'npc', status: 'missing' }), false);
});

test('queue keys: Forever without a branch, Classic and lists with one', () => {
  assert.deepEqual(crawler.parseKey('item:123'), { branch: 'forever', kind: 'item', id: 123, path: '/forever/item=123' });
  assert.deepEqual(crawler.parseKey('classic/npc:7'), { branch: 'classic', kind: 'npc', id: 7, path: '/classic/npc=7' });
  assert.deepEqual(crawler.parseKey('classic/list:npcs?filter=37;2;1'), { branch: 'classic', kind: 'list', query: 'npcs?filter=37;2;1', path: '/classic/npcs?filter=37;2;1' });
  assert.equal(crawler.parseKey('item:0'), null);
  assert.equal(crawler.keyOf('forever', 'npc', 7), 'npc:7');
  assert.equal(crawler.keyOf('classic', 'list', 'npcs'), 'classic/list:npcs');
});

test('an npc page: its drops with every number, the per-mode and per-season counts too, no name', () => {
  const npc = `<script>var g_pageInfo = {type: 1, typeId: 250484};
new Listview({template: 'item', id: 'drops', _totalCount: 995, data: [{"id":818,"name":"Tigerseye","classs":7,"flags2":-2147459072,"count":27,"outof":995,"modes":{"0":{"count":27,"outof":995},"mode":[1]},"itemSeasonPhaseData":{"0":{"0":{"count":27}}},"envChange":{"labels":[]},"stack":[1,1]}]});
new Listview({template: 'item', id: 'sells', data: [{"id":12844,"avail":-1,"cost":[[0,[],[[22484,15]]]]}]});</script>` + pad;
  const record = crawler.extract('npc', 250484, npc, 200, '');
  assert.deepEqual(record.tabs.drops, { template: 'item', rows: [{ id: 818, classs: 7, flags2: -2147459072, count: 27, outof: 995,
    modes: { 0: { count: 27, outof: 995 }, mode: [1] }, itemSeasonPhaseData: { 0: { 0: { count: 27 } } }, envChange: { labels: [] }, stack: [1, 1] }], total: 995 });
  assert.deepEqual(record.tabs.sells.rows, [{ id: 12844, avail: -1, cost: [[0, [], [[22484, 15]]]] }]);
});

test('a range with nothing in it: Wowhead shows its whole list instead, the page is read as empty', () => {
  const whole = `<script type="application/json" id="data.page.listPage.listviews">[{"id":"objects","template":"object","data":[{"id":31},{"id":716529}],"note":"5,127 objects found (1,000 displayed)","totalCount":5127,"_truncated":true}]</script>` + pad;
  const empty = crawler.extractList('objects?filter=15;2;800001', whole, 200);
  assert.deepEqual([empty.rows, empty.found, empty.truncated], [[], 0, false]);
  assert.deepEqual(crawler.splitList(empty), []);
  const inside = crawler.extractList('objects?filter=15:15;2:4;1:800000', whole, 200);   // every row in the range: the list as it is
  assert.deepEqual([inside.rows.length, inside.found, inside.truncated], [2, 5127, true]);
});

console.log(passed + ' tests passed');
