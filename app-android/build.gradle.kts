import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
    alias(libs.plugins.kotlin.serialization)
}

val envFile = rootProject.file(".env")
val envProps = Properties().apply {
    if (envFile.exists()) envFile.inputStream().use { load(it) }
}

android {
    namespace = "com.musubi.eurio"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.musubi.eurio"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField("String", "SUPABASE_URL", "\"${envProps.getProperty("SUPABASE_URL", "")}\"")
        buildConfigField("String", "SUPABASE_ANON_KEY", "\"${envProps.getProperty("SUPABASE_ANON_KEY", "")}\"")

        // Restrict to arm64-v8a only — all modern Android phones (including Pixel 9a) use this.
        // Drops OpenCV native libs from ~120 MB (all ABIs) to ~30 MB.
        ndk {
            abiFilters.add("arm64-v8a")
        }
    }

    signingConfigs {
        // Keystore versionné dans le repo pour que les debug builds aient la
        // même signature sur toutes les machines (PC NixOS / Mac). Sans ça,
        // Gradle génère un debug.keystore par machine et `installDebug` échoue
        // avec INSTALL_FAILED_UPDATE_INCOMPATIBLE quand on push depuis une
        // machine alors que le device a déjà une version signée par l'autre.
        // Pas un risque sécurité : c'est une clé debug standard (password
        // "android"), seule la signature release/QA prod doit rester secrète.
        getByName("debug") {
            storeFile = file("keys/debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("debug")
            buildConfigField("Boolean", "IS_QA", "false")
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            buildConfigField("Boolean", "IS_QA", "false")
        }
        create("qa") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".qa"
            buildConfigField("Boolean", "IS_QA", "true")
        }
    }

    // Sprint 3 — training-pipeline cohort test app.
    // `full`       = the production app (default behavior).
    // `cohortTest` = the per-cohort scan harness, signed with the same debug
    // keystore so it cohabits with `full` on the device. Bundle (model.tflite,
    // filtered catalog, manifests) is dropped into src/cohortTest/assets/cohort_bundle/
    // by `go-task -t app-android/Taskfile.yml cohort-test:bundle`.
    flavorDimensions += "scope"
    productFlavors {
        create("full") {
            dimension = "scope"
        }
        create("cohortTest") {
            dimension = "scope"
            applicationIdSuffix = ".cohorttest"
            versionNameSuffix = "-cohorttest"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
        }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

ksp {
    // Exporte le schéma Room à chaque build → permet de diff/review les migrations
    // et de détecter les changements de schéma dans le repo.
    arg("room.schemaLocation", "$projectDir/schemas")
    arg("room.incremental", "true")
}

dependencies {
    // Compose
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")

    // CameraX
    val cameraxVersion = "1.4.1"
    implementation("androidx.camera:camera-core:$cameraxVersion")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    implementation("androidx.camera:camera-view:$cameraxVersion")

    // LiteRT (ex-TFLite) — 16KB page-size compliant
    implementation("com.google.ai.edge.litert:litert:1.4.2")
    implementation("com.google.ai.edge.litert:litert-support:1.4.2")
    implementation("com.google.ai.edge.litert:litert-gpu:1.4.2")
    implementation("com.google.ai.edge.litert:litert-gpu-api:1.4.2")

    // OpenCV — for HoughCircles fallback detection when YOLO fails on hand-held / cluttered frames.
    // Official Maven publication since OpenCV 4.9.0.
    implementation("org.opencv:opencv:4.10.0")

    // Room (SQLite)
    val roomVersion = "2.8.4"
    implementation("androidx.room:room-runtime:$roomVersion")
    implementation("androidx.room:room-ktx:$roomVersion")
    ksp("androidx.room:room-compiler:$roomVersion")
    // Migration / DAO test support — used by VaultMigrationTest (chunk-5a).
    androidTestImplementation("androidx.room:room-testing:$roomVersion")

    // Supabase
    implementation(platform("io.github.jan-tennert.supabase:bom:3.1.1"))
    implementation("io.github.jan-tennert.supabase:postgrest-kt")
    implementation("io.github.jan-tennert.supabase:auth-kt")
    implementation("io.github.jan-tennert.supabase:storage-kt")
    implementation("io.ktor:ktor-client-okhttp:3.0.3")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.8.5")

    // JSON
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // Adapts CameraX ListenableFuture<T> → suspend via .await() — needed by
    // CameraLockController.lock() (chunk-4 AE/AF/AWB lock).
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-guava:1.9.0")

    // Coil (async image loading for Compose)
    implementation("io.coil-kt:coil-compose:2.7.0")

    // EXIF metadata writer — used by ExifStripper (chunk-5b) to drop GPS
    // and device-fingerprint tags from raw JPEG inputs (out-of-pipeline
    // imports). Bitmap.compress(JPEG) already drops EXIF for the normal
    // capture path.
    implementation("androidx.exifinterface:exifinterface:1.3.7")

    // Koin (DI)
    implementation("io.insert-koin:koin-androidx-compose:4.0.0")

    // SceneView (Filament) — 3D coin viewer (cf. docs/coin-3d-viewer/porting-android.md)
    implementation("io.github.sceneview:sceneview:4.0.0")

    // Test
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}

// ── Filament material compilation ────────────────────────────────────────────
// Compile *.mat sources in src/main/materials/ to *.filamat in
// src/main/assets/materials/ via the matc binary installed by
// `go-task filament:install-matc` (cf. docs/coin-3d-viewer/porting-android.md
// D-PORT-7). Wired into preBuild so a fresh checkout that has run the install
// task gets self-contained builds.
val compileFilamentMaterials by tasks.registering(Exec::class) {
    val matc = file("${rootProject.projectDir}/tools/filament/bin/matc")
    val srcDir = file("src/main/materials")
    val outDir = file("src/main/assets/materials")
    inputs.dir(srcDir)
    outputs.dir(outDir)
    doFirst {
        if (!matc.exists()) {
            throw GradleException(
                "matc not found at $matc — run `go-task filament:install-matc` first."
            )
        }
        outDir.mkdirs()
    }
    workingDir = projectDir
    commandLine = listOf(
        "bash", "-c",
        """
        set -e
        for src in src/main/materials/*.mat; do
          [ -f "${'$'}src" ] || continue
          name=${'$'}(basename "${'$'}{src%.mat}")
          "${matc.absolutePath}" -p mobile -a opengl -o "src/main/assets/materials/${'$'}{name}.filamat" "${'$'}src"
        done
        """.trimIndent()
    )
}
tasks.named("preBuild") { dependsOn(compileFilamentMaterials) }

// ── QA fixtures ──────────────────────────────────────────────────────────────
// Copie shared/fixtures/preset-*.json → src/qa/assets/fixtures/, lus au runtime
// par MainActivity.seedFromFixture() (`assets.open("fixtures/preset-<nom>.json")`).
//
// Remplace un symlink `src/qa/assets/fixtures -> ../../../../shared/fixtures`
// (retiré le 2026-08-14) : un symlink qui sort du module casse au clone d'un
// dépôt isolé et rend le module non déplaçable. Même contrat que
// compileFilamentMaterials ci-dessus — sortie générée, gitignorée, régénérée au
// build. Cf. docs/adr/007-pas-de-split-eurio-avant-artefacts.md.
//
// `Sync` (et non `Copy`) : le dossier cible est un miroir strict de la source,
// un preset supprimé côté shared/ disparaît aussi des assets.
val syncQaFixtures by tasks.registering(Sync::class) {
    description = "Mirror shared/fixtures/preset-*.json into the QA assets"
    val srcDir = file("${rootProject.projectDir}/shared/fixtures")
    doFirst {
        if (!srcDir.isDirectory) {
            throw GradleException(
                "shared/fixtures introuvable à $srcDir — le module attend le monorepo. " +
                    "Si app-android est extrait un jour, remplacer cette tâche par une " +
                    "dépendance au package de tokens/fixtures publié (ADR-007)."
            )
        }
    }
    from(srcDir) { include("preset-*.json") }
    into("src/qa/assets/fixtures")
}
tasks.named("preBuild") { dependsOn(syncQaFixtures) }