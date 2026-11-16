// Forever Tracker: Wowhead crawl. In every Wowhead tab, beside the page: passes the pages the crawler of this tab
// sends (window.postMessage, crawler.js "the link to the tracker") to the extension, and its answer back. The crawler
// forgets a batch only once the answer says the tracker kept it.
window.addEventListener('message', (event) => {
  const d = event.data;
  if (event.source !== window || !d || d.whc !== 'pages' || !Array.isArray(d.lines)) return;
  chrome.runtime.sendMessage({ whc: 'pages', lines: d.lines }).then((answer) => {
    if (answer && answer.ok) window.postMessage({ whc: 'ack', batch: d.batch, note: answer.pages + ' kept' }, location.origin);
  }).catch(() => { /* the extension was reloaded: the crawler sends the batch again */ });
});
