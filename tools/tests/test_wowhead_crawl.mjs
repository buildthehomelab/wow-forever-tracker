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
});

console.log(passed + ' tests passed');
