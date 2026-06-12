# C7 — Scan robuste : cascade de classification (face, authenticité, fusion)

**Statut : 🟡 en cours** (ouvert 2026-06-12) · Dépend de : C0, C1, C2 · Débloque : produit scan fiable

## Objectif

Rendre la classification d'un crop (eBay scrape **et** scan device) robuste aux
« cas pourris » via une **cascade de portes + un cœur d'identité**, au lieu de
demander à un seul modèle un verdict binaire contre une cible.

```
Stage 0 — VRAIE PHOTO DE PIÈCE UNIQUE ?        [porte, du moins cher au plus cher]
   géométrie (cercle/fragment/tilt)            ✅ normalize_snap, census
   pas lot / slab / coffret                     ✅ texte serveur + census device
   pas dessin / 3D / carton / réplique          ❌ à construire (pilier 2)
Stage 1 — QUELLE FACE ?                          🟡 baseline OK (pilier 1, ci-dessous)
   avers national vs revers commun (carte + "2 EURO")
   → device: "retourne la pièce" ; serveur: face=reverse, skip identité
Stage 2 — IDENTITÉ (fusion)
   texte (serveur)        ✅ 69,7 % @ 94,5 %
   DINO top-K (proposer)  ✅ vitl14 80,9 % hit@5
Stage 3 — ROUTAGE CONFIANCE
   haute → auto • moyenne → humain choisit dans top-K DINO • basse → junk
```

## Pourquoi (diagnostic « ccproxy pourri »)

La lane ccproxy demandait à Claude « ce crop = la pièce **recherchée** ? » alors
qu'elle ne contient que les cas où le DINO **diverge déjà** de la cible → 86 %
de « no_match » structurels et **inexploitables** (« pas la cible » sans dire
quoi). La page review manuelle marche car le **DINO propose un top-K** d'identité
(bon). Donc : **la vision PROPOSE l'identité, elle ne vérifie pas une cible.**
Si on garde un appel cher, il doit **confirmer le top-1 DINO**, pas la requête.

## Hypothèses (à challenger)

- **H7 — Les embeddings DINO séparent l'avers national du revers commun 2€**
  sans réentraînement. → **CONFIRMÉE** (pilier 1, voir Résultats).
- **H8 — Un détecteur d'authenticité (vraie pièce vs dessin/3D/carton/réplique)
  est nécessaire et n'existe pas.** Croyance : forte (audit code = 0 détecteur
  image). À mesurer une fois un gold construit.
- **H9 — Retourner la question Claude (confirmer top-1 DINO au lieu de vérifier
  la cible) ↑ le rendement en refs.** Non mesuré.

## Pilier 1 — Détecteur de face (avers vs revers commun)

Le revers commun 2€ a **exactement 2 designs** (v1 ≤2006, v2 ≥2007), packagés
APK (`app-android/.../shared_reverse/reverse_2eur_v*.webp`). Détecteur
**zéro-training** : `face = reverse` si
`sim_max(2 ancres revers) − sim_top1(banque avers 2eur_all) ≥ τ`.

Bench : `ml/scripts/bench_face_detection.py`. Gold figé :
`ml/state/face_bench/face_gold.jsonl` (566 avers confirmés admin + 40 revers
minés & vérifiés visuellement).

### Résultats (2026-06-12, DINO vitl14, DB canonique)

| Mesure | Valeur |
|---|---|
| Faux positifs (avers→revers) @ marge ≥ 0 | **0,0 %** (0/562) |
| Marge avers (rev−obv), distrib. | médiane −0,221, **max −0,006** |
| Top-40 candidats revers minés (pool non-labellisé) | **100 % vrais revers** (vérif visuelle) |
| Pool non-labellisé avec marge ≥ 0 | **15,5 %** (163/1049) |

**Lecture :** séparation nette (les avers plafonnent à −0,006, jamais ≥ 0 ;
les revers montent à +0,15). Le seuil `marge ≥ 0` donne ~0 % de FP. ~15 % de la
queue review sont en fait des **revers** qui polluent identité + flywheel
aujourd'hui (le training ArcFace filtre `face!='reverse'`, mais `face` n'était
quasi jamais renseigné → ces revers passaient en `NULL`).

### Câblage livré (2026-06-12) — back + données + funnel

Le détecteur tourne **dans la pipeline** et l'élimination est **visible dans le
funnel bench** :

- **Détecteur** (`auto_validate.py`) : réutilise le `vec` vitl14 déjà encodé →
  `reverse_sim`/`face_margin` stockés sur la prédiction `2eur_all`, et
  `image_assets.face` écrit **si NULL** (anti-clobber des labels humains). τ via
  `FACE_REVERSE_TAU=0.05`. Parité de sortie avec le bench vérifiée au millième.
- **Ancres** : banque `reverse_2eur` (2 webp packagés, vitl14) —
  `go-task ml:dino-anchors:build -- --kind reverse_2eur`.
- **Données** : colonnes `reverse_sim`/`face_margin` (`image_asset_dino_predictions`)
  via `_ensure_column` (idempotent).
- **Routing** : un crop `face=reverse` est **rejeté** (pattern `consensus_reject`
  factorisé en `_reject_crop_terminal`), `quality_reason='face_reverse'`,
  ré-ouvrable via /restore. `_route_decision_for_source_image` → bucket
  `route_reason='face_reverse'`.
- **Funnel** : bucket « Rejeté · revers commun 2€ » dans « TRAITEMENT DES CROPS »
  (rendu générique), cliquable → drill des listings via
  `?route_decision=rejected&route_reason=face_reverse`.
- **Backfill** (`go-task ml:backfill-face`) sur l'existant : **2277 crops 2€
  évalués → 231 reverse / 2046 obverse**, 119 revers rejetés (les autres déjà
  tranchés / restore humain → sticky), 48 listings single-crop re-routés en
  `face_reverse`. Idempotent (re-run = 0 écrit). Les 566 avers humains + 170
  unknown intacts.

### Caveats / reste à faire (pilier 1)

- **Rappel wild non chiffré** : le top minée est 100 % revers (précision@top),
  mais le rappel (quels revers ratés sous le seuil) demande un gold revers plus
  large. Le gold actuel n'a que 40 revers (vérifiés). → élargir par mining +
  vérif, puis fixer τ sur précision **et** rappel.
- **Robustesse v1/v2** : 2 ancres seulement. Tester si ajouter quelques vues
  réelles de revers (usés/inclinés) comme ancres ↑ le rappel wild.
- **Câblage** (décision produit, non fait) :
  - Serveur : Stage 1 avant l'identité — backfill `image_assets.face`, et un
    crop `reverse` ne part plus en identité/flywheel.
  - Device : `app-android` n'a aucun rejet de face → UX « retourne la pièce »
    (le matching ArcFace est obverse-only, un revers échoue silencieusement).

## Pilier 2 — Authenticité (à venir)

Détecter dessin / rendu 3D / impression carton / réplique plastique / slab.
Aucun détecteur image aujourd'hui (signaux faibles : Laplacian, DINO coin-ness,
probe fragment dormante ; marqueur texte « replica »). Gold à construire
(mining eBay via marqueurs texte + curation). Cf. H8.

## Sources de vérité (code)

- Bench face : `ml/scripts/bench_face_detection.py`
- Gold face : `ml/state/face_bench/face_gold.jsonl`
- Ancres revers : `app-android/.../shared_reverse/reverse_2eur_v{1,2}.webp`
- Banque avers : `ml/state/foundation_anchors_2eur_all.npz` (vitl14)
- Colonne face : `image_assets.face` (schema.sql), écrite aujourd'hui seulement
  par review humaine / Claude (`review_queue_routes.py`)
- Filtre training : `scripts/build_arcface_dataset.py:127` (`face != 'reverse'`)
