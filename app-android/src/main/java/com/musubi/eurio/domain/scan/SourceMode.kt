package com.musubi.eurio.domain.scan

/** Where the archived JPEG came from — feeds bench replay (chunk-7). */
enum class SourceMode(val wire: String) {
    IMAGE_CAPTURE_FULL("image_capture_full"),
    YUV_PREVIEW_FALLBACK("yuv_preview_fallback"),
}
