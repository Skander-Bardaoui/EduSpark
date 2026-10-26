import fs from 'node:fs';
import path from 'node:path';

const BASE = 'http://127.0.0.1:8000';
const CDP = 'http://127.0.0.1:9222';
const OUT = path.resolve('_ui_tmp');
const SHOTS = path.join(OUT, 'shots');
fs.mkdirSync(SHOTS, { recursive: true });

const sessions = JSON.parse(fs.readFileSync(path.join(OUT, 'sessions.json'), 'utf8'));

const PAGES = JSON.parse(process.argv[2] || '[{"role":"admin","name":"dashboard","url":"/administration/tableau-de-bord/"}]');
const WIDTHS = JSON.parse(process.argv[3] || '[1440, 390]');

const list = await fetch(CDP + '/json/list').then((r) => r.json());
const target = list.find((t) => t.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let seq = 0; const pending = new Map();
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result); }
};
const send = (m, p = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method: m, params: p })); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await send('Page.enable');
await send('Network.enable');
await send('Runtime.enable');

for (const pg of PAGES) {
  for (const w of WIDTHS) {
    await send('Network.clearBrowserCookies');
    await send('Network.setCookie', { name: 'sessionid', value: sessions[pg.role].sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: BASE + pg.url });
    await sleep(1800);
    const probe = await send('Runtime.evaluate', { returnByValue: true, expression: `JSON.stringify({
      h1: (() => { const e = document.querySelector('h1'); return e ? getComputedStyle(e).fontSize : null; })(),
      h1txt: (() => { const e = document.querySelector('h1'); return e ? e.textContent.trim().slice(0,40) : null; })(),
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      kpi: (() => { const e = document.querySelector('.font-data-metric'); return e ? getComputedStyle(e).fontSize : null; })()
    })` });
    console.log('probe', pg.name, w, probe.result.value);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const name = `${pg.role}__${pg.name}__${w}.png`;
    fs.writeFileSync(path.join(SHOTS, name), Buffer.from(shot.data, 'base64'));
    console.log('shot', name);
  }
}
ws.close();
process.exit(0);
