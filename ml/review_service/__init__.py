"""Service review collaboratif (VPS) — review.db SQLite + FastAPI.

App autonome, toujours allumée sur le VPS. N'ouvre QUE `review.db` (jamais
`eurio.db`). Des amis non-techniques reviewent des pièces en parallèle ; leurs
décisions sont tirées dans `eurio.db` (staging `peer_review_decisions`) par
`go-task ml:review:reconcile`, puis arbitrées côté admin.

cf. docs/work-in-progress/collaborative-review/
"""
