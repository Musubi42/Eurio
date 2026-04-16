package com.musubi.eurio.features.catalog

/**
 * SVG path data for the 21 eurozone countries, matching vault-catalog-map.html.
 * Paths are defined in a 400×500 viewBox coordinate system.
 * Micro-states (LU, MT, CY) are rendered as pastilles with leader lines.
 */
data class CountryPath(
    val iso: String,
    val pathData: String,
    val labelX: Float,
    val labelY: Float,
    val isMicro: Boolean = false,
    val microCx: Float = 0f,
    val microCy: Float = 0f,
    val leaderFromX: Float = 0f,
    val leaderFromY: Float = 0f,
)

val EUROZONE_MAP_PATHS = listOf(
    CountryPath("IE", "M40 165 C 58 152, 84 158, 88 180 C 90 204, 74 216, 54 212 C 36 208, 28 188, 40 165 Z", 64f, 188f),
    CountryPath("PT", "M32 308 C 46 300, 62 304, 60 344 C 58 372, 40 380, 28 368 C 20 348, 22 322, 32 308 Z", 44f, 340f),
    CountryPath("ES", "M62 318 C 105 300, 150 306, 158 344 C 160 378, 132 392, 88 390 C 56 386, 48 355, 62 318 Z", 110f, 352f),
    CountryPath("FR", "M128 230 C 170 222, 200 248, 200 290 C 198 320, 168 328, 135 320 C 108 310, 100 278, 116 252 C 120 242, 124 234, 128 230 Z", 158f, 278f),
    CountryPath("NL", "M178 200 C 198 195, 212 205, 212 222 C 208 235, 194 238, 182 232 C 172 226, 170 210, 178 200 Z", 194f, 216f),
    CountryPath("BE", "M178 232 C 200 228, 215 238, 212 254 C 206 266, 190 268, 180 262 C 170 256, 168 240, 178 232 Z", 194f, 250f),
    CountryPath("DE", "M198 198 C 232 192, 262 210, 264 250 C 262 278, 230 286, 202 276 C 184 268, 180 228, 198 198 Z", 230f, 240f),
    CountryPath("IT", "M218 278 C 232 272, 246 282, 250 306 C 252 328, 244 348, 252 368 C 264 382, 278 378, 272 398 C 264 410, 250 402, 240 388 C 232 372, 228 352, 224 336 C 218 318, 206 296, 218 278 Z", 244f, 330f),
    CountryPath("AT", "M240 258 C 268 254, 288 266, 282 288 C 272 298, 250 294, 240 284 C 230 274, 230 262, 240 258 Z", 262f, 276f),
    CountryPath("SI", "M252 292 C 272 290, 282 300, 276 314 C 264 322, 248 318, 244 306 C 240 298, 246 292, 252 292 Z", 262f, 306f),
    CountryPath("HR", "M262 308 C 286 304, 300 318, 290 340 C 278 356, 262 348, 258 328 C 255 318, 258 310, 262 308 Z", 276f, 328f),
    CountryPath("SK", "M262 246 C 290 242, 308 254, 298 270 C 280 280, 258 274, 254 260 C 254 250, 258 246, 262 246 Z", 280f, 260f),
    CountryPath("EE", "M288 124 C 312 120, 326 132, 322 150 C 310 160, 290 156, 282 142 C 278 130, 284 124, 288 124 Z", 304f, 140f),
    CountryPath("LV", "M284 154 C 310 150, 326 162, 318 180 C 304 190, 284 186, 276 170 C 272 160, 278 154, 284 154 Z", 300f, 170f),
    CountryPath("LT", "M278 184 C 304 180, 320 192, 312 210 C 296 220, 276 216, 268 200 C 264 190, 272 184, 278 184 Z", 294f, 200f),
    CountryPath("FI", "M276 36 C 314 28, 332 52, 332 92 C 328 122, 312 130, 292 120 C 274 108, 264 82, 268 54 C 270 42, 272 38, 276 36 Z", 302f, 80f),
    CountryPath("GR", "M284 368 C 314 362, 334 378, 330 402 C 322 422, 300 428, 286 412 C 274 398, 274 378, 284 368 Z", 308f, 395f),
    CountryPath("BG", "M304 308 C 330 304, 348 316, 340 336 C 322 350, 298 344, 292 324 C 290 314, 298 308, 304 308 Z", 320f, 326f),
    // Micro-states rendered as pastilles
    CountryPath("LU", "", 0f, 0f, isMicro = true, microCx = 382f, microCy = 92f, leaderFromX = 202f, leaderFromY = 258f),
    CountryPath("MT", "", 0f, 0f, isMicro = true, microCx = 200f, microCy = 474f, leaderFromX = 246f, leaderFromY = 418f),
    CountryPath("CY", "", 0f, 0f, isMicro = true, microCx = 380f, microCy = 470f, leaderFromX = 332f, leaderFromY = 408f),
)

const val MAP_VIEWBOX_WIDTH = 400f
const val MAP_VIEWBOX_HEIGHT = 500f
