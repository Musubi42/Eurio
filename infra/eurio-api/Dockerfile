# syntax=docker/dockerfile:1.6
#
# Eurio API (serve-role) — canonique eurio.db derrière l'API, writer unique
# (Modèle B, chunk C4). Image LÉGÈRE : PAS de torch/cv2/ultralytics (no CV/ML sur
# le VPS). Les routers de calcul lourd se skippent proprement au boot.
#
# Build context = ce dossier ; les sources viennent par `additional_contexts`
# (docker-compose.yml) : ml → ../../ml.

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/ml \
    TZ=UTC

# Deps strictement nécessaires au serve-role (API + ingest + store + S3).
# Volontairement SANS torch/opencv/ultralytics. Si un router léger réclame une
# dep absente, il est skippé au boot (log) — on l'ajoute alors ici.
RUN pip install --no-cache-dir \
        "fastapi>=0.115,<0.120" \
        "uvicorn[standard]>=0.32,<0.40" \
        "pydantic>=2.7,<3.0" \
        "boto3>=1.35,<2.0" \
        "httpx>=0.27,<0.30" \
        "python-jose[cryptography]>=3.3,<4.0"

WORKDIR /srv/ml

# Sous-paquets nécessaires au serve-role. On NE copie PAS sources/vision/training
# (calcul lourd). `serving/` est copié en entier mais seuls les routers légers
# sont importés par server_serve (les modules cv2/torch ne sont jamais touchés).
COPY --from=ml serving        ./serving
COPY --from=ml store          ./store
COPY --from=ml client         ./client
COPY --from=ml shared         ./shared
COPY --from=ml jobs           ./jobs
COPY --from=ml referential    ./referential
COPY --from=ml review         ./review
COPY --from=ml state/schema.sql ./state/schema.sql

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Canonique monté en volume (writer unique). Auth bearer requise sur le serveur.
ENV EURIO_DB_PATH=/var/lib/eurio/eurio.db \
    EURIO_API_AUTH_REQUIRED=1

EXPOSE 8042

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "serving.server_serve:app", "--host", "0.0.0.0", "--port", "8042"]
