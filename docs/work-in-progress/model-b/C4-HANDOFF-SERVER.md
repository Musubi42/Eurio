# HANDOFF — déployer l'eurio-api sur le VPS (Modèle B, chunk C4)

> **Pour qui** : une session Claude Code (ou un humain) qui tourne **sur le VPS**
> (NixOS, flake `vps`, là où tournent déjà MinIO + review_service via Docker).
> **But** : bâtir et démarrer le conteneur `eurio-api` (canonique `eurio.db`
> derrière FastAPI, writer unique, auth bearer, Traefik), puis **rédiger un résumé**
> (modèle en fin de doc) que l'utilisateur ramènera à la session de design.
>
> Tu n'écris PAS de code applicatif ici : tout le code est déjà dans le repo
> (`infra/eurio-api/` + `ml/serving/server_serve.py`). Ton job = déployer, vérifier,
> reporter. Si tu dois dévier (dep manquante, nom de réseau, domaine), **fais-le et
> note-le dans le résumé**.

## 0. Contexte (à lire d'abord)

On migre `eurio.db` d'un fichier-unique-sous-lease (Modèle A) vers un **canonique
serveur derrière l'API** (Modèle B). Le serveur FastAPI devient le **writer unique**
(SQLite WAL) ; les clients (Mac/PC) parleront HTTP. Détails : `DESIGN.md` (même dossier).

**⚠️ C4 est un stand-up de VALIDATION, PAS le cutover.** Le conteneur :
- **seed** une *copie* de `eurio.db` depuis MinIO (`bucket eurio-db`) au 1er boot ;
- **n'y re-pousse JAMAIS** (aucun chemin d'écriture vers MinIO dans le serve-role).

Donc cette copie diverge volontairement du canonique réel ; le Mac reste le writer
via le lease jusqu'au cutover (C8). **Ne branche pas la vraie console admin dessus**
(c'est C5) et considère toute écriture testée ici comme jetable (re-seedée au cutover).

L'image est **légère** (pas de torch/cv2) : `server_serve.py` monte un cœur garanti
(`/healthz`, auth, `/ingest/run`) puis les routers interactifs légers en best-effort
(ceux qui réclament cv2/torch — `review_queue`, `coin_assets` — se **skippent** et
sont journalisés ; c'est normal et voulu : pas de CV/ML sur le VPS).

## 1. Prérequis (vérifier, ne pas supposer)

```bash
docker --version && docker compose version          # compose ≥ 2.17 (additional_contexts)
docker network ls | grep traefik                    # réseau 'traefik' externe existe (cf. infra/review)
docker ps | grep -iE 'traefik|minio|review'         # Traefik + MinIO up
ls /opt/eurio || echo "repo absent ?"               # le repo Eurio (adapter le chemin si besoin)
```
- Le repo doit être présent et à jour : `cd /opt/eurio && git pull` (branche
  `sources-jo-wikipedia` pour l'instant — vérifie avec l'utilisateur si une autre).
- MinIO doit contenir l'objet `eurio-db/eurio.db` (+ `eurio-db/eurio.db.sha256`).
  Vérifie : `mc ls <alias>/eurio-db/` (l'alias `mc` est configuré côté VPS).
  **S'il est absent**, STOP : l'utilisateur doit d'abord `go-task ml:db:release`
  depuis le Mac. Note-le dans le résumé.
- DNS : un enregistrement `eurio-api.musubi.dev` → IP du VPS (comme
  `eurio-review.musubi.dev`). Si absent, crée-le (même provider) ou note-le.

## 2. Secrets

```bash
cd /opt/eurio/infra/eurio-api
cp secrets/minio_access_key.example  secrets/minio_access_key
cp secrets/minio_secret_key.example  secrets/minio_secret_key
# Remplace par les VRAIES clés MinIO (les mêmes que infra/review/secrets/* —
# tu peux les copier de là si présentes).
$EDITOR secrets/minio_access_key secrets/minio_secret_key
```
Les `secrets/*` (hors `.example`) sont gitignorés. Pas de token d'API dans un
fichier : les tokens bearer sont créés en base après le boot (étape 4).

## 3. Vérifier la config avant de lancer

Ouvre `docker-compose.yml` et confirme/adapte :
- `MINIO_ENDPOINT` (défaut `eurio-s3.musubi.dev`) = le même que `infra/review`.
- `EURIO_API_CORS_ORIGINS` = origine(s) de la console admin (Vercel + localhost).
- Le domaine Traefik `eurio-api.musubi.dev` et le `certresolver=letsencryptresolver`
  = mêmes valeurs que `infra/review/docker-compose.yml` (compare les deux ; aligne
  si le resolver ou le réseau diffèrent sur ce VPS).

## 4. Build, run, créer un token

```bash
docker compose up -d --build
docker compose logs -f eurio-api        # observe le boot ; Ctrl-C quand stable
```
Au boot tu dois voir :
- `[bootstrap_canonical] seedé depuis MinIO (…) → /var/lib/eurio/eurio.db`
  (ou `présent localement` si re-run) ;
- `serve-role prêt | DB=… | auth=True` ;
- `routers montés : [...]` et éventuellement `routers skippés : [...]`
  (review_queue/coin_assets skippés = **attendu** sur l'image lean).

Crée un token bearer pour le Mac (et un pour le PC) :
```bash
docker compose exec eurio-api python -m serving.auth add-token --name mac
docker compose exec eurio-api python -m serving.auth add-token --name pc
docker compose exec eurio-api python -m serving.auth list
```
**Copie les tokens affichés** (non ré-affichables) et donne-les à l'utilisateur
de façon sûre (il les mettra dans `secrets/dev.env` côté Mac/PC comme
`EURIO_API_TOKEN`). **Ne colle PAS les tokens en clair dans le résumé** — juste les
*noms* créés.

## 5. Vérifications (à reporter)

```bash
# a) Liveness (ouvert, sans auth)
curl -s https://eurio-api.musubi.dev/healthz ; echo
#   → {"ok":true,"role":"serve","db":"/var/lib/eurio/eurio.db"}

# b) Auth ACTIVE : sans token → 401
curl -s -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/ingest/run/none

# c) Avec token → 200 (statut d'un run inexistant = applied:false)
TOKEN=<colle_un_token_mac_ici_localement_pas_dans_le_resume>
curl -s -H "Authorization: Bearer $TOKEN" \
     https://eurio-api.musubi.dev/ingest/run/does-not-exist ; echo
#   → {"run_id":"does-not-exist","applied":false}

# d) (optionnel) round-trip ingest : POST un petit batch et re-GET le statut.
#    Demande à la session de design un batch JSON minimal si tu veux pousser ce test.
```
Note aussi : le certificat TLS est-il bien émis (Let's Encrypt via Traefik) ? Si
`curl` se plaint du cert, attends la propagation/émission ou vérifie les logs Traefik.

## 6. Garde-fous / dépannage

- **`additional_contexts` non supporté** → compose trop vieux ; utilise `docker
  compose` v2 (plugin) et non `docker-compose` v1.
- **Un router léger attendu est SKIPPÉ** (autre que review_queue/coin_assets) →
  copie le message d'erreur exact dans le résumé (souvent une dep Python légère
  manquante, ex. `httpx`/`supabase` ; on l'ajoutera au `Dockerfile`). Ne tente PAS
  d'installer torch/opencv (interdit sur le VPS).
- **`bootstrap_canonical` dit "AUCUNE DB distante"** → l'objet `eurio-db/eurio.db`
  manque dans MinIO ; STOP, voir §1.
- **OOM / conteneur tué** → ne devrait pas arriver (image lean, pas d'inférence).
  Si ça arrive, copie `docker compose logs` + `free -m` dans le résumé.
- Ne fais **aucun** `mc cp` / push vers `eurio-db/` : le serve-role ne doit jamais
  écrire le canonique distant (pas de split-brain avec le lease du Mac).

## 7. Résumé à produire (handoff retour)

À la fin, écris ce résumé (l'utilisateur le ramènera à la session de design) :

```
## C4 — résumé de déploiement eurio-api

- Repo : <commit sha déployé> (branche <…>)
- Build : OK / KO (+ erreur)
- Conteneur : up depuis <…> / restart-loop / KO
- bootstrap_canonical : seedé (sha …) / présent / AUCUNE DB distante
- Boot log — routers MONTÉS : [...]
- Boot log — routers SKIPPÉS : [...]   (review_queue/coin_assets attendus ; signale tout autre + l'erreur exacte)
- Auth : tokens créés (NOMS uniquement) : [mac, pc, …]
- Vérifs HTTP :
    - /healthz : <réponse>
    - /ingest/run/none sans token : <code HTTP>   (attendu 401)
    - /ingest/run/... avec token : <réponse>      (attendu applied:false)
    - round-trip ingest (si fait) : <résultat>
- TLS / DNS : cert émis ? domaine résout ? <…>
- Déviations vs ce handoff : <…>
- Erreurs / blocages : <…>
- Questions ouvertes pour la session de design : <…>
```
```
```
