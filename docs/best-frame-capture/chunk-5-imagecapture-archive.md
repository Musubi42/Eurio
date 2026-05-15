# Chunk 5 — ImageCapture full-res + archive Room/filesystem

> Quand le lock est `Locked`, on déclenche `ImageCapture.takePicture`,
> on attend le consensus ArcFace (anti-objectif : pas d'archive pour
> pièces non-reconnues), on strip EXIF, on resize long-side 2048, on
> écrit le JPEG sur disque, on persiste dans Room. Fallback YUV si
> `ImageCapture` + `ImageAnalysis` incompatibles sur le device.
>
> **Deux opérations distinctes** (D24) :
> - `archive(...)` — automatique sur consensus, écrit dans `coin_captures`
> - `confirmPossession(...)` — manuel sur tap « Ajouter au coffre »,
>   upsert `coin_in_vault`

## Pré-requis

- Chunks 1-4 livrés.
- Décision tech à valider en début de chunk : sur Pixel 9a + Samsung
  Galaxy A35 (référence mid-range), le binding simultané des 3
  UseCases (`Preview` + `ImageAnalysis` + `ImageCapture`) fonctionne.
  Si non, on bascule en fallback YUV documenté §Fallback.

## Goal

À la fin du chunk-5 :

1. Au passage `LockState.Locked`, `ImageCapture.takePicture` est
   déclenchée (full-res JPEG du capteur).
2. Le JPEG est rotation-corrigé, redimensionné long-side 2048,
   ré-encodé quality 92, EXIF strippé.
3. Le pipeline attend l'arrivée d'un consensus ArcFace (timeout
   3000 ms). Si consensus → archive. Si pas de consensus dans le
   délai → JPEG jeté.
4. Archive = écriture filesystem `context.filesDir/vault/<uuid>.jpg`
   + insert Room dans `coin_captures`, upsert dans `coin_in_vault`
   (créer si premier scan, replace primary si quality_score
   supérieure).
5. La snackbar opt-in "*Belle prise, en faire la photo de référence ?*"
   s'affiche conditionnellement (D17).
6. Sur device non-compatible 3 UseCases, fallback transparent vers
   re-encodage de la best preview frame YUV en JPEG.

À ce stade, **toujours pas de state machine refondue** (chunk-6).
L'archive se fait en side effect du Fire/Lock, parallèle au flux
fiche. La fiche reste pilotée par le consensus comme aujourd'hui.

## Scope

**Dans le chunk** :

- Room : entités `CoinInVaultEntity` + `CoinCaptureEntity`, DAO,
  Database, migration depuis le schéma actuel.
- Filesystem : writer + dossier `vault/`, naming UUID.
- JPEG pipeline : rotation, resize, ré-encode quality 92, EXIF strip.
- `ImageCapture` UseCase wired dans `ScanScreen`.
- `PendingArchiveBuffer` : retient le JPEG en attendant le consensus.
- Fallback YUV : encoder la best preview frame si `ImageCapture`
  indisponible.
- `VaultCaptureRepository` : façade qui orchestre tout.
- Snackbar "remplacer la primary ?" sur quality_score supérieur.
- Tests : DAO (insert/replace primary), Repository (archive happy
  path + pending expiration + fallback), JpegResizer, ExifStripper.

**Hors chunk** :

- State machine refondue `Capturing → Identifying → Accepted` (chunk-6).
- Replay des captures stockées pour bench (chunk-7).
- Sync Supabase Storage (phase marketplace future, Référentiel V2 phase 4).
- UI fiche coffre qui affiche la primary capture (Phase 2 coffre app).
- `declared_count` UI +/− sur fiche coffre (Phase 2 coffre app).
- Refonte / suppression de `photoMode` + `captureMode` debug (D25 — ils
  cohabitent avec le nouveau vault, dossiers distincts).

## Architecture

```
TriggerEvent.Fire → CameraLockController.lock() → LockState.Locked
                                                       │
                                                       ↓
                                          ImageCapture.takePicture()
                                                       │
                                                       ↓ (200-500ms)
                                                onCaptureSuccess(imageProxy)
                                                       │
                                                       ↓
                                          JpegPipeline.process(
                                              imageProxy,
                                              rotationDegrees = imageInfo.rotationDegrees,
                                              longSideMax = 2048,
                                              quality = 92,
                                          )
                                                       │
                                                       ↓
                                          PendingArchiveBuffer.set(
                                              captureId, jpegBytes, score, metadata,
                                              expiresAtNs = now + 3_000ms,
                                          )
                                                       │
                                                       ↓
                                          (waits for ConsensusBuffer.lockedClass)
                                                       │
                                                       ↓ (or expired → discard)
                                          VaultCaptureRepository.archive(
                                              eurioId = locked,
                                              captureId, jpegBytes, score, metadata,
                                          )
                                                       │
                                          ┌────────────┴────────────┐
                                          ↓                         ↓
                                  VaultFilesystemWriter      VaultDao
                                  .write(filename,            .insertCapture(capture)
                                          stripped)            +.promotePrimary(...)
                                                                  ↑
                                                       (uniquement si déjà
                                                        possédé + promotion;
                                                        sinon archive seule —
                                                        coin_in_vault NON touché,
                                                        cf. D24)
                                                       │
                                          (if promotesByQuality)
                                          SnackbarController.show(
                                              "Belle prise, en faire la photo de référence ?"
                                          )

                                          (Possession via ScanViewModel
                                           .onAddToVault → repository
                                           .confirmPossession — chemin séparé)
```

### Fallback YUV path

```
LockState.Locked
        │
        ↓
if (imageCaptureBound) {
    takePicture() → pipeline normal
} else {
    val best = lastBestSelection.frame.crop  // 224×224 BGR uint8 du buffer
    // (note: c'est dégradé, c'est le crop normalisé pas la frame source)
    val sourceBitmap = lastBestSelection.frame.sourceBitmap  // need to expose
    val jpegBytes = JpegPipeline.fromBitmap(sourceBitmap, longSideMax = 2048, quality = 92)
    // … strip EXIF, archive same as above
}
```

Pour le fallback à pleine qualité du fallback, on doit garder dans
`BufferedFrame` non seulement le `crop` 224 mais aussi une référence
au `Bitmap` source full-res. Coût mémoire : 1080×1920×4 bytes ≈ 8 MB
par frame × 5 = 40 MB en RAM. **Trop**. Donc en fallback YUV :
- soit on garde un seul Bitmap source pointé par `lastBestFrameIndex`
  (mis à jour à chaque push de buffer) → 8 MB constant, OK
- soit on perd la fidélité full-res et on archive le crop 224
  upscalé (mauvaise idée, perte qualité énorme)

Mon vote (acté dans ce chunk) : garder **uniquement** le Bitmap source
de la dernière `BufferedFrame` poussée, avec une SoftReference. Coût
RAM borné, pas de fuite, et le fallback YUV reste pratique.

## Migration depuis `vault_entries` (D23)

L'app actuelle utilise une seule table `vault_entries`
(`VaultEntryEntity.kt`, schéma Room v2) qui joue deux rôles à la fois :
journal de scan ET marqueur de possession (via `source = SCAN |
MANUAL_ADD`). Migration `v2 → v3` :

1. **Création** des deux nouvelles tables (`coin_in_vault`,
   `coin_captures`) via `CREATE TABLE`.
2. **Backfill** `coin_in_vault` pour chaque `coin_eurio_id` distinct
   de `vault_entries` :
   ```sql
   INSERT INTO coin_in_vault (eurioId, firstCapturedAt,
                              primaryCaptureId, declaredCount, notes)
   SELECT
       coin_eurio_id            AS eurioId,
       MIN(scanned_at)          AS firstCapturedAt,
       NULL                     AS primaryCaptureId,   -- aucun JPEG historique
       COUNT(*)                 AS declaredCount,      -- préserve scans répétés
       NULL                     AS notes
   FROM vault_entries
   GROUP BY coin_eurio_id;
   ```
3. **Pas de `coin_captures` rétroactives** — on n'a pas les images
   originelles. `primaryCaptureId` reste `NULL` jusqu'au premier scan
   post-migration. La fiche coffre v1 doit gérer ce cas en fallback
   sur l'image canonique Numista (`coins.image_obverse_url`).
4. **DROP** `vault_entries` en fin de migration.
5. `EurioDatabase.kt` passe à `version = 3` avec `MIGRATION_2_3`
   ajoutée à `addMigrations(...)`. **Pas** de
   `fallbackToDestructiveMigration` en release (la branche debug-only
   reste comme aujourd'hui).

Conséquences schéma chunk-5 :

- `CoinInVaultEntity.primaryCaptureId: String?` (nullable au lieu de
  non-null comme initialement esquissé).
- `VaultCaptureRepository.archive(...)` doit gérer le cas
  `existingVault.primaryCaptureId == null` → la première vraie capture
  remplit le slot (acte implicite de promote-primary, sans snackbar).

Test instrumented dédié : `VaultMigrationTest.kt` avec une base v2
peuplée → migration → assertions sur les counts + nullabilité.

## Possession (`coin_in_vault`) vs Archive (`coin_captures`) — D24

Deux opérations distinctes, jamais fusionnées :

- **Archive** (`coin_captures` insert) — automatique dès qu'un
  consensus ArcFace + `PendingArchive` sont alignés, indépendamment de
  l'action user (P1 vision.md). Toute capture acceptée laisse une
  trace dans le journal, **même si** l'utilisateur dismiss la card
  sans taper « Ajouter au coffre ». Permet le pattern « j'identifie
  juste cette pièce en passant » sans perdre la frame pour autant.

- **Possession** (`coin_in_vault` upsert) — déclenchée **uniquement**
  par `ScanViewModel.onAddToVault()` (tap explicite sur
  `ScanAcceptedCard`, cohérent avec décision #7 phase-1 app). À ce
  moment-là, `VaultCaptureRepository.confirmPossession(eurioId,
  captureId)` :
  - Si pas de `coin_in_vault` : crée la row, set
    `primaryCaptureId = captureId`.
  - Si déjà possédée : `declaredCount` inchangé (P4 + D14), pas de
    promotion auto — la promotion primary passe par le snackbar D17 ou
    par auto-fill du `primaryCaptureId == null` post-migration.

Le snackbar D17 « Belle prise · en faire la photo de référence ? »
fire uniquement sur archive d'une `coin_captures` **dont l'`eurioId`
est déjà possédé** ET dont le `qualityScore` dépasse celui de la
primary actuelle. Sur premier scan jamais possédé, pas de snackbar —
c'est `ScanAcceptedCard` qui pilote l'UX.

**Conséquence** : `coin_captures` peut contenir des rows orphelines
(pas de `coin_in_vault` associé). C'est voulu (cf. D24 rationale).
Aucun cleanup automatique en v1 ; module séparé futur si besoin.

## Fichiers à créer

### Persistance Room

| Fichier | Rôle |
|---|---|
| `data/vault/CoinInVaultEntity.kt` | @Entity 1 row par eurio_id (`primaryCaptureId` nullable, D23) |
| `data/vault/CoinCaptureEntity.kt` | @Entity N rows journal |
| `data/vault/VaultDao.kt` | DAO avec ops idempotentes (`insertCapture` seul + `confirmPossession` transaction) |
| `data/local/migrations/Migration_2_3.kt` | Migration `vault_entries` → `coin_in_vault` + `coin_captures` (D23) |
| `data/vault/CaptureMetadata.kt` | data class sérialisable en JSON (kotlinx.serialization) |

Note : on ajoute les entités au `EurioDatabase` existant
(`data/local/EurioDatabase.kt`) — pas de DB séparée. La ligne
`@Database(entities = [...])` accueille `CoinInVaultEntity` et
`CoinCaptureEntity` à côté des entités actuelles. `VaultEntryEntity`
est **retiré** de la liste (cohérent avec le DROP §Migration).

### Filesystem + JPEG

| Fichier | Rôle |
|---|---|
| `data/vault/VaultFilesystemWriter.kt` | Écrit `context.filesDir/vault/<uuid>.jpg` atomic via tmp + rename |
| `ml/image/JpegPipeline.kt` | Rotation + resize + ré-encode quality 92 |
| `ml/image/ExifStripper.kt` | Supprime tous tags EXIF avant écriture finale |

### Capture & coordination

| Fichier | Rôle |
|---|---|
| `ml/capture/PendingArchiveBuffer.kt` | Retient un JPEG + métadata en attente du consensus, timeout 3s |
| `data/vault/VaultCaptureRepository.kt` | Façade : archive() / replacePrimary() / cleanupOrphans() |
| `features/scan/SnackbarController.kt` | Émet les snackbars "remplacer primary ?" depuis le ViewModel |

### Tests

| Fichier | Rôle |
|---|---|
| `data/vault/VaultDaoTest.kt` | Tests insert + idempotence + replace primary |
| `data/vault/VaultCaptureRepositoryTest.kt` | Tests archive happy / first capture / replace primary / orphan |
| `ml/image/JpegPipelineTest.kt` | Resize correct, rotation correcte, quality 92 |
| `ml/image/ExifStripperTest.kt` | Tags geo/sensor/timestamp absents post-strip |
| `ml/capture/PendingArchiveBufferTest.kt` | Set → onConsensus = archive ; Set → expired = discard |

## Fichiers à modifier

| Fichier | Modification |
|---|---|
| `features/scan/ScanScreen.kt` | Binder `imageCaptureUseCase` (avec try/catch pour fallback YUV) |
| `features/scan/ScanViewModel.kt` | Exposer `vaultRepository` ; observer `consensusState` pour `PendingArchiveBuffer.onConsensus()` ; relayer snackbar |
| `ml/CoinAnalyzer.kt` | Garder référence au Bitmap source de la dernière `BufferedFrame` (SoftReference) pour le fallback YUV |
| `ml/trigger/BufferedFrame.kt` | Ajouter `sourceBitmap: SoftReference<Bitmap>?` |
| `app/build.gradle.kts` | Bump Room version si nécessaire ; ajouter `kotlinx-serialization-json` |

## Room schémas

### `CoinInVaultEntity`

```kotlin
@Entity(
    tableName = "coin_in_vault",
    foreignKeys = [ForeignKey(
        entity = CoinCaptureEntity::class,
        parentColumns = ["captureId"],
        childColumns = ["primaryCaptureId"],
        onDelete = ForeignKey.NO_ACTION,  // FK pure documentaire
    )],
    indices = [Index("primaryCaptureId")],
)
data class CoinInVaultEntity(
    @PrimaryKey val eurioId: String,
    val firstCapturedAt: Long,                  // ms epoch
    val primaryCaptureId: String?,              // FK coin_captures.captureId — nullable post-migration v2→v3 (D23) et pour manual_add futur
    val declaredCount: Int = 1,
    val notes: String? = null,
    // sync placeholders pour la phase marketplace future (Référentiel V2 phase 4), nullable
    val uploadedAt: Long? = null,
    val remoteVaultId: String? = null,
)
```

### `CoinCaptureEntity`

```kotlin
@Entity(
    tableName = "coin_captures",
    indices = [
        Index("eurioId"),
        Index(value = ["eurioId", "isPrimary"]),
    ],
)
data class CoinCaptureEntity(
    @PrimaryKey val captureId: String,          // uuid v4
    val eurioId: String,                        // FK coin_in_vault.eurioId
    val capturedAt: Long,                       // ms epoch
    val imageFilename: String,                  // <uuid>.jpg
    val qualityScore: Float,                    // FrameScore.aggregate
    val isPrimary: Boolean,
    val captureMetadataJson: String,            // JSON-serialized CaptureMetadata
    val uploadedAt: Long? = null,               // sync placeholder (phase marketplace future, P8)
    val lowQualityFlag: Boolean = false,        // si BEST_AGGREGATE_FALLBACK
)
```

### `CaptureMetadata`

```kotlin
@Serializable
data class CaptureMetadata(
    val frameScore: FrameScoreSnapshot,         // sub-scores + raw values
    val detection: DetectionSnapshot,           // bbox, method (yolo/hough), conf
    val triggerMode: String,                    // name de la TriggerStrategy
    val triggerParams: TriggerParamsSnapshot,   // IoU, N, conf seuils effectifs
    val lockResult: LockResultSnapshot?,        // durée, AF converged, AE/AWB
    val arcfaceTop3: List<ArcfaceMatchSnapshot>,
    val sourceMode: SourceMode,                 // IMAGE_CAPTURE_FULL ou YUV_PREVIEW_FALLBACK
    val pipelineTimingsMs: TimingBreakdown,
    val deviceModel: String,                    // Build.MODEL pour bench cross-device
    val androidApi: Int,
    val schemaVersion: Int = 1,
)
```

Toute info qui pourrait servir au replay/bench (chunk-7) est dans ce
JSON. Ne le minifie pas — le fichier sera petit (< 4 KB par capture).

## DAO contract

Opérations atomiques bas-niveau. La logique « archive vs possession »
vit dans `VaultCaptureRepository` (D24), **pas** dans le DAO.

```kotlin
@Dao
abstract class VaultDao {

    @Query("SELECT * FROM coin_in_vault WHERE eurioId = :eurioId")
    abstract suspend fun getVault(eurioId: String): CoinInVaultEntity?

    @Query("SELECT * FROM coin_captures WHERE captureId = :captureId")
    abstract suspend fun getCapture(captureId: String): CoinCaptureEntity?

    @Query("""
        SELECT * FROM coin_captures
        WHERE eurioId = :eurioId AND isPrimary = 1 LIMIT 1
    """)
    abstract suspend fun getPrimaryCapture(eurioId: String): CoinCaptureEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    abstract suspend fun insertCapture(capture: CoinCaptureEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun upsertVault(vault: CoinInVaultEntity)

    @Query("""
        UPDATE coin_captures
        SET isPrimary = (captureId = :newPrimaryId)
        WHERE eurioId = :eurioId
    """)
    abstract suspend fun setPrimary(eurioId: String, newPrimaryId: String)

    /**
     * Swap primary atomique : flip is_primary sur le bon row + update
     * du pointer dans coin_in_vault. Appelée par
     * VaultCaptureRepository.archive() quand une nouvelle capture
     * doit promote.
     *
     * Pré-requis : `coin_in_vault[eurioId]` existe. Si appelée sans
     * vault existant, lève — c'est un bug du repository.
     */
    @Transaction
    open suspend fun promotePrimary(eurioId: String, newPrimaryId: String) {
        val existing = getVault(eurioId)
            ?: error("promotePrimary called on non-possessed eurioId=$eurioId — repository bug")
        setPrimary(eurioId, newPrimaryId)
        upsertVault(existing.copy(primaryCaptureId = newPrimaryId))
    }
}
```

Note l'absence de `insertCaptureAndUpsertVault` : la version précédente
de ce chunk créait `coin_in_vault` implicitement à chaque archive — D24
acte le contraire (séparation stricte). Ne pas re-introduire ce
helper, même si « ça simplifie » en apparence.

## VaultCaptureRepository

Refactorisé pour refléter D24 (archive ≠ possession) : deux APIs
distinctes, le `archive` ne touche jamais `coin_in_vault`.

```kotlin
class VaultCaptureRepository(
    private val dao: VaultDao,
    private val filesystem: VaultFilesystemWriter,
    private val snackbar: SnackbarController,
) {
    /**
     * Archive automatique d'une capture acceptée. Crée la row coin_captures
     * et le fichier JPEG. **Ne touche jamais coin_in_vault.** Appelée par
     * PendingArchiveBuffer dès qu'un consensus ArcFace + un JPEG sont
     * alignés, indépendamment du tap user (cf. P1 vision.md + D24).
     */
    suspend fun archive(
        eurioId: String,
        captureId: String,
        jpegBytes: ByteArray,
        score: FrameScore,
        metadata: CaptureMetadata,
    ): ArchiveResult {
        val filename = "$captureId.jpg"

        // 1. Write file first (so DB never references a missing file).
        filesystem.write(filename, jpegBytes)

        // 2. Promotion logic — only relevant if eurioId is already possessed.
        val existingVault = dao.getVault(eurioId)
        val existingPrimary = existingVault?.primaryCaptureId
            ?.let { dao.getCapture(it) }

        // Auto-fill primary if vault exists but primary is NULL (case post
        // D23 migration: declared_count préservé mais aucun JPEG historique).
        val autoFillEmptyPrimary = existingVault != null && existingPrimary == null

        // Promotion classique : meilleur score qu'avant.
        val promotesByQuality = existingPrimary != null
            && score.aggregate > existingPrimary.qualityScore

        val shouldBePrimary = autoFillEmptyPrimary || promotesByQuality

        // 3. Insert capture.
        val capture = CoinCaptureEntity(
            captureId = captureId,
            eurioId = eurioId,
            capturedAt = System.currentTimeMillis(),
            imageFilename = filename,
            qualityScore = score.aggregate,
            isPrimary = shouldBePrimary,
            captureMetadataJson = Json.encodeToString(metadata),
            lowQualityFlag = metadata.frameScore.passes.all.not(),
        )
        dao.insertCapture(capture)

        // 4. Si on doit promote, faire le swap atomique + update du pointer
        // dans coin_in_vault. Cohérent avec D24 : promote ne crée jamais
        // coin_in_vault — il ne touche que si déjà possédé.
        if (shouldBePrimary && existingVault != null) {
            dao.promotePrimary(eurioId, captureId)
        }

        // 5. Snackbar opt-in D17 : uniquement sur promotion par qualité,
        // jamais sur auto-fill ni sur premier scan. Auto-fill = silencieux
        // (l'utilisateur ne sait pas qu'il manquait une primary). Premier
        // scan non-possédé = pas de snackbar (l'AcceptedCard gère l'UX).
        if (promotesByQuality) {
            snackbar.show(
                message = "Belle prise · en faire la photo de référence ?",
                action = SnackbarAction.RevertPrimary(
                    eurioId, previousPrimaryId = existingPrimary!!.captureId
                ),
            )
        }

        return ArchiveResult.Success(
            captureId = captureId,
            isPossessed = existingVault != null,
            promoted = shouldBePrimary,
        )
    }

    /**
     * Acte de possession explicite — tap « Ajouter au coffre » sur
     * ScanAcceptedCard. Crée coin_in_vault si pas encore existant, set la
     * capture courante comme primary. No-op si déjà possédée (declaredCount
     * inchangé per D14 — l'incrément manuel passera par la fiche coffre).
     *
     * Le captureId est celui que archive() vient d'écrire (peut être null
     * dans le cas dégradé où l'archive a échoué — fallback YUV ou timeout).
     * On accepte un captureId null : le coffre est créé sans photo de
     * référence (rendu fiche fallback Numista).
     */
    suspend fun confirmPossession(eurioId: String, captureId: String?) {
        val existing = dao.getVault(eurioId)
        if (existing != null) return  // déjà possédé, no-op (D14)

        dao.upsertVault(CoinInVaultEntity(
            eurioId = eurioId,
            firstCapturedAt = System.currentTimeMillis(),
            primaryCaptureId = captureId,
            declaredCount = 1,
        ))
        if (captureId != null) {
            dao.setPrimary(eurioId, captureId)
        }
    }

    /**
     * Annulation du snackbar D17 — restaure l'ancienne primary. Pas de
     * « annuler la promotion » destructif : on ne supprime pas la capture
     * récente, on remet juste le pointer.
     */
    suspend fun revertPrimary(eurioId: String, previousPrimaryId: String) {
        dao.setPrimary(eurioId, previousPrimaryId)
        val vault = dao.getVault(eurioId) ?: return
        dao.upsertVault(vault.copy(primaryCaptureId = previousPrimaryId))
    }
}

sealed class ArchiveResult {
    data class Success(
        val captureId: String,
        val isPossessed: Boolean,
        val promoted: Boolean,
    ) : ArchiveResult()
    data class Error(val cause: String) : ArchiveResult()
}

sealed class SnackbarAction {
    data class RevertPrimary(val eurioId: String, val previousPrimaryId: String) : SnackbarAction()
}
```

**Lecture du flow** :

1. Consensus reached → `archive()` écrit `coin_captures` + JPEG. Si la
   pièce est déjà possédée et la nouvelle capture est meilleure, promote
   primary + snackbar « Belle prise ».
2. Si user tap « Ajouter au coffre » sur l'AcceptedCard →
   `confirmPossession()` crée `coin_in_vault` avec la capture récente
   comme primary. Pas de snackbar (l'AcceptedCard *est* la confirmation
   UI).
3. Si user dismiss → `coin_captures` reste orpheline, c'est OK (D24).

**Conséquence chunk-6** : le reducer `ScanReducer.reduceFromAccepted(...)`
doit, sur `UserConfirmAdd`, déclencher un `SideEffect.ConfirmPossession`
qui appelle `repository.confirmPossession(...)`. À documenter là-bas.

## PendingArchiveBuffer

```kotlin
class PendingArchiveBuffer(
    private val consensusFlow: StateFlow<ConsensusState>,
    private val repository: VaultCaptureRepository,
    private val scope: CoroutineScope,
    private val timeoutMs: Long = 3_000L,
) {
    private val mutex = Mutex()
    private var pending: PendingArchive? = null

    suspend fun set(
        captureId: String,
        jpegBytes: ByteArray,
        score: FrameScore,
        metadata: CaptureMetadata,
    ) = mutex.withLock {
        // Discard any previously pending (newer takes precedence).
        pending = PendingArchive(
            captureId, jpegBytes, score, metadata,
            expiresAtNs = SystemClock.elapsedRealtimeNanos() + timeoutMs * 1_000_000L,
        )
    }

    init {
        scope.launch {
            consensusFlow.collect { state ->
                val locked = state.lockedClass ?: return@collect
                val p = mutex.withLock { pending?.also { pending = null } } ?: return@collect
                repository.archive(
                    eurioId = locked,
                    captureId = p.captureId,
                    jpegBytes = p.jpegBytes,
                    score = p.score,
                    metadata = p.metadata,
                )
            }
        }
        // Timeout sweeper.
        scope.launch {
            while (isActive) {
                delay(500)
                mutex.withLock {
                    val p = pending ?: return@withLock
                    if (SystemClock.elapsedRealtimeNanos() > p.expiresAtNs) {
                        pending = null
                        // Log: archive discarded due to timeout. JPEG bytes GC'd.
                    }
                }
            }
        }
    }
}

private data class PendingArchive(
    val captureId: String,
    val jpegBytes: ByteArray,
    val score: FrameScore,
    val metadata: CaptureMetadata,
    val expiresAtNs: Long,
)
```

Le timeout 3 s couvre largement le temps entre lock acquired et
consensus (typiquement < 1.5 s). Si pas de consensus dans le délai,
on assume que ArcFace ne match rien → on ne stocke pas la frame
(anti-objectif §6).

## JpegPipeline

```kotlin
object JpegPipeline {
    fun process(
        imageProxy: ImageProxy,
        rotationDegrees: Int,
        longSideMax: Int = 2048,
        quality: Int = 92,
    ): ByteArray {
        require(imageProxy.format == ImageFormat.JPEG) { "expected JPEG" }
        val rawBytes = imageProxy.planes[0].buffer.toByteArray()
        val bitmap = BitmapFactory.decodeByteArray(rawBytes, 0, rawBytes.size)
            ?: error("decode failed")

        val rotated = if (rotationDegrees != 0) {
            Bitmap.createBitmap(
                bitmap, 0, 0, bitmap.width, bitmap.height,
                Matrix().apply { postRotate(rotationDegrees.toFloat()) },
                true,
            ).also { bitmap.recycle() }
        } else bitmap

        val resized = if (maxOf(rotated.width, rotated.height) > longSideMax) {
            val scale = longSideMax.toFloat() / maxOf(rotated.width, rotated.height)
            Bitmap.createScaledBitmap(
                rotated,
                (rotated.width * scale).roundToInt(),
                (rotated.height * scale).roundToInt(),
                true,
            ).also { rotated.recycle() }
        } else rotated

        val out = ByteArrayOutputStream()
        resized.compress(Bitmap.CompressFormat.JPEG, quality, out)
        resized.recycle()
        return out.toByteArray()
    }

    fun fromBitmap(bitmap: Bitmap, longSideMax: Int = 2048, quality: Int = 92): ByteArray {
        // Same resize + compress logic, used by fallback YUV path.
        // ...
    }
}
```

Note : `BitmapFactory.decodeByteArray` → `compress(JPEG, 92)` est un
double-encode lossy. Acceptable car (a) la perte cumulative est
~1-2% à quality 92 vs source, invisible à l'œil, (b) on a besoin de
recycler le pipeline pour la rotation et le resize.

Alternative : libjpeg-turbo natif pour resize sans décoder
intégralement. Hors scope v1 — la solution Bitmap suffit.

## ExifStripper

```kotlin
object ExifStripper {
    fun strip(jpegBytes: ByteArray): ByteArray {
        // Approach: write to tmp file, open with ExifInterface, remove all
        // sensitive tags, write back. ExifInterface ne supporte pas
        // l'opération sur ByteArray directement (limitation API).
        val tmp = File.createTempFile("exif-strip", ".jpg").apply {
            writeBytes(jpegBytes)
        }
        try {
            val exif = ExifInterface(tmp.absolutePath)
            SENSITIVE_TAGS.forEach { tag ->
                exif.setAttribute(tag, null)
            }
            exif.saveAttributes()
            return tmp.readBytes()
        } finally {
            tmp.delete()
        }
    }

    private val SENSITIVE_TAGS = listOf(
        ExifInterface.TAG_GPS_LATITUDE,
        ExifInterface.TAG_GPS_LONGITUDE,
        ExifInterface.TAG_GPS_ALTITUDE,
        ExifInterface.TAG_GPS_TIMESTAMP,
        ExifInterface.TAG_GPS_DATESTAMP,
        ExifInterface.TAG_DATETIME,
        ExifInterface.TAG_DATETIME_ORIGINAL,
        ExifInterface.TAG_DATETIME_DIGITIZED,
        ExifInterface.TAG_MAKE,
        ExifInterface.TAG_MODEL,
        ExifInterface.TAG_SOFTWARE,
        ExifInterface.TAG_SUBJECT_DISTANCE,
        ExifInterface.TAG_USER_COMMENT,
        ExifInterface.TAG_ARTIST,
        // … liste complète dans le code
    )
}
```

Alternative plus radicale : ré-encoder le Bitmap final sans utiliser
le JPEG d'origine → 0 EXIF. C'est déjà ce que fait `JpegPipeline.process`
qui décode → resize → `Bitmap.compress(JPEG, …)`. Le `compress` ne
copie pas l'EXIF source. **Donc en pratique, `ExifStripper` est redondant
post-`JpegPipeline.process`.**

Conséquence : on **n'appelle pas** `ExifStripper` après `JpegPipeline`
en chemin normal — c'est inutile. On le garde comme garde-fou pour
le path qui passe des `ByteArray` JPEG bruts (ex: imports futurs).

## VaultFilesystemWriter

```kotlin
class VaultFilesystemWriter(private val context: Context) {
    private val vaultDir: File by lazy {
        File(context.filesDir, "vault").apply { mkdirs() }
    }

    suspend fun write(filename: String, bytes: ByteArray) = withContext(Dispatchers.IO) {
        val target = File(vaultDir, filename)
        val tmp = File(vaultDir, "$filename.tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(target)) {
            tmp.delete()
            error("Failed to atomic-rename $filename")
        }
    }

    fun read(filename: String): File = File(vaultDir, filename)

    fun delete(filename: String): Boolean = File(vaultDir, filename).delete()

    suspend fun cleanupOrphans(knownFilenames: Set<String>) = withContext(Dispatchers.IO) {
        vaultDir.listFiles()?.forEach { file ->
            if (file.name !in knownFilenames && !file.name.endsWith(".tmp")) {
                file.delete()
            }
        }
    }
}
```

Tmp + rename = écriture atomique. Pas de fichier corrompu si le
process meurt en plein write.

`cleanupOrphans` sera appelé en startup app (Application.onCreate ou
WorkManager hebdo) pour balayer les fichiers sans row DB. Pas câblé
dans ce chunk — c'est une maintenance Phase 3 du coffre.

## ImageCapture wiring dans ScanScreen

```kotlin
LaunchedEffect(Unit) {
    val provider = ProcessCameraProvider.getInstance(context).await()
    val previewUseCase = Preview.Builder().build().apply {
        setSurfaceProvider(previewView.surfaceProvider)
    }
    val analysisUseCase = ImageAnalysis.Builder()
        .setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)
        .build()
        .apply { setAnalyzer(executor, coinAnalyzer) }

    val captureUseCase = ImageCapture.Builder()
        .setCaptureMode(CAPTURE_MODE_MAXIMIZE_QUALITY)
        .setJpegQuality(95)  // raw quality before our resize
        .build()

    val camera = try {
        provider.bindToLifecycle(
            lifecycleOwner, cameraSelector,
            previewUseCase, analysisUseCase, captureUseCase,
        )
    } catch (e: IllegalArgumentException) {
        // 3-usecase combo not supported → fallback to YUV path.
        scanViewModel.markFallbackYuv(reason = e.message)
        provider.bindToLifecycle(
            lifecycleOwner, cameraSelector,
            previewUseCase, analysisUseCase,
        )
    }

    scanViewModel.attachCamera(
        cameraLockController = CameraLockController(camera),
        imageCapture = if (provider.isBound(captureUseCase)) captureUseCase else null,
    )
}
```

`isBound(captureUseCase)` est exposé par le provider en CameraX
≥ 1.3 ; sinon on tracke via le try/catch.

## Acceptance criteria

**Schema** :
- [ ] Migration Room appliquée, `coin_in_vault` et `coin_captures`
      créées avec leurs indexes.
- [ ] `app-android/schemas/` contient le JSON de la nouvelle version
      (Room schema export).

**Happy path** :
- [ ] Scan une pièce reconnue → file `<uuid>.jpg` apparaît dans
      `context.filesDir/vault/`, row dans `coin_captures`, row dans
      `coin_in_vault`.
- [ ] Re-scan la même pièce avec quality_score inférieur → nouvelle
      capture archivée, `isPrimary = false`, vault `primaryCaptureId`
      inchangé, snackbar **PAS** affiché.
- [ ] Re-scan avec quality_score supérieur → capture `isPrimary =
      true`, vault `primaryCaptureId` updaté, snackbar affiché.
- [ ] Scan une pièce inconnue (ArcFace top1 < 0.20) → aucun fichier
      écrit, aucune row DB.

**Fallback** :
- [ ] Sur device sans support 3 UseCases : capture YUV ré-encodée
      → JPEG résultant ressemble visuellement au preview mais
      compressé. `CaptureMetadata.sourceMode = YUV_PREVIEW_FALLBACK`.

**Timing** :
- [ ] `ImageCapture.takePicture` : 200-500 ms du déclenchement à
      `onCaptureSuccess` sur Pixel 9a.
- [ ] Le flux fiche (chunk-3 consensus) n'est pas bloqué par
      l'archive : la fiche s'affiche dès consensus, l'archive
      arrive ensuite (potentiellement < 1 s plus tard).

**EXIF** :
- [ ] Capture archivée → `ExifInterface(file).getAttribute(TAG_GPS_*)`
      retourne null pour tous les tags GPS et sensor.
- [ ] `Bitmap.compress(JPEG)` ne propage pas l'EXIF source : vérifier
      en test unitaire.

**Robustesse** :
- [ ] App killed pendant write → pas de fichier corrompu (le tmp est
      supprimé ou le rename a pris).
- [ ] `PendingArchiveBuffer` timeout 3 s : si consensus pas atteint,
      le JPEG est GC'd (vérifier via leak detection).
- [ ] Database transaction `promotePrimary` rollback si l'update
      échoue (constraint). Pas de coin_in_vault créé par archive() —
      vérifier qu'un scan accepté + dismiss laisse `coin_captures`
      avec 0 row `coin_in_vault` correspondant (D24).
- [ ] Migration `v2 → v3` (D23) sur DB peuplée : 100 % des
      `coin_eurio_id` migrés, `declared_count` préservé,
      `primary_capture_id == NULL` partout post-migration.

**Tests** :
- [ ] Tous les tests unitaires + DAO + Repository passent.
- [ ] Test instrumented : "scan → archive → relire fichier → contenu
      identique aux bytes archivés".

## Questions ouvertes à trancher pendant l'implem

1. **Promotion primary auto vs opt-in** : acté A (auto), snackbar
   informatif avec undo via `revertPrimary()`. À revoir si user
   feedback dit "trop de prises se promeuvent toutes seules" en bench.
2. **`PendingArchiveBuffer` timeout 3000 ms** : à valider que c'est
   assez long pour les triggers `BoxStability` qui fire avant le
   consensus. Si on observe des archives perdues alors qu'un
   consensus arrive juste après le timeout, on étend à 5 s.
3. **`uploadedAt` placeholder en v1** : on l'ajoute dès maintenant
   pour ne pas avoir à migrer à l'arrivée de la phase marketplace
   future (Référentiel V2 phase 4). Validé — cf. P8 vision.md.
4. **Compression PNG ou JPEG ?** JPEG quality 92. PNG = 3-5× plus
   gros sans gain visuel sur photo (PNG sans-perte n'apporte que
   pour graphismes plats). Acté.
5. **Format orientation EXIF préservé ou rotation appliquée ?**
   Rotation appliquée au Bitmap dans `JpegPipeline` → l'image est
   "physiquement" orientée correctement, pas dépendante d'un tag
   EXIF orientation. Plus compatible cross-viewer. Acté.
6. **Stockage du `metadata` JSON inline (column) vs fichier sidecar ?**
   Inline (`coin_captures.captureMetadataJson` TEXT) — petit (< 4 KB),
   queryable au besoin via SQL JSON funcs. Acté.
7. **Encryption au repos** : non v1. Internal storage Android est
   sandbox per-app, hors root, suffisant pour des photos de pièces
   personnelles. Si jamais sync (phase marketplace future) →
   l'encryption se fait à l'upload Supabase Storage côté server.
8. **Tailles attendues** : ~500 KB par JPEG long-side 2048 quality 92.
   200 coins ≈ 100 MB. À surveiller si user dépasse 1000 coins
   (post-v1).

## Mémoires & règles liées

- D13, D14, D15, D16, D17 implémentés ici fidèlement, complétés par
  D23 (migration), D24 (archive ≠ possession), D25 (cohabitation avec
  photoMode/captureMode debug).
- D3 (display fiche découplé de l'archivage) implémenté via le
  `PendingArchiveBuffer` + flow consensus indépendant.
- Anti-objectif §6 vision.md "Pas de stockage de frames pour pièces
  non-reconnues" → le timeout 3s du PendingArchiveBuffer matérialise
  ça : pas de consensus dans le délai = pas d'archive.
- `feedback_no_debt` — pas de fallback silencieux : si
  `cleanupOrphans` détecte des fichiers sans DB, il les supprime ;
  il ne les "guérit" pas en inventant une row.
- `project_admin_workspace` — l'admin (phase marketplace future) lira
  ces captures via une future API user-side, pas directement via le
  filesystem.
- CLAUDE.md interdictions : pas d'édition `.envrc`, pas de `git add -A`
  pour les fichiers générés.
