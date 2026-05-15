# Décisions actées — best-frame capture

> Décisions architecturales tranchées dans le brainstorm initial (D1-D22)
> et complétées par l'audit cross-ref 2026-05-15 (D23-D25). Source de
> vérité opposable à toute implémentation de chunk.

## Scénario & flow

### D1. Phrase de scénario figée

Voir [`vision.md`](vision.md) §1. Toute évolution du flow doit re-éditer
cette phrase d'abord. Si la phrase ne tient plus en l'état, on revoit
l'architecture, pas l'inverse.

### D2. State machine à 6 états

`Idle → Detecting → Locking → Capturing → Identifying → Accepted`, avec
retour `Detecting` sur abort/timeout. Locking et Capturing pourraient
être fusionnés visuellement mais restent distincts dans le code pour
faciliter le debug (logs, HUD, replay).

**Alternative rejetée** : state machine plate (`Idle → Scanning → Done`).
Trop opaque, impossible à débugger sans logs JSONL fouillis.

### D3. Display fiche découplé de l'archivage

Au passage `Accepted`, la fiche est affichée immédiatement. L'archivage
(ImageCapture + écriture Room/disk) continue en background. Si
l'archivage échoue, la fiche reste, l'erreur est loggée en JSON.

**Rationale** : on évite le ressenti "freeze 3-4 secondes". Cf.
`feedback_scan_ux` (QR-scanner-style).

**Alternative rejetée** : archive synchrone bloquante. Casse l'UX
QR-scanner.

### D4. Rolling buffer pré-trigger N=5

Dès l'entrée en Detecting, ring de 5 frames avec scores qualité maintenu.
Quand le trigger fire, on a déjà 5 frames notées. Permet sélection
rétroactive (la meilleure des 5 dernières) sans re-burst si une frame
passe les seuils absolus.

**Rationale** : économise 1-2 s perçues. Détecter la stabilité ET burster
en série prendrait 3-4 s, ce qui sort du seuil QR-scanner-style.

**Alternative rejetée** : burst séquentiel après trigger. Plus simple à
coder, mais latence inacceptable.

## Trigger best-frame

### D5. Trois stratégies implémentées en parallèle

`BoxStabilityTrigger` (IoU temporel > 0.7 sur N frames consécutives),
`YoloConfidenceTrigger` (conf > seuil sur N frames), `ArcFaceConsensusTrigger`
(consensus actuel atteint, burst en aval). Strategy pattern Kotlin avec
interface `TriggerStrategy`.

**Rationale** : on ne sait pas a priori lequel est le bon. Tester
empiriquement.

### D6. Pas de choix par défaut a priori, pas d'auto-suppression de path

Au runtime, la debug-bar fixe la stratégie. Les trois stratégies restent
**toutes compilées en release** tant qu'une décision conjointe explicite
(user + audit) n'a pas été prise pour en retirer une. Aucun path de
détection n'est supprimé automatiquement — même après bench, on choisit
ensemble lequel devient le défaut, et les autres restent disponibles
jusqu'à ce que rien ne justifie de les garder.

**Rationale** : on n'a pas assez de data device pour décider
intelligemment a priori. Et même *avec* la data, l'auto-pruning crée de
la dette silencieuse — mieux vaut un code un peu redondant mais
auditable que des suppressions hâtives qu'on regrette quand un nouveau
mode de scan se présente.

**Alternative rejetée** : choisir maintenant et auto-tuner ;
auto-suppression des stratégies non-élues après N sessions de bench.

## Quality scoring

### D7. Score agrégé pondéré, pas d'absolue unique

Score = `w₁·sharpness + w₂·exposure + w₃·completeness (+ w₄·motion)`.
Mesuré sur le crop normalisé 224×224, pas sur la frame brute. Poids
calibrés sur 50 captures bench, pas hard-codés.

**Mesures concrètes** :
- **Sharpness** = `var(Laplacian(gray))` normalisé par taille
- **Exposure** = `1 − |mean_luminance − 0.5| × 2 − clipping_penalty` où
  clipping_penalty pénalise > 1% de pixels à 0 ou 255
- **Completeness** = `1 − max(0, (bord_pièce − bord_frame_avec_marge) /
  rayon)` où marge = 5% du rayon
- **Motion** (optionnel) = `1 − |Δbbox_center| / rayon` vs frame n-1

### D8. Early-stop sur seuils absolus + fallback sur relatif

Si une frame du buffer passe les 3 (ou 4) seuils absolus → on prend
celle-là, on arrête. Si aucune ne passe → on prend la moins pire et on
note `low_quality=true` dans capture_metadata.

**Rationale** : éviter de bloquer l'UX si l'utilisateur est dans des
conditions difficiles. Mieux vaut une archive imparfaite qu'aucune.

### D9. Pas de grading qualité **automatique** v1

Anti-objectif explicite : le pipeline scan **n'infère pas** un grade
numismatique (Belle/TB/SUP/SPL ou UNC/TTB/TB Sheldon) depuis l'image. Le
`quality_score` archivé dans `coin_captures` sert uniquement à :
(a) choisir la primary parmi les captures, (b) signaler une archive
dégradée. Il n'est jamais affiché à l'utilisateur sous forme de grade.

**Compatibilité Référentiel V2 / phase marketplace future** : le grading
UNC/TTB/TB acté par la décision D3 du Référentiel V2 (cf.
`docs/research/referential-v2.md`, Phase 4 de **cette** roadmap — à ne
pas confondre avec la Phase 4 app-implem qui est la carte eurozone) est
un grade **déclaré manuellement par l'utilisateur** au moment de proposer
une pièce à l'échange. Ça vivra dans un futur schéma `coin_listings`,
distinct du `quality_score` technique du scan. Les deux ne se croisent
pas en v1 : qualité de la photo ≠ état de la pièce.

**Rationale** : le grading numismatique automatique demande son propre
modèle ML, sa propre data labellisée (pièces certifiées NGC/PCGS), et
n'est pas dans le scope du scan v1. Quand il arrivera (Phase 5+ peut-
être avec Sheldon 70 points), il sera un module séparé qui consomme
l'image archivée, pas une feature couplée au scan.

## Capture

### D10. Preview YUV + ImageCapture full-res en parallèle

Preview continue pour scoring + ArcFace (latence zéro). ImageCapture
déclenché à l'entrée Locking pour le JPEG full-sensor archivé.
**Sous réserve** de validation tech (chunk 5) que CameraX supporte les
deux UseCase simultanés sur Pixel 9a + mid-range Samsung.

**Fallback** si non-supporté : meilleure frame preview YUV → encode JPEG
quality 92. Perte qualité visible en zoom mais acceptable.

### D11. AE/AF/AWB lock via Camera2Interop pendant Locking

`CONTROL_AE_LOCK = true`, `CONTROL_AF_TRIGGER = START` (puis wait
`AF_STATE == LOCKED`), `CONTROL_AWB_LOCK = true`. Relâché à l'entrée
Accepted (ou au fallback Detecting si abort).

**Rationale** : sans lock, l'autofocus continue à hunt pendant que les
5 frames burst → toutes floues. Sans AE lock, exposition varie → quality
score instable.

### D12. JPEG quality 92, long-side max 2048

Sweet spot taille/qualité. Long-side 2048 suffit pour zoom inspection
détaillé sans gonfler l'APK ni la sync future. ~500 KB/coin estimé.

**Alternative rejetée** : conserver le full-res brut (12 MP). 3-5 MB par
fichier × 200-1000 coins = trop sur le device de l'utilisateur.

## Storage

### D13. Schéma deux tables — possession vs capture

```sql
coin_in_vault                      -- 1 row par eurio_id possédé
  eurio_id TEXT PRIMARY KEY
  first_captured_at INTEGER NOT NULL
  primary_capture_id TEXT NOT NULL  -- FK coin_captures.capture_id
  declared_count INTEGER NOT NULL DEFAULT 1
  notes TEXT

coin_captures                      -- journal complet
  capture_id TEXT PRIMARY KEY       -- uuid v4
  eurio_id TEXT NOT NULL            -- FK coin_in_vault.eurio_id (nullable plus tard pour orphan)
  captured_at INTEGER NOT NULL
  image_filename TEXT NOT NULL
  quality_score REAL NOT NULL
  is_primary INTEGER NOT NULL       -- bool 0/1, exactement 1 primary par eurio_id
  capture_metadata TEXT NOT NULL    -- JSON
```

**Rationale** : sépare la logique d'inventaire de la logique d'archive
photo. Détecter "même exemplaire physique" via embedding visuel n'est
pas fiable — on ne tente pas.

### D14. Pas de multi-instance physique en v1

`declared_count` est un entier manuel, pas un compteur d'instances. Si
l'utilisateur veut taguer "j'ai 3 exemplaires", il le déclare depuis la
fiche coffre (+/- buttons). Pas de table `coin_instances` v1.

**Rationale** : l'ambiguïté "même pièce ou pas" est résolue par
"l'utilisateur décide", pas "le modèle infère".

**Alternative rejetée** : table `coin_instances(eurio_id, instance_id)`
avec une row par scan. Schéma plus riche mais force des questions
impossibles à l'utilisateur ("quel exemplaire viens-tu de scanner ?").

### D15. Filesystem `context.filesDir/vault/<uuid>.jpg`

Internal storage, pas externalFilesDir. Pas visible dans l'explorateur
fichiers Android, pas exposé via FileProvider à des tiers sans intention
explicite. Cleanup automatique si l'app est désinstallée.

**Rationale** : scope storage Android post-API 29, plus simple en
internal. Backup via Android Auto-Backup possible plus tard (opt-in).

### D16. EXIF strippé à l'encodage

`ExifInterface.removeAttribute()` sur tous les tags geo, sensor, OS,
timestamps avant l'écriture. Aucune frame archivée ne sort avec EXIF.

**Rationale** : si la sync Supabase Storage arrive avec la phase
marketplace future (Référentiel V2 phase 4), pas de rétro-fit panique.
Donnée user neutre dès aujourd'hui. Cf. P8 vision.md pour la stratégie
forward-compat globale.

### D17. Re-scan = archive silencieuse + opt-in pour replace primary

Si l'utilisateur re-scanne une pièce déjà en `coin_in_vault` :
- Toujours archiver dans `coin_captures` (no question)
- Si `new.quality_score > current_primary.quality_score` → snackbar
  *"Belle prise, en faire la photo de référence ?"* avec action
- Sinon : silent

**Rationale** : ne jamais bloquer le scan continuous. Valoriser les
bonnes prises sans frustrer.

## Debug & itération

### D18 (note — pas dans les 17 originaux mais implicite). Debug-bar BuildConfig.DEBUG only

Aucun code de debug-bar dans le build release. Pas de toggle caché, pas
de feature flag. Cf. `feedback_no_debt`. Le bench se fait en debug-build
dédié si besoin.

### D19. Record mode opt-in

Toggle dans la debug-bar pour activer le dump JSONL + raw frames du run
courant. Pas auto-ON par défaut (sinon le filesystem device dev se
remplit). Option "always record in debug build" disponible si on veut
inverser pour une session de bench longue.

### D21. Visualisation graphique riche des phases en debug

En BuildConfig.DEBUG, une couche overlay graphique par-dessus la
preview caméra rend visible **chaque phase** du pipeline best-frame :

- bbox détectée dessinée en couleur, change selon la state machine
  (Detecting/Locking/Locked/Failed/Aborted)
- région AF effective (élargie 10-15% autour du centre bbox) dessinée
  en pointillés pendant Locking
- halo de lock qui pulse pendant Acquiring, fixe pendant Locked
- flash d'abort + label motif quand `TriggerEvent.Abort`
- timing AF affiché en ms après l'acquisition

**Rationale** : l'utilisateur (dev) doit pouvoir tenir le téléphone et
comprendre instantanément ce que fait le pipeline sans regarder les
logs. Le HUD textuel donne les chiffres, l'overlay graphique donne
l'intuition spatiale. Les deux sont complémentaires, pas redondants.

**Strictement debug** : en release, conformément à `feedback_scan_ux`
(QR-scanner-style, zéro friction), aucun de ces overlays n'est rendu.
L'utilisateur final ne voit que la caméra et la fiche au moment du
match. Pas de "vous êtes en phase locking" user-facing.

**Conséquence pour le bench** (D20 + chunk-7) : tout ce qui est dessiné
sur l'overlay doit aussi être loggué dans le JSONL — LockState
transitions avec timestamps, AF region effective, motif d'Abort, etc.
Le bench reproduit hors-device exactement ce que l'utilisateur a vu
sur l'overlay.

### D22. Abort sur perte de stabilité pendant le lock

Si la pièce bouge ou disparaît de la frame pendant que
`CameraLockController` est en `Acquiring` ou `Locked`, le trigger
émet `TriggerEvent.Abort`. Le controller appelle `release()` (AE/AWB
unlock + cancelFocusAndMetering), l'overlay affiche un flash rouge
avec le motif, et la state machine retombe en Detecting.

**Rationale** : plus simple qu'une boucle de surveillance motion
parallèle. Délègue la décision au seul composant qui sait ("le
trigger a perdu sa stabilité").

**Alternative rejetée** : monitorer le motion score en parallèle du
lock et auto-release sur motion > seuil. Demande une boucle dédiée,
duplique la logique de stabilité, pas worth it.

### D20. Replay sur frames bufferisées

Chaque session record produit assez de data pour re-jouer la décision
best-frame avec d'autres paramètres trigger / quality gates **sans
re-scanner physiquement**. Tooling dans le chunk 7.

**Rationale** : économise des dizaines d'heures de scan répété quand on
veut tuner les seuils.

---

## Décisions de transition (ajoutées après audit cross-ref 2026-05-15)

### D23. Migration `vault_entries` → `coin_in_vault` + `coin_captures`

`vault_entries` (table actuelle, `VaultEntryEntity.kt`, schéma v2) joue
aujourd'hui les deux rôles : journal de scan ET marqueur de possession.
Migration v2 → v3 :

1. Création des deux nouvelles tables (`coin_in_vault`, `coin_captures`).
2. Pour chaque `coin_eurio_id` distinct de `vault_entries` : insert dans
   `coin_in_vault` avec `firstCapturedAt = MIN(scanned_at)`,
   `primaryCaptureId = NULL` (pas de JPEG historique disponible),
   `declaredCount = COUNT(*)` (préserve les scans répétés implicites).
3. **Aucune** `coin_captures` rétroactive — on n'a pas les images
   originelles. Le `primaryCaptureId` reste NULL jusqu'au premier scan
   post-migration ; le rendu fiche coffre v1 doit fallback sur l'image
   canonique Numista quand `primaryCaptureId == null`.
4. `vault_entries` est DROP en fin de migration. `MIGRATION_2_3` explicite
   dans `EurioDatabase.kt`, **pas** `fallbackToDestructiveMigration` en
   release.

**Conséquence schéma** : `CoinInVaultEntity.primaryCaptureId: String?`
(nullable), pas non-null comme initialement esquissé dans chunk-5.

**Rationale** : préserver les `declared_count` implicites (l'utilisateur
qui a scanné Slovenia 3 fois a fait un acte intentionnel, ne pas perdre
cette info), sans inventer de JPEG. Migration data-safe par construction.

### D24. Archive auto vs Possession opt-in

Le scan accepté **archive systématiquement** dans `coin_captures` (P1) —
même si l'utilisateur dismiss la card sans taper « Ajouter au coffre ».
La possession (`coin_in_vault` upsert) est **strictement déclenchée**
par le tap « Ajouter au coffre » (cohérent avec décision #7 phase-1 app
et `feedback_scan_ux` — la card adaptive existe déjà).

```
Consensus reached  ──> coin_captures insert (toujours, side effect P1)
                  ──> AcceptedCard affichée
                          │
                          ├─ user tap « Ajouter au coffre »
                          │     └─> coin_in_vault upsert + setPrimary(captureId)
                          │
                          └─ user dismiss (ou auto-cooldown)
                                └─> rien — capture reste orpheline dans le journal
```

**Conséquence** : `coin_captures` peut contenir des rows sans `coin_in_vault`
correspondant. C'est **voulu** — le journal d'inférence reste utile au
bench (chunk-7), et l'utilisateur peut toujours adopter rétroactivement
une pièce qu'il avait scannée mais pas gardée. Un cleanup éventuel
(purge captures orphelines > 30 jours) sera ajouté en module séparé si
le filesystem grossit trop — pas en v1.

**Rationale** : ne pas casser silencieusement l'UX existante (le bouton
« Ajouter au coffre » disparu serait une régression invisible mais
brutale pour le user). Le découplage P1 reste : la fiche affiche le
match dès consensus, l'archive tourne en background, et la possession
est un acte conscient.

**Alternative rejetée** : auto-upsert `coin_in_vault` à chaque scan
accepté. Bypass l'intent user, pollue le coffre avec des pièces que le
user voulait juste identifier en passant. Casse le pattern Shazam-like
implicite de la décision #7.

### D25. `photoMode` + `captureMode` debug conservés tels quels

Les deux modes existants côté `CoinAnalyzer.kt` (photoMode = snap manuel
debug, captureMode = protocole Phase 0 golden-set ML) **ne sont pas
touchés** par best-frame :

- Ils écrivent dans `externalFilesDir/eurio_debug/{snaps,eval_real}/`
  (storage **externe**, scope debug, `BuildConfig.DEBUG` only).
- Le nouveau `VaultCaptureRepository` écrit dans `filesDir/vault/`
  (storage **interne**, scope production, toujours actif).
- Zéro overlap : dossiers distincts, finalités distinctes (debug ML
  training vs vault user), durées de vie distinctes (debug = wiped à
  l'uninstall et via `go-task android:pull-debug`, vault = persistant).

**Rationale** : `feedback_chunk_audit_flow` impose chunk-par-chunk. Faire
disparaître ces modes en parallèle de best-frame mélangerait deux
refactorings indépendants. Ils restent jusqu'à preuve qu'ils sont
obsolètes (cf. D6 — pas d'auto-suppression de path).

**Conséquence** : `CoinAnalyzer.saveSnapToDisk()` (lignes 375-438
actuelles) coexiste avec `VaultCaptureRepository.archive()`. Les deux
chemins ne se croisent jamais. Audit visuel chunk-5 doit vérifier que
le tap « Ajouter au coffre » écrit dans `vault/` et **pas** dans
`eurio_debug/`.

---

## Pointeurs vers les chunks correspondants

| Décision | Chunk d'implémentation |
|---|---|
| D2, D3, D4 | chunk-6 (state machine) |
| D5, D6 | chunk-3 (trigger strategies) |
| D7, D8, D9 | chunk-2 (quality scorer) |
| D10, D11, D12 | chunk-4 (AE/AF lock) + chunk-5 (ImageCapture archive) |
| D13, D14, D15, D16, D17 | chunk-5 (ImageCapture archive) |
| D18, D19, D20 | chunk-1 (debug-bar) + chunk-7 (bench protocol) |
| D23, D24, D25 | chunk-5 (migration + repository possession) |
