# Vue — Défis adaptatifs (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).
> **Remplace la streak** (supprimée — cf. recherche [`04`](../../psychologie-documentation/04-streak-vs-defis.md)).

## 1. Rôle

> **Le pilier de rétention.** Des défis qui s'adaptent à ta collection et gamifient l'**acquisition
> réelle** — sans la punition d'une streak. La règle d'or : **rien à perdre, bonus à gagner**.

**Drive primaire** : Complétion — secondaires : Statut, acquisition (cat. 2).

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Asymétrie positive** | le non-fait ne *retire* rien ; le fait *donne* → dopamine sans peur | [`04`](../../psychologie-documentation/04-streak-vs-defis.md) |
| **Fogg** (rituel renouvelable) | l'action quotidienne est **toujours possible** (≠ scan supply-gated) | [`04`](../../psychologie-documentation/04-streak-vs-defis.md) |
| **Goal-gradient** | « plus que 3 pièces pour finir le défi » | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Gamifier l'acquisition** | « scanne 10 pièces que tu n'as pas » → casse un billet, fouille la monnaie | `02` (supply gap) · [`06`](../../psychologie-documentation/06-completion-double-axe.md) (goal-gradient) |
| **Rareté / comparaison descendante** (Cialdini) | « scanne une commémo détenue par <5% » — détenir ce que peu ont → statut | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |

## 3. Actions × biais

| Action | Levier |
|---|---|
| Voir les **défis du mois/semaine** | goal-gradient (progress visible) |
| Avancer un défi (« 7/10 nouvelles ») | goal-gradient + acquisition |
| Compléter → **bonus** (point/grade/badge) | asymétrie positive |
| Ne pas compléter → **rien ne se passe** (pas de punition) | anti-dark-pattern |
| (Optionnel) **cadence forgiving** non-supply-gated | Fogg Ability max + fierté (relatedness SDT), à tester |

## 4. Contenu

- Liste de défis **adaptatifs** : difficulté calée sur **l'état du coffre** (un débutant et un avancé
  n'ont pas le même « 10 nouvelles ») — *sans profiling*, juste la taille de la collection.
- Exemples : « 10 nouvelles ce mois-ci » · « complète 1 pays » · « scanne une pièce <5% détenue ».
- Récompense **toujours en gain** ; barre de progression par défi (goal-gradient) ; le défi reste en tête entre sessions (Zeigarnik).

## 5. Garde-fous

- ❌ **Jamais « scanne tous les jours »** (supply-gated → punitif → dark pattern).
- ✅ **Asymétrie positive** stricte : aucune perte au non-accomplissement.
- **Cadence/streak** éventuelle = **forgiving** (freezes), **cadrée fierté**, **non-supply-gated**,
  *optionnelle et à tester* — jamais imposée (cf. [`04`](../../psychologie-documentation/04-streak-vs-defis.md)).
- Filtre **SDT** : compétence (progrès) + autonomie (on choisit de relever) + relatedness (défis partagés, post-v1).

## 6. Drives servis

Complétion ⬤ · Statut ◑ · acquisition ◑ (pont marketplace/affiliation).

## 7. À proto'er (R1)

**Entièrement neuf** (absent de la structure existante — c'était la « streak » avant). Surface
défis + cartes de défi + barres → proto avant Compose.

⚠️ **Bloquant proto (R1)** : arbitrer l'emplacement (onglet / section Profil / bandeau accueil) AVANT de démarrer le proto, et créer l'entrée correspondante dans `scene-parity.md`.
