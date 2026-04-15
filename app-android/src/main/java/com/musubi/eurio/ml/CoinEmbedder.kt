package com.musubi.eurio.ml

import android.content.Context
import android.graphics.Bitmap
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.support.common.FileUtil
import java.nio.ByteBuffer
import java.nio.ByteOrder

@Serializable
data class ModelMeta(
    val mode: String,
    val classes: List<String> = emptyList(),
    val num_classes: Int? = null,
    val embedding_dim: Int? = null,
)

/**
 * Loads the TFLite coin model and runs inference.
 * Supports both classification (outputs probabilities) and embedding modes.
 */
class CoinRecognizer(
    context: Context,
    val modelPath: String = "models/eurio_embedder_v1.tflite",
    metaPath: String = "data/model_meta.json",
) {
    private val interpreter: Interpreter
    val meta: ModelMeta
    val outputSize: Int

    // ImageNet normalization constants
    private val mean = floatArrayOf(0.485f, 0.456f, 0.406f)
    private val std = floatArrayOf(0.229f, 0.224f, 0.225f)

    init {
        val model = FileUtil.loadMappedFile(context, modelPath)
        interpreter = Interpreter(model)

        val metaJson = context.assets.open(metaPath).bufferedReader().use { it.readText() }
        meta = Json.decodeFromString<ModelMeta>(metaJson)

        val outputShape = interpreter.getOutputTensor(0).shape()
        outputSize = outputShape[1]
    }

    /**
     * Run inference on a bitmap. Returns raw model output (logits or embeddings).
     */
    fun infer(bitmap: Bitmap): FloatArray {
        val input = preprocessBitmap(bitmap)
        val output = Array(1) { FloatArray(outputSize) }
        interpreter.run(input, output)
        return output[0]
    }

    /**
     * Classify a bitmap. Returns a list of (className, probability) sorted by confidence.
     * Only valid in classify mode.
     */
    fun classify(bitmap: Bitmap): List<CoinMatch> {
        val logits = infer(bitmap)
        val probs = softmax(logits)

        return meta.classes.zip(probs.toList())
            .map { (name, prob) -> CoinMatch(name, prob) }
            .sortedByDescending { it.similarity }
    }

    private fun softmax(logits: FloatArray): FloatArray {
        val maxLogit = logits.max()
        val exps = logits.map { Math.exp((it - maxLogit).toDouble()).toFloat() }
        val sum = exps.sum()
        return exps.map { it / sum }.toFloatArray()
    }

    private fun preprocessBitmap(bitmap: Bitmap): ByteBuffer {
        val resized = Bitmap.createScaledBitmap(bitmap, 224, 224, true)
        val pixels = IntArray(224 * 224)
        resized.getPixels(pixels, 0, 224, 0, 0, 224, 224)

        val buffer = ByteBuffer.allocateDirect(1 * 3 * 224 * 224 * 4)
        buffer.order(ByteOrder.nativeOrder())

        // NCHW format
        for (c in 0..2) {
            for (y in 0 until 224) {
                for (x in 0 until 224) {
                    val pixel = pixels[y * 224 + x]
                    val value = when (c) {
                        0 -> ((pixel shr 16) and 0xFF) / 255f
                        1 -> ((pixel shr 8) and 0xFF) / 255f
                        2 -> (pixel and 0xFF) / 255f
                        else -> 0f
                    }
                    buffer.putFloat((value - mean[c]) / std[c])
                }
            }
        }

        buffer.rewind()
        return buffer
    }

    fun close() {
        interpreter.close()
    }
}
