# Protocole de session — cohorte scan `mix-owned-42`

> Montage deux-cohortes (2026-07-06) pour agrandir le corpus rejouable
> ([`corpus-spec.md`](./corpus-spec.md)) au-delà des classes entraînables.
> Décisions : cohorte 42 maintenant, entraînement sur les classes prêtes,
> **sessions courtes multiples** (append-only, idempotent).

## 1. Le montage

| Cohorte | id | Contenu | Rôle |
|---|---|---|---|
| **`mix-owned-42`** | `9ecc2cd3f31a` | 42 pièces owned (27 classes ok + 8 warn + 7 block les mieux sourcées ; couvre les 16 de mix-zone-17) | **SCAN** : prescriptions live-tests + corpus. Jamais entraînée directement. |
| **`owned-ready-24`** | `ab28928bcdc2` | 27 pièces / 24 classes strictement ok au preflight | **TRAIN** : produit le modèle du bundle. Itération `base-24c` (`6a52aee52401`). |

Pourquoi deux : `create_iteration` hard-bloque sur toute classe warn/block
(« un run cohorte se veut propre »). Les 15 pièces non entraînées produisent
quand même des frames corpus **valides** (labels vrais, model-agnostic) — elles
plomberont juste le R@1 §I4d, qui se lit alors sur le sous-ensemble entraîné.

La collection (`coins.personal_owned`, **80 pièces**, écrite sur le VPS via
`eurio-api`) est la source des candidates ; 2 pièces de mix-zone-17 y ont été
ajoutées le 2026-07-06 (`es-1999-…-juan-carlos-i-1st-type-1st-map`,
`fr-2008-…-french-presidency`).

## 2. Build du bundle (nouveau : prescriptions ≠ cohorte modèle)

```bash
cd ml && .venv/bin/python -m scripts.build_cohort_bundle \
  --source lab --cohort ab28928bcdc2 --iteration <iid-complétée> \
  --prescribe-cohort 9ecc2cd3f31a --no-sample \
  --out output/cohort_test_<iid>
```

- `--prescribe-cohort` : les 42 pièces sont prescrites, le modèle vient de
  l'itération d'`owned-ready-24`.
- `--no-sample` : obligatoire (sans lui, ≥30 pièces → échantillonnage à 3).
- 42 pièces × 5 conditions (`bright/dim/tilt/glare/inhand`) = **210 tests**.

Puis copier le bundle dans les assets cohort-test et builder l'APK (même flux
que mix-zone-17 ; le build actuel archive raw+crop au SNAP — Lot 2).

## 3. Sessions de scan (découpage recommandé)

- **Session pilote (~15 min)** : 8-10 pièces × 5 conditions — valide le build
  (archivage natif, parité hash device↔PC au premier import, glare/inhand).
- Puis 2-3 sessions de ~70 tests. Le JSONL et le corpus sont append-only :
  on peut s'arrêter/reprendre n'importe quand ; un re-scan d'un test déjà fait
  écrase le best-of §I4d mais **ajoute** une frame au corpus.
- **2-3 SNAPs par test** (chaque SNAP = une frame corpus). Cible totale :
  210 tests × 2+ ≈ **400+ frames** (l'IC95 à n=400 ≈ ±5 pts).

## 4. Après chaque session

```bash
go-task android:cohort-test:pull-tests ITERATION=<iid>   # JSONL + frames + sync §I4d
go-task ml:scan-corpus:import ITERATION=<iid>            # → scan_corpus.db (idempotent)
```

Puis replays (chemins ABSOLUS — le cwd des tâches est `ml/`) : re-répliquer
exp-01 (train_mean), exp-03 (fast vs full, cette fois sans artefact JPEG) et
exp-04 (marge, avec split calibration/validation).

## 5. En parallèle (débloque les 15 non-entraînées)

Enrichment eBay + review des classes warn/block de `mix-owned-42` (8 warn à
4-9 crops, 7 block à 1-3). Quand le preflight passe : élargir la cohorte train
(nouvelle cohorte ou clone) et ré-entraîner — le corpus déjà scanné se rejoue
tel quel sur le nouveau modèle (c'est tout l'intérêt).
