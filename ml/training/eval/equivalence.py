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

from training.eval.class_resolver import coin_refs_from_sqlite


@dataclass(frozen=True)
class EquivalenceMap:
    """Maps each `eurio_id` to its `design_group_id` (or None if standalone)."""

    eurio_to_group: dict[str, str | None]

    def design_group(self, eurio_id: str) -> str | None:
        return self.eurio_to_group.get(eurio_id)

    def coalesce(self, label: str | None) -> str | None:
        """Resolve a label to its canonical mesh id COALESCE(group, eurio_id).

        ``label`` may be **either** a raw ``eurio_id`` (mapped to its
        ``design_group_id`` when it has one) **or** an already-canonical
        ``design_group_id`` (the lab trains/predicts on the mesh, so a
        prediction is a group id, not a key in this map → passthrough). A
        standalone eurio_id (group=None) also passes through. An unknown
        label passes through unchanged.
        """
        if label is None:
            return None
        return self.eurio_to_group.get(label) or label

    def are_equivalent(self, predicted: str | None, ground_truth: str) -> bool:
        """True when predicted is correct under the design-group rule.

        Compares both sides on the COALESCE(group, eurio_id) mesh, so it is
        symmetric and handles a **design_group id** as input (the lab predicts
        mesh labels, not eurio_ids). Must stay in parity with the Android
        ``EquivalenceMap.areEquivalent`` (cf. commit bc17d955) and
        ``feedback_output_contract_parity.md``.

        - Strict eurio_id match → equivalent.
        - Same non-null design_group_id (either side raw or already a group
          id) → equivalent.
        - Otherwise → not equivalent.
        """
        if predicted is None:
            return False
        return self.coalesce(predicted) == self.coalesce(ground_truth)

    def to_json(self) -> str:
        return json.dumps(self.eurio_to_group, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "EquivalenceMap":
        return cls(eurio_to_group=dict(json.loads(text)))

    @classmethod
    def from_path(cls, path: Path) -> "EquivalenceMap":
        return cls.from_json(Path(path).read_text())


def build_equivalence_map(db_path: Path | None = None) -> EquivalenceMap:
    """Load the eurio_id → design_group_id map from the canonical eurio.db.

    ``db_path`` overrides the default resolution (which honours
    ``EURIO_DB_PATH``) — pass the bound store's ``db_path`` to stay on the
    same DB as the caller (hermetic tests, replica vs canonical, etc.).
    """
    coins = coin_refs_from_sqlite(db_path=db_path)
    return EquivalenceMap(
        eurio_to_group={c.eurio_id: c.design_group_id for c in coins}
    )
