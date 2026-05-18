# Kickoff — Chunk 5 : ImageCapture full-res + archive Room/filesystem

> Brief auto-suffisant pour reprendre chunk 5 dans une session neuve.
> La spec complète vit dans `chunk-5-imagecapture-archive.md` (~930
> lignes) — ce kickoff la résume et propose un découpage exécutable.

## Pré-lecture obligatoire

1. [`vision.md`](./vision.md) — §1 (scénario), §6 (anti-objectifs), P1
   (reconnaissance/archivage découplés), P8 (sync future).
2. [`decisions.md`](./decisions.md) — **D13** (archive auto sur
   consensus), **D14** (declared_count UI seulement), **D15** (JPEG
   2048 / 92), **D16** (vault/<uuid>.jpg), **D17** (snackbar promote
   opt-in), **D23** (migration v2→v3 vault_entries), **D24** (archive
   ≠ possession), **D25** (cohabitation photoMode debug).
3. [`chunk-5-imagecapture-archive.md`](./chunk-5-imagecapture-archive.md)
   — la spec complète. À lire en entier avant d'attaquer.
4. Mémoires : `feedback_no_debt`, `feedback_chunk_audit_flow`.
5. `CLAUDE.md` §R0 (pas de dette).

## État du code au démarrage

**Chunks 1-4 livrés.** Concrètement :

- `CameraLockController` (chunk-4) drive AE/AF/AWB. `LockState`
  observable depuis `ScanViewModel.lockState: StateFlow<LockState>`.
- `ScanScreen.CameraPreview` bind aujourd'hui `Preview + ImageAnalysis`
  via `provider.bindToLifecycle(...)`. Pas encore `ImageCapture`.
- Room v2 : `EurioDatabase` (`data/local/EurioDatabase.kt`) avec
  entité unique `VaultEntryEntity` qui joue le double rôle (journal +
  possession via `source`). `VaultDao` minimal, `VaultRepository`
  expose `containsCoin / addCoin / …`.
- `ConsensusBuffer` (dans `ScanViewModel`) émet sur consensus
  ArcFace. Pas exposé en StateFlow aujourd'hui — `emitAccepted` est
  appelée directement.
- Pas de `kotlinx-serialization` côté Android (seulement Ktor JSON via
  `kotlinx-serialization-json:1.7.3` côté ktor-client, à vérifier que
  c'est utilisable pour notre `CaptureMetadata`).

## Périmètre du chunk 5

Voir spec complète. Cinq blocs intriqués :

1. **Persistance** : 2 nouvelles entités Room + DAO refondu +
   migration v2→v3 (D23) qui backfille `coin_in_vault` depuis
   `vault_entries` et drop l'ancienne table.
2. **JPEG pipeline** : `JpegPipeline.process(imageProxy, rotation,
   longSide=2048, q=92)` + `ExifStripper` (garde-fou) +
   `VaultFilesystemWriter` (atomic tmp+rename).
3. **Capture wiring** : binder `ImageCapture` UseCase en plus de
   Preview + ImageAnalysis. Try/catch → fallback YUV si combo
   non-supportée. `LockState.Locked` déclenche `takePicture`.
4. **Coordination archive/possession (D24)** :
   `PendingArchiveBuffer` retient le JPEG en attendant le consensus
   (timeout 3 s) ; `VaultCaptureRepository.archive(...)` écrit
   `coin_captures` + fichier ; `confirmPossession(...)` upsert
   `coin_in_vault` sur tap "Ajouter au coffre". **Archive ne touche
   jamais `coin_in_vault`** (D24).
5. **Snackbar promote primary** (D17) : si capture meilleure que la
   primary actuelle d'une pièce **déjà possédée**, snackbar
   "Belle prise · en faire la photo de référence ?" avec action
   "Annuler" (revert primary).

## Découpage proposé

Suggestion : **4 sous-chunks** auditables séparément.

### Chunk 5a — Persistance Room v2→v3

Backend pur, testable en JVM/instrumented sans toucher à la caméra.

- Entités `CoinInVaultEntity`, `CoinCaptureEntity`.
- `CaptureMetadata` data class @Serializable (vérifier que
  kotlinx-serialization est utilisable côté app ; sinon l'ajouter).
- `VaultDao` refondu (lecture/écriture atomique, `promotePrimary`
  transactionnel, **pas** de helper "insertCaptureAndUpsertVault" —
  D24).
- `Migration_2_3` : `CREATE TABLE` × 2, backfill `coin_in_vault` depuis
  `vault_entries` (préserve `declaredCount`), `DROP vault_entries`.
- `EurioDatabase` passe à `version = 3`, ajoute `MIGRATION_2_3`.
- Schema export v3 JSON (`app-android/schemas/`).
- `VaultRepository` adapté pour utiliser les nouvelles tables (refactor
  in-place — `addCoin` devient `confirmPossession`, `containsCoin` lit
  `coin_in_vault`).
- Tests JVM `VaultDaoTest` (Room in-memory). Test instrumented
  `VaultMigrationTest` (DB v2 peuplée → migration → assertions).

**Pas d'audit visuel** côté UI — vérifié via tests.

### Chunk 5b — JPEG pipeline + filesystem writer

Backend pur encore. Faisable en parallèle de 5a, mais probablement
plus simple à séquencer après (les tests veulent une DB en place pour
écrire end-to-end).

- `ml/image/JpegPipeline.kt` (process imageProxy + fromBitmap fallback).
- `ml/image/ExifStripper.kt` (garde-fou pour ByteArray bruts).
- `data/vault/VaultFilesystemWriter.kt` (atomic write, cleanupOrphans).
- Tests JVM (Bitmap via Robolectric ou skip décoder + scaler).
- Test instrumented sur device : rotation 90°, resize 1024→1024, EXIF
  GPS absent post-pipeline.

**Pas d'audit visuel** non plus — pure plomberie.

### Chunk 5c — ImageCapture wiring + PendingArchiveBuffer + Repository

Le cœur intégrateur. **Nécessite chunks 5a + 5b livrés.**

- `ImageCapture` UseCase binder dans `CameraPreview` avec try/catch
  → fallback YUV signalé via `viewModel.markFallbackYuv(...)`.
- `PendingArchiveBuffer` (mutex, expiration 3 s).
- `VaultCaptureRepository` (archive / confirmPossession /
  revertPrimary, D24 strict).
- `ConsensusBuffer` exposé en `StateFlow<ConsensusState>` côté VM
  pour alimenter `PendingArchiveBuffer`.
- `ScanViewModel` : sur `LockState.Locked` → `takePicture` →
  `JpegPipeline.process` → `PendingArchiveBuffer.set(...)`. Sur
  `onAddToVault` → `confirmPossession(...)` au lieu de l'ancien path.
- Adapter `emitAccepted` pour ne plus créer la possession en auto
  (cohérent avec D24 — la possession passe par le tap user).
- Tests JVM `VaultCaptureRepositoryTest`, `PendingArchiveBufferTest`.

**Audit visuel** : scan reconnu → fichier JPEG dans
`/data/data/com.musubi.eurio/files/vault/`, row `coin_captures`,
**pas** de row `coin_in_vault` tant que tu n'as pas tapé "Ajouter au
coffre". Vérifier via `adb pull` + sqlite-shell.

### Chunk 5d — Snackbar promote primary + fallback YUV smoke

Polish + dernière couverture.

- `SnackbarController` (probable réutilisation du
  `SnackbarHostState` déjà dans le `Scaffold`).
- Snackbar opt-in D17 sur promotion par qualité, action "Annuler"
  → `revertPrimary`.
- Smoke test fallback YUV : forcer le path via flag debug, vérifier
  que l'archive contient bien `CaptureMetadata.sourceMode =
  YUV_PREVIEW_FALLBACK`.
- Audit visuel : re-scan d'une pièce déjà possédée avec meilleur
  score → snackbar apparaît, tap "Annuler" remet l'ancienne primary.

## Gotchas / points d'attention

1. **kotlinx-serialization** : la spec suppose `@Serializable` sur
   `CaptureMetadata`. Vérifier que le plugin Kotlin Serialization est
   appliqué côté app-android (probablement absent — il faut
   `id("plugin.serialization") version "..."` dans `build.gradle.kts`).
   Alternative légère : sérialiser à la main en JSONObject Android
   (10× plus simple, suffisant pour < 4 KB metadata).

2. **D24 strict** : *aucune* méthode ne doit créer une row
   `coin_in_vault` en effet de bord d'une archive. Si tu vois
   `dao.insertCaptureAndUpsertVault` se faufiler, c'est un bug. Le
   `archive()` ne touche `coin_in_vault` que pour promote la primary
   si la pièce est *déjà* possédée.

3. **Migration v2→v3** : pas de
   `fallbackToDestructiveMigration` en release. Le test instrumented
   doit peupler une vraie DB v2 avec ≥ 1 row par eurio_id distinct,
   puis vérifier `declared_count` préservé et `primary_capture_id ==
   NULL`. Sans ça la première vraie release efface les coffres
   utilisateurs — risque sécurité-données majeur.

4. **`bindToLifecycle` avec 3 UseCases** : sur Pixel 9a probablement
   OK, sur entry-level Samsung à valider en bench. Le try/catch
   IllegalArgumentException + `provider.isBound(useCase)` ou le flag
   du catch sont suffisants. **Ne pas** essayer de détecter à l'avance
   via `CameraInfo.querySupportedCombinations` — c'est plus fragile.

5. **`ImageCapture.takePicture(executor, callback)` vs `takePicture(output, executor, callback)`** :
   le premier (in-memory `OnImageCapturedCallback`) suffit, on traite
   le `ImageProxy` JPEG en mémoire puis ferme. Pas besoin du second
   (qui écrit un fichier intermédiaire CameraX-géré).

6. **Anti-objectif §6 vision.md** : si pas de consensus dans 3 s, le
   JPEG est **jeté** (pas de "archive without eurioId pour bench"
   tentation). Le `PendingArchiveBuffer.timeout` matérialise ça.

7. **`feedback_chunk_audit_flow`** : livrer 5a, attendre "go", puis
   5b, etc. **Ne pas** chainer 5a+5b+5c+5d dans une seule session sans
   rétro intermédiaire — la migration Room peut casser silencieusement
   et ne se voir qu'à l'audit visuel post-5c.

8. **Existant `photoMode` + `captureMode` debug** : D25 dit qu'ils
   cohabitent dans des dossiers distincts (`debug_pull/`,
   `eval_real/`) — le nouveau vault va dans `files/vault/`. **Aucune
   migration** depuis ces deux modes vers `coin_captures` — ce sont des
   outils QA, pas du user content.

## Plan de bataille recommandé

1. Lire `chunk-5-imagecapture-archive.md` en entier (~30 min).
2. **Étape 5a** (1 session) : Room + DAO + migration + tests +
   `VaultRepository` refactor. Audit DB via sqlite-shell sur device
   après migration.
3. **Étape 5b** (1 session) : JpegPipeline + filesystem writer +
   tests. Audit via test instrumented seul.
4. **Étape 5c** (1 session, la plus grosse) : ImageCapture +
   PendingArchiveBuffer + VaultCaptureRepository. Audit visuel device
   end-to-end + sqlite-shell.
5. **Étape 5d** (1 session, courte) : snackbar promote + smoke fallback.

Soit ~4-5 sessions de coding focused. Si une session sort plus longue
que prévu, splitter dans le doute — c'est moins cher que de gérer un
bug Room migration en prod plus tard.

## Acceptance criteria globale (extraits spec)

Schema : migration appliquée, schemas/3.json checked in.
Happy path : scan reconnu → fichier `<uuid>.jpg` + row capture,
**pas** de row vault tant que pas de tap.
Re-scan supérieur d'une pièce possédée → primary promote + snackbar.
Fallback YUV : capture archivée avec
`sourceMode = YUV_PREVIEW_FALLBACK`.
EXIF GPS absent post-archive.
App killed pendant write → pas de fichier corrompu.

## Sortie attendue de la session

- Sous-chunk(s) livré(s) + audit(s) visuel(s) passé(s).
- Tests verts.
- État résumé en fin de session pour le prochain kickoff.
