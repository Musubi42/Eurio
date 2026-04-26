# Porting Coin 3D Viewer — Three.js (proto) → SceneView/Filament (Android)

Trace **finale** du portage. Toutes les phases (0 à 6) sont shippées et
validées sur Pixel 9a (Mali-G715, OpenGL ES 3.2). Cette doc reste comme
archéologie : status par phase, table de correspondance API Three.js ↔
Filament, décisions de portage (D-PORT-1 à 7), pièges Filament/SceneView
rencontrés. Référence transversale (géométrie, math UV, paramètres PBR) :
`technical-notes.md`. Décisions design qui datent du proto et restent valides
en prod : `decisions.md`.

## Résultat

`Coin3DViewer.kt` (un fichier ~450 lignes) rend une 2€ avec photo + relief
Sobel + éclairage 2-key + tone mapping ACES, intégré dans :
- **Sandbox dev** (`Coin3DSandboxScreen`, route `dev/coin-3d-sandbox`) — utile pour itérer matériaux/lighting hors flow scan
- **Scan flow Accepted** — viewer fullscreen + flip 600 ms à chaque détection, `ScanAcceptedCard` slide-in à +400 ms
- **Carousel debug** — toggle dans `ScanDebugOverlay`, cycle des 818 pièces 2€, flip rejoué à chaque ‹/›
- **Page coin-detail** — viewer fullscreen sans flip (l'utilisateur orbit/zoom librement)

Build & toolchain :
- `go-task filament:install-matc` — installe matc 1.71.0 dans `tools/filament/` (gitignored)
- Gradle preBuild compile automatiquement `app-android/src/main/materials/*.mat` → `assets/materials/*.filamat`

## Status par phase

| Phase | Description | Status | Notes |
|---|---|---|---|
| 0 | Foundation (SceneView wired, sandbox) | ✅ done | Build + run validés sur Pixel 9a (Mali-G715, OpenGL ES 3.2). 4 primitives PBR rendent. |
| 1 | Pipeline metadata photo (snapshot Python → CoinEntity → Repo → ViewData) | ✅ done | Snapshot embed obverse_meta/reverse_meta (216/2938 coins, datasets locaux). Room v2 + MIGRATION_1_2 (ALTER TABLE ADD 6 colonnes nullable). PhotoMeta exposé via CoinViewData. |
| 2 | `Coin3DViewer` composable (mesh procédural complet) | ✅ done | 2a (mesh bimétal flat) + 2b (photos sur faces) + 2c (tranche reeded procédurale) + 2d (éclairage 2-key + IBL default + ACES tone mapping) validés sur Pixel 9a avec la pièce-test 226447. |
| 3 | Normal map runtime + cache disque | ✅ done | Sobel tangent-space normal map généré au premier load via `NormalMapBuilder.kt`, persisté en PNG dans `Context.cacheDir/coin-3d-normals/<eurioId>-<face>.png` (~350 kB par face). Custom material `coin_face.filamat` avec `baseColorMap` + `normalMap` + `normalScale` compilé via `matc` (toolchain auto-installé via `go-task filament:install-matc`, hook Gradle preBuild). Validé Pixel 9a : reliefs des 12 étoiles, du "2020", et de la figure agenouillée bien lisibles. |
| 4 | Debug carousel mode (top-bar prev/next, fake detection) | ✅ done | `ScanViewModel` étendu avec `_carouselMode` + `toggleCarouselMode()` + `onCarouselNext/Prev()`. Liste des 2€ chargée via `coinDao.findAllByFaceValue(2.0)` (818 pièces). `ScanCarouselTopBar.kt` posé en TopCenter, sous les panels CONVERGE/LATENCY du debug overlay. Toggle ajouté comme 8e bouton du tools strip (highlighted vert quand actif). En mode carousel, `CameraPreview` est démonté → caméra/ML pipeline coupés. Validé sur Pixel 9a : 7 taps badge → debug ON, tap Carous → carousel ON + 1ère pièce affichée, ‹/› cyclent les 818 pièces avec wrap-around. |
| 5 | Animation flip 600ms intégrée au scan flow | ✅ done | `Coin3DViewer` accepte `flipKey: Any?` ; à chaque changement, anime `rotationY 0→720°` (tween 600 ms) + `scale 0.85→1.0` (spring low-bouncy/low-stiffness) via `Modifier.graphicsLayer`. `ScanScreen` Accepted branch monte le viewer fullscreen derrière la `ScanAcceptedCard` qui slide-in 400 ms après — le card "rattrape" le coin en plein vol. Validé sur Pixel 9a en mode carousel : flip joue à chaque ‹/›, photo + relief + lighting fonctionnent pendant la rotation, AcceptedCard apparaît à temps. |
| 6 | Page coin-detail full 3D (optionnel v1) | ✅ done | `CoinDetailScreen.CoinContent` swap : `CoinImageCarousel` (180dp circle thumbnail) → `Coin3DViewer` (fillMaxWidth × 360dp, fond Ink, rounded EurioRadii.lg) quand `coin.imageObverseUrl != null`. Sinon fallback sur l'ancien carousel doré. Pas de `flipKey` passé : la page détail n'est pas un moment de découverte, l'utilisateur orbit/zoom librement. Validé Pixel 9a sur la pièce AD-2014 ouverte depuis le carousel scan. |

## Correspondance API Three.js → SceneView/Filament

Mêmes concepts PBR, syntaxe différente. Référence pour porter chaque ligne du proto.

| Concept | Three.js (proto) | SceneView Compose | Notes |
|---|---|---|---|
| Renderer / Scene host | `new THREE.WebGLRenderer({antialias: true})` + `<canvas>` | `Scene { ... }` ou `SceneView(modifier, engine, ...) { ... }` | SceneView gère tout (engine, view, swapchain) |
| Engine | implicite | `rememberEngine()` | Filament Engine — un par activity recommandé |
| Material loader | implicite | `rememberMaterialLoader(engine)` | Charge .filamat ou crée via helpers |
| Environment loader | `RoomEnvironment` + `PMREMGenerator` | `rememberEnvironmentLoader(engine)` | KTX/HDR loaders |
| Tone mapping | `renderer.toneMapping = ACESFilmicToneMapping` | `view.colorGrading.toneMapping = Filament.ACES` | Identique |
| Exposure | `renderer.toneMappingExposure = 0.80` | `view.exposure = ev` (en EV stops) ou via `colorGrading` | Conversion : `ev = log2(1/0.80) ≈ 0.32` |
| `MeshStandardMaterial` (PBR metal/rough) | `new MeshStandardMaterial({color, metalness, roughness, map, normalMap, normalScale})` | `materialLoader.createColorInstance(color, metallic, roughness, reflectance)` ou material custom | Pour photo+normalMap : material custom .filamat ou Filament `Material.Builder()` |
| `RingGeometry`/`CircleGeometry` (UV custom) | `THREE.RingGeometry(rIn, rOut, segs, 1)` + remap UV manuel | `Geometry$Builder` Filament avec `bufferType=POSITION/UV/NORMAL/INDEX` | Custom UV via floats[] — port direct du `remapUVsFromXY` |
| `CylinderGeometry` (open) | `THREE.CylinderGeometry(r, r, h, segs, 1, true)` | `CylinderNode(radius, height, materialInstance)` (existing primitive) ou Filament builder | Pour la tranche : utiliser `CylinderNode` ou builder. Pour les step walls : pareil mais hauteur 0.06mm |
| `CircleGeometry` solid | `THREE.CircleGeometry(r, segs)` | Pas de primitive → builder avec triangle fan | À écrire |
| `DirectionalLight` | `new THREE.DirectionalLight(color, intensity)` + `light.position.set(x, y, z)` | `LightNode { type = LightManager.Type.DIRECTIONAL; intensity = ...; direction = ... }` | Filament unit = lumen, pas l'unité Three.js — calibrer empiriquement |
| `HemisphereLight` | `new THREE.HemisphereLight(sky, ground, intensity)` | Pas direct ; utiliser ambient via IBL ou skybox | Délégué à l'IndirectLight pour simplicité |
| IBL | `scene.environment = pmrem.fromScene(new RoomEnvironment(...)).texture` | `environmentLoader.createHDREnvironment("path.hdr")` ou `createEnvironment(loader)` (default) | Default suffit pour Phase 0 |
| OrbitControls | `new OrbitControls(camera, dom)` | `cameraManipulator = rememberCameraManipulator(orbitHomePosition, target)` | Built-in dans SceneView |
| `material.normalScale.set(v, v)` | direct property | Material parameter custom `setParameter("normalScale", v)` | Demande material avec un uniform `normalScale` |
| Texture loading | `new THREE.TextureLoader().load(url, onLoad)` | `textureLoader.createTexture(bitmap)` ou `Texture.Builder()` Filament | Coil → Bitmap → Filament Texture |
| Canvas-based normal map | `canvas.getImageData` + Sobel JS | Android `Bitmap` + Sobel Kotlin | Logic identique, syntaxe différente |
| Group / hierarchy | `new THREE.Group()` + `.add()` | `Node()` parent + `addChildNode()` | OK |

### Pièges anticipés en début de portage (résolution dans D-PORT)

- **Custom UV sur ring/disc** : pas de remap dynamique post-construction en Filament. Les UVs sont baked à la construction, géométrie rebuilt si la photo meta change. ✅ Acceptable en pratique — le viewer rebuild les sub-meshes via `remember(...)` quand la pièce change.
- **Material avec photo + normal map** : `materialLoader.createColorInstance` est uni-couleur, pas de slot normal map. → résolu en D-PORT-7 par un `coin_face.mat` custom compilé via matc.
- **Tone mapping** : Filament ACES diffère légèrement de Three.js ACESFilmicToneMapping. → résolu en D-PORT-6, calibré visuellement, pas de re-tune d'exposure nécessaire avec la default Filament f/16 1/125 ISO100.
- **`reflectance`** : Filament a ce paramètre (F0 du dielectric) absent de Three.js. Default 0.5 = équivalent, conservé tel quel.

## Décisions de portage

- D-PORT-1 (Phase 0) : version SceneView pinned `4.0.0` hardcoded dans `build.gradle.kts`, pas dans `libs.versions.toml`. Rationale : le fichier dependencies utilise déjà un mix de styles (Compose via libs, autres via inline) — cohérent avec la convention du fichier.
- D-PORT-2 (Phase 0) : bump Kotlin `2.0.21 → 2.3.21` + KSP `2.0.21-1.0.28 → 2.3.7` + Room `2.6.1 → 2.8.4` + migration `kotlinOptions { jvmTarget = "11" }` → `kotlin { compilerOptions { jvmTarget.set(JVM_11) } }`. Rationale : les jars publiés de SceneView 4.0.0 ont metadata Kotlin `2.3.0` (le plan annonçait à tort une compat K2.0). KSP 2.3.x n'existe qu'en mode KSP2 → Room 2.6.1 incompatible (`unexpected jvm signature V`) → bump à Room 2.8.4 (KSP2-ready). Ripple : `kotlinOptions` DSL retiré en Kotlin 2.3.
- D-PORT-7 (Phase 3) : toolchain Filament `matc` installée localement via `go-task filament:install-matc` (download tarball GitHub `filament-v1.71.0-mac.tgz` → `tools/filament/`, gitignored). Pinned à `v1.71.0` pour matcher exactement la version embarquée par SceneView 4.0.0 (vérifié via `filament-android-1.71.0`). `app-android/src/main/materials/*.mat` compilés en `.filamat` dans `app-android/src/main/assets/materials/` (gitignored, regénérés à chaque build via une tâche Gradle `compileFilamentMaterials` hookée à `preBuild`). Material custom `coin_face.mat` : lit + `baseColorMap` + `normalMap` + uniforms `metallic/roughness/reflectance/normalScale`. Tangent-space normal décodée `xyz * 2 - 1` puis multipliée par `normalScale.xy` AVANT `prepareMaterial(material)` (requis Filament). Cf. NormalMapBuilder pour la pipeline Sobel + cache disque (PNG via `Context.cacheDir`). Choix de ne pas committer le `.filamat` : éviter la dette d'un binaire qui drift de sa source.
- D-PORT-6 (Phase 2d) : éclairage 2-key porté via `mainLightNode` (front, 110k lm direction (+0.3,-0.3,-1)) + un second `LightNode` directionnel ajouté via la DSL `SceneScope.LightNode` dans la trailing lambda du `SceneView` (back fill, 78k lm direction négative). Ratio ~1.4 : 1 emprunté au proto. Tone mapping switché de `ToneMapper.Filmic()` (default SceneView) à `ToneMapper.ACES()` via un `View` custom construit avec `rememberView(engine) { createView(engine).apply { colorGrading = ColorGrading.Builder().toneMapper(ToneMapper.ACES()).build(engine) } }` — équivalent direct du `renderer.toneMapping = ACESFilmicToneMapping` du proto. Pas d'override d'exposure (la default Filament f/16 1/125 ISO100 + ACES rend déjà proche du proto à exposure 0.80 visuellement, à recalibrer plus tard si on importe un HDR custom). IBL = default SceneView (`rememberEnvironment(environmentLoader)`).
- D-PORT-5 (Phase 2c) : aucun `engine.destroyTexture()` explicite côté viewer. Compose dispose ses `DisposableEffect` blocks **avant** les `remember*` (LIFO selon ordre d'enregistrement), donc destroy-texture-puis-cleanup-MaterialLoader → MaterialInstance encore lié à la texture détruite → `Filament: Invalid texture still bound to MaterialInstance` → SIGABRT. Solution : laisser `Engine.destroy()` (dernier dispose à se déclencher via `rememberEngine`) nettoyer toutes les textures restantes. Conséquence : leak des textures obverse/reverse au swap de pièce dans la même instance de viewer — acceptable pour la sandbox single-coin, à revisiter en Phase 4 (carousel) avec un teardown explicite *MaterialInstance d'abord, puis Texture*.
- D-PORT-4 (Phase 2b) : photo textures portées via `materialLoader.createTextureInstance(texture, metallic, roughness, reflectance)` (qui consomme le `opaque_textured.filamat` bundlé dans l'AAR SceneView), pas via un `.mat` custom compilé avec `matc`. Rationale : ce material stock = équivalent direct de Three.js `MeshStandardMaterial({map})` ; aucune toolchain à installer (matc absent de nixpkgs, dispo seulement via tarball GitHub Filament), aucun artefact à shipper. Reverse face : bitmap pré-mirroré horizontalement via `Canvas.drawBitmap` + `Matrix.preScale(-1,1)`, et `cx_uv` du meta flippé à `1 - cx_uv` côté viewer (le repository expose le meta brut, le flip est une concern de rendu). UV remap `v = cy + (y/R)*r` porté tel quel — confirmé visuellement (texte "VON WARSCHAU" upright). Pas de teinte silver/gold sur le photo material en 2b (createTextureInstance n'a pas de baseColorFactor) ; à juger après 2d si l'effet est trop "photo-y" vs proto.
- D-PORT-3 (Phase 2a) : tous les sub-meshes du Coin3DViewer sont déclarés via la **DSL `SceneScope.MeshNode`** dans la trailing lambda de `SceneView`, pas via `Node + addChildNode(GeometryNode(...))`. Rationale : `SceneNodeManager.addNode(parent)` n'attache que les entités Filament *propres* du parent à la `Scene`, pas ses descendants. La propagation aux enfants se fait ensuite via le callback `onChildAdded` que `addNode` enregistre — **après** la phase d'`apply`. Conséquence : `addChildNode(child)` dans `apply` (ou même dans `onAddedToScene`) ajoute bien `child` à `parent.childNodes` mais l'entité Filament du child n'arrive jamais dans la `Scene` → invisible. Vérifié au binaire (cf. `javap -c SceneNodeManager.addNode`). MeshNode DSL appelle l'API d'attachement interne (`SceneScope.attach$sceneview_release`) qui fait le lien correctement.

## Pièges Filament/SceneView rencontrés

- L'API publique du composable est **`SceneView`** (pas `Scene`, qui existe mais est l'alias) et n'a **pas** de paramètre `childNodes` : les nodes sont déclarés dans la **trailing lambda** via les méthodes DSL de `SceneScope` (`CubeNode`, `SphereNode`, `CylinderNode`, etc.). Les classes Node hors lambda (`io.github.sceneview.node.CubeNode(...)`) existent aussi mais ne sont pas la voie Compose.
- `mcp__sceneview__validate_code` produit un faux positif `api/light-node-trailing-lambda` sur `rememberMainLightNode(engine) { intensity = 100_000f }`. Vérifié contre la signature : la lambda reçoit `LightNode` et `intensity` est une property setter sur `LightNode` lui-même → la forme du sample est correcte.
