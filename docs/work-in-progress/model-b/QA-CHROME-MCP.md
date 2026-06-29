# QA Chrome MCP — front Model B (R1) + chemin de données (R2)

> **But.** Vérifier **de bout en bout dans un vrai navigateur** que le front fusionné
> (R1) marche aux deux endroits, que la donnée charge **du VPS** et que les images
> viennent **du bon stockage** (MinIO), que le gating « lourd » est correct, et qu'il
> n'y a **aucune fuite mixed-content**. Complète les vérifs CLI déjà faites (build,
> endpoints, healthz, sha).

## Mode d'exécution (à graver pour la session QA)

- **Modèle : Sonnet 4.6** (pas Opus — overkill ici). Si orchestration : sous-agents
  Sonnet, un **par groupe de cas** (A→F), chacun rend un tableau PASS/FAIL + preuves.
- **Outils** : MCP `claude-in-chrome`. Charger en UN seul ToolSearch :
  `tabs_context_mcp, navigate, computer, read_page, tabs_create_mcp,
  read_console_messages, read_network_requests`.
- **Pattern** : `tabs_context_mcp` d'abord (jamais réutiliser un vieux tab) → un
  **nouveau** tab par cible → naviguer → observer (DOM via `read_page`, réseau via
  `read_network_requests`, console via `read_console_messages`) → conclure.
- **Le claude-in-chrome MCP utilise la session Chrome existante de l'utilisateur** →
  si déjà loggé Authentik, le cookie est présent. **Le login Authentik interactif
  (saisie mot de passe) n'est PAS automatisable** : précondition = être déjà connecté,
  sinon demander à l'utilisateur de se logger une fois manuellement.

## Préconditions

| Cible | URL | À avoir |
|---|---|---|
| Front hébergé | `https://eurio-admin.musubi.dev` | session Authentik active dans Chrome |
| Backend canonique | `https://eurio-api.musubi.dev/healthz` → 200 | (déjà OK) |
| Images | `https://eurio-s3.musubi.dev` (MinIO presigned) | — |
| Front local | `http://localhost:5173` | `pnpm -C admin/packages/studio-local dev` |
| API ML locale | `http://127.0.0.1:8042/health` | `go-task ml:api` (pour les cas E1/E2) |

Permissions extension claude-in-chrome requises : `eurio-admin.musubi.dev`,
`eurio-api.musubi.dev`, `eurio-s3.musubi.dev`, `localhost`.

---

## Groupe A — Hébergé : chargement + auth + routing réseau

- **A1 — La page charge.** Naviguer `eurio-admin.musubi.dev`. *Attendu* : SPA rendue
  (sidebar « Eurio / Admin », pas d'écran blanc). `read_console_messages` → **0 erreur
  JS fatale** (warnings tolérés).
- **A2 — Auth cookie.** Une fois loggé : `read_network_requests` → `GET
  eurio-api.musubi.dev/me` **200**, requête avec cookies (pas de header
  `Authorization`). Le bas de sidebar affiche email + rôles (pas « Non connecté »).
  Si 401 → le bandeau `EurioSessionBanner` s'affiche (« Session expirée… Authentik »).
- **A3 — Tout passe par le VPS, zéro `:8042`.** Cliquer 3-4 vues légères. `read_network_requests`
  → **aucune** requête vers `127.0.0.1:8042` ni `http://localhost`. `read_console_messages`
  → **aucun** warning « Mixed Content » / « blocked ». ⟵ *cœur du test : l'hébergé ne tape jamais le ML local.*

## Groupe B — Hébergé : gating des features lourdes

- **B1 — Nav grisée.** Dans la sidebar, les items lourds — **Revue Numista, Revue
  référentiel, Review queue, Arbitrage Numista, Training, Cartographie ML, Lab, Studio
  bench, Crop Bench, Gold denom, Parity Viewer** — sont **grisés** (opacity réduite),
  portent le badge **« local »**, et **ne naviguent pas** au clic.
- **B2 — Notice sur accès direct.** Mettre `…/training` dans l'URL. *Attendu* :
  `LocalOnlyNotice` rendu (texte « Cette vue tourne en local » + « pnpm dev » +
  « localhost »), **pas** la vraie page Training. `read_network_requests` → **0** requête
  `:8042` déclenchée. Idem pour `/lab`, `/review`, `/bench`.
- **B3 — Légers cliquables.** Dashboard (`/`), Sets, Pièces, Sources, Audit, Operations,
  Référentiel, Utilisateurs, Mes tokens : cliquables, la vue charge.

## Groupe C — Hébergé : les 3 vues rapatriées (admin)

- **C1 — Dashboard KPIs (`/`).** Cartes KPI présentes (coins / sets / sources / review /
  users / tokens selon scopes). `GET /stats/overview` **200**. Bouton « Rafraîchir »
  met à jour l'horodatage « maj … ».
- **C2 — Users (`/users`).** `GET /users` **200**, liste rendue. Si owner : bouton
  « Modifier rôles » visible. *(Édition = action sensible : tester en lecture, ou sur un
  user de test ; NE PAS retirer le dernier owner — l'API doit refuser, vérifier le message.)*
- **C3 — Mes tokens (`/me/tokens`), cycle complet.** `GET /me/tokens` 200. Créer un token
  **de test** (nom `qa-chrome-mcp`, quelques scopes) → `POST /me/tokens` 200 → le **clair
  `eurio_…` s'affiche UNE fois** + copie. Puis **révoquer** ce token de test → `DELETE
  /me/tokens/{id}` 200, il passe « révoqué ». ⟵ *cleanup obligatoire : ne pas laisser le token de test actif.*

## Groupe D — Hébergé : données VPS + images au bon endroit

- **D1 — Images depuis MinIO.** Ouvrir une vue avec visuels (ex. **Pièces** →
  `CoinDetail`, ou review en consultation). Les images s'affichent. `read_network_requests`
  → leur URL pointe vers **`eurio-s3.musubi.dev`** (presigned MinIO) — *« stocké au bon
  endroit »*. Pas d'images 404/403.
- **D2 — Données cohérentes.** Une liste (Pièces / Sets) charge ses lignes via
  `eurio-api.musubi.dev` (GET) ; les compteurs du Dashboard sont cohérents avec ce que
  montrent les listes (ex. nb de coins).

## Groupe E — Local (`localhost:5173`) : mode PAT + features lourdes

- **E1 — Mode local, nav complète.** Avec `go-task ml:api` **ON**, ouvrir
  `localhost:5173`. *Attendu* : **aucun** item grisé (hasLocalMlApi=true après ping
  `:8042/health`). Bas de sidebar = identité via PAT.
- **E2 — Feature lourde active.** Ouvrir Training (ou Review queue). La vue charge.
  `read_network_requests` → requêtes vers **`127.0.0.1:8042`** (normal et attendu **en
  local**), + requêtes data vers `eurio-api.musubi.dev`.
- **E3 — Dégradation si ML off.** Couper `go-task ml:api`, recharger `localhost:5173`.
  *Attendu* : items lourds **grisés** + `LocalOnlyNotice` « lance l'API ML » (le ping
  `:8042` échoue → `mlStatus=down`). Relancer `ml:api` + recharger → de nouveau actifs.
- **E4 — Auth PAT.** `GET eurio-api.musubi.dev/me` **200** avec header
  `Authorization: Bearer eurio_…` (pas de cookie). Si pas de PAT → bandeau « aucun PAT ».

## Groupe F — Sanity backend (rapide, pour cadrer)

- **F1** — `https://eurio-api.musubi.dev/healthz` → **200** (peut se faire via navigate +
  read_page). *(Le chemin réplique `/db/replica` est couvert par la vérif CLI R2, pas un test browser.)*

---

## Rapport attendu

Tableau par groupe : `cas | PASS/FAIL | preuve (status réseau / texte console / capture)`.
Tout FAIL : décrire, joindre la requête réseau ou l'erreur console, et l'étape de repro.
À la fin : verdict global + liste des écarts à corriger.

## Garde-fous d'exécution

- Actions **sensibles** (C2 édition rôles, C3 création/révocation token) : **objets de
  test uniquement**, **cleanup** systématique (révoquer le token `qa-chrome-mcp`). Ne
  jamais toucher au dernier owner.
- Pas de dialogs JS (`confirm`/`alert`) laissés ouverts — ils figent l'extension. La
  révocation token utilise un `confirm()` natif → soit l'éviter, soit prévenir.
- `read_network_requests` avec filtre d'hôte pour trancher la cible (`eurio-api` vs
  `:8042` vs `eurio-s3`) — c'est la preuve clé de A3 / D1 / E2.
- Bloqué après 2-3 essais sur un cas → **stop**, rapport de ce qui a été tenté, on
  demande. Ne pas boucler.
