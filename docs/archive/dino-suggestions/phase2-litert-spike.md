# Spike — dinov2_vits14 → LiteRT

- ai-edge-torch + ai-edge-litert, torch 2.9.1, input 224×224, batch 1 (comme on-device)
- Parité mesurée sur crops réels du set labellisé ; accord top1 contre la banque vits14 `2eur_commemo` (508 ancres).
- Latence = médiane CPU 4 threads sur cette machine (PROXY — la latence device réelle se mesure dans l'APK).

- Crops de test : 24
- Bake pos_embed 518→224 : cosine vs original min=1.000000 mean=1.000000 (attendu ≈ 1.0)

| Variante | taille | cosine vs eager (min / mean) | top1 == eager | latence CPU (médiane) |
|---|---|---|---|---|
| fp32 | 86.7 MB | 1.0000 / 1.0000 | 24/24 | 56 ms |
| int8-dynamic | 22.8 MB | 0.9666 / 0.9869 | 21/24 | 36 ms |
| fp16 | 43.5 MB | 1.0000 / 1.0000 | 24/24 | 58 ms |

Fichiers : `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/output/spike/dinov2_vits14_emb_<variante>.tflite`
