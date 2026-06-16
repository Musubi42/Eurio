# infra/eurio-api — API canonique (Modèle B, serve-role)

Stand-up de `eurio.db` derrière l'API FastAPI sur le VPS (writer unique, auth
bearer, Traefik). Image **légère** (pas de torch/cv2) : seuls les routers
interactifs légers + `/ingest/run` sont servis ; les routers de calcul lourd se
skippent au boot (log).

- Déploiement pas-à-pas : **`docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`**.
- Design d'ensemble : `docs/work-in-progress/model-b/DESIGN.md`.

⚠️ **C4 = stand-up + validation en ISOLATION.** L'API seed une **copie** de
`eurio.db` depuis MinIO et n'y re-pousse jamais. Le Mac reste le writer réel (lease)
jusqu'au cutover (C8). Ne pas faire d'admin réel contre cette API tant que C5/C8
ne sont pas faits.

```bash
cp secrets/minio_access_key.example  secrets/minio_access_key   # vraies clés
cp secrets/minio_secret_key.example  secrets/minio_secret_key
docker compose up -d --build
docker compose exec eurio-api python -m serving.auth add-token --name mac
```
