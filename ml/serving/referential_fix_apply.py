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

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = _ML_ROOT / "state" / "eurio.db"
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


def _preflight(conn: sqlite3.Connection, case: dict) -> dict:
    """Vérifie que la DB est dans un état compatible avec le case."""
    if case.get("shape") != "B":
        raise ApplyError(
            f"Only shape=B is implemented; got shape={case.get('shape')!r}",
            http_status=400,
        )
    swap = case.get("swap") or {}
    new_row = case.get("new_row") or {}

    existing_id: str = swap["eurio_id"]
    expected_current_nid: int = swap["current_numista_id"]
    new_nid_for_existing: int = swap["new_numista_id"]
    new_row_id: str = new_row["eurio_id"]
    new_row_nid: int = new_row["numista_id"]

    # Existing row must exist with the expected current numista_id.
    row = conn.execute(
        "SELECT numista_id FROM coins WHERE eurio_id = ?", (existing_id,)
    ).fetchone()
    if row is None:
        raise ApplyError(
            f"Pre-flight failed: existing eurio_id={existing_id!r} not found in coins",
            http_status=409,
        )
    current_nid = row[0]
    if current_nid != expected_current_nid:
        raise ApplyError(
            f"Pre-flight failed: {existing_id} has numista_id={current_nid}, "
            f"expected {expected_current_nid} (DB state diverged from proposal)",
            http_status=409,
        )

    # New row eurio_id must not already exist.
    if conn.execute(
        "SELECT 1 FROM coins WHERE eurio_id = ?", (new_row_id,)
    ).fetchone():
        raise ApplyError(
            f"Pre-flight failed: target eurio_id={new_row_id!r} already exists",
            http_status=409,
        )

    # The new numista_ids (for the swap target and the new row) must not
    # already be used by *another* row.
    for nid, expected_owner in (
        (new_nid_for_existing, existing_id),  # owner-to-be after swap
        (new_row_nid, new_row_id),            # owner-to-be after insert
    ):
        rows = conn.execute(
            "SELECT eurio_id FROM coins WHERE numista_id = ?", (nid,)
        ).fetchall()
        for (other,) in rows:
            if other != expected_owner and other != existing_id:
                raise ApplyError(
                    f"Pre-flight failed: numista_id={nid} already linked to {other!r}",
                    http_status=409,
                )

    return _step(
        "preflight",
        existing_eurio_id=existing_id,
        new_row_eurio_id=new_row_id,
        current_numista_id=current_nid,
        target_swap_numista_id=new_nid_for_existing,
        target_new_row_numista_id=new_row_nid,
    )


# ── Step 2 — Backup ─────────────────────────────────────────────────────────


def _backup_db(case_id: str) -> tuple[Path, dict]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = _BACKUP_DIR / f"eurio.db.bak-fix-{case_id}-{ts}"
    shutil.copy2(_DB_PATH, backup_path)
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


def _mutate_db(conn: sqlite3.Connection, case: dict) -> dict:
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

    # Build new row payload.
    new_payload = _build_new_row_payload(new_row, country_name)

    # Move source attributions flagged as target='new' (lmdlp only here; BCE
    # FS moves happen in step 4).
    attributions_moved: list[dict] = []
    for sa in case.get("source_attributions") or []:
        if sa.get("recommended_target") != "new":
            continue
        moved = _move_attribution_in_payload(
            existing_payload, new_payload, sa["source"], sa.get("feature_text")
        )
        if moved:
            attributions_moved.append({"source": sa["source"], "feature_text": sa.get("feature_text")})

    # Update existing row's cross_refs.numista_id to point at the post-swap id.
    existing_payload.setdefault("cross_refs", {})["numista_id"] = swap["new_numista_id"]
    existing_payload.setdefault("provenance", {})["last_updated"] = today

    # Single transaction.
    with conn:
        conn.execute(
            """
            INSERT INTO coins (
                eurio_id, country, country_name, year, face_value,
                is_commemorative, theme, numista_id, raw_payload_json,
                ref_source, ref_native_id, currency, collector_only,
                design_description, status, needs_review, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'numista', ?, 'EUR', 0, ?, 'referenced', 0, ?)
            """,
            (
                new_row_id,
                new_row["country"],
                country_name,
                new_row["year"],
                new_row["face_value"],
                new_row.get("theme"),
                new_row["numista_id"],
                json.dumps(new_payload, ensure_ascii=False),
                str(new_row["numista_id"]),
                new_row.get("design_description"),
                today,
            ),
        )
        conn.execute(
            """
            UPDATE coins
               SET numista_id = ?,
                   ref_native_id = ?,
                   raw_payload_json = ?,
                   updated_at = ?
             WHERE eurio_id = ?
            """,
            (
                swap["new_numista_id"],
                str(swap["new_numista_id"]),
                json.dumps(existing_payload, ensure_ascii=False),
                today,
                existing_id,
            ),
        )

    return _step(
        "mutate_db",
        inserted_eurio_id=new_row_id,
        inserted_numista_id=new_row["numista_id"],
        updated_eurio_id=existing_id,
        updated_numista_id=swap["new_numista_id"],
        attributions_moved=attributions_moved,
    )


# ── Step 4 — Move BCE FS sidecars ───────────────────────────────────────────


def _move_bce_sidecar(conn: sqlite3.Connection, existing_id: str, new_id: str) -> dict:
    """Move ``obverse_bce.{webp,_thumb.webp,json}`` from existing → new row
    directory, and update ``coin_canonical_images`` accordingly. No-op if
    the existing row has no BCE sidecar.
    """
    src_dir = _CANONICAL_ROOT / existing_id
    dst_dir = _CANONICAL_ROOT / new_id
    files = ["obverse_bce.webp", "obverse_bce_thumb.webp", "obverse_bce.json"]
    present = [f for f in files if (src_dir / f).is_file()]
    if not present:
        return _step("move_bce_sidecar", status="skipped", reason="no BCE sidecar on existing row")

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

    # Update coin_canonical_images: row keyed on (eurio_id, source, role).
    # source='bce_comm' per existing convention.
    with conn:
        # Drop any pre-existing canonical for the new row (defensive).
        conn.execute(
            "DELETE FROM coin_canonical_images WHERE eurio_id = ? AND source = ? AND role = ?",
            (new_id, "bce_comm", "obverse"),
        )
        # Re-parent the existing canonical row.
        cur = conn.execute(
            "UPDATE coin_canonical_images SET eurio_id = ?, local_path = ?, url = NULL "
            "WHERE eurio_id = ? AND source = ? AND role = ?",
            (
                new_id,
                f"ml/canonical_images/{new_id}/obverse_bce.webp",
                existing_id,
                "bce_comm",
                "obverse",
            ),
        )
        rewired = cur.rowcount

    return _step(
        "move_bce_sidecar",
        moved_files=moved,
        canonical_rows_rewired=rewired,
        from_=existing_id,
        to=new_id,
    )


def _step_move_sidecars(conn: sqlite3.Connection, case: dict) -> dict:
    """Move BCE sidecars per source_attributions[*].recommended_target=='new'."""
    swap_id: str = case["swap"]["eurio_id"]
    new_id: str = case["new_row"]["eurio_id"]
    bce_target_new = any(
        sa.get("source") == "bce_sidecar" and sa.get("recommended_target") == "new"
        for sa in case.get("source_attributions") or []
    )
    if not bce_target_new:
        return _step("move_bce_sidecar", status="skipped", reason="no BCE attribution with target=new")
    return _move_bce_sidecar(conn, swap_id, new_id)


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


def _step_fetch_numista(conn: sqlite3.Connection, case: dict) -> dict:
    KeyManager = _import_keymanager()
    km = KeyManager()
    targets = [
        (case["swap"]["eurio_id"], case["swap"]["new_numista_id"]),
        (case["new_row"]["eurio_id"], case["new_row"]["numista_id"]),
    ]
    results = []
    failures = []
    for eurio_id, nid in targets:
        try:
            res = _fetch_numista_image(km, eurio_id, nid)
        except Exception as e:
            failures.append({"eurio_id": eurio_id, "numista_id": nid, "error": str(e)[:300]})
            continue
        results.append(res)
        if res["status"] in ("fetched", "already_present"):
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO coin_canonical_images
                        (eurio_id, source, role, url, local_path)
                    VALUES (?, 'numista_api', 'obverse', NULL, ?)
                    """,
                    (eurio_id, f"ml/canonical_images/{eurio_id}/obverse_numista.webp"),
                )
    status = "ok" if not failures else "failed"
    return _step("fetch_numista", status=status, results=results, failures=failures)


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

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 1. Pre-flight (fatal if fails)
        steps.append(_preflight(conn, case))

        # 2. Backup
        backup_path, backup_step = _backup_db(case_id)
        steps.append(backup_step)

        # 3. Mutate eurio.db
        steps.append(_mutate_db(conn, case))

        # 4. Move BCE sidecars (and re-parent coin_canonical_images row)
        steps.append(_step_move_sidecars(conn, case))

        # 5. Fetch Numista image for both rows (existing post-swap + new row)
        try:
            steps.append(_step_fetch_numista(conn, case))
        except Exception as e:
            logger.exception("fetch_numista crashed")
            steps.append(_step("fetch_numista", status="failed", error=str(e)[:300]))
    finally:
        conn.close()

    # 6+7. Push Supabase (non-fatal per decision 2026-05-25)
    steps.append(_push_supabase())

    # 8. Verification
    steps.append(_audit_after())

    finished = datetime.now(timezone.utc)
    fatal_steps = {"preflight", "backup", "mutate_db"}
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
