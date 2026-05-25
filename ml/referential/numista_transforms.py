"""Transforms purs Numista payload → row dicts pour `eurio.db`.

Sous-chunk P.7c.2 du chantier coin-richness. Toutes les fonctions sont
**pures** : même input → même output, pas d'I/O DB. Le writer (P.7c.3)
appelle ces fonctions puis exécute les INSERT/UPSERT.

Vocabulaire registry obligatoire : ``source='numista_api'`` partout (cf.
P.3b ``ml/sources/_base/registry_map.py``).

Findings ayant guidé ce module : ``docs/coin-richness/findings-numista-api.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from referential.numista_eurio_id import NumistaSlugResult


# ─── Constantes ───────────────────────────────────────────────────────────

NUMISTA_SOURCE = "numista_api"

# Mapping 7 grades Numista → 3 grades Eurio. ``g`` ignoré (trop bas).
GRADE_RAW_TO_EURIO: dict[str, str | None] = {
    "g":   None,
    "vg":  "TB",
    "f":   "TB",
    "vf":  "TB",
    "xf":  "TTB",
    "au":  "TTB",
    "unc": "UNC",
}

# Mapping ``references[].catalogue.code`` Numista → ref_type Eurio. Les codes
# sont stables (cf. Numista API doc + payload Bremen : KM, J, Schön).
REF_TYPE_BY_CATALOGUE_CODE: dict[str, str] = {
    "KM":    "krause_mishler",
    "J":     "jaeger",
    "Schön": "schon",
}


# ─── Type de résolveur d'atelier (passé par l'orchestrateur) ──────────────
#
# Signature : (country, mark) → mint_id slug ou None si inconnu.
# Le résolveur consulte la table `mints` (SELECT id FROM mints WHERE
# country=? AND mark IS ?). Pure fonction si la table mints est figée.

MintResolver = Callable[[str, str | None], str | None]


# ─── Helpers ──────────────────────────────────────────────────────────────


def _detect_issue_type(comment: str | None) -> str:
    """Infère le issue_type Eurio depuis le ``comment`` Numista.

    Findings docs §1.4. Cas observés Bremen :
      - "" / None / "-"  → CIRC
      - "BU set"         → BU
      - "Proof"          → PROOF
      - "BE"             → BE (Belle Épreuve = Proof, occasionnel en FR)
      - "Coincard"       → COIN_CARD
    """
    if not comment:
        return "CIRC"
    low = comment.lower().strip()
    if not low or low == "-":
        return "CIRC"
    if "coincard" in low or "coin card" in low:
        return "COIN_CARD"
    if "proof" in low:
        return "PROOF"
    if "bu" in low or "uncirculated" in low:
        return "BU"
    # Standalone "be" token (Belle Épreuve), pas "weber" etc.
    if " be " in f" {low} " or low == "be":
        return "BE"
    return "OTHER"


def _mint_release_id(eurio_id: str, numista_iid: int) -> str:
    """Slug PK pour coin_mint_releases. Format aligné sur P.7c contract.

    Convention : ``{parent_eurio_id}/numista-{iid}``. Préfixe ``numista-``
    permet de futurs IDs alternatifs (ex: ``bce-...`` si BCE en source).
    """
    return f"{eurio_id}/numista-{numista_iid}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── coins ────────────────────────────────────────────────────────────────


def coin_row(slug: NumistaSlugResult, payload: dict) -> dict:
    """Row pour ``coins``. Champs minimaux NOT NULL satisfaits + métadonnées.

    NB: la composition est stockée en observation (cf. coin_observation_rows),
    pas dans coins (la table n'a pas de colonne dédiée — c'est volontaire,
    composition est variable et appartient à la couche provenance)."""
    return {
        "eurio_id": slug.eurio_id,
        "country": slug.country,
        "country_name": (payload.get("issuer") or {}).get("name"),
        "year": slug.year,
        "face_value": slug.face_value,
        "currency": "EUR",
        "is_commemorative": 1 if slug.is_commemorative else 0,
        "theme": slug.theme,
        "numista_id": int(payload["id"]),
        "design_description": slug.catalog_name,
        "design_group_id": slug.design_group_id,
        "ref_source": NUMISTA_SOURCE,
        "ref_native_id": str(payload["id"]),
    }


# ─── coin_source_refs ──────────────────────────────────────────────────────


def coin_source_ref_row(slug: NumistaSlugResult, payload: dict) -> dict:
    nid = int(payload["id"])
    url = payload.get("url") or f"https://en.numista.com/catalogue/pieces{nid}.html"
    return {
        "target_kind": "coin",
        "target_id": slug.eurio_id,
        "source": NUMISTA_SOURCE,
        "source_native_id": str(nid),
        "source_url": url,
    }


# ─── coin_cross_refs ──────────────────────────────────────────────────────


def coin_cross_ref_rows(slug: NumistaSlugResult, payload: dict) -> list[dict]:
    """KM#, Jaeger#, Schön# depuis ``references[]``. La table coin_cross_refs
    a PK ``(eurio_id, ref_type)`` — pas de colonne ``source`` (§3.3 du
    kickoff : table V1 inchangée). On émet 1 row par (ref_type)."""
    out: list[dict] = []
    seen: set[str] = set()
    for ref in payload.get("references") or []:
        cat = ref.get("catalogue") or {}
        code = cat.get("code")
        number = ref.get("number")
        if not code or not number:
            continue
        ref_type = REF_TYPE_BY_CATALOGUE_CODE.get(code)
        if not ref_type or ref_type in seen:
            continue
        seen.add(ref_type)
        out.append({
            "eurio_id": slug.eurio_id,
            "ref_type": ref_type,
            "ref_value": str(number),
        })
    return out


# ─── coin_mint_releases ────────────────────────────────────────────────────


def mint_release_rows(
    slug: NumistaSlugResult,
    issues: list[dict],
    mint_resolver: MintResolver,
) -> list[dict]:
    """Rows pour ``coin_mint_releases``, un par issue Numista.

    ``mint_resolver`` est appelé pour chaque (country, mark) ; renvoie le slug
    mint_id ou None. La FK ``mint_id`` est nullable côté schema, donc None
    ne casse pas l'insert (mais c'est un signal de mint à seeder).
    """
    out: list[dict] = []
    for issue in issues:
        iid = issue.get("id")
        if iid is None:
            continue
        mark = issue.get("mint_letter") or None
        mint_id = mint_resolver(slug.country, mark)
        issue_type = _detect_issue_type(issue.get("comment"))
        year = issue.get("gregorian_year") or issue.get("year")
        out.append({
            "id": _mint_release_id(slug.eurio_id, int(iid)),
            "parent_type_id": slug.eurio_id,
            "mint_year": int(year) if year is not None else slug.year,
            "mint_id": mint_id,
            "issue_type": issue_type,
            "notes": issue.get("comment") or None,
            # Champs hors schema mint_releases mais utiles pour writer →
            # à stocker en mint_release_observations en P.7c.3.
            "_mintage": issue.get("mintage"),
            "_mint_letter_raw": mark,
            "_numista_iid": int(iid),
        })
    return out


# ─── mint_release_prices ───────────────────────────────────────────────────


def mint_release_price_rows(
    mint_release_id: str,
    prices_payload: dict,
    *,
    fetched_at: str | None = None,
) -> list[dict]:
    """Une row par grade Numista (sauf ``g`` ignoré).

    Le UNIQUE est ``(mint_release_id, source, grade_raw, fetched_at)`` —
    même grade re-fetché à un autre timestamp = 2 rows historisées.
    """
    out: list[dict] = []
    ts = fetched_at or _now()
    currency = prices_payload.get("currency", "EUR")
    for entry in prices_payload.get("prices") or []:
        grade = (entry.get("grade") or "").lower()
        if grade not in GRADE_RAW_TO_EURIO:
            continue
        grade_eurio = GRADE_RAW_TO_EURIO[grade]
        if grade_eurio is None:
            continue
        price = entry.get("price")
        if price is None:
            continue
        out.append({
            "mint_release_id": mint_release_id,
            "source": NUMISTA_SOURCE,
            "grade_raw": grade,
            "grade_eurio": grade_eurio,
            "price": float(price),
            "currency": currency,
            "fetched_at": ts,
        })
    return out


# ─── coin_market_quotes (Type-level agrégé) ────────────────────────────────


def coin_market_quote_rows(
    eurio_id: str,
    prices_by_iid: dict[int, dict],
    *,
    period_start: str | None = None,
) -> list[dict]:
    """Agrégation Type-level : max sur tous les (issue, grade) pour chaque
    grade Eurio (UNC/TTB/TB). Findings §2.2.

    sample_size = nombre de couples (issue, grade) qui contribuent au max.
    p10/p50/p90 = même valeur (Numista expose une cote ponctuelle, pas une
    distribution). p50 = max retenu.

    period_start = date d'ouverture de la cote (default: aujourd'hui ISO).
    """
    today = period_start or datetime.now(timezone.utc).date().isoformat()

    # Bucket : condition_normalized → list[price]
    buckets: dict[str, list[float]] = {"UNC": [], "TTB": [], "TB": []}
    for prices_payload in prices_by_iid.values():
        for entry in prices_payload.get("prices") or []:
            grade = (entry.get("grade") or "").lower()
            grade_eurio = GRADE_RAW_TO_EURIO.get(grade)
            if grade_eurio is None:
                continue
            price = entry.get("price")
            if price is None:
                continue
            buckets[grade_eurio].append(float(price))

    out: list[dict] = []
    for condition, prices in buckets.items():
        if not prices:
            continue
        max_p = max(prices)
        out.append({
            "id": f"{eurio_id}/numista_api/{condition}/{today}",
            "eurio_id": eurio_id,
            "source": NUMISTA_SOURCE,
            "condition_raw": condition,
            "condition_normalized": condition,
            "currency": "EUR",
            "p10": max_p,
            "p50": max_p,
            "p90": max_p,
            "sample_size": len(prices),
            "period_start": today,
            "period_end": today,
        })
    return out


# ─── coin_canonical_images ─────────────────────────────────────────────────


def coin_canonical_image_rows(slug: NumistaSlugResult, payload: dict) -> list[dict]:
    out: list[dict] = []
    for role in ("obverse", "reverse"):
        face = payload.get(role) or {}
        url = face.get("picture")
        if not url:
            continue
        out.append({
            "eurio_id": slug.eurio_id,
            "source": NUMISTA_SOURCE,
            "role": role,
            "url": url,
            "local_path": None,  # download deferred (V.2 BCE images)
        })
    return out


# ─── coin_credits ─────────────────────────────────────────────────────────


def coin_credit_rows(slug: NumistaSlugResult, payload: dict) -> list[dict]:
    """Engravers depuis obverse.engravers + reverse.engravers. Numista n'a
    qu'un seul rôle "graveur" par face — la distinction avers/revers est dans
    la position du nom dans la liste, qu'on conserve via le ``position`` index
    (0-based dans la liste de la face).

    Tous mappés au role "engraver" (cf. mémoire — Luycx 524 fois OK).
    """
    out: list[dict] = []
    for face in ("obverse", "reverse"):
        face_payload = payload.get(face) or {}
        for idx, name in enumerate(face_payload.get("engravers") or []):
            if not name:
                continue
            out.append({
                "eurio_id": slug.eurio_id,
                "role": "engraver",
                "name": name,
                "source": NUMISTA_SOURCE,
                "source_ref": face,  # 'obverse' | 'reverse' — distingue les 2 faces
                "position": idx,
            })
    return out


# ─── design_groups (joint-issues) ──────────────────────────────────────────


def design_group_row(slug: NumistaSlugResult) -> dict | None:
    if not slug.is_joint_issue or not slug.design_group_id:
        return None
    return {
        "id": slug.design_group_id,
        "designation": slug.joint_designation,
        "description": (
            "Bootstrap from Numista refetch. "
            "Joint commemorative issue across eurozone members."
        ),
    }


# ─── coin_variants ─────────────────────────────────────────────────────────


def coin_variant_row(slug: NumistaSlugResult, payload: dict) -> dict | None:
    """Row pour ``coin_variants`` si le payload détecte un variant
    (coloured/hologram/...). Le parent_type_id pointe vers le coin classic.
    """
    if not slug.is_variant or not slug.variant_finish:
        return None
    nid = int(payload["id"])
    obverse_url = (payload.get("obverse") or {}).get("picture")
    reverse_url = (payload.get("reverse") or {}).get("picture")
    return {
        "id": f"{slug.eurio_id}/variant-numista-{nid}",
        "parent_type_id": slug.eurio_id,
        "finish": slug.variant_finish,
        "obverse_url": obverse_url,
        "reverse_url": reverse_url,
        "notes": slug.catalog_name,
    }


# ─── coin_observations (facts attribués à Numista) ─────────────────────────


def coin_observation_rows(slug: NumistaSlugResult, payload: dict) -> list[dict]:
    """Facts Type-level capturés depuis Numista en observations (provenance
    first-class). Pour Bremen on s'attend à : theme, series, tags, edge,
    weight, diameter, thickness, shape, orientation, composition.

    Chaque observation a un ``observation_type`` distinct (clé du UNIQUE).
    Le ``payload_json`` stocke la valeur structurée.
    """
    import json
    out: list[dict] = []

    def add(obs_type: str, value: Any) -> None:
        if value is None or value == "":
            return
        out.append({
            "eurio_id": slug.eurio_id,
            "source": NUMISTA_SOURCE,
            "observation_type": obs_type,
            "payload_json": json.dumps(value, ensure_ascii=False),
            "source_ref": f"https://en.numista.com/catalogue/pieces{int(payload['id'])}.html",
        })

    add("theme", payload.get("commemorated_topic"))
    add("series", payload.get("series"))
    add("tags", payload.get("tags") or None)
    add("edge", payload.get("edge"))
    add("shape", payload.get("shape"))
    add("orientation", payload.get("orientation"))
    add("weight_g", payload.get("weight"))
    add("diameter_mm", payload.get("diameter"))
    add("thickness_mm", payload.get("thickness"))
    add("composition", (payload.get("composition") or {}).get("text"))
    return out
