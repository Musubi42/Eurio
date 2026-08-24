# Brief subagent 01 — Recherche SOTA "is_coin scoring"

## Contexte court

Pipeline crop pour pièces de monnaie (Euros 2 €) à partir de listings eBay :
YOLO11-nano → Hough → polish → crop 224×224. Le pipeline détecte trop de
cercles non-pièces (timbres, logos, watermarks) et parfois des features
intérieures d'une grande pièce (millésime gravé, anneau intérieur bimétal).

**On ne veut PAS retrain YOLO**. On cherche un **post-filter algorithmique**
qui score chaque crop "ressemble-t-il à une vraie pièce bien cadrée ?",
applicable en Python OpenCV ou avec un modèle pré-entraîné léger
(< 50 MB, CPU-friendly).

## Tu cherches

1. **Techniques classiques OpenCV** pour scorer "is this region a coin":
   - radial gradient analysis (rim metallicness)
   - texture / variance patterns sur disque vs anneau
   - color signatures (gris/argent/or/cuivre)
   - HOG, LBP, ou autre descripteur pour reconnaissance pièce
   - papiers récents (2024-2026) sur coin segmentation

2. **Modèles ML pré-entraînés** utilisables tels quels (zero-shot ou
   few-shot) :
   - CLIP / SigLIP avec prompts "a photo of a coin"
   - DINO embeddings + ancres pièces (note : on a DÉJÀ DINOv2 ViT-S/14 dans
     le projet pour autre chose, peut-être réutilisable)
   - SAM / SAM2 pour segmentation puis scoring de la mask qualité

3. **Patterns d'industrie** :
   - Comment Numista / coin recognition apps comme Coinoscope, CoinSnap
     gèrent ce filtrage
   - Datasets publics de coin detection avec labels "vrai coin" vs
     "false positive"

## Format de rendu

Écris dans `docs/crop-forensics/findings/02-sota-research.md`. Structure :

```
# Finding 02 — SOTA research is_coin scoring

## Approche A — [nom]
- Idée : 1 paragraphe
- Coût impl : low/med/high
- Coût runtime : ms/crop, MB modèle
- Évidence d'efficacité : (paper, blog, repo) avec URL
- Verdict : (à tester / à éviter / pas applicable)

## Approche B — ...
...

## Recommandation
1-2 paragraphes : laquelle/lesquelles tenter en premier, pourquoi.
```

Max 400 mots total. Pas de blabla. Cite tes sources (URLs).

## Hors scope

- Recherche YOLO fine-tuning (on ne retrain pas).
- Approches qui demandent du dataset labellisé > 1000 images.
- Solutions nécessitant GPU à l'inference.

## Limite de temps

Concis. 2-3 web searches ciblées suffisent. Pas de marathon.
