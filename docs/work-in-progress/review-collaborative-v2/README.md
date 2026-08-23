# Review collaborative v2 — index

> **Statut : lot 0 livré (2026-08-23), implémentation en cours.**
> Supersède [`../collaborative-review/`](../collaborative-review/) (juin 2026) et
> tranche le chunk **K2** de [`../auth-redesign/ROADMAP.md`](../auth-redesign/ROADMAP.md).

> 🟢 **En production depuis le 2026-08-23, et utilisé.** Reprise, défaut connu et
> scénario de recette : **[`REPRISE.md`](REPRISE.md)** — à lire en premier.

## En une phrase

Faire reviewer des amis non-techniques depuis leur propre ordinateur, sur
`eurio-admin.musubi.dev`, avec un compte Authentik en rôle `reviewer` — en réutilisant
le back qui existe déjà, et en supprimant les deux piles qui font doublon.

## Ce qui a surpris

Le back était **déjà écrit, en triple**. Le vrai blocage n'était pas le calcul lourd
mais trois détails : des URLs d'images relatives préfixées vers `127.0.0.1:8042`, un
`decided_by = 'admin'` en dur, et `cv2` exclu de l'image VPS par association avec
torch alors qu'il n'y sert que de bibliothèque d'images.

## Les fichiers

| Fichier | Contenu |
|---|---|
| [`CONSTAT.md`](CONSTAT.md) | le problème, les trois piles, les mesures et leurs requêtes |
| [`DECISIONS.md`](DECISIONS.md) | D1-D10 — ce qu'on fait, pourquoi, et ce que ça écarte |
| [`ROADMAP.md`](ROADMAP.md) | les 10 lots, leur statut, leur vérification |
| [`NETTOYAGE.md`](NETTOYAGE.md) | l'inventaire de ce qui meurt au lot 9, tenu à jour |
| [`REPRISE.md`](REPRISE.md) | **où on en est, le défaut trouvé à l'usage, ce qui reste, le scénario de recette** |
| [`DEPLOIEMENT.md`](DEPLOIEMENT.md) | la procédure, ce qu'elle change en prod, et comment se donner un compte « ami » |

## Hors périmètre

- ❌ Une PWA ou une base locale côté ami (un lot = ~3,9 Mo, cf. CONSTAT)
- ❌ Le crop en Canvas côté client (D5)
- ❌ DINO dans le navigateur (D6)
- ❌ Un second système de permissions (D3)
