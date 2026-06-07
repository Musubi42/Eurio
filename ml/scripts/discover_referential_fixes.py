"""Discovery des fixes référentiel — auto-propose les mutations à appliquer.

Pré-requis lecture : ``docs/operations/referential-fixes-pipeline.md`` §
Cause racine + Shapes A/B.

Algorithme :
1. Lire `audit_referential` (Numista catalog vs coins).
2. Pour chaque `catalog_unlinked` (numista_id orphelin) :
   - Identifier les eurio_ids candidats : mêmes (country, year), face_value 2,
     commémoratives.
   - Pour chaque candidat, calculer la similarité titre Numista ↔ slug eurio_id.
   - Si **un candidat existant a un meilleur score que sa propre liaison
     actuelle** → Shape B (swap + missing row).
   - Sinon → Shape A (missing row only).
3. Pour Shape B, identifier les sources externes (BCE sidecar, lmdlp_variants)
   collées sur la row existante et qui appartiennent en réalité à la new row.

Sortie : ``ml/state/referential_fix_proposals.json`` — consommé par l'endpoint
admin `/referential/fix-proposals` (à venir Chunk 2).

Idempotent. Ne mute rien. Lecture seule.

Usage::

    python -m scripts.discover_referential_fixes
    python -m scripts.discover_referential_fixes --verbose
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
OUTPUT_PATH = ROOT / "state" / "referential_fix_proposals.json"

logger = logging.getLogger("discover_referential_fixes")


# ─── Slug generation ────────────────────────────────────────────────────────


_SLUG_TRIVIAL_WORDS = {
    "of", "the", "in", "for", "and", "to", "a", "an", "on", "with", "at", "from",
}


def slugify(text: str) -> str:
    """Convertit un texte libre en slug kebab-case ASCII.

    Aligné sur la convention observée dans `coins.eurio_id` :
    lowercase, ASCII-only, séparé par `-`, mots trivials gardés (la convention
    Eurio ne les retire pas — cf. ``lv-2018-2eur-100-years-of-the-independence-of-the-baltic-states``).
    """
    import unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    # Retire la ponctuation/parenthèses/guillemets, garde alphanum et espaces.
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return "-".join(text.split())


def build_eurio_id(country: str, year: int, face_value: float, title: str) -> str:
    """`{cc}-{year}-{denom}eur-{title-slug}`. Convention observée dans `coins`."""
    denom = int(face_value) if face_value == int(face_value) else face_value
    title_slug = slugify(title)
    # Numista écrit souvent "2 Euros (Title)" — strip le prefix si présent.
    title_slug = re.sub(r"^\d+-euros?-", "", title_slug)
    return f"{country.lower()}-{year}-{denom}eur-{title_slug}"


# ─── Fuzzy match ────────────────────────────────────────────────────────────


def normalize_for_match(text: str | None) -> str:
    if not text:
        return ""
    import unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def title_to_slug_similarity(numista_title: str, eurio_id: str) -> float:
    """Compare titre Numista à la partie 'theme' du slug eurio_id.

    On extrait la partie après `{cc}-{year}-{denom}eur-` pour ne comparer
    QUE la portion thématique. Sinon `at-2005`/`be-2005` polluent.
    """
    m = re.match(r"^[a-z]{2}-\d{4}-\d+eur-(.+)$", eurio_id)
    slug_theme = m.group(1) if m else eurio_id
    # Numista titles: "2 Euros (Zemgale)" → strip le prefix denomination.
    title_clean = re.sub(r"^\d+\s+Euros?\s*[-:(]?\s*", "", numista_title or "")
    title_clean = re.sub(r"\)$", "", title_clean).strip()
    na = normalize_for_match(slug_theme.replace("-", " "))
    nb = normalize_for_match(title_clean)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


# ─── Data classes ───────────────────────────────────────────────────────────


@dataclass
class ProposedRow:
    """Row à insérer en eurio.db (et à pusher Supabase cascade).

    Pour Shape A : ``numista_id`` = l'orphelin du catalog. ``theme`` dérivé
    de son titre.
    Pour Shape B : ``numista_id`` = le numista_id **déplacé** par le swap
    (celui qui était mal-rattaché sur la row existante). ``theme`` dérivé
    de son titre.
    """
    eurio_id: str
    country: str
    year: int
    face_value: float
    numista_id: int
    theme: str
    design_description: str | None


@dataclass
class SourceAttribution:
    """Pour une source externe (BCE sidecar, LMDLP variants), où elle doit
    aller selon le score de similarité.

    ``recommended_target`` : ``'existing'`` ou ``'new'`` ou ``'unknown'``.
    L'éditeur confirme dans la UI.
    """
    source: str                      # 'bce_sidecar' | 'lmdlp_variants'
    current_holder: str              # eurio_id qui la porte actuellement
    feature_text: str | None         # ce que la source dit (BCE.feature, LMDLP.name)
    sim_to_existing_slug: float
    sim_to_new_slug: float
    recommended_target: str          # 'existing' | 'new' | 'unknown'


@dataclass
class ExistingRowSwap:
    """Mutation d'une row existante (Shape B uniquement)."""
    eurio_id: str
    current_numista_id: int
    new_numista_id: int
    # Diagnostic
    current_numista_title: str | None = None
    new_numista_title: str | None = None
    current_similarity: float = 0.0
    new_similarity: float = 0.0


@dataclass
class FixProposal:
    case_id: str               # ex. "lv-2018-zemgale"
    country: str
    year: int
    shape: str                 # 'A' | 'B'
    confidence: str            # 'high' | 'medium' | 'low'
    reasoning: str
    new_row: ProposedRow
    swap: ExistingRowSwap | None = None  # None pour Shape A
    source_attributions: list[SourceAttribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─── Discovery ──────────────────────────────────────────────────────────────


def _country_iso2_from_catalog(country_name: str) -> str | None:
    """Map Numista country_name → ISO2 via datasets/country_mapping.json."""
    mapping_path = ROOT / "datasets" / "country_mapping.json"
    mapping = json.loads(mapping_path.read_text())
    by_name = {v["name"]: iso2 for iso2, v in mapping.items()}
    # Aliases observés (cf. audit_referential).
    by_name["Germany, Federal Republic of"] = "DE"
    by_name["Germany"] = "DE"
    return by_name.get(country_name)


def fetch_catalog_row(conn, numista_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT raw_json, country_name, year FROM referential_catalog "
        "WHERE source='numista' AND source_native_id=?",
        (numista_id,),
    ).fetchone()
    if row is None:
        return None
    data = json.loads(row["raw_json"])
    data["_country_name"] = row["country_name"]
    data["_year"] = row["year"]
    return data


def find_candidates(conn, country: str, year: int) -> list[dict[str, Any]]:
    """Pièces 2 € commémo existantes pour ce (country, year)."""
    rows = conn.execute(
        "SELECT eurio_id, theme, numista_id, raw_payload_json FROM coins "
        "WHERE country=? AND year=? AND face_value=2.0 AND is_commemorative=1",
        (country, year),
    ).fetchall()
    return [dict(r) for r in rows]


def has_bce_sidecar(eurio_id: str) -> bool:
    return (ROOT / "canonical_images" / eurio_id / "obverse_bce.json").is_file()


def has_lmdlp_variants(payload_json: str | None) -> bool:
    if not payload_json:
        return False
    try:
        p = json.loads(payload_json)
    except json.JSONDecodeError:
        return False
    obs = p.get("observations", {}) if isinstance(p, dict) else {}
    return bool(obs.get("lmdlp_variants"))


def discover(verbose: bool = False) -> list[FixProposal]:
    store = Store(DEFAULT_DB)
    conn = store._connection()  # noqa: SLF001

    # ── Catalog unlinked (numista_ids orphelins) ──────────────────────────
    catalog_unlinked = conn.execute(
        """
        SELECT rc.source_native_id AS nid, rc.country_name, rc.year, rc.raw_json
        FROM referential_catalog rc
        WHERE rc.source = 'numista'
          AND rc.type = 'commemorative'
          AND rc.face_value = 2.0
          AND NOT EXISTS (
            SELECT 1 FROM coins c WHERE c.numista_id = rc.source_native_id
          )
        ORDER BY rc.year, rc.country_name
        """
    ).fetchall()

    proposals: list[FixProposal] = []
    for row in catalog_unlinked:
        nid = int(row["nid"])
        raw = json.loads(row["raw_json"])
        title = raw.get("name") or f"Numista {nid}"
        country = _country_iso2_from_catalog(row["country_name"])
        year = int(row["year"]) if row["year"] else None
        if not country or not year:
            logger.warning("Skip nid=%s : country/year non résolus (%s, %s)",
                           nid, row["country_name"], row["year"])
            continue

        candidates = find_candidates(conn, country, year)
        if verbose:
            logger.info("[%s %s] orphan nid=%s (%s) — %d candidat(s) existant(s)",
                        country, year, nid, title, len(candidates))

        # Score chaque candidat existant : (slug match vs ORPHAN title) vs
        # (slug match vs CURRENT numista_id title).
        best_swap_candidate: dict[str, Any] | None = None
        best_swap_gain = 0.0
        for cand in candidates:
            sim_to_orphan = title_to_slug_similarity(title, cand["eurio_id"])
            current_cat = fetch_catalog_row(conn, int(cand["numista_id"])) if cand["numista_id"] else None
            current_title = current_cat.get("name") if current_cat else None
            sim_to_current = title_to_slug_similarity(current_title or "", cand["eurio_id"])
            gain = sim_to_orphan - sim_to_current
            cand["_sim_to_orphan"] = sim_to_orphan
            cand["_sim_to_current"] = sim_to_current
            cand["_current_title"] = current_title
            cand["_gain"] = gain
            if verbose:
                logger.info("  candidate %s : current_nid=%s title=%r sim_current=%.2f sim_orphan=%.2f gain=%+.2f",
                            cand["eurio_id"], cand["numista_id"], current_title,
                            sim_to_current, sim_to_orphan, gain)
            if gain > best_swap_gain:
                best_swap_gain = gain
                best_swap_candidate = cand

        face_value = 2.0

        if best_swap_candidate and best_swap_gain > 0.15 and best_swap_candidate["_sim_to_orphan"] > 0.35:
            # ── Shape B : swap + nouvelle row pour le numista_id déplacé ──
            cand = best_swap_candidate
            displaced_nid = int(cand["numista_id"])
            displaced_cat = fetch_catalog_row(conn, displaced_nid)
            if displaced_cat is None:
                logger.warning("Skip Shape B for cand=%s : displaced nid=%s introuvable en catalog",
                               cand["eurio_id"], displaced_nid)
                continue
            displaced_title = displaced_cat.get("name") or f"Numista {displaced_nid}"

            new_eurio_id = build_eurio_id(country, year, face_value, displaced_title)
            new_theme = re.sub(r"^\d+\s+Euros?\s*[-:(]?\s*", "",
                               displaced_title).rstrip(")").strip()
            new_row = ProposedRow(
                eurio_id=new_eurio_id, country=country, year=year, face_value=face_value,
                numista_id=displaced_nid, theme=new_theme,
                design_description=displaced_cat.get("obverse_description"),
            )

            swap = ExistingRowSwap(
                eurio_id=cand["eurio_id"],
                current_numista_id=displaced_nid,
                new_numista_id=nid,
                current_numista_title=cand["_current_title"],
                new_numista_title=title,
                current_similarity=round(cand["_sim_to_current"], 3),
                new_similarity=round(cand["_sim_to_orphan"], 3),
            )

            # Attribuer les sources externes : compare feature → existing_slug vs new_slug.
            source_attribs = _classify_external_sources(
                existing_eurio_id=cand["eurio_id"],
                new_eurio_id=new_eurio_id,
                existing_payload_json=cand.get("raw_payload_json"),
            )

            if best_swap_gain > 0.3 and cand["_sim_to_orphan"] > 0.6:
                conf = "high"
            elif best_swap_gain > 0.2:
                conf = "medium"
            else:
                conf = "low"

            warnings: list[str] = []
            joint_hints = ("baltic", "rome", "emu", "euro cash", "erasmus", "eu flag",
                           "european flag")
            if any(h in (displaced_title or "").lower() for h in joint_hints):
                warnings.append(
                    "Le numista_id déplacé décrit possiblement une joint issue — "
                    "vérifier si un design_group existe/manque."
                )

            case_id_slug = new_eurio_id.replace(f"{country.lower()}-{year}-2eur-", "")
            proposals.append(FixProposal(
                case_id=f"{country.lower()}-{year}-{case_id_slug}",
                country=country, year=year,
                shape="B", confidence=conf,
                reasoning=(
                    f"Existing row {cand['eurio_id']} currently points to "
                    f"nid={displaced_nid} ({cand['_current_title']!r}, "
                    f"sim={cand['_sim_to_current']:.2f}). Orphan nid={nid} "
                    f"({title!r}) matches its slug better (sim={cand['_sim_to_orphan']:.2f}, "
                    f"gain={best_swap_gain:+.2f}). Swap + create new row for displaced nid="
                    f"{displaced_nid} ({displaced_title!r})."
                ),
                new_row=new_row, swap=swap,
                source_attributions=source_attribs,
                warnings=warnings,
            ))
        else:
            # ── Shape A : missing row only ──
            new_eurio_id = build_eurio_id(country, year, face_value, title)
            new_theme = re.sub(r"^\d+\s+Euros?\s*[-:(]?\s*", "",
                               title).rstrip(")").strip()
            new_row = ProposedRow(
                eurio_id=new_eurio_id, country=country, year=year, face_value=face_value,
                numista_id=nid, theme=new_theme,
                design_description=raw.get("obverse_description"),
            )
            warnings = []
            if best_swap_candidate:
                warnings.append(
                    f"Best swap candidate had gain={best_swap_gain:+.2f} "
                    f"(sub-threshold) — no swap proposed."
                )
            case_id_slug = new_eurio_id.replace(f"{country.lower()}-{year}-2eur-", "")
            proposals.append(FixProposal(
                case_id=f"{country.lower()}-{year}-{case_id_slug}",
                country=country, year=year,
                shape="A", confidence="high",
                reasoning=f"Orphan nid={nid} ({title!r}). No existing slug claims it — create new row.",
                new_row=new_row, swap=None,
                source_attributions=[],
                warnings=warnings,
            ))

    return proposals


def _classify_external_sources(
    existing_eurio_id: str,
    new_eurio_id: str,
    existing_payload_json: str | None,
) -> list[SourceAttribution]:
    """Pour chaque source externe attachée à la row existante, décide si
    elle décrit l'identité existing OU new (à confirmer en UI)."""
    attribs: list[SourceAttribution] = []

    # ── BCE sidecar (FS) ──
    sidecar = ROOT / "canonical_images" / existing_eurio_id / "obverse_bce.json"
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text())
        except json.JSONDecodeError:
            data = {}
        feature = data.get("feature")
        sim_existing = title_to_slug_similarity(feature or "", existing_eurio_id)
        sim_new = title_to_slug_similarity(feature or "", new_eurio_id)
        if sim_existing > sim_new + 0.05:
            target = "existing"
        elif sim_new > sim_existing + 0.05:
            target = "new"
        else:
            target = "unknown"
        attribs.append(SourceAttribution(
            source="bce_sidecar",
            current_holder=existing_eurio_id,
            feature_text=feature,
            sim_to_existing_slug=round(sim_existing, 3),
            sim_to_new_slug=round(sim_new, 3),
            recommended_target=target,
        ))

    # ── LMDLP variants (raw_payload_json.observations.lmdlp_variants) ──
    if existing_payload_json:
        try:
            p = json.loads(existing_payload_json)
        except json.JSONDecodeError:
            p = {}
        lmdlp = p.get("observations", {}).get("lmdlp_variants") or []
        if lmdlp:
            # Prend le nom du premier variant comme proxy.
            feature = lmdlp[0].get("name") if isinstance(lmdlp[0], dict) else None
            sim_existing = title_to_slug_similarity(feature or "", existing_eurio_id)
            sim_new = title_to_slug_similarity(feature or "", new_eurio_id)
            if sim_existing > sim_new + 0.05:
                target = "existing"
            elif sim_new > sim_existing + 0.05:
                target = "new"
            else:
                target = "unknown"
            attribs.append(SourceAttribution(
                source="lmdlp_variants",
                current_holder=existing_eurio_id,
                feature_text=feature,
                sim_to_existing_slug=round(sim_existing, 3),
                sim_to_new_slug=round(sim_new, 3),
                recommended_target=target,
            ))

    return attribs


def main() -> None:
    ap = argparse.ArgumentParser(description="Discovery des fixes référentiel")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--output", default=str(OUTPUT_PATH), help="Fichier JSON de sortie")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(message)s")

    proposals = discover(verbose=args.verbose)

    # Pretty summary
    by_shape: dict[str, int] = {}
    by_conf: dict[str, int] = {}
    for p in proposals:
        by_shape[p.shape] = by_shape.get(p.shape, 0) + 1
        by_conf[p.confidence] = by_conf.get(p.confidence, 0) + 1

    print(f"\nDiscovered {len(proposals)} fix proposals.")
    print(f"  By shape : A={by_shape.get('A', 0)}  B={by_shape.get('B', 0)}")
    print(f"  By confidence : high={by_conf.get('high', 0)}  "
          f"medium={by_conf.get('medium', 0)}  low={by_conf.get('low', 0)}")
    print()
    for p in proposals:
        print(f"  [{p.shape}/{p.confidence:6s}] {p.case_id}")
        if p.shape == "B" and p.swap:
            print(f"      swap {p.swap.eurio_id}")
            print(f"           nid {p.swap.current_numista_id} ({p.swap.current_numista_title!r}, sim={p.swap.current_similarity})")
            print(f"        →  nid {p.swap.new_numista_id} ({p.swap.new_numista_title!r}, sim={p.swap.new_similarity})")
        print(f"      new  {p.new_row.eurio_id}")
        print(f"           nid={p.new_row.numista_id}  theme={p.new_row.theme!r}")
        for sa in p.source_attributions:
            print(f"      attr {sa.source} (currently on {sa.current_holder})")
            print(f"           feature={sa.feature_text!r}")
            print(f"           sim existing={sa.sim_to_existing_slug} new={sa.sim_to_new_slug} → {sa.recommended_target}")
        for w in p.warnings:
            print(f"      ⚠ {w}")

    # Output JSON
    output = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "n_proposals": len(proposals),
        "by_shape": by_shape,
        "by_confidence": by_conf,
        "proposals": [asdict(p) for p in proposals],
    }
    Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
