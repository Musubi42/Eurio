"""Client SDK workstation → serveur canonique (Modèle B).

Le calcul lourd (scraping/crop/dino/training) tourne sur Mac/PC contre une
réplique read-only de ``eurio.db`` et pousse ses résultats au serveur canonique
(writer unique) par **run-batch**. Ce package est la SEULE porte d'écriture du
compute vers le canonique — il ne touche jamais le fichier canonique en direct.

Voir ``docs/work-in-progress/model-b/DESIGN.md``.

Chunks :
- C1 (livré) : ``runbatch`` — export/ingest d'un run, idempotent.
- C2 (livré) : ``http`` (client urllib, ``EURIO_API_URL`` + ``EURIO_API_TOKEN``).
- C3 (livré) / R2 : ``replica`` — ``pull_replica()`` tire la réplique DU VPS
  (``GET /db/replica``) → ``eurio.replica.db`` (plus de MinIO/lease).
"""
