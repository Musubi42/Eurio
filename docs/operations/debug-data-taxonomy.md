# Debug data taxonomy — rangement, pull/clean par catégorie, visibilité on-device

> **Statut : VALIDÉ (décisions actées 2026-05-29) — prêt pour implémentation.**
> Design doc pour ranger les données debug écrites par l'app sur le device,
> les pull/clean catégorie par catégorie, et donner une visibilité read-only
> de ce qui est *réellement* sur le filesystem (+ fix du resume capture cohort).
>
> Intent : memory `project_cohort_capture_flow`, `project_crop_format_ablation`.
> Tracker opérationnel capture : `docs/cohort-capture-ablation.md`.

---

## 1. Problème

L'app écrit de la donnée debug à plusieurs endroits, sans taxonomie claire :

- Un seul `pull-debug` ramasse **tout** `eurio_debug/` en vrac (eval_real +
  snaps + tous les `session_*`), y compris des choses périmées.
- `clean-debug` fait `rm -rf eurio_debug` → **tout ou rien**, dangereux.
- Les noms de dossiers (`snaps`, `session_<ts>`) ne disent pas grand-chose sur
  l'écran qui les a produits une fois mélangés.
- **Aucune visibilité côté téléphone** : impossible de savoir ce qui est
  vraiment écrit sans faire un pull sur l'ordi.
- **Bug resume (déclencheur initial)** : `CaptureViewModel.enter()` reset les
  index à 0 à chaque ouverture → la progression capture cohort *paraît*
  perdue (les fichiers, eux, survivent — rien ne les efface).

### 1.1 Inventaire des producteurs/consommateurs debug (vérifié code 2026-05-29)

Racine commune : `getExternalFilesDir(DIRECTORY_DOCUMENTS)/eurio_debug/`
(`EurioApp.kt:187-190`) → **stockage externe, donc `adb pull` fonctionne sans
root**.

| Catégorie | Écran / source | Chemin device | Forme | Code | Statut |
|---|---|---|---|---|---|
| **Capture Cohort** | `/dev/capture` | `…/Documents/eurio_debug/eval_real/<eurioId>/` | `<step>[_p<n>]_{crop,raw}.jpg` + `<step>.json` | `CaptureViewModel.kt`, `CoinAnalyzer.kt:490-504` | **canonique** |
| **Photo snap** | `/dev/photo` | `…/eurio_debug/snaps/snap_<ts>/` | `crop.jpg`/`raw.jpg`/`meta.json` | `CoinAnalyzer.kt:461-528` | jetable |
| **Scan record** | barre debug `/scan` | `…/eurio_debug/session_<ts>/` | `frame_*.jpg`(+`_annotated`/`_crop`) + `session.jsonl` | `ScanViewModel` (`onRecordToggle`), `CoinAnalyzer.kt:779-852` | jetable |
| **Bench protocol** | `/dev/bench` | `getExternalFilesDir(null)/bench/sessions/<id>/` ⚠️ **autre racine** (pas sous `Documents/eurio_debug`) | `events.jsonl` + `frames/%04d.jpg` | `BenchRecorder.kt:98-197` | semi-canonique |
| **Cohort live-tests** | app séparée `com.musubi.eurio.cohorttest` | `…/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iid>.jsonl` ⚠️ **autre package** | JSONL 1 ligne/test | `LiveTestLogger.kt`, `CohortTestActivity.kt` | jetable |
| Carousel / 3D sandbox | `/dev/carousel`, `/dev/coin-3d-sandbox` | — (aucune écriture) | — | — | — |
| Vault (HORS scope) | scan prod | `filesDir/vault/<id>.jpg` (interne, app-private) | JPEG | `VaultFilesystemWriter.kt` | données user, **pas debug** |
| Caches (HORS scope) | 3D / EXIF | `cacheDir/coin-3d-normals/`, `cacheDir/exif-strip-*` | PNG / temp | `NormalMapBuilder.kt`, `ExifStripper.kt` | éphémère système |

Constats :
- Bench est **déjà séparé** (racine + task `bench:pull` dédiés) — modèle cible,
  mais sur une **autre racine** que `eurio_debug`.
- **Deux racines orphelines manquaient à l'ancien inventaire** : bench
  (`files/bench/`) et surtout les **cohort live-tests** d'un **package distinct**
  (`com.musubi.eurio.cohorttest`, pull via `android:cohort-test:pull-tests` →
  `ml/state/live_test_logs/`). La taxonomie doit les nommer, même pour les
  scoper-out explicitement.
- ✅ `eval_real/manifest.jsonl` **existe** (`CaptureViewModel.appendManifest`,
  l.281-302) : log **append-only**, 1 ligne JSON par snap réussi (`ts`,
  `eurio_id`, `step_id`, `step_index`, `photo_index`, `crop_path`, …). Il ne
  trace **pas les skips** (`onSkipCell` l.226 n'écrit rien). La persistance des
  skips (§5) **étend** ce manifeste existant, n'en crée pas un second.
- ✅ **Bug resume confirmé** : `enter()` (l.96-100) force `coinIdx=stepIdx=
  photoIdx=captured=0` à chaque ouverture. Les crops sur disque survivent
  (chemin déterministe), seul le curseur UI est perdu.

---

## 2. Décisions actées (2026-05-29)

| # | Question | Décision |
|---|---|---|
| 1 | Renommage `eval_real` | **NE PAS renommer `eval_real`** (device **ni** ML) — utilisé partout côté Python (~15 fichiers), risque de tout casser pour zéro gain. On garde `eurio_debug/eval_real/` tel quel. |
| 2 | Autres renommages | **Renommer uniquement le sûr** : `snaps/` → `photo_snaps/`, `session_<ts>/` → `scan_sessions/session_<ts>/`. Ces dossiers ne sont lus que par les tasks pull qu'on contrôle. |
| 3 | Tasks globales | **Garder** `pull-debug`/`clean-debug` (alias « tout ») **+** ajouter les tasks par catégorie. |
| 4 | Migration device | **Aucune** : plus rien à sauvegarder, on **wipe + re-capture clean**. Pas de script `adb shell mv`. |
| 5 | Skips capture | **Persister dans le `manifest.jsonl` existant** (pas un 2e fichier) : `onSkipCell` ajoute une ligne `{"event":"skip","eurio_id":…,"step_id":…,"step_index":…}`. Distingue « pas encore fait » de « volontairement passé » sans dupliquer la source. |
| 6 | Visibilité on-device | **Écran dédié read-only `/dev/status`** (pas une icône ⓘ noyée). Lit le FS, **aucune suppression depuis le téléphone**. |
| 7 | Bench / autres catégories | **Capture cohort d'abord** (chunk A, testé bout-en-bout), puis rollout au reste (photo/scan/bench). Rapatriement bench = différé au rollout. |

Principe transverse confirmé : **suppression device = task `clean` dédiée et
explicite, jamais automatique, jamais depuis le front**.

---

## 3. Taxonomie cible

Racine de sortie unique, un sous-dossier par catégorie. `eval_real/` **garde son
nom** (décision #1) ; les autres sont renommés (décision #2).

```
…/Documents/eurio_debug/          # SORTIES debug
├── eval_real/                    # ← /dev/capture   (NOM CONSERVÉ — coupling ML)
│   ├── manifest.jsonl            # EXISTANT : 1 ligne/snap ; + lignes "event":"skip" (§5)
│   └── <eurioId>/
│       ├── <step>_crop.jpg
│       ├── <step>_raw.jpg
│       ├── <step>.json
│       └── <step>_p{1,2,3}_*     # mode ablation (4 photos/cellule)
├── photo_snaps/                  # ← /dev/photo     (renommé depuis snaps/)
│   └── snap_<ts>/{crop,raw}.jpg + meta.json
└── scan_sessions/                # ← /scan record   (renommé, ex session_<ts>/ à plat)
    └── session_<ts>/frame_*.jpg + session.jsonl

getExternalFilesDir(null)/bench/  # ← /dev/bench (autre racine, rapatriement différé)
└── sessions/<id>/events.jsonl + frames/

…/Documents/eurio_capture/        # ENTRÉE (CSV poussé par admin) — inchangé
└── cohort.csv

[package com.musubi.eurio.cohorttest] eurio_live_tests/<iid>.jsonl  # hors scope chunk A
```

Comme `eval_real/` n'est pas renommé, **aucune modif ML n'est requise** :
`sync_eval_real.py` continue d'auto-détecter `eval_real/` dans le pull. C'est le
chemin le plus sûr (zéro régression pipeline ML).

---

## 4. Tasks pull / clean par catégorie

Namespace par catégorie. Chaque `*:pull` finit par afficher le compte pullé + la
commande `*:clean` prête à coller. Tasks dans `app-android/Taskfile.yml`.

| Task | Pull depuis | Vers | Clean |
|---|---|---|---|
| `capture:pull` / `capture:clean` | `eurio_debug/eval_real/` | `debug_pull/eval_real/<ts>/` | `rm -rf …/eval_real` |
| `photo:pull` / `photo:clean` | `eurio_debug/photo_snaps/` | `debug_pull/photo_snaps/<ts>/` | `rm -rf …/photo_snaps` |
| `scan:pull` / `scan:clean` | `eurio_debug/scan_sessions/` | `debug_pull/scan_sessions/<ts>/` | `rm -rf …/scan_sessions` |
| `bench:pull` *(existe)* / `bench:clean` *(rollout)* | `bench/sessions/` | `ml/bench/sessions/<device>/` | `rm -rf …/bench` |
| `pull-debug` / `clean-debug` *(conservées)* | tout `eurio_debug/` | `debug_pull/<ts>/` | `rm -rf eurio_debug` |

Exemple de fin de `capture:pull` :

```
✓ Pullé 47 crops · 12 coins (2 skipped) → debug_pull/eval_real/20260529_171204/
  Sur le device : inchangé tant que tu ne nettoies pas.
  Pour libérer le téléphone :
      go-task -t app-android/Taskfile.yml capture:clean
```

- **Pas de delete automatique** : `*:clean` est une commande séparée.
- ⚠️ Edge case : capture *après* pull et *avant* clean → `clean` efface aussi les
  nouvelles. Mitigation : le message de `*:pull` rappelle de cleaner juste après.

---

## 5. Persistance des skips (manifest.jsonl existant)

On **réutilise** `eurio_debug/eval_real/manifest.jsonl` (déjà écrit par
`appendManifest`). Aujourd'hui il logge 1 ligne par snap réussi ; on ajoute une
ligne dédiée quand l'utilisateur skippe une cellule :

```jsonl
{"ts":"…","eurio_id":"2_FR_2010","step_id":"bright_plain","step_index":0,"photo_index":0,"crop_path":"…"}
{"ts":"…","eurio_id":"2_FR_2010","step_id":"dim_plain","step_index":1,"event":"skip"}
```

- **Capture** = présence du `<step>[_p<n>]_crop.jpg` sur disque → **le disque est
  l'autorité** pour `captured` (robuste même si le manifeste diverge).
- **Skip** = ligne `"event":"skip"` dans le manifeste (pas de fichier disque).
- Skipper = `onSkipCell` ajoute la ligne skip **avant** d'avancer le curseur.
- Pas de second fichier d'état : une seule source append-only, déjà pullée avec
  le reste de `eval_real/`.

---

## 6. Visibilité on-device + resume (scanner disque + manifeste)

### 6.1 Resume (fix du bug initial)

`CaptureViewModel.enter()` ne reset plus `coinIdx/stepIdx/photoIdx/captured` à 0
(l.96-100) : il **scanne `eval_real/`** (crops présents) + lit les lignes skip du
`manifest.jsonl`, puis reconstruit le curseur.

- Cellule **captured** ssi son `<step>[_p<n>]_crop.jpg` existe (disque = autorité).
- Cellule **skipped** ssi ligne `"event":"skip"` correspondante (et pas de crop).
- Reprise = **première cellule ni captured ni skipped** (ordre protocole :
  `coins × steps × photosPerStep`).
- `captured` = nb de crops comptés. `total` = `CaptureProtocol.totalSnaps`.
- Robuste : restart app, redo (overwrite même path déterministe), pull
  intermédiaire.

### 6.2 Écran dédié read-only `/dev/status`

Route `/dev/status`, ouverte depuis la **bottom-sheet debug** de `ScanScreen`
(long-press → `DebugToolSheet`, entrée `DevTool.STATUS`). Il n'y a pas de hub
`/dev` : tous les écrans dev passent par cette sheet.
**Lecture seule, zéro suppression depuis le téléphone.**

- Résumé global par catégorie : nb fichiers + taille (eval_real / photo_snaps /
  scan_sessions / bench).
- Vue structurée capture cohort : par `<eurioId>` → par `<step>` → statut
  (captured n photos / skipped / pending) + total `X/<total protocole>`
  (total = coins × steps × photos, dérivé du protocole, pas codé en dur).
- Sert d'**outil de vérification du clean** : après `capture:clean`, l'écran doit
  montrer eval_real vide (contre-vérifié par `adb shell ls`).

### 6.3 Extension aux autres catégories (rollout)

Même scanner, dump générique « arbre + compte + taille » pour photo/scan/bench.
Capture cohort = vue structurée ; les autres = dump plat. → chunk B.

---

## 7. Plan d'implémentation (chunks)

Capture cohort de bout en bout **d'abord**, testée, **avant** de généraliser
(cf. feedback `chunk_audit_flow`).

### Chunk A — Capture cohort end-to-end ✅ LIVRÉ (2026-05-29)
1. **Resume** : `CaptureViewModel.enter()` reconstruit le curseur via
   `CaptureDiskReader` (scan `eval_real/` + lignes skip du `manifest.jsonl`) au
   lieu du reset à 0. Cœur pur testable = `CaptureProgressScanner` (9 tests JVM).
2. **Manifeste skips** : `onSkipCell` ajoute une ligne `"event":"skip"` au
   `manifest.jsonl` existant. Nommage des chemins single-sourcé dans `CapturePaths`
   (writer `CoinAnalyzer` + reader partagent la même source).
3. **Écran `/dev/status`** : `DebugStatusScreen`, vue structurée par coin/step
   (read-only, dump monospace), accessible via `DevTool.STATUS` dans la sheet debug.
4. **Tasks** : `capture:pull` + `capture:clean` (sur `eval_real/`), echo de fin.
   `pull-debug`/`clean-debug` globales conservées.

Fichiers : `ml/CapturePaths.kt`, `features/dev/capture/CaptureProgressScanner.kt`,
`features/dev/capture/CaptureDiskReader.kt`, `features/dev/status/DebugStatusScreen.kt`
(+ édits `CaptureViewModel.kt`, `CoinAnalyzer.kt`, `EurioDestinations.kt`,
`DebugBar.kt`, `EurioNavHost.kt`, `app-android/Taskfile.yml`) ;
test `CaptureProgressScannerTest.kt`.

### Chunk A — Test de validation (GATE avant rollout)
- Capturer une cohort (+ au moins 1 skip) sur device.
- Vérifier on-device via `/dev/status` (compteurs + skip corrects).
- `go-task -t app-android/Taskfile.yml capture:pull` → vérifier
  `debug_pull/eval_real/<ts>/`.
- `capture:clean` → vérifier device **vide** via (a) `/dev/status` ET
  (b) `adb shell ls …/eval_real`.
- ✅ Si OK → rollout.

### Chunk B — Rollout au reste ✅ LIVRÉ (2026-05-29)
- ✅ Renommé `snaps/` → `photo_snaps/`, `session_<ts>/` (à plat) →
  `scan_sessions/session_<ts>/`. Noms single-sourcés dans `CapturePaths`
  (`PHOTO_SNAPS_DIR`, `SCAN_SESSIONS_DIR`) ; writers `CoinAnalyzer.kt` /
  `ScanViewModel.kt` patchés. Aucune ref Python/ML à ces dossiers (vérifié grep),
  zéro régression pipeline.
- ✅ Tasks `photo:pull`/`photo:clean`, `scan:pull`/`scan:clean`, `bench:clean`
  (mêmes echos de fin que `capture:`). **Rapatriement bench** : `bench:pull`
  existait déjà (→ `ml/bench/sessions/<device>/`), conservé tel quel ; seul
  `bench:clean` manquait. Pas de re-routage.
- ✅ `/dev/status` étendu : `DebugCategoryReader` (scan générique read-only,
  count + taille + arbre plat, cap 30 lignes) → section « Catégories éphémères »
  pour `photo_snaps` / `scan_sessions` / `bench`. Bench passé via `benchRootDir`
  (autre racine `getExternalFilesDir(null)/bench/`) câblé dans `EurioNavHost`.
- ✅ **Cohort live-tests** (`com.musubi.eurio.cohorttest`) : **documenté comme
  flux distinct, hors taxonomie `eurio_debug`**. Raison : package + racine
  séparés, déjà servi par sa propre task `cohort-test:pull-tests` (→
  `ml/state/live_test_logs/`) couplée à un POST `/lab/.../live-tests/sync`. Le
  fusionner dans `/dev/status` ou les tasks `*:pull` mélangerait deux apps ;
  on le laisse autonome (cf. §1.1, ligne live-tests).
- ✅ MAJ `docs/cohort-capture-ablation.md` (commandes par catégorie + resume).

Fichiers : `features/dev/status/DebugCategoryReader.kt` (+ édits `CapturePaths.kt`,
`CoinAnalyzer.kt`, `ScanViewModel.kt`, `DebugStatusScreen.kt`, `EurioNavHost.kt`,
`app-android/Taskfile.yml`).

### Chunk B — Test de validation (GATE device)
- Renommage : faire 1 photo snap (`/dev/photo`) + 1 record scan → vérifier
  `photo_snaps/snap_<ts>/` et `scan_sessions/session_<ts>/` sur device
  (`adb shell ls …/eurio_debug`).
- `/dev/status` : section « Catégories éphémères » montre les bons compteurs +
  tailles (eval_real reste en vue structurée).
- `photo:pull` / `scan:pull` → vérifier `debug_pull/<ts>/{photo_snaps,scan_sessions}/`.
- `photo:clean` / `scan:clean` / `bench:clean` → device vide pour la catégorie
  (contre-vérifié `/dev/status` + `adb shell ls`).

---

## 8. Liens

- Tracker capture : `docs/cohort-capture-ablation.md`
- Flow admin cohort : `docs/admin/cohort-capture-flow/{README,design}.md`
- Code : `CaptureViewModel.kt`, `CaptureProtocol.kt`, `CoinAnalyzer.kt`,
  `ScanViewModel.kt`, `BenchRecorder.kt`, `app-android/Taskfile.yml`
- Adaptateur ML (inchangé) : `ml/scan/sync_eval_real.py`, `ml/scripts/sweep_ablation.py`
- Memory : `project_cohort_capture_flow`, `project_crop_format_ablation`,
  `project_scan_screen_refacto`
