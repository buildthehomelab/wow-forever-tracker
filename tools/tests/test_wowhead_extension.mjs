// node tools/tests/test_wowhead_extension.mjs
//
// The Chrome extension's background script (tools/wowhead-pages/extension/background.js) against a fake Chrome: it
// loads the tracker's crawler into a tab that has none, leaves a young one alone, and reloads the tab for a new one
// once the crawler it runs is an hour old or came from an extension that kept no time, never while the tracker is away.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'wowhead-pages', 'extension', 'background.js'), 'utf8');
let passed = 0;
const test = async (name, run) => { await run(); passed++; console.log('ok   ' + name); };

/** A fresh background script with a fake chrome and fetch: [its listeners, what it did, the tab's window]. */
function boot({ page = {}, tracker = true } = {}) {
  const did = { reloads: 0, fetched: 0, injected: 0, notes: [] };
  const win = page;
  const listeners = {};
  const on = (name) => ({ addListener: (f) => { listeners[name] = f; } });
  const storage = { tab: 7 };
  const chrome = {
    runtime: { getURL: (p) => 'ext://' + p, onInstalled: on('installed'), onStartup: on('startup'), onMessage: on('message') },
    storage: { local: { get: async (keys) => { const out = {}; for (const k of [].concat(keys)) if (k in storage) out[k] = storage[k]; return out; }, set: async (o) => Object.assign(storage, o) } },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    alarms: { create: () => {}, onAlarm: on('alarm') },
    tabs: {
      get: async (id) => ({ id, url: 'https://www.wowhead.com/forever', status: 'complete' }),
      query: async () => [], create: async () => ({ id: 7 }), update: async () => {},
      reload: async () => { did.reloads++; for (const k of Object.keys(win)) delete win[k]; },
      onUpdated: on('updated'), onRemoved: on('removed'),
    },
    scripting: {
      executeScript: async ({ func, args = [] }) => {
        const before = !!win.WHC;
        const result = new Function('window', 'args', 'const f = ' + func.toString().replace(/\(0, eval\)\(code\)/, 'window.WHC = {}') + '; return f(...args);')(win, args);
        if (!before && win.WHC) did.injected++;
        return [{ result }];
      },
    },
  };
  const fetch = async (url) => {
    if (url === 'ext://config.json') return { ok: true, json: async () => ({ tracker: 'http://tracker:8090', key: 'k'.repeat(20) }) };
    did.fetched++;
    if (!tracker) throw new Error('down');
    return { ok: true, status: 200, text: async () => 'WHC.start()' };
  };
  new Function('chrome', 'fetch', source)(chrome, fetch);
  const origSet = chrome.storage.local.set;
  chrome.storage.local.set = async (o) => { if (o.note) did.notes.push(o.note); return origSet(o); };
  return { listeners, did, win };
}
const tick = () => new Promise((r) => setTimeout(r, 0));
const alarm = async (b) => { b.listeners.alarm({ name: 'check' }); for (let i = 0; i < 20; i++) await tick(); };

await test('a tab with no crawler gets one, with the time it was loaded', async () => {
  const b = boot();
  await alarm(b);
  assert.equal(b.did.injected, 1);
  assert.equal(b.did.reloads, 0);
  assert.ok(Date.now() - b.win.__whcLoadedAt < 5000);
});

await test('a crawler younger than an hour is left alone: nothing is asked of the tracker', async () => {
  const b = boot({ page: { WHC: {}, __whcLoadedAt: Date.now() - 30 * 60000 } });
  await alarm(b);
  assert.deepEqual([b.did.fetched, b.did.reloads, b.did.injected], [0, 0, 0]);
});

await test('an hour-old crawler: the tab is reloaded, and loads the crawler fetched before it, without asking again', async () => {
  const b = boot({ page: { WHC: {}, __whcLoadedAt: Date.now() - 61 * 60000 } });
  await alarm(b);
  assert.deepEqual([b.did.fetched, b.did.reloads], [1, 1]);
  b.listeners.updated(7, { status: 'complete' });
  for (let i = 0; i < 20; i++) await tick();
  assert.deepEqual([b.did.fetched, b.did.injected], [1, 1]);
  assert.ok(b.win.WHC && b.win.__whcLoadedAt);
});

await test('a crawler an earlier extension loaded (no time kept) is replaced at once', async () => {
  const b = boot({ page: { WHC: {}, __whcExtension: true } });
  await alarm(b);
  assert.equal(b.did.reloads, 1);
});

await test('with the tracker away the old crawler goes on: the tab is not reloaded', async () => {
  const b = boot({ page: { WHC: {}, __whcLoadedAt: Date.now() - 2 * 3600000 }, tracker: false });
  await alarm(b);
  assert.deepEqual([b.did.fetched, b.did.reloads], [1, 0]);
  assert.ok(b.win.WHC);
});

console.log(passed + ' tests passed');
