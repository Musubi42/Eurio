# Real photo capture — Critères de shooting

> Document de référence à garder ouvert au moment de photographier tes pièces pour la bibliothèque benchmark (Bloc 3). L'objectif : obtenir une distribution de photos qui reflète **la variabilité des conditions réelles** auxquelles le scan utilisateur sera exposé en production.
>
> Sans cette variabilité, le bench surestime les performances. Avec elle, les métriques reflètent ce que vivra l'utilisateur final.

## Règle absolue

**Ces photos ne doivent JAMAIS rentrer dans le training set.** Elles sont exclusivement dédiées à l'évaluation. Tout mélange invaliderait toutes les métriques du benchmark.

Gate technique : les photos stockées dans `ml/data/real_photos/` sont **gitignored** et exclues par assertion dans `prepare_dataset.py` (voir Bloc 3 §spec technique).

---

## Les 5 axes à faire varier

Pour chaque pièce, essaye de capturer des photos couvrant **chacun des 5 axes**. Pas besoin de toutes les combinaisons (5⁵ = 3125), mais d'au moins **5-8 photos par pièce** qui couvrent des valeurs différentes sur chaque axe.

### 1. Éclairage

| Valeur | Description | Impact ML |
|---|---|---|
| `natural-direct` | Soleil direct, près d'une fenêtre en plein jour | Reflets marqués, contrastes forts |
| `natural-diffuse` | Intérieur jour, loin fenêtre (ciel couvert OK) | Éclairage homogène doux |
| `artificial-warm` | LED 2700K, halogène, ampoule filament | Dominante jaune/orange |
| `artificial-cold` | LED 5000K+, néon blanc | Dominante bleue |
| `mixed` | Combinaison naturel + artificiel (lampe de bureau en fin de journée) | Conditions réelles d'intérieur |

**Intention** : le modèle doit apprendre à ignorer la température de couleur et l'intensité absolue.

### 2. Fond

| Valeur | Description | Impact ML |
|---|---|---|
| `wood` | Table en bois, parquet, planche | Texture organique, motif régulier |
| `cloth` | Drap, pull, nappe | Texture douce, motif irrégulier |
| `paper` | Feuille blanche, carton kraft | Fond uniforme neutre |
| `metal` | Plateau inox, ardoise, surface brillante | Reflets sur le fond → challenge de segmentation |
| `hand` | Paume ouverte, doigts | Cas réaliste : scan pris à main levée |

**Intention** : le détecteur (YOLO) doit segmenter la pièce de son contexte quelle qu'en soit la texture.

### 3. Angle (tilt par rapport à la caméra)

| Valeur | Description | Impact ML |
|---|---|---|
| `0deg` | Frontal, caméra perpendiculaire à la pièce | Cas idéal |
| `15deg` | Légèrement tilté | Cas courant |
| `30deg` | Moyennement tilté | Stress test perspective |
| `45deg` | Fortement tilté | Cas limite |

**Intention** : valider que les augmentations `perspective` sont bien calibrées. Si le modèle foire à 30° mais marche à 0°, l'augmentation `perspective.max_tilt_degrees` est trop conservatrice.

### 4. Distance / cadrage

| Valeur | Description |
|---|---|
| `close` | La pièce remplit >80% du cadre |
| `medium` | Pièce ~40-60% du cadre, contexte visible |
| `far` | Pièce au centre avec beaucoup de contexte autour |

**Intention** : YOLO crop la pièce avant ArcFace, mais les marges varient. Valider que le modèle tient quel que soit le crop relatif.

### 5. État de la pièce

| Valeur | Description |
|---|---|
| `clean` | Pièce sortie d'un album, pas manipulée |
| `handled` | Traces de doigts fraîches (sors la pièce, tripote, photographie) |
| `dirty` | Pièce circulée visiblement patinée / tachée |
| `wet` | Goutte d'eau, après contact humide (optionnel) |
| `specular` | Pièce capturant un hotspot de lumière directe (reflet blanc visible) |

**Intention** : valider que les augmentations `overlays` (patina, dust, fingerprints) et `relighting` sont calibrées pour matcher la réalité.

---

## Convention de nommage

Format : `<eurio_id>_<index>_<lighting>_<background>_<angle>.jpg`

Exemples :

```
be-2008-2eur-standard_01_natural-direct_wood_0deg.jpg
be-2008-2eur-standard_02_artificial-warm_cloth_15deg.jpg
be-2008-2eur-standard_03_mixed_hand_30deg.jpg
ad-2014-2eur-standard_01_artificial-cold_paper_0deg.jpg
```

Pas obligatoire de respecter strictement — le script d'éval scanne `*.jpg` et `*.png` dans chaque dossier, quel que soit le nom. Mais cette convention te facilitera la vie quand tu analyseras les échecs (filtrer par condition).

**Les valeurs d'état et distance** ne rentrent pas dans le nom de fichier (trop long), stocke-les dans un sidecar optionnel `meta.json` par dossier si tu veux les tracker finement. Pour v1, le nom suffit.

---

## Emplacement

```
ml/data/real_photos/
├── be-2008-2eur-standard/
│   ├── 01_natural-direct_wood_0deg.jpg
│   ├── 02_artificial-warm_cloth_15deg.jpg
│   └── ...
├── ad-2014-2eur-standard/
│   └── ...
└── fr-2012-2eur-10-years-emu/
    └── ...
```

Un dossier par `eurio_id`. Créé automatiquement au premier dépôt ou à la main.

---

## Règle des "sessions de shooting"

Un data leak subtil à éviter : si tu prends 10 photos d'une pièce en 30 secondes **dans la même session** (même fond, même lumière, même angle caméra à 2° près), elles partagent des features contextuelles qui ne généralisent pas.

**Règle** : pour chaque pièce, photographie en **au moins 2 sessions distinctes** (idéalement 3), séparées par **au moins un changement de fond + lumière**. Déplace-toi physiquement, change la source lumineuse, réinstalle-toi. Sinon le bench sera gonflé parce que les photos du split éval partagent le contexte de celles du split train (s'il y a un split interne au bench).

Tracker la session dans `meta.json` ou dans le nom de fichier (`session1`, `session2`).

---

## Quantité recommandée par zone (first pass)

| Zone | Nb pièces cibles | Photos par pièce | Total par zone |
|---|---|---|---|
| Verte | 5 | 6 | 30 |
| Orange | 5 | 8 | 40 |
| Rouge | 5 | 10 | 50 |
| **Total** | **15** | **6-10** | **~120** |

~2h de shooting en une session si les pièces sont prêtes. Tu peux en faire plus, mais c'est le seuil utile minimum pour que les métriques soient stables.

**Priorité de shooting** : commence par **rouge** (c'est là qu'on a le plus besoin de vérité terrain pour calibrer les recipes les plus complexes). Puis orange. Verte en dernier (sanity check).

---

## Protocole type pour une pièce

1. Sors la pièce (état `clean`)
2. Installe-la sur ton fond 1 (ex: bois) sous éclairage 1 (ex: naturel diffuse)
3. Photographie à 0°, 15°, 30° → 3 photos
4. Change l'angle caméra : distance `close`, `medium`, `far` → 3 photos
5. Manipule la pièce (état `handled`) → 2 photos sous fond 2 (ex: main) éclairage 2 (ex: LED chaude)
6. Fin de session. Laisse tomber si c'est pénible, reviens un autre jour pour la session 2.

**Durée estimée par pièce** : 4-8 min selon rigueur.

---

## Checklist rapide au moment du shoot

- [ ] La pièce est **centrée** et **focus** dans le cadre
- [ ] Pas de main qui masque partiellement la pièce (sauf si l'axe `background=hand` est l'objectif)
- [ ] Le format final est **JPG** ou **PNG**, minimum **1024×1024** pixels
- [ ] Fichier nommé selon la convention (idéalement) ou au moins mis dans le bon dossier `eurio_id/`
- [ ] Pas de filtre / retouche / beauté appliqué (pas d'Instagram style)
- [ ] Appareil = ton Android habituel (cohérent avec le scan utilisateur final)

---

## Voir aussi

- [`03-real-photo-benchmark.md`](./03-real-photo-benchmark.md) — PRD du Bloc 3 qui consomme cette bibliothèque
- [`02-augmentation-studio.md`](./02-augmentation-studio.md) — PRD du Bloc 2 qui pilote les recipes validées par ces photos
- [`../research/ml-scalability-phases/phase-4-subcenter-evalbench.md`](../research/ml-scalability-phases/phase-4-subcenter-evalbench.md) — spec d'origine du banc d'éval in-the-wild
