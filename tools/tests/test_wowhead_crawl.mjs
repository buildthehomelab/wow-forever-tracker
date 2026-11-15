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

console.log(passed + ' tests passed');
