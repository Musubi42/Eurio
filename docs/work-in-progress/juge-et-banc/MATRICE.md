# La matrice d'encodeurs — tout tester, décider ensuite

> **Cadré le 2026-08-25, rien d'implémenté.** Décision du PO : *« je veux tout
> tester — tous les DINOv2, tous les DINOv3, à tous les niveaux de
> quantisation, quelle que soit leur licence ou leur taille »*, et **la même
> chose pour ArcFace**. Ce sont des **mesures**, pas un choix de production.
> Rien ici n'engage ce qui partira dans l'APK.
>
> ⛔ **Précondition** : cette matrice n'a de sens qu'avec un juge propre. Lire
> [`PROBLEME.md`](./PROBLEME.md) d'abord. Mesurer avant la séparation
> train/juge, c'est produire un classement biaisé en faveur d'ArcFace.

## 1. Les trois axes

| Axe | Valeurs | Aujourd'hui |
|---|---|---|
| **modèle** | DINOv2 (s/b/l, ± reg4, giant), DINOv3 (18 entrées timm), ArcFace (le nôtre) | 4 bras mesurés le 2026-08-20, tous en fp32 |
| **quantisation** | fp32, fp16, int8 | **aucune** — jamais varié |
| **corpus de jugement** | gold review (1958 crops eBay), corpus device (`eval_real_norm`) | **le gold review seul** |

Les deux derniers axes n'existent ni dans le code ni dans le schéma. C'est
l'essentiel du travail.

## 2. Ce que pèse chaque candidat — mesuré

Comptes de paramètres réels (`timm.create_model(..., pretrained=False)` et
`torch.load` sur les checkpoints du cache), **2026-08-25**. Les tailles fp32 /
fp16 / int8 sont les poids seuls, sans le graphe ni les métadonnées d'export.

### DINOv2 — `torch.hub`, déjà en cache local

| modèle | params | fp32 | fp16 | int8 | tient dans un APK ? |
|---|---:|---:|---:|---:|---|
| `dinov2_vits14` | 22,1 M | 84,1 Mo | 42,1 Mo | **21,0 Mo** | ✅ même en fp32 |
| `dinov2_vitb14` | 86,6 M | 330,3 Mo | 165,1 Mo | **82,6 Mo** | ✅ **en int8 seulement** |
| `dinov2_vitl14` | **304,4 M** | 1 161 Mo | 580,5 Mo | 290,3 Mo | ❌ jamais |

### DINOv3 — `timm`, 18 entrées

| modèle | params | fp32 | fp16 | int8 | APK |
|---|---:|---:|---:|---:|---|
| `vit_small_patch16_dinov3` | 21,6 M | 82,3 | 41,2 | **20,6** | ✅ fp32 |
| `convnext_tiny.dinov3` | 27,8 M | 106,1 | 53,1 | **26,5** | ✅ fp16 |
| `vit_small_plus_patch16_dinov3` | 28,7 M | 109,4 | 54,7 | **27,4** | ✅ fp16 |
| `convnext_small.dinov3` | 49,5 M | 188,7 | **94,3** | 47,2 | ✅ fp16 |
| `vit_base_patch16_dinov3` | 85,6 M | 326,7 | 163,3 | **81,7** | ✅ int8 |
| `convnext_base.dinov3` | 87,6 M | 334,0 | 167,0 | **83,5** | ✅ int8 |
| `convnext_large.dinov3` | 196,2 M | 748,6 | 374,3 | 187,1 | ❌ |
| `vit_large_patch16_dinov3` | 303,1 M | 1 156 | 578,1 | 289,0 | ❌ |
| `vit_huge_plus_*`, `vit_7b_*` | ≥ 840 M / **7 G** | — | — | — | ❌ et **hors budget RAM** |

Variantes non listées : `_qkvb` (biais QKV) et `.sat493m` (pré-entraînement
imagerie satellite) existent pour plusieurs tailles. Le `.sat493m` est
**probablement hors sujet** pour des pièces de monnaie — à écarter en connaissance
de cause, pas par oubli.

### 🔎 Les deux lectures qui sautent aux yeux

1. **`vitb14` en int8 fait 82,6 Mo — il tient dans un APK, et il n'a jamais été
   mesuré.** Le banc du 2026-08-20 avait `vitl14`, `vits14` et deux DINOv3 ;
   la taille intermédiaire de DINOv2 a été sautée. C'est le candidat le moins
   cher à tester et potentiellement le point d'équilibre du projet.
2. **Le plafond des 100 Mo n'est pas une loi de la nature.** C'est la limite
   d'un APK Play Store. Play Asset Delivery et le téléchargement au premier
   lancement lèvent la contrainte — au prix d'un chantier d'architecture (§6).
   Un **APK QA sideloadé n'a aucune limite** : `vitl14` à 1,2 Go est testable
   sur device dès qu'un export existe.

## 3. L'axe quantisation — ce qu'il faut décider avant de mesurer

« int8 » n'est pas une valeur, c'est une famille de procédés, et le chiffre de
recall en dépend :

| Procédé | Ce qu'il demande | Ce qu'il coûte en précision |
|---|---|---|
| **fp16** | rien, une conversion | quasi nul sur un ViT |
| **int8 dynamique** | rien | modéré, variable selon l'architecture |
| **int8 statique (PTQ)** | un **jeu de calibration** représentatif | le meilleur des int8 — si la calibration est bonne |
| **QAT** | un réentraînement | hors sujet ici (le backbone est gelé par définition) |

⚠️ **Le jeu de calibration est un piège de fuite de plus.** Il doit sortir du
`train`, jamais du `judge` — sinon on calibre sur l'examen. Précédent dans le
repo : `ml/calibration_image_sample_data_20x128x128x3_float32.npy` existe déjà
pour le modèle actuel ; sa provenance n'est pas documentée et **devra être
établie** avant de s'en inspirer.

⚠️ Et une réserve de fond : **quantiser un ViT n'est pas quantiser un CNN.**
Les couches d'attention encaissent mal l'int8 naïf. Un résultat int8 décevant
peut être un défaut de procédé plutôt qu'une propriété du modèle — ne pas
conclure sur un seul bras.

## 4. Le schéma — deux colonnes manquent

`encoder_bench_runs` (migration 0009) est bien conçue : elle porte déjà
`encoder_spec`, `encoder_version`, `n_params_m`, `embed_dim`, `input_px`,
`device`, `ms_per_img`, le McNemar apparié avec `n_paired`, et le drapeau
`provisional`. Deux axes lui manquent :

| Colonne à ajouter | Pourquoi |
|---|---|
| `quantization` (`fp32`\|`fp16`\|`int8_dynamic`\|`int8_static`) | sans elle, deux bras du même modèle à deux précisions **s'écrasent** ou deviennent indiscernables |
| `eval_corpus` + `eval_corpus_version` | la table est **câblée sur le gold de review** (`gold_version`, `gold_n_crops`, tirés de `review.bench_gold`). Elle ne sait pas exprimer « noté sur le corpus device » |

⚠️ **Une migration entraîne son miroir.** `ml/state/schema.sql` **et** le
`MIROIR_ATTENDU` de `tests/test_schema_mirror.py` doivent être mis à jour dans
le même lot, sinon deux tests rougissent — précédent vécu avec la 0011.

⚠️ Et une dette ouverte à ne pas empiler dessus : **`provisional` est gardé à
l'écriture mais son prédicat croit quatre champs déclarés par l'appelant**
(Q1..Q4 de `scan-sans-retrain/FINDINGS.md` §8.10). Quatre payloads mensongers
ressortent `provisional=0`. Une page qui affiche cette matrice fonderait un
choix d'encodeur sur ce drapeau — **à fermer avant, pas après**.

## 5. La page dédiée

Demande du PO : un seul endroit pour lire la matrice, **DINO et ArcFace
ensemble**.

| | |
|---|---|
| **Où** | `admin/packages/studio-local`, feature nouvelle à côté de `features/bench/` |
| **Gating** | route `meta: { heavy: true }` + item nav `heavy: true` — elle tape `:8042`, donc elle se grise toute seule en hébergé (R0bis, [ADR-011](../../adr/011-front-admin-unique.md)) |
| **Proto-first ?** | **non** — R1 ne porte que sur l'app Android. Discipline applicable : maquette d'abord dans le front où elle vivra, avec fixtures et états vides/erreur |
| **Source** | `encoder_bench_runs` + `encoder_bench_predictions` |

Ce qu'elle doit rendre lisible, par ordre d'importance :

1. **la matrice** modèle × quantisation, une cellule = un run, la couleur = le
   recall — c'est la lecture que le PO a demandée ;
2. **le corpus de jugement affiché en permanence**, jamais implicite : un
   chiffre sur le gold review et un chiffre sur le corpus device ne se
   comparent pas, et rien ne doit permettre de les mettre côte à côte sans
   étiquette ;
3. **le coût à côté de la qualité** — `ms_per_img`, `n_params_m`, poids estimé,
   et le verdict « tient dans un APK » ;
4. **la significativité** — un écart sans sa p-value (`mcnemar_p`, `n_paired`)
   ne s'affiche pas comme un classement ;
5. **`provisional` visible**, et une cellule provisoire ne doit pas pouvoir se
   lire comme un résultat.

⚠️ **Le piège d'affichage à éviter absolument** : une matrice invite à trier par
recall décroissant toutes cellules confondues. Deux corpus, deux tâches, deux
populations — le tri global fabriquerait un gagnant qui n'existe pas.

## 6. L'export vers le téléphone — un chantier, pas une étape

**Il n'existe aucun chemin DINO → device dans le repo.** Ni TFLite, ni ONNX, ni
ExecuTorch. Ce qui est embarqué aujourd'hui (`eurio_embedder_v1.tflite`, 4,4 Mo)
sort de la chaîne ArcFace.

Ce que ce chantier devra trancher, quand il s'ouvrira :

- le **format** (LiteRT/TFLite, ONNX Runtime Mobile, ExecuTorch) et son
  délégué (NNAPI, GPU, XNNPACK) ;
- la **latence réelle sur téléphone** — le seul chiffre qui compte, et il n'est
  pas déductible des 217,9 ms/img mesurées en CPU sur Mac pour `vitl14` ;
- le **format de banque de l'APK**, qui doit changer de toute façon : il lit
  `coin_embeddings.json` (23 entrées, un centroïde par classe) et doit passer à
  N références par classe, avec agrégation **par max des cosinus, pas par
  moyenne** (ADR-008) ;
- la **licence** : DINOv3 n'est pas Apache 2.0. Redistribution sous les mêmes
  termes, copie de l'accord jointe, mention « Built with DINOv3 ». La
  quantification ne lave pas la licence. Sans objet tant qu'on mesure ; **payable
  avant le Play Store** si un DINOv3 gagne.

👉 **Le raccourci qui donne le chiffre sans écrire l'export** : l'app QA en mode
capture. Elle enregistre les frames normalisées ; les modèles sont notés
**hors device**, sur exactement les mêmes images. On n'investit dans l'export
que pour le gagnant.

## 7. Ordre de travail proposé

Rien de ceci n'est engagé — c'est la séquence qui minimise le travail jeté.

| # | Lot | Dépend de |
|---|---|---|
| 0 | Établir où vit le corpus device complet (317 photos ≠ 114 sur le Mac) et **le répliquer** | — |
| 1 | Séparation train/val/judge — Q1 de [`PROBLEME.md`](./PROBLEME.md) | 0 |
| 2 | Les deux colonnes de schéma + leur miroir (§4) | — |
| 3 | Fermer `provisional` (Q1..Q4 de FINDINGS §8.10) | — |
| 4 | Bras `vitb14` fp32 au banc — le moins cher, le plus informatif | 2 |
| 5 | Axe quantisation (fp16 puis int8), calibration issue du `train` seul | 2, 4 |
| 6 | La page | 2, 3 |
| 7 | Entraînement ArcFace sur `rich10-68c`, noté contre le juge propre | 1 |
| 8 | Export device — chantier séparé, ouvert seulement s'il y a un gagnant | 4-5 |

⚠️ **Le lot 7 est celui que le PO veut « en rapide », et il dépend du lot 1.**
C'est le seul arbitrage de calendrier réel de ce chantier : entraîner avant la
séparation donne un modèle qu'on ne saura pas noter proprement.
