# Bench best-frame-capture — conditions standardisées

> Référence opérateur pour le protocole bench (chunk 7). La source de vérité
> côté app est `BenchProtocol.kt` (écran `/dev/bench`, protocole guidé) —
> ce fichier la documente côté PC, il ne la remplace pas.

## Les 5 conditions canoniques

| id | Setup |
|---|---|
| `bright_plain` | Lumière jour, fond uni |
| `bright_textured` | Lumière jour, fond bois ou tissu |
| `dim` | Intérieur soir, lampe loin |
| `oblique` | Caméra inclinée ~30° par rapport à la pièce |
| `glare_specular` | Lampe directe au-dessus, reflet central |

`glare_specular` remplace le `partial_shadow` de la spec d'origine
(décision `project_scan_screen_refacto` — le reflet spéculaire est le mode
d'échec réellement observé, l'ombre partielle ne l'était pas).

## Cohorte

Pas de `cohort.json` dédié : la cohorte vient de `CaptureProtocol.coins`
(le même `cohort.csv` que le flow golden-set, pushable via
`go-task android:push-capture-csv`). L'écran `/dev/bench` itère
(pièce × condition) et **auto-tague** chaque session avec `coin` et
`condition` dans le `session_start` (schema v2) — l'annotation humaine ne
porte donc plus que sur le best-frame et la confirmation d'identité.

## Boucle outillée

```
[device]  /dev/bench (protocole guidé) → sessions JSONL
   ↓ go-task android:bench:pull
ml/bench/sessions/<device>/sessions/<id>/
   ↓ go-task ml:bench:annotate            (ground_truth.json)
   ↓ go-task ml:bench:replay -- --session …  (shadow JSONL, replays/)
   ↓ go-task ml:bench:calibrate           (grid 96 configs → recommandation)
   ↓ go-task ml:bench:compare -- --run …  (rapport markdown + plots)
```

Les `replays/` et `ml/bench/reports/` sont dérivés (gitignorés) ; les
sessions et leur `ground_truth.json` sont les données primaires, trackées.

## Limites de replay (assumées)

- La **détection** n'est pas rejouable (pas de frames source full-res) — on
  replay seuils/trigger/sélection sur ce que le détecteur a vu.
- `arcface_consensus` est rejoué aux events `consensus_reached` (le
  `consensusLockedClass` n'est pas enregistré par frame).
- La composition exacte du `RollingFrameBuffer` est reconstruite (frames
  scorées, capacité `burst_size`) — approximation documentée dans
  `bench/replay.py`.
- Le re-scoring **image-level** (`vision/frame_scorer.measure_crop`) attend
  des sessions enregistrées avec `recordFramesEnabled` (JPEG q85 → léger
  biais sharpness, cf. spec chunk-7 Q1). La parité pure-math, elle, est
  verrouillée sur la session Pixel9a committée (`tests/test_frame_scorer.py`).
