# Coffre — le centre du produit

> **Objectif UX** : le coffre est l'espace de patrimoine de l'user. Il doit donner une impression de valeur accumulée, de progression, de chasse en cours. C'est la surface principale après le scan.
>
> **Principe** : local-first. Tout vit dans Room. Le cloud est opt-in et jamais bloquant.

---

## Sous-docs

- [`data-model.md`](./data-model.md) — comment `user_collection` est structuré, flows d'ajout/retrait, sync opt-in.
- [`filters-search.md`](./filters-search.md) — filtres, recherche, tri, vue grille/liste.

---

## Décisions tranchées

| Décision | Contexte |
|---|---|
| **Stockage Room local-first** | Décidé le 2026-04-13. SQLite typé, migrations propres, OK pour la recherche filtrée. |
| **Plusieurs exemplaires d'une même pièce autorisés** | Un user peut avoir 3× la même pièce. Pas de unique constraint sur `(user_id, eurio_id)`. |
| **Photo user optionnelle** | Si l'user ajoute une pièce manuellement sans scanner, pas de photo obligatoire. |
| **Export PDF dès la v1** | PRD §5.3. Export simple : liste + valeurs totales. |
| **Vue grille OU liste** | Toggle user. Default = grille (plus visuel). |

---

## Structure de la vue

### Vue principale (onglet Coffre)

```
┌─────────────────────────────────────┐
│ Ton coffre                          │
│                                     │
│ [Valeur totale]                     │
│ 247 €                               │
│ +34% depuis que tu as commencé      │
│                                     │
│ [Stats]                             │
│ 23 pièces · 8 pays · 2 séries       │
├─────────────────────────────────────┤
│ [Search bar]                        │
│ [Filtres : Pays ▾] [Année ▾] [Rareté ▾] │
│ [Tri ▾]           [Grille/Liste ⊞]  │
├─────────────────────────────────────┤
│ [Grille de pièces]                  │
│ ┌──┐ ┌──┐ ┌──┐ ┌──┐                │
│ │  │ │  │ │  │ │  │                │
│ └──┘ └──┘ └──┘ └──┘                │
│ ┌──┐ ┌──┐ ┌──┐ ┌──┐                │
│ │  │ │  │ │  │ │  │                │
│ └──┘ └──┘ └──┘ └──┘                │
├─────────────────────────────────────┤
│ [Bouton flottant : Scanner]         │
└─────────────────────────────────────┘
```

### Vue détail d'une pièce possédée

Tap sur une pièce → ouvre la fiche pièce avec `context = OwnedCoin`. Voir [`../coin-detail/README.md`](../coin-detail/README.md).

### Vue grille

- 2, 3 ou 4 colonnes selon la largeur écran.
- Chaque cellule : photo obverse + mini-label valeur faciale + mini-flag pays.
- Badge discret "×3" si plusieurs exemplaires.
- Halo spécial pour les pièces appartenant à un set complet.

### Vue liste

- Ligne : photo miniature + nom + pays + année + valeur actuelle + delta.
- Plus dense, meilleure pour scanner rapidement une grande collection.

---

## Actions disponibles

| Action | Où | Comportement |
|---|---|---|
| **Ajouter une pièce** | Depuis le scan ou le bouton flottant | Ouvre le scan directement |
| **Retirer une pièce** | Long press sur une pièce dans la grille, OU bouton discret dans la fiche détail | Confirmation modale puis delete Room |
| **Modifier une pièce** | Tap dans la fiche détail | Permet de changer la condition, note perso |
| **Marquer comme vendue** (v2) | Fiche détail | Modifie le statut, pas de delete |
| **Exporter en PDF** | Menu overflow en haut | Génère un PDF local, ouvre share sheet Android |
| **Partager le coffre** (v2) | Menu overflow | Screenshot ou deep link |

---

## Calcul de la valeur totale

La valeur totale affichée est la somme des `p50_cents` de chaque pièce de la collection.

Règles :
- Pour les pièces sans données de marché : on utilise la valeur faciale (pas de surévaluation fantaisiste).
- Pour les pièces avec données obsolètes (> 30 jours) : même chose, on prend `p50_cents` quand même mais on marque la valeur totale d'un indicateur "MAJ nécessaire".
- Le delta "+34% depuis que tu as commencé" compare la somme actuelle à la somme des `value_at_add_cents` de chaque pièce (le P50 au moment de l'ajout). Si toutes les `value_at_add_cents` sont nulles (cas user qui a commencé avant qu'on ait des prix), on cache le delta.

## États spéciaux

| État | Affichage |
|---|---|
| Coffre vide | Illustration + "Scanne ta première pièce" + CTA gros bouton Scan |
| Coffre avec 1-2 pièces | Même layout que normal mais on met en avant "il te manque X pièces pour compléter la série [nom]" |
| Aucune valeur totale connue | "Valeur totale : à calculer" + lien "Pourquoi ?" → explique que les prix arrivent via sync |

---

## Questions ouvertes

- [ ] Faut-il un mode "vue par set" en plus de grille/liste ? (Pièces groupées par set plutôt qu'à plat.)
- [ ] Archivage : si l'user vend une pièce (v2 marketplace), elle disparaît du coffre ou elle passe en "historique" ?
- [ ] Notes perso : simple texte ou rich (photo annotée, date d'acquisition libre, lieu, prix payé) ?
- [ ] Comportement du scroll long : pagination invisible ou tout charger d'un coup ? Question perf si user a 1000+ pièces.
- [ ] Export PDF : on génère côté app (plus de contrôle) ou on utilise un template Android natif ?
