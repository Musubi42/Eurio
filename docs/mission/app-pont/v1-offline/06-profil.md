# Vue — Profil (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).
> **Sans streak** (supprimée, cf. [`04`](../../psychologie-documentation/04-streak-vs-defis.md)).

## 1. Rôle

> **L'identité long-terme du collectionneur.** Là où le Coffre montre la progression *mécanique*, le
> Profil montre **qui tu es devenu** : grade, badges, stats, réglages.

**Drive primaire** : Statut/Sens (identité) — secondaire : Complétion (méta).

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Self-extension / identité** | la collection **complète symboliquement le soi** | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **Compétence (SDT)** | grade/badges = **feedback de progrès**, pas carotte sèche | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **Goal-gradient** (badges) | « prochain badge : plus que 2 » (par analogie avec les sets, cf. `06`) | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Statut** | grade affichable (et partageable, post-v1) | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |

## 3. Contenu / actions

- **Grade / niveau** : paliers de **compétence non-comparatifs** (SDT + goal-gradient — concept tranché,
  cf. `03`) — critère de calcul *question produit ouverte* : basé sur volume, rareté détenue, ou
  complétion de sets ? mix ?
- **Badges** : débloqués (LazyRow) + **3 prochains avec barre** (goal-gradient).
- **Stats** : total scans, pays touchés, sets complétés, valeur du coffre.
- **Réglages** : langue, **lentille de reveal** (le choix d'onboarding, modifiable), **notifications**
  (fréquence), catalogue, à propos.
- **Modale de déblocage** grade/badge = **transition identitaire** (peak-end, célébration mesurée).

## 4. Flow × biais

| Action | Levier |
|---|---|
| Tap un badge (débloqué ou prochain) | Goal-gradient + Compétence (SDT) |
| Modale de déblocage grade/badge | Peak-end rule — transition identitaire |
| Scroll des stats | Endowment effect (ce que j'ai accumulé est à moi) |

## 5. Garde-fous

- ❌ **Pas de streak** (ni visible, ni punitive).
- **Badges = compétence, pas manipulation** : célèbrent un *vrai* accomplissement, pas un grind
  artificiel (sinon érosion de la motivation intrinsèque, SDT).
- **Grade honnête** : reflète une vraie progression, pas un compteur d'engagement creux.
- **Max 3 badges « prochains » affichés** : limiter les boucles Zeigarnik simultanées (cf. `06`
  §garde-fous). Au-delà, le Profil devient un écran d'anxiété de complétion, pas d'identité.

## 6. Drives servis

**Statut/identité ⬤ · Sens ◑ · Complétion ◔** — le récit complet vit dans la Page pièce (Sens
secondaire ici) ; la complétion détaillée vit dans le Coffre (Complétion tertiaire ici).

## 7. À proto'er (R1)

`profile.html` / `profile-achievements.html` / `profile-settings.html` / `profile-unlock.html`
existent → socle.

**Deltas à appliquer sur le proto existant :**
- Retirer la streak du hero (`profile.html` — décision #6/#8 obsolète).
- Ajouter le réglage lentille dans `profile-settings.html`.

**Vérification à faire avant merge :**
- Confirmer que `profile-unlock.html` couvre la « transition identitaire / célébration mesurée »
  (§3 Modale de déblocage) ; si non, inscrire cet état comme delta à ajouter.

La définition du **grade** (critère de calcul) reste une question produit ouverte — à trancher
avant implémentation Android.
