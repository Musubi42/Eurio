"""Helper Claude vision pour la review queue — partagé entre bench et prod.

Source unique du SYSTEM_PROMPT + de la mécanique d'appel Claude pour décider
si un CROP correspond à un TARGET proposé. Réutilisé par :
- ``ml/scripts/bench_claude_review.py``   (mesure offline sur gold set)
- ``ml/api/review_queue_routes.py``       (prod batch ccproxy)

Le contrat du verdict est strict : JSON-only, schéma rigide, aucune chain-of-
thought. C'est le résultat du chunk 2 (bench validation, cf. memory
``project_claude_vision_bench``) : Sonnet 4.6 atteint 85 % accuracy / 92 %
precision sur le gold set avec ce prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from shared.ccproxy_client import DEFAULT_BASE_URL, ChatResult, chat, image_part, parse_json_response, text_part

logger = logging.getLogger(__name__)

# Alias humains → identifiants Anthropic. ``sonnet`` est le default (cf. bench).
MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}
DEFAULT_MODEL_ALIAS = "sonnet"

ClaudeVerdict = Literal["match", "no_match", "uncertain"]
ClaudeFace = Literal["obverse", "reverse", "unknown"]

SYSTEM_PROMPT = (
    "You are a numismatic expert reviewing online listings of euro "
    "commemorative coins.\n\n"
    "You will see two images:\n"
    "  1. CROP — a coin extracted from an online marketplace photo.\n"
    "  2. CANONICAL — the official reference image of the proposed target coin.\n\n"
    "Decide whether the CROP shows THE SAME coin design as the CANONICAL.\n"
    "Same coin = same country, year, and commemorative design.\n"
    "Allow for: wear, lighting, angle, partial crop, low resolution.\n"
    "Different coin = different design, year, or country, OR the crop shows "
    "something that is not the target (multi-coin photo with wrong coin "
    "centered, unrelated object, unreadable).\n\n"
    "Respond with ONE LINE of strict JSON, nothing else. No preamble, no "
    "explanation outside the fields, no markdown fences.\n"
    'Schema: {"verdict":"match"|"no_match"|"uncertain",'
    '"face":"obverse"|"reverse"|"unknown",'
    '"confidence":<float 0..1>}\n'
)


@dataclass(frozen=True)
class ClaudeJudgement:
    verdict: ClaudeVerdict | None
    face: ClaudeFace | None
    confidence: float | None
    raw_content: str
    model: str
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cost_usd: float
    duration_ms: int
    error: str | None = None

    @property
    def parsed_ok(self) -> bool:
        return self.error is None and self.verdict is not None


def build_user_parts(
    *, crop_path: Path, canonical_path: Path,
    target_label: str, listing_title: str,
) -> list[dict]:
    """Construit le payload OpenAI ``user`` : crop + canonical + contexte."""
    return [
        text_part("Image 1 — CROP from listing:"),
        image_part(crop_path),
        text_part("Image 2 — CANONICAL reference of proposed target:"),
        image_part(canonical_path),
        text_part(
            f"Proposed target: {target_label}\n"
            f"Listing title: {listing_title or '(empty)'}\n\n"
            "JSON verdict:"
        ),
    ]


def judge(
    *,
    crop_path: Path,
    canonical_path: Path,
    target_label: str,
    listing_title: str,
    model_alias: str = DEFAULT_MODEL_ALIAS,
    base_url: str = DEFAULT_BASE_URL,
) -> ClaudeJudgement:
    """Single-shot : appelle Claude, parse, retourne le verdict structuré.

    Toute erreur (ccproxy down, parse fail, exception) est capturée dans le
    champ ``error`` — l'appelant peut décider de retry ou de loguer.
    """
    model_id = MODELS.get(model_alias, model_alias)
    try:
        user_parts = build_user_parts(
            crop_path=crop_path,
            canonical_path=canonical_path,
            target_label=target_label,
            listing_title=listing_title,
        )
        result: ChatResult = chat(
            model=model_id,
            system=SYSTEM_PROMPT,
            user_parts=user_parts,
            base_url=base_url,
        )
    except Exception as exc:  # noqa: BLE001
        return ClaudeJudgement(
            verdict=None, face=None, confidence=None,
            raw_content="", model=model_id,
            tokens_in=0, tokens_out=0, cache_read_tokens=0,
            cost_usd=0.0, duration_ms=0,
            error=f"{type(exc).__name__}: {exc}",
        )

    parsed = parse_json_response(result.content)
    verdict: ClaudeVerdict | None = None
    face: ClaudeFace | None = None
    confidence: float | None = None
    if parsed is not None:
        v = parsed.get("verdict")
        if v in ("match", "no_match", "uncertain"):
            verdict = v  # type: ignore[assignment]
        f = parsed.get("face")
        if f in ("obverse", "reverse", "unknown"):
            face = f  # type: ignore[assignment]
        c = parsed.get("confidence")
        if isinstance(c, (int, float)):
            confidence = max(0.0, min(1.0, float(c)))

    err = None if verdict is not None else "parse_fail"

    return ClaudeJudgement(
        verdict=verdict, face=face, confidence=confidence,
        raw_content=result.content, model=result.model,
        tokens_in=result.tokens_in, tokens_out=result.tokens_out,
        cache_read_tokens=result.cache_read_tokens,
        cost_usd=result.cost_usd, duration_ms=result.duration_ms,
        error=err,
    )
