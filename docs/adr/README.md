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
| [004](./004-artefacts-binaires-hors-git.md) | Artefacts binaires hors de git, fetchés au build | ✅ | 2026-08-14 | Appliquée le 2026-08-16 : bucket `model-artifacts` + manifestes `shared/*-assets.json`, `preBuild` Gradle |
| [005](./005-remaster-historique-git.md) | Remaster de l'historique git sur une base propre | 🟡 | 2026-08-14 | Nouveau `main` en commits thématiques ; ancien historique archivé en tarball hors ligne |
| [006](./006-extraction-loan.md) | `loan/` extrait dans son propre dépôt | ✅ | 2026-08-14 | Fait : `loan` vit dans `../loan`, dépôt séparé. Couplage réduit à une ligne de CSS |
| [007](./007-pas-de-split-eurio-avant-artefacts.md) | Ne pas découper Eurio avant d'avoir des artefacts publiés | 🟡 | 2026-08-14 | Un split par dossier casse R1/R2 ; il faut d'abord publier tokens et catalogue |
| [008](./008-deux-voies-backbone-gele-et-arcface.md) | Deux voies vers le modèle embarqué : backbone gelé + banque, à côté d'ArcFace | 🟡 | 2026-08-19 | Ajouter une classe ne doit plus coûter un réentraînement ; le corpus de scan départagera |
| [009](./009-direction-a-writer-canonique-unique.md) | Direction A : un seul writer du canonique, le VPS | ✅ | 2026-07-03 | L'event-log a été mesuré divergent ; Mac/PC lisent une réplique read-only et écrivent par HTTP |
| [010](./010-authentik-oidc-et-pat.md) | Authentik en IDP unique, PAT pour les machines, RBAC dans `eurio-api` | ✅ | 2026-06-19 | Quatre surfaces × quatre auths → une. L'identité est humaine ; le Mac n'est pas une personne |
| [011](./011-front-admin-unique.md) | Un seul front admin, deux cibles de build ; le lourd se grise | ✅ | 2026-06-29 | Le mixed content interdit d'*appeler* `:8042` en hébergé, pas de *servir le même code* |
| [012](./012-review-collaborative-ecriture-directe.md) | Les amis reviewent le canonique directement, en quarantaine par scope | ✅ | 2026-08-23 | Sous Direction A, un tampon `review.db` recopierait la donnée d'un serveur vers lui-même |
| [013](./013-la-maille-est-la-classe.md) | La maille du modèle est la CLASSE, jamais la pièce | ✅ | 2026-08-18 | 129 pièces = 40 classes. Et trois conventions portent le nom `class_id` — toujours demander *laquelle* |
| [014](./014-sauvegarde-duplicati-et-anneaux.md) | Sauvegarde : Duplicati unique, staging applicatif, cinq anneaux | ✅ | 2026-08-14 | Le risque n'est pas de ne pas sauvegarder, c'est de croire qu'on sauvegarde — 81 jours de vert sur des jobs en 401 |
| [015](./015-secrets-sops-age.md) | Secrets : SOPS + age, une source unique, y compris sur le VPS | ✅ | 2026-06-16 | `secrets/dev.env` chiffré et committé ; le code lit `os.environ`, jamais un fichier |

## Où vit quelle information

| Type | Emplacement |
|---|---|
| **Pourquoi** une décision a été prise | `docs/adr/` (ce dossier) |
| **Ce que fait le système** aujourd'hui | `docs/architecture/` |
| **Ce qu'on est en train de faire** | `docs/work-in-progress/<chantier>/` |
| Décisions design par vue | `docs/design/{vue}/README.md` |
| Règles non-négociables | `CLAUDE.md` |

> 📌 **Cet index est le seul journal de décisions du dépôt.** `docs/DECISIONS.md`
> (avril 2026) et `docs/refacto-ml/adr.md` (juin 2026) ont été supprimés le 2026-08-24 :
> deux index concurrents, c'était deux index de trop, et le premier se contredisait
> lui-même (il prescrivait `unittest` contre 131 fichiers pytest dans le dépôt). Ce
> qu'ils portaient encore de vivant est repris dans les ADR 009 à 015.

## Écrire une ADR

Fichier `00X-titre-court.md`, format des ADR existantes :
**Contexte** (le problème et ses contraintes) → **Décision** → **Alternatives considérées**
(tableau option/verdict) → **Conséquences** (y compris les mauvaises).

Une ADR ne se réécrit pas : si la décision change, on en crée une nouvelle et on marque
l'ancienne ⚪️ *superseded par ADR-00Y* — **on garde la trace du raisonnement d'origine**,
c'est tout l'intérêt. Puis on ajoute la ligne ici.
