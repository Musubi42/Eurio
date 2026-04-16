/* bridge.js — postMessage bridge for parity viewer iframe
 *
 * When the proto runs inside an iframe (parity viewer), this module
 * provides a command channel via postMessage. The parent sends
 * navigation/preset commands, and the proto responds with lifecycle events.
 *
 * In standalone mode (direct browser open), this module is a no-op.
 *
 * Protocol:
 *   Parent → Proto:
 *     { type: 'parity:navigate', route: '/vault', preset: 'populated' }
 *
 *   Proto → Parent:
 *     { type: 'parity:ready' }       — proto booted, ready for commands
 *     { type: 'parity:rendered', scene: 'vault-home' }  — scene mounted
 */

const isEmbedded = window.parent !== window;

export function init({ state, navigate }) {
  if (!isEmbedded) return;

  // Signal rendered after each scene mount
  window.addEventListener('scene:mounted', (ev) => {
    window.parent.postMessage({
      type: 'parity:rendered',
      scene: ev.detail?.scene ?? null,
    }, '*');
  });

  // Listen for navigation commands from the parity viewer
  window.addEventListener('message', async (ev) => {
    if (!ev.data || ev.data.type !== 'parity:navigate') return;

    const { route, preset } = ev.data;

    // Apply preset if specified (loads fixture JSON)
    if (preset) {
      try {
        await state.applyPreset(preset);
      } catch (err) {
        console.warn('[bridge] applyPreset failed', preset, err);
      }
    }

    // Navigate to the requested route
    if (route) {
      navigate('#' + route);
    }
  });

  // Signal ready — post a few times to handle the race where the
  // parent's message listener isn't installed yet when the proto boots.
  window.parent.postMessage({ type: 'parity:ready' }, '*');
  setTimeout(() => window.parent.postMessage({ type: 'parity:ready' }, '*'), 200);
  setTimeout(() => window.parent.postMessage({ type: 'parity:ready' }, '*'), 600);
}
