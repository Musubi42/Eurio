"""Apply cascade for `POST /referential/fix-proposals/{case_id}/apply`.

Spec : `docs/operations/referential-fixes-kickoff.md` § Chunk 2.

Cascade en 8 étapes, exécutées dans l'ordre. Chaque étape produit un dict
`{name, status, diagnostic}` (status ∈ {"ok", "failed", "skipped"}). On
s'arrête sur la première étape `failed`, **sauf** pour le push Supabase
(étapes 6-7) où on continue et on signale `push_failed` — décision actée
2026-05-25.

Atomicité :
- Étape 2 fait un backup de ``eurio.db`` avant toute mutation.
- Étape 3 (mutations eurio.db) tourne en une seule transaction SQLite.
- Étapes 4-5 (FS + Numista fetch) sont idempotentes : ré-exécutables après
  un crash.
- Étapes 6-7 (push Supabase) sont relançables séparément via
  ``POST /referential/push``.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from store import resolve_db_path
from store.referential_fix import (
    ReferentialFixConflict,
    apply_referential_fix,
    preflight_coins,
)

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parents[1]
_DB_DEFAULT = _ML_ROOT / "state" / "eurio.db"
_FIX_PROPOSALS_PATH = _ML_ROOT / "state" / "referential_fix_proposals.json"
_CANONICAL_ROOT = _ML_ROOT / "canonical_images"
_BACKUP_DIR = _ML_ROOT / "state"


# ── Errors ──────────────────────────────────────────────────────────────────


class ApplyError(Exception):
    """Raised when a step fails fatally (abort the cascade).

    `http_status` is the status code the route should return.
    """

    def __init__(self, message: str, *, http_status: int = 500) -> None:
        super().__init__(message)
        self.http_status = http_status


# ── Step helpers ────────────────────────────────────────────────────────────


def _step(name: str, status: str = "ok", **diagnostic: Any) -> dict:
    return {"name": name, "status": status, "diagnostic": diagnostic}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Step 1 — Pre-flight ─────────────────────────────────────────────────────


def _load_case(case_id: str) -> dict:
    if not _FIX_PROPOSALS_PATH.exists():
        raise ApplyError(
            "referential_fix_proposals.json absent — run POST /referential/fix-proposals/refresh first",
            http_status=404,
        )
    data = json.loads(_FIX_PROPOSALS_PATH.read_text())
    for p in data.get("proposals", []):
        if p.get("case_id") == case_id:
            return p
    raise ApplyError(f"case_id not found: {case_id}", http_status=404)


def _preflight_dict(case: dict) -> dict:
    """Les attendus du preflight (partagés client↔serveur via le diff)."""
    swap = case.get("swap") or {}
    new_row = case.get("new_row") or {}
    return {
        "existing_eurio_id": swap["eurio_id"],
        "current_numista_id": swap["current_numista_id"],
        "new_row_eurio_id": new_row["eurio_id"],
        "new_row_numista_id": new_row["numista_id"],
        "swap_new_numista_id": swap["new_numista_id"],
    }


def _preflight(conn: sqlite3.Connection, case: dict) -> dict:
    """Vérifie que la DB est dans un état compatible avec le case (checks coins
    délégués à ``store.referential_fix.preflight_coins``, source unique)."""
    if case.get("shape") != "B":
        raise ApplyError(
            f"Only shape=B is implemented; got shape={case.get('shape')!r}",
            http_status=400,
        )
    pf = _preflight_dict(case)
    try:
        preflight_coins(conn, **pf)
    except ReferentialFixConflict as exc:
        raise ApplyError(f"Pre-flight failed: {exc}", http_status=409) from exc
    return _step(
        "preflight",
        existing_eurio_id=pf["existing_eurio_id"],
        new_row_eurio_id=pf["new_row_eurio_id"],
        current_numista_id=pf["current_numista_id"],
        target_swap_numista_id=pf["swap_new_numista_id"],
        target_new_row_numista_id=pf["new_row_numista_id"],
    )


# ── Step 2 — Backup ─────────────────────────────────────────────────────────


def _backup_db(case_id: str, db_path: Path) -> tuple[Path, dict]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = _BACKUP_DIR / f"eurio.db.bak-fix-{case_id}-{ts}"
    shutil.copy2(db_path, backup_path)
    return backup_path, _step(
        "backup",
        backup_path=str(backup_path.relative_to(_ML_ROOT.parent)),
        size_bytes=backup_path.stat().st_size,
    )


# ── Step 3 — eurio.db mutations ─────────────────────────────────────────────


def _load_country_name(conn: sqlite3.Connection, country_iso2: str) -> str:
    row = conn.execute(
        "SELECT country_name FROM coins WHERE country = ? AND country_name IS NOT NULL LIMIT 1",
        (country_iso2,),
    ).fetchone()
    return row[0] if row and row[0] else country_iso2


def _move_attribution_in_payload(
    existing_payload: dict, new_payload: dict, source: str, feature_text: str | None
) -> bool:
    """Move an observation attribution from existing → new row payload.

    Currently handles ``lmdlp_variants`` (list in observations.lmdlp_variants).
    BCE sidecars live on disk, not in payload, so they're moved in step 4.
    Returns True if the payload was actually modified.
    """
    if source != "lmdlp_variants":
        return False
    obs = existing_payload.setdefault("observations", {})
    variants = obs.get("lmdlp_variants") or []
    if not variants or feature_text is None:
        return False
    moved = [v for v in variants if v.get("name") == feature_text]
    if not moved:
        return False
    obs["lmdlp_variants"] = [v for v in variants if v.get("name") != feature_text]
    if not obs["lmdlp_variants"]:
        obs.pop("lmdlp_variants")
    new_obs = new_payload.setdefault("observations", {})
    new_obs.setdefault("lmdlp_variants", []).extend(moved)
    return True


def _build_new_row_payload(new_row: dict, country_name: str) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "eurio_id": new_row["eurio_id"],
        "identity": {
            "country": new_row["country"],
            "country_name": country_name,
            "year": new_row["year"],
            "face_value": new_row["face_value"],
            "currency": "EUR",
            "is_commemorative": True,
            "theme": new_row.get("theme"),
            "design_description": new_row.get("design_description"),
            "national_variants": None,
            "collector_only": False,
        },
        "cross_refs": {"numista_id": new_row["numista_id"]},
        "observations": {},
        "images": {},
        "provenance": {
            "first_seen": today,
            "last_updated": today,
            "sources_used": ["referential_fix_apply"],
            "needs_review": False,
            "review_reason": None,
        },
    }


def _compute_coins_diff(conn: sqlite3.Connection, case: dict) -> tuple[dict, dict, list[dict]]:
    """Calcule le diff ``coins`` (pur : lit la réplique, construit les payloads,
    N'ÉCRIT RIEN). Retourne ``(coins_insert, coins_update, attributions_moved)``.
    Miroir de l'ancien ``_mutate_db`` sans les ``conn.execute`` d'écriture."""
    swap = case["swap"]
    new_row = case["new_row"]
    existing_id: str = swap["eurio_id"]
    new_row_id: str = new_row["eurio_id"]
    today = datetime.now(timezone.utc).date().isoformat()

    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT raw_payload_json, country FROM coins WHERE eurio_id = ?",
        (existing_id,),
    ).fetchone()
    existing_payload = json.loads(existing["raw_payload_json"]) if existing["raw_payload_json"] else {}
    country_name = _load_country_name(conn, new_row["country"])

    new_payload = _build_new_row_payload(new_row, country_name)

    attributions_moved: list[dict] = []
    for sa in case.get("source_attributions") or []:
        if sa.get("recommended_target") != "new":
            continue
        moved = _move_attribution_in_payload(
            existing_payload, new_payload, sa["source"], sa.get("feature_text")
        )
        if moved:
            attributions_moved.append({"source": sa["source"], "feature_text": sa.get("feature_text")})

    existing_payload.setdefault("cross_refs", {})["numista_id"] = swap["new_numista_id"]
    existing_payload.setdefault("provenance", {})["last_updated"] = today

    coins_insert = {
        "eurio_id": new_row_id,
        "country": new_row["country"],
        "country_name": country_name,
        "year": new_row["year"],
        "face_value": new_row["face_value"],
        "theme": new_row.get("theme"),
        "numista_id": new_row["numista_id"],
        "raw_payload_json": json.dumps(new_payload, ensure_ascii=False),
        "ref_native_id": str(new_row["numista_id"]),
        "design_description": new_row.get("design_description"),
        "updated_at": today,
    }
    coins_update = {
        "eurio_id": existing_id,
        "numista_id": swap["new_numista_id"],
        "ref_native_id": str(swap["new_numista_id"]),
        "raw_payload_json": json.dumps(existing_payload, ensure_ascii=False),
        "updated_at": today,
    }
    return coins_insert, coins_update, attributions_moved


# ── Step 4 — Move BCE FS sidecars ───────────────────────────────────────────


def _move_bce_sidecar(existing_id: str, new_id: str) -> tuple[dict, dict | None]:
    """Move ``obverse_bce.{webp,_thumb.webp,json}`` from existing → new row
    directory (FS, client-side). Retourne ``(step, reparent_intent | None)`` — le
    re-parent DB de ``coin_canonical_images`` voyage dans le diff, pas ici. No-op
    si la row existante n'a pas de sidecar BCE.
    """
    src_dir = _CANONICAL_ROOT / existing_id
    dst_dir = _CANONICAL_ROOT / new_id
    files = ["obverse_bce.webp", "obverse_bce_thumb.webp", "obverse_bce.json"]
    present = [f for f in files if (src_dir / f).is_file()]
    if not present:
        return _step("move_bce_sidecar", status="skipped", reason="no BCE sidecar on existing row"), None

    dst_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for fname in present:
        src = src_dir / fname
        dst = dst_dir / fname
        if dst.exists():
            # Idempotent: existing file at destination — remove source only.
            src.unlink()
        else:
            shutil.move(str(src), str(dst))
        moved.append(fname)

    # If the JSON sidecar moved, rewrite its embedded eurio_id field.
    json_path = dst_dir / "obverse_bce.json"
    if json_path.is_file():
        try:
            meta = json.loads(json_path.read_text())
            if meta.get("eurio_id") != new_id:
                meta["eurio_id"] = new_id
                json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            pass

    intent = {
        "op": "reparent",
        "from_eurio_id": existing_id,
        "to_eurio_id": new_id,
        "source": "bce_comm",  # convention existante
        "role": "obverse",
        "local_path": f"ml/canonical_images/{new_id}/obverse_bce.webp",
    }
    return _step("move_bce_sidecar", moved_files=moved, from_=existing_id, to=new_id), intent


def _step_move_sidecars(case: dict) -> tuple[dict, dict | None]:
    """Move BCE sidecars per source_attributions[*].recommended_target=='new'.
    Retourne ``(step, reparent_intent | None)``."""
    swap_id: str = case["swap"]["eurio_id"]
    new_id: str = case["new_row"]["eurio_id"]
    bce_target_new = any(
        sa.get("source") == "bce_sidecar" and sa.get("recommended_target") == "new"
        for sa in case.get("source_attributions") or []
    )
    if not bce_target_new:
        return _step("move_bce_sidecar", status="skipped", reason="no BCE attribution with target=new"), None
    return _move_bce_sidecar(swap_id, new_id)


# ── Step 5 — Fetch Numista images ───────────────────────────────────────────


def _import_keymanager():
    """Lazy import — keeps the module importable without env vars present."""
    sys.path.insert(0, str(_ML_ROOT))
    from referential.numista_keys import KeyManager  # noqa: E402

    return KeyManager


def _fetch_numista_image(km, eurio_id: str, numista_id: int) -> dict:
    """Idempotent : skip if WebP detail already present on disk."""
    sys.path.insert(0, str(_ML_ROOT))
    from referential.canonical_image_local import canonical_path, exists, write_variants  # noqa: E402
    from referential.import_numista import get_type_details  # noqa: E402

    role = "obverse"
    source = "numista"
    if exists(eurio_id, role, source):
        return {"eurio_id": eurio_id, "numista_id": numista_id, "status": "already_present"}

    details = km.call(get_type_details, numista_id)
    obv = (details.get("obverse") or {}).get("picture")
    if not obv:
        return {"eurio_id": eurio_id, "numista_id": numista_id, "status": "no_obverse_url"}

    resp = httpx.get(obv, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    raw = resp.content
    meta = write_variants(eurio_id, role, source, raw)
    return {
        "eurio_id": eurio_id,
        "numista_id": numista_id,
        "status": "fetched",
        "detail_path": str(canonical_path(eurio_id, role, source).relative_to(_ML_ROOT.parent)),
        **meta,
    }


def _step_fetch_numista(case: dict) -> tuple[dict, list[dict]]:
    """Fetch les images Numista (client : PIL + clés + arbre canonical_images) et
    retourne ``(step, upsert_intents)`` — les rows ``coin_canonical_images``
    voyagent dans le diff."""
    KeyManager = _import_keymanager()
    km = KeyManager()
    targets = [
        (case["swap"]["eurio_id"], case["swap"]["new_numista_id"]),
        (case["new_row"]["eurio_id"], case["new_row"]["numista_id"]),
    ]
    results = []
    failures = []
    intents: list[dict] = []
    for eurio_id, nid in targets:
        try:
            res = _fetch_numista_image(km, eurio_id, nid)
        except Exception as e:
            failures.append({"eurio_id": eurio_id, "numista_id": nid, "error": str(e)[:300]})
            continue
        results.append(res)
        if res["status"] in ("fetched", "already_present"):
            intents.append({
                "op": "upsert",
                "eurio_id": eurio_id,
                "source": "numista_api",
                "role": "obverse",
                "local_path": f"ml/canonical_images/{eurio_id}/obverse_numista.webp",
            })
    status = "ok" if not failures else "failed"
    return _step("fetch_numista", status=status, results=results, failures=failures), intents


# ── Step 6+7 — Push Supabase ────────────────────────────────────────────────


def _push_supabase() -> dict:
    """Invoque ``scripts.push_to_supabase`` (full push, idempotent).

    Décision actée 2026-05-25 : pas de filtre par eurio_id ; le push global
    est idempotent et plus simple à maintenir. Si le push échoue, on
    retourne status='failed' sans revert.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.push_to_supabase"],
        capture_output=True,
        text=True,
        cwd=_ML_ROOT,
        timeout=600,
    )
    if proc.returncode != 0:
        return _step(
            "push_supabase",
            status="failed",
            returncode=proc.returncode,
            stderr_tail=proc.stderr[-1000:],
        )
    # Parse last JSON block from stdout (mirrors _run_python_module).
    out = proc.stdout
    last_open = out.rfind("\n{")
    if last_open < 0:
        last_open = out.find("{")
    summary: dict = {}
    if last_open >= 0:
        try:
            summary = json.loads(out[last_open:].strip())
        except json.JSONDecodeError:
            pass
    return _step("push_supabase", summary=summary)


# ── Step 8 — Verification ───────────────────────────────────────────────────


def _audit_after() -> dict:
    """Re-run audit_referential and return the summary counts."""
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.audit_referential"],
        capture_output=True,
        text=True,
        cwd=_ML_ROOT,
        timeout=120,
    )
    if proc.returncode != 0:
        return _step(
            "audit_after",
            status="failed",
            returncode=proc.returncode,
            stderr_tail=proc.stderr[-500:],
        )
    audit_path = _ML_ROOT / "datasets" / "referential_audit.json"
    if not audit_path.exists():
        return _step("audit_after", status="failed", reason="audit JSON not written")
    data = json.loads(audit_path.read_text())
    return _step(
        "audit_after",
        n_count_mismatch=len(data.get("count_mismatch", [])),
        n_catalog_unlinked=len(data.get("catalog_unlinked", [])),
        n_numista_orphan=len(data.get("numista_orphan", [])),
        n_coins=data.get("n_coins"),
        n_coins_linked=data.get("n_coins_linked"),
    )


# ── Apply diff (canonique) ──────────────────────────────────────────────────


def _apply_diff(diff: dict, db_path: Path) -> dict:
    """Applique le diff au canonique. Direction A (sync active) : forward
    ``POST /ingest/referential-fix`` — un 409/erreur réseau est FATAL (jamais de
    fallback local qui écrirait la réplique). Model A pur (sync off) : applique
    localement dans une transaction. Retourne un ``_step("apply_diff", …)``."""
    from client.http import sync_enabled  # noqa: PLC0415

    if sync_enabled():
        from client.ingest import push_referential_fix  # noqa: PLC0415

        try:
            res = push_referential_fix(diff) or {}
            return _step("apply_diff", mode="ingest", **res)
        except Exception as e:  # noqa: BLE001 — 409/réseau = échec fatal du fix
            logger.exception("apply_diff forward échoué")
            return _step("apply_diff", status="failed", mode="ingest", error=str(e)[:300])

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            res = apply_referential_fix(conn, diff)
            conn.execute("COMMIT")
        except ReferentialFixConflict as e:
            conn.execute("ROLLBACK")
            return _step("apply_diff", status="failed", mode="local", error=str(e))
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return _step("apply_diff", mode="local", **res)


# ── Orchestrator ────────────────────────────────────────────────────────────


def apply_fix(case_id: str) -> dict:
    """Run the 8-step cascade for a given case_id.

    Returns a dict with `case_id`, `success`, `started_at`, `finished_at`,
    `duration_sec`, `steps: [...]`, `backup_path`, `audit_after`. Never
    raises for "expected" failures (preflight, push) — those are reflected
    in `steps[].status`.
    """
    started = datetime.now(timezone.utc)
    steps: list[dict] = []
    backup_path: Path | None = None
    case = _load_case(case_id)
    db_path = resolve_db_path(_DB_DEFAULT)

    # Lectures (preflight, diff, backup) sur une connexion READ-ONLY : sous
    # Direction A, db_path est la réplique (jamais écrite localement) ; les
    # écritures voyagent via le diff (/ingest) ou, en Model A pur, s'appliquent
    # localement dans _apply_diff.
    ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    try:
        # 1. Pre-flight (fatal if fails — raises ApplyError)
        steps.append(_preflight(ro, case))

        # 2. Backup (snapshot de la DB lue)
        backup_path, backup_step = _backup_db(case_id, db_path)
        steps.append(backup_step)

        # 3. Diff coins (pur, aucune écriture)
        coins_insert, coins_update, attrs_moved = _compute_coins_diff(ro, case)
    finally:
        ro.close()

    # 4. Move BCE sidecars FS (client) → intent de re-parent DB
    move_step, reparent_intent = _step_move_sidecars(case)
    steps.append(move_step)

    # 5. Fetch Numista image (client : PIL + clés) → intents d'upsert DB
    try:
        fetch_step, upsert_intents = _step_fetch_numista(case)
    except Exception as e:
        logger.exception("fetch_numista crashed")
        fetch_step, upsert_intents = _step("fetch_numista", status="failed", error=str(e)[:300]), []
    steps.append(fetch_step)

    # Assemble le diff et l'applique au canonique (forward /ingest si sync, sinon
    # local en Model A). Fatal si l'apply échoue → on n'enchaîne pas Supabase.
    diff = {
        "case_id": case_id,
        "preflight": _preflight_dict(case),
        "coins_insert": coins_insert,
        "coins_update": coins_update,
        "canonical_images": ([reparent_intent] if reparent_intent else []) + upsert_intents,
    }
    apply_step = _apply_diff(diff, db_path)
    apply_step["diagnostic"]["attributions_moved"] = attrs_moved
    steps.append(apply_step)

    if apply_step["status"] != "failed":
        # 6+7. Push Supabase (non-fatal per decision 2026-05-25)
        steps.append(_push_supabase())
        # 8. Verification
        steps.append(_audit_after())

    finished = datetime.now(timezone.utc)
    fatal_steps = {"preflight", "backup", "apply_diff"}
    success = all(
        s["status"] != "failed" for s in steps if s["name"] in fatal_steps
    ) and not any(
        s["name"] in {"move_bce_sidecar", "fetch_numista"} and s["status"] == "failed"
        for s in steps
    )
    return {
        "case_id": case_id,
        "success": success,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_sec": (finished - started).total_seconds(),
        "steps": steps,
        "backup_path": (
            str(backup_path.relative_to(_ML_ROOT.parent)) if backup_path else None
        ),
    }
