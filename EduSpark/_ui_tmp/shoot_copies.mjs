import fs from 'node:fs';
import path from 'node:path';
const BASE = 'http://127.0.0.1:8000';
const CDP = 'http://127.0.0.1:9222';
const SHOTS = path.join(process.cwd(), 'shots');
fs.mkdirSync(SHOTS, { recursive: true });
const sessions = JSON.parse(fs.readFileSync('sessions.json', 'utf8'));
const WIDTHS = [[1440,900],[1024,900],[390,844]];
const list = await fetch(CDP + '/json/list').then(r => r.json());
const target = list.find(t => t.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let seq = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } };
const send = (m, p = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method: m, params: p })); });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
await send('Page.enable'); await send('Network.enable');
for (const [w,h] of WIDTHS) {
  await send('Network.clearBrowserCookies');
  await send('Network.setCookie', { name: 'sessionid', value: sessions.prof.sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 500 });
  await send('Page.navigate', { url: BASE + '/prof/copies/' });
  await sleep(1800);
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(SHOTS, `copies__${w}.png`), Buffer.from(shot.data, 'base64'));
  console.log('shot', w);
}
ws.close(); process.exit(0);
