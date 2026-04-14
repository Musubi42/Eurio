// Injects shared chrome: status bar, version badge, tab bar, home indicator.
// Use via window.EurioChrome.mount(screen).

(function(){
  const svg = (s) => { const t = document.createElement('template'); t.innerHTML = s.trim(); return t.content.firstChild; };

  const STATUSBAR = `
    <div class="statusbar">
      <span>9:41</span>
      <div class="right">
        <svg width="17" height="10" viewBox="0 0 17 10" fill="none"><path d="M1 5.5v-2a1 1 0 011-1h1v5H2a1 1 0 01-1-1v-1z" fill="currentColor"/><rect x="4" y="1" width="3" height="8" rx="0.5" fill="currentColor"/><rect x="8" y="0" width="3" height="10" rx="0.5" fill="currentColor"/><rect x="12" y="0" width="3" height="10" rx="0.5" fill="currentColor"/></svg>
        <svg width="16" height="11" viewBox="0 0 16 11" fill="none"><path d="M8 1.5c2.2 0 4.2.9 5.7 2.3l-1.4 1.4A6 6 0 008 3.5 6 6 0 003.7 5.2L2.3 3.8C3.8 2.4 5.8 1.5 8 1.5zm0 3c1.4 0 2.7.5 3.7 1.4l-1.4 1.4A3.8 3.8 0 008 6.5c-1 0-1.8.3-2.3 0.8L4.3 5.9A5.5 5.5 0 018 4.5zm0 3a1.5 1.5 0 100 3 1.5 1.5 0 000-3z" fill="currentColor"/></svg>
        <svg width="26" height="12" viewBox="0 0 26 12" fill="none"><rect x="0.5" y="0.5" width="22" height="11" rx="3" stroke="currentColor" fill="none"/><rect x="2" y="2" width="18" height="8" rx="1.5" fill="currentColor"/><rect x="23.5" y="4" width="1.5" height="4" rx="0.5" fill="currentColor"/></svg>
      </div>
    </div>`;

  const ISLAND = `<div class="island"></div>`;

  const VERSION_BADGE = `
    <div class="version-badge">
      <span>v0.1.0</span>
      <span class="led"></span>
    </div>`;

  const SCAN_HEADER = `
    <div class="scan-header">
      <div class="label">Scan</div>
      <div class="title">Eurio</div>
    </div>`;

  const TOP_CTL = `
    <div class="top-controls">
      <div class="ctl" title="flash">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
      </div>
      <div class="ctl" title="help">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 015.8 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      </div>
    </div>`;

  const TABBAR = `
    <div class="tabbar">
      <div class="tab">
        <div class="icon-wrap">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>
        </div>
        <span>Coffre</span>
      </div>
      <div class="tab active">
        <div class="icon-wrap">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg>
        </div>
        <span>Scanner</span>
      </div>
      <div class="tab">
        <div class="icon-wrap">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 016-6h4a6 6 0 016 6v1"/></svg>
        </div>
        <span>Profil</span>
      </div>
    </div>`;

  const HOME = `<div class="home-indicator"></div>`;

  window.EurioChrome = {
    inject(screen, opts = {}) {
      screen.insertAdjacentHTML('afterbegin', ISLAND + STATUSBAR);
      if (opts.versionBadge !== false) screen.insertAdjacentHTML('beforeend', VERSION_BADGE);
      if (opts.scanHeader !== false) screen.insertAdjacentHTML('beforeend', SCAN_HEADER);
      if (opts.topCtl !== false) screen.insertAdjacentHTML('beforeend', TOP_CTL);
      if (opts.tabbar !== false) screen.insertAdjacentHTML('beforeend', TABBAR);
      screen.insertAdjacentHTML('beforeend', HOME);
    }
  };
})();
