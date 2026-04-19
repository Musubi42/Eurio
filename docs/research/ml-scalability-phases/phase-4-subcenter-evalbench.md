# Phase 4 — Sub-center ArcFace + banc d'éval honnête

> **Objectif** : exploiter la variation intra-classe réellement apportée par les photos eBay (phase 3) via sub-center ArcFace, et surtout **construire un banc d'éval qui reflète la distribution cible** (pièces sales, tiltées, mauvais éclairage, en main), pour arrêter de mesurer R@1=100% en labo et savoir ce que le modèle vaut **en vrai**.

## Pourquoi cette phase après l'enrichissement eBay

- Sub-center ArcFace **n'invente pas** de variation : il accommode celle qui existe dans le training set. Avant phase 3 (1 seule image Numista + aug synthétique), activer sub-center n'aurait aucun effet positif (k sous-centres convergent ou splittent sur des artefacts).
- Après phase 3, on a de vraies photos avec variations authentiques (angle, éclairage, usure) → sub-center peut enfin jouer son rôle.
- Le banc d'éval est **la pièce la plus importante de tout ce plan**. Sans banc honnête, toutes les décisions précédentes (augmentation, enrichissement) sont optimisées dans le vide. On le construit tardivement parce qu'il a besoin des photos eBay validées pour être alimenté.

## Dépendances

- Phase 3 livrée (dataset enrichi avec photos eBay validées + modèle v3 entraîné)
- Tes propres pièces (tu les as dans la main, photographiables)

## Livrables

### Partie A — Banc d'éval in-the-wild

**Le principe fondamental** : un test set doit être **disjoint** du training set, et surtout tiré de la **même distribution que l'inférence réelle** (scan user avec caméra Android, mauvaise lumière, etc.).

Le test set actuel (augmentations de Numista) n'est ni disjoint (mêmes images sources) ni représentatif (pas de vraie variation). D'où le R@1=100% optimiste.

#### 1. Test set "Raphaël collection"

- Photographie TES pièces (celles que tu possèdes physiquement) avec ton Android, dans des conditions **volontairement variées** :
  - Lumière tamisée, plein soleil, néon, led blanche
  - Fond tissu, bois, papier, main
  - Angles : parfaitement droit, tilté 15°, tilté 30°
  - Distance : proche (pièce remplit le cadre), loin (pièce au centre avec background)
  - État : propre, après manipulation (empreintes doigts), avec un peu d'eau
- Target : 5-10 photos par pièce que tu possèdes
- Stockage : `ml/data/eval_in_the_wild/{eurio_id}/{iso_date}_{condition}.jpg`
- **Ces images ne rentrent jamais dans le training set.** Gate dur.

#### 2. Test set "eBay held-out"

- Au moment de la validation en `LabelingQueuePage` (phase 3), un toggle "Marquer comme eval set" réserve l'image pour le banc d'éval au lieu du training
- Répartition visée : 80% train / 20% eval par coin
- Évite le data leakage : des photos du même vendeur/lot eBay partagent du contexte (même fond, même lumière). Si on met 4 photos d'un lot en train et 1 en eval, l'eval est trop optimiste. Donc **split par lot/seller**, pas par photo individuelle.

#### 3. Test set "confusion pairs"

- Pour chaque paire red zone identifiée en phase 1, on veut des photos des **deux** pièces dans le eval set
- Permet de mesurer spécifiquement le taux de collision sur les cas où on sait que ça peut foirer
- Si on n'a pas les deux physiquement, on mix collection perso + eBay held-out

#### 4. Vue admin `EvalBenchPage.vue`

Emplacement : `admin/packages/web/src/features/eval/pages/EvalBenchPage.vue`.

- Liste des 3 sous-benchs (collection perso / eBay held-out / confusion pairs)
- Stats de couverture : combien de coins ont des photos d'éval, combien en manquent
- Upload direct depuis l'admin (drag & drop photos perso, auto-assigné à un eurio_id)
- Bouton **"Run eval"** qui lance `ml/scripts/run_eval.py` et sort un rapport

#### 5. Rapport d'évaluation

`ml/scripts/run_eval.py` produit :
- **R@1 / R@3 / R@5 globaux** sur chaque sous-bench
- **R@1 par zone** (verte / orange / rouge)
- **R@1 par pays, par commemorative-ness, par face_value**
- **Matrice de confusion** des top 20 paires les plus confuses sur le vrai bench
- **Distribution des spreads top1-top2** (visualisation collision density)
- **Courbes precision-recall** à différents seuils de confiance

Stocké dans `ml/reports/eval_{iso_date}_{model_version}.json` + visualisation dans `EvalBenchPage`.

### Partie B — Sub-center ArcFace

#### 6. Implémentation sub-center dans la loss

Modification de `ml/training/arcface_loss.py` :

**Principe sub-center k=K** (Deng et al. 2020) :
- Au lieu d'une matrice de poids `W ∈ R^{d × N_classes}`, utiliser `W ∈ R^{d × N_classes × K}`
- Pour chaque sample, calculer les similarités avec les K sous-centres de sa classe
- **Max pooling** sur les K sous-centres → le sample s'assigne automatiquement à son sous-centre le plus proche
- Le margin angulaire est appliqué sur ce max
- Les autres sous-centres de la même classe ne sont pas pénalisés (ils peuvent drifter pour attraper d'autres variantes)
- Les sous-centres des **autres classes** restent des négatifs normaux

**Choix de K** :
- K=2 : justifié immédiatement par **avers/revers** (deux faces visuellement différentes d'une même pièce)
- K=3 : justifié par **avers / revers propre / revers usé** — mais demande assez de variation pour que les 3 sous-centres divergent
- Décision par default : **K=2** pour commencer. Passer à K=3 uniquement pour les coins zone rouge avec ≥ 5 photos validées.

Alternative à évaluer : **K variable par classe** (configurable, 1 pour zone verte, 2 pour orange, 3 pour rouge). Complexité d'implémentation mais cohérent avec la stratification.

#### 7. Test-time augmentation (TTA)

Au moment du scan, au lieu d'un seul embedding de la frame :
- Générer N versions augmentées légères de la frame (flip horizontal, ±5° rotation, crop légèrement décalé)
- Embed chacune
- Moyenne L2-normalisée des embeddings
- Matcher cette moyenne

Coût : N× latence embedding. Avec N=4 et embedding à ~50ms, on est à ~200ms, dans le budget 100ms/frame si on skip TTA sur les frames détectées non-stables. Ou : appliquer TTA uniquement sur la frame sélectionnée pour consensus final.

#### 8. Hard negative mining par zone

Modification du batch sampler :
- Probabilité accrue d'inclure, dans le même batch, des coins de la même zone rouge (paires quasi-jumelles)
- Force le modèle à voir ses négatifs les plus durs pendant l'entraînement
- Implémentation : batch composé de 60% random + 40% paires de zone rouge

#### 9. Comparaisons A/B

Entraîner 3 variantes et comparer sur le banc d'éval :
- **Baseline** : modèle v3 (fin de phase 3, ArcFace classique k=1)
- **+ sub-center K=2** : même training set, sub-center activé
- **+ sub-center K=2 + hard negative mining** : sub-center + sampler modifié

Décision de garder sub-center **uniquement si** il améliore le R@1 sur eval in-the-wild de ≥ 2 points (marge statistique raisonnable).

## Non-livrables (explicites)

- Pas de 3D (phase 5)
- Pas de changement de backbone
- Pas de changement de dimension d'embedding (on reste 256)

## Métriques de sortie

C'est **la phase où on obtient les premiers chiffres honnêtes** :
- R@1 / R@3 sur eval in-the-wild avant / après sub-center
- R@1 par zone
- Matrice de confusion réelle sur vraies photos
- Temps d'inférence mobile avec / sans TTA (sur device Android réel)

Ces chiffres deviennent le **seuil de décision produit** : à partir de quel R@1 le scan est-il acceptable pour release ? Probablement R@1 ≥ 90% global, ≥ 85% zone rouge. À définir selon l'UX cible.

## Critères de passage à la phase suivante

Phase 5 est **optionnelle** — on ne la lance que si phase 4 conclut qu'il reste :
- Des paires rouges où R@1 < 70% même après sub-center + enrichissement eBay
- Ces paires sont suffisamment nombreuses pour impacter l'UX globale (pas juste 2-3 cas tordus)

Sinon, le plan s'arrête ici et on passe en maintenance / improvement incrementale.

## Risques / points d'attention

- **Data leakage par lot eBay** : le point le plus dangereux du banc d'éval. Si on split naïvement par image au lieu de par seller/lot, l'eval est gonflé de plusieurs points. À auditer à la main sur un échantillon.
- **Sub-center overfit** : si K est trop grand pour la variation disponible, les sous-centres deviennent instables (un sous-centre par augmentation synthétique). D'où le K=2 par défaut.
- **TTA et consensus buffer** : déjà un consensus 5/3 sticky en place. TTA ajoute une autre couche de moyenne. Attention à l'interaction : TTA peut stabiliser à l'intérieur d'une frame au détriment de la réactivité du buffer. À tester en UX réelle.
- **Seuils d'acceptation du scan** à re-calibrer après phase 4 : les seuils actuels (top1 > 0.55 OU spread > 0.08 avec top1 > 0.20) ont été tunés sur 7 classes. Avec 500 classes et une vraie distribution de similarités, ils devront être refits.
- **Honnêteté du banc d'éval** : il y a toujours une tentation d'optimiser les choix jusqu'à ce que le bench monte. Contre-mesure : **garder un hold-out du hold-out** — un sous-test de 10-15% du banc qu'on ne regarde qu'une fois par mois, pour détecter l'overfitting au bench.
