"""Store — domaine staging (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations


from .common import ClassRef





class StagingMixin:

    # ─── Staging (add) ───────────────────────────────────────────────────

    def stage_classes(
        self,
        items: list[ClassRef],
        *,
        aug_recipe_ids: list[str | None] | None = None,
    ) -> None:
        """Stage classes for the next training run.

        ``aug_recipe_ids`` is an optional parallel list — same length as
        ``items`` — associating each class with a recipe id (or None).
        Backwards-compatible: callers that pass only ``items`` get the legacy
        behaviour (aug_recipe_id stays null).
        """
        if not items:
            return
        if aug_recipe_ids is None:
            aug_recipe_ids = [None] * len(items)
        if len(aug_recipe_ids) != len(items):
            raise ValueError(
                f"aug_recipe_ids length {len(aug_recipe_ids)} != items length {len(items)}"
            )
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO training_staging (class_id, class_kind, aug_recipe_id)
                VALUES (?, ?, ?)
                ON CONFLICT(class_id) DO UPDATE SET
                  class_kind = excluded.class_kind,
                  aug_recipe_id = excluded.aug_recipe_id,
                  staged_at = datetime('now')
                """,
                [
                    (item.class_id, item.class_kind, recipe_id)
                    for item, recipe_id in zip(items, aug_recipe_ids)
                ],
            )

    def unstage_class(self, class_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM training_staging WHERE class_id = ?",
                (class_id,),
            )
            return cur.rowcount > 0

    def list_staging(self) -> list[ClassRef]:
        rows = self._connection().execute(
            "SELECT class_id, class_kind FROM training_staging ORDER BY staged_at"
        ).fetchall()
        return [ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]) for r in rows]

    def list_staging_with_recipe(self) -> list[tuple[ClassRef, str | None]]:
        """Same as list_staging but also returns the aug_recipe_id per item."""
        rows = self._connection().execute(
            "SELECT class_id, class_kind, aug_recipe_id FROM training_staging "
            "ORDER BY staged_at"
        ).fetchall()
        return [
            (
                ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]),
                r["aug_recipe_id"],
            )
            for r in rows
        ]

    def clear_staging(self) -> list[ClassRef]:
        with self._writing() as c:
            rows = c.execute(
                "SELECT class_id, class_kind FROM training_staging"
            ).fetchall()
            c.execute("DELETE FROM training_staging")
            return [
                ClassRef(class_id=r["class_id"], class_kind=r["class_kind"])
                for r in rows
            ]

    def clear_staging_with_recipe(self) -> list[tuple[ClassRef, str | None]]:
        """Drain the staging table and also return the aug_recipe_id per item."""
        with self._writing() as c:
            rows = c.execute(
                "SELECT class_id, class_kind, aug_recipe_id FROM training_staging"
            ).fetchall()
            c.execute("DELETE FROM training_staging")
            return [
                (
                    ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]),
                    r["aug_recipe_id"],
                )
                for r in rows
            ]

    # ─── Staging (removal) ───────────────────────────────────────────────

    def stage_removal(self, items: list[ClassRef]) -> None:
        if not items:
            return
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO training_removal_staging (class_id, class_kind)
                VALUES (?, ?)
                ON CONFLICT(class_id) DO UPDATE SET
                  class_kind = excluded.class_kind,
                  staged_at = datetime('now')
                """,
                [(i.class_id, i.class_kind) for i in items],
            )

    def unstage_removal(self, class_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM training_removal_staging WHERE class_id = ?",
                (class_id,),
            )
            return cur.rowcount > 0

    def list_removal_staging(self) -> list[ClassRef]:
        rows = self._connection().execute(
            "SELECT class_id, class_kind FROM training_removal_staging "
            "ORDER BY staged_at"
        ).fetchall()
        return [ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]) for r in rows]

    def clear_removal_staging(self) -> list[ClassRef]:
        with self._writing() as c:
            rows = c.execute(
                "SELECT class_id, class_kind FROM training_removal_staging"
            ).fetchall()
            c.execute("DELETE FROM training_removal_staging")
            return [
                ClassRef(class_id=r["class_id"], class_kind=r["class_kind"])
                for r in rows
            ]
