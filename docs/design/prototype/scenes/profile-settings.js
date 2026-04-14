/* scenes/profile-settings.js — sidecar for profile-settings.html (Agent B5-bis)
 *
 * Reads state.prefs, wires toggles/segmented controls/select, handles debug
 * actions (seed-demo, reset) and ephemeral toasts.
 *
 * We extend state.prefs in-place with the new notification/theme keys. No
 * schema migration needed : missing keys read as undefined/false and that
 * maps to our OFF default.
 */

function showToast(root, text) {
  const el = root.querySelector('[data-bind="toast"]');
  if (!el) return;
  el.textContent = text;
  el.classList.add('is-on');
  setTimeout(() => el.classList.remove('is-on'), 1800);
}

function initToggle(btn, initial) {
  const pad = btn.querySelector('.profile-settings-toggle');
  if (pad) pad.setAttribute('aria-pressed', initial ? 'true' : 'false');
}

function setToggle(btn, value) {
  const pad = btn.querySelector('.profile-settings-toggle');
  if (pad) pad.setAttribute('aria-pressed', value ? 'true' : 'false');
}

function initSegmented(group, current) {
  group.querySelectorAll('button[role="radio"]').forEach(btn => {
    btn.setAttribute('aria-pressed', btn.dataset.value === current ? 'true' : 'false');
  });
}

export function mount(ctx) {
  const { state, navigate } = ctx;
  const root = document.querySelector('[data-scene="profile-settings"]');
  if (!root) return;

  const prefs = state.state.prefs || (state.state.prefs = {});

  // ───── Locale (select)
  const localeSel = root.querySelector('[data-bind="pref-locale"]');
  if (localeSel) {
    localeSel.value = prefs.locale || 'fr';
    localeSel.addEventListener('change', () => {
      prefs.locale = localeSel.value;
      state.save();
      showToast(root, 'Langue mise à jour');
    });
  }

  // ───── Theme : disabled in v1 (light only). The control stays visible
  //       with a "Bientôt · v2" pill — see DECISIONS.md §15. No state wire.

  // ───── Notifications toggles
  const TOGGLES = [
    { key: 'notifHunting',   defaultOn: false },
    { key: 'notifSetDone',   defaultOn: false },
    { key: 'notifNewCoins',  defaultOn: false },
    { key: 'telemetry',      defaultOn: false },
  ];
  TOGGLES.forEach(({ key, defaultOn }) => {
    const btn = root.querySelector(`[data-toggle="${key}"]`);
    if (!btn) return;
    const initial = prefs[key] ?? defaultOn;
    initToggle(btn, initial);
    btn.addEventListener('click', () => {
      const next = !prefs[key];
      prefs[key] = next;
      setToggle(btn, next);
      state.save();
    });
  });

  // ───── Catalogue update (segmented)
  const catGroup = root.querySelector('[data-bind="pref-catalog"]');
  if (catGroup) {
    initSegmented(catGroup, prefs.catalogUpdate || 'wifi');
    catGroup.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        prefs.catalogUpdate = btn.dataset.value;
        initSegmented(catGroup, prefs.catalogUpdate);
        state.save();
      });
    });
  }

  // ───── Back
  const backBtn = root.querySelector('[data-action="back"]');
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      if (window.history.length > 1) window.history.back();
      else navigate('#/profile');
    });
  }

  // ───── Export buttons
  root.querySelector('[data-action="export-pdf"]')?.addEventListener('click',
    () => showToast(root, 'Export PDF · bientôt'));
  root.querySelector('[data-action="export-csv"]')?.addEventListener('click',
    () => showToast(root, 'Export CSV · bientôt'));

  // ───── Seed demo
  const seedBtn = root.querySelector('[data-action="seed-demo"]');
  if (seedBtn) {
    seedBtn.addEventListener('click', async () => {
      try {
        if (typeof state.seedDemoCollection === 'function') {
          await state.seedDemoCollection();
        }
        showToast(root, 'Démo ajoutée · 15 pièces');
        setTimeout(() => navigate('#/vault'), 600);
      } catch (err) {
        console.warn('[profile-settings] seed-demo failed', err);
        showToast(root, 'Démo indisponible');
      }
    });
  }

  // ───── Reset (inline confirm)
  const resetBtn = root.querySelector('[data-action="reset"]');
  const confirmBox = root.querySelector('[data-bind="reset-confirm"]');
  const cancelBtn = root.querySelector('[data-action="reset-cancel"]');
  const confirmBtn = root.querySelector('[data-action="reset-confirm"]');

  if (resetBtn && confirmBox) {
    resetBtn.addEventListener('click', () => {
      confirmBox.classList.add('is-on');
    });
  }
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      confirmBox.classList.remove('is-on');
    });
  }
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      try { state.reset(); } catch (err) { console.warn(err); }
      window.location.hash = '#/';
      setTimeout(() => window.location.reload(), 120);
    });
  }

  // ───── About links (mock)
  root.querySelector('[data-action="licenses"]')?.addEventListener('click', (ev) => {
    ev.preventDefault();
    showToast(root, 'Licences · bientôt');
  });
  root.querySelector('[data-action="contact"]')?.addEventListener('click', (ev) => {
    ev.preventDefault();
    showToast(root, 'Contact · bientôt');
  });
}
