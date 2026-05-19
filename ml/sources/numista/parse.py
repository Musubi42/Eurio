"""Numista HTML parsing helpers."""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)


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
