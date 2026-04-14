/* scenes/vault.js — routed wrapper that injects vault-home.html
 *
 * The router table (router.js) maps /vault to the scene named "vault".
 * The brief requires the real content to live in vault-home.html. This
 * wrapper bridges both : it fetches vault-home.html, inlines it, then
 * imports and runs vault-home.js mount() with the same ctx.
 */

export async function mount(ctx) {
  const host = document.querySelector('[data-scene="vault-wrapper"]');
  if (!host) return;

  try {
    const res = await fetch('scenes/vault-home.html');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    host.innerHTML = await res.text();
  } catch (err) {
    host.innerHTML = '<p style="padding:32px;color:var(--ink-400);">Coffre indisponible.</p>';
    console.error('[vault] failed to load vault-home.html', err);
    return;
  }

  // Delegate mount
  try {
    const mod = await import('./vault-home.js');
    if (mod && typeof mod.mount === 'function') mod.mount(ctx);
  } catch (err) {
    console.error('[vault] vault-home.js mount failed', err);
  }
}
