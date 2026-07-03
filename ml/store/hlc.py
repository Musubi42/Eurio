"""Horloge logique hybride (HLC) pour la sync event-log multi-machine.

Chaque event autoritatif est estampillé d'un HLC ``(ts physique ms, compteur
logique, machine)`` encodé en chaîne à largeur fixe ::

    '{ts_ms:013d}-{count:04d}-{machine}'

→ l'ordre lexicographique EST l'ordre HLC (comparable en SQL par ``hlc > ?``,
sans parse). Le compteur absorbe les rafales dans une même milliseconde et les
horloges murales qui reculent ; la machine départage les ex æquo (ordre total).

État persistant (table ``sync_state``, KV) :
- ``machine_id`` : identité stable de la machine (généré au premier besoin,
  override par env ``EURIO_MACHINE_ID`` — le VPS est figé à ``vps``).
- ``hlc_last`` : dernier HLC émis OU reçu (via :func:`hlc_merge`) — garantit la
  monotonie à travers les restarts et la causalité après un pull.

Toutes les fonctions s'exécutent dans la transaction du CALLER (pas de
BEGIN/COMMIT ici), comme ``emit_state_event``.
"""

from __future__ import annotations

import os
import re
import socket
import sqlite3
import time
import uuid

_COUNT_MAX = 9999  # largeur 4 — au-delà, on avance le ts d'1 ms (rafale irréaliste)

_MACHINE_SAFE = re.compile(r"[^a-z0-9-]+")


def _sanitize_machine(raw: str) -> str:
    """Nom de machine sûr pour l'encodage HLC (minuscules, [a-z0-9-], ≤16)."""
    cleaned = _MACHINE_SAFE.sub("-", raw.strip().lower()).strip("-")
    return cleaned[:16] or "machine"


def machine_id(conn: sqlite3.Connection) -> str:
    """Identité stable de cette machine (env > sync_state > génération).

    Généré une seule fois par base : ``<hostname court>-<4 hex>`` (lisible dans
    les logs ET unique si deux machines partagent un hostname).
    """
    env = os.environ.get("EURIO_MACHINE_ID")
    if env:
        return _sanitize_machine(env)
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key='machine_id'"
    ).fetchone()
    if row is not None:
        return row[0] if not isinstance(row, sqlite3.Row) else row["value"]
    # Hostname tronqué à 11 AVANT le suffixe aléatoire : la troncature globale
    # à 16 ne doit jamais manger le suffixe (deux machines aux hostnames
    # similaires — macbook-air vs macbook-pro — collisionneraient sinon).
    host = _sanitize_machine(socket.gethostname().split(".")[0])[:11].rstrip("-")
    generated = f"{host}-{uuid.uuid4().hex[:4]}"
    # INSERT-or-ignore + re-lecture : si deux threads génèrent en même temps,
    # le premier écrit gagne et tout le monde relit la même valeur.
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES ('machine_id', ?) "
        "ON CONFLICT(key) DO NOTHING",
        (generated,),
    )
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key='machine_id'"
    ).fetchone()
    return row["value"] if isinstance(row, sqlite3.Row) else row[0]


def hlc_encode(ts_ms: int, count: int, machine: str) -> str:
    return f"{ts_ms:013d}-{count:04d}-{machine}"


def hlc_parse(hlc: str) -> tuple[int, int, str]:
    """``'0001719999999999-0003-mac-a1b2'`` → ``(ts_ms, count, machine)``."""
    ts_part, count_part, machine = hlc.split("-", 2)
    return int(ts_part), int(count_part), machine


def _read_last(conn: sqlite3.Connection) -> tuple[int, int] | None:
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key='hlc_last'"
    ).fetchone()
    if row is None:
        return None
    value = row["value"] if isinstance(row, sqlite3.Row) else row[0]
    ts_ms, count, _machine = hlc_parse(value)
    return ts_ms, count


def _write_last(conn: sqlite3.Connection, hlc: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES ('hlc_last', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (hlc,),
    )


def hlc_now(conn: sqlite3.Connection, machine: str) -> str:
    """Prochain HLC local : ``max(horloge murale, dernier HLC)`` + compteur.

    Monotone strict même si l'horloge murale recule (NTP) ou si plusieurs
    events tombent dans la même milliseconde. Persiste ``hlc_last`` dans la
    transaction du caller.
    """
    wall_ms = int(time.time() * 1000)
    last = _read_last(conn)
    if last is not None and last[0] >= wall_ms:
        ts_ms, count = last[0], last[1] + 1
        if count > _COUNT_MAX:
            ts_ms, count = ts_ms + 1, 0
    else:
        ts_ms, count = wall_ms, 0
    stamp = hlc_encode(ts_ms, count, machine)
    _write_last(conn, stamp)
    return stamp


def hlc_merge(conn: sqlite3.Connection, remote_hlc: str) -> None:
    """Avance l'horloge locale au niveau d'un HLC reçu (causalité au pull).

    Après merge, tout event local futur est ordonné APRÈS tout ce qu'on a vu
    du reste du monde — c'est ce qui rend le LWW-par-champ intuitif (« ma
    correction après un pull bat ce que j'ai pullé »).
    """
    remote_ts, remote_count, _ = hlc_parse(remote_hlc)
    last = _read_last(conn)
    if last is None or (remote_ts, remote_count) > last:
        # On stocke le HLC distant tel quel : seuls (ts, count) comptent pour
        # la monotonie ; hlc_now réémettra avec la machine locale.
        _write_last(conn, remote_hlc)
