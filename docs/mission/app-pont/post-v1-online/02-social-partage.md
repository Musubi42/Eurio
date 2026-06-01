# Vue — Social / Partage / Amis (post-v1-online)

> Doc-pont psychologie → app. Périmètre **post-v1-online**. Overview : [`../README.md`](../README.md).
> Le **partage** d'objets peut exister *partiellement* dès la v1 (partage système, sans compte) ;
> les **amis / comparaison** requièrent un compte → post-v1.

## 1. Rôle

> **La boucle virale + le lien social.** Partager une pièce/une complétion/sa carte, et se comparer
> à ses amis. C'est le levier durable (relatedness) — et le moteur de croissance.

**Drive primaire** : Social (relatedness) — secondaires : Statut, Sens.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Relatedness (SDT)** | le besoin social, levier de rétention durable | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **Lien social / bonding** | scanner/recevoir un objet convoité active un circuit proche du lien social (`05`) — partager ce moment le prolonge via relatedness (SDT, `01`) | [`05`](../../psychologie-documentation/05-juice-du-scan.md) · [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **Narration > frime** | partager = **raconter une histoire**, pas exhiber | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Comparaison sociale** | « il me manque 3 pays », « regarde ma carte » | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |

## 3. Actions × biais

| Action | Quoi afficher | Levier |
|---|---|---|
| **Partager une nouvelle pièce** | 3D + 1 ligne d'histoire + « 2% la détiennent » | N-effect + comparaison descendante (Cialdini, `03`) · narration (`07`) · statut (`01`) |
| **Partager une complétion** | « j'ai fini l'Allemagne 🇩🇪 » | signal de statut / achievement (Belk `01`) · goal-gradient (`06`) |
| **Partager la carte eurozone** | l'asset n°1 (« il me manque 3 pays ») | endowment effect de la carte + signal social (`01`·`07`) |
| **Comparer aux amis** | rang local, qui a quoi | local dominance + comparaison similaire (Festinger, `03`) |
| **Recevoir une share card d'un ami** | aperçu collection d'un ami → envie de comparer | FOMO éthique · comparaison locale descendante (`03`) |
| **Consulter le coffre d'un ami / ajouter un ami** | qui a quoi, delta avec soi | local dominance (`03`) · relatedness SDT (`01`) |

## 4. Contenu

- **Cartes de partage** générées (image attractive) : pièce / complétion / carte → une image/carte partageable
  envoyable à un pote (lien direct avec la **machine à contenu**, mission Croissance).
- **Amis** : ajout, comparaison locale (post-v1, compte requis).

## 5. Garde-fous

- **Fierté/histoire, pas flex creux** : on partage *ce que ça raconte*, pas un montant.
- **Pas de pression sociale coercitive** (« tes amis te battent ! » culpabilisant = banni).
- Filtre **SDT** : relatedness *positive*, jamais l'anxiété de comparaison.

## 6. Drives servis

Social ⬤ · Statut ◑ · Sens ◑.

## 7. À proto'er (R1) + prérequis

**Rendus visuels à proto'er avant implémentation Android (R1) :**
- ❌ **Share card pièce** (layout image générée : 3D + 1 ligne histoire + stat rareté)
- ❌ **Share card complétion pays** (image générée : « j'ai fini l'Allemagne 🇩🇪 »)
- ❌ **Vue partageable carte eurozone** (asset différenciateur, « il me manque 3 pays »)

**Partage système** (sans compte) : bon candidat d'avance dès v1.
**Amis/comparaison** : **post-v1** (compte/serveur). Alimente la croissance (contenu short-form).
