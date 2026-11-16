// Forever Tracker: Wowhead crawl (docs/WOWHEAD-PAGES.md, "The Chrome extension").
//
// Keeps one pinned Wowhead tab, loads the crawler the tracker builds (tools/wowhead-pages/crawler.js with the pages the
// tracker wants next queued, api/wowhead-crawler) into it after every load, and sends the pages it reads to the tracker
// (api/wowhead-push). The crawler keeps its own pace and its queue in the tab's IndexedDB, so a reload, a restart of
// Chrome or a block loses nothing: it goes on where it was. One crawl at a time per address: Wowhead counts them all.
//
// config.json holds the tracker's address and the extension's key; the tracker writes it into the download
// (The Forge › Crawl › Download the Chrome extension).

const HOME = 'https://www.wowhead.com/forever';
const WOWHEAD = /^https:\/\/www\.wowhead\.com\//;

let settings = null;
async function config() {
  if (!settings) {
    const answer = await fetch(chrome.runtime.getURL('config.json'));
    const read = await answer.json();
    if (!/^https?:\/\/\S+$/.test(read.tracker || '') || String(read.key || '').length < 16) throw new Error('config.json has no tracker address or key');
    settings = { tracker: read.tracker.replace(/\/+$/, ''), key: read.key };
  }
  return settings;
}

/** What it last did, for the popup; a problem also shows as "!" on the icon. */
async function note(text, problem = false) {
  await chrome.storage.local.set({ note: text, noteAt: Date.now(), problem });
  await chrome.action.setBadgeText({ text: problem ? '!' : '' });
  await chrome.action.setBadgeBackgroundColor({ color: '#b3261e' });
}

/** The crawl's tab: the one kept, else a pinned Wowhead tab Chrome brought back after a restart, else a new one. */
async function crawlTab(create = true) {
  const { tab } = await chrome.storage.local.get('tab');
  if (tab) {
    try {
      const kept = await chrome.tabs.get(tab);
      if (WOWHEAD.test(kept.url || kept.pendingUrl || '')) return kept;
    } catch (error) { /* closed */ }
  }
  const [pinned] = await chrome.tabs.query({ url: 'https://www.wowhead.com/*', pinned: true });
  if (!pinned && !create) return null;
  const found = pinned || await chrome.tabs.create({ url: HOME, pinned: true, active: false });
  // Chrome's Memory Saver would otherwise put a background tab to sleep, and the crawl with it
  await chrome.tabs.update(found.id, { autoDiscardable: false });
  await chrome.storage.local.set({ tab: found.id });
  return found;
}

/** How long a crawler runs before the tab is reloaded for a new one: the tracker's queue (what it wants read next, in
 *  what order) and its crawler code change while a tab crawls for days. */
const REFRESH_MINUTES = 60;
let fresh = null;   // a crawler fetched just before a reload, for the load that follows it

async function fetchCrawler() {
  const { tracker, key } = await config();
  let answer;
  try { answer = await fetch(tracker + '/api/wowhead-crawler', { headers: { 'X-Push-Token': key }, cache: 'no-store' }); }
  catch (error) { await note('the tracker does not answer at ' + tracker + ': tried again in 5 minutes', true); return null; }
  if (!answer.ok) {
    const said = await answer.json().catch(() => ({}));
    await note('the tracker refused the crawler (' + answer.status + (said.error ? ': ' + said.error : '') + ')', true);
    return null;
  }
  return answer.text();
}

/** Loads the crawler into the tab when it has none; it starts by itself (the tracker's file ends with WHC.start()). A
 *  crawler older than REFRESH_MINUTES (or one an earlier version of the extension loaded, which kept no time) is
 *  replaced: the tab is reloaded, and loads the new one. Only once the tracker has answered, so a crawl goes on while
 *  the tracker is away. */
async function load(tabId) {
  const [{ result: loadedAt } = {}] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: () => window.WHC ? (window.__whcLoadedAt || 0) : null });
  if (loadedAt !== null && loadedAt !== undefined) {
    if (Date.now() - loadedAt < REFRESH_MINUTES * 60000) return;
    const src = await fetchCrawler();
    if (src === null) return;
    fresh = src;
    await note('the tab is reloaded for the tracker\'s latest queue');
    await chrome.tabs.reload(tabId);
    return;
  }
  const src = fresh || await fetchCrawler();
  fresh = null;
  if (src === null) return;
  await chrome.scripting.executeScript({
    target: { tabId }, world: 'MAIN', args: [src],
    func: (code) => { if (window.WHC) return; window.__whcExtension = true; window.__whcLoadedAt = Date.now(); (0, eval)(code); },
  });
  await note('crawler loaded from the tracker');
}

async function start() {
  const { paused } = await chrome.storage.local.get('paused');
  if (paused) return;
  try {
    const tab = await crawlTab();
    if (tab.status === 'complete') await load(tab.id);   // otherwise when it has loaded (tabs.onUpdated)
  } catch (error) {
    await note('could not start: ' + (error && error.message || error), true);
  }
}

chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create('check', { periodInMinutes: 5 }); start(); });
chrome.runtime.onStartup.addListener(() => { chrome.alarms.create('check', { periodInMinutes: 5 }); start(); });
// every 5 minutes: the tab is there (closed: opened again) and has its crawler (lost: loaded again; older than
// REFRESH_MINUTES: the tab reloaded for a new one)
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'check') start(); });
chrome.tabs.onUpdated.addListener(async (tabId, change) => {
  if (change.status !== 'complete') return;
  const { tab, paused } = await chrome.storage.local.get(['tab', 'paused']);
  if (tabId === tab && !paused) load(tabId).catch((error) => note('could not load the crawler: ' + error.message, true));
});

/** Pages the crawler read (through bridge.js) to the tracker; the answer goes back to the crawler, which forgets the
 *  pages only once they are kept. */
async function push(lines) {
  const { tracker, key } = await config();
  let answer;
  try {
    answer = await fetch(tracker + '/api/wowhead-push', {
      method: 'POST', headers: { 'X-Push-Token': key, 'Content-Type': 'application/x-ndjson' }, body: lines.join('\n') + '\n',
    });
  } catch (error) {
    await note('the tracker does not answer: the pages wait in the tab', true);
    return { ok: false, error: 'no answer' };
  }
  const said = await answer.json().catch(() => ({ ok: false, error: 'HTTP ' + answer.status }));
  if (!said.ok) { await note('the tracker refused ' + lines.length + ' page(s): ' + (said.error || answer.status), true); return said; }
  const { sent = 0 } = await chrome.storage.local.get('sent');
  await chrome.storage.local.set({ sent: sent + said.pages, sentAt: Date.now() });
  await note(said.pages + ' page(s) kept by the tracker');
  return said;
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!message) return false;
  if (message.whc === 'pages' && Array.isArray(message.lines) && message.lines.length) {
    push(message.lines).then(reply, (error) => reply({ ok: false, error: String(error && error.message || error) }));
    return true;
  }
  if (message.whc === 'pause' || message.whc === 'resume') {
    const paused = message.whc === 'pause';
    (async () => {
      await chrome.storage.local.set({ paused });
      const tab = await crawlTab(!paused);
      if (tab) {
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', args: [paused],
          func: (stop) => { if (window.WHC) stop ? window.WHC.stop() : window.WHC.start(); } });
        if (!paused) await load(tab.id);
      }
      await note(paused ? 'paused' : 'going on');
    })().then(() => reply({ ok: true }), (error) => reply({ ok: false, error: String(error && error.message || error) }));
    return true;
  }
  return false;
});
