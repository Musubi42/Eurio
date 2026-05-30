"""Refetch Numista 2€ → SQLite (eurio.db) — orchestrateur cohorte-keyed.

Chunk P.7 du chantier coin-richness. Remplace l'ancien
``ml/referential/refetch_numista_2eur.py`` (Supabase-target) par une version
SQLite-only, alignée sur la doctrine ``SQLite-only`` + ``provenance
first-class`` (cf. ROADMAP-DB.md §2).

**Scope P.7a (cette étape)** : scaffold uniquement.

  - CLI ``--nids-file``, ``--dry-run`` / ``--apply``, ``--skip-prices``,
    ``--skip-images``, ``--cache-dir``.
  - Parse ``cohort_validation_19.txt`` : un NID par ligne, commentaires
    ``# …`` et lignes vides autorisés.
  - KeyManager wiring (status printing — RuntimeError tolerated when no
    keys configured pour permettre l'exécution scaffold sans secrets).
  - Plan printer : count NIDs, ~3*N calls estimés, slots de clé visibles.

  Pas encore : HTTP, transform, écriture DB. Ces étapes arrivent en P.7b
  (fetch + cache), P.7c (transform + DB writes), P.7d (tests fixtures).

Sous-étapes prévues post-P.7a — résumées ici pour mémoire ::

  P.7b  Fetch HTTP 3 endpoints (types/{nid}, /issues, /issues/{iid}/prices),
        cache JSON sur disque (cache-dir), rotation clés via KeyManager.
  P.7c  Transform payloads → rows DB. Cibles : coins, coin_source_refs,
        coin_mint_releases, mint_release_prices, coin_market_quotes
        (Type-level agrégé), coin_canonical_images, coin_credits,
        coin_observations (mintage/JOUE/theme), design_groups, coin_variants.
        Vocabulaire registry (source='numista_api'). Idempotent (UPSERT sur
        UNIQUE).
  P.7d  Tests pytest avec fixtures payloads Numista réels stockés en
        ``ml/tests/fixtures/numista/<nid>.json``.

**Usage cible (post-P.7d)** ::

    go-task ml:refetch-numista -- --nids-file ml/state/cohort_validation_19.txt --apply

⚠️ Kickoff §9 interdit le live fetch sur > 1 pièce avant V.1. Le mode
``--apply`` ne sera **pas** invoqué live durant la session P.7.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


API_BASE = "https://api.numista.com/v3"
REQUEST_DELAY_S = 0.4   # politeness — Numista WAF tolère mais 1+/s vaut mieux
HTTP_TIMEOUT = 20


# ─── Numista API wrappers (key injected by KeyManager.call) ────────────────


def api_type_details(api_key: str, nid: int, lang: str = "en") -> dict:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}",
        params={"lang": lang},
        headers={"Numista-API-Key": api_key},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def api_type_issues(api_key: str, nid: int) -> dict | list:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}/issues",
        params={"lang": "en"},
        headers={"Numista-API-Key": api_key},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def api_issue_prices(api_key: str, nid: int, iid: int) -> dict:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}/issues/{iid}/prices",
        params={"currency": "EUR", "lang": "en"},
        headers={"Numista-API-Key": api_key},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Cache helpers ────────────────────────────────────────────────────────


def _cache_paths(cache_dir: Path, nid: int) -> dict[str, Path]:
    """Layout : {cache_dir}/{nid}/type.json, type_fr.json, issues.json, prices_{iid}.json."""
    nid_dir = cache_dir / str(nid)
    return {
        "dir": nid_dir,
        "type": nid_dir / "type.json",
        "type_fr": nid_dir / "type_fr.json",
        "issues": nid_dir / "issues.json",
    }


def _price_cache_path(cache_dir: Path, nid: int, iid: int) -> Path:
    return cache_dir / str(nid) / f"prices_{iid}.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _extract_issues(payload: Any) -> list[dict]:
    """Numista /issues retourne parfois une list, parfois {'issues': [...]}.
    Normalise."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("issues", []) or []
    return []


# ─── Fetcher — orchestrate API + cache ───────────────────────────────────


@dataclass
class FetchBundle:
    """Snapshot des 3 endpoints Numista pour un NID.

    ``type_payload`` est en EN (canon historique pour les writers existants).
    ``type_payload_fr`` est en FR, fetché en plus pour alimenter
    ``coin_names_i18n`` (titres traduits Numista natifs FR+EN).
    """
    nid: int
    type_payload: dict
    issues_payload: Any
    # iid -> prices_payload. Vide si --skip-prices ou si pas d'issues.
    prices_by_iid: dict[int, dict] = field(default_factory=dict)
    type_payload_fr: dict | None = None


@dataclass
class FetchStats:
    api_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


class Fetcher:
    """Orchestre les calls Numista pour un NID avec cache disque idempotent.

    Politique :
    - Si le fichier cache existe et que ``refresh=False`` → load disk, no API.
    - Sinon → call API via ``KeyManager.call`` (rotation 429 automatique),
      write to cache.
    - ``time.sleep(REQUEST_DELAY_S)`` entre 2 calls API (pas entre 2 cache hits).
    """

    def __init__(self, km, cache_dir: Path, *, refresh: bool = False) -> None:
        self.km = km
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.stats = FetchStats()

    def _get_cached_or_fetch(
        self, cache_path: Path, fn, *args
    ) -> Any:
        if cache_path.exists() and not self.refresh:
            self.stats.cache_hits += 1
            return _read_json(cache_path)
        # Politeness delay between API calls.
        if self.stats.api_calls > 0:
            time.sleep(REQUEST_DELAY_S)
        payload = self.km.call(fn, *args)
        self.stats.api_calls += 1
        self.stats.cache_misses += 1
        _write_json(cache_path, payload)
        return payload

    def fetch_nid(self, nid: int, *, skip_prices: bool = False) -> FetchBundle | None:
        """Return FetchBundle for one NID, or None on fatal error."""
        paths = _cache_paths(self.cache_dir, nid)
        try:
            type_payload = self._get_cached_or_fetch(
                paths["type"], api_type_details, nid
            )
            issues_payload = self._get_cached_or_fetch(
                paths["issues"], api_type_issues, nid
            )
        except Exception as e:
            self.stats.errors.append((nid, f"meta fetch failed: {e}"))
            return None

        # FR i18n title : 1 extra call par NID, indispensable au theme-matcher
        # eBay multi-marketplace (cf. project_i18n_strategy memory). EN reste
        # le canon des autres writers (slug, theme, design). Failure ici n'est
        # PAS fatal — on garde le bundle EN, l'i18n FR sera ré-essayé au
        # prochain refetch.
        type_payload_fr: dict | None = None
        try:
            type_payload_fr = self._get_cached_or_fetch(
                paths["type_fr"], api_type_details, nid, "fr"
            )
        except Exception as e:
            self.stats.errors.append((nid, f"i18n fr fetch failed: {e}"))

        bundle = FetchBundle(
            nid=nid,
            type_payload=type_payload,
            issues_payload=issues_payload,
            type_payload_fr=type_payload_fr,
        )

        if skip_prices:
            return bundle

        for issue in _extract_issues(issues_payload):
            iid = issue.get("id")
            if iid is None:
                continue
            cache_path = _price_cache_path(self.cache_dir, nid, iid)
            try:
                prices = self._get_cached_or_fetch(
                    cache_path, api_issue_prices, nid, iid
                )
                bundle.prices_by_iid[int(iid)] = prices
            except httpx.HTTPStatusError as e:
                # 404 = pas de prices pour cette issue (cas connu Numista).
                if e.response.status_code == 404:
                    continue
                self.stats.errors.append((nid, f"prices iid={iid}: {e}"))
            except Exception as e:
                self.stats.errors.append((nid, f"prices iid={iid}: {e}"))

        return bundle


def parse_nids_file(path: Path) -> list[int]:
    """Parse a NID list file. Format : un NID par ligne, commentaires
    ``# ...`` ignorés, lignes vides ignorées, commentaire inline après le
    NID autorisé (``68395    # ad-2014-2eur-standard``).

    Raises FileNotFoundError si le fichier n'existe pas, ValueError sur une
    ligne invalide (avec le numéro de ligne pour debug).
    """
    if not path.exists():
        raise FileNotFoundError(f"NIDs file not found: {path}")

    nids: list[int] = []
    seen: set[int] = set()
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        # Strip inline comment + whitespace.
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            nid = int(line)
        except ValueError as e:
            raise ValueError(
                f"{path}:{lineno}: cannot parse NID from {raw!r}"
            ) from e
        if nid in seen:
            raise ValueError(f"{path}:{lineno}: duplicate NID {nid}")
        seen.add(nid)
        nids.append(nid)
    return nids


def _load_keymanager_safe():
    """Best-effort KeyManager load. Returns None if no keys configured
    (scaffold can run without secrets). Other RuntimeErrors propagate."""
    try:
        from referential.numista_keys import KeyManager
    except ImportError as e:
        print(f"⚠️  KeyManager import failed: {e}")
        return None
    try:
        return KeyManager()
    except RuntimeError as e:
        # Typically "No Numista API keys found" when secrets/dev.env not loaded.
        print(f"⚠️  KeyManager init failed: {e}")
        return None


def print_plan(nids: list[int], cache_dir: Path, *,
               apply: bool, skip_prices: bool, skip_images: bool) -> None:
    n = len(nids)
    print("═" * 60)
    print("REFETCH NUMISTA 2€ — execution plan")
    print("═" * 60)
    print(f"  NIDs to fetch              : {n}")
    print(f"  Mode                       : {'--apply' if apply else '--dry-run'}")
    print(f"  Skip prices                : {skip_prices}")
    print(f"  Skip images                : {skip_images}")
    print(f"  Cache dir                  : {cache_dir}")

    # API call budget estimate (per NID) :
    #   - 1 × /types/{nid}                    → metadata
    #   - 1 × /types/{nid}/issues             → liste mint_releases
    #   - K × /types/{nid}/issues/{iid}/prices (K ≈ avg # issues per type)
    avg_issues = 4  # estimation prudente cf. archive kickoff §6.2
    calls_meta = 2 * n
    calls_prices = 0 if skip_prices else avg_issues * n
    total = calls_meta + calls_prices
    print(f"  Estimated API calls        : "
          f"{total} ({calls_meta} meta + {calls_prices} prices, "
          f"avg {avg_issues} issues/type)")

    km = _load_keymanager_safe()
    if km is None:
        print("  KeyManager                 : not loaded (no NUMISTA_API_KEY_* in env)")
    else:
        statuses = km.status()
        total_remaining = sum(s["remaining"] for s in statuses)
        print(f"  KeyManager                 : {len(statuses)} slot(s), "
              f"{total_remaining} calls remaining this month")
        for s in statuses:
            tag = " EXHAUSTED" if s["exhausted"] else ""
            print(f"    slot {s['slot']:>2}  calls={s['calls_this_month']:>5}  "
                  f"remaining={s['remaining']:>5}{tag}")

    print("\n  Preview (first 5 NIDs) :")
    for nid in nids[:5]:
        print(f"    {nid}")
    if n > 5:
        print(f"    ... +{n - 5} more")

    print("\n⚠️  P.7b SCAFFOLD — HTTP fetch + cache OK. DB writes arrivent en P.7c.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--nids-file",
        required=True,
        type=Path,
        help="Path to file with one NID per line (# comments allowed). "
             "Ex: ml/state/cohort_validation_19.txt",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=ML_DIR / "state" / "numista_cache",
        help="Directory to cache Numista API payloads (default: ml/state/numista_cache/)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ML_DIR / "state" / "eurio.db",
        help="Path to eurio.db (default: ml/state/eurio.db)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Plan only, no HTTP, no DB writes (default).")
    mode.add_argument("--apply", action="store_true",
                      help="Execute fetch + cache to disk. DB writes arrivent en P.7c (no-op pour l'instant).")
    parser.add_argument("--skip-prices", action="store_true",
                        help="Skip /issues/{iid}/prices (~75%% quota saving).")
    parser.add_argument("--skip-images", action="store_true",
                        help="Skip image URL capture (deferred to V.2/V.3).")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Force re-fetch même si le cache disque est présent.")
    parser.add_argument("--max-nids", type=int, default=None,
                        help="Safety throttle : ne traite que les N premiers NIDs (utile pour smoke tests, ex: --max-nids 1).")
    args = parser.parse_args()

    try:
        nids = parse_nids_file(args.nids_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    if not nids:
        print(f"⚠️  No NIDs found in {args.nids_file} (empty or all comments).")
        return 1

    if args.max_nids is not None and args.max_nids > 0:
        original_count = len(nids)
        nids = nids[: args.max_nids]
        print(f"ℹ️  --max-nids={args.max_nids} : throttle {original_count} → {len(nids)} NIDs")

    print_plan(
        nids, args.cache_dir,
        apply=args.apply,
        skip_prices=args.skip_prices,
        skip_images=args.skip_images,
    )

    if not args.apply:
        return 0

    result = refetch_nids(
        nids, cache_dir=args.cache_dir, db_path=args.db,
        skip_prices=args.skip_prices, refresh_cache=args.refresh_cache,
    )
    print("\n" + "═" * 60)
    print("FETCH STATS")
    print("═" * 60)
    print(f"  Bundles collected : {result['bundles_ok']} / {result['n_nids']}")
    if result.get("api_errors"):
        print(f"  Errors ({len(result['api_errors'])}) :")
        for nid, msg in result["api_errors"]:
            print(f"    {nid}: {msg}")
    return 0 if result["ok"] else 1


def refetch_nids(
    nids: list[int],
    *,
    cache_dir: Path,
    db_path: Path,
    skip_prices: bool = False,
    refresh_cache: bool = False,
) -> dict:
    """Entrée programmatique du refetch Numista (toujours apply) pour les NIDs
    donnés. Renvoie ``{ok, bundles_ok, n_nids, error?, api_errors, db_rc?}``.
    Utilisé par le refresh par coin (sans les prints détaillés de ``main``).
    """
    km = _load_keymanager_safe()
    if km is None:
        return {"ok": False, "error": "no_api_key", "bundles_ok": 0,
                "n_nids": len(nids), "api_errors": []}
    fetcher = Fetcher(km, cache_dir, refresh=refresh_cache)
    bundles: dict[int, "FetchBundle"] = {}
    for nid in nids:
        bundle = fetcher.fetch_nid(nid, skip_prices=skip_prices)
        if bundle is not None:
            bundles[nid] = bundle
    out: dict = {
        "ok": False, "bundles_ok": len(bundles), "n_nids": len(nids),
        "api_errors": list(fetcher.stats.errors),
    }
    if not bundles:
        out["error"] = "fetch_failed"
        return out
    rc = _apply_to_db(bundles, db_path, cache_dir=cache_dir)
    out["db_rc"] = rc
    out["ok"] = rc == 0
    if rc != 0:
        out["error"] = "db_errors"
    return out


def _apply_to_db(bundles: dict[int, "FetchBundle"], db_path: Path,
                 cache_dir: Path | None = None) -> int:
    """Transform payloads → rows → UPSERT vers eurio.db. Transaction par NID.

    Skipped NIDs (slug=None, out-of-scope) sont reportés. Erreurs DB par NID
    → rollback de ce NID seul, autres NIDs continuent.
    """
    from referential.numista_eurio_id import eurio_id_from_numista_payload
    from referential.numista_writer import NumistaWriter
    from state.source_status import numista_axes, upsert_source_status
    from state.store import Store

    print("\n" + "═" * 60)
    print(f"WRITE TO SQLite — {db_path}")
    print("═" * 60)

    store = Store(db_path)
    conn = store._connection()
    mint_resolver = _make_mint_resolver(conn)

    total_stats = {
        "ok": 0, "skipped_out_of_scope": 0, "skipped_variant_or_jointly": 0,
        "db_errors": 0,
    }
    writer = NumistaWriter(conn)

    for nid, bundle in bundles.items():
        slug = eurio_id_from_numista_payload(bundle.type_payload)
        if slug is None:
            print(f"  [{nid}] ⏭  out_of_scope (non-2€ ou champ manquant)")
            total_stats["skipped_out_of_scope"] += 1
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            writer.write_bundle(
                slug=slug,
                payload=bundle.type_payload,
                issues=_extract_issues(bundle.issues_payload),
                prices_by_iid=bundle.prices_by_iid,
                mint_resolver=mint_resolver,
                payload_fr=bundle.type_payload_fr,
                cache_dir=cache_dir,
            )
            conn.execute("COMMIT")
            print(f"  [{nid}] ✓ {slug.eurio_id}")
            total_stats["ok"] += 1
            # Instrumentation disponibilité : ok (axes re-dérivés depuis la DB).
            try:
                upsert_source_status(conn, eurio_id=slug.eurio_id, source="numista_api",
                                     state="ok", axes=numista_axes(conn, slug.eurio_id))
            except Exception as exc:  # noqa: BLE001
                print(f"  [{nid}] ⚠ source_status: {exc}")
        except Exception as e:
            conn.execute("ROLLBACK")
            print(f"  [{nid}] ❌ {e}")
            total_stats["db_errors"] += 1

    print("\n" + "═" * 60)
    print("WRITE STATS")
    print("═" * 60)
    print(f"  Bundles written     : {total_stats['ok']} OK / {total_stats['db_errors']} errors / {total_stats['skipped_out_of_scope']} skipped")
    print(f"  Total rows by table :")
    s = writer.stats
    for table, n in [
        ("coins", s.coins), ("coin_source_refs", s.source_refs),
        ("coin_cross_refs", s.cross_refs), ("coin_mint_releases", s.mint_releases),
        ("mint_release_observations", s.mint_release_observations),
        ("mint_release_prices", s.prices), ("coin_market_quotes", s.market_quotes),
        ("coin_canonical_images", s.images), ("coin_credits", s.credits),
        ("coin_observations", s.observations), ("design_groups", s.design_groups),
        ("coin_variants", s.variants), ("coin_names_i18n", s.i18n_names),
        ("coin_topics", s.topics),
    ]:
        print(f"    {table:<28} {n:>4}")
    return 0 if total_stats["ok"] else 1


def _make_mint_resolver(conn):
    """Construit un mint_resolver depuis la table mints (cached lookup)."""
    cache: dict[tuple[str, str | None], str | None] = {}
    rows = conn.execute("SELECT id, country, mark FROM mints").fetchall()
    for row in rows:
        # row[0]=id, row[1]=country, row[2]=mark
        cache[(row[1], row[2])] = row[0]
        # Fallback : si une seule mint NON-mark existe pour ce pays, accepte
        # mark=None comme alias.

    def _resolve(country: str, mark: str | None) -> str | None:
        # Exact match
        if (country, mark) in cache:
            return cache[(country, mark)]
        # Fallback : mark=None requested mais on n'a que des marks pour ce pays
        # — pick le premier slug du pays. NB: ne se produit pas pour DE/IT/ES
        # qui ont la mark requise.
        if mark is None:
            for (c, m), slug in cache.items():
                if c == country and m is None:
                    return slug
        return None

    return _resolve


if __name__ == "__main__":
    sys.exit(main())
