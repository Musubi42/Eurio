# Best-frame capture — kickoff

> Faire évoluer le scan d'un "inférer chaque frame indifféremment" vers un
> "détecter la stabilité, verrouiller la caméra, capturer une rafale courte,
> n'inférencer que la meilleure frame, et l'archiver en haute qualité dans
> le coffre utilisateur". Le tout en gardant le ressenti QR-scanner-style.

Lis [`vision.md`](vision.md) en premier — scénario d'usage, principes,
anti-objectifs. Puis [`decisions.md`](decisions.md) pour la liste tranchée
des choix architecturaux. Les chunks numérotés sont des briques
implémentables séparément, dans l'ordre indiqué. Aucun chunk ne doit être
attaqué sans que ses pré-requis soient livrés et audités.

## Plan

| # | Chunk | Pré-req | Statut |
|---|---|---|---|
| 1 | [Debug-bar + HUD live](chunk-1-debug-bar.md) | — | À écrire |
| 2 | [Frame quality scorer](chunk-2-quality-scorer.md) | 1 | À écrire |
| 3 | [Trigger strategies (3 candidats)](chunk-3-trigger-strategies.md) | 1, 2 | À écrire |
| 4 | [AE/AF/AWB lock via Camera2Interop](chunk-4-ae-af-lock.md) | 3 | À écrire |
| 5 | [ImageCapture + archive schema](chunk-5-imagecapture-archive.md) | 4 | À écrire |
| 6 | [State machine refonte ScanViewModel](chunk-6-state-machine.md) | 3, 4, 5 | À écrire |
| 7 | [Bench protocol + replay tooling](chunk-7-bench-protocol.md) | 6 | À écrire |

## Ordre d'implémentation conseillé

```
1 (debug-bar) ──┬──> 2 (quality scorer) ──> 3 (triggers) ──┐
                │                                          ├──> 6 (state machine) ──> 7 (bench)
                └─────────────────> 4 (AE/AF lock) ────────┤
                                              │            │
                                              └─> 5 (archive)
```

La debug-bar (chunk 1) est le **prérequis transverse** : c'est elle qui
permet de tester les triggers et les seuils sans rebuild. Sans elle, on
calibre à l'aveugle. Les chunks 4 et 5 peuvent partir en parallèle de 3
une fois le scorer en place.

## Conventions communes

- **Pas de fallback silencieux.** Si une étape échoue (ex: `takePicture`
  qui timeout, qualité gates non passées), le code émet un état explicite
  consommé par la state machine — jamais de skip muet.
- **Toute frame archivée est traçable.** Chaque row de `coin_captures`
  contient quality_score, métadonnées détecteur, et le mode trigger qui
  l'a sélectionnée — pour replay et A/B à froid.
- **Aucun chunk n'introduit de feature flag user-facing.** La debug-bar
  est un outil dev (uniquement en `BuildConfig.DEBUG`), pas un toggle
  user à laisser traîner. Cf. `feedback_no_debt`.
- **Standards Android uniquement** : CameraX, Camera2Interop, Room, KSP.
  Pas d'invention exotique.

## Mémoires liées

- `feedback_no_debt` — pas de shortcut, on construit propre
- `feedback_chunk_audit_flow` — chunk-par-chunk avec audit visuel
- `feedback_workflow_check_before_ux` — scénario d'usage formulé en
  1 phrase avant code (cf. vision.md §1)
- `feedback_scan_ux` — QR-scanner-style, zéro friction, le best-frame ne
  doit pas dégrader le ressenti continuous
- `project_scan_single_coin` — une pièce à la fois, jamais multi-pièces
