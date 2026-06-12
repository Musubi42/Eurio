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

## Pilier 2 — Gate dénomination « est-ce un 2€ ? » (PROCHAIN — voir HANDOFF-C7)

**Constat 2026-06-12** (run `059dc8d…`, AT-2€-2005) : le grid review est pollué par
des **1ct/2ct/20ct** issus de **photos de lots** (le crop crope toutes les pièces).
Le détecteur de face les étiquette `obverse` par défaut (margin≈0, ne matche ni
avers ni revers 2€). Le funnel **isole déjà** ces crops dans les buckets lot
(`multi_coin_photo` 149, `is_lot_suspected` 12, `listing_kind_lot` 4 — 0 junk en
attente dans `single_unmatched`). **Pas de fix par seuil de similarité** : les
non-2€ chevauchent les avers 2€ usés (seuil `max(obv,rev)<0,60` = 25 % junk
capturé mais 4 % de vrais avers perdus). → Il faut un **vrai signal 2€-ness**
(bimétal géométrique recommandé, ou probe DINO dénomination). Détails, mesures et
pistes : **[HANDOFF-C7.md](./HANDOFF-C7.md)**.

### H10 — Le bimétal géométrique (contraste couleur radial) gate les non-2€ → **RÉFUTÉ comme gate dur** (2026-06-13)

Signal testé (zéro-training) : `bimetal_score` = distance dans le plan chroma
(a*, b* de CIELAB, L* ignoré) entre la couleur médiane du **disque interne** et de
l'**anneau externe** (`ml/vision/denom_geometry.py`). Hypothèse : 1€/2€ bimétal
(anneau argent + centre or) → score haut ; 1/2/5 ct cuivre & 10/20/50 ct nordic
gold monométal → score ~0. Bench : `ml/scripts/bench_denom.py`.

**Mesure (gold = 2843 crops `face IN obverse,reverse` = vrais 2€) :**

| τ (garder si score ≥ τ) | rappel 2€ (gold) | part pool lot droppé |
|---|---|---|
| 4 | **74,8 %** | 17,9 % |
| 8 | 55,3 % | 30,4 % |
| 12 | 32,3 % | 44,6 % |

→ À τ=4, le gate **false-drop 25 % des vrais 2€** pour ne retirer que 18 % du pool.
La distribution des vrais 2€ (`p10=1,4 · p50=8,3`) **chevauche massivement** celle
du pool lot. **Cause 1** : le contraste de couleur d'un 2€ **usé/toné/mal éclairé**
est indistinguable du gradient radial d'une monométal. **Cause 2 (confond connu)** :
le détecteur de crop **perd parfois l'anneau argent** du 2€ et ne garde que le
disque or → un crop sans anneau n'a aucun contraste à mesurer (cf. mémoire
*bimetal crop harden*). R0 → inutilisable en gate dur.

**Mais le signal n'est pas nul** (planches `state/denom_bench/band_*.png`,
`gold_page*.png`) : la **bande haute (score ≥ 18) est ~100 % de vrais 2€**
(précision@top forte) ; les non-2€ se concentrent dans la bande basse. Le signal a
une **bonne précision en tête, un mauvais rappel** — exploitable comme **ranker doux
de triage de lot** (piste 3), pas comme porte binaire.

### Découvertes structurantes du bench denom (2026-06-13)

1. **Le catalogue est 2€-only** (`coins` : 689 lignes, toutes `face_value=2.0` ;
   `coin_canonical_images` 1924, toutes 2€). → **Aucune image non-2€ labellisée** :
   toute probe DINO dénomination (piste 2) est **bloquée sur un gold de négatifs**
   qui doit être miné + curé visuellement depuis les crops de lots. Pas de raccourci.
2. **La pollution de lot dépasse la dénomination.** Inspection des 112 crops lot
   (run 059, buckets lot, `face=NULL`) : on trouve des **médailles/jetons**
   (« MONNAIE DE PARIS »), des **logos**, une **mire de couleurs**, des **crops
   partiels** — pas seulement des cents. ⟹ Pilier 2 (dénom) et **pilier 3
   (authenticité/junk) se recouvrent** : un même gate « vraie pièce euro 2€ ?»
   les traiterait ensemble. La coin-ness DINO (`census.py`, banque
   `foundation_coinness.npz` **absente** sur desktop) rejetterait médailles/logos/mire ;
   la dénomination ne tranche que cents vs 2€.
3. **Le pool lot est majoritairement de vrais 2€** (pages 1–2 des planches) — la
   pollution est **concentrée mais minoritaire**, cohérent avec le constat funnel.

**Reco (révisée)** : la piste gate dur **bimétal seul est morte**. Construire un
gold denom/junk curé (112 crops lot prêts à labelliser : `state/denom_bench/gold_page*.png`
+ `gold_index.json`), puis **probe DINO 2€-vs-junk** (piste 2, primaire) avec
`bimetal_score` en **feature auxiliaire / ranker de triage de lot** (piste 3). La
coin-ness DINO doit d'abord être rebuild sur desktop (banque npz absente).

### Gold denom provisoire labellisé (2026-06-13, pass visuel Claude)

Les 112 crops lot labellisés à la main → `state/denom_bench/denom_gold.jsonl`
(`label` ∈ pos/neg/unk, `kind` neg ∈ cent/medal/chart/other, `conf` hi/lo,
verif visuelle `gold_verify.png`). **76 pos · 32 neg · 4 unk** après un **2ᵉ pass
en pleine résolution** (224² = résolution native : dans une photo de lot 1600px,
chaque pièce ne fait que ~223px → 224 est déjà le plein cadre, pas de re-crop
source possible). Le full-res a résolu 9 « unk » en 2€ sous capsule (reflet de
capsule trompeur en vignette) ; ne restent `unk` que **4 vrais ambigus** (3 crops
d'un même motif « bleuet » bleu colorisé = 2€ colorisé ? médaille caritative ? +
1 crop obscurci). Décomposition des 32 négatifs : **16 cent · 8 médaille · 6 mire ·
2 other (1€ + set multi-pièces)** — soit **~44 % de NON-pièces-2€-uniques**
(médaille+mire+set), ce qui **reconfirme le recouvrement pilier 2 ∩ 3** : seuls les
16 cents relèvent de la dénomination pure ; médailles/mires/sets relèvent de la
coin-ness / Stage-0 (pilier 3).

**Éval du `bimetal_score` sur ce gold (pos vs neg, unk exclus)** : **AUC = 0,77**,
junk concentré en bas (**27/32 négatifs dans la moitié basse** du score). τ=12 →
rappel 2€ ~72 %, capte ~78 % du junk : **bon ranker, mauvaise porte dure** (cohérent
H10). → exploitable pour **trier l'ordre de review d'un lot**, pas pour droper.

⚠️ Gold **provisoire** (labels Claude, full-res) : 67 `conf=hi` (charts/médailles
MdP/cents cuivre/2€ nets = ancres solides), 45 `conf=lo` + 4 `unk` à **valider par
un humain** avant d'entraîner la probe. Re-figer via `python scripts/_seed_denom_gold.py`
(dict éditable). Pas de page web crop-level dédiée (cf. note `crop-bench` ci-dessous).

## Pilier 3 — Authenticité (à venir)

Détecter dessin / rendu 3D / impression carton / réplique plastique / slab.
Aucun détecteur image aujourd'hui (signaux faibles : Laplacian, DINO coin-ness,
probe fragment dormante ; marqueur texte « replica »). Gold à construire
(mining eBay via marqueurs texte + curation). Cf. H8.

## Sources de vérité (code)

- Bench face : `ml/scripts/bench_face_detection.py`
- Gold face : `ml/state/face_bench/face_gold.jsonl`
- Signal bimétal (denom) : `ml/vision/denom_geometry.py` (`bimetal_score`, `ring_is_silver`)
- Bench denom : `ml/scripts/bench_denom.py` ; planches/amorce gold : `ml/state/denom_bench/`
- Ancres revers : `app-android/.../shared_reverse/reverse_2eur_v{1,2}.webp`
- Banque avers : `ml/state/foundation_anchors_2eur_all.npz` (vitl14)
- Colonne face : `image_assets.face` (schema.sql), écrite aujourd'hui seulement
  par review humaine / Claude (`review_queue_routes.py`)
- Filtre training : `scripts/build_arcface_dataset.py:127` (`face != 'reverse'`)

### H11 — Probe DINO « 2€-vs-junk » : direction validée, gold trop mince (2026-06-13)

Baseline benchmark-first (`ml/scripts/train_denom_probe.py`, logistique sur vitl14
gelé, CV 5-fold stratifiée, gold 79 pos / 32 neg) :

| features | AUC | @rappel2€≥95% : junk capté | cents captés |
|---|---|---|---|
| bimetal seul | 0,776 | 18,8 % | 1/16 |
| DINO vitl14 | 0,813 | 21,9 % | 1/16 |
| **DINO + bimetal** | **0,831** | 21,9 % | 0/16 |

**Lecture** : (1) DINO bat le bimétal, +bimétal en feature aux. gagne encore un peu
→ **archi validée** = une seule probe gelée subsume coin-ness + dénom. (2) Mais à un
opérateur R0-safe (ne pas droper les vrais 2€), elle ne capte que ~22 % du junk et
**~0 cent** : les **médailles/non-pièces sont faciles (5/8), les cents sont la classe
dure** et le gold n'en a que 16. ⟹ **grossir le gold, priorité aux cents**, avant
de figer un seuil ou de câbler (R0).

### H11bis — Gold grossi (cents minés + positifs propres) : **probe VALIDÉE** (2026-06-13)

Gold étendu (`denom_gold.jsonl`) : **229 pos · 153 neg (137 cents) · 24 unk**.
- **+121 cents** minés depuis le pool caché par ranking junk-likelihood (bimétal bas
  + teinte cuivre `a*`), pré-labellisés Claude puis **confirmés par l'utilisateur**
  (23 exceptions écartées en `unk` = crops partiels de 2€ ou images saturées
  rouge/magenta imitant le cuivre — d'où la confusion couleur, **argument pour
  DINO-pas-couleur**). 135/144 candidats étaient `face='obverse'` en base = **les
  cents mislabellisés-avers qui polluent la review** (confirmation directe du méca).
- **+150 positifs propres** = 2€ obverse **résolus humainement** (`resolution_status
  IN manual,auto_phash`, identité 2€ confirmée → zéro risque de label).

Éval CV 5-fold (gold équilibré 229/153) :

| features | AUC | @rappel2€≥95% : precision · junk capté | cents · médailles |
|---|---|---|---|
| bimetal | 0,882 | 71 % · 43 % | 59/137 · 5/8 |
| DINO vitl14 | 0,910 | 81 % · 67 % | 99/137 · 0/8 |
| **DINO + bimetal** | **0,922** | **84 % · 73 %** | **105/137 · 5/8** |

**Lecture** : la probe **marche** (rappel cents 0/16 → 105/137). DINO+bimétal domine
partout. À un opérateur gardant 95 % des vrais 2€, elle **drop 73 % du junk** et le
gardé est **84 % pur**. Probe sauvée → `state/denom_probe.npz` (coef logistique +
norm bimétal, encoder vitl14). **Caveats** : (1) à 95 % rappel on droperait encore
5 % de vrais 2€ → pour une **porte dure** (R0) viser un opérateur ~99 % rappel
(moins de junk capté) **ou** l'utiliser en **ranker doux** de triage de lot ;
(2) **médailles/mires sous-captées** (cents dominent les négatifs) → ajouter des
négatifs non-pièces, ou laisser coin-ness/Stage-0 les gérer.

### Câblage livré (2026-06-13) — gate per-crop, miroir de la face

Opérateur retenu (choix produit) : **drop dur @99 % rappel + ranker doux**. Seuil
calibré `t=0,24` (`denom_probe.npz`) — **validé R0 sur 419 vrais 2€ held-out :
99,52 % passent** (false-drop 0,48 %, et le rejet reste ré-ouvrable /restore).

- **Inférence** : `ml/vision/denom_probe.py` (`denom_score` réutilise le vec vitl14
  + `bimetal_score`, `decide_denom` applique le seuil). No-op si l'artefact absent.
- **Détecteur** (`auto_validate.py`) : score calculé dans le bloc face (vec vitl14
  réutilisé) → `image_asset_dino_predictions.denom_2eur_score` (ranker/audit) +
  `image_assets.denom` écrit **si NULL** (anti-clobber, miroir de `face`).
- **Routing** (`enqueue.py`) : un crop `denom='not_2eur'` est **rejeté per-crop**
  (`_reject_crop_terminal`, `quality_reason='not_2eur'`, `_DENOM_ENGINE_VERSION`),
  ré-ouvrable. **Jamais la photo entière** → dans un lot mixte les avers 2€ restent
  en review. `_route_decision_for_source_image` → bucket `route_reason='not_2eur'`.
- **Funnel** : bucket « pas un 2€ (cent/médaille/mire) » (`REASON_LABELS` Vue +
  `_HUMAN_REASON` bench_routes).
- **Backfill** (`go-task ml:backfill-denom [-- --run …]`) : idempotent, sticky-aware.
  **Run 059 : 2093 crops scorés → 253 not_2eur, 177 rejetés, 119 listings re-routés.**
  Parité sortie probe↔câblage vérifiée (gold 98,7 % 2€ gardés in-sample).
- **Preuve per-crop** : sur une photo de lot, le gate a droppé 5/50/20/2/10/50 ct et
  **gardé les 4 vrais 2€** (2 avers bimétal + Plautus + bâtiment) — c.-à-d.
  exactement « re-run la détection après le crop pour ne pas perdre les avers ».

**Caveats** : (1) `denom` écrit only-if-NULL → comme `face`, un **re-crop** (mêmes
pixels, même asset_id) ne recalcule pas (cas rare ; nouveau crop = nouvelle row =
NULL = recalculé). (2) médailles/mires sous-captées (ci-dessus). (3) backfill lancé
sur run 059 seulement (autres runs : crops non cachés / 403 ici → couverts au fil de
l'eau par la pipeline inline ou un futur backfill).
