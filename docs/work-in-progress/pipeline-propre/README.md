# Chantier « pipeline propre »

> 671 classes, 8 exemplaires propres chacune dans la banque DINO, avec le moins
> de quota eBay et de temps humain possible.

## 👉 Où en est-on, et par où reprendre

**[`REPRENDRE-ICI.md`](REPRENDRE-ICI.md)** — l'état mesuré, ce qui est déployé
et ce qui ne l'est pas, les défauts connus, et les trois gestes qui font
avancer l'objectif. **À lire en premier.**

## Les documents, et à quoi ils servent

| | |
|---|---|
| [`REPRENDRE-ICI.md`](REPRENDRE-ICI.md) | l'ÉTAT et la SUITE — le point d'entrée |
| [`DECISIONS.md`](DECISIONS.md) | D1-D10, arbitrées avec le PO. Non négociables ; chacune dit ce qu'elle écarte |
| [`JOURNAL.md`](JOURNAL.md) | un geste par entrée, avec sa commande, son témoin et sa mesure. Le plus récent en haut |
| [`VISION.md`](VISION.md) | pourquoi ce chantier existe, et les quatre vérités mesurées qui contraignent tout le design |
| [`FLOW-ADMIN.md`](FLOW-ADMIN.md) | les huit plaques, les quatre stations |
| [`outils/`](outils/) | une spec par outil (O1-O7). Chacune porte son statut |
| [`design/`](design/) | la conception de `/besoin` : parcours, états, **vocabulaire (§5)**, maquettes jetables |

⚠️ **Les specs et le design disent l'INTENTION, pas l'état.** Pour savoir ce que
le code fait aujourd'hui, c'est `REPRENDRE-ICI.md`.

## Ce qu'il faut savoir avant de toucher au code

- **Ici les pannes sont muettes.** Une requête fausse rend un nombre plausible ;
  un filtre vide une file en silence ; un JOIN à zéro ligne se lit « il n'y a
  rien à faire ». Skill `eurio-verify`.
- **`class_id` désigne trois conventions différentes** (défaut V4, cf.
  `VISION.md`). Il s'est présenté **quatre fois** pendant l'implémentation.
  Devant une requête qui compare un `class_id`, demander *lequel*.
- **Un test vert ne prouve rien tant qu'il n'a pas échoué.** Toute
  fonctionnalité de ce chantier a sa mutation jouée.
- **Quand tu ajoutes un filtre, la question n'est pas « est-ce qu'il marche »
  mais « qu'est-ce que l'écran dit quand il mord ».**
