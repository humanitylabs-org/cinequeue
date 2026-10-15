/* Movies: offer installation only when the browser supplies an install prompt. */
(() => {
  'use strict';
  const script = document.currentScript;
  if (!script || (script.dataset.pwaOrigin && location.origin !== script.dataset.pwaOrigin)) return;
  const base = new URL('.', script.src);
  if (!location.pathname.startsWith(base.pathname) || window.top !== window.self) return;
  const name = script.dataset.pwaName || document.title;
  const key = `wizard-pwa-install:${base.origin}${base.pathname}`;

  const read = () => { try { return Number(localStorage.getItem(key)) || 0; } catch (_) { return 0; } };
  const dismiss = () => { try { localStorage.setItem(key, String(Date.now() + 86400000)); } catch (_) {} };
  let deferred = null, host = null, root = null, busy = false, installed = false, dismissedHere = false;
  const clear = () => { host?.remove(); host = root = null; };

  function render() {
    // No event means unknown state. It never warrants an install suggestion.
    // A real install capability outranks an inherited parent-container display mode.
    if (!deferred || installed || dismissedHere || read() > Date.now()) { clear(); return; }
    if (!document.body) { document.addEventListener('DOMContentLoaded', render, {once: true}); return; }
    if (!host) {
      host = document.createElement('aside');
      host.id = 'wizard-pwa-install';
      host.dataset.state = 'ready';
      host.setAttribute('aria-label', `${name} installation`);
      host.style.display = 'block';
      root = host.attachShadow({mode: 'open'});
      root.innerHTML = `<style>
        :host{display:block;color:var(--text,#f4f4f7);font:13px/1.4 system-ui,sans-serif;background:var(--bg-panel,#12121a);border-bottom:1px solid var(--line-strong,rgba(255,255,255,.16))}
        *{box-sizing:border-box}.bar{max-width:1160px;margin:auto;padding:8px 14px;display:flex;align-items:center;gap:10px}.copy{flex:1;min-width:0}.title{font-weight:650}.hint{font-size:11px;color:var(--muted,#999)}
        button{font:600 12px system-ui;min-height:40px;padding:8px 12px;border:1px solid var(--line-strong,#555);border-radius:7px;color:inherit;background:transparent;cursor:pointer;white-space:nowrap}button:focus-visible{outline:2px solid var(--amber,#e2b13c);outline-offset:2px}.action{background:var(--amber,#e2b13c);border-color:transparent;color:#111}.close{min-width:40px;padding:8px;font-size:20px;font-weight:400}
      </style><div class="bar"><div class="copy"><div class="title"></div><div class="hint">Open it directly next time.</div></div><button class="action" type="button">Install</button><button class="close" type="button" aria-label="Dismiss install suggestion">×</button></div>`;
      root.querySelector('.title').textContent = `Install ${name}`;
      document.body.prepend(host);
      root.querySelector('.action').addEventListener('click', act);
      root.querySelector('.close').addEventListener('click', () => { dismissedHere = true; dismiss(); clear(); });
    }
    root.querySelector('.action').textContent = busy ? 'Opening…' : 'Install';
    root.querySelector('.action').disabled = busy;
  }

  async function act() {
    if (busy || !deferred) return;
    const event = deferred;
    busy = true;
    try {
      // Keep the real native prompt inside this click's user activation.
      const pending = event.prompt();
      render();
      await pending;
      const choice = await event.userChoice;
      if (choice?.outcome === 'accepted') installed = true;
      else { dismissedHere = true; dismiss(); }
    } catch (error) {
      // A rejected/consumed capability is not a reason to advertise installation.
      console.warn('Movies installation prompt unavailable', error?.name || 'Error');
    } finally { deferred = null; busy = false; render(); }
  }

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferred = event; installed = false; render();
  });
  window.addEventListener('appinstalled', () => { installed = true; deferred = null; clear(); });

  window.addEventListener('pageshow', render);
  window.addEventListener('storage', event => { if (event.key === key) render(); });
})();
