# Améliorer les résultats de scan — vision & campagne d'expérimentation

> **But du dossier.** Le scan est l'acte central d'Eurio (cf. `CLAUDE.md` §Mission).
> Ce dossier est le **hub d'une campagne d'expérimentation** pour pousser la
> qualité du scan **en vrai, sur de vrais téléphones** — au-delà du pipeline
> actuel. On y teste **des modèles différents**, **des façons de scanner
> différentes**, et on **mesure honnêtement**. Ce README est la vision + la carte ;
> les expériences vivent dans des fichiers frères (à créer au fil de l'eau).
>
> **État : graine (2026-07-06).** Posé pour être repris (session PC). Rien ici
> n'est tranché — c'est le cadre, pas la décision. Ne pas dupliquer les docs
> existants : on les **référence** (§7).

---

## 1. North Star — ce que « bon scan » veut dire

Un utilisateur pointe sa caméra sur une pièce, en conditions réelles (lumière de
salon, pièce sale/usée/tiltée, en main, reflets métalliques), et l'app
l'identifie **vite et juste**. Le modèle est **on-device** (coût marginal ≈ 0,
offline-first, cf. `research/cloud-vs-ondevice-costs.md` — décision 100%
on-device). La contrainte dure, c'est le **parc de téléphones** :

| Tier device | Exemple | Budget réaliste | Rôle dans la stratégie |
|---|---|---|---|
| **Low** (≥ 5 ans, entrée de gamme) | ~2019, 2-3 Go RAM, pas de NPU | modèle **léger quantifié**, latence tolérable | le modèle **universel** doit y tomber |
| **Mid** | milieu de gamme récent | marge confortable | cible principale du volume |
| **High / flagship récent** | **Pixel 9A** (cible perso de test), flagships 2024-2025, NPU/GPU | peut faire tourner **du SOTA plus lourd** | régime **premium** : meilleure précision quand le device le permet |

**Deux régimes assumés** (à valider) :
1. **Modèle universel** — tombe **partout**, du low-end de 2019 au flagship. Plancher de qualité garanti.
2. **Modèle premium** — SOTA plus gros, **activé seulement** sur les devices capables (détection de capacité). Meilleure précision là où le hardware suit.

> ⚠️ Cible de vérité perso : **ça doit au moins bien tourner sur le Pixel 9A** (device de test principal). Tout ce qu'on teste doit passer ce filtre d'abord.

---

## 2. Baseline — ce qu'on a AUJOURD'HUI (point de départ à battre)

Le pipeline de scan on-device actuel (à ne pas ré-inventer, à **mesurer et
dépasser**) :

```
Frame CameraX (portrait)
  → Détection : YOLO11-nano (320²) ∥ OpenCV HoughCircles → merge IoU
  → Rerank : ArcFace on-device (embedding) → cosine sim au catalogue → top-K
  → Consensus buffer (sticky) → révélation
```

- **Reconnaissance = embedding matching ArcFace**, pas classification (ajouter une
  pièce ≠ re-trainer, cf. `research/embedding-vs-classification.md`). Entraînement
  maille `design_group`, few-shot metric learning (cf. `research/arcface-few-shot.md`,
  mémoire `project_arcface_design_group_label`).
- **DINO vitl14** = outil **admin** de suggestions (review), **pas** on-device.
- Backbone embarqué historiquement visé : **MobileNetV3-Small** (`research/scan-approaches.md`)
  → **c'est justement un des axes à ré-ouvrir** (§4).
- **Trou connu et documenté** : le **banc d'éval est optimiste** (R@1≈100% en labo
  car test = augmentations de Numista, non disjoint et non représentatif). Sans
  banc honnête, toute « amélioration » est mesurée dans le vide
  (`research/ml-scalability-phases/phase-4-subcenter-evalbench.md`). **C'est le
  prérequis n°1 de cette campagne.**

---

## 3. Les 3 piliers de la qualité de scan

La qualité end-to-end = **capture × modèle × mesure**. Un maillon faible plafonne
tout.

### Pilier A — CAPTURE (déjà cadré ailleurs → on LIE, on ne duplique pas)
La mécanique « quelle frame on infère » est le projet **[`best-frame-capture/`](../best-frame-capture/README.md)** :
stabilité → verrou AE/AF → rafale courte → n'inférer que la meilleure frame →
archive HQ. Inclut déjà un **quality scorer** (chunk-2) et un **protocole de
bench** (chunk-7).
- **À rattacher ici** : **détection de photo de mauvaise qualité** (flou de bougé,
  hors-focus, surexposition/reflet, pièce hors-cadre) → **proposer de refaire la
  photo** plutôt que d'inférer une frame pourrie. (Recouvre partiellement le
  quality scorer best-frame ; à unifier, pas à re-faire.)
- **Robustesse capture** : les 2 bugs bloquants de **F03**
  (`../hardening-2026-07/03-android-robustesse.md`) — permission caméra jamais
  re-demandée, échec de bind CameraX **avalé** — sont un **prérequis** : un scan
  qui rate à cause de la caméra ne doit pas être lu comme un problème de modèle.

### Pilier B — MODÈLE (le cœur NEUF de ce dossier)
Explorer **quel modèle** on met sur le téléphone (§4). C'est ici que vit
l'essentiel de la nouveauté : tester des backbones, du SOTA, le tiering device.

### Pilier C — MESURE (sans quoi rien n'est vrai)
Un **banc d'éval honnête in-the-wild** (photos caméra Android, sale/tilté/mauvaise
lumière, **disjoint** du training) — cf. phase-4. On ne compare **aucun** modèle ni
approche sans lui. Métriques cibles : **R@1 / R@5 in-the-wild**, **latence par
tier device**, **taux d'abstention** (dire « je ne sais pas » plutôt que se
tromper), robustesse face/usure/tilt.

---

## 4. Axes d'expérimentation MODÈLE (le backlog à remplir)

> Chaque axe → un fichier frère quand on l'attaque (ex. `exp-backbones.md`). Ici =
> la liste des pistes, pas les résultats.

- **Backbones embarqués** : re-benchmarker MobileNetV3-Small (baseline) vs
  EfficientNet-Lite / MobileViT / EdgeNeXt / (SOTA mobile récents) — précision ↔
  latence ↔ taille APK, par tier device.
- **Modèle premium flagship** : un backbone plus gros/meilleur activé seulement si
  NPU/GPU dispo (détection de capacité device). Combien de précision on gagne ? À
  quel coût de complexité (2 modèles à maintenir + 2 sets d'embeddings) ?
- **Quantization / delegates** : INT8 vs FP16, NNAPI/GPU delegate LiteRT, impact
  précision vs latence — surtout côté low-tier.
- **Embedding dim & tête** : 128 vs 256 ; sub-center ArcFace (variation intra-classe
  des photos eBay, phase-4) ; effet sur la séparabilité en vrai.
- **Normalisation d'entrée** : le crop/mask/resize on-device doit MATCHER le
  training (cf. mémoire `project_scan_normalization`) — vérifier qu'un changement de
  modèle ne casse pas la parité Python↔Kotlin.
- **Abstention / seuils** : calibrer « pas sûr → ne propose pas » par device/lumière
  (précision d'abord — un faux positif coûte la confiance).

---

## 5. Protocole — comment on tranche (pas d'opinion sans mesure)

1. **Banc honnête d'abord** (pilier C) : sans lui, on ne lance aucune comparaison.
2. **Un axe = une expérience isolée** : on change **une** variable (backbone, ou
   quantization, ou capture) et on mesure le delta sur le même banc.
3. **Mesure multi-device** : au minimum **Pixel 9A** + un device low/mid-tier (réel
   ou profil de latence). Un gain de précision qui triple la latence low-end n'est
   pas un gain universel.
4. **Décision tranchée écrite** dans un `decisions.md` (comme best-frame-capture) —
   jamais enfouie dans le code (cf. `CLAUDE.md` Interdictions).

---

## 6. Anti-objectifs (ce que ce dossier n'est PAS)

- ❌ Pas de scan cloud/serveur (décision 100% on-device tenue).
- ❌ Pas de sur-optimisation labo (R@1=100% sur Numista augmenté = piège, cf. §2).
- ❌ Pas de duplication de `best-frame-capture/` (capture) ni des `research/*`
  (décisions déjà prises) — on **référence** et on **dépasse**.
- ❌ Pas de refonte du référentiel / de l'entraînement admin ici (autres dossiers).

---

## 7. Cartographie — docs existants à lire avant d'attaquer

| Sujet | Doc |
|---|---|
| Pipeline détection on-device actuel | `research/detection-pipeline-unified.md` |
| Embedding vs classification (pourquoi ArcFace) | `research/embedding-vs-classification.md` |
| ArcFace few-shot (lib, params) | `research/arcface-few-shot.md` |
| Sub-center ArcFace + **banc d'éval honnête** | `research/ml-scalability-phases/phase-4-subcenter-evalbench.md` |
| Comparatif des approches de scan (2026-04) | `research/scan-approaches.md` |
| On-device vs cloud (coûts) | `research/cloud-vs-ondevice-costs.md` |
| Pipeline ML côté app (Kotlin) | `design/scan/ml-pipeline.md` |
| **Capture best-frame** (pilier A) | `work-in-progress/best-frame-capture/` (vision.md, decisions.md, chunks 1-7) |
| Normalisation crop on-device (parité) | mémoire `project_scan_normalization` |
| Qualité de crop (training data) | `work-in-progress/crop-quality-overhaul/` |
| Robustesse app scan/caméra (prérequis) | `work-in-progress/hardening-2026-07/03-android-robustesse.md` (F03) |

---

## 8. Prochaines actions (graine)

> **Le banc honnête existe en graine** : la boucle cohort-test (vue §I4d,
> best-of + eq, par condition) est le banc **in-the-wild** ; le gap connu est
> qu'elle **n'est pas rejouable** (JSONL = prédictions seules). D'où la brique
> n°1 ci-dessous.

- [x] **Corpus de scan rejouable** → **[`corpus-spec.md`](./corpus-spec.md)**
      — **implémenté (2026-07-06, lots 1-5)** : store `ml/store/scan_corpus.py`
      + `scan_corpus.db`, archivage device au SNAP (raw q95 + crop PNG,
      `raw_sha`/`crop_sha` JSONL, conditions `glare`/`inhand`), pull étendu,
      `import_scan_corpus.py` (nominal + backfill photo_snaps),
      `replay_corpus.py` (scorecard §8 + McNemar §8bis, chemins fast/full),
      baseline épinglée, [`exp-template.md`](./exp-template.md). Tâches :
      `go-task ml:scan-corpus:{import,replay,test}`.
- [x] `exp-01-centroids` (`train_mean` vs `val_mean`) = **rodage du funnel** →
      **[`exp-01-centroids.md`](./exp-01-centroids.md)** — **terminée
      (2026-07-06)** sur les 73 frames réelles (backfill device, corpus
      `9b1bc705525d`) : train_mean +8.2 pts R@1 eq (0.767 vs 0.685), gain sur
      les 3 conditions, **mais McNemar p=0.18** → pas de promotion ; agrandir
      le corpus (cible 150–300 frames) et re-répliquer.
- [x] `exp-02` arcface_w → **[`exp-02-centroids-arcfacew.md`](./exp-02-centroids-arcfacew.md)**
      — no-go (+5.5 pts mais battu par train_mean, p=0.48).
- [x] `exp-03` re-crop full-path → **[`exp-03-recrop-full-path.md`](./exp-03-recrop-full-path.md)**
      — exploratoire : re-crop PC +1.4/+4.1 pts sur les 2 candidats, confondu
      avec les artefacts JPEG du backfill ; re-mesurer sur corpus natif.
- [x] `exp-04` abstention → **[`exp-04-abstention-margin.md`](./exp-04-abstention-margin.md)**
      — exploratoire : la marge top1−top2 écrase le score absolu (0.955 de
      précision à 60 % de couverture, train_mean) ; seuils à valider hors-échantillon.
- [ ] **Agrandir le corpus** (prérequis pour trancher exp-01/03/04) →
      **[`session-protocol-mix-owned-42.md`](./session-protocol-mix-owned-42.md)**
      — montage en place (2026-07-06) : cohorte scan `mix-owned-42`
      (42 pièces owned, `9ecc2cd3f31a`) + cohorte train `owned-ready-24`
      (24 classes, `ab28928bcdc2`, itération `base-24c`),
      `build_cohort_bundle --prescribe-cohort --no-sample`. Cible 400+ frames
      en sessions courtes. **Reste : sessions de scan physiques.**
- [ ] Écrire `exp-backbones.md` : matrice backbones × tier device × (précision, latence, taille), baseline MobileNetV3-Small.
- [ ] Décider la politique **1 modèle universel** vs **universel + premium flagship** (§1) — dépend des premiers benchs.
- [ ] Unifier « détection photo mauvaise qualité + re-take » avec le quality scorer best-frame (pilier A).
- [ ] (Prérequis capture) trancher F03 : permission caméra + bind CameraX (sinon les ratés capture polluent la mesure modèle).

### Acquis récents (2026-07-05)
- **Sync live-tests fiabilisé** : dédup best-of canonique + verdict cohérent
  (`serving/lab_routes.py`, `store/iterations.py`) — le §I4d ne ment plus.
- **Étapes post-train sur CUDA** (`compute_embeddings.py`, `validate_per_class.py`)
  — parité prouvée (max|Δ| = 1e-6). Contexte du travail sur le corpus.
