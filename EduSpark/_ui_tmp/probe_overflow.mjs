import fs from 'node:fs';
const CDP = 'http://127.0.0.1:9222';
const BASE = 'http://127.0.0.1:8000';
const sessions = JSON.parse(fs.readFileSync('sessions.json', 'utf8'));
const list = await fetch(CDP + '/json/list').then(r => r.json());
const target = list.find(t => t.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let seq = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } };
const send = (m, p = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method: m, params: p })); });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
await send('Page.enable'); await send('Network.enable'); await send('Runtime.enable');
for (const w of [1440, 390]) {
  await send('Network.clearBrowserCookies');
  await send('Network.setCookie', { name: 'sessionid', value: sessions.prof.sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 500 });
  await send('Page.navigate', { url: BASE + '/prof/copies/' });
  await sleep(1600);
  const r = await send('Runtime.evaluate', { expression: `JSON.stringify({w:${w}, doc: document.documentElement.scrollWidth, h1: parseFloat(getComputedStyle(document.querySelector('h1')).fontSize)})`, returnByValue: true });
  console.log(r.result.value);
}
ws.close(); process.exit(0);
