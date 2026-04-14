/* scenes/profile-unlock.js — sidecar for profile-unlock.html (Agent B5-bis)
 *
 * Receives either ?setId=... in the query, or reads state.level.lastUnlock.
 * Fills in the medal glyph, the set title and the subtitle. Falls back on
 * "Série complète France" so the scene is always presentable.
 */

const PRESETS = {
  'circulation-fr':     { glyph: '★', title: 'Série complète France',     sub: 'Série 8 / 8 pièces' },
  'circulation-de':     { glyph: '✦', title: 'Série complète Allemagne',  sub: 'Série 8 / 8 pièces' },
  'eurozone-founding':  { glyph: '◎', title: 'Eurozone founding',         sub: '12 / 12 pays fondateurs' },
  'grande-chasse':      { glyph: '◐', title: 'La grande chasse',          sub: '21 / 21 pays de la zone euro' },
  'commemoratives-2e':  { glyph: '◇', title: 'Dix 2 € commémoratives',    sub: '10 / 10 pièces' },
};

export function mount(ctx) {
  const { query, state, navigate } = ctx;
  const root = document.querySelector('[data-scene="profile-unlock"]');
  if (!root) return;

  const setId =
    (query && query.setId) ||
    (state && state.state && state.state.level && state.state.level.lastUnlock && state.state.level.lastUnlock.id) ||
    'circulation-fr';

  const preset = PRESETS[setId] || PRESETS['circulation-fr'];

  const glyphEl = root.querySelector('[data-bind="medal-glyph"]');
  if (glyphEl) glyphEl.textContent = preset.glyph;

  const titleEl = root.querySelector('[data-bind="set-title"]');
  if (titleEl) titleEl.textContent = preset.title;

  const subEl = root.querySelector('[data-bind="set-sub"]');
  if (subEl) subEl.textContent = preset.sub;

  const cta = root.querySelector('[data-action="continue"]');
  if (cta) {
    cta.addEventListener('click', ev => {
      ev.preventDefault();
      if (navigate) navigate('#/profile');
      else window.location.hash = '#/profile';
    });
  }
}
