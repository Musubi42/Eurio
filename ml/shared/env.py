"""Canonical secret & config accessor for the ML codebase.

Single source of truth: ``secrets/dev.env`` (encrypted with SOPS+age). It is
decrypted and exported into the process environment by ``.envrc`` (direnv) when
the shell loads, so everything here reads from ``os.environ`` only — no
plaintext ``.env`` parsing, no second store.

Edit secrets with ``go-task secrets:edit`` (opens the encrypted file in
``$EDITOR`` and re-encrypts on save). After editing, reload the shell with
``direnv reload`` so the new values reach ``os.environ``.

Numista is special: there is **no** singular ``NUMISTA_API_KEY``. The several
rotating keys live in ``NUMISTA_API_KEY_MUSUBI00``, ``..01`` … and are
quota-tracked / rotated by :class:`referential.numista_keys.KeyManager`. Use
:func:`numista_api_key` (or, for batches, ``KeyManager().call(...)`` directly)
to obtain a usable key.
"""

from __future__ import annotations

import os

# Known secret/config vars sourced from secrets/dev.env (via .envrc).
# Numista keys are intentionally absent here — see numista_api_key().
_KNOWN_KEYS: tuple[str, ...] = (
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_ANON_KEY",
    "VITE_SUPABASE_SERVICE_KEY",
    "EBAY_CLIENT_ID",
    "EBAY_CLIENT_SECRET",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_USE_SSL",
    "REVIEW_ADMIN_TOKEN",
)


def load_env() -> dict[str, str]:
    """Snapshot of the known secret/config vars present in the environment.

    Backwards-compatible with the historical per-module ``load_env()`` (same
    ``dict[str, str]`` contract, callers use ``env.get(...)``) but reads only
    from ``os.environ``. The values originate from ``secrets/dev.env`` exported
    by ``.envrc``. A missing var is simply absent from the returned dict.
    """
    return {k: os.environ[k] for k in _KNOWN_KEYS if k in os.environ}


def require(name: str) -> str:
    """Return a required env var, or raise a clear, actionable error.

    Use this instead of ``env.get(name)`` followed by a hand-rolled check when
    the value is mandatory.
    """
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"{name} manquant dans l'environnement. "
            f"Vérifie secrets/dev.env (`go-task secrets:edit`) puis recharge le "
            f"shell (`direnv reload`)."
        )
    return val


def numista_api_key() -> str:
    """Return one usable Numista API key via the multi-key manager.

    There is no singular ``NUMISTA_API_KEY``; keys live in
    ``NUMISTA_API_KEY_MUSUBI00..`` and are rotated/quota-tracked by
    :class:`referential.numista_keys.KeyManager`. Prefer ``KeyManager().call``
    when issuing many requests so quota tracking and 429 rotation kick in.
    """
    from referential.numista_keys import KeyManager

    return KeyManager().pick()
