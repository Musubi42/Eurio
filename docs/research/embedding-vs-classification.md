# Embedding vs Classification — Analyse de la décision architecturale

> Décision prise : **Embedding matching** pour Eurio.  
> Ce document explique pourquoi et dans quels cas cette décision pourrait être revue.

---

## 1. Les deux approches

### Classification (softmax)

Le modèle apprend à répondre : "cette image appartient à la classe N parmi 500 classes possibles."

```
Image → MobileNetV3 → Couche softmax (500 neurones) → "Classe 347 à 94%"
```

- La dernière couche a exactement N neurones (1 par pièce connue)
- Ajouter une pièce = ajouter un neurone = **re-trainer le modèle entier**
- Le modèle est dans l'APK → mise à jour de l'app nécessaire

### Embedding matching (metric learning)

Le modèle apprend à répondre : "voici la signature visuelle de cette image" (un vecteur de nombres). On compare ensuite cette signature avec une base de référence.

```
Image → MobileNetV3 → Embedding [0.023, -0.145, ...] (256 dims)
                          ↓
                    Cosine similarity vs base
                          ↓
                    "Ressemble à 94% à la pièce X"
```

- Le modèle produit toujours un vecteur de taille fixe (256 dims)
- Ajouter une pièce = calculer son embedding + l'ajouter à la base
- **Aucun re-training nécessaire**

---

## 2. Comparaison détaillée

| Critère | Classification | Embedding |
|---|---|---|
| Précision brute | Légèrement supérieure (~2-3%) | Très bonne |
| Ajout d'une pièce | Re-training complet (~30 min) | Calcul d'1 embedding (~1 seconde) |
| Mise à jour app | Oui (nouveau .tflite) | Non (sync JSON via API) |
| Nombre d'images minimum / nouvelle pièce | 50-100 | **1 seule** (idéalement 3-5) |
| Day Zero pour nouvelles pièces | Impossible sans re-training | **Automatisable** via cron |
| Scalabilité (500 → 5000 pièces) | Modèle plus gros, re-training plus long | Même modèle, JSON plus gros |
| Complexité d'entraînement | Simple (cross-entropy loss) | Moyenne (triplet loss + mining) |
| Taille embarquée | ~2.5 MB (modèle) | ~2.5 MB (modèle) + ~500 KB (base) |
| Inférence | ~5ms | ~5ms + ~2ms comparaison |

---

## 3. Pourquoi embedding est le bon choix pour Eurio

### Raison 1 — Le catalogue est vivant

La zone euro produit ~15-20 nouvelles commémoratives par an. Chaque nouvelle pièce doit être reconnaissable rapidement. Avec la classification, chaque ajout est un cycle re-training + release. Avec l'embedding, c'est un push de données.

### Raison 2 — Le problème du cold start

Les nouvelles pièces n'ont que 1-3 images officielles au moment de leur annonce. La classification a besoin de 50-100 images par classe pour être fiable. L'embedding fonctionne avec 1 image (et s'améliore avec plus).

### Raison 3 — Maintenance solo developer

Raphaël est seul. Un pipeline qui nécessite un re-training manuel à chaque nouvelle pièce ne scale pas. L'embedding permet une automatisation complète : cron → Numista → embedding → Supabase → app.

### Raison 4 — Les pièces sont des objets idéaux pour l'embedding

Les pièces ont des designs distincts, une forme constante (disque), et des variations limitées (usure, éclairage). Le cosine similarity sur des embeddings fonctionne particulièrement bien dans ce cas car les différences intra-classe (même pièce, conditions différentes) sont petites par rapport aux différences inter-classes (pièces différentes).

---

## 4. Triplet Loss vs autres méthodes de metric learning

### Triplet Loss (retenu)

```
Triplet = (anchor, positive, negative)
Loss = max(0, d(anchor, positive) - d(anchor, negative) + margin)
```

- Intuitif et bien documenté
- Fonctionne bien avec pytorch-metric-learning
- Hard mining améliore significativement la convergence
- Margin = 0.2 est un bon point de départ

### Alternatives considérées

| Méthode | Avantage | Inconvénient | Verdict |
|---|---|---|---|
| Contrastive Loss | Plus simple (paires, pas triplets) | Moins discriminant | Correct pour démarrer |
| ArcFace / CosFace | Meilleure séparation des classes | Plus complexe, besoin de plus de data | Overkill pour le POC |
| NT-Xent (SimCLR) | Self-supervised, pas besoin de labels | Besoin de beaucoup de data | Pas adapté au few-shot |

**Décision** : Triplet Loss avec hard mining. Simple, efficace, bien supporté par les librairies.

---

## 5. Seuils de confiance

La cosine similarity retourne une valeur entre -1 et 1 (en pratique entre 0 et 1 pour des embeddings normalisés).

| Similarity | Interprétation | Action dans l'app |
|---|---|---|
| > 0.90 | Match quasi certain | Affichage direct de la fiche pièce |
| 0.75 — 0.90 | Probable mais incertain | Affichage top 3 suggestions avec "Est-ce cette pièce ?" |
| < 0.75 | Pas de match fiable | "Pièce non identifiée" avec valeur faciale détectée |

Ces seuils devront être calibrés empiriquement sur des données réelles. Le risque principal est le faux positif (afficher avec confiance une mauvaise pièce) — d'où un seuil de match direct volontairement élevé (0.90).

---

## 6. Quand reconsidérer cette décision

L'embedding matching pourrait être remplacé par de la classification si :

- Le catalogue se stabilise (pas de nouvelles pièces fréquentes) — peu probable
- La précision de l'embedding est significativement inférieure en production — à surveiller
- Le nombre de pièces dépasse 10 000+ et la comparaison cosine devient lente — résolvable avec ANN (Approximate Nearest Neighbors)

Pour le moment et le futur prévisible, **l'embedding est la bonne architecture**.
