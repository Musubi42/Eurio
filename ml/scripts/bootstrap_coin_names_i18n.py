"""Scrape Numista localized titles via TOR. Writes JSONL artifacts only.

Runs on **VPS** (where TOR + diversified exit IPs live). Reads a worklist
JSON produced by ``export_i18n_worklist`` on the PC side, fetches
``<lang>.numista.com/<numista_id>`` for each (eurio_id, lang) pair via
TOR with per-username circuit isolation, and writes two append-only
JSONL files:

- ``i18n_results.jsonl``  — one line per successful (eurio_id, lang)
- ``i18n_failures.jsonl`` — one line per 403 / challenge / error

Both files are append-only; restarting the script reads them to skip
already-done work, so crash-resume is free (no checkpoint logic).

Cf. ``docs/sources-refacto/ebay-multi-marketplace/i18n-scrape-numista.md``.

Two modes:

- **default (full)** — reads worklist, distributes across N circuits.
  Run on the VPS. Produces JSONL that gets rsync'd back to PC.
- **--poc** — 5 hardcoded coins × FR+EN, single JSON dump, no JSONL,
  no worklist needed. Use for validating TOR setup / parsing.

Usage on VPS::

    go-task ml:tor:up
    go-task ml:bootstrap-coin-names-i18n         # full mode
    go-task ml:bootstrap-coin-names-i18n -- --circuits 10

Usage POC (local or VPS)::

    go-task ml:bootstrap-coin-names-i18n:poc

Prerequisite: TOR proxy reachable at ``--tor-proxy``. Start it with::

    go-task ml:tor:up
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.numista.parse import extract_title_from_html  # noqa: E402

LOGGER = logging.getLogger("bootstrap_coin_names_i18n")

POC_LANGS: tuple[str, ...] = ("fr", "en")
POC_COINS: tuple[tuple[str, int], ...] = (
    ("fr-1999-2eur-standard", 104),
    ("de-2020-2eur-50-years-since-the-kniefall-von-warschau", 226447),
    ("ad-2025-2eur-bearded-vulture", 482937),
    ("mc-2007-2eur-25th-anniversary-of-the-death-of-grace-kelly", 5036),
    ("sm-2005-2eur-world-year-of-physics-2005", 5076),
)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ACCEPT_LANG_BY_LANG = {
    "fr": "fr-FR,fr;q=0.9,en;q=0.5",
    "en": "en-US,en;q=0.9",
    "de": "de-DE,de;q=0.9,en;q=0.5",
    "it": "it-IT,it;q=0.9,en;q=0.5",
    "es": "es-ES,es;q=0.9,en;q=0.5",
    "nl": "nl-NL,nl;q=0.9,en;q=0.5",
}

REQUEST_TIMEOUT = 30.0
CHALLENGE_MARKERS = ("challenge.php", "/challenge", "cf-chl")


# ────────────────────────────────────────────────────────────────────
# HTTP helpers
# ────────────────────────────────────────────────────────────────────


def _url_for(lang: str, numista_id: int) -> str:
    return f"https://{lang}.numista.com/{numista_id}"


def _build_client(proxy_url: str, username: str) -> httpx.Client:
    """One httpx.Client per worker, bound to a unique SOCKS5 username.

    TOR's IsolateSOCKSAuth gives each username its own circuit pool.
    To rotate, bump the username (e.g. ``circuit0_b1``).
    """
    scheme, rest = proxy_url.split("://", 1)
    auth_proxy = f"{scheme}://{username}:x@{rest}"
    return httpx.Client(
        proxy=auth_proxy,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            # No "br" — pythonEnv has no brotli decoder.
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )


def _detect_challenge(final_url: str, html: str) -> bool:
    lowered_url = final_url.lower()
    if any(m in lowered_url for m in CHALLENGE_MARKERS):
        return True
    if len(html) < 2048 and "challenge" in html.lower():
        return True
    return False


def fetch_one(client: httpx.Client, lang: str, numista_id: int) -> dict[str, Any]:
    url = _url_for(lang, numista_id)
    started = time.monotonic()
    headers = {"Accept-Language": ACCEPT_LANG_BY_LANG.get(lang, "en-US,en;q=0.9")}

    try:
        resp = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "final_url": None,
            "http_status": None,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "raw_h1_html": None,
            "h1_text": None,
            "h1_main_text": None,
            "h1_span_text": None,
            "redirected_to_other_lang": False,
            "challenge_detected": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    final_url = str(resp.url)

    redirected_to_other_lang = False
    if "numista.com" in final_url:
        host = final_url.split("/", 3)[2]
        final_lang = host.split(".", 1)[0] if "." in host else None
        if final_lang and final_lang != lang and len(final_lang) == 2:
            redirected_to_other_lang = True

    challenge = _detect_challenge(final_url, resp.text)

    title = (
        extract_title_from_html(resp.text)
        if resp.status_code == 200 and not challenge
        else {
            "raw_h1_html": None,
            "h1_text": None,
            "h1_main_text": None,
            "h1_span_text": None,
        }
    )

    return {
        "url": url,
        "final_url": final_url,
        "http_status": resp.status_code,
        "elapsed_ms": elapsed_ms,
        **title,
        "redirected_to_other_lang": redirected_to_other_lang,
        "challenge_detected": challenge,
        "error": None,
    }


def _verify_tor_exit(proxy_url: str) -> str:
    scheme, rest = proxy_url.split("://", 1)
    with httpx.Client(
        proxy=f"{scheme}://probe:x@{rest}",
        timeout=30.0,
        headers={"User-Agent": BROWSER_UA},
    ) as client:
        resp = client.get("https://check.torproject.org/api/ip")
        resp.raise_for_status()
        data = resp.json()
        if not data.get("IsTor"):
            raise RuntimeError(f"proxy is not TOR: {data}")
        return data["IP"]


# ────────────────────────────────────────────────────────────────────
# POC mode (5 hardcoded coins, single JSON dump)
# ────────────────────────────────────────────────────────────────────


def run_poc(
    proxy_url: str,
    per_circuit_sleep: float,
    output_path: Path,
) -> None:
    LOGGER.info("verifying TOR exit IP via %s", proxy_url)
    exit_ip = _verify_tor_exit(proxy_url)
    LOGGER.info("TOR OK, exit IP: %s", exit_ip)

    coins = list(POC_COINS)
    langs = list(POC_LANGS)
    LOGGER.info(
        "POC: %d coins × %d langs = %d fetches, %d workers, %.0fs/req per circuit",
        len(coins), len(langs), len(coins) * len(langs),
        len(coins), per_circuit_sleep,
    )

    results: dict[str, dict[str, Any]] = {}
    results_lock = Lock()

    def worker(idx: int, eurio_id: str, numista_id: int) -> None:
        username = f"circuit{idx}"
        with _build_client(proxy_url, username) as client:
            entry: dict[str, Any] = {
                "eurio_id": eurio_id,
                "numista_id": numista_id,
                "circuit_username": username,
                "langs": {},
            }
            first = True
            for lang in langs:
                if not first:
                    time.sleep(per_circuit_sleep)
                first = False
                LOGGER.info("[%s] fetch %s [%s]", username, eurio_id, lang)
                result = fetch_one(client, lang, numista_id)
                entry["langs"][lang] = result
                if result["challenge_detected"]:
                    LOGGER.warning("[%s] CHALLENGE on %s [%s] → %s",
                                   username, eurio_id, lang, result["final_url"])
            with results_lock:
                results[eurio_id] = entry

    with ThreadPoolExecutor(max_workers=len(coins)) as pool:
        futures = [
            pool.submit(worker, idx, eurio_id, numista_id)
            for idx, (eurio_id, numista_id) in enumerate(coins)
        ]
        for fut in as_completed(futures):
            fut.result()

    ordered = [results[e] for e, _ in coins if e in results]
    payload = {
        "probed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "poc",
        "proxy_url": proxy_url,
        "tor_exit_ip": exit_ip,
        "per_circuit_sleep": per_circuit_sleep,
        "user_agent": BROWSER_UA,
        "results": ordered,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("wrote %s", output_path)
    _print_poc_summary(ordered, langs)


def _print_poc_summary(results: list[dict[str, Any]], langs: list[str]) -> None:
    print()
    print(f"{'eurio_id':<60} " + " ".join(f"{l:>4}" for l in langs))
    for entry in results:
        row = []
        for lang in langs:
            r = entry["langs"].get(lang)
            if r is None:
                row.append("  - ")
            elif r["error"]:
                row.append(" ERR")
            elif r["challenge_detected"]:
                row.append(" CHL")
            elif r["redirected_to_other_lang"]:
                row.append(" RDR")
            elif r["http_status"] == 200 and r["h1_text"]:
                row.append(" OK ")
            else:
                row.append(f"{r['http_status']!s:>4}")
        print(f"{entry['eurio_id']:<60} " + " ".join(row))
    print()
    print("Legend: OK=200+title, RDR=lang redirect, CHL=challenge.php, ERR=net/5xx")
    print()
    for entry in results:
        for lang in langs:
            r = entry["langs"].get(lang)
            if r and r["h1_text"]:
                print(f"  [{lang}] {entry['eurio_id']:<55} {r['h1_text']}")


# ────────────────────────────────────────────────────────────────────
# Full mode (read worklist, write JSONL artifacts)
# ────────────────────────────────────────────────────────────────────


def _load_jsonl_keys(path: Path) -> set[tuple[str, str]]:
    """Return set of (eurio_id, lang) already present in a JSONL file."""
    if not path.is_file():
        return set()
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                seen.add((obj["eurio_id"], obj["lang"]))
            except (json.JSONDecodeError, KeyError):
                LOGGER.warning("skipping malformed line in %s: %r", path, line[:80])
    return seen


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_jsonl(path: Path, lock: Lock, obj: dict[str, Any]) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    with lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def run_full(
    worklist_path: Path,
    results_path: Path,
    failures_path: Path,
    proxy_url: str,
    n_circuits: int,
    per_circuit_sleep: float,
    rotate_every: int,
) -> None:
    if not worklist_path.is_file():
        raise FileNotFoundError(f"worklist not found: {worklist_path}")

    payload = json.loads(worklist_path.read_text(encoding="utf-8"))
    items = payload["items"]
    LOGGER.info("loaded worklist %s — %d items", worklist_path, len(items))

    # Skip-set: only already-succeeded entries. Past failures get retried
    # automatically on re-run (fresh TOR circuits between runs ≈ free retry).
    # The failures.jsonl stays as append-only forensic log; delete it
    # manually if you want a clean slate.
    done = _load_jsonl_keys(results_path)
    n_prior_failures = len(_load_jsonl_keys(failures_path))
    LOGGER.info(
        "skip set: %d already-ok (prior failures %d → will be retried)",
        len(done), n_prior_failures,
    )

    # Expand items × langs, filter out already-done.
    work: list[tuple[str, int, str]] = []
    for item in items:
        for lang in item["langs"]:
            key = (item["eurio_id"], lang)
            if key in done:
                continue
            work.append((item["eurio_id"], item["numista_id"], lang))

    if not work:
        LOGGER.info("nothing to do — all entries already in results/failures")
        return

    LOGGER.info(
        "verifying TOR exit IP via %s", proxy_url,
    )
    exit_ip = _verify_tor_exit(proxy_url)
    LOGGER.info("TOR OK, exit IP: %s", exit_ip)

    LOGGER.info(
        "full run: %d fetches across %d circuits, %.0fs/req per circuit, "
        "rotate username every %d reqs. ETA ≈ %d min",
        len(work), n_circuits, per_circuit_sleep, rotate_every,
        round(len(work) * per_circuit_sleep / n_circuits / 60),
    )

    # Round-robin distribute work to circuits.
    queues: list[list[tuple[str, int, str]]] = [[] for _ in range(n_circuits)]
    for i, w in enumerate(work):
        queues[i % n_circuits].append(w)

    results_lock = Lock()
    failures_lock = Lock()
    progress_lock = Lock()
    progress = {"ok": 0, "fail": 0}
    total = len(work)
    started = time.monotonic()

    results_path.parent.mkdir(parents=True, exist_ok=True)
    failures_path.parent.mkdir(parents=True, exist_ok=True)

    def _is_success(r: dict[str, Any]) -> bool:
        return bool(
            r["error"] is None
            and r["http_status"] == 200
            and not r["challenge_detected"]
            and not r["redirected_to_other_lang"]
            and r["h1_text"]
        )

    def _is_burnt(r: dict[str, Any]) -> bool:
        """403 / challenge / 5xx → circuit (or rather: its exit pool) is
        likely banned by Numista. Worth a fresh username to escape."""
        if r["challenge_detected"]:
            return True
        st = r["http_status"]
        if st is None:
            return False  # network error, not a ban
        return st == 403 or st == 429 or (500 <= st < 600)

    def worker(circuit_idx: int, queue: list[tuple[str, int, str]]) -> None:
        # Mutable so inner helpers can rotate.
        state: dict[str, Any] = {
            "batch": 0,
            "username": f"circuit{circuit_idx}_b0",
            "client": _build_client(proxy_url, f"circuit{circuit_idx}_b0"),
            "reqs_in_batch": 0,
        }

        def rotate(reason: str) -> None:
            state["client"].close()
            state["batch"] += 1
            state["username"] = f"circuit{circuit_idx}_b{state['batch']}"
            state["client"] = _build_client(proxy_url, state["username"])
            state["reqs_in_batch"] = 0
            LOGGER.info("[c%d] rotated to %s (%s)",
                        circuit_idx, state["username"], reason)

        first = True
        try:
            for eurio_id, numista_id, lang in queue:
                # Scheduled rotation (every N reqs)
                if state["reqs_in_batch"] >= rotate_every:
                    rotate("scheduled")

                if not first:
                    time.sleep(per_circuit_sleep)
                first = False

                result = fetch_one(state["client"], lang, numista_id)
                state["reqs_in_batch"] += 1
                attempts = 1

                # Emergency rotate + retry once on 403/challenge/5xx.
                if _is_burnt(result) and not _is_success(result):
                    LOGGER.info(
                        "[%s] BURNT on %s [%s] status=%s chl=%s → rotate + retry",
                        state["username"], eurio_id, lang,
                        result["http_status"], result["challenge_detected"],
                    )
                    rotate(f"burnt by {result['http_status']}")
                    # Let the new circuit settle before retrying.
                    time.sleep(per_circuit_sleep)
                    result = fetch_one(state["client"], lang, numista_id)
                    state["reqs_in_batch"] += 1
                    attempts = 2

                if _is_success(result):
                    _append_jsonl(results_path, results_lock, {
                        "eurio_id": eurio_id,
                        "lang": lang,
                        "title": result["h1_text"],
                        # P.3b : registry vocabulary. Le JSONL est ré-importé
                        # par scripts/import_i18n_results.py qui ré-attribue
                        # toujours source='numista_api' au final ; on aligne
                        # ici pour cohérence d'archive.
                        "source": "numista_api",
                        "confidence": "canon",
                        "fetched_at": _now(),
                        "circuit": state["username"],
                        "attempts": attempts,
                        "elapsed_ms": result["elapsed_ms"],
                    })
                    with progress_lock:
                        progress["ok"] += 1
                else:
                    _append_jsonl(failures_path, failures_lock, {
                        "eurio_id": eurio_id,
                        "lang": lang,
                        "numista_id": numista_id,
                        "http_status": result["http_status"],
                        "final_url": result["final_url"],
                        "challenge_detected": result["challenge_detected"],
                        "redirected_to_other_lang": result["redirected_to_other_lang"],
                        "error": result["error"],
                        "circuit": state["username"],
                        "attempts": attempts,
                        "attempt_at": _now(),
                    })
                    with progress_lock:
                        progress["fail"] += 1
                    LOGGER.warning(
                        "[%s] FAIL %s [%s] status=%s chl=%s rdr=%s err=%s (attempts=%d)",
                        state["username"], eurio_id, lang,
                        result["http_status"], result["challenge_detected"],
                        result["redirected_to_other_lang"], result["error"],
                        attempts,
                    )

                # Periodic progress
                with progress_lock:
                    done_n = progress["ok"] + progress["fail"]
                if done_n and done_n % 20 == 0:
                    elapsed = time.monotonic() - started
                    rate = done_n / elapsed if elapsed else 0
                    eta_s = (total - done_n) / rate if rate else 0
                    LOGGER.info(
                        "progress: %d/%d (ok=%d fail=%d) — %.1f req/s, ETA %d min",
                        done_n, total, progress["ok"], progress["fail"],
                        rate, round(eta_s / 60),
                    )
        finally:
            state["client"].close()

    with ThreadPoolExecutor(max_workers=n_circuits) as pool:
        futures = [
            pool.submit(worker, idx, q)
            for idx, q in enumerate(queues) if q
        ]
        for fut in as_completed(futures):
            fut.result()

    elapsed = time.monotonic() - started
    LOGGER.info(
        "full run done in %d min — ok=%d fail=%d (success rate %.1f%%)",
        round(elapsed / 60), progress["ok"], progress["fail"],
        100 * progress["ok"] / max(progress["ok"] + progress["fail"], 1),
    )
    LOGGER.info("results: %s", results_path)
    LOGGER.info("failures: %s", failures_path)


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tor-proxy",
        default="socks5h://127.0.0.1:9050",
        help="SOCKS5 proxy URL (use socks5h:// to resolve DNS via TOR)",
    )
    parser.add_argument(
        "--per-circuit-sleep",
        type=float,
        default=30.0,
        help="Seconds to sleep between fetches on the same circuit",
    )
    parser.add_argument(
        "--poc",
        action="store_true",
        help="POC mode: 5 hardcoded coins × FR+EN, single JSON dump, no worklist",
    )
    parser.add_argument(
        "--worklist",
        type=Path,
        default=ROOT / "state" / "i18n_worklist.json",
        help="Path to worklist JSON (full mode only)",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=ROOT / "state" / "i18n_results.jsonl",
        help="Path to append-only results JSONL (full mode)",
    )
    parser.add_argument(
        "--failures",
        type=Path,
        default=ROOT / "state" / "i18n_failures.jsonl",
        help="Path to append-only failures JSONL (full mode)",
    )
    parser.add_argument(
        "--circuits", type=int, default=10,
        help="Number of parallel TOR circuits (full mode)",
    )
    parser.add_argument(
        "--rotate-every", type=int, default=20,
        help="Bump SOCKS username every N reqs per circuit",
    )
    parser.add_argument("--output", help="POC output JSON path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
    )

    if args.poc:
        if args.output:
            output_path = Path(args.output)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output_path = ROOT / "state" / f"bootstrap_coin_names_i18n_poc_{ts}.json"
        run_poc(
            proxy_url=args.tor_proxy,
            per_circuit_sleep=args.per_circuit_sleep,
            output_path=output_path,
        )
    else:
        run_full(
            worklist_path=args.worklist,
            results_path=args.results,
            failures_path=args.failures,
            proxy_url=args.tor_proxy,
            n_circuits=args.circuits,
            per_circuit_sleep=args.per_circuit_sleep,
            rotate_every=args.rotate_every,
        )


if __name__ == "__main__":
    main()
