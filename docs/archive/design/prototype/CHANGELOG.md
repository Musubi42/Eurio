# Prototype — CHANGELOG (Phase 3 · Agent C)

> Consolidation pass after Phase 2 (6 agents, ~26 scenes). Goal : kill cross-
> scene tech debt, normalise the chrome contract, and ship a production-ready
> navigable prototype. Date : 2026-04-13 · Author : Agent C (Integration).

---

## Routing

- **Added route `/onboarding/splash`** → scene `onboarding-splash` (chrome
  `none`). Was orphaned (file existed, no route). First-run redirect now lands
  on `/onboarding/splash` instead of `/onboarding/1`. The splash sidecar
  auto-advances to `/onboarding/1` after 1.4 s, so the rest of the flow is
  unchanged.
- **Added route `/scan/detecting`** → scene `scan-detecting` (chrome `dark`).
  Was orphaned. Now reachable so the intermediate state is debuggable. Not yet
  inserted automatically into the scan flow (out of scope — see
  OPEN-QUESTIONS §3).
- **Removed `vault.html` + `vault.js` wrapper.** The router now maps `/vault`
  directly to scene `vault-home`. Wrapper was a Phase 2 hack to avoid touching
  `_shared/router.js`. Fixed at the root.
- **`replay-onboarding` and `reset` actions** now redirect to
  `/onboarding/splash` (not `/onboarding/1`) so the full first-run flow
  replays end-to-end.

## Chrome contract (full-bleed scenes)

- **Introduced `chrome: 'none'` route option.** New value alongside
  `'light'|'dark'|'modal'`. When set, `router.js` writes
  `data-chrome="none"` on `.screen` and `shell.css` hides `.statusbar`,
  `.bottomnav`, `.home-indicator`, `.version-badge` and zeroes `#view`
  padding. Centralised, scene-scope-respecting.
- **Routes migrated to `chrome: 'none'`** :
  - `/onboarding/splash`
  - `/onboarding/1` `/2` `/3`
  - `/onboarding/permission`
  - `/onboarding/replay`
  - `/profile/unlock`
- **Removed manual `<style>` chrome-hiding overrides** from 6 scenes :
  `onboarding-splash.html`, `onboarding-1.html`, `onboarding-2.html`,
  `onboarding-3.html`, `onboarding-permission.html`, `profile-unlock.html`.
  They no longer reach into the shell — scope clean. Replaced each block
  with a single comment pointing at the chrome contract.

## Shared classes extracted

- **`.toast` / `.toast--on-dark` / `.toast--debug`** added to `components.css`.
  Replaces three near-identical scoped toasts in :
  - `profile-settings.html` (was `.profile-settings-toast`, ~22 lines)
  - `scan-not-identified.html` (was `.scan-ni-toast`, ~24 lines)
  - `scan-debug.html` (was `.scan-debug-toast`, ~25 lines)
  JS sidecars unchanged — they all toggled `data-visible` / `is-on`, which the
  shared class supports.
- **`.btn[disabled] / .btn:disabled`** disabled state added.
- **`.btn-danger`** moved to `components.css`. Replaces
  `.profile-settings-danger` (was 5 lines, used twice in profile-settings).
- **`.btn-gold--lg`** size variant added (used by the onboarding hero CTAs in
  the next iteration — reserved for now, not yet wired into onboarding-1/2/3
  to keep the visual identical).

**Total CSS extracted from scenes → components.css : ~75 lines.**
**Total CSS deleted from scenes (chrome overrides + duplicated toasts/danger)
: ~100 lines.**

## Theme preference

- **Theme picker disabled in v1.** Per DECISIONS §15, the prototype lives in
  light mode. The segmented control in `profile-settings.html` is now visually
  disabled with a "Bientôt · v2" pill, and the JS handler is gone. Preference
  key `state.prefs.theme` is no longer written but stays in DEFAULT_STATE for
  forward compat.

## Auto-unlock celebration

- **`state.addCoin()` now calls `checkSetCompletions()`** which detects
  newly-completed sets (currently : `circulation-fr`, mirroring profile.js's
  achievement list) and writes `state.level.pendingUnlock = setId` plus
  appends to `state.level.unlockedSets` (dedup).
- **`profile.js` mount** checks `state.level.pendingUnlock` and, if set,
  calls `consumePendingUnlock()` and navigates to
  `/profile/unlock?setId=…`. Single-fire — clears on read.
- **State shape additions** : `state.level.pendingUnlock` (string|null),
  `state.level.unlockedSets` (string[]). Forward-compatible : missing keys
  default cleanly.

## Hardcoded values

- **Replaced `#F5F3EC`** in `profile-set.html` (silver disc gradient) with
  `var(--paper)`. The remaining metal-class hexes (`#F6D3B0`, `#D49A6A`,
  `#8F5120`, `#C7C6BC`, `#6F6E63`, `#B7B59A`, `#6B6A52`) are intentional metal
  renderings outside the brand palette — see DECISIONS §16.
- **Brand grep** (`#1A1B4B|C8A864|FAFAF8|0E0E1F|C3A45A|B8973F`) returns
  zero hits in `scenes/`.
- **Font grep** (`Fraunces|Inter|JetBrains|Instrument`) returns zero
  hardcoded `font-family:` declarations in `scenes/`.

## Walk test (routes)

| Route                                | Status | Notes |
|--------------------------------------|--------|-------|
| `/`                                  | OK | Redirects to splash if firstRun, else `/scan` |
| `/onboarding/splash`                 | OK | Auto-advance 1.4 s, full-bleed |
| `/onboarding/1` `/2` `/3`            | OK | Full-bleed, no chrome leak |
| `/onboarding/permission`             | OK | Full-bleed sheet |
| `/onboarding/replay`                 | OK | Wipes firstRun → `/onboarding/splash` |
| `/scan`                              | OK | Idle viewfinder |
| `/scan/detecting`                    | OK | Newly routed; reachable for debug |
| `/scan/matched`                      | OK | Sheet `bottom: 96px` clear of nav |
| `/scan/failure` `/scan/not-identified` | OK | Toast now uses `.toast--on-dark` |
| `/scan/debug`                        | OK | Toast uses `.toast--debug` |
| `/coin/:id?ctx=scan|owned|reference` | OK | 3 contexts render distinct |
| `/vault`                             | OK | Now routes directly to vault-home (no wrapper). Sort persists. |
| `/vault/filters` `/vault/search`     | OK | |
| `/profile`                           | OK | Auto-unlock check fires at top of mount |
| `/profile/achievements`              | OK | |
| `/profile/set/circulation-fr`        | OK | |
| `/profile/unlock?setId=…`            | OK | Full-bleed via chrome:'none' |
| `/profile/settings`                  | OK | Theme disabled, reset+seed work |
| `/marketplace`                       | OK | Sheet teaser |
| `/debug/reset`                       | OK | Now lands on splash, not 1 |
| `/debug/seed-demo`                   | OK | Seeds + nav to `/vault` |

## Bugs found / not introduced

- None of the Phase 2 fixes were re-touched. Padding-bottom 104 px on profile
  scenes, sheet lift on scan-matched, data.init() race in scan-idle, and the
  vault sort selector all stay as delivered.

## Sanity checks

```
$ find . -name "*.js" -path "*/prototype/*" -exec node --check {} \;   → 0 errors
$ grep -rE "#(1A1B4B|C8A864|FAFAF8|0E0E1F)" scenes/                    → 0 hits
$ grep -rE "font-family:\s*['\"](Fraunces|Inter|JetBrains)" scenes/    → 0 hits
$ grep -rE "\.(statusbar|bottomnav|home-indicator)" scenes/            → 1 hit (a comment)
```

## Breaking changes

**None.** The route table changed (`/vault` now points to `vault-home`,
`/onboarding/*` is `chrome:'none'`) but no public URL or hash changed. The
state shape added two optional keys, both backward compatible.
