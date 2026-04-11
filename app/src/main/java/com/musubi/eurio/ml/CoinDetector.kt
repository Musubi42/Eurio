package com.musubi.eurio.ml

import android.content.Context
import android.graphics.Bitmap
import android.graphics.RectF
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.support.common.FileUtil
import java.nio.ByteBuffer
import java.nio.ByteOrder
import android.util.Log

/**
 * Bounding box detection result from YOLOv8-nano.
 */
data class Detection(
    val bbox: RectF,
    val confidence: Float,
)

/**
 * YOLOv8-nano coin detector — detects whether there is a coin in the frame
 * and returns its bounding box.
 *
 * Input:  320×320 RGB image
 * Output: bounding boxes with confidence scores
 */
class CoinDetector(
    context: Context,
    modelPath: String = "models/coin_detector.tflite",
) {
    private val interpreter: Interpreter
    private val inputSize = 320

    init {
        val model = FileUtil.loadMappedFile(context, modelPath)
        interpreter = Interpreter(model)
    }

    /**
     * Detect coins in a bitmap. Returns the best detection above the threshold,
     * or null if no coin is found.
     *
     * Model output is [1, 5, 2100] (raw YOLOv8 without NMS):
     *   row 0 = x_center, row 1 = y_center, row 2 = width, row 3 = height, row 4 = confidence
     * Coordinates are in 320×320 pixel space.
     */
    fun detect(bitmap: Bitmap, confidenceThreshold: Float = 0.5f): Detection? {
        val input = preprocessBitmap(bitmap)

        val outputTensor = interpreter.getOutputTensor(0)
        val outputShape = outputTensor.shape() // [1, 5, 2100]
        val numChannels = outputShape[1]       // 5
        val numPredictions = outputShape[2]    // 2100

        val output = Array(1) { Array(numChannels) { FloatArray(numPredictions) } }
        interpreter.run(input, output)

        val raw = output[0] // [5][2100]
        val scaleX = bitmap.width.toFloat() / inputSize
        val scaleY = bitmap.height.toFloat() / inputSize

        // Find the detection with highest confidence
        var bestConf = 0f
        var bestIdx = -1
        for (i in 0 until numPredictions) {
            val conf = raw[4][i]
            if (conf > bestConf) {
                bestConf = conf
                bestIdx = i
            }
        }

        if (bestIdx < 0 || bestConf < confidenceThreshold) return null

        val cx = raw[0][bestIdx]
        val cy = raw[1][bestIdx]
        val w = raw[2][bestIdx]
        val h = raw[3][bestIdx]

        return Detection(
            bbox = RectF(
                (cx - w / 2) * scaleX,
                (cy - h / 2) * scaleY,
                (cx + w / 2) * scaleX,
                (cy + h / 2) * scaleY,
            ),
            confidence = bestConf,
        )
    }

    private fun preprocessBitmap(bitmap: Bitmap): ByteBuffer {
        val resized = Bitmap.createScaledBitmap(bitmap, inputSize, inputSize, true)
        val pixels = IntArray(inputSize * inputSize)
        resized.getPixels(pixels, 0, inputSize, 0, 0, inputSize, inputSize)

        // NHWC format [1, 320, 320, 3], normalized to [0, 1]
        // Each pixel: R, G, B as consecutive floats
        val buffer = ByteBuffer.allocateDirect(1 * inputSize * inputSize * 3 * 4)
        buffer.order(ByteOrder.nativeOrder())

        for (pixel in pixels) {
            buffer.putFloat(((pixel shr 16) and 0xFF) / 255f) // R
            buffer.putFloat(((pixel shr 8) and 0xFF) / 255f)  // G
            buffer.putFloat((pixel and 0xFF) / 255f)           // B
        }

        buffer.rewind()
        if (resized !== bitmap) resized.recycle()
        return buffer
    }

    fun close() {
        interpreter.close()
    }
}
