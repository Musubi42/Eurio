# Coin Detection — Research & Strategy

> Date : 2026-04-10. Recherche approfondie sur les modeles, datasets et techniques de detection de pieces.

---

## Contexte

Notre YOLOv8-nano (12 MB, float32) obtient 99.5% mAP en validation mais genere des faux positifs massifs en conditions reelles. Ce document synthetise la recherche pour trouver la meilleure approche.

### Use case cible

L'utilisateur pointe sa camera sur une piece et l'app la detecte automatiquement (style Yuka/QR scanner). La piece peut etre :
- Tenue entre les doigts (bords partiellement masques)
- Posee sur du tissu/coton (bords flous)
- Mal eclairee, en angle, partiellement visible
- Sur une table, dans la main, sur n'importe quel fond

### Contraintes

- **100% on-device** (pas de serveur, souverainete des donnees)
- **Taille du modele** < 15 MB idealement (app store friendly)
- **Latence** < 300ms par frame (scan continu temps reel)
- **Android TFLite** comme runtime

---

## 1. Comparatif des modeles

### Point cle : la taille du modele depend de l'architecture, PAS du dataset

Le nombre d'images d'entrainement ou de classes n'affecte PAS la taille du modele final. Un YOLO-nano entraine sur 100 images fait la meme taille qu'entraine sur 100 000 images.

### Modeles YOLO (detection)

| Modele | Params | FLOPs | mAP COCO | CPU ONNX | TFLite float32 (est.) |
|---|---|---|---|---|---|
| **YOLOv8-nano** | 3.2M | 8.7B | 37.3 | 80ms | ~12 MB |
| **YOLO11-nano** | 2.6M | 6.5B | 39.5 | 56ms | ~10 MB |
| **YOLO26-nano** | 2.4M | 5.4B | 40.9 | 39ms | ~9 MB |
| YOLOv8-small | 11.2M | 28.6B | 44.9 | 128ms | ~43 MB |
| YOLO11-small | 9.4M | 21.5B | 47.0 | 90ms | ~36 MB |
| YOLO26-small | 9.5M | 20.7B | 48.6 | 87ms | ~36 MB |

**YOLO26-nano est le meilleur choix** :
- 25% moins de params que YOLOv8-nano
- +3.6 points de mAP
- 2x plus rapide sur CPU
- Concu pour le edge deployment
- Quantization-friendly (FP16/INT8)

### RF-DETR (alternative transformer-based)

| Modele | Params | mAP COCO | Latence T4 |
|---|---|---|---|
| RF-DETR-nano | 30.5M | 48.4 | 2.3ms GPU |
| RF-DETR-small | 32.1M | 53.0 | 3.5ms GPU |

**Elimine pour notre cas** : RF-DETR-nano a 30M params (~120 MB), 12x plus gros que YOLO26-nano. Excellentes performances sur GPU mais trop lourd pour du TFLite on-device sur mobile.

### Concurrence : CoinDetect

[CoinDetect](https://coindetect.com/) est l'app la plus proche de notre concept :
- ~300 types de pieces Euro (dont 2EUR commemoratives)
- Precision 97-99%
- **Server-side** : les images sont envoyees au serveur pour analyse
- Notre avantage : 100% on-device, pas de dependance serveur, donnees privees

---

## 2. Datasets disponibles

### Datasets Roboflow pour la detection de pieces

| Dataset | Images | Classes | Notes |
|---|---|---|---|
| [Euro-Coin-Detection (OwnSoft)](https://universe.roboflow.com/ownsoft-technologies/euro-coin-detection) | 461 | Euro coins | Le plus pertinent, CC BY 4.0, annotations YOLO-ready |
| [YoloCOIN](https://universe.roboflow.com/yolocoin/coin-gva2j) | 826 | 20 classes multi-devises | Plus de volume, pre-trained model dispo |
| [Coin Counter (GE)](https://universe.roboflow.com/ge-roboflow-yolov8/coin-counter-5uuip) | 239 | coins | Mis a jour fev 2026 |
| [Euro coin dataset (GitHub)](https://github.com/SuperDiodo/euro-coin-dataset) | ~200+ | 8 denominations Euro | Raw images, pas d'annotations |

### Dataset du paper YOLOv11 (MDPI sept 2025)

[Paper : Real-Time Identification of Mixed and Partly Covered Foreign Currency](https://www.mdpi.com/2673-2688/6/10/241)

- 46 classes (USD, EUR, CNY, KRW — pieces + billets)
- **200 images par classe = 9200 images** total
- Sources : Kaggle, Google Images, collections perso
- Cas inclus : **overlap, pliage, couverture partielle**
- Augmentation : rotation, flip, brightness
- Labeling sur Roboflow
- Compare SSD, RetinaNet, YOLOv8, YOLOv11 → **YOLOv11 gagne**
- Pipeline hybride TFLite on-device + server optionnel

### Projet GitHub

- [Euro-Coin-Detection YOLOv5](https://github.com/Tanwar-12/Euro-Coin-Detection) — projet complet
- [CV-coins-project](https://github.com/iambarge/CV-coins-project) — approche CV pure pour Euro

---

## 3. Techniques pour reduire les faux positifs

### Hard negative mining (recommande par Ultralytics)

Source : [ultralytics/ultralytics#5044](https://github.com/ultralytics/ultralytics/issues/5044), [Tips for best training](https://docs.ultralytics.com/yolov5/tutorials/tips_for_best_training_results/)

**Principe** : ajouter des images "background" (sans pieces) au dataset pour apprendre au modele ce qui n'est PAS une piece.

**Implementation** :
```
images/train/
  coin_001.jpg
  coin_002.jpg
  background_001.jpg    # photo de bureau, mur, ecran...
  background_002.jpg

labels/train/
  coin_001.txt          # contient les bounding boxes
  coin_002.txt
  background_001.txt    # FICHIER VIDE
  background_002.txt    # FICHIER VIDE
```

**Ratio recommande** : 1-10% d'images background (COCO utilise ~1%). Pour notre cas avec beaucoup de faux positifs, viser 10%.

**Recommandation** : telecharger des images de fond realistes (bureaux, mains, ecrans) plutot que les prendre manuellement. Des datasets comme COCO ont deja des milliers d'images de scenes interieures.

### Augmentation pour l'occlusion

Le paper YOLOv11 utilise :
- Rotation, flipping
- Ajustements de luminosite
- Images avec pieces partiellement couvertes/chevauchees
- Conditions reelles variees

### Best practices Ultralytics

- >= 1500 images par classe (ideal)
- >= 10 000 instances labellees par classe (ideal)
- Entrainer a la resolution de deploiement (320px pour nous)
- >= 300 epochs, plus gros batch size possible
- Cosine LR scheduler (`--cos-lr`)
- Mosaic augmentation (desactiver les 10 derniers epochs)

---

## 4. Strategie recommandee

### Phase 1 : Quick upgrade — YOLO26-nano + dataset combine

1. **Telecharger** le dataset OwnSoft Euro (461 images) + YoloCOIN (826 images)
2. **Mapper** toutes les classes vers une seule classe "coin"
3. **Ajouter ~100-200 images background** (depuis COCO ou scenes interieures)
4. **Entrainer YOLO26-nano** (au lieu de YOLOv8-nano) sur ce dataset combine
5. **Exporter TFLite** float32 (~9 MB) ou float16 (~4.5 MB)
6. **Tester** sur le Pixel avec le systeme de debug capture

### Phase 2 : Si Phase 1 insuffisante — dataset enrichi

1. Ajouter les images de fond qui generent encore des faux positifs (a partir des captures debug)
2. Ajouter des images de pieces dans des conditions difficiles (doigts, tissu, angle)
3. Explorer le dataset du paper YOLOv11 (si disponible)
4. Re-entrainer

### Phase 3 : Optimisation finale

1. **Float16 quantization** pour reduire la taille (~4.5 MB)
2. **INT8 quantization** si faisable (~2.5 MB)
3. Tuning du seuil de confiance
4. Test A/B YOLO26-nano vs YOLO11-nano

---

## 5. Questions ouvertes

- [ ] Le dataset OwnSoft contient quelles conditions exactement ? (fonds, eclairage, angles)
- [ ] YOLO26 export TFLite fonctionne-t-il out-of-the-box avec Ultralytics ?
- [ ] Peut-on entrainer sur Roboflow cloud directement avec YOLO26 ?
- [ ] Le dataset du paper YOLOv11 est-il en open access ?
- [ ] Performance reelle de YOLO26-nano sur Pixel 9a (vs YOLOv8-nano actuel) ?

---

## Sources

- [Ultralytics YOLO26 vs YOLOv8](https://docs.ultralytics.com/compare/yolov8-vs-yolo26/)
- [Ultralytics YOLO11 vs YOLOv8](https://docs.ultralytics.com/compare/yolov8-vs-yolo11/)
- [RF-DETR GitHub](https://github.com/roboflow/rf-detr)
- [Tips for best training results](https://docs.ultralytics.com/yolov5/tutorials/tips_for_best_training_results/)
- [Hard negative mining for YOLO](https://github.com/ultralytics/ultralytics/issues/5044)
- [YOLOv11 currency detection paper](https://www.mdpi.com/2673-2688/6/10/241)
- [CoinDetect app](https://coindetect.com/)
- [Euro-Coin-Detection dataset](https://universe.roboflow.com/ownsoft-technologies/euro-coin-detection)
- [YoloCOIN dataset](https://universe.roboflow.com/yolocoin/coin-gva2j)
- [Euro coin dataset GitHub](https://github.com/SuperDiodo/euro-coin-dataset)
- [Best mobile detection models](https://blog.roboflow.com/mobile-object-detection-models/)
- [Background images for YOLO training](https://y-t-g.github.io/tutorials/bg-images-for-yolo/)
