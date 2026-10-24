import fs from 'node:fs';
import path from 'node:path';

const BASE = 'http://127.0.0.1:8000';
const CDP = 'http://127.0.0.1:9222';
const OUT = path.resolve('_ui_tmp');
const sessions = JSON.parse(fs.readFileSync(path.join(OUT, 'sessions.json'), 'utf8'));

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
await send('Network.clearBrowserCookies');
await send('Network.setCookie', { name: 'sessionid', value: sessions.prof.sessionid, domain: '127.0.0.1', path: '/', httpOnly: true });
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: BASE + '/prof/tableau-de-bord/' });
await sleep(2000);

const JS = `
(() => {
  const out = {};
  // Tailwind loaded?
  out.tailwindLoaded = typeof window.tailwind !== 'undefined';
  // material symbols loaded?
  const ms = document.querySelector('.material-symbols-outlined');
  out.materialSymbols = ms ? getComputedStyle(ms).fontFamily : null;

  const gs = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const c = getComputedStyle(el);
    return { fontSize: c.fontSize, lineHeight: c.lineHeight, fontWeight: c.fontWeight };
  };
  out.h1 = gs('h1');
  out.h2 = gs('h2');
  out.h3 = gs('h3');
  out.body = gs('p');
  // KPI big numbers (font-data-metric with big size)
  const kpi = [...document.querySelectorAll('[class*="data-metric"]')].slice(0,6).map(e => {
    const c = getComputedStyle(e); return { txt: e.textContent.trim().slice(0,20), fs: c.fontSize, fw: c.fontWeight, ff: c.fontFamily.slice(0,40) };
  });
  out.kpi = kpi;
  // headline classes
  out.headlines = [...document.querySelectorAll('[class*="headline"], [class*="display"], [class*="title-md"], [class*="title-lg"], [class*="title-sm"]')].slice(0,15).map(e => {
    const c = getComputedStyle(e); return { cls: (e.className||'').toString().slice(0,60), fs: c.fontSize, lh: c.lineHeight };
  });
  // icon sizes
  const icons = [...document.querySelectorAll('.material-symbols-outlined')].slice(0,40);
  const sizes = {};
  for (const i of icons) {
    const c = getComputedStyle(i);
    const s = c.fontSize;
    sizes[s] = (sizes[s]||0)+1;
  }
  out.iconSizeCounts = sizes;
  out.iconFontFamily = icons[0] ? getComputedStyle(icons[0]).fontFamily : null;
  // nav label sizes
  const navLabel = document.querySelector('aside a, nav a');
  out.navAnchor = navLabel ? (() => { const c = getComputedStyle(navLabel); return { fs: c.fontSize, txt: navLabel.textContent.trim().slice(0,30) }; })() : null;
  // check body font family
  out.bodyFontFamily = getComputedStyle(document.body).fontFamily;
  return JSON.stringify(out, null, 1);
})()
`;
const r = await send('Runtime.evaluate', { expression: JS, returnByValue: true });
console.log(r.result.value);
ws.close();
process.exit(0);
