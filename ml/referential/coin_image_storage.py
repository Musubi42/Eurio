"""Shared helpers for the coin-images storage layout.

Path convention (Phase 2C.8 follow-up):
    coin-images/{eurio_id}/{role}_{source}.webp        # detail
    coin-images/{eurio_id}/{role}_{source}_thumb.webp  # thumb (120px)

Both `enrich_from_numista.py` (Numista source) and `fetch_bce_images.py`
(BCE source) write through this module. Each upload produces an `ImageVariant`
that callers merge into `coins.images[role][]`.

`coins.images` shape going forward:

    {
      "obverse": [
        { "source": "numista",  "url": "...", "thumb_url": "...",
          "width": 400, "height": 400, "bytes": 28734 },
        { "source": "bce_comm", "url": "...", "thumb_url": "...",
          "width": 270, "height": 270, "bytes": 24558 }
      ],
      "reverse": [
        { "source": "numista", "url": "...", "thumb_url": "...",
          "width": 400, "height": 400 }
      ]
    }
"""

from __future__ import annotations

import io
from typing import Any, Literal, TypedDict

import httpx
from PIL import Image

BUCKET_NAME = "coin-images"
THUMB_WIDTH = 120
DETAIL_QUALITY = 90
THUMB_QUALITY = 80

Role = Literal["obverse", "reverse"]
Source = Literal["numista", "bce_comm"]

# `source` in the DB / observations is the long form (matches source_observations.source).
# In storage paths we use a short tag because the BCE one is just clutter on disk.
_SOURCE_FILE_TAG: dict[str, str] = {
    "numista":  "numista",
    "bce_comm": "bce",
}


def source_file_tag(source: str) -> str:
    return _SOURCE_FILE_TAG.get(source, source)


class ImageVariant(TypedDict, total=False):
    source: str
    url: str
    thumb_url: str
    width: int
    height: int
    bytes: int


def storage_key(eurio_id: str, role: str, source: str, *, thumb: bool = False) -> str:
    suffix = "_thumb" if thumb else ""
    return f"{eurio_id}/{role}_{source_file_tag(source)}{suffix}.webp"


def public_url(supabase_url: str, key: str) -> str:
    return f"{supabase_url}/storage/v1/object/public/{BUCKET_NAME}/{key}"


def encode_webp(
    raw: bytes,
    *,
    max_width: int | None = None,
    quality: int = DETAIL_QUALITY,
) -> tuple[bytes, int, int]:
    """Re-encode an image as WebP. Optionally downscale to `max_width` (preserves aspect)."""
    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if max_width and img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, round(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue(), img.width, img.height


def upload_object(
    client: httpx.Client,
    supabase_url: str,
    key: str,
    data: bytes,
) -> bool:
    """PUT an object into the bucket (upserts)."""
    resp = client.post(
        f"{supabase_url}/storage/v1/object/{BUCKET_NAME}/{key}",
        content=data,
        headers={"Content-Type": "image/webp", "x-upsert": "true"},
    )
    if resp.status_code >= 400:
        print(f"    upload FAIL {key}: HTTP {resp.status_code} {resp.text[:200]}")
        return False
    return True


def copy_object(
    client: httpx.Client,
    supabase_url: str,
    src_key: str,
    dest_key: str,
) -> bool:
    """Server-side copy. Free, no Numista/BCE round-trip.

    Idempotent: if the destination already exists Supabase returns 409, which
    we treat as a successful no-op so re-running the migration is safe.
    """
    resp = client.post(
        f"{supabase_url}/storage/v1/object/copy",
        json={
            "bucketId": BUCKET_NAME,
            "sourceKey": src_key,
            "destinationKey": dest_key,
        },
    )
    if resp.status_code == 409:
        return True  # destination already there → idempotent success
    if resp.status_code == 404:
        # Source missing — usually because we're re-running and the legacy
        # path was already pruned. Caller has the destination via --apply
        # phase already, so this is safe to skip.
        return True
    if resp.status_code >= 400:
        print(f"    copy FAIL {src_key} → {dest_key}: HTTP {resp.status_code} {resp.text[:200]}")
        return False
    return True


def remove_object(client: httpx.Client, supabase_url: str, key: str) -> bool:
    """Delete one object. Returns True for success or for not-found (idempotent).

    Supabase Storage returns HTTP 400 with body {"statusCode":"404","error":"not_found"}
    instead of a real 404 when the key doesn't exist — handle both.
    """
    resp = client.delete(f"{supabase_url}/storage/v1/object/{BUCKET_NAME}/{key}")
    if resp.status_code < 400 or resp.status_code == 404:
        return True
    if resp.status_code == 400 and "not_found" in resp.text:
        return False  # silently treat as "nothing to delete" — caller can ignore
    print(f"    delete FAIL {key}: HTTP {resp.status_code} {resp.text[:160]}")
    return False


def upload_variant(
    client: httpx.Client,
    supabase_url: str,
    eurio_id: str,
    role: str,
    source: str,
    raw_bytes: bytes,
    *,
    detail_max_width: int | None = None,
) -> ImageVariant | None:
    """Encode + upload (detail, thumb) for one (eurio_id, role, source).

    `detail_max_width=None` keeps the source's native resolution (used for BCE
    where the published image is already small). Set e.g. 400 for Numista.
    """
    detail_bytes, dw, dh = encode_webp(raw_bytes, max_width=detail_max_width, quality=DETAIL_QUALITY)
    thumb_bytes, _, _ = encode_webp(raw_bytes, max_width=THUMB_WIDTH, quality=THUMB_QUALITY)

    detail_key = storage_key(eurio_id, role, source)
    thumb_key = storage_key(eurio_id, role, source, thumb=True)

    if not upload_object(client, supabase_url, detail_key, detail_bytes):
        return None
    if not upload_object(client, supabase_url, thumb_key, thumb_bytes):
        return None

    return {
        "source": source,
        "url": public_url(supabase_url, detail_key),
        "thumb_url": public_url(supabase_url, thumb_key),
        "width": dw,
        "height": dh,
        "bytes": len(detail_bytes),
    }


def copy_variant(
    client: httpx.Client,
    supabase_url: str,
    *,
    src_eurio_id: str,
    dest_eurio_id: str,
    role: str,
    source: str,
    width: int = 0,
    height: int = 0,
    bytes_: int = 0,
) -> ImageVariant | None:
    """Server-side copy detail + thumb between two eurio_id folders.

    Used when several eurio_ids share the same numista_id — we upload once to
    the first one, then copy to the rest.
    """
    src_detail = storage_key(src_eurio_id, role, source)
    src_thumb = storage_key(src_eurio_id, role, source, thumb=True)
    dest_detail = storage_key(dest_eurio_id, role, source)
    dest_thumb = storage_key(dest_eurio_id, role, source, thumb=True)

    if not copy_object(client, supabase_url, src_detail, dest_detail):
        return None
    if not copy_object(client, supabase_url, src_thumb, dest_thumb):
        return None

    return {
        "source": source,
        "url": public_url(supabase_url, dest_detail),
        "thumb_url": public_url(supabase_url, dest_thumb),
        "width": width,
        "height": height,
        "bytes": bytes_,
    }


def merge_variant(images: Any, role: str, variant: ImageVariant) -> dict[str, list[ImageVariant]]:
    """Insert/replace a variant in `coins.images[role]` (idempotent on (role, source))."""
    out: dict[str, list[ImageVariant]] = {}
    if isinstance(images, dict):
        for k, v in images.items():
            if k in ("obverse", "reverse") and isinstance(v, list):
                out[k] = list(v)
    role_list = [v for v in out.get(role, []) if v.get("source") != variant["source"]]
    role_list.append(variant)
    out[role] = role_list
    return out


def normalize_legacy_images(images: Any) -> dict[str, list[ImageVariant]]:
    """Convert legacy shapes (Numista dict / BCE dict / array) to the new array shape.

    Used by the migration script and as a defensive read-side helper. Returns
    an empty dict when nothing recognisable is found.
    """
    if not images:
        return {}
    out: dict[str, list[ImageVariant]] = {}

    # Already the new shape: { obverse: [...], reverse: [...] } with array values
    if isinstance(images, dict) and any(
        isinstance(images.get(r), list) for r in ("obverse", "reverse")
    ):
        for r in ("obverse", "reverse"):
            if isinstance(images.get(r), list):
                out[r] = [dict(v) for v in images[r] if isinstance(v, dict)]
        return out

    # Legacy dict (Numista pipeline): { obverse, reverse, obverse_thumb, ... }
    if isinstance(images, dict):
        for role in ("obverse", "reverse"):
            url = images.get(role)
            if not isinstance(url, str):
                continue
            thumb = images.get(f"{role}_thumb")
            source = images.get(f"{role}_source") or _guess_source_from_url(url)
            entry: ImageVariant = {"source": source, "url": url}
            if isinstance(thumb, str):
                entry["thumb_url"] = thumb
            out.setdefault(role, []).append(entry)
        return out

    # Legacy flat array: [{url, role, source}]
    if isinstance(images, list):
        for item in images:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            url = item.get("url")
            if role not in ("obverse", "reverse") or not isinstance(url, str):
                continue
            entry = {
                "source": item.get("source") or _guess_source_from_url(url),
                "url": url,
            }
            out.setdefault(role, []).append(entry)
        return out

    return {}


def _guess_source_from_url(url: str) -> str:
    if "obverse_bce" in url or "reverse_bce" in url or "_bce_comm" in url:
        return "bce_comm"
    return "numista"
