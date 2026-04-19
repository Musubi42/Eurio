# Overlays — textures pour l'augmentation Phase 2

> Ce dossier contient les **textures libres** utilisées pour salir, ternir et rayer les images de pièces lors de la génération d'augmentations synthétiques. Objectif : simuler les conditions réelles (pièces circulées, mal éclairées) à partir d'un scan Numista studio parfait.

## 📐 Principe

Le pipeline d'augmentation applique, sur chaque variante synthétique d'une pièce :

1. **Transformation géométrique** (rotation, tilt, perspective) — code dans `ml/augmentations/perspective.py`
2. **Overlays de textures** depuis ce dossier, composés sur l'image via des modes de blend — code dans `ml/augmentations/overlays.py`
3. *(itérations futures)* Relight 2.5D, spécularités, motion blur, etc.

Les textures sont des **PNG grayscale** (mode `L`) qui modulent la luminance de l'image. Elles ne remplacent pas la pièce — elles la salissent *par-dessus*, sous le masque circulaire (pour rester dans la pièce). Le code d'application (`overlays.py`) ignore tout canal alpha éventuel et convertit en RGB à la volée, donc une seule map grayscale par texture suffit.

## 📂 Les 4 catégories

```
ml/data/overlays/
├── patina/          ← ternissement global, oxydation
├── scratches/       ← rayures linéaires, micro-éraflures
├── fingerprints/    ← traces de doigts, empreintes grasses
└── dust/            ← poussière, saleté fine accumulée
```

Les dossiers sont peuplés par `go-task augment-textures-generate` (voir section plus bas). **Le pipeline scanne automatiquement le contenu** — pas de convention de nommage, pas de fichier d'index à maintenir. Si un jour tu déposes des PNG curated à la main, ils coexistent sans friction.

---

### `patina/` — Ternissement

**Effet visuel** : la pièce paraît oxydée, noircie, ou ternie de façon non uniforme.

**Usage code** : blend mode `multiply`, opacité 0.10–0.30 (orange) ou 0.15–0.40 (red).

**Count par défaut du générateur** : 18

---

### `scratches/` — Rayures

**Effet visuel** : marques linéaires fines à larges qui traversent la surface.

**Usage code** : blend mode `screen`, opacité 0.05–0.20.

**Count par défaut du générateur** : 14

---

### `fingerprints/` — Empreintes

**Effet visuel** : traces de doigts huileuses, tourbillons ovales papillaires.

**Usage code** : blend mode `overlay`, opacité 0.10–0.25.

**Count par défaut du générateur** : 7

---

### `dust/` — Poussière et grime

**Effet visuel** : poussière fine, saleté accumulée, pattern bruiteux.

**Usage code** : blend mode `multiply`, opacité 0.20–0.40.

**Count par défaut du générateur** : 14

---

## 🛠️ Génération procédurale (source de vérité)

La banque est **générée par script**, pas téléchargée. Motivation :

- Les banques CC0 (ambientCG, Poly Haven) sont orientées rendu 3D (PBR packs lourds) ou signalétique urbaine — très peu d'alphas grunge utilisables directement.
- `augmentations/overlays.py` ne consomme qu'**une seule map grayscale par texture** (le canal alpha est ignoré), donc un générateur procédural couvre exactement le besoin.
- Zéro licence à tracker, reproductibilité totale (seed fixe), diff git lisible (le code produit la banque).

Générateur : [`ml/generate_overlay_textures.py`](../../generate_overlay_textures.py).

```bash
go-task augment-textures-generate -- --clean           # regénère tout
go-task augment-textures-generate -- --scratches 20    # plus de rayures
go-task augment-textures-generate -- --size 2048       # bump à 2K
```

Défauts : `--size 1024`, `--seed 42`, counts `{patina:18, dust:14, scratches:14, fingerprints:7}`.

Stratégies par catégorie :

| Catégorie | Technique | Raison |
|---|---|---|
| `patina` | Bruit fractal (5 octaves) remappé vers [150, 250] | blend=multiply ; blotches diffuses |
| `dust` | Grain gaussien haute-fréquence + cercles sombres sparse | blend=multiply ; particules |
| `scratches` | Lignes aléatoires OpenCV sur fond noir, parfois directionnelles | blend=screen ; n'impacte que les pixels brillants |
| `fingerprints` | Sinusoïde radiale anisotrope (ellipse) + bruit basse-fréquence | blend=overlay ; pattern papillaire approximé |

---

## 📦 Curation CC0 — remisée

La voie initialement envisagée (download de textures CC0 depuis ambientCG / Poly Haven) est **suspendue** pour l'instant. Raisons :

- Les catégories CC0 pertinentes s'avèrent soit absentes (Poly Haven n'a pas de section "Imperfection"), soit biaisées vers la signalétique urbaine (ambientCG "Decal"), soit fournies sous forme de packs PBR lourds inadaptés (Poly Haven fournit 96 MB pour un matériau quand on n'a besoin que d'une map grayscale ~1 MB).
- Le générateur procédural couvre le besoin d'augmentation sans friction de licence ni dépendance externe.

On ré-ouvrira cette voie **si** le générateur procédural montre ses limites visuelles (manque de réalisme photographique qui dégrade la qualité des embeddings). À ce moment-là : curation sélective, sources CC0 strictes (pas de CC-BY/CC-NC), dépose manuelle dans les dossiers ad hoc — le pipeline ne différenciera pas.

---

## 💾 Format produit par le générateur

| Caractéristique | Valeur |
|---|---|
| Format fichier | `.png` mode `L` (grayscale 8-bit) |
| Résolution | `--size` CLI (défaut 1024) — le pipeline redimensionne à la taille de la pièce à l'application |
| Nommage | `{category}_{000..N}.png` (déterministe pour un seed fixé) |

---

## ✅ Validation

```bash
go-task augment-textures-check
```

Ce que ça fait :
- Compte les `.png` valides dans chaque sous-dossier
- Vérifie qu'ils ouvrent correctement
- Affiche un tableau par catégorie avec le count et le statut
- Exit code 1 si **aucune** texture du tout (bloquant), 0 sinon

## 🎬 Test visuel du pipeline

```bash
go-task ml:augment-preview -- --eurio-id ad-2014-2eur-standard --count 16 --seed 42
```

La grille PNG 4×4 sort dans `ml/output/augmentation_previews/`. Ouvre dans Preview / Finder et juge visuellement.

**Sans aucune texture**, la preview marche quand même — elle n'applique que le perspective tilt. Tu verras juste des variations géométriques, pas de saleté.

---

## 🎯 Itérer sur la banque

Workflow typique :

1. `go-task augment-textures-generate -- --clean` (banque fraîche)
2. `go-task ml:augment-preview -- --eurio-id <coin> --count 16 --seed 42` (visuel)
3. Si un paramètre semble off (trop/pas assez, trop sombre, etc.), ajuster :
   - **Counts / size** → flags CLI
   - **Caractéristiques d'une catégorie** (fréquence, intensité, etc.) → tuner dans `generate_overlay_textures.py`
   - **Opacités d'application** → tuner dans `ml/augmentations/recipes.py`
4. Regénérer + re-preview.

---

## 🔒 Licences

Banque générée procéduralement → aucun enjeu de licence. Le jour où on ré-ouvre la voie curation CC0 (voir plus haut), règle stricte : **CC0 ou domaine public** uniquement, pas de CC-BY ni CC-NC.

---

## 🗂️ Gitignore

Le `.gitignore` local ignore `*.png`/`*.jpg` ; les `.gitkeep` gardent la structure des dossiers dans git. La banque est donc régénérée à la demande plutôt que versionnée. Puisqu'elle est déterministe (seed + counts + code ⇒ mêmes bytes), on peut basculer à "tout committer" plus tard sans perdre la reproductibilité — à trancher si le workflow le justifie.

---

## 🧭 Voir aussi

- [`docs/research/ml-scalability-phases/phase-2-augmentation.md`](../../../docs/research/ml-scalability-phases/phase-2-augmentation.md) — spec fonctionnelle Phase 2
- [`ml/augmentations/recipes.py`](../../augmentations/recipes.py) — paramètres par zone (opacités, counts, layers)
- [`ml/augmentations/overlays.py`](../../augmentations/overlays.py) — code d'application des textures
