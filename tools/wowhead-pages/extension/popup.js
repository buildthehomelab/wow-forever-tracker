// The popup: what the crawl is doing (the crawler's own WHC.status() in its tab) and a pause.
const facts = document.getElementById('facts');
const toggle = document.getElementById('toggle');
const row = (name, value, problem) => {
  const dt = document.createElement('dt'); dt.textContent = name;
  const dd = document.createElement('dd'); dd.textContent = value; if (problem) dd.className = 'problem';
  facts.append(dt, dd);
};
const ago = (at) => at ? Math.round((Date.now() - at) / 60000) + ' min ago' : 'never';

async function show() {
  const kept = await chrome.storage.local.get(['note', 'noteAt', 'problem', 'sent', 'sentAt', 'paused', 'tab']);
  let config = {};
  try { config = await (await fetch(chrome.runtime.getURL('config.json'))).json(); } catch (error) { /* shown below */ }
  let status = null;
  if (kept.tab) {
    try {
      const [{ result } = {}] = await chrome.scripting.executeScript({ target: { tabId: kept.tab }, world: 'MAIN',
        func: async () => window.WHC ? await window.WHC.status() : null });
      status = result;
    } catch (error) { /* the tab is gone: the next check opens it again */ }
  }
  facts.textContent = '';
  row('Tracker', config.tracker || 'no config.json', !config.tracker);
  row('State', kept.paused ? 'paused' : status ? (status.running ? 'crawling' : 'idle: ' + (status.note || 'queue empty')) : 'starting', !kept.paused && !status);
  if (status) {
    row('Queued', status.queued + ' page(s), about ' + status.hoursLeft + ' h');
    row('Pace', status.paceSeconds + ' s a page' + (status.waitingFor ? ', waiting ' + status.waitingFor + ' after a block' : ''));
    row('Last page', (status.last || '-') + (status.secondsSinceLast != null ? ' (' + status.secondsSinceLast + ' s ago)' : ''));
    if (status.link) row('Waiting to send', String(status.link.toSend));
  }
  row('Sent', (kept.sent || 0) + ' page(s), last ' + ago(kept.sentAt));
  row('Last news', (kept.note || '-') + ' (' + ago(kept.noteAt) + ')', kept.problem);
  toggle.textContent = kept.paused ? 'Go on' : 'Pause';
  toggle.onclick = async () => { toggle.disabled = true; await chrome.runtime.sendMessage({ whc: kept.paused ? 'resume' : 'pause' }); toggle.disabled = false; show(); };
  document.getElementById('show').onclick = async () => { if (kept.tab) { const tab = await chrome.tabs.get(kept.tab).catch(() => null); if (tab) { await chrome.windows.update(tab.windowId, { focused: true }); await chrome.tabs.update(tab.id, { active: true }); } } };
}
show();
