# Vue — Reveal post-scan (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).
> Fait suite à [`01-scan.md`](./01-scan.md) (le settle de la pièce enchaîne ici).

## 1. Rôle

> Révéler **le sens, le statut, la place et la valeur** de la pièce — beaucoup d'infos, **sans
> surcharge**, avec le 3D en héros. C'est le **payload** du pull éthique.

**Drive primaire** : Découverte (défaut) — secondaires : Statut, Complétion, Valeur, Sens.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Stratification** (Miller 7±2 / Hick / progressive disclosure) | ≤3 infos ici, la profondeur à la demande | [`05`](../../psychologie-documentation/05-juice-du-scan.md) |
| **Servir ≥3 drives + autonomie** | défaut multi-drive, **lentille choisie** pas devinée | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **N-effect + comparaison descendante** | « 3ᵉ à scanner / 2% détiennent » sur les pièces rares | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |
| **Transportation narrative** (amorce) | une ligne d'histoire ouvre la porte au sens | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Effet IKEA** (Norton/Ariely) | le scan = labeur signifiant → ne pas trivialiser le geste reveal | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Économie des célébrations** | le grand show réservé aux jalons | [`05`](../../psychologie-documentation/05-juice-du-scan.md) |

## 3. Contenu (stratification)

| Couche | Contenu | Principe |
|---|---|---|
| **Héros** | 3D de la pièce (haut-centre), rotatable/zoomable | game feel, focal |
| **Primaire (≤3)** | Découverte (titre + 1 ligne d'histoire) · Complétion (« nouvelle ! 24/27 ») · 1 **accent contextuel** | Miller/Hick : plafond 3 |
| **Profondeur** | tap → [`03-page-piece`](./03-page-piece.md) | progressive disclosure |

**Accent contextuel** (le 3ᵉ slot, piloté par *la pièce*, pas par un profil) :
- pièce rare → « tu es le **3ᵉ** à la scanner ce mois-ci » / « 2% la détiennent » (**N-effect**) ;
- pièce qui boucle une série → « complète : Allemagne 2023 **X/Y** » (complétion) ;
- valeur notable → « ~12€ en TTB » (valeur, en *info* pas en *titre*) ;
- sinon → la découverte respire (histoire un peu plus longue).

## 4. Lentilles (le flow zéro-friction)

| Action | Comportement | Levier |
|---|---|---|
| **Défaut** | Découverte d'abord (universel), ou le choix d'onboarding | servir ≥3 drives |
| **Swipe latéral** sur la carte | feuillette Histoire / Rareté / Valeur / Complétion (points indicateurs) | autonomie · progressive disclosure |
| **Épingle** (optionnelle) | punaise « ouvre toujours là » (préférence déclarée, visible) — **ou** mémoire du *dernier-état* (fallback implicite) · [à trancher avant implémentation] | autonomie sans profiling (R0-safe) |
| **Tap / swipe-up** | → page pièce (profondeur) | progressive disclosure |

## 5. Embranchements

- **Doublon** : settle rapide + toast « tu l'as déjà », **pas de grand reveal**, le scan continue. *(Économie des célébrations + vitesse.)*
- **Non identifié** : top-N + saisie manuelle de la valeur faciale — **récupération douce**, jamais un échec sec. *(Autonomie SDT : l'user reprend le contrôle.)*
- **Jalon** (nouvelle pièce qui complète set/pays, légendaire, 1ᵉʳ à scanner) → déclenche la **catégorie de célébration** (cf. [`04-coffre`](./04-coffre.md) / [`05-defis`](./05-defis.md)). Règle de priorité : quand la pièce déclenche un jalon, la célébration remplace l'accent contextuel — le slot Primaire affiche l'état final (ex. « 27/27 »), puis la célébration prend le relais. L'accent N-effect ordinaire (3ᵉ, 5ᵉ…) ne s'affiche pas indépendamment si un jalon catégorie 2-4 est actif.

### Économie des célébrations — 4 catégories à plat
1. **Nouvelle pièce** (le reveal standard, le plus léger) · 2. **Set complété** · 3. **Pays complété** (carte à gratter, cf. [`04c`](./04c-coffre-carte-eurozone.md)) · 4. **Exploit rareté/statut**. Chacune : thématique/anim/banderole/data propres ; la rareté garde le pic spécial.

## 6. Garde-fous

- ❌ Zéro hasard/near-miss (le payload est déterministe).
- 🎉 Célébration **non inflationniste** (tout célébrer = aplatir le pic).
- 🧠 **Filtre SDT** : compétence (où ça me place) + autonomie (lentille) + relatedness (amorce statut/partage) — pas le `+€` seul (carotte sèche).
- 💶 Valeur en *info*, jamais en *titre* par défaut (trahirait historien/complétionniste).

## 7. Drives servis

| Drive | Niveau | Par quoi |
|---|---|---|
| Découverte | ⬤ | histoire (défaut), 3D |
| Statut/rareté | ◑ si rare | accent N-effect |
| Complétion | ◑ | « nouvelle ! X/Y » |
| Sens | ◑ | amorce → page pièce |
| Valeur | ◔ | cote en info |

## 8. À proto'er (R1)

❌ **Bloque le code Compose** tant que ces scènes ne sont pas prototypées :
1. **Reveal stratifié** — héros 3D + carte-lentille swipeable + accent contextuel (plus riche que `scan-matched.html`, bottom-sheet 2 CTA).
2. **Chacune des 4 catégories de célébration** — thématique/anim/banderole propres.

Le merge avec `app-implem-phases` (décision #7 post-scan adaptive) est distinct et ultérieur à la validation proto.
