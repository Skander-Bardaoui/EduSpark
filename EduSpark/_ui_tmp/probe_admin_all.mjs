import fs from 'node:fs';
import path from 'node:path';

const BASE = 'http://127.0.0.1:8000';
const CDP = 'http://127.0.0.1:9222';
const OUT = path.resolve('_ui_tmp');
const sessions = JSON.parse(fs.readFileSync(path.join(OUT, 'sessions.json'), 'utf8'));

const PAGES = [
  '/administration/tableau-de-bord/',
  '/administration/perseverance/',
  '/administration/suivi/',
  '/administration/communication/',
  '/administration/forums/',
  '/administration/signalements/',
  '/administration/emploi-du-temps/',
  '/administration/offre-de-formation/',
  '/administration/cours/',
  '/administration/sessions-examen/',
  '/administration/statistiques/',
  '/administration/releves-officiels/',
  '/administration/banques-exercices/',
  '/administration/categories-niveaux/',
  '/administration/etudiants/',
  '/administration/enseignants/',
  '/administration/classes/',
  '/administration/invitations/',
  '/administration/universite/',
  '/administration/parametres/',
];

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
await send('Network.clearBrowserCookies');
await send('Network.setCookie', { name: 'sessionid', value: sessions.admin.sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });

for (const url of PAGES) {
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: BASE + url });
  await sleep(1300);
  const r = await send('Runtime.evaluate', { returnByValue: true, expression: `JSON.stringify({
    h1: (() => { const e = document.querySelector('h1'); return e ? getComputedStyle(e).fontSize : null; })(),
    kpi: (() => { const e = document.querySelector('[class*="text-[20px]"]'); return e ? getComputedStyle(e).fontSize : null; })(),
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth
  })` });
  console.log(url.replace('/administration/', '').replace('/', ''), r.result.value);
}
ws.close();
process.exit(0);
