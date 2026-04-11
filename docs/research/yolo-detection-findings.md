# YOLO Detection — Findings & Next Steps

> Date : 2026-04-10. Premier test en conditions réelles sur Pixel 9a.

---

## Résultats du training

| Métrique | Valeur |
|---|---|
| mAP@50 | 99.5% |
| Precision | 99.7% |
| Recall | 100% |
| Training time | 2h (150 epochs, MPS) |
| Model size | 12 MB (float32, sans NMS) |

Les métriques de training sont excellentes. Le problème est en conditions réelles.

---

## Problèmes identifiés en conditions réelles

### 1. Faux positifs massifs

YOLO détecte des "pièces" partout : murs, écrans, bureaux, mains vides. La confiance est souvent 80-89% sur des objets qui ne sont pas des pièces.

**Cause probable** : le dataset Roboflow (~1900 images) contient surtout des photos de pièces sur des fonds variés. Le modèle a appris "détecter quelque chose au centre de l'image" plutôt que "détecter un objet rond métallique spécifique". Les 30 images négatives synthétiques ajoutées étaient trop simples (couleurs unies) par rapport au monde réel.

### 2. Bounding boxes trop grandes

Les crops font 200-280px sur un frame de 480×640 (40-50% du frame). Un vrai coin devrait occuper une fraction beaucoup plus petite du frame dans un usage normal (pièce dans la main à ~30cm).

**Cause probable** : beaucoup d'images du dataset montrent des pièces prises de très près, occupant la majorité du frame. Le modèle n'a pas appris à détecter des pièces petites dans un frame large.

### 3. Biais ArcFace vers 226447 (Kniefall)

Sur 6 captures, 5 identifient la Kniefall même quand c'est une autre pièce. La similarité est faible (58-83%), ce qui signifie que le match n'est pas vraiment bon — c'est juste que 226447 est le "moins mauvais" match par défaut.

**Cause probable** : comme YOLO crop des zones random du frame, ArcFace reçoit des images qui ne ressemblent à aucune pièce. Le centroid 226447 est peut-être le plus "générique" (closest to the mean embedding).

### 4. Export TFLite compliqué

- L'export natif Ultralytics échoue (conflits tf_keras/tensorflow/protobuf)
- L'export avec NMS intégré (onnx2tf) crash au runtime (GATHER_ND op)
- La quantification INT8 est cassée (toutes les confidences à 1.0)
- Seul le float32 sans NMS fonctionne → 12 MB au lieu de 2 MB

---

## Ce qui fonctionne bien

- **ArcFace** : quand on lui donne une vraie pièce bien croppée, l'identification est correcte (capture 115843 : Portugal à 76%)
- **L'architecture 2 modèles** : le pipeline YOLO → crop → ArcFace est correct en théorie
- **Les toggles A/B** : très utiles pour comparer les modes en temps réel
- **Le debug capture** : frame + crop + logs sauvegardés pour analyse

---

## Pistes d'amélioration pour la prochaine session

### Option A : Améliorer le dataset YOLO

1. **Ajouter des négatifs réalistes** — prendre 50-100 photos avec le Pixel de : bureau, mur, écran, main vide, porte-monnaie, objets ronds non-pièces (boutons, capuchons)
2. **Prendre des photos de pièces en conditions réelles** — pièce dans la main, sur la table avec du bruit, sous différents éclairages
3. **Ré-entraîner** avec ce dataset enrichi

### Option B : Utiliser un meilleur dataset

- Chercher un dataset de détection de pièces avec des négatifs réalistes
- Roboflow Universe a d'autres datasets (YoloCOIN, Roboflow-100 coins)
- Combiner plusieurs datasets

### Option C : Entraîner sur Roboflow (cloud)

- Upload les images annotées sur Roboflow
- Entraîner dans le cloud (GPU puissant, hyperparameter tuning automatique)
- Télécharger le modèle optimisé
- Coût : payant mais peut donner de meilleurs résultats

### Option D : Modèle pré-entraîné spécialisé

- Chercher un modèle de détection de pièces déjà entraîné et publié
- Fine-tuner sur nos images spécifiques

### Option E : Contourner YOLO temporairement

- Utiliser la détection de cercles classique (Hough Transform via OpenCV) comme pré-filtre
- Plus simple, moins de faux positifs sur des formes non-rondes
- Combinable avec YOLO : Hough confirme que c'est rond, YOLO confirme que c'est une pièce

### Recommandation

**Option A en priorité** (rapide, on maîtrise les données) + **monter le seuil à 70-75%** (quick fix immédiat). Si A ne suffit pas, explorer E (Hough Transform comme filtre complémentaire).

---

## Changements appliqués (2026-04-10)

- Seuil YOLO monté de 50% à 70%
- Capture sauvegarde maintenant le vrai frame caméra (bitmap) + le crop YOLO, pas un screenshot PixelCopy
- Logs enrichis avec bbox, crop size, frame size
- Tous les findings documentés ici
