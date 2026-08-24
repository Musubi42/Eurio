# Bench students ArcFace — lecture (2026-06-11)

> Interprétation de `phase2-student-bench.md` (généré par
> `scripts/bench_encoder_dino.py`, re-runnable). 10 backbones zero-shot sur
> le set labellisé review (604 crops — le set a grossi depuis l'audit du
> matin à 478, les reviews continuent) contre les 546 ancres `2eur_all`.

## Verdict : le pré-entraînement DINOv2 EST l'avantage, pas la taille

| Modèle (≈ même taille) | M params | pays@1 | pays@5 |
|---|---|---|---|
| **dinov2_vits14** | 22.1 | **70.8 %** | **87.9 %** |
| tiny_vit_21m (distillé in22k) | 20.6 | 43.2 % | 69.1 % |
| repvit_m2_3 (mobile, distillé) | 22.4 | 30.9 % | 60.4 % |

À taille de modèle ÉGALE (~21 M), vits14 met **+28 points de pays@1** au
meilleur candidat supervisé ImageNet. Tous les backbones mobiles classiques
(TinyViT, EfficientFormer, MobileViT, RepViT, ConvNeXtV2, MobileNetV4)
s'effondrent sur les euros — l'architecture n'explique rien (le pire est un
conv 31 M à 384px), c'est le pré-entraînement self-supervised LVD-142M de
DINOv2 qui voit les micro-différences entre avers.

Échelle complète DINOv2 (cohérente, même protocole) :
vits14 70.8 % → vitb14 79.8 % (86 M) → vitl14 89.1 % (304 M, mesure du matin
sur 478 crops) en pays@1.

## Décision recommandée pour le student ArcFace on-device

**Fine-tuner `dinov2_vits14` + tête ArcFace (label = design_group).**

- 22 M params ≈ 22–44 Mo (int8/fp16) — dans l'épure APK ; 29 ms/img sur M4
  MPS, ordre de grandeur OK pour le scan avec le buffer consensus 5/3.
- Un écart zero-shot de 28 pts à taille égale ne se rattrape pas au
  fine-tune ; partir d'un backbone ImageNet serait un handicap structurel.
- Caveat honnête : le zero-shot avantage DINOv2 par construction (features
  self-supervised mieux « prêtes à l'emploi ») — mais la littérature
  retrieval fine-grained va dans le même sens, et l'écart est trop grand
  pour parier l'inverse.
- vitb14 (86 M, 79.8 %) = plan B si le téléphone encaisse ~90–170 Mo et la
  latence ; à ne considérer qu'après mesure réelle on-device.

## Spike LiteRT — FAIT, bloquant levé (2026-06-11)

`scripts/spike_vits14_litert.py` → `phase2-litert-spike.md` (re-runnable),
artefacts dans `ml/output/spike/`.

| Variante | taille | parité vs eager | latence CPU M4 (proxy) |
|---|---|---|---|
| fp32 | 86.7 MB | cosine 1.0000, top1 24/24 | 56 ms |
| **fp16** | **43.5 MB** | **cosine 1.0000, top1 24/24** | 58 ms |
| int8-dynamic | 22.8 MB | cosine min 0.9666, top1 21/24 | 36 ms |

- **Le piège était le pos_embed** : checkpoint à 518px (1370 tokens),
  interpolé en bicubique à chaque forward → chemin dynamique inexportable.
  Solution : pré-calcul à 224 via `interpolate_pos_encoding` du modèle
  lui-même — équivalence numérique exacte (cosine 1.000000 en eager).
- **Artefact recommandé : fp16 (43.5 MB, lossless en pratique).**
  L'int8 dynamique fait basculer 3 top1 sur 24 — trop risqué pour du
  ranking fine-grained sans calibration ; un int8 STATIQUE (PT2E +
  calibration sur crops réels) reste la piste si les 43 Mo gênent.
- Le module exporté inclut la L2-normalisation (sortie prête pour le
  dot-product côté Kotlin, même contrat que la banque d'ancres).
- Piège d'API : `ai_edge_torch` est un shim déprécié → `litert_torch`,
  et les converter flags se passent en dict IMBRIQUÉ
  (`{"target_spec": {"supported_types": [tf.float16]}}`), une clé pointée
  est silencieusement ignorée.
- Latence : 56-58 ms sur M4 CPU = proxy ; sur téléphone milieu de gamme
  compter 2-4× en CPU, delegates GPU/NNAPI à évaluer dans l'APK. Avec le
  buffer consensus 5/3 à quelques fps, l'épure tient.

## Étapes suivantes proposées

1. ~~Spike conversion vits14 → LiteRT~~ **FAIT** — reste la mesure de
   latence réelle dans l'APK (harness scan existant).
2. Fine-tune ArcFace de vits14 (design_group), éval sur set review (script
   audit) + cohorte device en hold-out (doctrine bench). Re-baker le
   pos_embed et ré-exporter après fine-tune (même recette).
3. Optionnel : distillation d'embeddings vitl14 → vits14 sur le corpus de
   crops (sans labels) avant la tête ArcFace — cumule teacher fort + student
   embarquable.
4. Si la taille APK gêne : int8 statique PT2E calibré sur crops réels
   (viser parité top1 ≥ 23/24 avant d'adopter).
