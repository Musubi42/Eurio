# Fiche pièce

> **Objectif UX** : une vue unique, riche et paramétrable, qui sert de surface d'affichage pour **toute** pièce, qu'elle vienne du scan, du coffre, ou d'une future vue Explorer. Pas de couplage fort avec la source.
>
> **Principe** : la fiche est un composant Compose paramétré par un `eurio_id` et un contexte (`ScanResult` | `OwnedCoin` | `ReferenceOnly`). Elle affiche ce qu'elle sait et cache proprement ce qu'elle ne sait pas encore (prix manquants, historique vide...).

---

## Sous-docs

- [`data-schema.md`](./data-schema.md) — quels champs sont affichés, d'où ils viennent, comment on gère les valeurs manquantes.
- [`price-history-component.md`](./price-history-component.md) — composant graphe historique/projection, **empty-compatible** dès le départ.

---

## Décisions tranchées

| Décision | Contexte |
|---|---|
| **Vue unique paramétrée** | Décidé le 2026-04-13. Pas de duplication de code. La fiche est le même composable quelles que soient la source et le contexte. |
| **Composants historique/projection créés dès la v1, même si vides** | Décidé le 2026-04-13. Quand les données eBay arriveront, les composants se chargent automatiquement sans avoir à redesigner. |
| **Photos Numista fetchées depuis Supabase Storage, pas direct Numista** | Rate limit Numista épuisé (cf. [`_shared/offline-first.md`](../_shared/offline-first.md)). Un scrape one-shot côté `ml/` + upload Supabase Storage. |
| **Face value en cents, pas en float** | Évite les problèmes de représentation. 2€ = 200. |

---

## Contextes d'affichage

Le même composable `CoinDetailScreen(eurioId, context)` s'affiche différemment selon le `context` :

| Contexte | Source | Différences |
|---|---|---|
| `ScanResult` | Résultat d'un scan juste terminé | Header avec photo snappée par l'user (grande), badge "Nouvelle pièce", CTA principal "Ajouter au coffre" |
| `OwnedCoin` | Ouvert depuis le coffre | Header avec photo user + photo référence, date d'ajout, valeur à l'ajout vs actuelle, delta, CTA "Retirer du coffre" discret |
| `ReferenceOnly` | Futur : ouvert depuis Explorer ou un deep link | Photo référence uniquement, CTA "Ajouter au coffre manuellement" |

Dans les trois cas, le corps de la fiche est identique : infos de base, rareté, valorisation, historique, projection, sets liés.

---

## Structure visuelle

```
┌─────────────────────────────────────┐
│ [Header photo(s)]                   │
│ - Photo user (si scan/owned)        │
│ - Photo référence (obverse/reverse) │
│ - Toggle recto/verso                │
├─────────────────────────────────────┤
│ [Identité]                          │
│ 2 € · France · 2012                 │
│ "10 ans de l'euro fiduciaire"       │
│ Rareté : Peu courante               │
├─────────────────────────────────────┤
│ [Valorisation marché]               │
│ 8 € ─ 15 € (fourchette P25-P75)     │
│ Médiane : 11 €                      │
│ +450% vs valeur faciale             │
│ MAJ : il y a 3 jours · eBay Browse  │
├─────────────────────────────────────┤
│ [Historique de prix — 12 mois]      │
│ ╭ sparkline ╮                       │
│ ↗ +12% sur 3 mois                   │
│ [Étendre 5 ans →]                   │
├─────────────────────────────────────┤
│ [Projection]                        │
│ Si la tendance se maintient :       │
│ dans 5 ans : 12 € à 18 €            │
│ (estimation indicative)             │
├─────────────────────────────────────┤
│ [Sets liés]                         │
│ ○ Millésime 2012 (3/8)              │
│ ○ Commémoratives France (2/15)      │
├─────────────────────────────────────┤
│ [Détails]                           │
│ Tirage : 10 000 000                 │
│ Design : …                          │
│ Pays émetteur : France              │
│ (si émission commune : liste pays)  │
└─────────────────────────────────────┘
[CTA contextuel flottant]
```

## Gestion des données manquantes

| Cas | Affichage |
|---|---|
| Pas de prix eBay | Section "Valorisation marché" remplacée par "Pas encore de données de marché" avec icône et un lien discret "Qu'est-ce que c'est ?" |
| Historique vide | Graphe affiché en skeleton + message "L'historique sera disponible bientôt" |
| Pas de photo Numista fetchée | Fallback sur image BCE. Si BCE aussi null, icône placeholder générique avec la valeur faciale. |
| Tirage inconnu | Ligne "Tirage : non communiqué" |
| Émission commune | Section spéciale "Émission commune zone euro" avec liste des pays participants |

**Règle** : jamais de "—" vide, jamais de "null", jamais de "0 €". On explicite toujours ce qui manque et pourquoi.

---

## Questions ouvertes

- [ ] Toggle recto/verso : si on n'a qu'une seule face dans nos assets, on grise l'autre ou on cache ?
- [ ] "Valeur à l'ajout vs actuelle" dans le contexte `OwnedCoin` : on stocke la valeur au moment de l'ajout dans `user_collection.value_at_add_cents`. Mais quelle valeur ? P50 du jour ? Médiane sur 30j ? À préciser quand on aura les vraies données.
- [ ] Partage social (v1 light) : bouton share sheet Android natif avec un screenshot de la fiche ? Ou un deep link qui ouvrira l'app de l'ami ?
- [ ] Comment gérer l'affichage si l'user a plusieurs exemplaires de la même pièce dans son coffre ? Une fiche agrégée avec "×3" ou 3 lignes séparées ?
