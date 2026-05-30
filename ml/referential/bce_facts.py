"""Normaliseurs des facts BCE lang-invariants : tirage + date d'émission.

Parsés depuis la page EN (les chiffres sont identiques dans les 24 langues).
Les deux parsers sont **extractifs** : ils cherchent le motif utile et ignorent
le bruit (pied de page « Copyright … » que le dernier coin d'une page absorbe,
coquille BCE « I ssuing date »). On garde toujours ``raw_text`` pour la
traçabilité / revue éditoriale.

Écrits dans ``coin_observations`` (provenance-first, n'écrase pas
``coins.mintage`` Numista) :
- ``observation_type='mintage_official'`` payload ``{value:int|None, raw_text}``
- ``observation_type='issuing_date'``     payload ``{year, month, day, raw_text}``
"""

from __future__ import annotations

import re

_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Coupe le pied de page / la coquille « I ssuing date » qui bavent dans la valeur.
_FOOTER_RE = re.compile(r"\bcopyright\b|i\s*ssuing\s+date", re.IGNORECASE)
_MILLION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*million", re.IGNORECASE)
_DIGIT_GROUP_RE = re.compile(r"\d[\d ,.]*\d|\d")

_DAY_MON_YEAR_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_MON_YEAR_RE = re.compile(r"([A-Za-z]+)\s+(\d{4})")
_YEAR_RE = re.compile(r"(\d{4})")


def _clean(raw: str) -> str:
    s = raw.replace("\xa0", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_issuing_volume(raw: str | None) -> dict:
    """``{value: int|None, raw_text: str|None}`` depuis ex. « 1.6 million coins »,
    « 100,000 coins », « 2 000 000 coins », « max 750 000 coins »."""
    if not raw:
        return {"value": None, "raw_text": None}
    cleaned = _clean(raw)
    body = _FOOTER_RE.split(cleaned)[0]

    m = _MILLION_RE.search(body)
    if m:
        num = float(m.group(1).replace(",", "."))
        return {"value": int(round(num * 1_000_000)), "raw_text": cleaned}

    grp = _DIGIT_GROUP_RE.search(body)
    if grp:
        digits = re.sub(r"[ ,.]", "", grp.group())
        if digits.isdigit():
            return {"value": int(digits), "raw_text": cleaned}
    return {"value": None, "raw_text": cleaned}


def parse_issuing_date(raw: str | None) -> dict:
    """``{year, month, day, raw_text}`` depuis ex. « September 2017 »,
    « 21 October 2019 », « Fourth quarter 2022 » (→ année seule, month=None)."""
    out: dict = {"year": None, "month": None, "day": None, "raw_text": None}
    if not raw:
        return out
    cleaned = _clean(raw)
    body = _FOOTER_RE.split(cleaned)[0].strip()
    out["raw_text"] = body

    m = _DAY_MON_YEAR_RE.search(body)
    if m and m.group(2).lower() in _MONTHS:
        out.update(
            day=int(m.group(1)),
            month=_MONTHS[m.group(2).lower()],
            year=int(m.group(3)),
        )
        return out

    for mm in _MON_YEAR_RE.finditer(body):
        if mm.group(1).lower() in _MONTHS:
            out.update(month=_MONTHS[mm.group(1).lower()], year=int(mm.group(2)))
            return out

    y = _YEAR_RE.search(body)
    if y:
        out["year"] = int(y.group(1))
    return out
