# Brainstorm follow-up : améliorer le calcul de cousinage entre pièces

> Prompt à coller en début d'une nouvelle session Claude Code. Self-contained.

## Contexte
Sur `/confusion` (admin), on calcule le "cousinage" visuel entre pièces avec **DINOv2 ViT-S/14 (ImageNet-pretrained)**. C'est un encoder a-priori (pas spécifique aux pièces). Investigation du 2026-04-28 a révélé que **Dino gonfle massivement les similarités sur les pièces euro** :

- Distribution des `nearest_similarity` sur 557 pièces mappées :
  - p10 = 0.768
  - p25 = 0.807
  - p50 = 0.852
  - p75 = 0.885
  - p90 = 0.910
- Cluster ultra-tight entre 0.80 et 0.90.
- Cause : toutes les 2€ partagent forme circulaire, anneau d'étoiles, palette de couleurs métal. Dino "voit" la même chose.

Conséquences pratiques :
1. Les seuils fixes (0.70/0.85) mettent 51% des paires en "red" → triage useless.
2. On a basculé sur **percentile-based** (bottom 25% green / mid 50% orange / top 25% red) en quick-fix — ça calibre mais ne règle pas le fond.
3. Les top-red pairs sont DOMINÉES par les ré-éditions de pièces standards (ie-2002 ↔ ie-2007 sim 0.978 etc.), ce qui est cohérent (ces pièces sont *vraiment* quasi-pixel-identiques) mais **pas la bonne info** pour identifier les pièces commémoratives qui se ressemblent visuellement.

## Question de fond à brainstormer

**Quel encoder utiliser pour calculer le cousinage entre pièces euro ?**

### Pistes à explorer

**P1 — DINOv2 fine-tuned sur pièces.** Prendre DINOv2 et fine-tune avec self-supervised contrastive sur ~5000 images pièces (du catalog + crawl Numista). Coûteux (GPU temps), mais l'encoder devient sensible aux *différences* internes entre pièces.

**P2 — Réutiliser l'encoder ArcFace post-training.** Une fois qu'on a entraîné ArcFace sur N classes, l'embedder ResNet-50 produit des embeddings discriminants entre classes. Les utiliser pour calculer la similarité *a posteriori* (entre deux classes déjà apprises). Limitation : ne couvre que les pièces déjà dans le training set.

**P3 — Combo : Dino pour bootstrap, ArcFace pour les classes connues.** Dual-source confusion map :
- Pour pièces non-trained : Dino similarity (a priori)
- Pour pièces trained : ArcFace similarity (a posteriori, bien plus précis)
- Affiche un badge dans `/confusion` indiquant la source.

**P4 — Encoder hybride : embedding Dino + embedding OCR.** Concat les deux. OCR capture les inscriptions (pays, année, theme), Dino capture la structure visuelle. Distance pondérée. Risque : OCR hard sur textes gravés.

**P5 — Triplet learning sur pairs labellisées humain.** L'admin labellise 500 paires "même design / différent design" → on entraîne un petit projecteur (MLP 128) au-dessus de Dino. Très précis mais demande du labelling manuel.

### Critères de décision

- **Coût compute** : on a un Mac M4 + 1080 Ti (cf memory user_raphael). Pas de cloud.
- **Coût data** : on a déjà 508 pièces 2€ + 49 1€ avec une image obverse. Numista a beaucoup plus mais rate-limit.
- **Maintenance** : doit re-tourner à chaque ajout de pièce au catalog (~1-2/mois).
- **Lisibilité métriques** : la similarité doit être interprétable par un humain (`0.95 = ils se ressemblent vraiment`).

### Contraintes du projet

- R0 : pas de dette technique, pas de hack
- Solo dev, app Android coin-scanner offline-first
- Le cousinage sert à 2 choses :
  1. Sélectionner les classes ArcFace à entraîner (zones green/orange/red pour stratégier le training-set)
  2. Aider l'utilisateur à comprendre pourquoi le scan se trompe (UI : "tu as scanné FR-2007 mais c'est très proche de FR-1999")

## Livrable attendu de la session

1. Décision sur l'encoder cible (P1-P5 ou autre)
2. Plan d'implémentation chiffré (jours-homme, GPU-heures)
3. Mise à jour de `docs/research/detection-pipeline-unified.md` avec la décision
4. Migration plan : comment passer de l'actuel Dino-only sans casser `/confusion`

## Fichiers clés à lire

- `ml/eval/confusion_map.py` (pipeline actuel)
- `ml/api/server.py` (endpoint /confusion exposé à l'admin)
- `admin/packages/web/src/features/confusion/composables/useConfusionMap.ts`
- `docs/research/detection-pipeline-unified.md` (architecture détection unifiée)
- Memory : `feedback_dino_thresholds.md` (le contexte qu'on vient de noter)

## Important

- **Ne pas implémenter dans cette session de follow-up** — c'est un brainstorm + plan + ADR.
- Revenir avec une recommandation argumentée, pas un menu d'options laissé à l'utilisateur.
- Le timing : pas urgent. On entraîne déjà sans avoir résolu ça (percentile thresholds + bootstrap design_group sur 2€). À faire avant de scaler à 100+ classes.
