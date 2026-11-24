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

test('no name and no comment is kept in the facts the imports read', () => {
  const { full, ...facts } = page;
  const kept = JSON.stringify(facts);
  for (const text of ['Kurzen', 'Vendor', 'Quoted', 'never kept', 'someone', 'Fixture Item', 'Shared Row']) assert.ok(!kept.includes(text), text);
});

test('the whole page: names, text, Quick Facts with their links, every tab row whole, what its links name', () => {
  const full = page.full;
  assert.equal(full.name, 'Fixture Item');
  assert.equal(full.title, 'Fixture Item & Co');
  assert.equal(full.description, 'A fixture "item" for tests.');
  assert.equal(full.info.typeId, 216616);
  assert.equal(full.text, 'Fixture Item\nBind on pickup\nRequires Level 13\nDrops in <Stranglethorn>.');
  assert.deepEqual(full.quick, ['Level: 13', 'Added in patch 1.60.1', 'Requires:', '[url=/forever/quest=77 class=q1]A "Quoted" Name[/url]', 'Sell Price: [money=125]']);
  assert.equal(full.tabs['dropped-by'].rows[1].name, 'Kurzen\'s "Agent"');
  assert.equal(full.tabs['dropped-by'].rows[0].pctstack, '{1: 100}');
  assert.equal(full.tabs['sold-by'].rows[0].name, 'Vendor A');
  assert.equal(full.tabs['contained-in-object'].rows[0].name, 'Shared Row');
  assert.deepEqual(full.links, { 1: { 939: { name_enus: 'Kurzen Elite' } }, 3: { 216616: { name_enus: 'Fixture Item', quality: 3 }, 20558: { name_enus: 'Warsong Mark', quality: 1 } } });
  assert.deepEqual(full.map, { 33: [{ count: 2, coords: [[41.2, 9.4], [42, 10]] }] });
  assert.equal(page.v, 4);
});

test('what users wrote is never kept, not even in the whole page', () => {
  const kept = JSON.stringify(page.full);
  for (const text of ['never kept', 'someone', 'comments']) assert.ok(!kept.includes(text), text);
  assert.ok(!('comments' in page.full.tabs));
});

test('of a comment only its rating and what it links to, with what the words around the link say it is', () => {
  const c = 'x var lv_comments0 = [{"body":"Turns in to [url=https:\\/\\/www.wowhead.com\\/forever\\/npc=11705\\/rayan]Rayan[\\/url] in Azshara. Quest starts at [npc=249550] up north. The [npc=5] drops it. Also [item=9] is nice.","rating":2,"deleted":0},'
    + '{"body":"no links","rating":5},{"body":"[npc=77] sells it now","rating":-3},{"body":"[npc=6] gone","rating":1,"deleted":1}];';
  assert.deepEqual(crawler.commentLinks(c), [[2, [[2, 1, 11705], [1, 1, 249550], [3, 1, 5], [0, 3, 9]]], [-3, [[4, 1, 77]]]]);
  assert.ok(!JSON.stringify(crawler.commentLinks(c)).includes('Azshara'));
  assert.deepEqual(crawler.commentLinks('no comments here'), []);
});

test('a whole page past FULL_MAX loses the linked names first, then rows past 2000', () => {
  const rows = Array.from({ length: 30000 }, (_, i) => ({ id: i + 1, name: 'Row ' + 'x'.repeat(200) + i }));
  const big = html.replace('var g_mapperData', 'new Listview({template: \'npc\', id: \'big\', data: ' + JSON.stringify(rows) + '});\nvar g_mapperData');
  const full = crawler.whole(big);
  assert.ok(full.cut);
  assert.ok(!('links' in full));
  assert.equal(full.tabs.big.rows.length, 2000);
  assert.equal(full.tabs.big.total, 30000);   // how many Wowhead has, not how many were kept
  assert.ok(JSON.stringify(full).length <= crawler.FULL_MAX);
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

test('what a gap\'s page names is read soon: its creatures, vendors and chests, not a world drop\'s, a quest\'s giver and ender', () => {
  const item = { kind: 'item', status: 'ok', tabs: {
    'dropped-by': { rows: [{ id: 939 }, { id: 978 }] }, 'sold-by': { rows: [{ id: 3413 }] },
    'contained-in-object': { rows: [{ id: 2843 }] }, 'reward-from-q': { rows: [{ id: 77 }] } } };
  assert.deepEqual(crawler.namedBy(item), ['npc:939', 'npc:978', 'npc:3413', 'object:2843']);
  const world = { kind: 'item', status: 'ok', tabs: { 'dropped-by': { rows: [{ id: 1 }], total: 40 }, 'sold-by': { rows: [{ id: 5 }] } } };
  assert.deepEqual(crawler.namedBy(world), ['npc:5']);
  const quest = { kind: 'quest', status: 'ok', quick: ['Level: 12', 'Start: [url=/forever/npc=253812]', 'End: [url=/forever/object=180001] [url=/forever/npc=7]'] };
  assert.deepEqual(crawler.namedBy(quest), ['npc:253812', 'object:180001', 'npc:7']);
  assert.deepEqual(crawler.namedBy({ kind: 'item', status: 'missing' }), []);
  // a page without a Dropped by tab (item 842, a mount nobody gets): nothing named, no error
  assert.deepEqual(crawler.namedBy({ kind: 'item', status: 'ok', tabs: { 'same-model-as': { rows: [{ id: 1 }] } } }), []);
  assert.deepEqual(crawler.namedBy({ kind: 'item', status: 'ok' }), []);
});

test('the queue is in value order: a page goes after every page worth as much or more', () => {
  const T = crawler.TIERS;
  assert.equal(crawler.defaultTier('list:npcs'), T.list);
  assert.equal(crawler.defaultTier('classic/list:npcs'), T.list);
  assert.equal(crawler.defaultTier('npc:7'), T.bulk);
  assert.equal(crawler.defaultTier('classic/npc:7'), T.classic);
  const tiers = { 'quest:1': T.gap, 'item:5': T.gap, 'item:6': T.gapOther, 'npc:9': T.missing };
  const queue = ['list:npcs', 'quest:1', 'item:5', 'item:6', 'npc:9', 'npc:7', 'object:2', 'classic/npc:7'];
  assert.equal(crawler.insertAt(queue, tiers, T.named), 3);       // after the gaps, before the items that lack a source
  assert.equal(crawler.insertAt(queue, tiers, T.namedOther), 4);  // what those name, before the missing data
  assert.equal(crawler.insertAt(queue, tiers, T.missing), 5);
  assert.equal(crawler.insertAt(queue, tiers, T.bulk), 7);        // a Forever page before the Classic ones
  assert.equal(crawler.insertAt(queue, tiers, T.classic), 8);
  assert.equal(crawler.insertAt(queue, tiers, T.list), 1);
});

test('a crawl kept before the items that lack a source came first is put in the new order', () => {
  const T = crawler.TIERS;
  const kept = { 'item:5': 1, 'npc:9': 3, 'npc:8': 3, 'item:6': 4, 'npc:4': 5, 'npc:7': 6 };
  const tiers = crawler.retier(kept);
  assert.deepEqual(tiers, { 'item:5': T.gap, 'npc:9': T.missing, 'npc:8': T.missing, 'item:6': T.gapOther, 'npc:4': T.namedOther, 'npc:7': T.bulk });
  assert.deepEqual(crawler.sortQueue(['list:items', 'item:5', 'npc:9', 'npc:8', 'item:6', 'npc:4', 'npc:7', 'classic/npc:1'], tiers),
    ['list:items', 'item:5', 'item:6', 'npc:4', 'npc:9', 'npc:8', 'npc:7', 'classic/npc:1']);
});

test('what a later release phase needs comes after the items that lack a source, before the missing data', () => {
  const T = crawler.TIERS;
  assert.ok(T.namedOther < T.later && T.later < T.missing);
  const tiers = { 'item:6': T.gapOther, 'npc:4': T.namedOther, 'npc:9': T.missing };
  assert.equal(crawler.insertAt(['item:6', 'npc:4', 'npc:9', 'npc:7'], tiers, T.later), 2);
  assert.equal(crawler.namedTier(T.later), null);
});

test('what a page names is worth the tier after its own, for the gaps only', () => {
  const T = crawler.TIERS;
  assert.equal(crawler.namedTier(T.gap), T.named);
  assert.equal(crawler.namedTier(T.gapOther), T.namedOther);
  assert.equal(crawler.namedTier(T.missing), null);
  assert.equal(crawler.namedTier(T.bulk), null);
});

test('a creature page keeps its model display ids, numbers only', () => {
  assert.deepEqual(crawler.models('<script>WH.ModelViewer.show({ displayId = 140708 })</script><a data-mv-display-id="140708"></a><a data-mv-display-id="5435">'), [140708, 5435]);
  assert.deepEqual(crawler.models('<p>no model</p>'), []);
  assert.ok(crawler.TIERS.wanted < crawler.TIERS.list);   // pages asked for by hand come first, before the lists of a whole crawl
  const tiers = { 'list:npcs': crawler.TIERS.list, 'list:items': crawler.TIERS.list, 'item:5': crawler.TIERS.gap };
  assert.equal(crawler.insertAt(['list:npcs', 'list:items', 'item:5'], tiers, crawler.TIERS.wanted), 0);
});

test('a list part queued first goes after the pages asked for by hand, not before them', () => {
  const T = crawler.TIERS;
  const tiers = { 'npc:247195': T.wanted, 'npc:247198': T.wanted, 'item:5': T.gap };
  assert.equal(crawler.headAfterWanted(['npc:247195', 'npc:247198', 'list:npcs', 'item:5'], tiers), 2);
  assert.equal(crawler.headAfterWanted(['list:npcs', 'item:5'], tiers), 0);
  assert.equal(crawler.headAfterWanted([], tiers), 0);
});

// a made-up guide in the two forms a guide's table comes in: Wowhead markup in a script (its slashes escaped, as the
// page's JSON writes them) and HTML
const guideMarkup = pad + `<script>WH.markup.printHtml("[h3 toc=\\"Alchemy\\"]Alchemy[\\/h3]\\r\\n[table class=grid]\\r\\n`
  + `[tr background=black][td][b]Item[\\/b][\\/td][td][b]Hand In Zone[\\/b][\\/td][td][b]Level[\\/b][\\/td][\\/tr]\\r\\n`
  + `[tr][td][item=264019][\\/td][td]Wetlands[\\/td][td]Journeyman[\\/td][\\/tr]\\r\\n`
  + `[tr][td][item=264081][\\/td][td]Tanaris[\\/td][td]Expert[\\/td][\\/tr]\\r\\n`
  + `[tr][td][item=264160][\\/td][td]Winterspring[\\/td][td] Artisan [\\/td][\\/tr]\\r\\n`
  + `[tr][td][item=264081][\\/td][td]Tanaris[\\/td][\\/tr]\\r\\n[\\/table]", "guide-body");</script> a guide`;
const guideHtml = pad + '<div class="guide"><table><tr><td><a href="https://www.wowhead.com/forever/item=264020/x">A writ</a></td><td>Kixxle</td><td>Expert</td></tr>'
  + '<tr><td><a href="/forever/item=5">No tier</a></td><td>Someone</td></tr></table></div>';

test('a guide: the items its tables link to, each with the tier its row names, and no text', () => {
  const query = 'professions/craftsmans-writs-overview-recipes-rewards';
  assert.deepEqual(crawler.extractGuide(query, guideMarkup, 200, ''), { kind: 'guide', query, v: crawler.VERSION, status: 'ok',
    rows: [{ id: 264019, tier: 1 }, { id: 264081, tier: 2 }, { id: 264160, tier: 3 }] });
  assert.deepEqual(crawler.extractGuide(query, guideHtml, 200, '').rows, [{ id: 5 }, { id: 264020, tier: 2 }]);
  assert.ok(!JSON.stringify(crawler.extractGuide(query, guideMarkup, 200, '')).match(/Wetlands|Alchemy|Journeyman/));
  assert.equal(crawler.extractGuide(query, 'short', 405, '').status, 'blocked');
  assert.equal(crawler.extractGuide(query, guideHtml, 404, '').status, 'missing');
  assert.equal(crawler.extractGuide(query, pad.replace('wowhead', 'wowhead page'), 200, '').status, 'odd');
  assert.deepEqual(crawler.parseKey('guide:' + query), { branch: 'forever', kind: 'guide', query, path: '/forever/guide/' + query });
  assert.equal(crawler.parseKey('guide:../admin'), null);
  assert.equal(crawler.parseKey('guide:a//b'), null);
});

console.log(passed + ' tests passed');
