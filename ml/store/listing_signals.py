"""Store — domaine listing_signals (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class ListingTextSignalsRow:
    """Persisted output of ``ml/sources/text_signals/`` for one source_image.

    1 row per source_image (= 1 per listing image, partagée entre toutes
    les images d'un même listing eBay puisque le titre est identique).
    Pas de comparaison vs target ici (chunk 6) : on ne stocke que ce
    que le titre dit.
    """

    source_image_id: str
    extractor_version: str = "v1"
    countries: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    denominations: list[float] = field(default_factory=list)
    theme_tokens: list[str] = field(default_factory=list)
    rejected_markers: list[str] = field(default_factory=list)
    is_lot: bool = False
    coverage: str = "empty"
    matched: dict[str, list[str]] = field(default_factory=dict)
    # Chunk 6 — verdict vs target_eurio_id. None quand le target n'est
    # pas connu (pas de target_eurio_id, ou absent de la table coins).
    vs_target_verdict: str | None = None
    contradictions: list[str] = field(default_factory=list)
    convergences: list[str] = field(default_factory=list)
    # Chunk C2 — taxonomie listing & état numismatique extraits du titre.
    # None sur les rows produites avant C2 (extractor_version < v2).
    listing_kind: str | None = None
    listing_kind_confidence: float | None = None
    condition_normalized: str | None = None
    condition_confidence: float | None = None
    computed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_image_id": self.source_image_id,
            "extractor_version": self.extractor_version,
            "countries": list(self.countries),
            "years": list(self.years),
            "denominations": list(self.denominations),
            "theme_tokens": list(self.theme_tokens),
            "rejected_markers": list(self.rejected_markers),
            "is_lot": self.is_lot,
            "coverage": self.coverage,
            "matched": dict(self.matched),
            "vs_target_verdict": self.vs_target_verdict,
            "contradictions": list(self.contradictions),
            "convergences": list(self.convergences),
            "listing_kind": self.listing_kind,
            "listing_kind_confidence": self.listing_kind_confidence,
            "condition_normalized": self.condition_normalized,
            "condition_confidence": self.condition_confidence,
            "computed_at": self.computed_at,
        }


def _row_to_text_signals(r: sqlite3.Row) -> ListingTextSignalsRow:
    cols = r.keys()
    verdict = r["vs_target_verdict"] if "vs_target_verdict" in cols else None
    contradictions_raw = (
        r["contradictions_json"] if "contradictions_json" in cols else None
    )
    convergences_raw = (
        r["convergences_json"] if "convergences_json" in cols else None
    )

    def _opt(name: str):
        return r[name] if name in cols else None

    return ListingTextSignalsRow(
        source_image_id=r["source_image_id"],
        extractor_version=r["extractor_version"],
        countries=json.loads(r["countries_json"] or "[]"),
        years=json.loads(r["years_json"] or "[]"),
        denominations=json.loads(r["denominations_json"] or "[]"),
        theme_tokens=json.loads(r["theme_tokens_json"] or "[]"),
        rejected_markers=json.loads(r["rejected_markers_json"] or "[]"),
        is_lot=bool(r["is_lot"]),
        coverage=r["coverage"],
        matched=json.loads(r["matched_json"] or "{}"),
        vs_target_verdict=verdict,
        contradictions=json.loads(contradictions_raw or "[]"),
        convergences=json.loads(convergences_raw or "[]"),
        listing_kind=_opt("listing_kind"),
        listing_kind_confidence=_opt("listing_kind_confidence"),
        condition_normalized=_opt("condition_normalized"),
        condition_confidence=_opt("condition_confidence"),
        computed_at=r["computed_at"],
    )


class ListingSignalsMixin:

    # ─── Listing text signals (chunk 5 auto-validation) ──────────────────

    def upsert_listing_text_signals(
        self, rows: list[ListingTextSignalsRow]
    ) -> int:
        if not rows:
            return 0
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO listing_text_signals (
                  source_image_id, extractor_version,
                  countries_json, years_json, denominations_json,
                  theme_tokens_json, rejected_markers_json,
                  is_lot, coverage, matched_json,
                  vs_target_verdict, contradictions_json, convergences_json,
                  listing_kind, listing_kind_confidence,
                  condition_normalized, condition_confidence,
                  computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(source_image_id) DO UPDATE SET
                  extractor_version     = excluded.extractor_version,
                  countries_json        = excluded.countries_json,
                  years_json            = excluded.years_json,
                  denominations_json    = excluded.denominations_json,
                  theme_tokens_json     = excluded.theme_tokens_json,
                  rejected_markers_json = excluded.rejected_markers_json,
                  is_lot                = excluded.is_lot,
                  coverage              = excluded.coverage,
                  matched_json          = excluded.matched_json,
                  vs_target_verdict     = excluded.vs_target_verdict,
                  contradictions_json   = excluded.contradictions_json,
                  convergences_json     = excluded.convergences_json,
                  listing_kind            = excluded.listing_kind,
                  listing_kind_confidence = excluded.listing_kind_confidence,
                  condition_normalized    = excluded.condition_normalized,
                  condition_confidence    = excluded.condition_confidence,
                  computed_at           = datetime('now')
                """,
                [
                    (
                        r.source_image_id,
                        r.extractor_version,
                        json.dumps(r.countries),
                        json.dumps(r.years),
                        json.dumps(r.denominations),
                        json.dumps(r.theme_tokens),
                        json.dumps(r.rejected_markers),
                        int(r.is_lot),
                        r.coverage,
                        json.dumps(r.matched),
                        r.vs_target_verdict,
                        json.dumps(r.contradictions),
                        json.dumps(r.convergences),
                        r.listing_kind,
                        r.listing_kind_confidence,
                        r.condition_normalized,
                        r.condition_confidence,
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def get_listing_text_signals(
        self, source_image_id: str
    ) -> ListingTextSignalsRow | None:
        row = self._connection().execute(
            "SELECT * FROM listing_text_signals WHERE source_image_id = ?",
            (source_image_id,),
        ).fetchone()
        return _row_to_text_signals(row) if row else None

    def has_listing_text_signals(
        self, source_image_id: str, *, extractor_version: str = "v1"
    ) -> bool:
        row = self._connection().execute(
            "SELECT 1 FROM listing_text_signals "
            "WHERE source_image_id = ? AND extractor_version = ?",
            (source_image_id, extractor_version),
        ).fetchone()
        return row is not None
