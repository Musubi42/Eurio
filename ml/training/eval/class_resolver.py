"""Ré-export — le corps de ce module a été relocalisé dans ``store/class_resolver.py``
(C3, Direction A) : stdlib-only, ne lit que ``eurio.db``, importable depuis
``store/funnel.py`` (lecture funnel lean VPS) sans tirer numpy/torch.

Ce shim préserve tous les usages existants (``from training.eval.class_resolver
import build_resolver`` etc.) sans duplication ni drift. Nouveau code : importer
directement ``store.class_resolver``.
"""
from __future__ import annotations

from store.class_resolver import (
    MANIFEST_FILENAME,
    ClassDescriptor,
    CoinRef,
    Resolver,
    build_resolver,
    build_resolver_from_cohort_csv,
    coin_refs_from_cohort_csv,
    coin_refs_from_sqlite,
    load_env,
    read_manifest,
    write_manifest,
)

__all__ = [
    "MANIFEST_FILENAME",
    "ClassDescriptor",
    "CoinRef",
    "Resolver",
    "build_resolver",
    "build_resolver_from_cohort_csv",
    "coin_refs_from_cohort_csv",
    "coin_refs_from_sqlite",
    "load_env",
    "read_manifest",
    "write_manifest",
]
