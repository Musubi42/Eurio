# Howto — je reviens 6 mois plus tard, qu'est-ce que je fais ?

Mémo opérationnel pour Raphaël (futur lui). Si tu as oublié comment ce
projet marche, lis ça avant les autres docs.

## Le flow global, en 30 secondes

1. **Tu ajoutes / cures des pièces 2€ dans Eurio admin** comme
   d'habitude (`personal_owned` toggle, `numista_id`, images).
2. Quand tu veux solliciter un nouveau cercle d'amis, tu fais
   `go-task loan:deploy` → ça push un site statique à jour sur
   Vercel.
3. **Tu contactes un ami en privé** (WhatsApp, Signal, etc.) :
   « Salut, je fais un projet de scan de pièces, tu peux aller sur
   https://eurio-loan.vercel.app et me dire les 2€ que tu as ?
   Si tu veux bien m'en prêter quelques-unes ce serait top. »
4. L'ami se met un prénom + un emoji, scrolle le catalogue, coche les
   pièces qu'il a (le filtre par défaut « pas chez Raph » lui montre
   directement ce qui peut t'intéresser).
5. **Tu vas sur `/admin`** (basic auth), tu vois ses claims regroupés
   sous son prénom + emoji.
6. **Tu le revois IRL.** Il sort ses pièces. Vous discutez :
   - Il dit « celle-là je préfère la garder » → tu vas sur `/admin`,
     tu cliques pour la rejeter (le set `rejected` se remplit).
   - Il te file les autres → tu les notes dans **Notion** (table
     « Pièces empruntées » avec qui / quand / rendu).
7. **De retour chez toi**, tu ouvres l'admin Eurio `/coins`, tu
   coches `lent_to_me` sur chaque pièce reçue. C'est la **seule**
   donnée qui passe dans Supabase. Le reste vit dans Vercel KV +
   Notion.
8. Tu peux maintenant inclure ces pièces dans tes rounds
   d'entraînement / tests via le filtre `testable = personal_owned
   OR lent_to_me`.

## Quand tu rends une pièce

1. Tu ouvres l'admin Eurio `/coins`, tu décoches `lent_to_me` pour
   cette pièce.
2. Dans Notion, tu coches « rendue » avec la date.
3. C'est tout. Pas de touch KV nécessaire — la déclaration de l'ami
   reste dans le KV (« j'ai cette pièce »), c'est juste que tu ne
   l'as plus en main.

## Les commandes que tu vas taper

```bash
# Tu as ajouté/curé des pièces, tu veux refresh le site
go-task loan:deploy

# Tu veux tester le site en local avant de push
go-task loan:dev

# Tu veux t'assurer que ta clé Supabase n'a pas leak dans le bundle
go-task loan:env-check
```

## Où vit chaque info

| Info | Où | Pourquoi |
|---|---|---|
| Catalogue 2€ (508 pièces, méta, prix) | Supabase `coins` | Source curated, déjà en place |
| Mes pièces perso (78) | Supabase `coins.personal_owned` | Pré-existant, toggle admin |
| Pièces qu'on m'a prêtées (état actuel) | Supabase `coins.lent_to_me` | Filtre training, toggle manuel |
| Claims des amis (déclarations) | Vercel KV `user:{id}:claims` | Volatile, opérationnel |
| Mes overrides (« non finalement non ») | Vercel KV `user:{id}:rejected` | Pareil |
| Qui m'a prêté quoi, dates, rendu | **Notion** | Tracking ops, hors-repo |
| Images servies aux visiteurs | `loan/public/coins/` (gitignored) | Copiées au build, zéro egress |

## Si tu veux tout reset

- **Catalog dépassé** → `go-task loan:deploy` rebuild tout (idempotent
  sur les images déjà téléchargées).
- **Repartir de zéro côté KV** → Vercel dashboard → KV → flush. Tu
  perdras toutes les déclarations des amis. Garde-le pour les cas
  extrêmes.
- **Tu changes le mot de passe admin** → Vercel env vars
  `LOAN_ADMIN_USERNAME` + `LOAN_ADMIN_PASSWORD`, puis redeploy.

## Pourquoi pas de sync Vercel ↔ Supabase

Tentation initiale : importer les claims dans une table `coin_loans`
Supabase pour tout centraliser. Abandonné parce que :

- Les claims sont des **déclarations**, pas une vérité physique. Les
  rapatrier donne une fausse impression de canonicité.
- Le tracking physique est opérationnel : Notion fait ça mieux qu'une
  table SQL pour ce volume.
- Une seule colonne `lent_to_me` couvre 100 % du besoin réel
  (composer le candidate pool d'entraînement).
- Moins de code, moins de scripts, moins de désynchros.

Si un jour tu as 200+ amis et un workflow industriel, c'est le moment
de revoir cette décision. Pour 5-30 amis, c'est over-engineered.

## Si tu agrandis le scope (plus tard)

- **Autres dénominations (1€, 0,50€, …)** : ajouter un filtre
  denomination au build, et un sélecteur en haut du catalog.
- **Notifications quand un ami claim** : webhook Vercel KV →
  ntfy.sh / Discord. Pas urgent.
- **Stats personnelles** (« tu as 12/25 pays remplis ») : feature
  catalogueuse, sympa mais pas core.

## Template Notion — table « Pièces empruntées »

À créer dans ton Notion (workspace perso). Database type **Table**.

| Propriété | Type | Notes |
|---|---|---|
| `Pièce` | Title | Format libre, ex. `IT-2002-EU-CIRC — Italie 2002 Dante` |
| `Eurio ID` | Text | `eurio_id` exact (utile pour copier depuis admin/loan) |
| `Prêteur` | Select | Un tag par ami (Thomas 🦊, Pierre 🐢, …). Garde l'emoji du site Loan pour cohérence. |
| `Date emprunt` | Date | Quand l'ami me l'a remise |
| `Statut` | Select | `Empruntée` / `Rendue` / `Perdue` (rare mais soyons honnête) |
| `Date retour` | Date | Vide tant que `Statut = Empruntée` |
| `Notes` | Text | Lieu de remise, état physique, anecdote |
| `Photo état` | Files & media | (Optionnel) photo recto/verso au moment de l'emprunt — protège en cas de litige |

### Vues recommandées

- **À rendre** : filtre `Statut = Empruntée`, sort par `Date emprunt` ascendant.
  → Mes plus vieux emprunts en haut, je sais qui relancer.
- **Par prêteur** : group by `Prêteur`, filtre `Statut = Empruntée`.
  → Quand je vois Thomas, je vois exactement ses pièces en un coup d'œil.
- **Historique complet** : pas de filtre, sort par `Date emprunt`
  descendant. Pour la mémoire long terme.

### Routine de mise à jour

1. **Au moment où je reçois une pièce IRL** :
   - Une nouvelle ligne dans Notion (`Statut = Empruntée`, date, notes).
   - Coche dans `/admin` Vercel (ami × pièce → checkbox prêtée).
   - Coche `lent_to_me` dans Eurio admin `/coins`.
2. **Au moment où je rends** :
   - Notion : `Statut = Rendue` + `Date retour`.
   - `/admin` Vercel : décoche.
   - Eurio admin `/coins` : décoche `lent_to_me`.

Les trois actions sont manuelles et indépendantes. Pas idéal en théorie,
suffisant en pratique pour le volume visé (≤ 50 prêts simultanés).

## Liens utiles

- `loan/README.md` — vision et stack
- `loan/docs/data-model.md` — schémas KV et Supabase
- `loan/docs/build-and-deploy.md` — détails build local et deploy
- `loan/docs/ux-flows.md` — wireframes et API
- Notion : (à coller le lien quand la table sera créée)
- Vercel project : https://vercel.com/<account>/eurio-loan
