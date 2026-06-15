"""Évaluateur HYBRIDE : rejoue des politiques sur l'UNION des candidats de plusieurs runs
(A, B, …) SANS re-cropper ni re-scorer (tout est déjà loggé). Permet de choisir « le
meilleur des deux » a posteriori. Cf. BENCHMARK §5.
"""

from __future__ import annotations

import json
from pathlib import Path

from .harness import metrics


def _load(paths: list[str]) -> dict[str, list[dict]]:
    """case_id -> liste de cas (un par run)."""
    by: dict[str, list[dict]] = {}
    for p in paths:
        for c in json.loads(Path(p).read_text())["cases"]:
            by.setdefault(c["case_id"], []).append(c)
    return by


def evaluate(run_paths: list[str], policy: str = "argmax", label: str | None = None) -> dict:
    """Politiques :
      - "argmax"        : sur l'union des candidats, garder le score max ≥ τ ;
      - "B_prior"       : préférer un candidat 'B:*' s'il passe, sinon argmax (drop-in plus
                          tard si on veut tester la priorité géométrie) — ici = argmax filtré.
    Reconstruit un `result` consommable par `harness.metrics`.
    """
    by = _load(run_paths)
    tau = json.loads(Path(run_paths[0]).read_text())["tau"]
    cases = []
    for case_id, variants in by.items():
        ref = variants[0]
        pooled, seen = [], set()
        for v in variants:
            for c in v["candidates"]:
                key = (c["source"], round(c["cx"]), round(c["cy"]), round(c["r"]))
                if key in seen:
                    continue
                seen.add(key)
                pooled.append(c)
        if not pooled:
            continue
        chosen = max(range(len(pooled)), key=lambda i: pooled[i]["score"])
        base = next((c["score"] for c in pooled if c["source"] == "baseline"), None)
        cases.append({**{k: ref[k] for k in
                         ("case_id", "dataset", "raw_key", "target_eurio_id",
                          "emu_globe", "gold_circle", "is_fragment")},
                      "candidates": pooled, "chosen_idx": chosen,
                      "chosen_score": pooled[chosen]["score"],
                      "baseline_score": base,
                      "passed": pooled[chosen]["score"] >= tau})
    result = {"strategy": label or f"hybrid:{policy}", "tau": tau, "cases": cases}
    metrics(result)
    return result
