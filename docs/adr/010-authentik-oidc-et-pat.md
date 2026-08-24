# ADR-010 — Authentik en IDP unique, PAT pour les machines, RBAC dans `eurio-api`

- **Statut** : ✅ Acceptée
- **Date** : 2026-06-19 · livré et déployé (C1→C4) le jour même
- **Supersède** : les quatre surfaces × quatre auths d'avant (Supabase OTP côté admin web,
  cookie HMAC maison du `review_service`, tokens `?u=Paolo42`, pattern `add-token` du C4 model-b)

## Contexte

Avant cette décision, Eurio comptait **quatre surfaces avec quatre mécanismes d'auth
différents** : l'admin Vue sur Vercel (Supabase OTP), le `review_service` sur le VPS
(cookie HMAC maison), la régie reviewer (`review-admin`, encore autre chose), et les
appels machine Mac/PC (un token collé à la main). Aucune n'avait de modèle de droits :
soit tout, soit rien.

Un compte Authentik était **déjà déployé** sur `authentik.musubi.dev` pour d'autres
stacks du serveur, avec sa gestion d'utilisateurs, de groupes et son MFA.

## Décision

**Authentik est l'IDP unique. `eurio-api` est le seul backend qui vérifie l'identité.**

- **Humains** : OIDC contre Authentik → cookie `eurio_session` posé par `eurio-api`.
- **Machines** (Mac, PC, CLI, futurs runners) : **PAT** de style GitHub — créés depuis
  le panel par l'utilisateur connecté, **scopés en intersection avec ses rôles**,
  révocables, stockés en `sha` uniquement.
- **L'identité est humaine et durable.** Il n'y a pas de « compte machine » : le Mac
  n'est pas une personne, et une capacité matérielle (un GPU) ne définit pas une
  identité. Mac et PC sont des **jetons de la même identité**.
- **RBAC** : trois rôles applicatifs (`owner`, `admin`, `reviewer`) mappés depuis les
  groupes Authentik, plus des **scopes fins** (`review:read`, `review:write`,
  `review:arbitrate`, `coins:write`, `training:run`, `users:manage`…).
- **Les scopes SONT le modèle de droits.** Aucun second système de permissions. Le
  serveur les fait respecter route par route (`require_scope`) ; le filtrage de
  navigation côté front est du **confort**, pas une garde.
- `users`, `roles`, `user_roles`, `api_tokens` vivent dans `eurio.db` (SQLite). Le
  miroir local d'un utilisateur se crée seul au premier login (claim `sub`). Aucun mot
  de passe n'est stocké côté Eurio.
- `review_service` est **absorbé** par `eurio-api` : une API, un middleware, un CORS,
  un rate-limit.

Corollaire : **les scopes effectifs sont `jeton ∩ rôles`.** Le PO peut donc se forger
un PAT restreint et vivre l'expérience d'un reviewer depuis son propre compte, sans
créer aucun compte Authentik — ce qui a permis de recetter toute la review
collaborative avant d'inviter qui que ce soit.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Garder Supabase Auth | ❌ Lie l'identité admin à un SaaS qu'on est par ailleurs en train de réduire à une projection read-only. Pas de RBAC utilisable |
| Rouler son propre IDP | ❌ MFA, reset de mot de passe, sessions, providers OAuth : tout est déjà écrit dans Authentik, déjà déployé, déjà sauvegardé |
| Lien magique adossé à `pat_tokens` pour les amis | ❌ Techniquement viable, mais impose un **second mode d'auth** dans le front hébergé (cookie), une route de création hors OIDC et une révocation à gérer. C'est du code possédé pour toujours — exactement ce que les tokens `?u=` avaient déjà coûté |
| Un compte machine par machine | ❌ Multiplie les identités sans rien apporter. Un jeton révoqué suffit à couper une machine |
| Postgres pour `users`/`roles` | ❌ Zéro infra à ajouter tant qu'on est sous ~50 utilisateurs. Le schéma est trivialement portable |

## Conséquences

**Bonnes.** Créer un reviewer coûte deux minutes une fois, côté PO, et zéro côté
l'invité. Un `403` est une vraie garde serveur, pas une page cachée. La révocation est
immédiate et centralisée.

**Mauvaises, et assumées.**

- **`ROLE_SCOPES` est un dict Python en dur** (`auth_principal.py:33`) : ajuster ce que
  voit un rôle = un changement de code + un redéploiement. Acceptable à trois rôles ;
  le jour où le réglage devient fin, ce dict doit descendre en base.
- Toute la chaîne dépend d'Authentik : s'il tombe, plus personne ne se connecte
  (les PAT, eux, continuent de fonctionner).
- Le PAT local vit dans `.env.local` (gitignoré). Un PAT en clair sur un disque reste
  un PAT en clair sur un disque.

## Voir aussi

- Front qui consomme cette auth : [ADR-011](./011-front-admin-unique.md)
- Quarantaine des décisions d'un reviewer : [ADR-012](./012-review-collaborative-ecriture-directe.md)
- Handoffs d'implémentation C1→C5, conservés : [`../archive/auth-redesign/`](../archive/auth-redesign/)
