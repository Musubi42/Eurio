# Dump QA — 3ᵉ profil hermétique (parité web ↔ Android)

> Source de vérité du chantier « dump QA ». Le côté **web est livré et vérifié** (2026-06-02). Le côté **Android (Chunks 4+6) est implémenté + compile** (`compileFullQaKotlin` OK, 2026-06-02) ; reste la **vérif device par Raphaël** (build/install/run + screenshots checklist §6).

## 1. Idée

`eurio.db` (SQLite) est la source de vérité. Le pipeline de dump en dérive les artefacts apps — jamais l'inverse. Il existe **trois profils** :

| | PROD (`build_app_core`) | QA (`build_app_core_qa`) |
|---|---|---|
| Source | Supabase (projection app-facing) | **eurio.db direct** (via les builders) |
| Données | catalogue complet | **sous-ensemble curé** (~15 pièces) |
| Timestamps / now | réels / dynamiques | **figés** (`parity_now`) |
| Images avers | **pas bundlées** → Supabase Storage au runtime | **toutes bundlées** → 100% hermétique, zéro réseau |
| Consommé par | app release + proto live | proto en mode parité + **Android `src/qa`** |

Le dump QA est le seul endroit où on fige le déterminisme (timestamps, seeds, sous-ensemble, images). Les fixtures de parité sont un **output généré**, pas écrit à la main.

## 2. Le dump QA (livré)

`ml/export/build_app_core_qa.py` (go-task `ml:build-app-core-qa`) :

1. lit `shared/fixtures/qa_curation.json` (15 `eurio_id` curés + `parity_now`, **édité manuellement** par Raphaël, jamais réécrit par le script) ;
2. ouvre `eurio.db` en RO (`get_sqlite_con()`) et bâtit le dict `core` via **les mêmes builders** que la projection Supabase (`app_export/builders/*`) → fidélité garantie, offline ;
3. filtre `core` au sous-ensemble, FR+EN seulement ;
4. fige `generated_at = parity_now`, injecte `obverse_image_url` (chemin local, `null` si pas d'avers → fallback SVG) ;
5. réutilise `build_json()` / `build_sqlite()` de `build_app_core` **sans modification** ;
6. copie les webps avers (`coin_canonical_images.local_path`, priorité `bce_official > eurlex_jo`) vers les deux cibles.

**Sorties** (toutes gitignorées — régénérables) :

```
admin/packages/proto/public/data/app_core_qa.json
admin/packages/proto/public/data/coin-images/<eurio_id>/obverse.webp
app-android/src/qa/assets/app_core.db
app-android/src/qa/assets/coin-images/<eurio_id>/obverse.webp
```

## 3. Côté WEB (livré + vérifié)

- `proto/src/api/parity.ts` : `PARITY_NOW` (= `parity_now` du manifest, à garder synchrones), `isParity()` (flag runtime `window.__eurioParity` injecté par Playwright, ou `?parity`), `now()`.
- `loader.loadFixtures` : charge `app_core_qa.json` si `isParity()`, sinon `app_core.json`.
- `normalise` mappe `prices` ; `market.deriveMarket` câblé sur les **cotes réelles** `coin.prices` (history/projection `null` = pas de fausse tendance) ; fallback synthétique seedé sinon.
- `coinObverseUrl` : `null` en parité si pas d'avers local (**pas de fallback réseau Supabase**) → `CoinImage` rend le SVG.
- Capture déterministe : `proto.ts` attend `document.fonts` chargées + (scènes 3D) `__eurioCoinReady` (posé après 2 rAF, marqueur `__eurioHas3D`) au lieu d'un délai aveugle.

**Vérifié** : vault QA (11 pièces, images locales), reveal 3D hermétique **byte-identique 3/3**, fiche prix réel (Princess Grace 2162,5 €), fiche no-image → fallback SVG. `go-task parity:capture-proto` régénère le bundle QA puis capture.

## 4. Côté ANDROID — implémenté (Chunks 4+6), vérif device en attente

> **Statut implémentation (2026-06-02)** — code livré + `compileFullQaKotlin` OK :
> - **C4.2** `obverseStorageUrl` (CoinRepository.kt) branché `IS_QA` → URI asset / Supabase sinon (zéro code QA en release).
> - **C4.3 / pièges** `android:build-qa`→`assembleFullQa`, `android:install-qa`→`installFullQa` (Taskfile corrigé).
> - **C6.4** `build_app_core_qa.py` régénère `preset-populated.json` + `preset-profile-demo.json` depuis la curation (1 pièce/pays, **11 pièces**, `addedAt = parity_now − (N−i)·24 h`). **Single-source tranché : preset-driven des deux côtés** — le web `store.seedFixture` lit désormais ces presets (`@shared/fixtures/*`) au lieu de `demoCoinIds()` dynamique. Métadonnées éditoriales (`levelOverride`) préservées (idempotent).
> - **C6.5** *no-op* : aucun rendu relatif-à-maintenant côté Android. `VaultGrid` (tri date) groupe sur `firstCapturedAt` **absolu** (= `addedAt` figé) via `SimpleDateFormat("MMMM yyyy")` → déjà déterministe. Les `System.currentTimeMillis()` restants sont en pipeline scan/bench, hors capture vault.
> - **C6.6** `Coin3DViewer` : flip figé en `IS_QA` (snap pose finale, pas d'anim) — miroir du `__eurioCoinReady` web. Pas de tilt inventé (serait du drift proto, R1) → comparaison visuelle à l'œil de Raphaël.
>
> **Correctifs post-1ère vérif device (2026-06-02, compile OK)** :
> - **Bug version-gate** (catalogue stale / `fr-1999` absent) : `AppCoreBootstrapper` sautait le rechargement quand `storedVersion >= APP_CORE_VERSION`. → en `IS_QA` le bootstrap **force un reload propre à chaque lancement** (`clearCoins()` + reload → catalogue = exactement les 15 ; coffre cascadé re-seedé par le deep link). **Plus besoin de `pm clear`** manuel. Le merge asset qa>main est confirmé OK (asset packagé = 147 k / 15 coins).
> - **Gap prix fiche** : la fiche Android n'affichait **aucune cote** (`CoinPriceDao` jamais lu, pas de section). → ajout `deriveMarketFromPrices` (port fidèle de `market.marketFromPrices`, cotes réelles only, pas de tendance fabriquée), `CoinRepository.findMarket`, et bloc **VALEUR** dans `CoinDetailScreen` (P25/P50/P75 + Δ vs faciale + badge rareté). `+AppCoreBootstrapper:D` ajouté au filtre `android:logs`.
>
> **Restent device-only (non scriptables ici)** : vérif runtime du catalogue (logcat `AppCoreBootstrapper` → ~15 coins), affichage cote Princess Grace (2162,5 €), avers offline (mode avion sur install fraîche), et toute la **checklist §6**.

### Spec d'origine (Chunks 4+6)

### Pré-acquis vérifiés
- buildType `qa` (`initWith debug`, `applicationIdSuffix ".qa"`, `BuildConfig.IS_QA = true`) ; flavors `full` / `cohortTest` → variant **`fullQa`** (`com.musubi.eurio.qa`).
- `src/qa/assets/` est un **vrai dossier** (seul `fixtures` y est un symlink vers `shared/fixtures/`) → on peut y déposer `app_core.db` + `coin-images/` sans casser le symlink. ✅ (le dump le fait déjà.)
- `MainActivity` gère `eurio://parity/seed?fixture=<name>` (gardé par `BuildConfig.IS_QA`) → `seedFromFixture()` lit `fixtures/preset-<name>.json` → insère dans `coin_in_vault`.
- Images : tous les repos passent par **`obverseStorageUrl(eurioId)`** (`CoinRepository.kt:104`) → un seul seam à dériver.
- `AppCoreBootstrapper` : version-gate via constante `APP_CORE_VERSION` ; skip si `stored >= packaged`.

### Chunk 4 — bundle QA hermétique côté Android

1. **Asset overlay** (déjà produit par le dump) : `src/qa/assets/app_core.db` (subset 15) doit **shadow** `src/main/assets/app_core.db` (complet) dans `fullQa`. Comportement Gradle attendu (buildType source set > main) — **à vérifier** (cf. checklist). Si le merge ne prend pas : fallback = renommer en `app_core_qa.db` + constante `ASSET_NAME` en `src/qa`.
2. **Avers depuis les assets** : dériver `obverseStorageUrl` —
   ```kotlin
   fun obverseStorageUrl(eurioId: String): String =
       if (BuildConfig.IS_QA)
           "file:///android_asset/coin-images/$eurioId/obverse.webp"
       else
           "${SupabaseConfig.STORAGE_BASE_URL}/coin-images/$eurioId/obverse.webp"
   ```
   Coil sert l'URI asset en offline. La pièce no-image (`fr-1999`) n'a pas d'asset → Coil error → fallback composant (= équivalent du fallback SVG web). **Zéro code QA dans le release** (`IS_QA` false → branche Supabase). *(Variante plus pure : mettre la branche dans un fichier `src/qa/java/` — mais le `if (IS_QA)` sur une fonction unique est acceptable et plus simple.)*
3. **Bootstrap QA déterministe** : l'app `.qa` est un id séparé → **install propre** = `storedVersion` null → bootstrap depuis le `app_core.db` QA. Pour des captures reproductibles, faire une **install propre** (désinstaller avant, ou `adb shell pm clear com.musubi.eurio.qa`). *(Durcissement optionnel : `APP_CORE_VERSION` lu depuis une resource `src/qa/res/values/qa_version.xml` générée par le dump — non requis pour démarrer.)*

### Chunk 6 — seed figé + capture Maestro hermétique

4. **Preset aligné au sous-ensemble + `parity_now`** (CRITIQUE) : `seedFromFixture('populated')` lit `shared/fixtures/preset-populated.json`. Ses `eurio_id` **doivent ⊆ les 15 pièces QA** (sinon violation FK `coin_in_vault → coin`) et ses `addedAt` doivent être **alignés sur `parity_now`** (mêmes valeurs que le web).
   → Étendre `build_app_core_qa.py` pour **régénérer `preset-populated.json`** (et `preset-profile-demo.json`) depuis la curation : 1 pièce/pays du sous-ensemble, `addedAt = parity_now_ms - (N-i)*24h`. Idempotent.
   → **Single-source du seed** : faire lire ce même preset par le web (`store.seedFixture` → charger le JSON au lieu de `demoCoinIds()` dynamique) pour une parité web↔android exacte. *(Décision à confirmer : web preset-driven, ou garder web dynamique — déjà in-subset et figé via `now()`.)*
5. **Horloge figée Android** : si du rendu relatif (« ajoutée il y a X ») existe côté Android, le brancher sur `parity_now` (constante partagée) en `IS_QA`. Sinon les `addedAt` figés du preset suffisent.
6. **Mock caméra / freeze 3D** : `ParityFlags.mockCamera` existe déjà ; vérifier que le viewer 3D Android (`Coin3DViewer`) peut être figé (pose fixe) pour les captures de reveal — sinon ajouter un flag de freeze en `IS_QA` (miroir du `__eurioCoinReady` web).
7. **Capture** : `go-task android:parity:capture` (boucle Maestro sur `flows/*.yaml`, deps `install-qa`).

### Risques / pièges connus
- **`go-task android:install-qa` exécute `./gradlew :app-android:installQa`** → tâche **ambiguë/inexistante** (les variants sont `installFullQa` / `installCohortTestQa`). **À corriger** en `installFullQa`. De même `build-qa` (`assembleQa`) assemble les deux flavors.
- Merge asset `app_core.db` qa>main : non testé → checklist.
- FK preset ⊄ subset : à garantir (point 4).
- Les flows scan `scan-detecting/matched/failure/not-identified/debug` pointent vers des routes proto **mortes** (design shift) — drift à réconcilier (chantier C3), hors dump QA.

## 5. Build / install / run eurio QA sur device

```bash
go-task ml:build-app-core-qa        # (1) régénère le bundle QA (db + images dans src/qa/assets)
# corriger d'abord android:install-qa → installFullQa, ou directement :
cd app-android && ./gradlew :app-android:installFullQa   # (2) build + install variant fullQa
adb shell pm clear com.musubi.eurio.qa                   # (3) install propre → bootstrap frais
adb shell am start -n com.musubi.eurio.qa/.MainActivity  # (4) lancer
go-task android:logs                                     # (5) logs filtrés Eurio
```

Seed d'un état (parité) via deep link :
```bash
adb shell am start -a android.intent.action.VIEW -d "eurio://parity/seed?fixture=populated" com.musubi.eurio.qa
```

## 6. Checklist de vérification (screenshots à m'envoyer)

Après `go-task ml:build-app-core-qa` + install propre `fullQa` :

- [ ] **Catalogue = 15 pièces** : logcat `AppCoreBootstrapper` doit afficher ~15 coins lus (pas le catalogue complet) → confirme que le merge asset qa>main a pris. *(screenshot logcat + écran catalogue)*
- [ ] **Coffre seedé** : deep link `parity/seed?fixture=populated` → le coffre se peuple **sans crash FK**, avec les pièces du sous-ensemble. *(screenshot coffre)*
- [ ] **Avers offline** : couper le réseau (mode avion), ouvrir une fiche d'une pièce avec image (ex. Princess Grace) → l'avers s'affiche (servi depuis l'asset, pas Supabase). *(screenshot fiche, avion activé)*
- [ ] **Fallback no-image** : fiche de `fr-1999-2eur-standard-1st-map` → rendu dégradé (pas de photo, fallback composant), pas de spinner infini. *(screenshot)*
- [ ] **Prix réel** : fiche Princess Grace → valeur ≈ **2162,5 €** (cote TTB réelle, comme le web). *(screenshot)*
- [ ] **Parité visuelle** : comparer chaque écran au screenshot web correspondant (`admin/packages/parity/screenshots/proto/`) — mêmes pièces, mêmes valeurs, mêmes états.
- [ ] **Release intact** : `installFullDebug` (ou release) → l'app charge le **catalogue complet** + avers Supabase (le code QA ne fuit pas). *(screenshot)*

## 7. Curation actuelle (`shared/fixtures/qa_curation.json`)

15 pièces (14 avec image + 1 sans). Cas couverts : chère (Princess Grace 3900 €), micro-états (MC/VA/SM), variantes coloured/hologram (+ `canonical_eurio_id`), source EUR-Lex/JO vs BCE, titres i18n longs, commémos récentes FR/DE/IT, contraste prix bas (Atomium), fallback SVG (`fr-1999`).

**Gaps assumés** : design-group multi-pays NON couvrable (aucune pièce à image locale n'a de `design_group_id`) ; pièce démonétisée non sourçable en brut (`status='referenced'`, démonétisation calculée par le builder).
