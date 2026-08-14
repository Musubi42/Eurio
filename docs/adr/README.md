# ADR — index

> **Charge ce fichier, pas le dossier.** Une ligne par décision : tu identifies la
> bonne ADR ici, puis tu lis **celle-là seule**. Ça évite de parcourir tout `docs/adr/`.
>
> Une ADR enregistre **pourquoi** on a tranché, pas comment le code marche aujourd'hui.
> Pour l'état courant du système : [`../architecture/README.md`](../architecture/README.md).

**Statuts** : ✅ Acceptée · 🟡 Proposée (pas encore validée PO) · ⚪️ Superseded · ❌ Rejetée

| # | Titre | Statut | Date | En une ligne |
|---|---|---|---|---|
| [001](./001-litert-over-tflite.md) | LiteRT 1.4.2 au lieu de TensorFlow Lite 2.16.1 | ✅ | 2026-04-09 | Android 15 exige un alignement 16 Ko ; LiteRT est un drop-in avec les mêmes imports |
| [002](./002-nix-devshell.md) | Nix devShell pour le toolchain | ✅ | 2026-04-09 | Toutes les deps par `flake.nix` + direnv, jamais de brew ni d'install manuelle |
| [003](./003-yolo-tflite-export.md) | Export YOLOv8-nano vers TFLite | ✅ | 2026-04-10 | L'export natif d'Ultralytics casse sous Nix (conflits TF/tf_keras/protobuf) |
| [004](./004-artefacts-binaires-hors-git.md) | Artefacts binaires hors de git, fetchés au build | 🟡 | 2026-08-14 | git sert aujourd'hui de transport Mac→PC ; cible = MinIO + manifeste sha256 |
| [005](./005-remaster-historique-git.md) | Remaster de l'historique git sur une base propre | 🟡 | 2026-08-14 | Nouveau `main` en commits thématiques ; ancien historique archivé en tarball hors ligne |
| [006](./006-extraction-loan.md) | `loan/` extrait dans son propre dépôt | 🟡 | 2026-08-14 | Produit distinct, couplage réduit à une ligne de CSS ; données via MinIO |
| [007](./007-pas-de-split-eurio-avant-artefacts.md) | Ne pas découper Eurio avant d'avoir des artefacts publiés | 🟡 | 2026-08-14 | Un split par dossier casse R1/R2 ; il faut d'abord publier tokens et catalogue |

## Où vit quelle information

| Type | Emplacement |
|---|---|
| **Pourquoi** une décision a été prise | `docs/adr/` (ce dossier) |
| **Ce que fait le système** aujourd'hui | `docs/architecture/` |
| **Ce qu'on est en train de faire** | `docs/work-in-progress/<chantier>/` |
| Décisions design par vue | `docs/design/{vue}/README.md` |
| Règles non-négociables | `CLAUDE.md` |

> ⚠️ `docs/DECISIONS.md` (2026-04-15) est un ancien index, **partiellement périmé** —
> il porte par exemple une décision « tests en `unittest`, pas pytest » contredite par
> les 123 fichiers pytest du repo. À réconcilier ou archiver.

## Écrire une ADR

Fichier `00X-titre-court.md`, format des ADR existantes :
**Contexte** (le problème et ses contraintes) → **Décision** → **Alternatives considérées**
(tableau option/verdict) → **Conséquences** (y compris les mauvaises).

Une ADR ne se réécrit pas : si la décision change, on en crée une nouvelle et on marque
l'ancienne ⚪️ *superseded par ADR-00Y* — **on garde la trace du raisonnement d'origine**,
c'est tout l'intérêt. Puis on ajoute la ligne ici.
