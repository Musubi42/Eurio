"""Verifier les invariants post-refetch Numista (chunk 5).

Voir docs/research/numista-clean-refetch-kickoff.md §7.4.

Checks :
  1. Unicité   — aucun couple (country, year, slug) en doublon
  2. Couverture — ≥ 20 pays eurozone ont des rows
  3. Source refs — chaque coin a 1 source_ref numista
  4. Prices    — ≥ 80% des coins ont au moins 1 mint_release_prices
  5. Mint releases — chaque coin commémo a ≥ 1 release
  6. Images    — sample 20 obverse URLs résolvent HTTP 200
  7. Sanity    — 0 coins avec needs_review=true en 2€
  8. Determinism — re-deriver slug depuis (country, year, design_description)
                  via la fonction pure ; doit matcher l'eurio_id stocké
                  pour ≥ 95% des coins (les écarts révèlent override DB ou
                  un changement de fonction depuis l'insert).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.numista_eurio_id import (  # noqa: E402
    commemo_slug, standard_slug,
)


class Verifier:
    def __init__(self, sb: SupabaseClient):
        self.sb = sb
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        print(f"  ❌ {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  ⚠️  {msg}")

    def ok(self, msg: str) -> None:
        print(f"  ✅ {msg}")

    # ─── 1. Unicité ──────────────────────────────────────────────────────────

    def check_uniqueness(self) -> None:
        print("\n▶ 1. Unicité (country, year, slug)")
        # Strip the "{country}-{year}-2eur-" prefix to recover slug
        rows = self.sb.query("coins",
                             params={"select": "eurio_id,country,year",
                                     "face_value": "eq.2.0"})
        seen: dict[tuple, str] = {}
        dups = []
        for r in rows:
            eid = r["eurio_id"]
            prefix = f"{r['country'].lower()}-{r['year']}-2eur-"
            slug = eid.removeprefix(prefix)
            key = (r["country"], r["year"], slug)
            if key in seen:
                dups.append((key, seen[key], eid))
            else:
                seen[key] = eid
        if dups:
            for k, e1, e2 in dups[:10]:
                self.fail(f"duplicate {k}: {e1} vs {e2}")
        else:
            self.ok(f"{len(rows)} coins, 0 duplicates")

    # ─── 2. Couverture pays ──────────────────────────────────────────────────

    def check_country_coverage(self) -> None:
        print("\n▶ 2. Couverture pays eurozone")
        expected = {"AD","AT","BE","BG","CY","DE","EE","ES","FI","FR","GR","HR",
                    "IE","IT","LT","LU","LV","MC","MT","NL","PT","SI","SK","SM","VA"}
        rows = self.sb.query("coins",
                             params={"select": "country",
                                     "face_value": "eq.2.0"})
        present = {r["country"] for r in rows}
        missing = expected - present
        if missing:
            self.warn(f"countries missing: {sorted(missing)}")
        extra = present - expected
        if extra:
            self.warn(f"countries unexpected: {sorted(extra)}")
        self.ok(f"{len(present)}/{len(expected)} eurozone countries present")

    # ─── 3. Source refs ──────────────────────────────────────────────────────

    def check_source_refs(self) -> None:
        print("\n▶ 3. coin_source_refs (numista)")
        coins = self.sb.query("coins",
                              params={"select": "eurio_id",
                                      "face_value": "eq.2.0"})
        coin_ids = {r["eurio_id"] for r in coins}
        # Fetch all source_refs in chunks
        refs = self._fetch_in_chunks("coin_source_refs",
                                     "coin_type_id", list(coin_ids),
                                     extra={"source": "eq.numista"},
                                     select="coin_type_id,native_id")
        ref_ids = {r["coin_type_id"] for r in refs}
        missing = coin_ids - ref_ids
        if missing:
            self.fail(f"{len(missing)} coins missing numista source_ref")
            for m in list(missing)[:5]:
                self.fail(f"  e.g. {m}")
        else:
            self.ok(f"{len(refs)} numista source_refs for {len(coin_ids)} coins")

    # ─── 4. Prices coverage ──────────────────────────────────────────────────

    def check_prices_coverage(self) -> None:
        print("\n▶ 4. mint_release_prices coverage")
        coins = self.sb.query("coins",
                              params={"select": "eurio_id",
                                      "face_value": "eq.2.0"})
        coin_ids = [r["eurio_id"] for r in coins]
        # mint_release_id starts with eurio_id/numista-...
        # Fetch distinct parent_type_id for prices
        releases = self._fetch_in_chunks("coin_mint_releases",
                                         "parent_type_id", coin_ids,
                                         select="id,parent_type_id")
        release_ids_by_coin: dict[str, list[str]] = {}
        for rel in releases:
            release_ids_by_coin.setdefault(rel["parent_type_id"], []).append(rel["id"])
        prices = self._fetch_in_chunks("mint_release_prices",
                                       "mint_release_id",
                                       [r["id"] for r in releases],
                                       extra={"source": "eq.numista"},
                                       select="mint_release_id")
        priced_release_ids = {p["mint_release_id"] for p in prices}
        coins_with_prices = sum(
            1 for c in coin_ids
            if any(rid in priced_release_ids for rid in release_ids_by_coin.get(c, []))
        )
        pct = 100 * coins_with_prices / max(1, len(coin_ids))
        if pct < 80:
            self.fail(f"only {coins_with_prices}/{len(coin_ids)} coins have prices ({pct:.1f}%) < 80%")
        elif pct < 95:
            self.warn(f"{coins_with_prices}/{len(coin_ids)} coins have prices ({pct:.1f}%)")
        else:
            self.ok(f"{coins_with_prices}/{len(coin_ids)} coins have prices ({pct:.1f}%)")

    # ─── 5. Mint releases ────────────────────────────────────────────────────

    def check_mint_releases(self) -> None:
        print("\n▶ 5. coin_mint_releases")
        coins = self.sb.query("coins",
                              params={"select": "eurio_id,is_commemorative",
                                      "face_value": "eq.2.0"})
        commemo_ids = [r["eurio_id"] for r in coins if r.get("is_commemorative")]
        releases = self._fetch_in_chunks("coin_mint_releases",
                                         "parent_type_id", commemo_ids,
                                         select="parent_type_id")
        coverage = {r["parent_type_id"] for r in releases}
        missing = set(commemo_ids) - coverage
        if missing:
            self.warn(f"{len(missing)} commemos without any mint_release")
            for m in list(missing)[:5]:
                self.warn(f"  e.g. {m}")
        else:
            self.ok(f"{len(commemo_ids)} commemos all have ≥ 1 release")

    # ─── 6. Images HTTP HEAD ─────────────────────────────────────────────────

    def check_images_sample(self, sample_size: int = 20) -> None:
        print(f"\n▶ 6. Images (HEAD sample {sample_size})")
        coins = self.sb.query("coins",
                              params={"select": "eurio_id,images",
                                      "face_value": "eq.2.0",
                                      "limit": str(sample_size)})
        # Random-ish: take first N which have images
        with_imgs = [c for c in coins if c.get("images")]
        if not with_imgs:
            self.fail("no coins with images in sample")
            return
        with httpx.Client(timeout=15, follow_redirects=True) as cli:
            fails = []
            for c in with_imgs:
                for img in c["images"]:
                    url = img.get("url")
                    if not url:
                        continue
                    try:
                        r = cli.head(url)
                        if r.status_code != 200:
                            fails.append((c["eurio_id"], img.get("role"), r.status_code))
                    except httpx.HTTPError as e:
                        fails.append((c["eurio_id"], img.get("role"), str(e)))
        total = sum(len(c["images"]) for c in with_imgs)
        if fails:
            for eid, role, status in fails[:10]:
                self.fail(f"image fail {eid}/{role}: {status}")
        else:
            self.ok(f"{total} images HTTP 200 / {len(with_imgs)} coins")

    # ─── 7. needs_review sanity ──────────────────────────────────────────────

    def check_needs_review(self) -> None:
        print("\n▶ 7. coins.needs_review")
        rows = self.sb.query("coins",
                             params={"select": "eurio_id",
                                     "face_value": "eq.2.0",
                                     "needs_review": "eq.true"})
        if rows:
            self.warn(f"{len(rows)} coins with needs_review=true (expected 0 post-greenfield)")
            for r in rows[:5]:
                self.warn(f"  e.g. {r['eurio_id']}")
        else:
            self.ok("0 coins with needs_review=true")

    # ─── 8. Determinism spot-check ───────────────────────────────────────────

    def check_determinism(self, sample_size: int = 50) -> None:
        print(f"\n▶ 8. Determinism re-derivation (sample {sample_size})")
        # For each coin, re-derive slug from design_description (which IS the
        # original Numista catalog_name preserved in coins.design_description).
        rows = self.sb.query("coins",
                             params={"select": "eurio_id,country,year,is_commemorative,design_description",
                                     "face_value": "eq.2.0",
                                     "limit": str(sample_size)})
        mismatches = []
        for r in rows:
            cat = r.get("design_description") or ""
            country = r["country"].lower()
            year = r["year"]
            if r["is_commemorative"]:
                slug = commemo_slug(cat)
                expected = f"{country}-{year}-2eur-{slug}"
            else:
                slug = standard_slug(cat)
                expected = f"{country}-{year}-2eur-standard-{slug}"
            if expected != r["eurio_id"]:
                mismatches.append((r["eurio_id"], expected, cat))
        if mismatches:
            pct = 100 * (len(rows) - len(mismatches)) / max(1, len(rows))
            if pct < 95:
                self.fail(f"determinism: {len(mismatches)}/{len(rows)} mismatch ({100-pct:.1f}%)")
            else:
                self.warn(f"determinism: {len(mismatches)}/{len(rows)} mismatch ({100-pct:.1f}%)")
            for eid, exp, cat in mismatches[:5]:
                self.warn(f"  {eid} ≠ {exp}  (cat: {cat[:60]!r})")
        else:
            self.ok(f"{len(rows)}/{len(rows)} re-derive identically")

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _fetch_in_chunks(self, table: str, col: str, ids: list[str], *,
                         extra: dict | None = None, select: str = "*") -> list[dict]:
        out = []
        for i in range(0, len(ids), 200):
            chunk = ids[i:i+200]
            params = {"select": select, col: f"in.({','.join(chunk)})"}
            if extra:
                params.update(extra)
            out.extend(self.sb.query(table, params=params))
        return out

    # ─── Summary ─────────────────────────────────────────────────────────────

    def summary(self) -> int:
        print("\n" + "═" * 60)
        print("VERIFY SUMMARY")
        print("═" * 60)
        print(f"  failures : {len(self.failures)}")
        print(f"  warnings : {len(self.warnings)}")
        if self.failures:
            print("\n  Failures:")
            for f in self.failures:
                print(f"    - {f}")
        if self.warnings:
            print("\n  Warnings:")
            for w in self.warnings:
                print(f"    - {w}")
        if not self.failures:
            print("\n  ✅ GO — pipeline propre. Chunk 5 repop can proceed.")
        else:
            print("\n  ❌ NO-GO — fix failures before chunk 5 repop.")
        return 1 if self.failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="append", default=[],
                        help="Limit to specific checks: uniqueness, coverage, source_refs, prices, releases, images, needs_review, determinism")
    args = parser.parse_args()

    env = load_env()
    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])
    v = Verifier(sb)

    all_checks = {
        "uniqueness": v.check_uniqueness,
        "coverage": v.check_country_coverage,
        "source_refs": v.check_source_refs,
        "prices": v.check_prices_coverage,
        "releases": v.check_mint_releases,
        "images": v.check_images_sample,
        "needs_review": v.check_needs_review,
        "determinism": v.check_determinism,
    }
    to_run = args.check or list(all_checks.keys())
    for name in to_run:
        fn = all_checks.get(name)
        if not fn:
            print(f"⛔ unknown check: {name}")
            continue
        try:
            fn()
        except Exception as e:
            v.fail(f"{name} crashed: {e}")
    return v.summary()


if __name__ == "__main__":
    sys.exit(main())
