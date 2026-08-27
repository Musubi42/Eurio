# Juge du crop — construire l'instrument avant de choisir la méthode

> **Ce chantier ne choisit pas une méthode de crop. Il construit le juge qui
> permettra d'en choisir une.** Le nom reprend celui de
> [`juge-et-banc/`](../juge-et-banc/SUIVI-MATRICE.md) pour la même raison : ce
> chantier-là a tranché ArcFace ↔ DINO parce qu'il avait bâti son juge **avant**
> de comparer.

**Ouvert le 2026-08-27.** Décision structurante :
[ADR-017](../../adr/017-le-crop-d-enrichissement-est-decouple-du-scan.md).

## En une phrase

Sept chantiers « crop » entre mai et août 2026 ont chacun atteint leur cible sur
leur propre métrique et produit des crops que l'humain jette. **Le mode d'échec
est constant : l'oracle, jamais l'algorithme.**

## Par où entrer

| Tu veux… | Lis |
|---|---|
| comprendre pourquoi sept fois | [`PROBLEME.md`](./PROBLEME.md) |
| le jeu de vérité terrain | [`JEU-D-OR.md`](./JEU-D-OR.md) |
| **le juge, et pourquoi il n'est pas un score** | [`JUGE.md`](./JUGE.md) |
| comment on compare des méthodes | [`PROTOCOLE-BANC.md`](./PROTOCOLE-BANC.md) |
| ce qui a été tranché, et quand | [`DECISIONS.md`](./DECISIONS.md) |
| où on en est | [`SUIVI.md`](./SUIVI.md) |

## Les quatre choses à savoir avant de toucher au crop

1. **`quality_score` ne mesure rien d'utile.** 0,9200 chez les acceptés, 0,9208
   chez les rejetés pour motif de crop. Huit dix-millièmes. Ne l'utilise dans
   aucun verdict.
2. **Un seuil « IoU ≥ 0,80 » tolère 10,6 % d'amputation du rayon.** C'était le
   critère pré-enregistré et validé PO de `crop-recovery`. Il était
   mathématiquement aveugle à ce qu'il devait mesurer.
3. **Aucun score d'embedding dans la boucle de décision du crop.** DINO et
   ArcFace sont des juges d'identité, pas de cadrage, et l'optimum de cadrage
   sous critère d'identité est **structurellement l'amputation**. Mesuré le
   2026-08-27, planche visuelle à l'appui.
4. **`tilt_deg` est tronqué par le bas à 14,07°.** `_TILT_TRIVIAL = 0.97` et
   `acos(0,97) = 14,0699°` : `tilt_trustworthy=1 ⟺ tilt_deg ≥ 14,07°`. Chercher
   une pièce « de face » dans cette colonne est une contradiction logique.
   Le critère de remplacement est `axis_ratio ≥ 0,97`, sans `tilt_trustworthy`.

## Les lots, dans l'ordre où ils doivent tomber

| lot | contenu | bloque |
|---|---|---|
| **L0** | `PROBLEME` + `JUGE` + `JEU-D-OR`, seuils **signés PO** | tout le reste |
| **L1** | instrumentation du recadrage manuel (migration `0018` + payload) | rien — **à jouer en premier, la collecte court dès qu'il est posé** |
| **L2** | outil d'annotation jetable + séance PO (~50 min) → `gold.json v1` | L3 |
| **L3** | juge implémenté + **RE-4 exécuté sur le crop actuel** | ⛔ **point d'arrêt : si RE-4 échoue, le chantier s'arrête** |
| **L4** | bornes (`gold_replay`, `human_2nd_pass`, `measure_tilt_ellipse`) | L5 |
| **L5** | ouverture du banc aux méthodes candidates | — |

⚠️ **L1 ne bloque personne et rapporte tous les jours.** Chaque review du PO
produit une observation dès qu'il est posé. Le jouer en premier.

## Ce qui n'est PAS dans ce chantier

- Le choix d'une méthode de crop — c'est L5, et il n'ouvrira qu'après L3.
- Le crop du **scan Android**. ADR-017 les découple : ce sont deux problèmes
  différents. La dette inverse est `BACKLOG.md` M3.
- Le rejet **de sujet** (mauvaise face, mauvaise dénomination). C'est le premier
  motif de rejet en volume — 4 669 contre 1 430 — mais il ne parle pas du
  cadrage. Il vit dans `debit-enrichissement/`.
