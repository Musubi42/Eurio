"""Probe — scrape Numista localized titles for 5 sample coins, no DB write.

Cf. ``docs/sources-refacto/ebay-multi-marketplace/i18n-probe.md``.

Phase de validation avant I1 "réel" (script de bootstrap final). On
fetch <lang>.numista.com/<numista_id> pour 5 coins × 9 langues = 45
requêtes, on extrait le <h1> en 3 variantes (full / main / span), on
dump un JSON pour review manuelle. Aucune écriture DB.

Usage::

    .venv/bin/python -m scripts.probe_coin_names_i18n
    .venv/bin/python -m scripts.probe_coin_names_i18n --eurio fr-1999-2eur-standard
    .venv/bin/python -m scripts.probe_coin_names_i18n --lang fr,en,de

Output : ``ml/state/probe_coin_names_i18n_<timestamp>.json``.

Script jetable : à supprimer après validation et bascule sur le
script final ``bootstrap_coin_names_i18n.py`` (qui réutilisera la
fonction ``extract_title_from_html``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("probe_coin_names_i18n")

ALL_LANGS: tuple[str, ...] = ("fr", "en", "de", "it", "es", "nl", "ru", "pt", "el")

# Hardcoded sample — cf. i18n-probe.md §"Coins de test".
SAMPLE_COINS: tuple[tuple[str, int], ...] = (
    ("fr-1999-2eur-standard", 104),
    ("de-2020-2eur-50-years-since-the-kniefall-von-warschau", 226447),
    ("ad-2025-2eur-bearded-vulture", 482937),
    ("mc-2007-2eur-25th-anniversary-of-the-death-of-grace-kelly", 5036),
    ("sm-2005-2eur-world-year-of-physics-2005", 5076),
)

USER_AGENT = "Eurio probe (https://github.com/Musubi42/Eurio)"
THROTTLE_SECONDS = 1.0
REQUEST_TIMEOUT = 15.0
RETRY_BACKOFFS = (2.0, 4.0, 8.0)


def _url_for(lang: str, numista_id: int) -> str:
    return f"https://{lang}.numista.com/{numista_id}"


def extract_title_from_html(html: str) -> dict[str, str | None]:
    """Extract <h1> in 3 variants from a Numista coin page.

    Returns dict with keys ``h1_text`` (full concatenated), ``h1_main_text``
    (h1 minus span), ``h1_span_text`` (span only or None), and
    ``raw_h1_html`` (raw outerHTML for audit).
    """
    soup = BeautifulSoup(html, "html.parser")
    h1_list = soup.find_all("h1")
    if not h1_list:
        return {
            "raw_h1_html": None,
            "h1_text": None,
            "h1_main_text": None,
            "h1_span_text": None,
        }
    if len(h1_list) > 1:
        LOGGER.warning("multiple <h1> on page (%d), taking first", len(h1_list))
    h1 = h1_list[0]

    span = h1.find("span")
    span_text = span.get_text(strip=True) if span is not None else None

    # h1_main = h1 with span removed (clone-ish: extract from a copy)
    h1_copy = BeautifulSoup(str(h1), "html.parser").find("h1")
    if h1_copy is None:
        main_text = None
    else:
        for s in h1_copy.find_all("span"):
            s.decompose()
        main_text = h1_copy.get_text(" ", strip=True) or None

    full_text = h1.get_text(" ", strip=True) or None

    return {
        "raw_h1_html": str(h1),
        "h1_text": full_text,
        "h1_main_text": main_text,
        "h1_span_text": span_text,
    }


def fetch_one(
    client: httpx.Client, lang: str, numista_id: int
) -> dict[str, Any]:
    url = _url_for(lang, numista_id)
    started = time.monotonic()
    last_exc: Exception | None = None

    for attempt, backoff in enumerate((0.0, *RETRY_BACKOFFS)):
        if backoff:
            LOGGER.warning("retry %d after %.1fs (%s)", attempt, backoff, url)
            time.sleep(backoff)
        try:
            resp = client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            last_exc = exc
            continue

        elapsed_ms = int((time.monotonic() - started) * 1000)
        final_url = str(resp.url)

        # Detect inter-lang redirect (e.g. el.numista.com → en.numista.com when
        # the page isn't translated). Numista's behavior to confirm empirically.
        redirected_to_other_lang = False
        if final_url.startswith("https://") and "numista.com" in final_url:
            host = final_url.split("/", 3)[2]  # "<lang>.numista.com"
            final_lang = host.split(".", 1)[0] if "." in host else None
            if final_lang and final_lang != lang:
                redirected_to_other_lang = True

        if 500 <= resp.status_code < 600 and attempt < len(RETRY_BACKOFFS):
            last_exc = httpx.HTTPStatusError(
                f"5xx: {resp.status_code}", request=resp.request, response=resp
            )
            continue

        title = (
            extract_title_from_html(resp.text)
            if resp.status_code == 200
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
            "redirected_to_other_lang": redirected_to_other_lang,
            "http_status": resp.status_code,
            "elapsed_ms": elapsed_ms,
            **title,
            "error": None,
        }

    return {
        "url": url,
        "final_url": None,
        "redirected_to_other_lang": False,
        "http_status": None,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "raw_h1_html": None,
        "h1_text": None,
        "h1_main_text": None,
        "h1_span_text": None,
        "error": f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown",
    }


def run_probe(
    coins: list[tuple[str, int]],
    langs: list[str],
    output_path: Path,
) -> None:
    LOGGER.info("probing %d coins × %d langs = %d fetches", len(coins), len(langs), len(coins) * len(langs))
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    results: list[dict[str, Any]] = []

    with httpx.Client(headers=headers, timeout=REQUEST_TIMEOUT) as client:
        first = True
        for eurio_id, numista_id in coins:
            entry: dict[str, Any] = {
                "eurio_id": eurio_id,
                "numista_id": numista_id,
                "langs": {},
            }
            for lang in langs:
                if not first:
                    time.sleep(THROTTLE_SECONDS)
                first = False
                LOGGER.info("fetch %s [%s]", eurio_id, lang)
                entry["langs"][lang] = fetch_one(client, lang, numista_id)
            results.append(entry)

    payload = {
        "probed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "throttle_seconds": THROTTLE_SECONDS,
        "user_agent": USER_AGENT,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("wrote %s", output_path)
    _print_summary(results, langs)


def _print_summary(results: list[dict[str, Any]], langs: list[str]) -> None:
    print()
    print(f"{'eurio_id':<60} " + " ".join(f"{l:>4}" for l in langs))
    for entry in results:
        row = []
        for lang in langs:
            r = entry["langs"][lang]
            if r["error"]:
                row.append(" ERR")
            elif r["redirected_to_other_lang"]:
                row.append(" RDR")
            elif r["http_status"] == 200 and r["h1_text"]:
                row.append(" OK ")
            elif r["http_status"] == 404:
                row.append(" 404")
            else:
                row.append(f"{r['http_status']!s:>4}")
        print(f"{entry['eurio_id']:<60} " + " ".join(row))
    print()
    print("Legend: OK=200+title, RDR=redirected to other lang (not translated), 404, ERR=network/5xx")


def _parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [tok.strip() for tok in value.split(",") if tok.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eurio",
        help="Comma-separated eurio_ids to override the hardcoded 5 samples. "
        "Must exist in the hardcoded list (script doesn't query DB).",
    )
    parser.add_argument(
        "--lang",
        help="Comma-separated langs to fetch (default: all 9). E.g. --lang fr,en,de",
    )
    parser.add_argument(
        "--output",
        help="Output JSON path (default: ml/state/probe_coin_names_i18n_<ts>.json)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sample_map = dict(SAMPLE_COINS)
    eurio_filter = _parse_csv(args.eurio)
    if eurio_filter:
        missing = [e for e in eurio_filter if e not in sample_map]
        if missing:
            parser.error(f"unknown eurio_id(s): {missing}. Known: {list(sample_map)}")
        coins = [(e, sample_map[e]) for e in eurio_filter]
    else:
        coins = list(SAMPLE_COINS)

    langs = _parse_csv(args.lang) or list(ALL_LANGS)
    unknown = [l for l in langs if l not in ALL_LANGS]
    if unknown:
        parser.error(f"unknown lang(s): {unknown}. Known: {list(ALL_LANGS)}")

    if args.output:
        output_path = Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = ROOT / "state" / f"probe_coin_names_i18n_{ts}.json"

    run_probe(coins, langs, output_path)


if __name__ == "__main__":
    main()
