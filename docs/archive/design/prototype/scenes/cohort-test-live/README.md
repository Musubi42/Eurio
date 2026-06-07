# Cohort test live — canonical proto scene

Source-of-truth visual for the Android `cohortTest` flavor's live-test
screen. Used both as a reference during Compose implementation and as a
playground for further design iterations on the same screen.

This proto is a **standalone page** (not a router-fetched fragment like
the other files in `scenes/`) because it includes its own device-frame
chrome and a design-toggle console outside the device. To view it,
open `index.html` directly — the prototype router does not load it.

## How to view

```bash
# from this directory
python3 -m http.server 4300
# then open http://localhost:4300/
```

Imports `../../_shared/tokens.css` (which itself re-exports
`shared/tokens.css` from the repo root — the only source of truth for
design tokens, never duplicated here).

## What's demoed

A 390 × 844 device mockup of the live-test screen, top-to-bottom:

1. **Status bar** — faux iOS-style, just for ambience.
2. **Progress strip** — N segments colored by state (correct / wrong /
   current with pulse / pending). Test counter + tally on the right.
3. **Hero "à snaper" card** — gold-rimmed coin thumbnail (SVG; the real
   build loads `image_obverse_url` via Coil), eyebrow with flag + year +
   denomination, Fraunces-italic serif title (multi-line), condition chip
   below.
4. **Camera viewfinder** — square. Dark warm gradient + film grain.
   Vignette + ring (SVG): `--scan-idle` when no coin, `--success` green
   with glow when detected. "Pièce détectée" pill fades in. Corner
   brackets + REC indicator + arcface label.
5. **Snap CTA** — pill button, indigo brand, disabled until detection
   (this is the keyboard-matched-bug fix).
6. **Result bottom sheet** — slides up over the camera + CTA when a
   result lands. Verdict band (✓/✗/⚠) with similarity score, "Tu visais"
   compact card, "Le modèle a vu" card if incorrect, expandable top-3
   in mono, "Suivant →" CTA.

## Toggle panel (right rail)

Three segmented controls let you walk through every visual state without
touching code:

- **Détection** — `idle` / `détectée` (toggles ring color + snap button)
- **Résultat** — `hidden` / `correct` / `incorrect` / `error`
- **Condition** — `bright` / `dim` / `tilt` (changes hero chip)

Keyboard shortcuts: <kbd>D</kbd> toggles detection, <kbd>R</kbd> cycles
through result states.

Tapping `Snap` (when ring is detected) reveals the correct result.
Tapping the backdrop or `Suivant →` resets.

## Parity with the Compose implementation

The Android port lives in
`app-android/src/cohortTest/java/com/musubi/eurio/cohorttest/`:

| Proto element       | Compose composable    | File                                       |
|---------------------|-----------------------|--------------------------------------------|
| `.progress-strip`   | `ProgressStrip`       | `components/ProgressStrip.kt`              |
| `.hero` card        | `HeroCoinCard`        | `components/HeroCoinCard.kt`               |
| `.viewfinder`       | `DetectionViewfinder` | `components/DetectionViewfinder.kt`        |
| `.snap-btn`         | `SnapCta`             | `components/SnapCta.kt`                    |
| `.sheet`            | `ResultSheet`         | `components/ResultSheet.kt`                |
| Page orchestration  | `LiveTestsScreen`     | `LiveTestsScreen.kt`                       |

Cross-cutting:

- The viewfinder ring reuses `PhotoGuideOverlay` from the main app's
  `features/scan/components/ScanDebugOverlay.kt` (same vignette + ring
  used in debug snap mode).
- All colors, fonts, radii, spacings come from auto-generated
  `app-android/src/main/java/com/musubi/eurio/ui/theme/{Color,Spacing,Shape,Type}.kt`,
  themselves regenerated from `shared/tokens.css` (R2 — never edit them
  by hand).
- Per-coin display strings (country FR, denomination, eyebrow,
  human title) are pre-computed by `ml/scripts/build_cohort_bundle.py`
  using the helpers in `ml/utils/i18n.py`. The Android client never
  parses an eurio_id slug.

## What's still placeholder in this proto

- **Coin thumbnail** is a stylized SVG. The real Compose UI loads the
  obverse from Supabase via Coil.
- **Camera background** is a gradient, not a real preview.
- **eurio_id title** is hardcoded for the demo. The real backend ships
  pre-computed `display.title` per coin (Fr `name_fr` if present, else
  EN `name_en`/`theme`, else `"Type courant"` for circulation, else a
  slug-derived fallback).

## Files

- `index.html` — full proto (single file, vanilla HTML/CSS/JS)
- `README.md` — this file
