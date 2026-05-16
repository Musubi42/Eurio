"""Orchestrateur refetch Numista 2€ → Supabase (chunk 3 bench AD, chunk 4 full).

Voir docs/research/numista-clean-refetch-kickoff.md §6 et
docs/research/numista-clean-refetch-progress.md.

Pipeline par pays (--country AD … --country DE …) :
  1. Search /v3/types?issuer={iso}&face_value=2 (paginé)
  2. Pour chaque type retourné :
     a. /v3/types/{nid} → metadata complète
     b. /v3/types/{nid}/issues → liste mint_releases
     c. /v3/types/{nid}/issues/{iid}/prices?currency=EUR (par issue)
     d. eurio_id via numista_eurio_id.eurio_id_from_numista_payload()
  3. Transformations + UPSERT vers Supabase (coins, coin_source_refs,
     coin_mint_releases, mint_release_prices, design_groups)
  4. Images : download obverse+reverse → encode WebP → upload Storage
  5. Stats finales : counts SQL + coût quota réel + collisions/skipped

Variants : si une nid Numista détecte un variant_finish, on tente d'attacher
au parent classic du même (country, year, denom) dans CE batch. Sinon flag
`needs_review=true` sur le parent provisoire (un coin créé avec le slug
parent + variant_finish notée dans review_payload), pour résolution humaine.

Usage :
  python refetch_numista_2eur.py --country AD --dry-run
  python refetch_numista_2eur.py --country AD --apply
  python refetch_numista_2eur.py --country AD --country MC --apply
  python refetch_numista_2eur.py --all-eurozone --apply --skip-prices
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.coin_image_storage import (  # noqa: E402
    BUCKET_NAME, encode_webp, public_url, storage_key, upload_object,
)
from referential.numista_eurio_id import (  # noqa: E402
    NumistaSlugResult, eurio_id_from_numista_payload, joint_design_group_id,
)
from referential.numista_keys import KeyManager  # noqa: E402


API_BASE = "https://api.numista.com/v3"
DELAY = 0.4
STATE_PATH = ML_DIR / "state" / "refetch_state.json"

# Eurozone 21 + micro-states using EUR
ALL_EUROZONE = [
    "AD", "AT", "BE", "BG", "CY", "DE", "EE", "ES", "FI", "FR",
    "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MC", "MT", "NL",
    "PT", "SI", "SK", "SM", "VA",
]

# Numista uses string slugs (mostly French) as issuer codes, not ISO2.
# Map curated 2026-05-16 from GET /v3/issuers (canonical entries — `*_section`
# variants are placeholders, skipped).
NUMISTA_ISSUER_CODE: dict[str, str] = {
    "AD": "andorre",      "AT": "austria",     "BE": "belgium",
    "BG": "bulgarie",     "HR": "croatia",     "CY": "chypre",
    "EE": "estonie",      "FI": "finlande",    "FR": "france",
    "DE": "allemagne",    "GR": "greece",      "IE": "irlande",
    "IT": "italy",        "LV": "lettonie",    "LT": "lituanie",
    "LU": "luxembourg",   "MT": "malte",       "MC": "monaco",
    "NL": "netherlands",  "PT": "portugal",    "SM": "saint-marin",
    "SK": "slovaquie",    "SI": "slovenie",    "ES": "spain",
    "VA": "vatican",
    # `germany` and `lithuania` in Numista resolve to historic issuers
    # (Pomerania, Saxony… / Grand Duchy / placeholders). Modern Federal
    # Republic uses the FR labels `allemagne` and `lituanie`.
}

GRADE_RAW_TO_EURIO = {
    "unc": "UNC",
    "au": "TTB", "xf": "TTB",
    "vf": "TB", "f": "TB", "vg": "TB",
    "g": None,   # ignored
}


# ─── Numista API wrappers (called via KeyManager.call) ──────────────────────


def api_search(api_key: str, issuer: str, page: int = 1, count: int = 50) -> dict:
    resp = httpx.get(
        f"{API_BASE}/types",
        params={
            "q": "2 euros",
            "issuer": issuer.lower(),
            "category": "coin",
            "count": count,
            "page": page,
            "lang": "en",
        },
        headers={"Numista-API-Key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def api_type_details(api_key: str, nid: int) -> dict:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}",
        params={"lang": "en"},
        headers={"Numista-API-Key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def api_type_issues(api_key: str, nid: int) -> dict:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}/issues",
        params={"lang": "en"},
        headers={"Numista-API-Key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def api_issue_prices(api_key: str, nid: int, iid: int) -> dict:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}/issues/{iid}/prices",
        params={"currency": "EUR", "lang": "en"},
        headers={"Numista-API-Key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Image download + Storage upload ─────────────────────────────────────────


def download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except httpx.HTTPError as e:
        print(f"      image dl error: {e}")
    return None


def upload_role(
    sb_client: httpx.Client, supabase_url: str,
    eurio_id: str, role: str, raw: bytes,
) -> str | None:
    """Encode WebP detail + thumb, upload, return public URL of detail."""
    try:
        detail, w, h = encode_webp(raw, max_width=600, quality=90)
        thumb, _, _ = encode_webp(raw, max_width=120, quality=80)
    except Exception as e:
        print(f"      encode FAIL {eurio_id}/{role}: {e}")
        return None
    k_detail = storage_key(eurio_id, role, "numista", thumb=False)
    k_thumb = storage_key(eurio_id, role, "numista", thumb=True)
    if not upload_object(sb_client, supabase_url, k_detail, detail):
        return None
    upload_object(sb_client, supabase_url, k_thumb, thumb)
    return public_url(supabase_url, k_detail)


# ─── Transformations ─────────────────────────────────────────────────────────


def coin_row_from_slug(slug: NumistaSlugResult, payload: dict,
                       images: dict[str, str]) -> dict:
    """Build a coins INSERT payload."""
    today = date.today().isoformat()
    return {
        "eurio_id": slug.eurio_id,
        "country": slug.country,
        "year": slug.year,
        "face_value": slug.face_value,
        "currency": "EUR",
        "is_commemorative": slug.is_commemorative,
        "collector_only": False,
        "is_withdrawn": False,
        "personal_owned": False,
        "needs_review": False,
        "theme": slug.theme,
        "design_description": slug.catalog_name,
        "images": {
            # Dict shape expected by export_catalog_snapshot.py — {role: [{source, url}, ...]}
            role: [{"source": "numista", "url": u}]
            for role, u in images.items() if u
        },
        "cross_refs": {"numista_id": int(payload["id"])},
        "sources_used": ["numista"],
        "design_group_id": slug.design_group_id,
        "first_seen": today,
    }


def source_ref_row(slug: NumistaSlugResult, payload: dict) -> dict:
    nid = int(payload["id"])
    return {
        "coin_type_id": slug.eurio_id,
        "source": "numista",
        "native_id": str(nid),
        "native_url": f"https://en.numista.com/catalogue/pieces{nid}.html",
    }


def _detect_issue_type(comment: str | None) -> str:
    """Infer issue_type from Numista issue comment.

    Numista doesn't expose a structured BU/BE/PROOF field — it's embedded in
    the comment string. Heuristic with safe CIRC default.
    """
    if not comment:
        return "CIRC"
    low = comment.lower()
    if "proof" in low or "be " in low or low.endswith(" be"):
        return "PROOF"
    if "bu" in low or "coincard" in low or "uncirculated" in low:
        return "BU"
    return "CIRC"


def mint_release_row(eurio_id: str, issue: dict) -> dict:
    iid = issue.get("id")
    comment = issue.get("comment")
    return {
        "id": f"{eurio_id}/numista-{iid}",
        "parent_type_id": eurio_id,
        "mint_year": issue.get("gregorian_year") or issue.get("year") or 0,
        "mint_mark": issue.get("mint_letter") or None,
        "issue_type": _detect_issue_type(comment),
        "mintage": issue.get("mintage") or None,
        "released_on": None,
        "notes": comment or None,
    }


def price_rows(mint_release_id: str, prices_payload: dict) -> list[dict]:
    out = []
    now = datetime.now(timezone.utc).isoformat()
    for entry in prices_payload.get("prices", []):
        gr = entry.get("grade", "").lower()
        if gr not in GRADE_RAW_TO_EURIO:
            continue
        price = entry.get("price")
        if price is None:
            continue
        out.append({
            "mint_release_id": mint_release_id,
            "source": "numista",
            "grade_raw": gr,
            "grade_eurio": GRADE_RAW_TO_EURIO[gr],
            "price": price,
            "currency": prices_payload.get("currency", "EUR"),
            "fetched_at": now,
        })
    return out


def design_group_row(slug: NumistaSlugResult) -> dict | None:
    if not slug.is_joint_issue or not slug.design_group_id:
        return None
    return {
        "id": slug.design_group_id,
        "designation": slug.joint_designation,
        "description": (
            "Bootstrap from numista clean refetch 2026-05-16. "
            "Joint commemorative issue across eurozone members."
        ),
    }


# ─── Orchestrator core ──────────────────────────────────────────────────────


class Bench:
    def __init__(self, sb: SupabaseClient, km: KeyManager, *,
                 dry_run: bool, skip_prices: bool, skip_images: bool):
        self.sb = sb
        self.km = km
        self.dry_run = dry_run
        self.skip_prices = skip_prices
        self.skip_images = skip_images
        self.stats: Counter = Counter()
        self.collected_coins: list[dict] = []
        self.collected_source_refs: list[dict] = []
        self.collected_mint_releases: list[dict] = []
        self.collected_prices: list[dict] = []
        self.collected_design_groups: dict[str, dict] = {}
        self.collected_variants: list[dict] = []
        self.needs_review: list[dict] = []
        self.skipped: list[dict] = []
        self.slug_by_nid: dict[int, NumistaSlugResult] = {}
        self.payloads_by_nid: dict[int, dict] = {}
        self.images_by_nid: dict[int, dict[str, str]] = {}
        self.supabase_url = sb.url
        self._http_storage = httpx.Client(
            headers={
                "apikey": sb._headers["apikey"],
                "Authorization": sb._headers["Authorization"],
            },
            timeout=30,
        )

    def fetch_country(self, iso: str) -> None:
        issuer_code = NUMISTA_ISSUER_CODE.get(iso.upper())
        if not issuer_code:
            print(f"\n⛔ {iso}: no Numista issuer code mapping, skipping")
            self.skipped.append({"country": iso, "reason": "no_numista_issuer_code"})
            return
        print(f"\n▶ Country {iso.upper()} (numista issuer={issuer_code})")
        # 1. Search (paginated)
        page = 1
        all_types: list[dict] = []
        while True:
            time.sleep(DELAY)
            try:
                result = self.km.call(api_search, issuer_code, page=page)
            except Exception as e:
                print(f"  search error page {page}: {e}")
                break
            self.stats["api_search"] += 1
            types = result.get("types", [])
            if not types:
                break
            all_types.extend(types)
            print(f"  page {page}: +{len(types)} (cum {len(all_types)}/{result.get('count', '?')})")
            if len(all_types) >= result.get("count", 0):
                break
            page += 1
        print(f"  total search hits: {len(all_types)}")

        # 2. Per type — details + slug + issues + prices + images
        for t in all_types:
            nid = t.get("id")
            time.sleep(DELAY)
            try:
                payload = self.km.call(api_type_details, nid)
            except Exception as e:
                print(f"  [{nid}] details error: {e}")
                self.skipped.append({"nid": nid, "reason": f"details error: {e}"})
                continue
            self.stats["api_type_details"] += 1
            self._process_type(payload)

    def _process_type(self, payload: dict) -> None:
        nid = payload.get("id")
        slug = eurio_id_from_numista_payload(payload)
        if slug is None:
            self.skipped.append({
                "nid": nid,
                "reason": "out_of_scope (non-2€ or missing field)",
                "title": payload.get("title"),
            })
            self.stats["skipped_out_of_scope"] += 1
            return

        # Detect variant — for the bench AD, attach to parent if exists in batch
        if slug.is_variant:
            self.needs_review.append({
                "nid": nid,
                "slug": asdict(slug),
                "reason": "variant_finish detected, parent classic not yet bound (chunk 4 handles)",
            })
            self.stats["needs_review_variant"] += 1
            # Still record it so we can resolve in chunk 4
            return

        # Collision check within batch
        if slug.eurio_id in {c["eurio_id"] for c in self.collected_coins}:
            self.needs_review.append({
                "nid": nid,
                "slug": asdict(slug),
                "reason": "in-batch collision on eurio_id",
            })
            self.stats["needs_review_collision"] += 1
            return

        self.payloads_by_nid[nid] = payload
        self.slug_by_nid[nid] = slug

        # Joint-issue design_group
        dg = design_group_row(slug)
        if dg and dg["id"] not in self.collected_design_groups:
            self.collected_design_groups[dg["id"]] = dg

        # Fetch issues + prices
        self._fetch_issues_and_prices(slug, payload)

        # Download images
        images = self._fetch_images(slug, payload)
        self.images_by_nid[nid] = images

        # Build rows
        self.collected_coins.append(coin_row_from_slug(slug, payload, images))
        self.collected_source_refs.append(source_ref_row(slug, payload))
        self.stats["coins_built"] += 1

    def _fetch_issues_and_prices(self, slug: NumistaSlugResult, payload: dict) -> None:
        nid = payload["id"]
        time.sleep(DELAY)
        try:
            issues_data = self.km.call(api_type_issues, nid)
        except Exception as e:
            print(f"  [{nid}] issues error: {e}")
            return
        self.stats["api_issues"] += 1
        # Numista /issues returns either a list directly or a dict with "issues" key
        if isinstance(issues_data, list):
            issues = issues_data
        else:
            issues = issues_data.get("issues", [])
        for issue in issues:
            mr = mint_release_row(slug.eurio_id, issue)
            self.collected_mint_releases.append(mr)
            self.stats["mint_releases_built"] += 1
            if self.skip_prices:
                continue
            iid = issue.get("id")
            time.sleep(DELAY)
            try:
                prices = self.km.call(api_issue_prices, nid, iid)
            except Exception as e:
                if "404" in str(e):
                    self.stats["prices_404"] += 1
                else:
                    print(f"  [{nid}/{iid}] prices error: {e}")
                continue
            self.stats["api_prices"] += 1
            rows = price_rows(mr["id"], prices)
            self.collected_prices.extend(rows)
            self.stats["price_rows_built"] += len(rows)

    def _fetch_images(self, slug: NumistaSlugResult, payload: dict) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.skip_images:
            return out
        for role in ("obverse", "reverse"):
            face = payload.get(role) or {}
            url = face.get("picture")
            if not url:
                continue
            raw = download_image(url)
            self.stats[f"img_dl_{role}"] += 1
            if raw is None:
                self.stats[f"img_dl_fail_{role}"] += 1
                continue
            if self.dry_run:
                # In dry-run we still count it but don't upload
                out[role] = f"<would-upload {len(raw)}b>"
                continue
            public = upload_role(self._http_storage, self.supabase_url,
                                 slug.eurio_id, role, raw)
            if public:
                out[role] = public
                self.stats[f"img_uploaded_{role}"] += 1
        return out

    def apply_to_supabase(self) -> None:
        """UPSERT all collected rows. Idempotent."""
        # design_groups first (FK target)
        if self.collected_design_groups:
            self.sb.upsert("design_groups",
                           rows=list(self.collected_design_groups.values()),
                           on_conflict="id")
            print(f"  ✓ design_groups: {len(self.collected_design_groups)}")
        # coins
        if self.collected_coins:
            self.sb.upsert("coins", rows=self.collected_coins, on_conflict="eurio_id")
            print(f"  ✓ coins: {len(self.collected_coins)}")
        # source_refs
        if self.collected_source_refs:
            self.sb.upsert("coin_source_refs",
                           rows=self.collected_source_refs,
                           on_conflict="coin_type_id,source,native_id")
            print(f"  ✓ coin_source_refs: {len(self.collected_source_refs)}")
        # mint_releases
        if self.collected_mint_releases:
            self.sb.upsert("coin_mint_releases",
                           rows=self.collected_mint_releases,
                           on_conflict="id")
            print(f"  ✓ coin_mint_releases: {len(self.collected_mint_releases)}")
        # prices
        if self.collected_prices:
            self.sb.upsert("mint_release_prices",
                           rows=self.collected_prices,
                           on_conflict="mint_release_id,source,grade_raw,fetched_at")
            print(f"  ✓ mint_release_prices: {len(self.collected_prices)}")

    def print_summary(self, countries: list[str]) -> None:
        print("\n" + "═" * 60)
        print(f"SUMMARY — countries={','.join(countries)} dry_run={self.dry_run}")
        print("═" * 60)
        for k, v in sorted(self.stats.items()):
            print(f"  {k:.<45} {v}")
        print(f"  skipped (non-2€/missing-fields): {len(self.skipped)}")
        print(f"  needs_review entries: {len(self.needs_review)}")
        # Sample coin
        if self.collected_coins:
            print("\n  ▶ Sample coin (first):")
            sample = self.collected_coins[0]
            print(json.dumps({k: v for k, v in sample.items() if k != "images"}, indent=4, default=str))
            print(f"    images: {sample.get('images')}")
        # Quota status
        print("\n  ▶ Quota status (per-key):")
        for s in self.km.status():
            print(f"    slot {s['slot']:>2}  calls={s['calls_this_month']:>5}  "
                  f"remaining={s['remaining']:>5}  exhausted={s['exhausted']}")

    def save_state(self, countries: list[str]) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "countries": countries,
            "dry_run": self.dry_run,
            "stats": dict(self.stats),
            "needs_review": self.needs_review,
            "skipped": self.skipped,
            "design_groups_count": len(self.collected_design_groups),
            "coins_count": len(self.collected_coins),
            "mint_releases_count": len(self.collected_mint_releases),
            "prices_count": len(self.collected_prices),
            "quota_status": self.km.status(),
        }
        STATE_PATH.write_text(json.dumps(state, indent=2, default=str, ensure_ascii=False))
        print(f"\n✓ State written: {STATE_PATH.relative_to(ML_DIR.parent)}")


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--country", action="append", default=[],
                        help="ISO2 country code (repeatable)")
    parser.add_argument("--all-eurozone", action="store_true",
                        help="Fetch all 25 eurozone+micro-state codes")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="Fetch + transform but don't write to Supabase/Storage")
    g.add_argument("--apply", action="store_true",
                   help="Fetch + write")
    parser.add_argument("--skip-prices", action="store_true",
                        help="Skip /issues/{iid}/prices fetch (save ~75% of quota)")
    parser.add_argument("--skip-images", action="store_true",
                        help="Skip image download + upload")
    args = parser.parse_args()

    countries = args.country or (ALL_EUROZONE if args.all_eurozone else [])
    if not countries:
        print("⛔ no country given. Use --country AD or --all-eurozone.")
        return 2
    countries = [c.upper() for c in countries]

    env = load_env()
    # Inject Numista keys into os.environ for KeyManager
    import os
    for k, v in env.items():
        if k.startswith("NUMISTA_API_KEY"):
            os.environ.setdefault(k, v)

    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])
    km = KeyManager()

    print(f"▶ REFETCH start {datetime.now(timezone.utc).isoformat()}")
    print(f"  countries: {countries}")
    print(f"  dry_run={args.dry_run}  skip_prices={args.skip_prices}  skip_images={args.skip_images}")
    print(f"  keys available: {len(km._keys)}")

    bench = Bench(sb, km,
                  dry_run=args.dry_run,
                  skip_prices=args.skip_prices,
                  skip_images=args.skip_images)

    for iso in countries:
        bench.fetch_country(iso)

    bench.print_summary(countries)

    if args.apply:
        print("\n▶ APPLY → Supabase upserts")
        bench.apply_to_supabase()

    bench.save_state(countries)
    print("\n✅ Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
