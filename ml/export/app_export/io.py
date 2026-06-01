"""I/O helpers for the app-facing Supabase exporter.

Conventions
-----------
- get_sqlite_con()  opens eurio.db read-only with row_factory=sqlite3.Row.
- get_pg_client()   builds an httpx.Client configured for PostgREST
                    (service_role key), re-using load_env() from sync_to_supabase.
- upsert()          POST to PostgREST with merge-duplicates, chunked at 500 rows.
- json_scalar()     decodes a single-value JSON string stored in coin_observations
                    (e.g. '"Round"' -> 'Round', '25.75' -> 25.75).

Domain builders (build_<table>) live in separate modules under this package.
They must be pure functions: (sqlite3.Connection) -> list[dict].
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx

# Resolve repo root so we can locate eurio.db and reuse load_env.
_HERE = Path(__file__).resolve()
_ML_ROOT = _HERE.parents[2]          # ml/
_REPO_ROOT = _ML_ROOT.parent         # Eurio/

if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from export.sync_to_supabase import load_env  # noqa: E402

_DB_PATH = _ML_ROOT / "state" / "eurio.db"
_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def get_sqlite_con() -> sqlite3.Connection:
    """Return a read-only connection to ml/state/eurio.db with row_factory=Row."""
    uri = f"file:{_DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# PostgREST / Supabase
# ---------------------------------------------------------------------------

def get_pg_client() -> httpx.Client:
    """Return an httpx.Client pre-configured for PostgREST (service_role).

    Raises RuntimeError if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY are absent.
    """
    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
            "(via .env at repo root or environment variables)."
        )
    base = url.rstrip("/") + "/rest/v1"
    return httpx.Client(
        base_url=base,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )


def delete_all(client: httpx.Client, table: str, not_null_col: str) -> None:
    """Delete every row of a PostgREST table (full-refresh projection).

    PostgREST requires a filter on DELETE as a safety guard; we use
    ``<not_null_col>=not.is.null`` which matches all rows since the column is a
    NOT NULL key. service_role bypasses RLS.

    Raises:
        httpx.HTTPStatusError: on any 4xx/5xx response.
    """
    resp = client.delete(
        f"/{table}",
        params={not_null_col: "not.is.null"},
        headers={"Prefer": "return=minimal"},
    )
    resp.raise_for_status()


def upsert(
    client: httpx.Client,
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str | None = None,
) -> None:
    """POST rows to PostgREST table with merge-duplicates, chunked at 500.

    Args:
        client:      httpx.Client from get_pg_client().
        table:       PostgREST table name (no schema prefix).
        rows:        Rows to upsert; each dict's keys must match target columns.
        on_conflict: Comma-separated column list for ?on_conflict=…, or None.

    Raises:
        httpx.HTTPStatusError: on any 4xx/5xx response.
    """
    if not rows:
        return
    headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
    params: dict[str, str] = {}
    if on_conflict:
        params["on_conflict"] = on_conflict
    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i : i + _BATCH_SIZE]
        resp = client.post(f"/{table}", json=batch, headers=headers, params=params)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Scalar helper
# ---------------------------------------------------------------------------

def json_scalar(payload_json: str | None) -> Any:
    """Decode a JSON-encoded scalar stored in coin_observations.payload_json.

    Examples::

        json_scalar('"Round"')      -> 'Round'
        json_scalar('25.75')        -> 25.75
        json_scalar('true')         -> True
        json_scalar(None)           -> None

    Dicts/lists are returned as-is (the caller should not use this helper for
    structured payloads — use json.loads directly instead).
    """
    if payload_json is None:
        return None
    try:
        return json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return payload_json
