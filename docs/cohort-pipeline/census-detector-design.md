# Design — étage dedup + verify + fusion d'identité (census de pièces)

> **Statut : design VERROUILLÉ (2026-06-04), v1 pas encore codée.** Sous-chantier de [coin-census-bench](./coin-census-bench.md). Fait suite à la mesure du plafond (§5 du bench) : le **propose** est résolu (YOLO-low@~0.10, faux-single 0 %) ; reste à **ramener le sur-comptage** (faux-lot ~69 %) sans réintroduire de faux-single.
>
> **Décidé PO** : signal is-coin = **option A (prototype coin-ness large, DINO)** · v1 = **① NMS-concentrique + ② verify is-coin** (fusion ③ repoussée, bench front/back trop mince) → mesurer le résidu.

## 0. Ce que l'étage doit faire (contrat)

Entrée : un raw eBay + les **boîtes YOLO-low@0.10** (haut rappel, sur-compte). Sortie : **le nombre de pièces physiques distinctes** `n_coins` (+ les régions retenues, pour le crop). Découplé du format de crop. Benché sur `bench_v0.json` (mêmes métriques : faux-single = poison à garder à 0, faux-lot à écraser, exact/±1 à monter).

## 1. Évidence — de quoi est fait le sur-comptage

Caractérisation des **239 boîtes « extra »** (au-delà de la plus grosse) sur les **55 singles sur-comptés** (n_coins=1, ≥2 boîtes YOLO@0.10) :

| Classe de boîte extra | Part | Quoi | Étage qui l'adresse |
|---|---|---|---|
| **CONCENTRIC** | **8 %** | centre dans la box principale ou IoU>0.3 (doublon, anneau bimétal interne, fragment) | NMS-concentrique (géométrique) |
| **LOW_COIN** | **69 %** | sim DINO faible : texte, fenêtre/cadre coincard, logo, fond, reflet | **verify is-coin** |
| **COINLIKE_SEP** | **22 %** | disjointe ET « coin-like » : avers/revers, 2e vraie pièce, ou médaille/visuel imprimé coin-like | fusion-identité / réel |

**Lecture : le sur-comptage est d'abord un problème de VERIFY** (69 % = clutter non-pièce), pas de dedup (8 %) ni de fusion (22 % tail). L'ordre d'impact dicte l'effort.

## 2. L'échelle proposée (ladder), dans l'ordre

```
boîtes YOLO-low@0.10
  → ① NMS-concentrique      (géométrique, fusionne doublons/anneaux/contenus)   ~8% du bruit
  → ② verify is-coin        (garde « pièce, toute dénom/face » ; jette clutter)  ~69% du bruit
  → ③ fusion d'identité     (colle avers+revers d'1 pièce ; exemplaires ⟂)       ~22% tail
  → count = n pièces distinctes
```

### ① NMS-concentrique — tranché, peu de risque
Fusionner les boîtes dont l'une **contient** le centre de l'autre, ou IoU > ~0.3, en gardant la plus grande (rim externe). Couvre l'anneau bimétal interne + fragments + doublons. Pur géométrique, 0 dépendance. **Pas de débat** — à coder tel quel.

### ② verify is-coin — LE CŒUR, et la vraie question ouverte
69 % du sur-comptage = des boîtes qui **ne sont pas des pièces**. Un bon gate les jette et on a quasiment gagné. **MAIS** le signal is-coin doit être **agnostique à la dénomination ET à la face** : une pièce de 1 cent, un revers national, une pièce hors-cible restent des pièces. Le piège : le signal « sim DINO vs ancres 2€-commémo *avers* » (celui du bench) confond « pas une pièce » et « pas une 2€-commémo-avers » → l'utiliser comme gate **retuerait des vraies pièces** (= faux-single réintroduit sur les lots de cents/revers). À NE PAS faire.

**Options pour le signal is-coin (à choisir ensemble) :**

| Opt | Signal | Pour | Contre |
|---|---|---|---|
| **A. Prototype coin large** | sim DINO vs une banque « coin-ness » multi-dénom × 2 faces (cents→2€, avers+revers, bâtie depuis nos réfs Numista/BCE) | réutilise DINO déjà chargé ; agnostique dénom/face ; 0 entraînement | il faut construire+calibrer la banque ; un médaillon coin-like peut passer |
| **B. Probe is-coin** | régression logistique (1 couche) sur features DINO, coin vs non-coin | très précis ; léger | = un mini-entraînement (mais ≠ détecteur complet) ; besoin d'un petit set labellisé pos/neg |
| **C. Géométrie + YOLO-conf** | conf YOLO (percentile) + circularité/fill du masque + structure-guard (Laplacian, déjà en prod) | 0 modèle en plus ; rapide | le texte/fenêtre coincard peut être circulaire ; moins robuste |
| **D. Combo** | ① géométrie pré-filtre cheap → A ou B sur les survivants | étage cheap d'abord, modèle sur le résidu | plus de pièces mobiles |

> **✅ Décidé : option A (prototype coin-ness large, DINO).** Garder **C (structure-guard Laplacian, déjà en prod)** en pré-filtre cheap. **B** en réserve si A ne sépare pas assez (la banque large risque de laisser passer les visuels imprimés sur coincard).
>
> **Sous-questions A (pour le build)** : (a) sources de la banque = avers **+ revers** Numista (`ml/datasets/<nid>/{obverse,reverse}.jpg`) sur toutes dénoms (1c→2€), + BCE ; combien d'items vise-t-on ? (b) seuil τ calibré sur le bench (sweep, comme §5) ; (c) faut-il un set de **négatifs** (texte/coincard/fond) pour fixer τ proprement, ou le sweep sur le bench suffit ?

### ③ fusion d'identité — le tail 22 %, partiellement bench-limité
Deux sous-cas dans COINLIKE_SEP :
- **avers + revers d'1 même pièce** : 2 disques coin-like, même diamètre, dans un listing « single ». La fusion **n'est pas** par cosinus brut (les 2 faces sont visuellement différentes) → heuristique **contextuelle** : même taille + listing single + 2 disques isolés ⇒ 1 pièce. Signal d'appui possible : un classifieur avers/revers, ou la cohérence « paire » (mêmes dimensions, fond identique).
- **exemplaires identiques** (rouleau, lot de la même pièce) : là le cosinus DINO **élevé** entre disques colle bien → dedup par similarité.

⚠️ **Bench mince** : `single_two_faces` = **1** seul échantillon (4/110 front/back au total). On benche cet étage à l'aveugle. → **étendre le bench front/back** (cf. §1 gotcha bench) avant d'investir lourd ici. Pour la v1, viser ① + ② et **mesurer le résidu** ; ne coder ③ que si le résidu le justifie ET le bench le couvre.

## 3. Plan de validation (bench-first, R0)
- Étendre `measure_census_ceiling.py` (ou un module dédié) avec un proposeur **`yolo_low+ladder`** : boîtes YOLO@0.10 → ① → ② → (③) → count. Mêmes métriques que §5.
- **Cible** : faux-single **reste 0 %**, faux-lot **69 % → vers ~5-10 %**, `exact pièces` **25 % → ↑**, sur le même bench.
- Ablation : mesurer après ① seul, après ①+②, après ①+②+③ — pour isoler l'apport de chaque étage (et confirmer la lecture 8/69/22).

## 4. Décisions (2026-06-04)
1. **Signal is-coin** : ✅ **A (prototype coin-ness large, DINO)** + C (structure-guard) en pré-filtre.
2. **Périmètre v1** : ✅ **①+②**, mesurer le résidu ; **③ fusion repoussée** (bench front/back trop mince).
3. **Bench front/back** : à étendre **après** ①+② (pas un pré-requis tant que ③ est repoussé).
4. **Où vit le code** : d'abord **proposeur de bench** (`yolo_low+ladder` dans/à côté de `measure_census_ceiling.py`) → promotion en module `scan/census.py` une fois les chiffres validés. Bench-first.

## 5. Prochain pas concret (v1)

> **Réfs dispo (constat 2026-06-04)** : `ml/datasets/` = 688 nid, **564 obverse + 563 reverse**, mais **tous face_value 2€** (682 coins, 623 commémo). Pas de cents/1€/50c en réfs locales. → la banque v1 sera **2€ avers+revers (~1100 imgs)**, **bien alignée avec ce bench** (mix-zone-17 = 16 classes, toutes 2€). **Trou dénom assumé** (cents/1€) → à combler (scrape réfs / BCE) quand le pipeline touchera des cohortes non-2€. Bench-first : on valide d'abord ce que ce bench mesure.

1. **Banque coin-ness** : encoder avers+revers 2€ (Numista, ~1100 imgs ; + BCE si dispo) en DINO → `state/foundation_coinness.npz`. Script type `build_coinness_bank.py`.
2. **Ladder** : `nms_concentric(boxes)` → `is_coin(crop) = simDINO(crop, banque) ≥ τ` (+ structure-guard) → count. Ajouter le proposeur `yolo_low+ladder` au harnais de bench.
3. **Mesurer** sur `bench_v0.json` : ablation ① / ①+② ; cible faux-single **0 %**, faux-lot **69 %→~5-10 %**, exact ↑. Présenter au PO.
