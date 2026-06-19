# ROADMAP — auth-redesign (chunks d'implémentation)

> Découpage en chunks autonomes, chacun avec son propre `Cx-HANDOFF-*.md`.
> Une session future (Claude Code ou humain) prend un chunk, l'exécute, met à
> jour le statut ici, puis remonte un résumé.
>
> **Pré-requis transverse** : lire `DESIGN.md` avant de démarrer un chunk.

## Statuts

- ⬜ todo
- 🟡 in-progress
- ✅ done
- ⏸️ blocked (raison)

## Tableau

| # | Chunk | Statut | Dépend de | Handoff |
|---|---|---|---|---|
| C1 | Provisioning Authentik (OIDC app + groups) | ⬜ | — | [`C1-HANDOFF-AUTHENTIK.md`](./C1-HANDOFF-AUTHENTIK.md) |
| C1.5 | Bootstrap déploiement `infra/eurio-api/` sur VPS (compose, secrets, Traefik, healthcheck) | ⬜ | C1 | (dans C2 §0 — sous-section dédiée) |
| C2 | `eurio-api` : middleware JWT + tables RBAC + `/me` | ⬜ | C1, C1.5 | [`C2-HANDOFF-API-RBAC.md`](./C2-HANDOFF-API-RBAC.md) |
| C3 | Tokens API personnels (modèle + endpoints + vérif machine) | ⬜ | C2 | [`C3-HANDOFF-TOKENS.md`](./C3-HANDOFF-TOKENS.md) |
| C4 | Absorption `review_service` dans `eurio-api` | ⬜ | C2 | [`C4-HANDOFF-MERGE-REVIEW.md`](./C4-HANDOFF-MERGE-REVIEW.md) |
| C5 | Panel : skeleton Vue + login OIDC + shell | ⬜ | C2 | [`C5-HANDOFF-PANEL-SHELL.md`](./C5-HANDOFF-PANEL-SHELL.md) |
| C6 | Panel : portage des écrans review | ⬜ | C4, C5 | [`C6-HANDOFF-PORT-REVIEW.md`](./C6-HANDOFF-PORT-REVIEW.md) |
| C7a | Panel : portage editorial core (sources / coins / audit / referential) + endpoints `eurio-api` correspondants | ⬜ | C5 | [`C7-HANDOFF-PORT-WEB.md`](./C7-HANDOFF-PORT-WEB.md) §C7a |
| C7b | Panel : portage sets & analytics (sets / criteria-preview / design-groups / confusion / fragment-audit / crop-recovery / denom-gold / parity / lab) + endpoints correspondants | ⬜ | C7a | [`C7-HANDOFF-PORT-WEB.md`](./C7-HANDOFF-PORT-WEB.md) §C7b |
| C8 | Panel : UI users + UI mes tokens | ⬜ | C3, C5 | [`C8-HANDOFF-USERS-UI.md`](./C8-HANDOFF-USERS-UI.md) |
| C9 | Cutover : déploiement VPS, kill Vercel + Supabase Auth + `review_service`, archive | ⬜ | C6, C7a, C7b, C8 | [`C9-HANDOFF-CUTOVER.md`](./C9-HANDOFF-CUTOVER.md) |

## Chemin critique

```
C1 ─▶ C1.5 ─▶ C2 ─┬─▶ C3 ─▶ C8 ─┐
                  ├─▶ C4 ─▶ C6 ─┤
                  └─▶ C5 ─▶ C7a ─▶ C7b ─┴─▶ C9
```

C1 → C1.5 (déploiement `eurio-api`) → C2 sont strictement séquentiels : C2 ne peut être testé E2E (callback OIDC, `/me`) sans un `eurio-api` joignable sur `eurio-api.musubi.dev`. Une fois C2 mergé, C3, C4 et C5 sont parallélisables si plusieurs sessions tournent. C7 est **scindé** en C7a (editorial core) → C7b (sets & analytics) pour garder des chunks lisibles. C9 est le cutover final all-in (cf. DESIGN.md D9), à ne déclencher qu'après C6 + C7a + C7b + C8 validés en coexistence test ≥ 7 jours.

## Conventions de chunk

Chaque `Cx-HANDOFF-*.md` doit contenir :

1. **But en 1 phrase** + ce que le chunk *ne fait pas*.
2. **Pré-requis** (chunks dépendants validés + état repo).
3. **Étapes** numérotées et exécutables.
4. **Critères d'acceptation** vérifiables (curl, requête DB, screenshot).
5. **Garde-fous** (ce qu'il ne faut pas casser, retours arrière).
6. **Résumé à produire** en fin de session (template).

Le chunk **n'invente pas** : si une déviation est nécessaire (lib manquante,
endpoint Authentik différent, schéma DB à ajuster), il la **note dans le
résumé** et met à jour `DESIGN.md` si la déviation est structurelle.

## Hors scope de la roadmap

Cf. `DESIGN.md` §9. En particulier : App Android, MinIO, SSH, pCloud, MCP.
