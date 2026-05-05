# Kickoff — Dino verifier (foundation + intégration review)

> Brief auto-suffisant pour la session courante. Découpé en 3 chunks
> audit-par-chunk. À la fin, Dino propose des suggestions top-K
> visibles dans le drawer `/review` pour chaque crop scrapé.

## Pré-lecture obligatoire

1. [`vision.md`](./vision.md) (en entier — surtout P5 révisé)
2. `docs/sources-refacto/sessions-overview.md`
3. `ml/eval/confusion_map.py` (loader Dino existant qu'on extrait)
4. `ml/api/distance_logic.py` (autre consommateur, ne pas casser)
5. Mémoire `feedback_dino_thresholds`

## Pivot par rapport à la première version de ce kickoff

La V1 de ce doc proposait un **bench autonome** avec set de validation
hand-labellé. **Abandonné** — l'audit DB a montré 1 seul crop `manual`
sur 528 `needs_review`, donc pas de ground truth. Le bench autonome
serait soit synthétique soit dépendant d'une session de labellisation
préalable de 100+ crops, sans Dino visible. Mauvais ordre.

Nouveau plan : **Dino branché directement sur `/review` comme
suggestions visuelles**, calculé pour chaque crop, stocké en DB. Pas de
décision automatique (toujours `needs_review`) — Raphaël voit ce que
Dino propose, valide/corrige avec un clic, et chaque review devient un
data-point. Au bout de 200 reviews on calibre les seuils auto-accept.

## Chiffres de cadrage (vérifiés DB)

| Quoi | Valeur |
|---|---|
| Pièces 2€ commémoratives en `coins` | **466**, toutes avec `numista_id` |
| Folders dataset (`ml/datasets/<numista>/`) | 702 |
| `coins.is_commemorative` | colonne + index existants |
| Crops totaux en `needs_review` | 528 |
| Crops 2€ commémo en `needs_review` (target ciblé) | **524** |
| Crops en `manual` (validés humain) | **1** |

Donc le terrain : **466 ancres à encoder une fois**, **524 crops sur
lesquels Dino aura des suggestions** dès qu'on backfill.

## Décomposition des statuts (cohérence schéma)

Dans le schéma actuel chaque couche a son propre statut :

- `source_runs.status` (run du scrape)
- `discovery_log.pipeline_state` (état d'un listing dans la pipeline)
- `image_assets.resolution_status` (état d'un crop par rapport à
  l'identification)
- `review_queue.status` (état de la review humaine)
- `pending_quotes` séparé de `coin_market_quotes` (prix observé vs
  prix promu)

Dino n'est **pas** un nouveau statut sur l'asset. C'est un **signal
externe versionné** qui vit dans sa propre table, comme
`iteration_aug_vs_real` qui a son `dino_version` à part. La table
`image_asset_dino_predictions` stocke 1 row par
`(asset, encoder_version, anchors_kind)`, l'asset reste en
`needs_review`. Quand on activera l'auto-accept (chunk futur) on
ajoutera le status `auto_dino` à `image_assets.resolution_status` —
pas avant.

## Découpage en chunks

### Chunk 1 — Fondations (livrable courant)

- Module `ml/foundation/` (encoder, anchors, matcher), avec
  refacto sans régression de `confusion_map.py` et `distance_logic.py`
- Migration schema : nouvelle table `image_asset_dino_predictions`
- Helpers `store.py` pour la nouvelle table
- Script `ml/scripts/build_dino_anchors.py` qui encode les 466
  obverses 2€ commémo dans un `.npz` cache
- Entrée Taskfile `ml:dino-anchors:build`
- Tests unitaires `ml/tests/test_foundation.py`

**Audit visuel attendu** : lancer `go-task ml:dino-anchors:build`,
voir le `.npz` créé dans `ml/state/`, `python -m foundation.matcher`
sur 1 crop renvoie un top-K cohérent (la pièce qu'on cherchait est
souvent dans le top-3).

### Chunk 2 — Pipeline + API

- Étape `auto_validate_dino` après `detect_crop`, écrit dans
  `image_asset_dino_predictions`. Idempotent (skip si row existe pour
  même version d'encoder).
- Backfill : ré-applique sur les 524 reviews actuels.
- Endpoint `GET /review-queue/<asset_id>/dino-suggestions` qui retourne
  top-K enrichi avec image obverse + métadonnées coin.

**Audit visuel attendu** : `SELECT count(*) FROM
image_asset_dino_predictions` ≥ 524 ; un curl sur l'endpoint renvoie
JSON cohérent.

### Chunk 3 — Front review

- Composant `DinoSuggestions.vue` affiché dans le drawer single ET le
  drawer lot
- Liste de cards top-5 avec thumb obverse, sim, spread, bouton
  "Sélectionner cette pièce" qui pré-remplit `CoinSearchModal`
- Coloration indicative (top1 fort = vert, mid = gold, bas = grey),
  utilise les tokens `--success`, `--gold-600`, `--ink-400` du admin
- Pas de logique d'auto-accept. Toujours review humaine en V1.

**Audit visuel attendu** : ouvrir un drawer review, voir les top-5
Dino sous le crop, cliquer un candidat → modal pré-rempli.

## Structure code chunk 1

```
ml/
├── foundation/
│   ├── __init__.py            # re-exports principaux
│   ├── encoder.py             # DEFAULT_ENCODER_VERSION, pick_device,
│   │                          # load_encoder, build_transform,
│   │                          # encode_image, encode_paths
│   ├── anchors.py             # AnchorBank, build_anchors_2eur_commemo,
│   │                          # save_anchors, load_anchors
│   └── matcher.py             # Match dataclass, top_k_match
├── scripts/
│   └── build_dino_anchors.py  # CLI bootstrap
├── state/
│   ├── schema.sql             # + table image_asset_dino_predictions
│   └── store.py               # + DinoPredictionRow, upsert/list helpers
├── eval/
│   └── confusion_map.py       # MODIFIÉ : import depuis foundation
├── api/
│   └── distance_logic.py      # MODIFIÉ : import depuis foundation
└── tests/
    └── test_foundation.py     # smoke + round-trip ancres + matcher
```

### Schema migration (additif, table nouvelle)

```sql
CREATE TABLE IF NOT EXISTS image_asset_dino_predictions (
  asset_id        TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  encoder_version TEXT NOT NULL,        -- 'dinov2-vits14'
  anchors_kind    TEXT NOT NULL,        -- '2eur_commemo' (namespace)
  anchors_count   INTEGER NOT NULL,     -- nb ancres au moment du calcul
  top_k_json      TEXT NOT NULL,        -- [{eurio_id, sim}, ...] desc
  top1_eurio_id   TEXT,
  top1_sim        REAL,
  top2_eurio_id   TEXT,
  top2_sim        REAL,
  spread          REAL,                 -- top1_sim - top2_sim
  computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  duration_ms     INTEGER,
  PRIMARY KEY (asset_id, encoder_version, anchors_kind)
);
CREATE INDEX IF NOT EXISTS idx_dino_pred_asset
  ON image_asset_dino_predictions(asset_id);
CREATE INDEX IF NOT EXISTS idx_dino_pred_top1
  ON image_asset_dino_predictions(top1_eurio_id);
```

Choix de design :

- **Clé composée** `(asset_id, encoder_version, anchors_kind)` : permet
  de garder plusieurs versions/scopes sans collision. On peut switch
  d'encoder plus tard sans tout perdre.
- **`top_k_json`** : la liste complète sérialisée (top-5 ou top-10).
  Cohérent avec `predicted_top3_json` dans `iteration_live_tests`.
- **`top1_*`, `top2_*`, `spread` dénormalisés** : pour les queries
  rapides "donne-moi les crops où top1 == target_eurio_id" sans
  parser le JSON.
- **`anchors_count`** : audit. Si on rajoute des pièces au catalog les
  similarités peuvent changer ; permet de détecter les rows "stale".
- **`ON DELETE CASCADE`** : si l'asset est supprimé (purge run, recrop,
  etc.) ses prédictions disparaissent.

### Format `top_k_json`

```json
[
  {"eurio_id": "ad-2007-2eur-bearded", "sim": 0.7421},
  {"eurio_id": "fr-2007-2eur-rugby",   "sim": 0.6210},
  {"eurio_id": "be-2007-2eur-laaba",   "sim": 0.5993},
  ...
]
```

Trié par sim desc. K=5 stockés en DB (suffisant pour suggestions UI).
La sim est cosine, donc dans `[-1, 1]` mais en pratique `[0, 1]`
puisque les vecteurs sont L2-normalisés et l'image n'a pas
d'embeddings négatifs en valeur effective sur DINOv2.

## Module `ml/foundation/`

### `encoder.py`

Extrait du code de `confusion_map.py`. Source de vérité unique pour le
choix d'encoder et la pré-processing. API :

```python
DEFAULT_ENCODER_VERSION = "dinov2-vits14"
DINOV2_REPO = "facebookresearch/dinov2"
DINOV2_MODEL = "dinov2_vits14"
INPUT_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD  = (0.229, 0.224, 0.225)

def pick_device() -> torch.device: ...
def load_encoder(device: torch.device | None = None) -> tuple[torch.nn.Module, torch.device]: ...
def build_transform() -> transforms.Compose: ...
def encode_image(
    image: Image.Image | Path | str,
    *, encoder=None, device=None, transform=None,
) -> np.ndarray: ...  # (D,) float32 L2-normalized
def encode_paths(
    paths: list[Path], *, encoder=None, device=None, transform=None,
    batch_size: int = 32,
) -> tuple[list[Path], np.ndarray]: ...  # (N, D), kept paths only
```

Chargement lazy : `load_encoder()` appelé sans args alloue le device et
charge le modèle ; appels suivants réutilisent le cache de torch.hub.

### `anchors.py`

```python
@dataclass
class AnchorBank:
    eurio_ids: list[str]   # length N, stable order
    matrix: np.ndarray     # (N, D) float32 L2-normalized
    encoder_version: str   # 'dinov2-vits14'
    anchors_kind: str      # '2eur_commemo'
    built_at: str          # ISO8601 UTC

def anchor_path(kind: str) -> Path:
    return Path("ml/state") / f"foundation_anchors_{kind}.npz"

def save_anchors(bank: AnchorBank) -> Path: ...
def load_anchors(kind: str) -> AnchorBank | None: ...

def build_anchors_2eur_commemo(
    *, store: Store, datasets_dir: Path,
    force_recompute: bool = False,
) -> AnchorBank:
    """Encode toutes les obverse.jpg des 2€ commémo de la DB.

    Skips:
      - eurio_id sans numista_id en DB (logué)
      - numista_id sans dossier ml/datasets/<numista>/
      - dossier sans obverse.jpg
    """
```

Persistance `.npz` : un seul fichier par `anchors_kind`. Format :

```
ml/state/foundation_anchors_2eur_commemo.npz
  ├── matrix          (N, D) float32
  ├── eurio_ids       (N,)   <U64 strings
  └── meta            (1,)   JSON string : {encoder_version, anchors_kind, built_at}
```

### `matcher.py`

```python
@dataclass
class Match:
    eurio_id: str
    sim: float

def top_k_match(
    query_vec: np.ndarray,   # (D,)
    bank: AnchorBank,
    *, top_k: int = 5,
) -> list[Match]: ...

def spread(matches: list[Match]) -> float:
    if len(matches) < 2:
        return 0.0
    return matches[0].sim - matches[1].sim
```

Cosine simplifiée puisque tout est L2-normalisé : `sim = bank.matrix @
query_vec`. Tri descendant, slice top-K. Pas de batch — le batching
est la responsabilité du caller.

## Helpers `store.py`

Nouvelle dataclass + helpers :

```python
@dataclass
class DinoPredictionRow:
    asset_id: str
    encoder_version: str
    anchors_kind: str
    anchors_count: int
    top_k: list[dict]           # [{"eurio_id": ..., "sim": ...}, ...]
    top1_eurio_id: str | None
    top1_sim: float | None
    top2_eurio_id: str | None
    top2_sim: float | None
    spread: float | None
    duration_ms: int | None = None
    computed_at: str | None = None
```

Méthodes Store :

- `upsert_dino_predictions(rows: list[DinoPredictionRow]) -> int` —
  REPLACE INTO sur la PK composée. Retourne nb rows inscrites.
- `list_dino_predictions_for_asset(asset_id: str) -> list[DinoPredictionRow]` —
  toutes les versions stockées (en pratique 1 par asset).
- `get_dino_prediction(asset_id, encoder_version, anchors_kind) -> DinoPredictionRow | None`

## Script bootstrap

`ml/scripts/build_dino_anchors.py` :

```
Usage:
  go-task ml:dino-anchors:build              # encode 2€ commémo, écrit npz
  go-task ml:dino-anchors:build -- --force   # recompute forcé
  go-task ml:dino-anchors:build -- --kind 2eur_commemo  (default)
```

Logge :
- N pièces ciblées (depuis DB)
- N skipped (pas de numista_id, pas d'obverse.jpg)
- N encodées
- Path du npz
- Durée totale + median per-image

## Tests `ml/tests/test_foundation.py`

Tests rapides (skip Dino lourd si pas dispo CI) :

1. `test_pick_device_runs` — pas de crash, retourne un torch.device
2. `test_build_transform_shape` — image PIL → tensor (3, 224, 224)
3. `test_match_orders_by_sim_desc` — bank fixture mockée, top_k_match
   trie bien
4. `test_anchor_bank_roundtrip` — save_anchors → load_anchors récupère
   l'identique
5. `test_spread_zero_when_lt_2` — edge case singleton

Test "intégration encoder" (skip par défaut, marqué `@slow`) :
6. `test_encode_image_norm` — charge le modèle, encode 1 image, vérifie
   `np.linalg.norm(vec) ≈ 1.0` et `vec.shape == (384,)`

## Refacto `confusion_map.py` et `distance_logic.py`

`confusion_map.py` perd :
- `DEFAULT_ENCODER_VERSION`, `DINOV2_REPO`, `DINOV2_MODEL`,
  `INPUT_SIZE`, `IMAGENET_MEAN`, `IMAGENET_STD`
- `pick_device`, `load_encoder`, `_build_transform`,
  `_load_image_tensor`

Et les remplace par :
```python
from foundation.encoder import (
    DEFAULT_ENCODER_VERSION,
    pick_device,
    load_encoder,
    build_transform,
)
```

`distance_logic.py` change ses 3 imports lazy `from
eval.confusion_map import ...` en `from foundation.encoder import
...`.

Tests existants doivent rester verts : `test_lab.py`,
`test_lab_api.py`, et tout ce qui touchait l'aug-vs-real.

## Hors-scope chunk 1

- L'étape pipeline `auto_validate_dino` — chunk 2
- Le backfill 524 crops — chunk 2
- L'endpoint API — chunk 2
- Le composant front — chunk 3
- Toute logique d'auto-accept — pas avant qu'on ait des données

## Risques chunk 1

1. **Refacto confusion_map.py / distance_logic.py** : ne pas casser
   l'aug-vs-real. Lancer les tests pertinents avant + après.
2. **`.npz` size** : 466 × 384 × 4 = ~700 KB. OK.
3. **Mémoire torch.hub cache** : déjà téléchargé sur cette machine
   (confusion_map a déjà tourné). Pas de re-download.
4. **Taskfile dans ml/Taskfile.yml** : choisir le bon namespace.
   Convention déjà existante : `eval-real:*`, `scan:*`, etc. On utilise
   `dino-anchors:*`.

## Ordre d'exécution proposé

1. Schema migration (additive) + bootstrap test rapide DB
2. Module `ml/foundation/encoder.py` (extraction)
3. Refacto `confusion_map.py` + `distance_logic.py`, vérifier tests
4. Module `ml/foundation/anchors.py` + `matcher.py`
5. Helpers store.py + dataclass `DinoPredictionRow`
6. Script bootstrap
7. Entrée Taskfile
8. Tests unitaires
9. Lancer `go-task ml:dino-anchors:build` pour audit visuel
