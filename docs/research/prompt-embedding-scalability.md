# Prompt — Scalabilité des embeddings ArcFace pour la reconnaissance de pièces euro

> Ce prompt est conçu pour être utilisé avec un modèle Claude (ou autre LLM) pour explorer la question de la scalabilité de notre pipeline de reconnaissance de pièces.

---

## Contexte projet

Je développe **Eurio**, une application Android de collection de pièces euro. L'acte central est le **scan** : l'utilisateur pointe sa caméra sur une pièce et l'app l'identifie.

### Pipeline de reconnaissance actuelle

1. **Détection** : YOLOv8-nano (320×320) localise la pièce dans le frame + OpenCV HoughCircles en fallback
2. **Embedding** : MobileNetV3-Small backbone (576-dim) → projection linéaire (256-dim) → L2 normalization. Le modèle est entraîné avec **ArcFace loss** (angular margin classification)
3. **Matching** : Cosine similarity entre l'embedding de la photo et des **centroïdes de référence** précalculés (1 vecteur 256-dim par design)
4. **Consensus** : Buffer de 5 frames, seuil 3/5 pour stabiliser la détection

### Ce qu'on a aujourd'hui

- **Modèle** : MobileNetV3-Small + head linéaire 576→256, exporté en TFLite (4.2 MB)
- **Entraîné sur 7 designs** avec ~60-70 images par classe (photos réelles + augmentations synthétiques depuis images Numista)
- **Augmentations** : rotation 360°, perspective, color jitter, blur, backgrounds aléatoires (bois, tissu, gradient), masque circulaire
- **Résultats actuels** : R@1 = 100%, R@3 = 100% sur 7 classes (dataset de test)
- **Seuil de décision** : top1 > 0.55 (accept seul) OU spread top1-top2 > 0.08 avec top1 > 0.20

### Le dataset cible

- **~3000 pièces euro** dans le référentiel (circulation + commémoratives, 25 pays)
- **~300-500 designs visuels distincts** (beaucoup de pièces partagent le même design sur des années différentes)
- Source d'images : principalement **scans Numista** (haute résolution, fond neutre, 1-2 images par design)

## Mes questions

### 1. Est-ce que 256 dimensions suffisent pour 300-500 classes ?

Mon intuition : 256-dim semble peu pour discriminer des centaines de designs de pièces qui partagent des caractéristiques visuelles communes (même métal, même diamètre, même style de gravure). En face recognition, ArcFace travaille typiquement en 512-dim pour des millions de visages. Mais les pièces sont un domaine plus restreint que les visages.

- Y a-t-il une règle empirique sur le ratio dimension/nombre de classes ?
- À partir de combien de classes un espace 256-dim commence à saturer ?
- Faut-il passer à 512-dim ? Quel impact sur la taille du modèle et la latence mobile ?

### 2. Risque de collision entre designs similaires

Certains designs commémoratifs sont visuellement très proches :
- Même style graphique (gravure en relief sur anneau doré)
- Même structure (portrait central + texte + étoiles EU)
- Même palette de couleurs (c'est du métal)
- Différences subtiles (un visage différent, un monument différent, mais même mise en page)

Exemples de paires potentiellement confuses :
- Deux commémoratives françaises avec des personnages historiques
- Les pièces "standard" de pays voisins (Belgique/Luxembourg par exemple)
- Les émissions communes (même design, pays différents — comme les commémoratives du Traité de Rome)

Comment ArcFace gère-t-il les classes visuellement proches ? Le margin angulaire suffit-il ?

### 3. One-shot / few-shot à l'échelle

Aujourd'hui, pour chaque design, je n'ai que **1-2 images Numista** (scan studio) + **50 augmentations synthétiques**. Pour 500 classes, ça donne :
- 500 × 50 = 25 000 images train (augmentées)
- Mais seulement 500 images réelles distinctes

Est-ce suffisant pour un modèle ArcFace ? Le backbone MobileNetV3-Small est-il assez expressif, ou faut-il un backbone plus gros (MobileNetV3-Large, EfficientNet-B0) ?

### 4. Alternatives architecturales à considérer

- **Embedding plus grand** (512 ou 1024-dim) : impact perf mobile ?
- **Backbone plus gros** : MobileNetV3-Large, EfficientNet-B0/B1, ou un ViT petit ?
- **Hierarchical matching** : d'abord identifier le pays/type, puis le design exact ?
- **Hard negative mining** : ArcFace fait-il assez de séparation, ou faut-il des stratégies de mining spécifiques pour les pièces similaires ?
- **Sub-center ArcFace** : pour gérer les variations intra-classe (pièce neuve vs usée) ?
- **Test-time augmentation** : moyenner les embeddings de plusieurs crops/rotations au scan ?

### 5. Métriques à surveiller

Quelles métriques devrais-je tracker pour détecter les problèmes avant qu'ils deviennent critiques en production ?
- R@1 / R@3 / R@5 par pays ? Par type (circulation vs commémo) ?
- Matrice de confusion ? Pairs les plus confus ?
- Distribution des cosine similarities (spread top1-top2) ?

## Contraintes techniques

- **Mobile-first** : le modèle tourne sur Android (min API 26), TFLite, CPU/GPU mobile
- **Latence cible** : < 100ms par inference (embedding seul, sans détection)
- **Taille modèle** : actuellement 4.2 MB (TFLite), ne devrait pas dépasser ~15 MB
- **Batterie** : le scan est continu (analyse de frames), donc la consommation compte
- **Offline** : tout le matching est local, pas de round-trip serveur

## Ce que j'attends

1. Une analyse de la viabilité de l'architecture actuelle (256-dim ArcFace + MobileNetV3-Small) pour 500+ classes
2. Des recommandations concrètes sur les changements à apporter (dimension, backbone, loss function, matching strategy)
3. Un plan d'expérimentation : quelles expériences mener pour valider avant de s'engager dans un changement d'architecture
4. Des signaux d'alarme : à quoi ressemble un espace d'embeddings qui commence à saturer, et comment le détecter tôt
