# ADR-001 — LiteRT 1.4.2 au lieu de TensorFlow Lite 2.16.1

**Date :** 2026-04-09
**Statut :** Acceptée

## Contexte

Le Pixel 9a sous Android 15 exige des bibliothèques natives alignées sur des pages de 16 KB. À partir de novembre 2025, Google Play rejette les APK non-conformes ciblant Android 15+.

Les `.so` de TensorFlow Lite 2.16.1 (`libtensorflowlite_jni.so`, `libtensorflowlite_gpu_jni.so`) ont des segments LOAD alignés sur 4 KB.

## Décision

Utiliser **LiteRT 1.4.2** (`com.google.ai.edge.litert`) au lieu de TensorFlow Lite (`org.tensorflow:tensorflow-lite`).

LiteRT est le rebranding officiel de TFLite par Google. La série 1.x est un drop-in replacement : mêmes imports (`org.tensorflow.lite.*`), même API `Interpreter`.

## Alternatives considérées

| Option | Verdict |
|---|---|
| TFLite 2.16.1 + repackaging `.so` | Fragile, non maintenu |
| LiteRT 2.x (CompiledModel API) | API différente, migration lourde, bug 16KB dans 2.1.0-2.1.1 |
| **LiteRT 1.4.2** | Drop-in, 16KB fixé depuis 1.4.0 |

## Conséquences

- Aucun changement de code nécessaire (imports identiques)
- Dépendances Gradle changées (4 artifacts au lieu de 3)
- GPU delegate nécessite `litert-gpu` + `litert-gpu-api`
