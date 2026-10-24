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
await send('Network.clearBrowserCookies');
await send('Network.setCookie', { name: 'sessionid', value: sessions.prof.sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: BASE + '/prof/profil/' });
await sleep(1800);
const expr = `(() => {
  const q = s => document.querySelector(s);
  const fs = el => el ? parseFloat(getComputedStyle(el).fontSize) : null;
  const h = el => el ? Math.round(el.getBoundingClientRect().height) : null;
  const w = el => el ? Math.round(el.getBoundingClientRect().width) : null;
  const img = q('img[data-alt]');
  return JSON.stringify({
    h1: fs(q('h1')),
    profileName: fs(q('h2')),
    portraitW: w(img), portraitH: h(img),
    uniTitle: fs(q('h4')),
    sectionH3: fs(q('h3')),
    mainPad: getComputedStyle(q('main > div')).paddingLeft,
  });
})()`;
const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
console.log('raw:', JSON.stringify(r, null, 2));
ws.close(); process.exit(0);
