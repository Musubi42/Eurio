# Corpus de scan rejouable — spécification

> **Rôle.** Brique n°1 du funnel d'expérimentation (`README.md` §funnel). Un
> **corpus gelé, labellisé, rejouable** de vraies captures device : il découple
> l'itération modèle du re-scan physique. Sans lui, tester un candidat = une
> session de scan manuel (lente, bruitée, **non appariée**). Avec lui, on rejoue
> n'importe quel candidat **offline sur les mêmes frames** → delta apparié
> (McNemar), en secondes.
>
> **État : spec en revue (2026-07-06).** Rien de codé encore. On aligne la spec,
> puis on écrit le template `exp-*.md` et on code l'archivage.
>
> **Périmètre.** PC-only (les images restent sur le PC, gitignored). Cible de ce
> cycle : la cohorte actuelle **`mix-zone-17` (16 classes, `b0299ca0252b`)**. La
> spec est dimensionnée pour absorber une future cohorte 40 classes × 5 photos
> **sans changement de schéma**.

---

## 1. Ce que le corpus EST — et n'est pas

| | |
|---|---|
| ✅ **Model-agnostic** | Ne stocke **aucune** prédiction ni embedding. Que des images + labels. On rejoue *tout* candidat dessus. |
| ✅ **Rejouable 2 axes** | Contient le **raw** (rejouer détection/normalisation) **et** le **crop normalisé** (rejouer modèle/centroïdes/seuils, chemin rapide). |
| ✅ **Apparié** | Chaque capture a un `capture_id` stable → comparaison baseline↔candidat frame-par-frame. |
| ✅ **Append-only** | On ajoute des captures ; on ne réécrit jamais une image. Un « corpus vN » = un snapshot immuable (§5). |
| ❌ **Pas** `iteration_live_tests` | Cette table-là = résultats **scorés par itération** (métrique produit §5, best-of, eq). Le corpus = **frames brutes model-agnostic**. Elles partagent la provenance (`iteration_id`, `test_idx`) mais servent deux buts. Pas de duplication : le corpus ne re-scoore pas, il **fournit la matière** au replay. |
| ❌ **Pas un lab-produit** | Pas de service, pas d'UI, pas d'abstraction spéculative. 3 briques : un dossier, une table, un script. Le « lab futur » s'assoira dessus **s'il gagne son droit d'exister**. |

---

## 2. Ce qu'on stocke par capture (les deux, tranché)

Une **capture** = une frame device au moment d'un SNAP cohort-test. On persiste :

| Fichier | Contenu | Format | Pourquoi |
|---|---|---|---|
| `*.raw.jpg` | Frame caméra **post-rotation, pré-crop** (ce qui entre dans la détection) | JPEG q95 | Rejouer un changement de **détection / normalisation** (crop, mask, resize). |
| `*.crop.png` | Disque **normalisé masqué 224²** (sortie `SnapNormalizer`, l'entrée réelle de l'embedder) | **PNG (lossless)** | Rejouer **modèle / centroïdes / seuils** vite, sans re-détecter. Lossless car c'est la grandeur qu'on **mesure** — pas d'artefact JPEG dessus. |

> On **ne stocke pas** l'embedding : le but est justement de rejouer des modèles
> différents. (Un cache d'embeddings keyé `(crop_id, model_sha)` est possible
> plus tard comme optimisation, jamais comme source de vérité.)

---

## 3. Layout disque — content-addressed

```
ml/state/scan_corpus/            # gitignored (binaire lourd, PC-only)
├── frames/
│   ├── <capture_id>.raw.jpg
│   └── <capture_id>.crop.png
└── README.txt                   # « source de vérité = table scan_corpus (store lab, cf. §4) »
```

- **`capture_id` = `sha256(raw_bytes)[:16]`** (hex). Immuable, déterministe,
  **déduplique** deux frames identiques (idempotent à la ré-import).
- **Stockage plat, content-addressed** ; **toutes** les métadonnées (label,
  condition, provenance) vivent dans la table `scan_corpus`, pas dans le chemin.
  → re-labelliser ou re-catégoriser = un `UPDATE` SQL, **zéro déplacement de fichier**.

> **À discuter (Q1).** Le plat content-addressed est robuste mais peu
> « browsable » à l'œil. Alternative : une vue `by-label/<eurio_id>/<condition>/`
> en **symlinks générés** (jamais la source). Je penche pour : plat = vérité,
> vue symlink optionnelle à la demande. OK ?

---

## 4. Table `scan_corpus` — **PAS dans `eurio.db`** (donnée lab local-only)

> ⚠️ **Corrigé après audit du sync (Direction A, commits `1a434263` /
> `af271262` / `8dc06b3e`).** `eurio.db` est (sous le flip) une **réplique
> read-only** synchronisée depuis le VPS. Y écrire une table serait **doublement
> faux** : (1) bloqué par les gardes readonly (`EURIO_DB_READONLY=1`), (2) la
> donnée partirait au canonique/VPS. Le corpus est du **lab PC-only qui ne doit
> JAMAIS voyager**.

**Où il vit — TRANCHÉ : DB dédiée `ml/state/scan_corpus.db`.**

Store lab **totalement isolé**, **gitignored**, **architecturalement incapable de
syncer** (jamais référencé par le pipeline canonique/replica), zéro pollution du
`schema.sql` canonique, et prépare le « futur lab standalone ». Écarté : mettre la
table dans `eurio.local.db` (réutiliserait l'infra obs-local mais entrerait dans
le schéma canonique). Le corpus n'ayant **aucune** FK vers le canonique (eq
résolue en Python au replay, cf. ci-dessous), un store séparé ne coûte qu'un
petit câblage (helper d'ouverture + DDL de la seule table `scan_corpus`).

**Résolution de l'eq sans cross-db join :** le corpus stocke le label
`eurio_id` **seul**. Le `design_group` (pour scorer en maille eq) est résolu **au
replay**, en Python, via `training.eval.equivalence.build_equivalence_map(
db_path=<réplique ro>)` — la **même** source que le §5
(`serving/lab_routes.py::sync_live_tests`). Le corpus reste self-contained et
lit le canonique en **lecture seule** au moment du score, jamais en jointure SQL.

**Schéma de la table** (identique quelle que soit l'option A/B) — se lit/écrit
via un store dédié, model-agnostic :

| Colonne | Type | Note |
|---|---|---|
| `capture_id` | TEXT PK | `sha256(raw)[:16]` |
| `eurio_id` | TEXT | **Label vérité** (pièce attendue). |
| `condition` | TEXT | `bright`/`dim`/`tilt` aujourd'hui ; **vocabulaire ouvert** (§Q2). |
| `cohort_id` | TEXT | Provenance (à quelle cohorte appartient la pièce). |
| `source_iteration_id` | TEXT | Itération/session qui a produit le scan. **Provenance uniquement** — jamais utilisé pour scorer (corpus model-agnostic). |
| `bundle_source` | TEXT | Label du bundle au moment de la capture (`lab`/`prod`/…). |
| `raw_path` | TEXT | Relatif à `scan_corpus/`. |
| `crop_path` | TEXT | Idem. |
| `raw_w`,`raw_h`,`crop_w`,`crop_h` | INT | Sanity (crop attendu 224×224). |
| `device_model` | TEXT | `Pixel 9a`… → analyse par tier. |
| `quality_json` | TEXT NULL | Signaux `FrameQualityScorer` si dispo (sharpness/exposure/completeness/motion). Optionnel, précieux pour corréler échec ↔ qualité. |
| `captured_at` | TEXT | ISO 8601. |
| `notes` | TEXT NULL | Libre. |

Le **design_group** (pour l'eq) n'est **pas** dénormalisé ici : on le résout au
replay via `coin` / `training.eval.equivalence` (même source de vérité que le
§5, cf. `serving/lab_routes.py::sync_live_tests`). Évite la dérive.

---

## 5. Versioning — snapshots par hash de manifeste

Append-only ⇒ une « version de corpus » = un **snapshot immuable** = l'ensemble
trié des `capture_id` retenus par un filtre.

- **`corpus_version` d'une expérience** = `sha256(sorted(capture_ids))[:12]` +
  `n_frames`. Léger, reproductible, **pas de système de versioning lourd**.
- Une expérience `exp-*.md` **enregistre** le `corpus_version` + le filtre
  (`cohort_id=…`, conditions, date max) sur lequel elle a tourné. Rejouer plus
  tard sur exactement le même set = re-passer le filtre → même hash → même set.

> Pas de table `corpus_snapshots` pour l'instant : le hash-de-manifeste suffit.
> On en ajoutera une **si** on a besoin de nommer/épingler des snapshots (YAGNI).

---

## 6. Contrat d'archivage (device → PC)

**Device (cohort-test).** Au SNAP, en plus de la ligne JSONL actuelle
(`LiveTestLogger.append`, `app-android/src/cohortTest/.../LiveTestLogger.kt`) :

1. Persister `frames/<iteration>/<capture_id>.raw.jpg` (frame détection) et
   `.crop.png` (sortie `SnapNormalizer`).
2. Ajouter `raw_sha` + `crop_sha` à la ligne JSONL → lien frame ↔ prédiction.

> **Granularité = par FRAME, pas par test.** Le §5 collapse en best-of (métrique
> produit) ; le **corpus garde chaque frame** (chaque re-capture est un point de
> donnée / mesure de fragilité). Une ligne JSONL = une capture = une ligne
> `scan_corpus`.

**Pull.** Étendre `cohort-test:pull-tests` (`app-android/Taskfile.yml`) pour
tirer aussi `eurio_live_tests/frames/<iteration>/` à côté du `.jsonl`.

**Import.** `import_scan_corpus.py` (ou extension de `sync_live_tests`) : lit le
JSONL + les frames pullées, hash-vérifie, copie dans `scan_corpus/frames/`,
upsert la table. Idempotent (dédup par `capture_id`).

> **À discuter (Q3).** L'archivage frames est un **changement app**
> (cohort-test). Périmètre acceptable pour ce cycle ? (C'est le seul prérequis
> dur de la rejouabilité — sinon on reste sur du re-scan manuel.)

---

## 7. Contrat de replay — `replay_corpus.py`

Le **cœur du funnel S0**. Prend un **candidat** + un **filtre corpus** → une
**scorecard**.

- **Candidat** = un triplet `{ centroïdes (embeddings_v1.json), modèle
  (.tflite/.pth), seuils (top1_min / top1_strong / margin_min) }`.
  La **baseline est un candidat comme un autre** (le bundle prod épinglé, §9).
- **Deux chemins :**
  - *Rapide (modèle/centroïdes/seuils)* : charge `crop.png` → embed candidat →
    cosine vs centroïdes candidat → top-k + abstention. Pas de détection.
  - *Complet (normalisation/détection)* : charge `raw.jpg` → détection+normalise
    candidat → crop → embed → match. Plus lent.
    ⚠️ **Sur le corpus device, `--path full` n'est pas « réservé aux exp de
    géométrie » : il est OBLIGATOIRE.** Les crops stockés sortent de **quatre**
    normaliseurs (`hough_tight` 113, `hough_relaxed` 1, `hough_strict` 280,
    `hough_loose` 57 — 17 % du pull de juin). En `fast`, l'écart mesuré serait
    celui des normaliseurs. Mesure :
    [`../juge-et-banc/LOT1-IMPORT.md`](../juge-et-banc/LOT1-IMPORT.md) §4.
- **Sortie :** `scorecard.json` (§8) **+** `predictions.jsonl`
  (`capture_id → top-k, abstain`) pour le McNemar (§8bis).

Parité : le replay doit **matcher le matcher Android** (obverse-only, eq
design_group) — mêmes règles que `serving/distance_logic.py` et l'eq du §5, sinon
le delta offline ne prédit pas le device (cf. `feedback_output_contract_parity`).

---

## 8. Scorecard — schéma standard (toute exp remplit la même)

```jsonc
{
  "candidate": "exp-01-centroids/train_mean",     // libellé
  "baseline":  "prod@<bundle_sha>",
  "corpus_version": "a1b2c3d4e5f6", "n_frames": 48,
  "filter": { "cohort_id": "b0299ca0252b", "conditions": ["bright","dim","tilt"],
              "bundle_sources": ["device_pull_20260601"] },

  "label_space": {                                 // §8ter — le dénominateur
    "n_candidate_classes": 24,                     // centroïdes du candidat
    "n_ground_truth_classes": 20,                  // classes du corpus filtré
    "n_covered_classes": 18,
    "n_uncoverable_classes": 2,
    "uncoverable_classes": ["mt-2euro-standard-t1", "…"],
    "n_frames_covered": 44, "n_frames_uncoverable": 4,
    "frame_coverage": 0.9167 },

  "primary":   { "r_at_1_eq": 0.71, "r_at_5_eq": 0.90,
                 "r_at_1_strict": 0.69,            // eq = maille design_group
                 "r_at_1_on_covered": 0.77,        // §8ter — JAMAIS sans le global
                 "n_on_covered": 44 },             // …ni sans son n
  "by_condition": {                                // garde-fou régression
    "bright": { "n": 16, "r_at_1_eq": 1.00, "n_covered": 15, "r_at_1_on_covered": 1.00 },
    "dim":    { "n": 16, "r_at_1_eq": 0.75, "n_covered": 15, "r_at_1_on_covered": 0.80 },
    "tilt":   { "n": 16, "r_at_1_eq": 0.81, "n_covered": 14, "r_at_1_on_covered": 0.93 } },
  "errors": { "n": 0, "rate": 0.0, "by_kind": {} },// §8ter — échec ≠ abstention
  "abstention": { "coverage": 0.94,                // % de frames où on ose répondre
                  "precision_at_coverage": 0.80 }, // parmi celles-ci, % correct
  "latency_ms": { "p50": null, "p95": null,        // rempli en S2 (device)
                  "tier": null },
  "size": { "model_mb": 4.4, "delta_vs_baseline_mb": 0.0 },
  "confusions": { "gained": [...], "lost": [...] } // paires qui basculent
}
```

**Définitions (non négociables, mêmes partout) :**
- **R@1 eq** = maille `COALESCE(design_group, eurio_id)` — la métrique de vérité
  (le modèle prédit des labels de groupe ; le strict eurio_id ne peut pas
  matcher structurellement). Le strict est **informatif** seulement.
- **Abstention** = le candidat ne produit **aucune** réponse assez confiante
  (seuils). **`precision_at_coverage`** = parmi les non-abstenues, le taux
  correct. **Un faux positif confiant coûte la confiance** : ce couple
  (couverture, précision) prime souvent sur le R@1 brut.
- **Best-of vs per-frame** : la scorecard rapporte le **per-frame** (fragilité).
  Le best-of (produit) est dérivable en groupant par `(eurio_id, condition,
  session)` — reporté à part quand pertinent.

## 8ter. L'espace de labels — ajouté au contrat le 2026-08-25

> **Pourquoi ce paragraphe existe.** Le 2026-08-25, le run témoin du lot 3
> (`--iteration caf98145032c --bundle-source device_pull_20260601`) a rendu
> `r_at_1_eq = 0,1751` sur 337 frames. Le vrai chiffre est **98,3 % sur 60
> frames** : l'itération ne porte que **3 centroïdes** quand le corpus filtré
> porte **17 classes**, donc **277 frames sur 337 étaient fausses par
> construction** — aucun modèle ne pouvait les réussir. Le nombre était
> plausible, faux, et **muet**. Cf.
> [`../juge-et-banc/LOT3-JUGE.md`](../juge-et-banc/LOT3-JUGE.md) §3.

**Définition.** Une frame est **couvrable** ssi il existe un centroïde du
candidat qui `covers()` sa vérité terrain, **ou** qui lui est équivalent en
`design_group`. C'est la négation exacte de la règle de `compute_hits` : une
frame non couvrable a `correct_eq_top1 = false` **quoi que fasse le modèle**.
Le drapeau est porté par chaque ligne de `predictions.jsonl` (`coverable`).

**Trois obligations, non négociables :**

1. **`label_space` est obligatoire** dans toute scorecard. Sans lui, `n_frames`
   fait croire à un dénominateur honnête alors qu'il compte des frames dont la
   réponse n'est pas dans le modèle.
2. **`r_at_1_on_covered` et `r_at_1_eq` se rendent ensemble, avec `n_on_covered`.**
   Jamais l'un sans l'autre : le global est comparable entre candidats d'espaces
   différents (mais dilué), le sur-couvrables mesure le modèle (mais sur un
   sous-ensemble qui change avec lui). **Citer un seul des deux est une faute de
   lecture**, dans un `exp-*.md` comme dans une conversation.
3. **Une comparaison entre espaces de labels différents est REFUSÉE.** Un
   `--baseline` dont l'espace diffère de celui du candidat fait sortir
   `replay_corpus.py` en erreur explicite, **avant la première inférence et
   avant d'écrire quoi que ce soit sur disque**. Le McNemar croiserait sinon
   l'écart des **cohortes** et non celui des **modèles**, et rien ne le dirait.
   La comparaison se fait sur la maille `COALESCE(design_group, eurio_id)` :
   deux candidats entraînés l'un en `eurio_id`, l'autre en `design_group`, ne
   sont pas pour autant deux espaces différents.

⚠️ **Conséquence pour le départage ArcFace ↔ DINO** ([`MATRICE.md`](../juge-et-banc/MATRICE.md)) :
les deux voies n'ont **pas** le même espace de labels par défaut (la banque DINO
couvre bien plus de classes qu'une cohorte d'entraînement). Les opposer demande
de **recalculer les centroïdes des deux sur le même ensemble de classes** — ce
n'est pas une option de confort, c'est la condition pour que le p-value veuille
dire quelque chose.

### `errors` — un échec n'est pas une abstention

Même famille de silence, corrigée le même jour. `abstention.coverage` seul
confond deux choses : une **abstention** (le candidat a vu la frame et s'est tu)
et un **échec** (la frame n'a jamais atteint le modèle : `normalize_failed`,
`load_failed`). Un run où tout le raw échouerait sortait `r_at_1 = 0.0` et
`coverage = 0.0` — deux nombres plausibles, indiscernables d'un modèle prudent.
Le bloc **`errors` `{n, rate, by_kind}` est obligatoire**, et vaut
`{0, 0.0, {}}` explicitement quand tout va bien.

## 8bis. Stat appariée — McNemar (obligatoire vu le petit n)

On ne compare **jamais** deux R@1 indépendants (à n=48, IC95 ≈ ±13 pts). On croise
`predictions.jsonl` baseline vs candidat **sur les mêmes `capture_id`** :

- Table de contingence : correct/incorrect × correct/incorrect.
- **Puissance ∝ nombre de paires discordantes** (frames où les deux diffèrent).
  Un vrai +2 pts sur 48 ≈ 1 paire → **non significatif**. On ne tranche « gain »
  que sur un delta **franc** (≥ ~5 pts) ou un **shift net par condition**, tant
  que le corpus n'a pas grossi (~150–300 frames, cf. `README.md` §4).
- `replay_corpus.py` sort la p-value McNemar baseline↔candidat.
- ⚠️ Le croisement n'a lieu que si les deux candidats partagent le **même espace
  de labels** (§8ter, obligation 3) — sinon le script refuse.

---

## 9. Baseline épinglée

La baseline **n'est pas un chiffre mémorisé** — c'est un **artefact re-runnable** :

- `ml/state/scan_baselines/<name>/` = le bundle gelé (centroïdes + modèle +
  seuils) + sa scorecard sur un `corpus_version` donné.
- On **recalcule** son score sur le corpus courant à chaque comparaison (mêmes
  frames que le candidat) → jamais de comparaison inter-versions déguisée.
- Chaque `exp-*.md` cite « bat baseline `<name>` sur corpus `<version>` ».

---

## 10. Ce que la spec ne couvre pas (anti-dup)

- ❌ La **capture best-frame** (stabilité/AE-AF/rafale) → `best-frame-capture/`.
  Ici on **consomme** la meilleure frame, on ne la re-conçoit pas.
- ❌ Le **banc offline studio** (`ml/training/eval/evaluate_real_photos.py`)
  reste le banc hold-out Numista/eBay ; le corpus est le banc **in-the-wild**.
  Les deux coexistent (README §2).
- ❌ Le **scoring produit §5** (`iteration_live_tests`) — inchangé.

---

## 11. Décisions & questions

**Tranché :**
- **Q1 ✅** — Layout **plat content-addressed** + vue symlink `by-label/` optionnelle générée à la demande.
- **Q2 ✅** — Vocabulaire **ouvert** (TEXT + set validé) : `bright/dim/tilt`
  **+** `glare` **+** `inhand`. ⚠️ **`worn`/`dirty` reste dans le vocab mais
  **non peuplable ce cycle** — les pièces de test sont propres et ne se salissent
  pas à la demande. À couvrir plus tard avec des pièces réellement usées.
  Ajouter `glare`/`inhand` **change l'UI cohort-test** (nouvelles conditions
  prescrites) — cf. discussion §App ci-dessous.
- **Q3 ✅** — Changement app cohort-test **autorisé** (c'est sa raison d'être).
- **Q4 ✅** — Import via **script dédié `import_scan_corpus.py`** (le corpus est
  model-agnostic, découplé du cycle de sync des résultats §5).

- **Q5 ✅** — Placement DB : **DB dédiée `ml/state/scan_corpus.db`** (§4).
- **Conditions ce cycle ✅** — on **ajoute `glare` + `inhand`** maintenant (⇒
  nouvelles lignes prescrites dans l'app cohort-test). `worn` différé (pièces
  propres).

_Toutes les décisions sont prises — la spec est prête à implémenter (§12)._

### App cohort-test — garder le bench §I4d **et** archiver

La vue §I4d (matrice pièce × condition, studio vs live R@1, delta) est à
**conserver** — c'est le tableau de bord du bench. L'archivage frames s'y **ajoute
sans la remplacer** : au SNAP, en plus d'émettre la ligne JSONL qui alimente
§I4d, l'app persiste raw+crop (§6). Deux besoins, un seul flux de capture :
- **Bench §I4d** (existant) : prédiction → JSONL → sync → matrice. Inchangé.
- **Corpus** (nouveau) : raw+crop → frames → pull → import. Additif.

Les nouvelles conditions `glare`/`inhand` = de nouvelles lignes prescrites dans
la boucle de test (même mécanique que `bright/dim/tilt`). À cadrer : le nombre de
conditions × pièces gouverne la taille du corpus (`README.md` §4).

---

## 12. Plan d'implémentation (ordonné — la spec est figée)

Chaque lot est testable isolément. Ordre = dépendances.

**Lot 1 — Store corpus (Python, PC).**
- `ml/store/scan_corpus.py` : helper d'ouverture `ml/state/scan_corpus.db`
  (créé si absent) + DDL de la table `scan_corpus` (§4) + upsert idempotent par
  `capture_id` + requêtes de filtre (par `cohort_id`, `condition`, date).
- **Interdit** : ne référence ni `eurio.db`, ni `eurio.replica.db`, ni
  `local_state_store()`. Store autonome. Ajouter `scan_corpus.db*` au `.gitignore`.
- Tests : création DB, upsert idempotent (même `capture_id` 2× = 1 ligne), filtre.

**Lot 2 — Archivage device (Kotlin, cohort-test) + pull.**
- `app-android/src/cohortTest/.../LiveTestLogger.kt` (ou voisin) : au SNAP,
  persister `raw.jpg` (frame détection) + `crop.png` (sortie `SnapNormalizer`)
  sous `<external>/Documents/eurio_live_tests/frames/<iteration>/<capture_id>.*`
  et ajouter `raw_sha`/`crop_sha` à la ligne JSONL. **Ne pas casser §I4d**
  (le JSONL existant reste valide, on n'ajoute que 2 champs).
- Ajouter les conditions `glare` + `inhand` au set prescrit (mécanique identique
  à `bright/dim/tilt`).
- `app-android/Taskfile.yml` `cohort-test:pull-tests` : tirer aussi
  `eurio_live_tests/frames/<iteration>/`.
- Vérifier `capture_id` device == `sha256(raw)[:16]` recalculé côté PC (parité
  hash) — sinon la dédup casse.

**Lot 3 — Import (Python, PC).**
- `ml/scripts/import_scan_corpus.py` : lit le JSONL pullé + les frames, hash-
  vérifie (`capture_id` == sha256(raw)), copie dans `scan_corpus/frames/`,
  upsert `scan_corpus`. Idempotent. **Une ligne JSONL = une capture** (pas de
  best-of ici — le corpus garde toutes les frames).
- `go-task` : exposer `scan-corpus:import ITERATION=<iid>`.

**Lot 4 — Replay + scorecard (Python, PC) — le cœur du funnel S0.**
- `ml/scripts/replay_corpus.py` : entrée = candidat `{centroïdes, modèle, seuils}`
  + filtre corpus ; sortie = `scorecard.json` (§8) + `predictions.jsonl` (§8bis).
  Chemin rapide (crop→embed→match) + chemin complet (raw→détection→normalise→…).
  **Parité obligatoire** avec le matcher Android + l'eq du §5
  (`serving/distance_logic.py`, `training.eval.equivalence`). Résout le
  `design_group` en Python contre la réplique **en lecture seule**.
- McNemar baseline↔candidat sur `predictions.jsonl` (p-value dans la scorecard).
- Baseline épinglée (§9) : `ml/state/scan_baselines/prod/` = bundle prod gelé.

**Lot 5 — Template d'expérience.**
- `docs/work-in-progress/scan-quality/exp-template.md` : hypothèse / **variable
  unique** / corpus `vN` (hash+filtre) / baseline battue / scorecard remplie /
  McNemar / **décision go-no-go par étage** (S0→S3) + verdict écrit.

**Lot 6 — Rodage : `exp-01-centroids`.**
- Générer les centroïdes `train_mean` (`compute_embeddings.py --centroid-source
  train_mean`, déjà dispo) → candidat.
- Replay sur les 48 frames actuelles vs baseline `val_mean` → scorecard + McNemar.
- Valide le funnel **de bout en bout**. On ne conclut « gain » que sur delta
  franc (≥ ~5 pts) ou shift net par condition (n encore petit, cf. §8bis).
- Écrire `exp-01-centroids.md` (verdict) + mettre à jour `README.md` §8.
</content>
</invoke>
