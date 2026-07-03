"""Mini-client HTTP pour ccproxy (services/ccproxy/).

ccproxy expose une API OpenAI-compatible qui wrap la CLI ``claude``, donc on
parle Claude via les tokens de l'abonnement Claude Code plutôt que via une
API key Anthropic. Module réutilisé par :
- ``ml/scripts/bench_claude_review.py``  (chunk 2)
- l'endpoint ``/review-queue/claude/batch`` (chunk 3, à venir)

Pas de SDK OpenAI nécessaire : on POST en JSON brut, c'est plus simple à
déboguer et à instrumenter.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ccproxy est un service GLOBAL partagé entre projets (~/Taskfile.yml,
# namespace global:ccproxy:*), pas une instance locale à Eurio. Port fixe
# 3042 — voir ~/.claude/CLAUDE.md §Services globaux locaux. Overridable via
# CCPROXY_BASE_URL pour un déploiement alternatif (jamais commit de 3002/8042).
DEFAULT_BASE_URL = os.environ.get("CCPROXY_BASE_URL", "http://127.0.0.1:3042")
DEFAULT_TIMEOUT = 120  # seconds (vision peut être plus lent)


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    duration_ms: int

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


# Bord max envoyé à Claude. Les images vision sont tokenisées ~(w·h)/750 : un
# canonical Numista 1000-1500px coûte 1500-3000 tokens pour rien (un avers de
# pièce reste parfaitement lisible à 768px). Downscale = ~4× moins cher sur le
# canonical, sans perte de qualité de verdict (mesuré WS5). Les crops 224px
# passent inchangés (≤ MAX_EDGE → no-op, bytes exacts préservés).
MAX_IMAGE_EDGE = 768


def image_part(path: Path | str, *, max_edge: int = MAX_IMAGE_EDGE) -> dict[str, Any]:
    """Construit un message-part OpenAI ``image_url`` à partir d'un fichier
    disque, encodé en data URL base64. ccproxy renvoie ces images inline à
    Claude via ``--input-format stream-json`` (cf. ccproxy/README.md).

    Downscale au-delà de ``max_edge`` (bord le plus long) pour borner le coût
    tokens. En-dessous, l'image est envoyée telle quelle (bytes exacts).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    from PIL import Image

    with Image.open(p) as im:
        w, h = im.size
        if max(w, h) <= max_edge:
            # Déjà petite (ex. crop 224) → bytes d'origine, pas de ré-encodage.
            mime, _ = mimetypes.guess_type(p.name)
            data = base64.b64encode(p.read_bytes()).decode("ascii")
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{mime or 'image/jpeg'};base64,{data}"},
            }
        # Downscale proportionnel + ré-encodage JPEG (RGBA/P → RGB).
        scale = max_edge / max(w, h)
        resized = im.convert("RGB").resize(
            (max(1, round(w * scale)), max(1, round(h * scale))),
            Image.LANCZOS,
        )
        import io
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=88)
        data = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{data}"},
    }


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def chat(
    *,
    model: str,
    system: str,
    user_parts: list[dict[str, Any]] | str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> ChatResult:
    """Appel ccproxy / Claude pour un single-turn.

    ``user_parts`` accepte soit une string (texte simple), soit une liste de
    parts OpenAI-compat (mélange images + texte pour le mode vision).
    """
    if isinstance(user_parts, str):
        user_content: str | list[dict[str, Any]] = user_parts
    else:
        user_content = user_parts

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }

    t0 = time.monotonic()
    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        timeout=timeout,
    )
    dt_ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    body = resp.json()

    msg = body["choices"][0]["message"]
    content = msg.get("content", "") or ""
    usage = body.get("usage", {}) or {}

    return ChatResult(
        content=content.strip(),
        model=body.get("model", model),
        tokens_in=int(usage.get("prompt_tokens", 0)),
        tokens_out=int(usage.get("completion_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        cost_usd=float(usage.get("anthropic_cost_usd", 0.0)),
        duration_ms=dt_ms,
    )


def health(base_url: str = DEFAULT_BASE_URL, timeout: float = 5) -> dict[str, Any]:
    """Ping `/health` — utile en pré-flight pour vérifier que ccproxy tourne."""
    r = requests.get(f"{base_url}/health", timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_json_response(content: str) -> dict[str, Any] | None:
    """Parse la réponse JSON-only attendue. Tolère un éventuel wrap markdown
    (```json … ```) si le modèle a glissé. Retourne ``None`` si non-JSON."""
    text = content.strip()
    # Strip markdown code fences si présents
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON response: %s | content=%r", exc, content[:200])
        return None
