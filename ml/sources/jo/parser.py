"""Parsing d'une notice « New national side of euro coins » (JO série C).

La notice est rendue depuis du Formex en HTML simple. Le texte suit un
gabarit stable depuis 2004 :

    National side of the new commemorative 2-euro coin … issued by <Country>
    …
    Issuing country : <Country>
    Subject of commemoration: <subject>
    Description of the design: <desc…>
    Estimated number of coins to be issued : <n>
    Date of issue: <Month Year>

L'image du côté national est embarquée en **data-URI base64** dans le seul
``<figure><img src="data:image/jpg;base64,…">`` de la page.

Ce module ne fait que parser du HTML → dict. Il n'a aucune dépendance DB ;
le matching eurio_id et les écritures vivent dans ``adapter.py`` / ``pipeline.py``.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Header présent uniquement sur les notices de pièce commémorative 2 € (par
# opposition aux refontes de faces régulières « New national sides of euro
# circulation coins » qui couvrent les 8 dénominations et n'ont pas de
# « Subject of commemoration »).
_COMMEMO_MARKER = re.compile(r"commemorative\s+2-?euro\s+coin", re.IGNORECASE)

_LABELS = {
    "country": re.compile(r"Issuing country\s*:?\s*", re.IGNORECASE),
    "subject": re.compile(r"Subject of commemoration\s*:?\s*", re.IGNORECASE),
    "description": re.compile(r"Description of the design\s*:?\s*", re.IGNORECASE),
    "volume": re.compile(
        r"Estimated number of coins to be issued\s*:?\s*", re.IGNORECASE
    ),
    "date": re.compile(r"Date of issue\s*:?\s*", re.IGNORECASE),
}

# Ordre des sections pour borner la capture d'un champ jusqu'au label suivant.
_SECTION_ORDER = ["country", "subject", "description", "volume", "date"]

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


@dataclass
class JoNotice:
    """Champs structurés extraits d'une notice JO."""

    is_commemorative_2euro: bool
    country_name: str | None
    subject: str | None
    description: str | None
    issuing_volume: int | None
    date_of_issue_raw: str | None
    issue_year: int | None


def _capture_between(text: str, key: str) -> str | None:
    """Texte entre le label ``key`` et le prochain label connu (ou la fin)."""
    label = _LABELS[key]
    m = label.search(text)
    if m is None:
        return None
    start = m.end()
    # Borne basse : le prochain label parmi ceux qui suivent dans l'ordre.
    idx = _SECTION_ORDER.index(key)
    end = len(text)
    for nxt in _SECTION_ORDER[idx + 1 :]:
        nm = _LABELS[nxt].search(text, start)
        if nm is not None:
            end = nm.start()
            break
    value = text[start:end].strip()
    # Coupe les notes de bas de page « (1) … » qui suivent parfois.
    value = re.split(r"\n\(\s*\d+\s*\)", value)[0].strip()
    return value or None


def parse_jo_notice(html: str) -> JoNotice:
    """Parse une notice JO (HTML) → :class:`JoNotice`."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    is_commemo = bool(_COMMEMO_MARKER.search(text))

    country = _capture_between(text, "country")
    # « Issuing country : Greece » — garde la première ligne uniquement.
    if country:
        country = country.splitlines()[0].strip()

    subject = _capture_between(text, "subject")
    # Le rendu Formex insère des sauts de ligne internes (exposants « 1100ᵗʰ »,
    # césures) — on les recolle en espaces simples pour un sujet propre.
    if subject:
        subject = re.sub(r"\s+", " ", subject).strip()
    description = _capture_between(text, "description")
    if description:
        description = re.sub(r"\s+", " ", description).strip()

    volume_raw = _capture_between(text, "volume")
    volume = None
    if volume_raw:
        digits = re.sub(r"[^\d]", "", volume_raw.splitlines()[0])
        volume = int(digits) if digits else None

    date_raw = _capture_between(text, "date")
    if date_raw:
        date_raw = date_raw.splitlines()[0].strip()
    year = None
    if date_raw:
        ym = _YEAR_RE.search(date_raw)
        if ym:
            year = int(ym.group(0))

    return JoNotice(
        is_commemorative_2euro=is_commemo,
        country_name=country,
        subject=subject,
        description=description,
        issuing_volume=volume,
        date_of_issue_raw=date_raw,
        issue_year=year,
    )


def extract_coin_image(html: str) -> bytes | None:
    """Décode l'image base64 du côté national depuis la notice HTML.

    Retourne ``None`` si aucune ``<figure><img src="data:…">`` n'est trouvée
    (notice sans visuel, ou rendu sans image).
    """
    soup = BeautifulSoup(html, "html.parser")
    fig = soup.find("figure")
    img = fig.find("img") if fig else soup.find("img")
    if img is None:
        return None
    src = img.get("src", "")
    m = re.match(r"data:image/[\w.+-]+;base64,(.+)", src, re.DOTALL)
    if m is None:
        return None
    try:
        return base64.b64decode(m.group(1))
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return None
