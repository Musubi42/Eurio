# Chunk 7 — Bench protocol + replay tooling

> Boucle de mesure complète : (1) record JSONL exhaustif côté Android,
> (2) extraction ADB vers PC, (3) replay offline en Python avec
> paramètres alternatifs, (4) calibration des seuils, (5) protocole
> bench sur cohort 50 captures, (6) reporting comparatif. C'est ce
> qui transforme les décisions empiriques (D6 trigger gagnant, seuils
> qualité, timeouts) de "feeling" en "métriques justifiables".

## Pré-requis

- Chunks 1-6 livrés. La state machine, les triggers, le scoring, le
  lock, l'archive et la viz debug tournent.

## Goal

À la fin du chunk-7 :

1. **Record exhaustif** côté Android : JSONL streamable + frames raw
   (opt-in) pour chaque session de scan en mode bench. Stocké dans
   `context.filesDir/bench/sessions/<session_id>/`.
2. **Extraction simple** via `adb pull` ou `go-task` cible dédiée.
3. **Replay Python offline** : prend une session enregistrée, applique
   d'autres paramètres trigger/scoring/timeouts, produit le JSONL
   "ce que la machine aurait fait", sans rescanner physiquement.
4. **Calibration** : script qui prend N sessions annotées
   (ground-truth eurio_id + ground-truth best-frame humain) et
   propose des seuils optimaux par grid/Bayesian search.
5. **Reporting comparatif** : `compare_runs.py` qui aligne 2+
   stratégies sur le même set bench et sort un tableau de métriques
   + plots (latence end-to-end, best-frame agreement, accuracy).
6. **Protocole bench documenté** : 50 captures cohort, conditions
   standardisées, annotation humaine, métriques cibles.

## Scope

**Dans le chunk** :

- Android : `BenchRecorder.kt` (writer JSONL streamé + frames JPEG
  optionnels), wiring dans le ViewModel pour consommer les
  `ScanEvent` et les frames du `RollingFrameBuffer`.
- Android : toggle "Record session" dans la debug-bar (chunk-1, déjà
  présent) qui démarre/stoppe un session_id.
- Android : écran debug "Bench sessions" listant les sessions
  enregistrées, taille, possibilité de les supprimer (avant pull PC).
- `go-task bench:pull` : commande qui `adb pull` les sessions vers
  `ml/bench/sessions/`.
- Python : `ml/bench/replay_session.py` — replay offline.
- Python : `ml/bench/annotate_session.py` — UI CLI pour annoter
  ground-truth (best-frame humain, eurio_id confirmé).
- Python : `ml/bench/calibrate_thresholds.py` — grid search +
  ranking des configs candidates.
- Python : `ml/bench/compare_runs.py` — métriques + plots.
- Doc : protocole bench standardisé dans ce chunk + capture
  conditions list dans `ml/bench/conditions.md`.

**Hors chunk** :

- Sync automatique vers MinIO ou Supabase Storage (post-v1, hors scope
  best-frame — éventuellement couplé à la phase marketplace future).
- UI admin web pour browser les sessions (chunk dédié futur si
  besoin — aujourd'hui CLI suffit).
- Bench cross-device automatisé (CI device farm) — manuel sur
  Pixel 9a + 1 mid-range Samsung pour v1.

## Architecture

```
[Android device]
   │
   │ session start (toggle debug-bar)
   ↓
   BenchRecorder.start(session_id)
   │
   │ collect ScanEvent flow
   │ collect frames optionnellement
   ↓
   /data/data/com.musubi.eurio/files/bench/sessions/<id>/
     ├─ events.jsonl              (streamé, 1 event/ligne)
     ├─ config.json               (DebugScanConfig snapshot au start)
     ├─ device_info.json          (Build.MODEL, API, sensor)
     └─ frames/                   (opt-in)
          ├─ 0001.jpg
          ├─ 0002.jpg
          └─ …

[adb pull via go-task bench:pull]
   ↓
   ml/bench/sessions/<device>/<id>/

[Python tooling]
   │
   ├─ replay_session.py
   │     │
   │     │ load events.jsonl + frames/
   │     │ apply alternative config
   │     │ → produce replay_<config_hash>.jsonl
   │
   ├─ annotate_session.py
   │     │
   │     │ CLI interactif: montre les 5 frames du buffer,
   │     │ user choisit "best human pick" + confirme eurio_id
   │     │ → produce ground_truth.json
   │
   ├─ calibrate_thresholds.py
   │     │
   │     │ load N sessions + leurs ground_truth.json
   │     │ grid search sur (sharpnessMin, exposureBand, completeness)
   │     │ optimize best-frame agreement
   │     │ → output recommended_thresholds.json
   │
   └─ compare_runs.py
         │
         │ load 2+ sessions (original + replays)
         │ compute latency, agreement, accuracy
         │ render markdown table + matplotlib plots
         │ → report.md + plots/*.png
```

## Format `events.jsonl`

**Une ligne = un event JSON**. Streamé en append, pas de parse-then-rewrite.

```jsonl
{"t":1715769600.123,"evt":"session_start","session_id":"abc","schema_version":1}
{"t":1715769600.124,"evt":"device_info","model":"Pixel 9a","api":34,"sensor":"…"}
{"t":1715769600.125,"evt":"config_snapshot","config":{…full DebugScanConfig…}}
{"t":1715769601.456,"evt":"frame_analyzed","seq":0,"detection":{"method":"yolo","bbox":[…],"yolo_conf":0.62,"center":[640,480],"radius":180},"score":{"sharpness":0.74,"sharpness_raw":142.0,"exposure":0.81,"mean_luminance":0.48,"clipping_ratio":0.003,"completeness":1.0,"motion":null,"aggregate":0.83,"passes":{"sharpness":true,"exposure":true,"completeness":true,"motion":null,"all":true}},"arcface_top3":[{"eurio_id":"es-2018-2eur-asturias","cos":0.61},{"eurio_id":"es-2010-2eur","cos":0.42},{"eurio_id":"pt-2015-2eur","cos":0.38}],"timings_ms":{"detect":42,"normalize":18,"score":8,"arcface":15}}
{"t":1715769601.500,"evt":"state_transition","from":"Idle","to":"Detecting","via_event":"FirstDetection"}
{"t":1715769602.000,"evt":"trigger_fire","strategy":"box_stability","reason":"stable 3f IoU≥0.70","buffer_size":5,"buffer_seqs":[1,2,3,4,5]}
{"t":1715769602.001,"evt":"best_frame_selected","selection_reason":"PASSED_ALL_GATES","index_in_snapshot":3,"frame_seq":4,"aggregate":0.91}
{"t":1715769602.002,"evt":"state_transition","from":"Detecting","to":"Locking","via_event":"TriggerFire"}
{"t":1715769602.050,"evt":"lock_state","state":"Acquiring","af_region":[…]}
{"t":1715769602.450,"evt":"lock_state","state":"Locked","af_converged":true,"duration_ms":400,"ae_locked":true,"awb_locked":true}
{"t":1715769602.451,"evt":"state_transition","from":"Locking","to":"Capturing","via_event":"LockAcquired"}
{"t":1715769602.700,"evt":"capture_completed","capture_id":"cap-xyz","source_mode":"IMAGE_CAPTURE_FULL","jpeg_bytes":1842137}
{"t":1715769602.701,"evt":"state_transition","from":"Capturing","to":"Identifying","via_event":"CaptureCompleted"}
{"t":1715769603.100,"evt":"consensus_reached","eurio_id":"es-2018-2eur-asturias","top_k":[…]}
{"t":1715769603.101,"evt":"state_transition","from":"Identifying","to":"Accepted","via_event":"ConsensusReached"}
{"t":1715769603.200,"evt":"archive_completed","capture_id":"cap-xyz","filename":"cap-xyz.jpg","is_primary":true,"score_aggregate":0.91}
{"t":1715769605.000,"evt":"user_dismiss"}
{"t":1715769605.001,"evt":"state_transition","from":"Accepted","to":"Idle","via_event":"UserDismiss"}
{"t":1715769605.002,"evt":"session_end","duration_ms":4879}
```

Schéma versionné via `schema_version`. Pas de breaking change sans
bump explicite.

**Taille estimée** : ~3-5 KB par frame analysée + 1-2 KB par transition.
Session typique 20 frames + 10 transitions = ~80 KB JSONL. Très léger.

## Frames raw recording

Opt-in via `DebugScanConfig.recordFramesEnabled` (en plus de
`recordEnabled` qui gère le JSONL).

- Format : JPEG quality 85, long-side max 1024 (compromis taille
  vs reproductibilité).
- Naming : `frames/<seq:04d>.jpg`, seq = sequenceId du
  `BufferedFrame`.
- Volume : ~150 KB/frame × 20 frames = ~3 MB par session.
- Pas de frames pendant `Idle` (économie).

Le replay Python peut utiliser ces frames pour re-scorer en
reproduisant exactement le `FrameQualityScorer` Kotlin côté Python
(via wrappage OpenCV ; déjà disponible dans `ml/scan/normalize_snap.py`).

**Décision** : on fournit un module `ml/quality/frame_scorer.py`
**bit-for-bit équivalent** au `FrameQualityScorer.kt` (mêmes algos,
mêmes constantes). Précondition de validité du replay. Cohérent
avec le pattern de la phase 4 du chantier scan-normalization (Kotlin↔Python parity, cf. `project_scan_normalization`).

## `BenchRecorder.kt`

```kotlin
class BenchRecorder(
    private val context: Context,
    private val scope: CoroutineScope,
) {
    private var session: BenchSession? = null
    private val writeChannel = Channel<String>(capacity = 256)

    suspend fun start(): String {
        val sessionId = generateSessionId()
        val dir = File(context.filesDir, "bench/sessions/$sessionId").apply { mkdirs() }
        val eventsFile = File(dir, "events.jsonl")
        session = BenchSession(sessionId, dir, eventsFile)
        scope.launch { drainWrites(eventsFile) }
        log(BenchEvent.SessionStart(sessionId))
        return sessionId
    }

    suspend fun stop() {
        log(BenchEvent.SessionEnd(System.currentTimeMillis() - session!!.startedAt))
        writeChannel.close()
        session = null
    }

    fun log(event: BenchEvent) {
        val line = Json.encodeToString(BenchEvent.serializer(), event)
        writeChannel.trySend(line)
    }

    fun recordFrame(seq: Int, bitmap: Bitmap) {
        val s = session ?: return
        scope.launch(Dispatchers.IO) {
            val out = File(s.dir, "frames/${"%04d".format(seq)}.jpg")
            out.parentFile?.mkdirs()
            out.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 85, it) }
        }
    }

    private suspend fun drainWrites(file: File) {
        file.bufferedWriter().use { writer ->
            for (line in writeChannel) {
                writer.appendLine(line)
                writer.flush()  // streaming, pas de buffer accumulé
            }
        }
    }
}
```

Câblé dans le `ScanViewModel` : pour chaque `ScanEvent` collecté, on
log dans le `BenchRecorder` si la session est active.

## Toolchain Python

### `ml/bench/replay_session.py`

```python
"""
Replay a recorded scan session offline with alternative config.

Usage:
    python -m ml.bench.replay_session \
        --session ml/bench/sessions/Pixel9a/abc/ \
        --config-overrides triggerMode=yolo_confidence yoloConfMin=0.45 \
        --output ml/bench/output/abc-yoloconf.jsonl
"""
```

Le script :
1. Parse `events.jsonl` + `config.json` + `device_info.json`.
2. Reconstitue la séquence de `frame_analyzed` events.
3. Re-applique les algos (trigger, scorer, selector) avec les
   overrides → produit un JSONL "shadow" de ce qui se serait passé.
4. Si `frames/` dispo : re-score les frames depuis les images
   sources (vérifie la parité avec les scores enregistrés ± epsilon).
5. Sinon : utilise les scores enregistrés tels quels (les seuils
   absolus changent les `passes`, mais les sub-scores restent).

Limitation : on ne peut pas replay des changements de **détection**
(YOLO vs Hough), parce qu'on n'a pas les frames source full-res
préservées. Le replay opère sur ce que la détection a vu, pas sur la
détection elle-même.

### `ml/bench/annotate_session.py`

```python
"""
CLI interactif d'annotation des sessions bench.

Pour chaque session :
- montre les 5 frames du buffer au moment du trigger (vignettes)
- demande à l'humain : "Laquelle est la meilleure ?" (1-5)
- demande : "Confirme l'eurio_id détecté ?" (y/n + correction)
- demande : "Conditions (bright_plain / dim / oblique / …)" (choix liste)
- écrit `ground_truth.json`
"""
```

Sortie : `ml/bench/sessions/<device>/<id>/ground_truth.json`

```json
{
  "human_best_frame_seq": 4,
  "confirmed_eurio_id": "es-2018-2eur-asturias",
  "model_top1_correct": true,
  "condition": "bright_plain",
  "notes": "léger reflet visible sur la rim, ne devrait pas pénaliser"
}
```

UI : on peut utiliser `rich` + `Pillow` pour rendre les vignettes en
terminal (Sixel/Kitty graphics protocol si dispo, sinon ouverture
visionneuse système). Pour v1, simple fallback `subprocess.run(["open",
img])` sur macOS.

### `ml/bench/calibrate_thresholds.py`

```python
"""
Grid search sur les seuils qualité pour maximiser le best-frame agreement.

Métrique optimisée : % de sessions où BestFrameSelector(thresholds) choisit
la même frame que human_best_frame_seq.

Search space :
  sharpnessMin: [40, 60, 80, 100, 120, 160]
  exposureBandHalfWidth: [0.15, 0.20, 0.25, 0.30]
  completenessMin: [0.85, 0.90, 0.95, 0.98]

Output : ranking top-10 configs + ROC curves.
"""
```

Pour la v1, grid search exhaustif suffit (6×4×4 = 96 configs, < 1s
chacune en replay). Si on étend (motion, ceiling normalisation, etc.)
on passera à Bayesian via `optuna`.

### `ml/bench/compare_runs.py`

```python
"""
Compare N runs sur le même set de sessions et produit un rapport.

Usage:
    python -m ml.bench.compare_runs \
        --runs original yoloconf arcfaceconsensus \
        --sessions ml/bench/sessions/Pixel9a/ \
        --output ml/bench/reports/2026-05-15-trigger-bake-off.md

Produces:
    - tableau Markdown :
        | metric | original | yoloconf | arcfaceconsensus |
        | --- | --- | --- | --- |
        | end-to-end latency (p50) | 1.84s | 2.10s | 1.60s |
        | end-to-end latency (p95) | 2.42s | 2.85s | 2.10s |
        | best-frame agreement | 78% | 82% | 65% |
        | recognition top-1 | 92% | 93% | 91% |
        | lock success rate | 96% | 94% | n/a |
    - plots: matplotlib violin/box des latences, histo des aggregates retenus.
"""
```

## Protocole bench cohort

### Set canonique

- **10 pièces** cohort fixes (du `cohort_capture_flow` existant —
  cf. `project_cohort_capture_flow.md`).
- **5 conditions** par pièce :
  - `bright_plain` (lumière jour, fond uni)
  - `bright_textured` (lumière jour, fond bois/tissu)
  - `dim` (intérieur soir, lampe loin)
  - `oblique` (caméra tilt ~30° par rapport à la pièce)
  - `partial_shadow` (moitié pièce ombrée)
- **Total** : 50 sessions de scan.

Pour chaque session :
1. Démarrer la session via debug-bar (toggle "Record" + nom).
2. Scanner la pièce dans la condition demandée.
3. Stopper.
4. Pull device après les 50 sessions.

### Annotation

Une fois pull :
1. Pour chaque session, lancer `annotate_session.py` interactif.
2. Confirmer ground-truth eurio_id (si mismatch → fix dans le set
   de tests, signal modèle).
3. Picker le best frame humain (1-5).
4. Confirmer condition.

Temps estimé : ~30s par session × 50 = 25 min annotation total.

### Métriques cibles initiales (à valider empiriquement)

| Métrique | Cible v1 | Cible v2 (post-distillation) |
|---|---|---|
| End-to-end latency p50 (FirstDetection → Accepted) | < 2.5 s | < 1.8 s |
| End-to-end latency p95 | < 4.0 s | < 3.0 s |
| Best-frame agreement (selector vs human) | > 70% | > 85% |
| Recognition top-1 accuracy | > 90% (bright), > 75% (dim/oblique) | > 95% / > 85% |
| Lock success rate (LockState.Locked atteint) | > 92% | > 96% |
| Archive completion rate (sur reconnues) | > 95% | > 98% |

### Décisions actionnables post-bench

Après la cohort :
1. **Choix trigger gagnant** : meilleure latence p50 AVEC ≥ 70%
   best-frame agreement AVEC ≥ 90% top-1 accuracy.
2. **Seuils qualité figés** : sortie de `calibrate_thresholds.py`.
3. **Timeouts ajustés** : si `lock success rate < 92%` en
   conditions dim/oblique, on étend `LOCKING_TIMEOUT_MS`.
4. **Décision conjointe (D6)** : retirer ou conserver les
   stratégies non-élues. Si une stratégie a 0% d'usage hors bench,
   on en discute pour la mettre en `@Deprecated` (pas suppression
   silencieuse).

## Fichiers à créer

### Android

| Fichier | Rôle |
|---|---|
| `ml/bench/BenchRecorder.kt` | Writer JSONL streamé + frames JPEG |
| `ml/bench/BenchEvent.kt` | Sealed class events sérialisables (kotlinx-serialization) |
| `ml/bench/BenchSession.kt` | Holder session_id + paths |
| `features/scan/debug/BenchSessionsScreen.kt` | Liste sessions, taille, delete |
| `features/scan/debug/BenchSessionsLauncher.kt` | Bouton "📂 Sessions" dans debug-bar |

### Tâches go-task

| Tâche | Effet |
|---|---|
| `bench:pull` | `adb pull /data/data/.../files/bench/ ml/bench/sessions/<device>/` |
| `bench:annotate <device> <id>` | wrapper sur `annotate_session.py` |
| `bench:replay <device> <id> <config>` | wrapper sur `replay_session.py` |
| `bench:calibrate <device>` | wrapper sur `calibrate_thresholds.py` |
| `bench:compare <device> <run1> <run2> …` | wrapper sur `compare_runs.py` |

### Python

| Fichier | Rôle |
|---|---|
| `ml/bench/__init__.py` | Module bench |
| `ml/bench/session_io.py` | Parsers JSONL + ground_truth + config |
| `ml/bench/replay_session.py` | Replay offline |
| `ml/bench/annotate_session.py` | UI CLI annotation |
| `ml/bench/calibrate_thresholds.py` | Grid search seuils |
| `ml/bench/compare_runs.py` | Reporting comparatif |
| `ml/quality/frame_scorer.py` | Port Python du scorer Kotlin (parity) |
| `ml/quality/frame_scorer_test.py` | Tests de parité Kotlin↔Python sur fixtures partagées |
| `ml/bench/conditions.md` | Doc des 5 conditions standardisées |
| `ml/bench/cohort.json` | Liste fixe des 10 pièces cohort |

## Acceptance criteria

**Record côté Android** :
- [ ] Toggle "Record session" dans debug-bar démarre une session,
      crée `bench/sessions/<id>/events.jsonl`.
- [ ] Toggle off ou app paused → session proprement fermée
      (event `session_end` écrit, fichiers flushés).
- [ ] Toggle "Record frames" supplémentaire → `frames/<seq>.jpg`
      apparaissent en parallèle.
- [ ] App crash en cours de session → `events.jsonl` partiel
      lisible (streaming flush garantit ça).
- [ ] Taille session typique 20 frames + 10 transitions ≈ 80 KB
      JSONL (sans frames) ; ≈ 3 MB avec frames.

**Extraction** :
- [ ] `go-task bench:pull` ramène tous les sessions sans permission
      manuelle (adb autorisé).
- [ ] Sessions Pull-able même si app encore en cours d'utilisation
      (pas de fichier locked).

**Replay** :
- [ ] `replay_session.py --config triggerMode=yolo_confidence`
      produit un JSONL shadow différent de l'original (si la session
      original utilisait `box_stability`).
- [ ] `frame_scorer.py` produit des scores ≤ 1e-3 d'écart vs les
      scores Kotlin enregistrés (parité).
- [ ] Sessions sans `frames/` peuvent toujours être replay sur les
      seuils (sans re-scoring à partir des images).

**Annotation** :
- [ ] `annotate_session.py` permet de picker best-frame + confirmer
      eurio_id en < 30 s par session.
- [ ] `ground_truth.json` écrit, lisible par `calibrate_thresholds`.

**Calibration & reporting** :
- [ ] `calibrate_thresholds.py` produit un ranking top-10 sur 50
      sessions annotées en < 60s.
- [ ] `compare_runs.py` génère un Markdown report + 4 plots PNG.

**Protocole** :
- [ ] La cohort 10×5 = 50 captures est documentée, conditions
      définies, fichier `cohort.json` validé contre Supabase coins.
- [ ] Premier bench complet exécuté : rapport commit dans
      `docs/best-frame-capture/results/2026-XX-XX-bench-1.md`.

## Questions ouvertes à trancher pendant l'implem

1. **Frames raw : JPEG q85 long-side 1024 vs PNG** : JPEG q85 induit
   un léger biais sur la sharpness mesurée vs frame source vraie. Mon
   vote : JPEG q85, et on documente le biais. PNG triplerait la
   taille. Acceptable si le test de parité reste < 1e-3 d'écart.
2. **Sync vers MinIO** : pas v1 (pull manuel ADB suffit). Quand la
   cohort sera fixée, on automatisera — décision à reprendre
   éventuellement avec la phase marketplace future.
3. **Replay sur frames source vs scores enregistrés** : si on veut
   bench un nouveau `FrameQualityScorer` (ex: ajout d'un sous-score
   `texture_richness`), on a besoin des frames. Sinon on est
   limité aux seuils sur les 4 sous-scores existants. Inviter
   l'opérateur à toujours enregistrer les frames pour les sessions
   bench formelles, opt-out pour sessions exploratoires.
4. **Annotation collaborative** : si plusieurs personnes annotent,
   on a besoin d'un `annotator_id` dans ground_truth.json. Pour v1
   solo dev, on hard-code `raphael`.
5. **Cross-device aggregation** : pour comparer Pixel 9a vs Samsung
   A35, `compare_runs.py` doit filtrer par device. Implémenté via
   `--device` flag.
6. **Cohort 10 pièces, est-ce assez ?** Statistical sample size pour
   90% confidence sur best-frame agreement à 80% : ~80 samples →
   on est juste à 50 captures. Acceptable pour orienter, pas pour
   "ship a model with confidence". Pour la décision finale trigger,
   on étendrait à 20 pièces × 5 conditions = 100 captures.

## Mémoires & règles liées

- D19, D20 implémentés ici fidèlement (record opt-in, replay).
- D21 (overlay graphique) — les events captés par BenchRecorder
  sont précisément ceux qui pilotent l'overlay : donc on peut
  rejouer visuellement une session dans un viewer Python (out of
  scope v1, mais le format JSONL est compatible).
- `feedback_no_debt` — pas de fallback silencieux : si l'écriture
  JSONL échoue, la session est marquée `corrupt` (event final
  inattendu), elle n'est pas archivée comme "réussie".
- `feedback_chunk_audit_flow` — audit attendu : screencast d'une
  session bench complète, du pull ADB jusqu'au compare_runs report.
- `feedback_nix_devshell` — tous les deps Python (matplotlib, rich,
  optuna éventuel) via `flake.nix`, jamais `pip install` direct.
- `feedback_gotask_binary` — toutes les tâches passent par
  `go-task`, pas `task`.
- `project_cohort_capture_flow` — cohort déjà défini admin-side,
  on en hérite directement.
