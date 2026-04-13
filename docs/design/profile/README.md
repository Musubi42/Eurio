# Profil — achievements, stats, settings

> **Objectif UX** : le profil est le centre de progression et de motivation. L'user y voit son niveau, ses achievements en cours, ses stats d'usage, et accède aux settings.
>
> **Principe** : la gamification est **organique**. Les achievements suivent la progression naturelle du collectionneur, jamais des dark patterns (PRD §5.4).

---

## Sous-docs

- [`achievements-engine.md`](./achievements-engine.md) — comment les sets sont définis, comment les achievements sont calculés.
- [`level-progression.md`](./level-progression.md) — niveaux (Découvreur → Maître), critères de passage.

---

## Décisions tranchées

| Décision | Contexte |
|---|---|
| **Gamification organique** | PRD §5.4. Pas d'alerte quotidienne forcée, pas de streak qui culpabilise. |
| **Niveaux : 4 paliers** | Découvreur → Passionné → Expert → Maître (PRD §5.4) |
| **Calcul 100% local** | Depuis Room `user_collection`. Pas de dépendance backend. |
| **Notifications de chasse opt-in** | L'user peut activer les rappels "il te manque 2 pièces pour compléter la série allemande". Pas par défaut. |

---

## Structure de la vue

### Onglet Profil

```
┌─────────────────────────────────────┐
│ [Header]                            │
│ Niveau : Passionné                  │
│ 23 pièces · 8 pays · 2 séries       │
│ ▓▓▓▓▓░░░░░ 47% vers Expert          │
├─────────────────────────────────────┤
│ [Achievements en cours]             │
│ ○ Série complète France (6/8)       │
│ ○ Eurozone founding (5/12)          │
│ ○ Grande chasse (8/21)              │
│ [Voir tous →]                       │
├─────────────────────────────────────┤
│ [Achievements débloqués]            │
│ ★ Premier scan                      │
│ ★ Première série                    │
│ [Voir tous →]                       │
├─────────────────────────────────────┤
│ [Stats]                             │
│ 34 pièces scannées au total         │
│ Valeur du coffre : 247 € (+34%)     │
│ Membre depuis : 12 jours            │
├─────────────────────────────────────┤
│ [Settings]                          │
│ › Langue                            │
│ › Notifications                     │
│ › Mise à jour du catalogue          │
│ › À propos                          │
└─────────────────────────────────────┘
```

### Sous-vue : Liste des sets

Tap sur "Voir tous →" sur une section Achievements :

```
[Achievements]
[Tab: En cours] [Tab: Débloqués] [Tab: Verrouillés]

En cours :
┌──────────────────────────────────┐
│ ○ Série complète France          │
│ ▓▓▓▓▓▓░░ 6/8                     │
│ Il te manque : 2c France 2020,   │
│ 50c France 2019                  │
└──────────────────────────────────┘
┌──────────────────────────────────┐
│ ○ Eurozone founding              │
│ ▓▓▓▓░░░░░░░░ 5/12                │
│ Il te manque : 7 pièces fondateur│
└──────────────────────────────────┘
```

Tap sur un set → détail avec la liste de toutes les pièces nécessaires et lesquelles sont possédées.

### Sous-vue : Détail d'un set

```
Série complète France
▓▓▓▓▓▓░░ 6/8 pièces

[Grille des pièces du set]
✓ 1c France 2020   ✓ 2c France 2020
× 5c France 2020   ✓ 10c France 2020
✓ 20c France 2020  ✓ 50c France 2020
✓ 1€ France 2020   × 2€ France 2020

[Bouton] Scanner une pièce manquante
```

---

## Catalogue de sets v1

Reprend PRD §5.4, à affiner côté design engine :

| Set | Description | Difficulté |
|---|---|---|
| **Série complète [Pays]** | Toutes les pièces de circulation d'un pays (1c à 2€, 8 pièces) | Facile (pour les pays courants) |
| **Eurozone founding** | Une pièce de chaque pays fondateur (2002, 12 pays) | Moyen |
| **Millésime [Année]** | Une pièce de chaque valeur frappée une année donnée | Moyen |
| **Commémoratives [Pays]** | Toutes les 2€ commémoratives d'un pays | Difficile (varie selon pays) |
| **Grande chasse** | Au moins une pièce de chaque pays zone euro (21 pays en 2026) | Difficile |
| **Vintage 2002** | Toutes les pièces frappées en 2002 (1ère année) | Très difficile |
| **Le Coffre d'or** | 10 pièces d'une valeur de marché > 10x leur face | Très difficile |

**Note Bulgarie** : la Bulgarie a rejoint la zone euro le 2026-01-01 (mémoire `reference_eurozone_21.md`). Le set "Grande chasse" passe donc de 20 à 21 pays.

---

## Level progression

| Niveau | Critère (provisoire) |
|---|---|
| **Découvreur** | 0–5 pièces |
| **Passionné** | 6–25 pièces OU 1 série complète |
| **Expert** | 26–100 pièces OU 3 séries complètes OU valeur coffre > 500€ |
| **Maître** | 100+ pièces OU 5+ séries complètes OU valeur > 2000€ |

Critères à raffiner. Voir [`level-progression.md`](./level-progression.md).

---

## Settings disponibles

| Section | Options |
|---|---|
| **Langue** | Suit Android par défaut, override possible |
| **Notifications** | Rappels de chasse (on/off) · Complétion de set (on/off) · Nouvelles pièces dispo (on/off) |
| **Catalogue** | "Mettre à jour le catalogue" (Wi-Fi only / Wi-Fi + cellulaire / manuel) |
| **Prix** | Fréquence de sync des prix eBay |
| **Données** | Exporter le coffre (PDF/CSV) · Effacer toutes les données |
| **Vie privée** | Télémétrie anonyme (on/off, off par défaut) |
| **Compte** (v2) | Connexion Google · Sync cloud |
| **À propos** | Version, licences, contact |

---

## Questions ouvertes

- [ ] Stats d'usage : combien on garde et on montre ? (scans total, taux de succès, temps moyen par scan...) → éviter le voyeurisme stat.
- [ ] "Membre depuis" : à partir du premier lancement de l'app ou du premier scan ?
- [ ] Les achievements débloqués déclenchent-ils une animation plein écran à la première fois, ou juste une notification discrète ?
- [ ] Est-ce qu'on affiche les achievements "verrouillés" (pas encore commencés) ou on les cache jusqu'à ce que la première pièce les déclenche ?
- [ ] Thème sombre / clair : auto par défaut, override possible ?
