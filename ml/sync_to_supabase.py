"""Push the canonical referential JSON to Supabase — Phase 2C.7.

Reads `ml/datasets/eurio_referential.json` and the supporting state files
(`review_queue.json`, `matching_log.jsonl`), then upserts everything into the
6 canonical tables : `coins`, `source_observations`, `matching_decisions`,
`review_queue`, `coin_embeddings`, `user_collections`.

Flattening rules (referential → DB) :

    coins                  : one row per eurio_id with identity + images + cross_refs
    source_observations    : one row per (eurio_id, source, source_native_id, type)
                             where type ∈ {variant, issue_price, market_stats, mintage, image}
    matching_decisions     : one row per jsonl line in matching_log.jsonl
    review_queue           : one row per item in review_queue.json

The sync is idempotent :
- `coins` upserts on `eurio_id` PK
- `source_observations` upserts on the (eurio_id, source, source_native_id,
  observation_type) unique constraint
- `review_queue` upserts on (source, source_native_id, reason) unique
- `matching_decisions` is append-only and uses `--full` to reset before
  re-inserting from the log (otherwise it accumulates endlessly)

Uses the **service role** key so RLS is bypassed; the app will use the
anon key for reads, which is allowed by the public-read policies.

Usage :
    python ml/sync_to_supabase.py              # sync everything
    python ml/sync_to_supabase.py --dry-run    # just print stats
    python ml/sync_to_supabase.py --coins-only
    python ml/sync_to_supabase.py --no-reset-decisions
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from eurio_referential import load_referential
from review_core import (
    MATCHING_LOG_PATH,
    REVIEW_QUEUE_PATH,
    load_queue,
)

DATASETS_DIR = Path(__file__).parent / "datasets"

# Batch size used for every upsert — PostgREST caps large payloads, 500 is
# a safe middle ground that keeps the number of HTTP round-trips small.
UPSERT_BATCH_SIZE = 500


# ---------- env ----------


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


# ---------- PostgREST client ----------


class PostgrestClient:
    """Minimal PostgREST client with upsert and delete helpers."""

    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self._client = httpx.Client(
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=60,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PostgrestClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def upsert(
        self,
        table: str,
        rows: list[dict],
        *,
        on_conflict: str | None = None,
    ) -> None:
        """Upsert rows into a table. PostgREST supports batching natively."""
        if not rows:
            return
        for i in range(0, len(rows), UPSERT_BATCH_SIZE):
            batch = rows[i : i + UPSERT_BATCH_SIZE]
            headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
            params: dict[str, str] = {}
            if on_conflict:
                params["on_conflict"] = on_conflict
            resp = self._client.post(
                f"{self.base}/{table}",
                json=batch,
                headers=headers,
                params=params,
            )
            if resp.status_code >= 400:
                print(f"  FAIL batch {i}-{i+len(batch)}: HTTP {resp.status_code}")
                print(f"  {resp.text[:400]}")
                resp.raise_for_status()

    def delete_all(self, table: str) -> None:
        """Wipe a whole table. PostgREST requires a filter, we pass a tautology."""
        resp = self._client.delete(
            f"{self.base}/{table}",
            params={"id": "gt.0"},  # works for bigserial PK
        )
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"delete_all {table} failed: {resp.text}",
                request=resp.request,
                response=resp,
            )

    def count(self, table: str) -> int:
        resp = self._client.get(
            f"{self.base}/{table}",
            params={"select": "count"},
            headers={"Prefer": "count=exact"},
        )
        resp.raise_for_status()
        hdr = resp.headers.get("content-range") or ""
        if "/" in hdr:
            return int(hdr.rsplit("/", 1)[1])
        return 0


# ---------- flatteners ----------


def referential_to_coins_rows(referential: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in referential.values():
        ident = entry["identity"]
        prov = entry.get("provenance") or {}
        rows.append(
            {
                "eurio_id": entry["eurio_id"],
                "country": ident["country"],
                "year": ident["year"],
                "face_value": float(ident["face_value"]),
                "currency": ident.get("currency") or "EUR",
                "is_commemorative": bool(ident.get("is_commemorative")),
                "collector_only": bool(ident.get("collector_only")),
                "theme": ident.get("theme"),
                "design_description": ident.get("design_description"),
                "national_variants": ident.get("national_variants"),
                "images": entry.get("images") or [],
                "cross_refs": entry.get("cross_refs") or {},
                "sources_used": prov.get("sources_used") or [],
                "needs_review": bool(prov.get("needs_review")),
                "review_reason": prov.get("review_reason"),
                "first_seen": prov.get("first_seen") or date.today().isoformat(),
                "last_updated": prov.get("last_updated") or date.today().isoformat(),
            }
        )
    return rows


def referential_to_observations_rows(referential: dict[str, dict]) -> list[dict]:
    """Flatten observations into one row per (source, source_native_id, type).

    We explicitly enumerate the known observation shapes rather than dumping
    the whole `observations` dict, so the DB rows stay queryable per-type.
    """
    rows: list[dict] = []
    for entry in referential.values():
        eurio_id = entry["eurio_id"]
        obs = entry.get("observations") or {}

        wiki = obs.get("wikipedia")
        if isinstance(wiki, dict):
            rows.append(
                {
                    "eurio_id": eurio_id,
                    "source": "wikipedia",
                    "source_native_id": None,
                    "observation_type": "mintage",
                    "payload": wiki,
                }
            )

        lmdlp_variants = obs.get("lmdlp_variants") or []
        for v in lmdlp_variants:
            rows.append(
                {
                    "eurio_id": eurio_id,
                    "source": "lmdlp",
                    "source_native_id": v.get("sku"),
                    "observation_type": "variant",
                    "payload": v,
                }
            )

        lmdlp_mintage = obs.get("lmdlp_mintage")
        if isinstance(lmdlp_mintage, dict):
            rows.append(
                {
                    "eurio_id": eurio_id,
                    "source": "lmdlp",
                    "source_native_id": None,
                    "observation_type": "mintage",
                    "payload": lmdlp_mintage,
                }
            )

        mdp_issue = obs.get("mdp_issue") or []
        for v in mdp_issue:
            rows.append(
                {
                    "eurio_id": eurio_id,
                    "source": "mdp",
                    "source_native_id": v.get("sku"),
                    "observation_type": "issue_price",
                    "payload": v,
                }
            )

        ebay_market = obs.get("ebay_market")
        if isinstance(ebay_market, dict):
            rows.append(
                {
                    "eurio_id": eurio_id,
                    "source": "ebay",
                    "source_native_id": None,
                    "observation_type": "market_stats",
                    "payload": ebay_market,
                }
            )
    return rows


def matching_log_to_rows(path: Path) -> list[dict]:
    """Parse matching_log.jsonl into matching_decisions rows."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            stage = rec.get("stage")
            method = f"stage{stage}_{rec.get('reason', 'unknown')}" if stage else "unknown"
            # Human-review entries carry action=pick|skip|no_match instead of stage
            if stage == "human_review" or rec.get("stage") == "human_review":
                method = f"stage5_human_{rec.get('action', 'unknown')}"
            rows.append(
                {
                    "source": rec.get("source"),
                    "source_native_id": rec.get("sku") or rec.get("source_native_id") or rec.get("url"),
                    "eurio_id": rec.get("eurio_id"),
                    "method": method,
                    "confidence": rec.get("confidence"),
                    "runner_up": rec.get("runner_up"),
                    "decided_at": rec.get("sampled_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
    return rows


def queue_to_review_rows(queue: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in queue:
        rows.append(
            {
                "source": item.get("source"),
                "source_native_id": item.get("source_native_id"),
                "raw_payload": item.get("raw_payload") or {},
                "candidates": item.get("candidates"),
                "reason": item.get("reason") or "unknown",
                "created_at": item.get("queued_at") or datetime.now(timezone.utc).isoformat(),
                "resolved": bool(item.get("resolved")),
                "resolution": item.get("resolution"),
            }
        )
    return rows


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Sync Eurio referential JSON to Supabase")
    ap.add_argument("--dry-run", action="store_true", help="Print stats but don't hit the DB")
    ap.add_argument("--coins-only", action="store_true", help="Only sync coins (skip obs/queue/decisions)")
    ap.add_argument(
        "--no-reset-decisions",
        action="store_true",
        help="Don't wipe matching_decisions before re-inserting (default is to reset)",
    )
    return ap.parse_args()


def chunks(it: Iterable[Any], size: int) -> Iterable[list[Any]]:
    buf: list[Any] = []
    for x in it:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def main() -> None:
    args = parse_args()

    referential = load_referential()
    coins_rows = referential_to_coins_rows(referential)
    obs_rows = referential_to_observations_rows(referential)
    queue = load_queue()
    queue_rows = queue_to_review_rows(queue)
    decisions_rows = matching_log_to_rows(MATCHING_LOG_PATH)

    print("Source counts :")
    print(f"  coins            : {len(coins_rows)}")
    print(f"  observations     : {len(obs_rows)}")
    print(f"  review_queue     : {len(queue_rows)}")
    print(f"  matching_decisions: {len(decisions_rows)}")

    if args.dry_run:
        print("\n[dry-run] no HTTP calls.")
        return

    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from .env")
        sys.exit(1)

    with PostgrestClient(url, key) as client:
        print("\nUpserting coins...")
        client.upsert("coins", coins_rows, on_conflict="eurio_id")
        print(f"  coins upserted: {client.count('coins')}")

        if args.coins_only:
            return

        print("\nUpserting source_observations...")
        client.upsert(
            "source_observations",
            obs_rows,
            on_conflict="eurio_id,source,source_native_id,observation_type",
        )
        print(f"  source_observations now: {client.count('source_observations')}")

        print("\nUpserting review_queue...")
        client.upsert(
            "review_queue",
            queue_rows,
            on_conflict="source,source_native_id,reason",
        )
        print(f"  review_queue now: {client.count('review_queue')}")

        if not args.no_reset_decisions:
            print("\nResetting matching_decisions table...")
            client.delete_all("matching_decisions")
        print("Upserting matching_decisions...")
        client.upsert("matching_decisions", decisions_rows)
        print(f"  matching_decisions now: {client.count('matching_decisions')}")

    print("\n" + "=" * 60)
    print("Sync complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
