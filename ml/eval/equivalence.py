"""Design-group equivalence — phase 3 (lab-prod-refacto), Option B.

Le lab entraîne en `eurio_id` strict (cf. phase 1) — chaque coin a son
centroïde individuel. La prod considère deux `eurio_id` partageant le
même `design_group_id` comme équivalents au moment du verdict (un
matcher Android peut prédire BE-2007 quand la pièce est BE-2008 sans
que ce soit une erreur — design partagé).

Cette équivalence est appliquée à deux endroits :

  - Bench Python (`evaluate_real_photos.py`) : émet R@k strict ET R@k
    eq.
  - Matcher Android : règle de verdict identique (cf. brief Android
    dans `docs/lab-prod-refacto/progress.md` phase 3).

Les deux implémentations doivent rester en parité — même map source
(table `coins` Supabase), même règle. Cf.
`feedback_output_contract_parity.md`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eval.class_resolver import coin_refs_from_sqlite


@dataclass(frozen=True)
class EquivalenceMap:
    """Maps each `eurio_id` to its `design_group_id` (or None if standalone)."""

    eurio_to_group: dict[str, str | None]

    def design_group(self, eurio_id: str) -> str | None:
        return self.eurio_to_group.get(eurio_id)

    def are_equivalent(self, predicted: str, ground_truth: str) -> bool:
        """True when predicted is correct under the design-group rule.

        - Strict eurio_id match → equivalent.
        - Same non-null design_group_id → equivalent.
        - Otherwise → not equivalent.
        """
        if predicted == ground_truth:
            return True
        g_pred = self.eurio_to_group.get(predicted)
        g_gt = self.eurio_to_group.get(ground_truth)
        return g_pred is not None and g_pred == g_gt

    def to_json(self) -> str:
        return json.dumps(self.eurio_to_group, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "EquivalenceMap":
        return cls(eurio_to_group=dict(json.loads(text)))

    @classmethod
    def from_path(cls, path: Path) -> "EquivalenceMap":
        return cls.from_json(Path(path).read_text())


def build_equivalence_map() -> EquivalenceMap:
    """Load the eurio_id → design_group_id map from the canonical eurio.db."""
    coins = coin_refs_from_sqlite()
    return EquivalenceMap(
        eurio_to_group={c.eurio_id: c.design_group_id for c in coins}
    )
