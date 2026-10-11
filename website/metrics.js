// Tab-scoped anonymous visits. No cookies, fingerprinting or account identifiers.
(() => {
  if (navigator.doNotTrack === '1' || navigator.globalPrivacyControl || !window.crypto?.getRandomValues || window.NASTAUNIK_SITE_NOT_FOUND || new URLSearchParams(location.hash.slice(1)).has('tgWebAppData')) return;
  const token = () => [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
  let visit, source;
  try {
    visit = sessionStorage.getItem('nastaunik:visit');
    if (!/^[a-f0-9]{32}$/.test(visit || '')) { visit = token(); sessionStorage.setItem('nastaunik:visit', visit); }
    source = sessionStorage.getItem('nastaunik:source');
    if (source === null) { source = document.referrer ? new URL(document.referrer).origin : ''; sessionStorage.setItem('nastaunik:source', source); }
  } catch (_) { return; }
  let last;
  const send = () => {
    const path = location.pathname.replace(/\/$/, '') || '/';
    if (path === last || !/^(?:\/|\/(?:library|tracks|consultations|profile|support|rules|privacy)|\/(?:material|course|track)\/[1-9][0-9]*(?:\/lesson\/[1-9][0-9]*)?)$/.test(path)) return;
    last = path;
    fetch('/site/metrics', {method:'POST', credentials:'omit', headers:{'Content-Type':'application/json'}, body:JSON.stringify({visit,event:token(),path,source}), keepalive:true}).catch(() => {});
  };
  for (const name of ['pushState','replaceState']) {
    const original = history[name];
    history[name] = function(...args) { const result = original.apply(this,args); send(); return result; };
  }
  window.addEventListener('popstate',send);
  send();
})();
