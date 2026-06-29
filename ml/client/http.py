"""Client HTTP de l'eurio-api (Modèle B, chunk C3).

Stdlib uniquement (urllib), zéro dépendance — comme le publish_cli review. Base URL
``EURIO_API_URL`` (défaut local ``http://127.0.0.1:8042``), token bearer
``EURIO_API_TOKEN`` (omis en local si l'auth est off). 1 retry sur erreur réseau
transitoire.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def base_url() -> str:
    return os.environ.get("EURIO_API_URL", "http://127.0.0.1:8042").rstrip("/")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "User-Agent": "eurio-client/1.0"}
    token = os.environ.get("EURIO_API_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _request(path: str, *, method: str, payload: Any | None, timeout: int) -> dict:
    url = f"{base_url()}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    last_exc: Exception | None = None
    for attempt in range(2):  # 1 retry sur réseau transitoire
        req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                body = resp.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError:
            raise  # 4xx/5xx = erreur applicative, pas de retry
        except urllib.error.URLError as exc:  # réseau : 1 retry
            last_exc = exc
            if attempt == 0:
                time.sleep(0.5)
    raise last_exc  # type: ignore[misc]


def post_json(path: str, payload: Any, *, timeout: int = 120) -> dict:
    return _request(path, method="POST", payload=payload, timeout=timeout)


def get_json(path: str, *, timeout: int = 60) -> dict:
    return _request(path, method="GET", payload=None, timeout=timeout)


def download(path: str, dest, *, timeout: int = 300, chunk: int = 1 << 20) -> str:
    """GET ``path`` et streame le corps binaire vers ``dest`` (sans charger en RAM).

    Retourne la valeur de l'en-tête ``X-Eurio-DB-Sha256`` si présente (sinon ``""``).
    Utilisé pour tirer la réplique (``GET /db/replica``, ~106 Mo). 1 retry réseau.
    """
    from pathlib import Path  # noqa: PLC0415

    dest = Path(dest)
    url = f"{base_url()}{path}"
    last_exc: Exception | None = None
    for attempt in range(2):
        req = urllib.request.Request(url, headers=_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                sha_hdr = resp.headers.get("X-Eurio-DB-Sha256", "")
                with open(dest, "wb") as fh:
                    while True:
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        fh.write(buf)
                return sha_hdr
        except urllib.error.HTTPError:
            raise  # 4xx/5xx = erreur applicative, pas de retry
        except urllib.error.URLError as exc:  # réseau : 1 retry
            last_exc = exc
            if attempt == 0:
                time.sleep(0.5)
    raise last_exc  # type: ignore[misc]
