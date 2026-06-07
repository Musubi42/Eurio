"""Review vision Claude des design_groups STANDARD par avers.

Valide *a posteriori* la cohérence visuelle d'un groupe avers : tous les Types
membres montrent-ils bien le **même avers** (même effigie + même Nème type) ?
La vision **valide**, elle ne dérive jamais le groupage (déterministe depuis les
métadonnées, cf. ``ml/bootstrap/obverse_groups.py``). Sortie = anomalies pour
review PO, aucun re-groupage automatique.

Prompt DÉDIÉ (≠ ``claude_review.judge``, qui exige « même année » et rejetterait
be-1999 vs be-2007 alors qu'ils partagent justement l'avers) : on demande
explicitement d'IGNORER l'année et le revers.

Réutilise la plomberie ccproxy (``ccproxy_client.chat`` / ``image_part``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ccproxy_client import ChatResult, chat, image_part, parse_json_response, text_part

from foundation.claude_review import DEFAULT_MODEL_ALIAS, MODELS

logger = logging.getLogger(__name__)

# Chemin disque canonical : ml/datasets/<numista_id>/obverse.jpg (même layout que
# api/review_queue_routes._canonical_path — résolveur du batch ccproxy).
_DATASETS_DIR = Path(__file__).resolve().parents[1] / "datasets"


def canonical_obverse_path(numista_id: int | None) -> Path | None:
    """Avers canonique d'un coin via son numista_id, ou None si absent."""
    if not numista_id:
        return None
    coin_dir = _DATASETS_DIR / str(int(numista_id))
    if not coin_dir.exists():
        return None
    for name in ("obverse.jpg", "obverse.png", "obverse.jpeg"):
        p = coin_dir / name
        if p.exists():
            return p
    for f in sorted(coin_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            return f
    return None


SYSTEM_PROMPT = (
    "You are a numismatic expert auditing how euro coin Types are grouped by "
    "OBVERSE (national side) design.\n\n"
    "You will see N cropped images. Each is the OBVERSE of a euro coin Type that "
    "we believe shares the SAME obverse design — same monarch/effigy and same "
    "major design type.\n\n"
    "IGNORE entirely: the year/date, wear, lighting, crop tightness, resolution, "
    "and the reverse (the common European map is never shown here). Ignore minor "
    "portrait retouching.\n"
    "An OUTLIER is an image showing a DIFFERENT effigy (different monarch) or a "
    "clearly DIFFERENT major obverse design type.\n\n"
    "Decide whether ALL images show the same obverse design.\n"
    "Respond with ONE LINE of strict JSON, nothing else. No preamble, no markdown.\n"
    'Schema: {"same_obverse":true|false,'
    '"outlier_index":<1-based integer or null>,'
    '"confidence":<float 0..1>}\n'
)


@dataclass(frozen=True)
class GroupReview:
    group_id: str
    n_images: int
    same_obverse: bool | None
    outlier_index: int | None  # 1-based, dans l'ordre `members`
    outlier_label: str | None
    confidence: float | None
    raw_content: str
    model: str
    cost_usd: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True = groupe cohérent (vision a confirmé un avers unique)."""
        return self.error is None and self.same_obverse is True and self.outlier_index is None


def review_group(
    *,
    group_id: str,
    members: list[tuple[str, Path]],  # (label lisible, chemin avers)
    model_alias: str = DEFAULT_MODEL_ALIAS,
    base_url: str = "http://127.0.0.1:3002",
) -> GroupReview:
    """Envoie les avers d'un groupe à Claude et renvoie le verdict de cohérence.

    Toute erreur (ccproxy down, parse fail) est capturée dans ``error``.
    """
    model_id = MODELS.get(model_alias, model_alias)
    labels = [lbl for lbl, _ in members]

    def _fail(err: str) -> GroupReview:
        return GroupReview(
            group_id=group_id, n_images=len(members), same_obverse=None,
            outlier_index=None, outlier_label=None, confidence=None,
            raw_content="", model=model_id, cost_usd=0.0, error=err,
        )

    try:
        parts: list[dict] = []
        for i, (label, path) in enumerate(members, start=1):
            parts.append(text_part(f"Image {i} — {label} (obverse):"))
            parts.append(image_part(path))
        parts.append(text_part("JSON verdict:"))
        result: ChatResult = chat(
            model=model_id, system=SYSTEM_PROMPT, user_parts=parts, base_url=base_url,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"{type(exc).__name__}: {exc}")

    parsed = parse_json_response(result.content)
    if parsed is None:
        return _fail("parse_fail")

    same = parsed.get("same_obverse")
    same_obverse = same if isinstance(same, bool) else None
    raw_idx = parsed.get("outlier_index")
    outlier_index = int(raw_idx) if isinstance(raw_idx, int) and 1 <= raw_idx <= len(members) else None
    outlier_label = labels[outlier_index - 1] if outlier_index else None
    conf = parsed.get("confidence")
    confidence = max(0.0, min(1.0, float(conf))) if isinstance(conf, (int, float)) else None

    return GroupReview(
        group_id=group_id, n_images=len(members), same_obverse=same_obverse,
        outlier_index=outlier_index, outlier_label=outlier_label,
        confidence=confidence, raw_content=result.content, model=result.model,
        cost_usd=result.cost_usd,
        error=None if same_obverse is not None else "parse_fail",
    )
