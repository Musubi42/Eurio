# Vue Coffre

> ✅ **Livré (proto) — session 2 du 2026-06-15.** Voir `../session-log.md` pour le détail.
> Bascule retenue : restructuration sur le flow CoinSnap (header sobre + 3 onglets Résumé/Pièces/Sets),
> le dégraissage se fait par répartition sur les onglets, pas par repli. Les 5 points « À trancher »
> ci-dessous sont résolus ainsi : (1) au-dessus de la ligne = header sobre + spotlight ;
> (2) sparkline retirée du Résumé ; (3) recherche/filtres/tris déplacés dans l'onglet Pièces ;
> (4) best coins gardés mais en **carte spotlight** ; (5) bande articles non intégrée (hors scope).
> Le cadrage initial ci-dessous est conservé pour mémoire.

---

## Ce qu'on a (état actuel) — `VaultHome.vue`

Empilé du haut vers le bas (le PO trouve ça **trop lourd**) :
1. Header « Ton coffre » + actions (export, …)
2. Onglets Coins / Sets / Catalog
3. **Valeur totale** (gros chiffre) + delta + **courbe sparkline 12 mois**
4. Stats : **Pièces · Pays · Séries**
5. **Carrousel « Tes meilleures pièces »** (ajouté au batch précédent — badges rareté/valeur)
6. Barre de **recherche**
7. **Filtres** + toggle grille/liste + **tris** (Pays / Faciale / Prix / Date)
8. Groupes de pièces (enfin les pièces)

## Ce qui cloche (PO)

> « Si je prends ma page coffre, il y a trop de trucs… c'est trop lourd. »

Trop d'éléments de façade **avant** d'arriver aux pièces (la raison d'être de l'écran).

## Cible (ce qu'on veut)

- **Dégraisser la façade** : les pièces visibles vite. Stats/courbe/filtres → secondaires (repli, accès à la demande).
- **Bande d'articles légère** (éditorial, T5) intégrée discrètement.
- Garder ce qui a de la valeur émotionnelle (best coins ?) mais **pas tout en même temps**.

## À trancher

1. Que garde-t-on **au-dessus de la ligne de flottaison** ? (hypothèse : header sobre + pièces ; le reste en repli/onglet)
2. La **courbe sparkline** : on la garde (patrimoine qui grossit = motivant) ou on la déplace en détail ?
3. **Recherche/filtres/tris** : tout visible vs masqués derrière une icône ?
4. **Best coins** : on les garde en hero, ou ça fait partie du « trop » ?
5. **Bande articles** : position (haut/bas ?), format (carrousel horizontal léger ?).

## Findings CoinSnap

- Header patrimoine **sobre** (€ · pièces · issuers), pas 36 stats.
- Feed d'articles léger (« Coin Talk ») discret.
