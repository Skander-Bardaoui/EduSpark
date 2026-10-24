import fs from 'node:fs';
import path from 'node:path';
const BASE = 'http://127.0.0.1:8000';
const CDP = 'http://127.0.0.1:9222';
const OUT = path.resolve('_ui_tmp');
const sessions = JSON.parse(fs.readFileSync(path.join(OUT, 'sessions.json'), 'utf8'));
const PAGES = ['/etudiant/tableau-de-bord/','/etudiant/profil/','/etudiant/classe/','/etudiant/progression/','/etudiant/taches/','/etudiant/rendez-vous/','/etudiant/journal/','/etudiant/forums/','/etudiant/annonces/','/etudiant/messagerie/','/etudiant/cours/','/etudiant/emploi-du-temps/','/etudiant/supports-de-cours/','/etudiant/examens/','/etudiant/releves-de-notes/','/etudiant/devoirs/','/etudiant/entrainement/'];
const list = await fetch(CDP + '/json/list').then(r => r.json());
const target = list.find(t => t.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let seq = 0; const pending = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } };
const send = (m, p = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method: m, params: p })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
await send('Page.enable'); await send('Network.enable'); await send('Runtime.enable');
await send('Network.clearBrowserCookies');
await send('Network.setCookie', { name: 'sessionid', value: sessions.etudiant.sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });
let bad = 0;
for (const w of [1440, 390]) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 500 });
  for (const url of PAGES) {
    await send('Page.navigate', { url: BASE + url });
    await sleep(1200);
    const r = await send('Runtime.evaluate', { returnByValue: true, expression: `JSON.stringify({h1:(()=>{const e=document.querySelector('h1');return e?getComputedStyle(e).fontSize:null;})(),scrollW:document.documentElement.scrollWidth,clientW:document.documentElement.clientWidth})` });
    const d = JSON.parse(r.result.value);
    const over = d.scrollW > d.clientW;
    if (over) bad++;
    if (w === 1440) console.log(url.replace('/etudiant/','').replace('/',''), d.h1, over ? 'OVERFLOW' : 'ok');
    else if (over) console.log('  mobile overflow:', url);
  }
}
console.log('bad:', bad);
ws.close(); process.exit(0);
