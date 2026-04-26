package com.musubi.eurio.features.scan.components

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Shader
import android.graphics.Typeface
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import kotlinx.coroutines.launch
import androidx.compose.ui.platform.LocalContext
import coil.ImageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import com.google.android.filament.ColorGrading
import com.google.android.filament.Engine
import com.google.android.filament.LightManager
import com.google.android.filament.MaterialInstance
import com.google.android.filament.RenderableManager
import com.google.android.filament.Texture
import com.google.android.filament.ToneMapper
import com.google.android.filament.utils.TextureType
import io.github.sceneview.material.setParameter
import io.github.sceneview.material.setTexture
import com.musubi.eurio.data.repository.PhotoMeta
import dev.romainguy.kotlin.math.Float2
import dev.romainguy.kotlin.math.Float3
import dev.romainguy.kotlin.math.Float4
import io.github.sceneview.SceneView
import io.github.sceneview.geometries.Geometry
import io.github.sceneview.math.Position
import io.github.sceneview.rememberCameraManipulator
import io.github.sceneview.rememberEngine
import io.github.sceneview.rememberEnvironment
import io.github.sceneview.rememberEnvironmentLoader
import io.github.sceneview.rememberMainLightNode
import io.github.sceneview.rememberMaterialLoader
import io.github.sceneview.createView
import io.github.sceneview.rememberView
import io.github.sceneview.texture.ImageTexture
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

// ── 2 € coin physical constants ────────────────────────────────────────────────
// (mm) — exactly matches the proto (cf. docs/coin-3d-viewer/technical-notes.md).
// World units = mm so we don't scale; camera is set up at the same distance.
private const val R_OUT = 12.875f
private const val R_RING_INNER = 9.375f
private const val THICKNESS = 2.80f
private const val RING_LIP = 0.06f
private const val RIM_WIDTH = 0.90f
private const val RIM_HEIGHT = 0.06f

private const val FACE_SEGMENTS = 192
private const val EDGE_SEGMENTS = 192

// PBR defaults — match the proto's DEFAULT_METALNESS / DEFAULT_ROUGHNESS used
// for matSilver/matGold/matEdge in scan-coin-3d.js.
private const val DEFAULT_METALLIC = 0.85f
private const val DEFAULT_ROUGHNESS = 0.32f
private const val DEFAULT_REFLECTANCE = 0.5f

// Normal map intensity for the obverse (front-facing) photo. The reverse face
// gets a small relief boost so it stays alive when seen from the back side
// (matches the proto's REVERSE_RELIEF_BOOST).
private const val DEFAULT_NORMAL_STRENGTH = 0.85f
private const val REVERSE_RELIEF_BOOST = 1.15f

// Default UV mapping when no measured photo metadata is available.
private val DEFAULT_PHOTO_META = PhotoMeta(cxUv = 0.5f, cyUv = 0.5f, radiusUv = 0.499f)

private val WHITE = Float4(1f, 1f, 1f, 1f)

/** One sub-mesh of the coin: a Geometry + which material to bind. */
private data class CoinSubMesh(val geometry: Geometry, val material: MaterialInstance)

/**
 * Live PBR tuning applied to the photo materials and the view's color grading.
 * Defaults match the hard-coded constants used at viewer init — passing the
 * default-constructed value is functionally identical to omitting the param.
 *
 * `relief` is the obverse normal-map intensity; the reverse face automatically
 * gets [REVERSE_RELIEF_BOOST]× on top of it, same as the static path.
 * `exposure` is a Three.js-style multiplier (1.0 = neutral) and gets converted
 * to Filament's EV via `log2(exposure)`.
 */
data class Coin3DTuning(
    val relief: Float = DEFAULT_NORMAL_STRENGTH,
    val metallic: Float = DEFAULT_METALLIC,
    val roughness: Float = DEFAULT_ROUGHNESS,
    val exposure: Float = 1.0f,
) {
    companion object {
        val Default = Coin3DTuning()
        const val RELIEF_MIN = 0f
        const val RELIEF_MAX = 2f
        const val EXPOSURE_MIN = 0.2f
        const val EXPOSURE_MAX = 2.0f
    }
}

/**
 * Procedural bimetal viewer for a 2 € coin. Phase 2b : photo textures bound
 * to the 6 face sub-meshes (top/bottom disc + ring + rim). Edge stays flat
 * silver until 2c (procedural reeded texture).
 *
 * Each sub-mesh becomes a [io.github.sceneview.node.MeshNode] declared
 * inline via the SceneScope DSL — that's the only path that auto-attaches
 * a Renderable to the Filament scene (see SceneNodeManager.addNode and
 * D-PORT-3 in docs/coin-3d-viewer/porting-android.md).
 *
 * While photos are loading (or when null URLs are passed), faces fall back
 * to flat silver/gold material instances so the mesh is always visible.
 */
@Composable
fun Coin3DViewer(
    eurioId: String?,
    obverseImageUrl: String?,
    reverseImageUrl: String?,
    obverseMeta: PhotoMeta?,
    reverseMeta: PhotoMeta?,
    modifier: Modifier = Modifier,
    /** When this changes, the viewer plays the discovery flip (Phase 5). */
    flipKey: Any? = null,
    /** Live PBR/exposure overrides — defaults reproduce the static rendering. */
    tuning: Coin3DTuning = Coin3DTuning.Default,
) {
    val context = LocalContext.current
    val engine = rememberEngine()
    val materialLoader = rememberMaterialLoader(engine)
    val environmentLoader = rememberEnvironmentLoader(engine)

    val obverse = obverseMeta ?: DEFAULT_PHOTO_META
    // Reverse photo is pre-mirrored horizontally so the coin reads right-way-
    // round when seen from behind (cf. proto). cx_uv flips with the mirror;
    // cy_uv and radius_uv are invariant.
    val reverseMirroredMeta = reverseMeta?.let { it.copy(cxUv = 1f - it.cxUv) } ?: DEFAULT_PHOTO_META

    val matSilverFlat = remember(materialLoader) {
        materialLoader.createColorInstance(
            color = Color(0xFFEAEAEF), metallic = DEFAULT_METALLIC, roughness = DEFAULT_ROUGHNESS,
        )
    }
    val matGoldFlat = remember(materialLoader) {
        materialLoader.createColorInstance(
            color = Color(0xFFF3D68A), metallic = DEFAULT_METALLIC, roughness = DEFAULT_ROUGHNESS,
        )
    }
    val edgeTexture = remember(engine) {
        val bmp = buildProceduralEdgeBitmap()
        ImageTexture.Builder().bitmap(bmp).build(engine).also { bmp.recycle() }
    }
    // No explicit destroy for Filament textures — Compose runs DisposableEffect
    // onDispose blocks BEFORE rememberMaterialLoader's cleanup, which means
    // destroying a texture here panics with "Invalid texture still bound to
    // MaterialInstance". Engine.destroy() (the last cleanup to fire when the
    // composable leaves) cleans up all remaining textures. We only leak across
    // coin swaps inside the same viewer instance — fine for sandbox, will need
    // proper teardown ordering when the Phase 4 carousel cycles through coins.
    val matEdge = remember(materialLoader, edgeTexture) {
        materialLoader.createTextureInstance(
            texture = edgeTexture,
            isOpaque = true,
            metallic = DEFAULT_METALLIC,
            roughness = 0.40f,
        )
    }

    // Filament textures for the photo (baseColor) + Sobel-derived normal map,
    // per face. Built when Coil delivers the bitmap; the normal map is fetched
    // from disk cache when available (NormalMapBuilder, see Phase 3 plan).
    var obversePhoto by remember { mutableStateOf<FacePhotoTextures?>(null) }
    var reversePhoto by remember { mutableStateOf<FacePhotoTextures?>(null) }

    LaunchedEffect(engine, eurioId, obverseImageUrl) {
        obversePhoto = obverseImageUrl?.let { url ->
            loadFacePhotoTextures(context, engine, url, mirror = false, cacheKey = eurioId?.let { "$it-obverse" })
        }
    }
    LaunchedEffect(engine, eurioId, reverseImageUrl) {
        reversePhoto = reverseImageUrl?.let { url ->
            loadFacePhotoTextures(context, engine, url, mirror = true, cacheKey = eurioId?.let { "$it-reverse" })
        }
    }

    // Custom lit material with baseColorMap + normalMap samplers (compiled from
    // src/main/materials/coin_face.mat, cf. D-PORT-7). Loaded once per engine.
    val coinFaceMaterial = remember(materialLoader) {
        materialLoader.createMaterial("materials/coin_face.filamat")
    }

    // One photo MaterialInstance per face — shared across all sub-meshes of
    // that face (gold disc + silver ring + silver rim). Held outside the
    // sub-mesh build so the tuning LaunchedEffect can mutate their params
    // without recreating instances on every slider tick.
    val obvPhotoMat: MaterialInstance? = remember(materialLoader, coinFaceMaterial, obversePhoto) {
        obversePhoto?.let { tex ->
            materialLoader.createInstance(coinFaceMaterial).apply {
                setTexture("baseColorMap", tex.baseColor)
                setTexture("normalMap", tex.normal)
                setParameter("metallic", DEFAULT_METALLIC)
                setParameter("roughness", DEFAULT_ROUGHNESS)
                setParameter("reflectance", DEFAULT_REFLECTANCE)
                setParameter("normalScale", DEFAULT_NORMAL_STRENGTH)
            }
        }
    }
    val revPhotoMat: MaterialInstance? = remember(materialLoader, coinFaceMaterial, reversePhoto) {
        reversePhoto?.let { tex ->
            materialLoader.createInstance(coinFaceMaterial).apply {
                setTexture("baseColorMap", tex.baseColor)
                setTexture("normalMap", tex.normal)
                setParameter("metallic", DEFAULT_METALLIC)
                setParameter("roughness", DEFAULT_ROUGHNESS)
                setParameter("reflectance", DEFAULT_REFLECTANCE)
                setParameter("normalScale", DEFAULT_NORMAL_STRENGTH * REVERSE_RELIEF_BOOST)
            }
        }
    }

    // Push tuning to live MaterialInstances. Filament's setParameter is
    // pull-based per-frame, so writing to these once per slider change is
    // enough — no per-frame loop needed.
    LaunchedEffect(tuning, obvPhotoMat, revPhotoMat) {
        obvPhotoMat?.apply {
            setParameter("metallic", tuning.metallic)
            setParameter("roughness", tuning.roughness)
            setParameter("normalScale", tuning.relief)
        }
        revPhotoMat?.apply {
            setParameter("metallic", tuning.metallic)
            setParameter("roughness", tuning.roughness)
            setParameter("normalScale", tuning.relief * REVERSE_RELIEF_BOOST)
        }
    }

    // Fall back to flat silver/gold while photos are loading so the coin is
    // never invisible during the network round-trip.
    val matSilverObv = obvPhotoMat ?: matSilverFlat
    val matGoldObv = obvPhotoMat ?: matGoldFlat
    val matSilverRev = revPhotoMat ?: matSilverFlat
    val matGoldRev = revPhotoMat ?: matGoldFlat

    val subMeshes = remember(
        engine, obverse, reverseMirroredMeta,
        matSilverObv, matGoldObv, matSilverRev, matGoldRev, matEdge,
    ) {
        buildCoinSubMeshes(
            engine, obverse, reverseMirroredMeta,
            matSilverObv, matGoldObv, matSilverRev, matGoldRev, matEdge,
        )
    }

    // Custom Filament View tuned for the coin viewer : ACES tone mapping
    // (matches the proto's Three.js ACESFilmicToneMapping) instead of SceneView's
    // default Filmic. The grading is rebuilt whenever tuning.exposure changes —
    // Filament's exposure() is in EV stops, the proto exposes it as a multiplier,
    // so we convert with log2.
    val view = rememberView(engine) { createView(engine) }
    DisposableEffect(view, engine, tuning.exposure) {
        val ev = kotlin.math.log2(tuning.exposure.coerceAtLeast(0.01f))
        val grading = ColorGrading.Builder()
            .toneMapper(ToneMapper.ACES())
            .exposure(ev)
            .build(engine)
        view.colorGrading = grading
        onDispose { engine.destroyColorGrading(grading) }
    }

    // Discovery flip animation (Phase 5). Resets every time `flipKey` changes
    // so each new coin gets its own cinematic appearance. Spring matches the
    // ScanAcceptedCard slide-in feel (low-bouncy / low-stiffness) for visual
    // continuity. Two full Y rotations land back at 0° so the obverse faces
    // the camera at rest.
    val flipRotation = remember { Animatable(0f) }
    val flipScale = remember { Animatable(1f) }
    LaunchedEffect(flipKey) {
        if (flipKey == null) return@LaunchedEffect
        flipRotation.snapTo(0f)
        flipScale.snapTo(0.85f)
        // 720° rotation runs in fixed-duration tween (a spring on rotation
        // overshoots and reads as wobble, not flip). The scale uses the spring
        // for a warmer pop-in.
        kotlinx.coroutines.coroutineScope {
            launch { flipRotation.animateTo(720f, animationSpec = tween(durationMillis = 600)) }
            launch {
                flipScale.animateTo(
                    targetValue = 1f,
                    animationSpec = spring(
                        dampingRatio = Spring.DampingRatioLowBouncy,
                        stiffness = Spring.StiffnessLow,
                    ),
                )
            }
        }
    }

    SceneView(
        modifier = modifier.graphicsLayer {
            rotationY = flipRotation.value
            scaleX = flipScale.value
            scaleY = flipScale.value
        },
        engine = engine,
        view = view,
        cameraManipulator = rememberCameraManipulator(
            orbitHomePosition = Position(x = 0f, y = 0f, z = 80f),
            targetPosition = Position(0f, 0f, 0f),
        ),
        environment = rememberEnvironment(environmentLoader),
        // Front key — proto's main light (intensity ratio 1.4 vs back's 1.0).
        mainLightNode = rememberMainLightNode(engine) {
            intensity = 110_000f
            lightDirection = Float3(0.3f, -0.3f, -1f)
        },
    ) {
        // Back fill — keeps the reverse face alive when the coin flips.
        // Direction is the negated front so the obverse stays brighter.
        LightNode(
            type = LightManager.Type.DIRECTIONAL,
            intensity = 78_000f,
            direction = Float3(-0.2f, 0.2f, 1f),
        )
        subMeshes.forEach { sm ->
            MeshNode(
                primitiveType = RenderableManager.PrimitiveType.TRIANGLES,
                vertexBuffer = sm.geometry.vertexBuffer,
                indexBuffer = sm.geometry.indexBuffer,
                boundingBox = sm.geometry.boundingBox,
                materialInstance = sm.material,
            )
        }
    }
}

/** Photo (baseColor) + Sobel-derived normal map textures for one face. */
private data class FacePhotoTextures(val baseColor: Texture, val normal: Texture)

// ── Bitmap loading ─────────────────────────────────────────────────────────────

private suspend fun loadFacePhotoTextures(
    context: android.content.Context,
    engine: Engine,
    url: String,
    mirror: Boolean,
    cacheKey: String?,
): FacePhotoTextures? {
    val photo = loadCoinFaceBitmap(context, url, mirror) ?: return null
    val normalBitmap = if (cacheKey != null) {
        NormalMapBuilder.loadOrBuild(context, cacheKey, photo)
    } else {
        NormalMapBuilder.build(photo)
    }
    val baseTexture = ImageTexture.Builder().bitmap(photo, TextureType.COLOR).build(engine)
    val normalTexture = ImageTexture.Builder().bitmap(normalBitmap, TextureType.NORMAL).build(engine)
    photo.recycle()
    normalBitmap.recycle()
    return FacePhotoTextures(baseTexture, normalTexture)
}

private suspend fun loadCoinFaceBitmap(
    context: android.content.Context,
    url: String,
    mirror: Boolean,
): Bitmap? {
    val request = ImageRequest.Builder(context)
        .data(url)
        .allowHardware(false) // need software bitmap to upload to Filament
        .build()
    val result = ImageLoader(context).execute(request)
    val drawable = (result as? SuccessResult)?.drawable ?: return null
    val bitmap = (drawable as? android.graphics.drawable.BitmapDrawable)?.bitmap ?: return null
    val rgba = if (bitmap.config == Bitmap.Config.ARGB_8888) bitmap
    else bitmap.copy(Bitmap.Config.ARGB_8888, false)
    return if (mirror) mirrorHorizontal(rgba) else rgba
}

// ── Procedural edge texture ────────────────────────────────────────────────────

/**
 * 4096×256 reeded-edge texture with 6 repetitions of "2 ★ ★ ★" alternating
 * upright/inverted. Direct port of `buildProceduralEdgeTexture()` from the
 * Three.js proto (docs/design/prototype/scenes/scan-coin-3d.js). The cylinder
 * UV wraps 0..1 once around the circumference, so the 6 lettering reps land
 * exactly where they should.
 */
private fun buildProceduralEdgeBitmap(): Bitmap {
    val w = 4096
    val h = 256
    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bmp)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG)

    // Base metal gradient (top dark, mid bright, bottom dark).
    paint.shader = LinearGradient(
        0f, 0f, 0f, h.toFloat(),
        intArrayOf(0xFF7A7A82.toInt(), 0xFFC0C0C8.toInt(), 0xFF7A7A82.toInt()),
        floatArrayOf(0f, 0.5f, 1f),
        Shader.TileMode.CLAMP,
    )
    canvas.drawRect(0f, 0f, w.toFloat(), h.toFloat(), paint)
    paint.shader = null

    // Reeding — ~280 vertical stripes around the circumference.
    val stripes = 280
    val stripeW = w.toFloat() / stripes
    for (i in 0 until stripes) {
        val x = i * stripeW + kotlin.math.sin(i * 12.43) * 0.6f
        val darkAlpha = (0.30f + 0.10f * kotlin.math.sin(i * 1.7).toFloat()).coerceIn(0f, 1f)
        paint.color = (((darkAlpha * 255f).toInt() and 0xFF) shl 24) or 0x23232A
        canvas.drawRect(x.toFloat(), 0f, x.toFloat() + stripeW * 0.55f, h.toFloat(), paint)
        paint.color = 0x1AE1E1E8.toInt() // alpha ~0.10, soft highlight
        canvas.drawRect(x.toFloat() + stripeW * 0.6f, 0f, x.toFloat() + stripeW * 0.6f + 1f, h.toFloat(), paint)
    }

    // Lettering : 6 reps of "2 ★ ★ ★", alternating orientation. Two passes per
    // rep (dark fill below + soft highlight above) imitates an incised look.
    val reps = 6
    val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        textSize = 110f
        textAlign = Paint.Align.CENTER
    }
    val text = "2 ★ ★ ★"
    val textVerticalOffset = -(textPaint.descent() + textPaint.ascent()) / 2f
    for (i in 0 until reps) {
        val cx = (i + 0.5f) * w / reps
        val inverted = i % 2 == 1
        canvas.save()
        canvas.translate(cx, h / 2f)
        if (inverted) canvas.rotate(180f)
        textPaint.color = 0xD914141A.toInt() // dark fill, alpha ~0.85
        canvas.drawText(text, 0f, textVerticalOffset + 4f, textPaint)
        textPaint.color = 0x47F5F5FA.toInt() // soft highlight, alpha ~0.28
        canvas.drawText(text, 0f, textVerticalOffset - 2f, textPaint)
        canvas.restore()
    }

    // Final cylindrical-shading vignette.
    paint.shader = LinearGradient(
        0f, 0f, 0f, h.toFloat(),
        intArrayOf(0x38000000, 0x00000000, 0x38000000),
        floatArrayOf(0f, 0.5f, 1f),
        Shader.TileMode.CLAMP,
    )
    canvas.drawRect(0f, 0f, w.toFloat(), h.toFloat(), paint)

    return bmp
}

private fun mirrorHorizontal(src: Bitmap): Bitmap {
    val out = Bitmap.createBitmap(src.width, src.height, Bitmap.Config.ARGB_8888)
    val matrix = Matrix().apply { preScale(-1f, 1f, src.width / 2f, 0f) }
    Canvas(out).drawBitmap(src, matrix, null)
    return out
}

// ── Mesh construction ──────────────────────────────────────────────────────────

/**
 * Build the 7 bimetal sub-meshes for the coin (Phase 2b):
 *  - top disc (gold-tinted obverse photo), top ring face (silver-tinted obverse), top rim band (silver-tinted obverse)
 *  - bottom disc (gold-tinted reverse photo), bottom ring face (silver-tinted reverse), bottom rim band (silver-tinted reverse)
 *  - tranche cylinder (flat silver, procedural texture deferred to 2c)
 *
 * The ring-lip groove and ring-rim step (visual flourishes that don't change
 * recognition) are deferred to Phase 2c.
 */
private fun buildCoinSubMeshes(
    engine: Engine,
    obverse: PhotoMeta,
    reverse: PhotoMeta,
    matSilverObv: MaterialInstance,
    matGoldObv: MaterialInstance,
    matSilverRev: MaterialInstance,
    matGoldRev: MaterialInstance,
    matEdge: MaterialInstance,
): List<CoinSubMesh> {
    val topZ = THICKNESS / 2f
    val ringFaceZ = topZ - RIM_HEIGHT
    val discFaceZ = ringFaceZ - RING_LIP
    val rimInner = R_OUT - RIM_WIDTH

    val botZ = -THICKNESS / 2f
    val ringFaceBotZ = botZ + RIM_HEIGHT
    val discFaceBotZ = ringFaceBotZ + RING_LIP

    return listOf(
        CoinSubMesh(buildDiscGeometry(engine, R_RING_INNER, discFaceZ, obverse, faceUp = true), matGoldObv),
        CoinSubMesh(buildAnnulusGeometry(engine, R_RING_INNER, rimInner, ringFaceZ, obverse, faceUp = true), matSilverObv),
        CoinSubMesh(buildAnnulusGeometry(engine, rimInner, R_OUT, topZ, obverse, faceUp = true), matSilverObv),
        CoinSubMesh(buildDiscGeometry(engine, R_RING_INNER, discFaceBotZ, reverse, faceUp = false), matGoldRev),
        CoinSubMesh(buildAnnulusGeometry(engine, R_RING_INNER, rimInner, ringFaceBotZ, reverse, faceUp = false), matSilverRev),
        CoinSubMesh(buildAnnulusGeometry(engine, rimInner, R_OUT, botZ, reverse, faceUp = false), matSilverRev),
        CoinSubMesh(buildEdgeCylinderGeometry(engine, R_OUT, THICKNESS), matEdge),
    )
}

/** Solid disc at [z] (triangle fan). UVs from XY via Numista photo meta. */
private fun buildDiscGeometry(
    engine: Engine,
    radius: Float,
    z: Float,
    meta: PhotoMeta,
    faceUp: Boolean,
): Geometry {
    val vertices = ArrayList<Geometry.Vertex>(FACE_SEGMENTS + 2)
    val indices = ArrayList<Int>(FACE_SEGMENTS * 3)
    val normal = if (faceUp) Float3(0f, 0f, 1f) else Float3(0f, 0f, -1f)

    vertices += vertex(0f, 0f, z, normal, meta)
    for (i in 0..FACE_SEGMENTS) {
        val t = i.toFloat() / FACE_SEGMENTS * 2f * PI.toFloat()
        vertices += vertex(cos(t) * radius, sin(t) * radius, z, normal, meta)
    }
    for (i in 1..FACE_SEGMENTS) {
        if (faceUp) {
            indices += 0; indices += i; indices += i + 1
        } else {
            indices += 0; indices += i + 1; indices += i
        }
    }
    return Geometry.Builder(RenderableManager.PrimitiveType.TRIANGLES)
        .vertices(vertices)
        .indices(indices)
        .build(engine)
}

/** Annulus between [rIn] and [rOut] at [z]. */
private fun buildAnnulusGeometry(
    engine: Engine,
    rIn: Float,
    rOut: Float,
    z: Float,
    meta: PhotoMeta,
    faceUp: Boolean,
): Geometry {
    val vertices = ArrayList<Geometry.Vertex>((FACE_SEGMENTS + 1) * 2)
    val indices = ArrayList<Int>(FACE_SEGMENTS * 6)
    val normal = if (faceUp) Float3(0f, 0f, 1f) else Float3(0f, 0f, -1f)

    for (i in 0..FACE_SEGMENTS) {
        val t = i.toFloat() / FACE_SEGMENTS * 2f * PI.toFloat()
        val cx = cos(t)
        val sx = sin(t)
        vertices += vertex(cx * rIn, sx * rIn, z, normal, meta)
        vertices += vertex(cx * rOut, sx * rOut, z, normal, meta)
    }
    for (i in 0 until FACE_SEGMENTS) {
        val a = i * 2
        val b = a + 1
        val c = a + 2
        val d = a + 3
        if (faceUp) {
            indices += a; indices += b; indices += c
            indices += b; indices += d; indices += c
        } else {
            indices += a; indices += c; indices += b
            indices += b; indices += c; indices += d
        }
    }
    return Geometry.Builder(RenderableManager.PrimitiveType.TRIANGLES)
        .vertices(vertices)
        .indices(indices)
        .build(engine)
}

/** Open cylinder for the tranche. Default cylindrical UV mapping. */
private fun buildEdgeCylinderGeometry(engine: Engine, radius: Float, height: Float): Geometry {
    val vertices = ArrayList<Geometry.Vertex>((EDGE_SEGMENTS + 1) * 2)
    val indices = ArrayList<Int>(EDGE_SEGMENTS * 6)
    val zTop = height / 2f
    val zBot = -height / 2f

    for (i in 0..EDGE_SEGMENTS) {
        val u = i.toFloat() / EDGE_SEGMENTS
        val t = u * 2f * PI.toFloat()
        val cx = cos(t)
        val sx = sin(t)
        val normal = Float3(cx, sx, 0f)
        vertices += Geometry.Vertex(
            position = Float3(cx * radius, sx * radius, zBot),
            normal = normal,
            uvCoordinate = Float2(u, 0f),
            color = WHITE,
        )
        vertices += Geometry.Vertex(
            position = Float3(cx * radius, sx * radius, zTop),
            normal = normal,
            uvCoordinate = Float2(u, 1f),
            color = WHITE,
        )
    }
    for (i in 0 until EDGE_SEGMENTS) {
        val a = i * 2
        val b = a + 1
        val c = a + 2
        val d = a + 3
        indices += a; indices += c; indices += b
        indices += b; indices += c; indices += d
    }
    return Geometry.Builder(RenderableManager.PrimitiveType.TRIANGLES)
        .vertices(vertices)
        .indices(indices)
        .build(engine)
}

/** Construct a face vertex with XY→UV remap (cf. technical-notes.md). */
private fun vertex(x: Float, y: Float, z: Float, normal: Float3, meta: PhotoMeta): Geometry.Vertex {
    val u = meta.cxUv + (x / R_OUT) * meta.radiusUv
    val v = meta.cyUv + (y / R_OUT) * meta.radiusUv
    return Geometry.Vertex(
        position = Float3(x, y, z),
        normal = normal,
        uvCoordinate = Float2(u, v),
        color = WHITE,
    )
}
