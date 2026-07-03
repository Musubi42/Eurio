"""Classification vision d'un crop eBay vs un design_group STANDARD attendu.

Partagé entre l'éval (``scripts.eval_obverse_attribution_vision``) et le gate
(``scripts.gate_standard_vision``). Répond au problème surfacé par l'éval BE :
le standard scrape leake des commémos (titre vendeur générique → l'exclusion
text-based ne les voit pas). La vision tranche sur l'IMAGE.

Labels :
  - ``correct``            : même pays/dénom + même ère d'avers que le canonique ;
  - ``wrong_era``          : bon pays/dénom mais autre ère (effigie/type différent) ;
  - ``wrong_coin``         : autre pays / commémo / autre dénomination ;
  - ``junk``               : pas une pièce unique (multi-pièces, emballage, illisible) ;
  - ``reverse_cant_tell``  : la carte (revers commun) est montrée → non décidable.

Réutilise la plomberie ccproxy (``ccproxy_client``). Toute erreur est capturée.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from shared.ccproxy_client import DEFAULT_BASE_URL, ChatResult, chat, image_part, parse_json_response, text_part

from training.foundation.claude_review import DEFAULT_MODEL_ALIAS, MODELS

logger = logging.getLogger(__name__)

VALID_LABELS = ("correct", "wrong_era", "wrong_coin", "junk", "reverse_cant_tell")

SYSTEM_PROMPT = (
    "You are a numismatic expert auditing how eBay coin photos are attributed to "
    "euro coin design groups.\n\n"
    "The first images are the CANONICAL obverse(s) (national side) of the proposed "
    "design group — there may be several if the group spans minor effigy variants; "
    "treat any of them as a valid reference. The LAST image is a CROP from an eBay "
    "listing, attributed to that group.\n\n"
    "Classify the CROP relative to the proposed group:\n"
    "  correct           = same country & denomination & same obverse design era as a "
    "canonical (allow wear/lighting/angle);\n"
    "  wrong_era         = same country & denomination but a DIFFERENT obverse era "
    "(different effigy/type);\n"
    "  wrong_coin        = different country, a commemorative design, or different "
    "denomination;\n"
    "  junk              = not a single coin (multi-coin photo, packaging, unrelated, "
    "unreadable);\n"
    "  reverse_cant_tell = the crop shows the common European MAP side (reverse), so the "
    "obverse era cannot be judged.\n\n"
    "Respond with ONE LINE of strict JSON, nothing else. No markdown.\n"
    'Schema: {"label":"correct"|"wrong_era"|"wrong_coin"|"junk"|"reverse_cant_tell",'
    '"confidence":<float 0..1>}\n'
)


@dataclass(frozen=True)
class CropVerdict:
    label: str | None
    confidence: float | None
    raw_content: str
    cost_usd: float
    error: str | None = None


def classify_crop(
    *,
    canonical_paths: list[Path],
    crop_path: Path,
    group_label: str,
    year_range: str,
    listing_title: str,
    model_alias: str = DEFAULT_MODEL_ALIAS,
    base_url: str = DEFAULT_BASE_URL,
) -> CropVerdict:
    """Classe un crop vs les avers canoniques d'un groupe. Erreurs capturées."""
    model_id = MODELS.get(model_alias, model_alias)
    canon_parts = [image_part(p) for p in canonical_paths]
    if not canon_parts:
        return CropVerdict(None, None, "", 0.0, error="no_canonical")
    parts = [
        text_part(f"CANONICAL obverse(s) of group '{group_label}' ({year_range}):"),
        *canon_parts,
        text_part("eBay CROP attributed to this group:"),
        image_part(crop_path),
        text_part(f"Listing title: {listing_title or '(empty)'}\nJSON:"),
    ]
    try:
        res: ChatResult = chat(
            model=model_id, system=SYSTEM_PROMPT, user_parts=parts, base_url=base_url,
        )
    except Exception as exc:  # noqa: BLE001
        return CropVerdict(None, None, "", 0.0, error=f"{type(exc).__name__}: {exc}")

    parsed = parse_json_response(res.content)
    if parsed is None:
        return CropVerdict(None, None, res.content, res.cost_usd, error="parse_fail")
    label = parsed.get("label")
    label = label if label in VALID_LABELS else None
    conf = parsed.get("confidence")
    confidence = max(0.0, min(1.0, float(conf))) if isinstance(conf, (int, float)) else None
    return CropVerdict(
        label=label, confidence=confidence, raw_content=res.content,
        cost_usd=res.cost_usd, error=None if label else "parse_fail",
    )
