# syntax=docker/dockerfile:1.6
#
# Eurio API (serve-role) — canonique eurio.db derrière l'API, writer unique
# (Modèle B, chunk C4). Image LÉGÈRE — mais « légère » recouvrait TROIS raisons
# distinctes qu'il ne faut pas amalgamer :
#
#   torch / ultralytics : DÉLIBÉRÉMENT ABSENTS. Aucun modèle ne tourne sur le
#     VPS (pas de GPU, et la banque d'ancres n'y a rien à faire) — cf. D6 de
#     review-collaborative-v2. Le recalcul DINO d'un crop recadré est rattrapé
#     en lot par le Mac (`go-task ml:dino-predictions:backfill`).
#   cv2 : PRÉSENT depuis le lot 6b, en variante `headless` (ni GUI ni CUDA,
#     ~35 Mo). 18,4 % des crops sont recadrés à la main ; tant que ce geste
#     vivait sur l'API ML locale, un ami invité ne faisait que la moitié du
#     travail. Les pixels restent au SERVEUR parce que `canvas.drawImage` ne
#     rééchantillonne pas comme `INTER_AREA`, et pas pareil selon le navigateur
#     et le GPU — des crops qui diffèrent selon la machine de l'ami seraient une
#     pollution silencieuse du jeu d'entraînement (D5).
#   Pillow : toujours absent, et ce n'est plus un manque — `coin_image_storage`
#     ne l'importe qu'au moment d'ENCODER (lot 6b). Seules les machines qui
#     fabriquent des images en ont besoin.
#
# Les routers de calcul lourd se skippent proprement au boot.
#
# Build context = ce dossier ; les sources viennent par `additional_contexts`
# (docker-compose.yml) : ml → ../../ml.

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/ml \
    TZ=UTC

# Deps du serve-role (API + ingest + store + S3 + recadrage). Volontairement
# SANS torch/ultralytics. Si un router léger réclame une dep absente, il est
# skippé au boot (log) — on l'ajoute alors ici.
RUN pip install --no-cache-dir \
        "fastapi>=0.115,<0.120" \
        "uvicorn[standard]>=0.32,<0.40" \
        "pydantic>=2.7,<3.0" \
        "boto3>=1.35,<2.0" \
        "httpx>=0.27,<0.30" \
        "python-jose[cryptography]>=3.3,<4.0" \
        "numpy>=1.26,<3.0" \
        "opencv-python-headless>=4.10,<5.0"

WORKDIR /srv/ml

# Sous-paquets nécessaires au serve-role. On NE copie PAS training/ (calcul
# lourd). `serving/` est copié en entier mais seuls les routers légers sont
# importés par server_serve (les modules torch ne sont jamais touchés).
#
# `vision/` et `sources/` arrivent avec le lot 6b : `crop_edit.apply_manual_crop`
# a besoin de `vision.normalize_snap._crop_mask_resize_float` (LE format de prod,
# celui qu'il ne faut surtout pas réimplémenter) et de `sources._base.phash`.
# Les deux sont du cv2+numpy pur ; leurs voisins lourds (steps/auto_validate et
# consorts) ne sont jamais importés — le recalcul DINO échoue en ImportError,
# ce qui est exactement le chemin prévu (marquage « à réencoder », D6).
COPY --from=ml serving        ./serving
COPY --from=ml store          ./store
COPY --from=ml client         ./client
COPY --from=ml shared         ./shared
COPY --from=ml jobs           ./jobs
COPY --from=ml referential    ./referential
COPY --from=ml vision         ./vision
COPY --from=ml sources        ./sources
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
