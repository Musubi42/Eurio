# Architecture backend — pattern d'écriture d'endpoints

> **Cible** : un repo `eurio-api` propre, layered, testable. Tous les
> nouveaux endpoints suivent ce pattern. Les anciens (`coins_routes.py`,
> etc.) seront refactorés progressivement.

## 1. Pourquoi pas garder les "fat controllers" actuels

`ml/serving/coins_routes.py` mélange aujourd'hui :
- Pydantic models (request/response)
- SQL queries
- Business logic
- Validation HTTP

Résultat : 1000+ lignes par fichier, difficile à tester unitairement, SQL
collé aux routes, duplications entre routes qui font des SELECT
similaires. Ça marche, mais on veut mieux pour la suite.

## 2. Pattern cible : 4 couches par domaine

Pour chaque domaine métier (`coins`, `sources`, `review`, `training`,
`mints`, etc.) :

```
ml/serving/<domain>/
├── __init__.py            ← exports : `router` + service principal
├── models.py              ← Pydantic schemas (request, response, domaine)
├── repository.py          ← Accès SQL pur (sqlite3 stdlib)
├── service.py             ← Logique métier (orchestre repository)
└── router.py              ← FastAPI : validation + auth + service calls
```

### 2.1 `models.py` — Pydantic schemas

```python
"""Domain types pour <domain>.

Trois familles :
- *Filter / *Patch : payloads de requête (POST/PATCH bodies)
- *Response / *Detail : payloads de réponse (jamais des dict)
- objets domaine internes (utilisés par repository/service)
"""
from pydantic import BaseModel, Field


class SourceRunFilter(BaseModel):
    source_id: str | None = None
    status: list[str] | None = None  # ('running','done','failed',…)
    since: str | None = None         # ISO timestamp
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class SourceRun(BaseModel):
    """Représentation lue (read-only) — utilisée par les endpoints GET."""
    run_id: str
    source_id: str
    started_at: str
    ended_at: str | None
    status: str
    n_discovered: int
    n_downloaded: int
    n_failed: int
    error: str | None


class SourceRunListResponse(BaseModel):
    items: list[SourceRun]
    total: int
```

### 2.2 `repository.py` — Accès SQL pur

```python
"""Accès direct à eurio.db pour <domain>. Aucune logique métier.

Fonctions = SELECT/INSERT/UPDATE/DELETE. Reçoivent une connexion sqlite3,
retournent des objets typés (models.py) ou des tuples primitifs.
Pas d'HTTPException ici — les erreurs sont des exceptions Python pures.
"""
import sqlite3

from .models import SourceRun, SourceRunFilter


class SourceRunNotFound(Exception):
    pass


def list_runs(
    conn: sqlite3.Connection, filter: SourceRunFilter
) -> tuple[list[SourceRun], int]:
    where: list[str] = []
    params: list[object] = []
    if filter.source_id:
        where.append("source_id = ?")
        params.append(filter.source_id)
    if filter.status:
        placeholders = ",".join("?" * len(filter.status))
        where.append(f"status IN ({placeholders})")
        params.extend(filter.status)
    if filter.since:
        where.append("started_at >= ?")
        params.append(filter.since)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT count(*) FROM source_runs {where_clause}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT run_id, source_id, started_at, ended_at, status, "
        f"       n_discovered, n_downloaded, n_failed, error "
        f"FROM source_runs {where_clause} "
        f"ORDER BY started_at DESC LIMIT ? OFFSET ?",
        params + [filter.limit, filter.offset],
    ).fetchall()
    items = [SourceRun(**dict(r)) for r in rows]
    return items, total


def get_run(conn: sqlite3.Connection, run_id: str) -> SourceRun:
    row = conn.execute(
        "SELECT run_id, source_id, started_at, ended_at, status, "
        "       n_discovered, n_downloaded, n_failed, error "
        "FROM source_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise SourceRunNotFound(run_id)
    return SourceRun(**dict(row))
```

### 2.3 `service.py` — Logique métier

Optionnel si la logique est triviale (juste un passthrough). Utile dès
qu'on agrège plusieurs repository calls, fait une transformation, etc.

```python
"""Logique métier <domain>. Orchestre les repository functions.

Pas d'HTTP ici, pas de SQL non plus. Manipule des objets domaine,
appelle les repository, retourne des objets prêts à sérialiser.
"""
from . import repository
from .models import SourceRun, SourceRunFilter, SourceRunListResponse


def list_runs(conn, filter: SourceRunFilter) -> SourceRunListResponse:
    items, total = repository.list_runs(conn, filter)
    return SourceRunListResponse(items=items, total=total)


def get_run_with_funnel(conn, run_id: str) -> dict:
    """Exemple où le service combine 2 repo calls."""
    run = repository.get_run(conn, run_id)
    funnel = repository.compute_funnel(conn, run_id)
    return {"run": run, "funnel": funnel}
```

### 2.4 `router.py` — FastAPI endpoints

```python
"""Routes HTTP <domain>. Thin layer : validation, auth, error mapping.

Tout le code métier est dans service.py / repository.py — ce fichier ne
contient PAS de SQL ni de business logic.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from serving.auth_principal import Principal, require_scope
from . import service
from .models import SourceRunFilter, SourceRunListResponse
from .repository import SourceRunNotFound
from .deps import db_connection  # cf. §3

router = APIRouter(prefix="/source-runs", tags=["sources"])

_require_read = require_scope("sources:read")


@router.get("", response_model=SourceRunListResponse)
def list_runs(
    principal: Annotated[Principal, Depends(_require_read)],
    conn: Annotated[object, Depends(db_connection)],
    source_id: str | None = Query(default=None),
    status: str | None = Query(default=None, description="CSV"),
    since: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> SourceRunListResponse:
    filter = SourceRunFilter(
        source_id=source_id,
        status=status.split(",") if status else None,
        since=since,
        limit=limit,
        offset=offset,
    )
    return service.list_runs(conn, filter)


@router.get("/{run_id}", response_model=...)
def get_run(
    run_id: str,
    principal: Annotated[Principal, Depends(_require_read)],
    conn: Annotated[object, Depends(db_connection)],
):
    try:
        return service.get_run_with_funnel(conn, run_id)
    except SourceRunNotFound:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
```

## 3. Conventions de code

### 3.1 Connexion DB partagée

Plutôt que d'ouvrir une connexion sqlite3 dans chaque fonction, on
expose une dependency FastAPI :

```python
# serving/deps.py
import os, sqlite3
from pathlib import Path

def db_connection():
    path = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
```

Importé par les routers : `Depends(db_connection)`.

### 3.2 Naming

- Domaines en **kebab-case** dans les URL : `/source-runs`, `/coin-credits`,
  `/training-runs`. Pas de underscore.
- Tables SQLite restent en **snake_case** (`source_runs`, `coin_credits`).
- Pydantic models en `PascalCase`, fonctions en `snake_case`.
- Pas d'abréviation cryptique (`run_id`, pas `rid`).

### 3.3 Erreurs

- Repository lève des exceptions Python typées (`SourceRunNotFound`,
  `DuplicateCrossRef`, etc.) — jamais de `HTTPException`
- Router capture et mappe vers `HTTPException` avec `detail` lisible :
  `404` (not found), `400` (validation), `403` (scope), `409` (conflict),
  `500` (sentinelle, debug logged)
- Pas de `raise Exception("boom")` sans type

### 3.4 Auth

Toutes les routes ont au minimum `Depends(require_scope(...))`. Le
scope est documenté dans `auth_principal.ROLE_SCOPES`.

| Scope | Endpoints concernés |
|---|---|
| `coins:read` | GET /coins/*, /confusion-map/*, /coin-credits/* |
| `coins:write` | PATCH /coins/*, POST /coins/*/cross-refs/* |
| `sources:read` | GET /source-runs, /source-runs/{id}/*, /sources/{id} |
| `sources:write` | (Phase 6) POST /source-runs, PATCH /source-runs/{id} |
| `review:read` | GET /review/* |
| `review:write` | POST /review/* |
| `training:run` | POST /training-runs, PATCH /training-runs/{id} |
| `audit:read` | GET /audit/* |
| `users:read` | GET /users |
| `users:manage` | PUT /users/{id}/roles |
| `tokens:manage_own` | /me/tokens/* |

### 3.5 Tests minimum

Pour chaque domaine, deux niveaux :

**Smoke** (CI ou run manuel) — un test par endpoint qui :
- forge un PAT owner via CLI ou via fixture
- curl + parse JSON + asserts shape

**Unit** (idéal) — pour repository / service :
- fixture eurio.db en mémoire (`sqlite3.connect(":memory:")`)
- apply migrations
- insert sample data
- assert repository functions retournent ce qu'on attend

Tests TS côté studio-local : pas obligatoire mais bienvenu pour les
composables critiques (Arbitrage, sets/criteria).

### 3.6 Migrations

Tout nouveau schéma SQLite passe par `ml/serving/migrations/NNNN_*.sql`
(idempotent, appliquées au startup hook FastAPI via `db_migrate.run_migrations`).
La numérotation est strictement croissante et jamais réutilisée.

## 4. Refactor progressif des "fat controllers" existants

`coins_routes.py`, `sets_routes.py`, `operations_routes.py` :
fat-controllers actuels. On les **refactore au fur et à mesure**, pas en
big-bang :

- Quand on touche à un endpoint pour ajouter une feature : on en profite
  pour extraire les Pydantic models dans `models.py`, le SQL dans
  `repository.py`, et garder le router fin
- Les endpoints qu'on ne touche pas peuvent rester fat — pas de refactor
  gratuit
- Objectif moyen-terme : tous les domaines en pattern layered au moment
  de Phase 5 cutover

## 5. Câblage dans `server_serve.py`

Au lieu de mounter via `_CANDIDATES` (mécanisme legacy avec try/except),
on monte explicitement chaque router de domaine :

```python
from serving.coins import router as coins_router
from serving.sources import router as sources_router  # nouveau
from serving.review import router as review_router

app.include_router(coins_router)
app.include_router(sources_router, dependencies=[Depends(require_principal)])
```

Le mécanisme `_CANDIDATES` reste pour les routers legacy heavy
(`referential` avec PIL, `review_queue` avec cv2) en attendant qu'ils
soient soit refactorés soit retirés.

## 6. Anti-patterns à éviter

- ❌ SQL dans `router.py`
- ❌ `HTTPException` dans `repository.py` ou `service.py`
- ❌ Ouvrir une connexion sqlite3 manuellement dans une route
- ❌ Retourner des `dict` au lieu de Pydantic models
- ❌ `try/except Exception:` sans log + re-raise typé
- ❌ Hardcoder des paths absolus (`/var/lib/eurio/...`) — passer par env
- ❌ Importer des modules ML lourds (`cv2`, `torch`) au top du module
  — si nécessaire, lazy-import dans la fonction qui en a besoin
- ❌ Ajouter un nouvel endpoint sans `Depends(require_scope(...))`

## 7. Exemple complet — ajouter un domaine de zéro

Pour ajouter `mints` (table `mints`, 29 rows) :

```bash
mkdir -p ml/serving/mints
touch ml/serving/mints/{__init__.py,models.py,repository.py,service.py,router.py}
```

**models.py** :
```python
from pydantic import BaseModel

class Mint(BaseModel):
    id: str
    country: str
    name: str
    active: bool
```

**repository.py** :
```python
import sqlite3
from .models import Mint

def list_mints(conn: sqlite3.Connection) -> list[Mint]:
    rows = conn.execute("SELECT id, country, name, active FROM mints ORDER BY country, name").fetchall()
    return [Mint(id=r["id"], country=r["country"], name=r["name"], active=bool(r["active"])) for r in rows]
```

**router.py** :
```python
from typing import Annotated
from fastapi import APIRouter, Depends
from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from . import repository
from .models import Mint

router = APIRouter(prefix="/mints", tags=["mints"])

@router.get("", response_model=list[Mint])
def list_mints(
    principal: Annotated[Principal, Depends(require_scope("coins:read"))],
    conn: Annotated[object, Depends(db_connection)],
) -> list[Mint]:
    return repository.list_mints(conn)
```

**__init__.py** :
```python
from .router import router
```

**Câblage `server_serve.py`** :
```python
from serving.mints import router as mints_router
app.include_router(mints_router)
```

**Refactor côté studio-local** (si applicable) :
```ts
// shared/api/eurio-api.ts déjà existant
const mints = await eurioApi.get<Mint[]>('/mints')
```

Done.
