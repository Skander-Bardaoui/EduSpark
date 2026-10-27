/* Thème : Système → Clair → Sombre, mémorisé dans localStorage. */
(function () {
  'use strict';
  var KEY = 'eduspark-theme', ORDER = ['system', 'light', 'dark'];
  var NAME = { system: 'système', light: 'clair', dark: 'sombre' };
  var ICON = { system: 'contrast', light: 'light_mode', dark: 'dark_mode' };
  var root = document.documentElement, mq = matchMedia('(prefers-color-scheme: dark)');

  function pref() {
    try { var v = localStorage.getItem(KEY); return ORDER.indexOf(v) > -1 ? v : 'system'; } catch (e) { return 'system'; }
  }

  function apply(p, announce) {
    var theme = p === 'system' ? (mq.matches ? 'dark' : 'light') : p;
    var label = NAME[p] + (p === 'system' ? ' (' + NAME[theme] + ')' : '');
    root.setAttribute('data-theme', theme);
    root.setAttribute('data-theme-pref', p);
    document.querySelectorAll('[data-theme-toggle]').forEach(function (b) {
      b.setAttribute('aria-label', 'Changer le thème, actuellement : ' + label);
      b.title = 'Thème : ' + label;
      b.querySelector('[data-theme-icon]').textContent = ICON[p];
    });
    if (announce) document.querySelectorAll('[data-theme-status]').forEach(function (s) { s.textContent = 'Thème ' + label + ' activé'; });
    dispatchEvent(new CustomEvent('themechange', { detail: { theme: theme, preference: p } }));
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('[data-theme-toggle]')) return;
    var next = ORDER[(ORDER.indexOf(pref()) + 1) % 3];
    try { localStorage.setItem(KEY, next); } catch (err) {}
    root.classList.add('theme-animating');
    setTimeout(function () { root.classList.remove('theme-animating'); }, 250);
    apply(next, true);
  });
  mq.addEventListener('change', function () { if (pref() === 'system') apply('system'); });
  addEventListener('storage', function (e) { if (e.key === KEY) apply(pref()); });
  apply(pref());
})();
