# Coin 3D Viewer — notes techniques

Référence canonique pour la géométrie 2€, le mapping UV XY→photo, le Sobel et
l'éclairage. **Les valeurs ci-dessous sont implémentées à la fois dans le
proto Three.js et dans le viewer Android Filament**, sans drift — la
transposition s'est faite 1:1 sur les nombres. Pour les détails *spécifiques
à Filament/Compose* (custom material, lifecycle textures, animation flip),
voir `porting-android.md`.

## Stack proto vs production

| | Proto (validation visuelle) | Production |
|---|---|---|
| Moteur | Three.js r160 via esm.sh | SceneView 4.0.0 (Filament 1.71.0) |
| Lieu | `docs/design/prototype/scenes/scan-coin-3d.{html,js}` | `app-android/src/main/java/com/musubi/eurio/features/scan/components/Coin3DViewer.kt` |
| Distribution | CDN runtime, proto `serve.sh` | AAR via Gradle (toolchain `matc` via `go-task filament:install-matc`) |
| Statut | ✅ shippé | ✅ shippé sur Pixel 9a |

Les deux moteurs implémentent le même modèle PBR Cook-Torrance metallic-roughness :
les paramètres `metalness` / `roughness` / `normalScale` / IBL se transposent 1:1.

## Géométrie 2€

Cotes physiques (mm) :

```
R_OUT          = 12.875    # outer radius (Ø 25.75)
R_RING_INNER   =  9.375    # inner edge of silver ring (Ø 18.75)
THICKNESS      =  2.80     # total height (rim to rim)
RING_LIP       =  0.06     # disc-vs-ring groove height (press-fit shadow)
RIM_WIDTH      =  0.90     # raised rim band width (radial)
RIM_HEIGHT     =  0.06     # raised rim height above ring face
```

Note : `THICKNESS` est légèrement gonflé vs spec 2.20mm pour la lisibilité visuelle au framing du viewer.

### Coupe radiale (top half, axe Z vertical)

```
              (rim raised band, R_OUT-RIM_W to R_OUT, z = T/2)
              ────────────────────
             /                                  ← rim_step (RIM_HEIGHT)
            /
   ─────────── ─                                ← ring face (z = T/2 - RIM_H)
  /          ─
 /             ─
/                ─                              ← ring_lip groove (RING_LIP)
                  ─────────                     ← disc face (z = T/2 - RIM_H - RING_LIP)
                            ↓
                     (axe central, r=0)
```

Mirror exact pour la partie inférieure.

### Pièces de mesh (top, mirror pour bottom)

| Pièce | Géométrie | Matériau | UV |
|---|---|---|---|
| Disc face | `CircleGeometry(R_RING_INNER)` | matGold (photo + normal map) | XY → photo via remap |
| Ring face | `RingGeometry(R_RING_INNER, R_OUT − RIM_W)` | matSilver (photo + normal map) | XY → photo via remap |
| Rim band | `RingGeometry(R_OUT − RIM_W, R_OUT)` | matSilver (même que ring) | XY → photo via remap |
| Disc-ring groove | `CylinderGeometry(R_RING_INNER, h=RING_LIP, open)` | matGroove (near-black) | default cylinder UV (non sampled significativement) |
| Ring-rim step | `CylinderGeometry(R_OUT − RIM_W, h=RIM_HEIGHT, open)` | matRim (plain silver, no map) | default |
| Tranche cylindrique | `CylinderGeometry(R_OUT, h=THICKNESS, open)` | matEdge (procédural) | repeated default |

## UV mapping XY → photo

Le cœur du proto. Pour tout vertex (x, y, z) sur les faces du dessus ou du dessous :

```
u = cx_uv + (x / R_OUT) * radius_uv
v = cy_uv + (y / R_OUT) * radius_uv
```

où `(cx_uv, cy_uv, radius_uv)` sont les **métadonnées per-photo** :
- `cx_uv, cy_uv` : centre de la pièce dans la photo, en UV. ~(0.5, 0.5) si centrée.
- `radius_uv` : rayon de la pièce dans la photo, en UV. ~0.499 si la pièce remplit le frame edge-to-edge.

Mesurées par `ml/measure_photo_meta.py` (luminance threshold + bbox), exportées en JSON.

### Cas particulier reverse

Le reverse est pré-mirroré horizontalement avant d'être plaqué (voir D4 dans
`decisions.md`). Conséquence : la métadonnée originale `(cx_uv, cy_uv)` du reverse
doit être recalculée pour le canvas mirroré : `cx_mirrored = 1 − cx_original`,
`cy_mirrored = cy_original`. Le `radius_uv` est invariant sous mirroir.

## Normal map dérivée par Sobel

Pipeline (canvas 2D, JS pur) :

```
1. luminance(r,g,b) = 0.299r + 0.587g + 0.114b
2. gx = sobel_x(luminance), gy = sobel_y(luminance)
3. normal_tangent = normalize(-gx, -gy, 1)  # avec strength=1 baked
4. encode RGB = (normal * 0.5 + 0.5)
```

Strength baked = 1 (linéaire propre, pas de saturation).
Variation visible = `material.normalScale * baked_strength`.
Slider `Relief` agit sur `normalScale` directement.

Coût ~100ms par image 1063×1063 sur MacBook M4. Acceptable au mount.

## Lighting

Studio à deux clés en world-space (voir D6) :

```
DirectionalLight 1 : intensity 1.4, position (2.5, 3.5, 4.0)
DirectionalLight 2 : intensity 1.0, position (-2.5, -3.5, -4.0)
HemisphereLight    : intensity 0.25, sky #ffffff, ground #202028
IBL (RoomEnvironment via PMREM, intensity 0.04 in scene.environment)
```

`renderer.toneMapping = ACESFilmicToneMapping`, `toneMappingExposure = 0.80`.

### Defaults de matériau

| Param | Valeur | Pourquoi |
|---|---|---|
| metalness | 0.50 | Préset utilisateur validé. Plus haut = look plus "miroir", moins lit avec photo bakée. |
| roughness | 0.50 | Préset utilisateur validé. Donne reflets adoucis, pas de hot spot. |
| normalScale | 0.30 (faces avant), 0.40 (faces arrière, boost ×1.33) | Voir D7. |
| Tints | silver `#eaeaef` × photo, gold `#f3d68a` × photo | Photo porte la couleur, tint amplifie le bimétal. |

## Tranche procédurale

Canvas 4096×256, généré au runtime :
1. Gradient vertical (foncé top/bottom, clair milieu) — simule rolloff cylindrique
2. ~280 stries verticales (moletage), darkness modulée
3. 6× "2 ★ ★ ★" en serif gras 110px, alterné upright/inverted, fill incised + highlight subtil
4. Vignette top/bottom (atténuation aux bords)

Wrap : `RepeatWrapping` x, `ClampToEdgeWrapping` y. `repeat = 1` (la texture couvre 100% du tour).

## Dispositions ouvertes

- `RIM_WIDTH = 0.90` est la valeur retenue pour le proto sur 226447. À re-valider sur d'autres pièces dans le carousel — possible que des designs dont les éléments dépassent loin radialement (ex : pièces où l'année est sur l'anneau extérieur) tirent vers une largeur différente.
- L'effet du `REVERSE_RELIEF_BOOST` n'est validé que sur le reverse 2€ commun (carte d'Europe). Pour les commémoratives à reverse spécifique (rares mais existent), à reposer.
