# Transverse — Notifications (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline** (notifs locales, sans compte). Overview : [`../README.md`](../README.md).
> Transverse (pas un écran) — la surface de **ré-engagement**.

## 1. Rôle

> Ramener l'utilisateur **comme un cadeau**, jamais comme un rappel anxiogène. La notif doit
> provoquer *« ça fait longtemps, tiens, agréable surprise »*, pas la culpabilité.

**Drive primaire** : dépend du type (voir table) — transverse à Découverte/Statut/Complétion.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Notif = cadeau** (fréquence adaptative) | espacée selon la fréquence d'ouverture → effet surprise | décision équipe (non sourcé) |
| **N-effect** (petit nombre de détenteurs) | « seulement 12 personnes ont cette pièce » → motivation compétitive par pool réduit | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) §Garcia&Tor |
| **Rareté / comparaison descendante** | « sois le 1ᵉʳ à scanner ce mois » → envie sans culpabilité (Cialdini) | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) §Cialdini |
| **Nouvelle sortie (moat)** | on connaît les commémo **avant** les autres → raison légitime de rouvrir | mission Croissance |

> Chaque levier ci-dessus est soumis au filtre anti-dark-pattern décrit en §5.

## 3. Notifs par levier

| Notif | Levier | Exemple |
|---|---|---|
| **Rareté / FOMO doux** | Statut + N-effect | « tu es parmi les rares à avoir cette commémo » _(❌ v1-offline : "premier à scanner" requiert données sociales temps réel, impossibles sans compte — disponible v2-social)_ |
| **Nouvelle sortie** | Découverte + Complétion | « La commémo {pays} sort cette semaine — déjà au catalogue » |
| **Défi** | Complétion | « Plus que 3 pièces pour finir ton défi » |
| **Valeur** (parcimonie) | Valeur | « une pièce de ton coffre a pris de la valeur » _(nécessite un historique de snapshots ou une mise à jour catalogue — contrainte architecture v1 à résoudre avant implémentation)_ |

## 4. Règles de fréquence

- **Pas de quotidien.** Cadence **adaptative à la fréquence d'ouverture** (moins l'user ouvre, plus
  on espace — anti-harcèlement).
- **Configurable** (Réglages, cf. [`06-profil`](./06-profil.md)).
- **Qualité > régularité** : mieux vaut une notif rare et délicieuse que dix tièdes.

## 5. Garde-fous

- ❌ Jamais culpabilisant (« tu vas perdre ta streak » = banni — d'ailleurs **pas de streak**).
- ✅ Toujours une **action possible** derrière (sinon frustration, supply-gated).
- Filtre **SDT** : sert l'autonomie (réglable) et la compétence (montre une progression réelle), jamais la coercition ou la comparaison sociale punitive.

## 6. Drives servis

Transverse : Découverte / Statut / Complétion / Valeur selon le type.

## 7. À proto'er (R1)

Pas un écran — mais les **réglages de fréquence** (dans Profil) et les **gabarits de contenu** des
notifs sont à spécifier. Le **moteur de fréquence adaptative** est une logique neuve.

La **demande de permission de notification** (Android 13+ `POST_NOTIFICATIONS`) est un moment UX
à part entière — à proto'er comme micro-scène, ou à documenter comme delta systémique dans
`parity-rules.md` §R6 si on choisit de ne pas la proto'er.
