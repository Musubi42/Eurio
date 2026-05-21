"""Stable hash of a `SourceQuery` used for `discovery_log.query_signature`.

A short hex digest (16 chars = 64 bits of sha256) is enough to
distinguish cohort-level queries while staying robust to future
filter additions: as long as the new field has a deterministic
default (None, empty dict), pre-existing signatures stay stable.

Lisibility is sacrificed on purpose — see kickoff §"Décisions à
valider" question 3.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from sources._base.adapter import SourceQuery


def compute_query_signature(query: SourceQuery) -> str:
    payload = asdict(query)
    # target_eurio_ids / discovery_groups: stable sort so the signature
    # is order-independent (a batch of [A, B, C] hashes the same as
    # [C, B, A]). asdict() has already turned each DiscoveryGroup into a
    # plain dict, so we sort the group dicts by their canonical JSON.
    if payload.get("target_eurio_ids") is not None:
        payload["target_eurio_ids"] = sorted(payload["target_eurio_ids"])
    if payload.get("discovery_groups") is not None:
        payload["discovery_groups"] = sorted(
            payload["discovery_groups"],
            key=lambda g: json.dumps(g, sort_keys=True),
        )
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
