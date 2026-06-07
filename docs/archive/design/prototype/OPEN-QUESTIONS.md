# Prototype — Open Questions (post-Phase 3)

> Consolidated questions across all phases. Prioritised P0 (must answer
> before app build) → P2 (defer to v2). Date : 2026-04-13, dernière revue
> 2026-04-15.

---

## P0 · Must answer before Kotlin app build

### 1. ~~Set definitions — single source of truth~~ ✅ Résolu 2026-04-15

**Décision** : option (c) étendue — les sets sont des entités Supabase first-class
(`sets`, `set_members`, `sets_audit`), avec taxonomie 4 types (structurel / curé /
paramétré / dynamique), DSL figé v1, complétion utilisateur 100% locale.
L'enrichissement metadata `coins` (issue_type, series, ruler, theme_code) est un
prérequis. Un outil admin séparé (Vue 3 + shadcn-vue + Vercel + Supabase) est
documenté mais développement différé post-launch v1.

**Pour le proto navigable** : en attente du re-bootstrap du référentiel enrichi, puis
`_shared/sets.js` généré au format final et consommé par `state.js` + `profile.js`
(plus de duplication).

**Voir** :
- [`docs/design/_shared/sets-architecture.md`](../../_shared/sets-architecture.md)
- [`docs/design/admin/README.md`](../../admin/README.md)
- [`docs/DECISIONS.md`](../../../DECISIONS.md) §« Sets d'achievement » et §« Admin tooling »

### 2. Reset confirm UX
`profile-settings` reset uses an inline `.profile-settings-confirm` panel.
The corresponding standalone scene `vault-remove-confirm.html` uses a sheet
modal. Consistency : pick one pattern. Recommendation : sheet modal for
destructive everywhere.

### 3. `scan-detecting` flow integration
The scene now has a route (`/scan/detecting`) but `scan-idle.js` still jumps
straight to `/scan/matched` after 2 s. The intermediate detecting state
should fire ~1.6 s in, then matched ~0.4 s later. Phase 2 didn't wire this
because it was felt to slow down demos. Decide.

### 4. Auto-unlock celebration only fires on `/profile` mount
If a user completes a set then continues scanning instead of going to
profile, the celebration won't fire. Acceptable for prototype but in the
app this should be a toast/inline cue immediately after the matched sheet
adds the coin.

## P1 · Should answer before public beta

### 5. Shared classes still inline (deferred extractions)
The brief listed these for extraction into `components.css`. Phase 3 only
shipped `.toast`, `.btn-danger`, `.btn[disabled]`, `.btn-gold--lg`. The
following remain in scoped form. Each is used 2-3 times and the cost-benefit
of extracting was deemed marginal — re-evaluate before the Kotlin port :
- **`.pager`** — onboarding-1/2/3 dots/dashes
- **`.card--example`** — dashed gold border + EXEMPLE pill (onboarding-2/3)
- **`.panel-debug`** — glass mono debug panels (scan-debug only, single use)
- **`.scene-flash`** — radial flash (used in scan-matched success burst)
- **`.bubble-hint`** — failure tooltip (scan-failure only, single use)
- **`.coin-row`** — compact coin line (vault-home + profile-set, only 2 uses)

### 6. Mobile viewport ≤ 500 px
Acceptance was static (CSS media query, no live device test). Need a real
ngrok run on Pixel 9a + iPhone SE to confirm sheets, sticky bars, and
sparkline render. No issues *expected* given the breakpoint, but unverified.

### 7. Profile-settings reset reload
`reset()` triggers `window.location.reload()` after 120 ms. This is needed
because the seeded SVGs in vault-home cache by eurioId and a soft nav doesn't
re-mount cleanly. Document or fix before app port.

### 8. Marketplace teaser modal close
The sheet uses a backdrop + close button. There's no escape-key handler. Add
in Phase 4 or document as v1.

### 9. Hardcoded metal hexes outside brand palette
`profile-set.html` still has `#F6D3B0`, `#D49A6A`, `#8F5120`, `#C7C6BC`,
`#6F6E63`, `#B7B59A`, `#6B6A52` for the copper / silver / bimetal disc
gradients. They are NOT in the brand palette grep (intentional). Phase 3
attempted to lift these into `--metal-*` tokens in `tokens.css` but the
edit was blocked by a redaction tooling on tokens.css. Workaround : leave
in place, document here, lift in a follow-up commit when tooling allows
direct edits to tokens.css. See DECISIONS §16.

## P2 · Defer to v2

### 10. Theme picker
Disabled with "Bientôt · v2" pill. Decide colour scheme strategy : auto
(prefers-color-scheme), explicit, or none. Will affect every scene's
contrast tokens.

### 11. Self-host Google Fonts
DECISIONS §13. ngrok assumes online ; revisit if offline becomes a goal.

### 12. Coin SVGs vs real images
DECISIONS §11. The Kotlin app should ship Numista BCE images cached on
device. Affects `data.coinSvg()` in the prototype.

### 13. Locale picker (FR/EN/DE/IT)
Currently only persists the preference, no string substitution. Phase 4
needs a tiny i18n layer if we ship multilingual.

### 14. Status bar `9:41`
DECISIONS §7. Keep as-is or randomise per-screenshot ? Keep.
