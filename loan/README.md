# Loan — page publique « prête-moi tes pièces 2€ »

> Mini-site Vercel autonome, partageable à des amis non-tech, pour
> identifier les pièces 2€ qu'ils peuvent me prêter afin d'enrichir
> le dataset d'entraînement du scan Eurio.

## Vision produit

Raphaël possède **78** pièces 2€ sur les **508** référencées dans Eurio
(circulation + commémo, avec `numista_id` et image curated). Pour
tester l'app sur plus de designs, il veut emprunter physiquement les
pièces 2€ de ses amis.

Cette page :

1. Affiche un **catalogue mobile-first** des 508 pièces 2€ avec
   images, pays, année, type d'émission.
2. Indique **clairement les pièces que je possède déjà** (inutile de
   me les prêter).
3. Permet à un visiteur, après une **identification légère** (prénom +
   emoji, pas d'auth), de **claim** les pièces qu'il possède pour me
   les prêter. Stocké côté Vercel KV.
4. Donne accès à une **page Coin Detail simplifiée** (méta + prix
   marché + refs externes), sans aucun signal ML.

Une **page admin** sur le même site (`/admin`, basic auth) me permet
de voir tous les claims regroupés par ami et de les cocher/décocher
quand je discute avec eux IRL (ex. : « j'ai cette pièce mais je ne
veux pas te la prêter »).

## Architecture — pas de sync Vercel ↔ Supabase

Décision tranchée : **les claims restent dans Vercel KV**, point. Pas
de table `coin_loans` côté Supabase. Pourquoi :

- La table `coins` côté Eurio n'a besoin que d'un signal binaire :
  *« est-ce que j'ai accès physique à cette pièce pour entraîner /
  tester ? »*. Qui a prêté quoi, c'est du tracking opérationnel, pas
  du métier ML.
- Le tracking physique (qui m'a prêté quoi, rendu, pas rendu) vit
  dans **Notion**, pas dans l'admin Eurio. La page admin doit rester
  centrée sur la donnée ML/curation.
- Le sync KV → Supabase ajouterait une commande, un script, un risque
  de désynchro pour zéro valeur ajoutée.

Conséquences :

- Côté `coins` table Eurio : on ajoute **une seule** colonne
  `lent_to_me boolean DEFAULT false` (cf. `data-model.md`). Toggle
  manuel depuis la page admin `/coins` (3e checkbox sur la card,
  à côté de `personal_owned`).
- Côté Loan Vercel : aucune connexion Supabase au runtime. La clé
  service role n'est utilisée qu'au build local, pour figer
  `catalog.json` et copier les images dans `public/coins/`.

## Périmètre & non-objectifs

| Périmètre | Hors-scope |
|---|---|
| Pièces 2€ uniquement (`face_value = 2`) | Autres dénominations |
| Curated : `numista_id NOT NULL` ET image présente | Pièces sans méta |
| Multi-claim sans policy | Réservation exclusive |
| Identification prénom + emoji | Auth, OAuth |
| Admin Vercel-side avec basic auth | Auth complexe, rôles |
| Tracking physique dans **Notion** (externe) | Workflow loan dans admin Eurio |
| Build local, **pas de sync** Vercel→Supabase | Migration auto, webhooks |

## Stack

- **Next.js 15 App Router** (TS) — déployé sur Vercel free tier
- **Vercel KV** (Upstash Redis) — stockage des claims + admin overrides
- **Tailwind CSS** + import direct de `shared/tokens.css`
- **Build local uniquement** : `SUPABASE_SERVICE_ROLE_KEY` ne quitte
  jamais ma machine. Catalog et images figés au build, déployés via
  `vercel deploy --prebuilt`.
- **Aucun runtime Supabase côté Vercel.** Vercel ne parle qu'à KV.
- **Images en `public/coins/`** copiées au build : zéro egress
  Supabase Storage à l'usage.

## Pages

| Route | Auth | Description |
|---|---|---|
| `/` | — | Identification (prénom + emoji) si premier passage, sinon redirige vers `/catalog` |
| `/catalog` | identifié | Liste mobile-first 508 pièces 2€ avec filtres. Filtre par défaut « pas chez Raph ». |
| `/coins/[eurio_id]` | identifié | Coin Detail allégé (images, méta, prix, refs externes) |
| `/admin` | basic auth | Vue groupée par ami : claims par personne, toggle confirm/reject |

L'URL pattern `/coins/[eurio_id]` est aligné sur l'admin Eurio pour
faciliter le partage.

## Identification (visiteurs)

- Prénom libre + un **emoji** dans une palette de 12.
- Stocké `{ id: nanoid(8), name, emoji }` en localStorage et mirroré
  en KV (`user:{id}`).
- L'`id` est envoyé sur chaque mutation. Pas de cookie http-only.
- Pas d'URL avec param d'identification.

## Auth admin

- Basic auth via Next middleware sur `/admin/*` et `/api/admin/*`.
- Vars Vercel : `LOAN_ADMIN_USERNAME`, `LOAN_ADMIN_PASSWORD`.
- Suffit pour empêcher le tout-venant de bidouiller.

## Documents adjacents

- [`docs/data-model.md`](docs/data-model.md) — schéma KV (claims +
  rejected), colonne `coins.lent_to_me`, pas de `coin_loans`.
- [`docs/build-and-deploy.md`](docs/build-and-deploy.md) — workflow
  build local, copie des images, deploy `--prebuilt`, vars d'env.
- [`docs/ux-flows.md`](docs/ux-flows.md) — wireframes textuels :
  `/`, `/catalog`, `/coins/[id]`, `/admin`.
- [`howto.md`](howto.md) — guide « je reviens 6 mois plus tard, voilà
  comment je relance le projet et fais le tour des claims ».

## Status

- [ ] Doc validée
- [ ] Scaffold Next 15 + Tailwind + tokens import
- [ ] Build script `loan:build-catalog` + copie images
- [ ] Page `/catalog` mobile-first avec filtres
- [ ] Page `/coins/[id]` simplifiée
- [ ] Identification + KV writes (claims)
- [ ] Page `/admin` (basic auth, vue par ami, toggles)
- [ ] Migration Supabase `coins.lent_to_me`
- [ ] Filtre admin Eurio `/coins` « prêté »
