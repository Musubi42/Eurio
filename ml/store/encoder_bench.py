"""Résultats du banc multi-encodeurs — accès table, stdlib-only.

Deux tables, au **canonique** (pas dans un store local type ``scan_corpus.db``) :

* ``encoder_bench_runs`` — un run = un couple (banque, encodeur) évalué sur un
  gold versionné, avec ses métriques et son verdict de calibration ;
* ``encoder_bench_predictions`` — une ligne par crop, réduite aux scalaires
  dont McNemar et le balayage de seuils ont besoin. Sa raison d'être :
  ``load_correctness`` permet de rejouer un test apparié **sans ré-encoder**.

Pourquoi au canonique : la page admin qui affiche ces résultats est servie par
le front hébergé, qui n'a pas accès au ML local (``hasLocalMlApi=false``) ; et
``dino_thresholds`` — que la promotion écrit à partir de ces chiffres — y est
déjà. Une décision et sa preuve vivent au même endroit.

Contrat d'import : **stdlib + sqlite3 uniquement**. L'image lean du VPS sert
ces lectures ; y tirer numpy ou torch ferait skipper le routeur en silence.

⚠️ Direction A : sous le flip, Mac/PC lisent une réplique en lecture seule.
L'écriture passe par ``POST /ingest/encoder-bench`` (cf. ``client.ingest.
push_encoder_bench``), jamais par un ``INSERT`` local — sinon le
``readonly database`` tombe à la dernière ligne, après tout le calcul.

⚠️ **Le garde de calibration est armé dans :func:`record_run`** — la seule
porte d'écriture de ``encoder_bench_runs``. Aucun appelant, présent ou futur,
ne peut écrire ``provisional=0`` dans une base qui mesure des bloqueurs. Le
motif que cela ferme est décrit dans le docstring de ``record_run`` et verrouillé
par ``tests/test_encoder_bench_guard_family.py``.

Miroir DDL : ``serving/migrations/0009_encoder_bench.sql`` (+ ``state/schema.sql``).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterator, Sequence

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "serving"
    / "migrations"
    / "0009_encoder_bench.sql"
)

_MIGRATION_0015 = (
    Path(__file__).resolve().parent.parent
    / "serving"
    / "migrations"
    / "0015_encoder_bench_quantization_eval_corpus.sql"
)

#: Le DDL, lu depuis la migration : une seule source, pas de copie qui dérive.
SCHEMA_SQL = _MIGRATION.read_text(encoding="utf-8")

#: Les colonnes ajoutées par 0015, avec leur déclaration. Elles ne peuvent pas
#: être servies par ``executescript(SCHEMA_SQL)`` : ``ALTER TABLE ADD COLUMN``
#: n'a pas de ``IF NOT EXISTS`` et lèverait « duplicate column name » au
#: deuxième appel — or ``ensure_schema`` est explicitement rejouable.
_COLUMNS_0015 = (
    ("quantization", "TEXT NOT NULL DEFAULT 'fp32'"),
    ("eval_corpus", "TEXT"),
)

#: Le vocabulaire admis par ``quantization``. Gardé ICI et pas par un ``CHECK``
#: SQL : un CHECK imposerait une reconstruction de table pour admettre une
#: précision de plus, et resterait absent des bases antérieures à 0015 — donc
#: muet là où il compte. Cf. le commentaire de la colonne dans schema.sql.
QUANTIZATIONS = ("fp32", "fp16", "int8_dynamic", "int8_static")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Crée les tables si elles manquent (``IF NOT EXISTS``, rejouable).

    Sert les bases locales et les tests. Sur le canonique, c'est ``db_migrate``
    qui applique les migrations ; l'appeler ici ne fait rien de plus.

    Applique aussi 0015 (``quantization`` / ``eval_corpus``) : sans ça une base
    de test montée par cette fonction obtiendrait la table de 0009 et
    :func:`record_run` lèverait « colonne absente » sur un champ que TOUT run
    renseigne. La panne serait bruyante — mais au pire moment, après le calcul.
    """
    conn.executescript(SCHEMA_SQL)
    present = _table_columns(conn, "encoder_bench_runs")
    for column, decl in _COLUMNS_0015:
        if column not in present:
            conn.execute(
                f"ALTER TABLE encoder_bench_runs ADD COLUMN {column} {decl}"
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_encoder_bench_runs_corpus "
        "ON encoder_bench_runs(eval_corpus, created_at DESC) "
        "WHERE eval_corpus IS NOT NULL"
    )


@contextmanager
def _row_access(conn: sqlite3.Connection) -> Iterator[None]:
    """Pose ``sqlite3.Row`` le temps de la lecture, puis restaure l'existant.

    Les lectures d'ici indexent les colonnes par nom. Exiger de l'appelant
    qu'il ait posé ``row_factory`` serait un contrat invisible : sur une
    connexion nue — celle que ``ensure_schema`` invite à créer pour les tests
    et les bases locales — on récoltait un ``TypeError: tuple indices must be
    integers`` loin de la cause. Même patron que ``review.bench_gold.build_gold``.
    """
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        yield
    finally:
        conn.row_factory = previous


@dataclass
class EncoderBenchRun:
    """Miroir 1:1 des colonnes de ``encoder_bench_runs``."""

    run_id: str
    created_at: str
    gold_version: str
    gold_n_crops: int
    anchors_kind: str
    encoder_spec: str
    encoder_version: str
    n_in_scope: int
    gold_sample_n: int | None = None
    bank_build_id: str | None = None
    bank_n_anchors: int | None = None
    bank_n_classes: int | None = None
    embed_dim: int | None = None
    n_params_m: float | None = None
    input_px: int | None = None
    device: str | None = None
    ms_per_img: float | None = None
    recall1: float | None = None
    recall5: float | None = None
    country_n: int | None = None
    country_recall1: float | None = None
    country_recall5: float | None = None
    spread_at_p97: float | None = None
    coverage_at_p97: float | None = None
    precision_at_p97: float | None = None
    sweep_json: str | None = None
    baseline_run_id: str | None = None
    mcnemar_p: float | None = None
    mcnemar_b: int | None = None
    mcnemar_c: int | None = None
    #: D16 — taille de l'INTERSECTION des crops entre ce run et sa baseline.
    #: Sans elle, un recouvrement d'1 crop sur 501 rend ``mcnemar_p=1.0, b=0,
    #: c=0`` : indiscernable d'une égalité mesurée sur 1958 crops. La colonne
    #: SQL correspondante (``n_paired INTEGER``, nullable) a été posée le
    #: 2026-08-19 dans ``0009_encoder_bench.sql`` et son miroir
    #: ``state/schema.sql``. Renseignée par ``scripts/bench_encoder_dino`` à
    #: partir de ``PairedResult.n_paired`` ; NULL quand il n'y a pas de baseline.
    n_paired: int | None = None
    #: 1 par défaut — un run promouvable est l'exception qu'il faut justifier.
    provisional: int = 1
    provisional_reason: str | None = None
    host: str | None = None
    git_commit: str | None = None
    note: str | None = None
    #: Migration 0015 — la PRÉCISION à laquelle l'encodeur a tourné. Elle est
    #: RELEVÉE sur le modèle chargé, jamais déclarée par l'appelant (cf.
    #: ``scripts.bench_encoder_dino._quantization_of``) : l'axe int8 n'a pas
    #: encore été mesuré, et le jour où il le sera, un champ déclaratif dirait
    #: « int8 » d'un modèle resté en fp32 sans que rien ne rougisse.
    quantization: str = "fp32"
    #: Migration 0015 — le corpus d'évaluation noté (``image_assets.eval_corpus``,
    #: 0014), recopié du sidecar du gold. NULL = gold de review.
    eval_corpus: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class EncoderBenchPrediction:
    """Miroir 1:1 de ``encoder_bench_predictions`` — scalaires seulement."""

    asset_id: str
    #: Le ``class_id`` de la BANQUE (représentant de groupe de dessin), pas un
    #: ``coins.eurio_id`` — 105 crops sur 1958 divergent (D5). Nommée
    #: ``truth_eurio_id`` jusqu'au 2026-08-19 ; le nom mentait et la table
    #: était vide partout, donc le renommage n'a rien coûté.
    truth_class_id: str
    correct: int
    in_top5: int
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top2_sim: float | None = None
    spread: float | None = None
    country_top1_eurio_id: str | None = None
    country_correct: int | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


_RUN_COLUMNS = [f.name for f in fields(EncoderBenchRun)]
_PRED_COLUMNS = ["run_id"] + [f.name for f in fields(EncoderBenchPrediction)]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


#: Nombre de références à partir duquel une classe est **couverte**.
#:
#: C'est une constante de la COURBE, pas un réglage : held-out, vits14,
#: `COURBE-REFERENCES.md` mesure N=0 à 53,1 %, N=1 à **50,1 %** (une classe à
#: un seul exemplaire est PIRE qu'au canonique seul) et N=2 à 54,6 % — le
#: premier palier qui sort du régime canonique-seul. Même forme en vitl14
#: (76,1 / 72,5 / 74,5), décalée en niveau : la valeur ne dépend pas de
#: l'encodeur.
#:
#: ⚠️ **Ce que ce N=1 signifie a été précisé le 2026-08-20 au soir** : « TOUTES
#: les classes plafonnées à 1 », jamais « ces classes-ci à 1, les autres
#: pleines ». La mesure restreinte dit qu'un exemplaire unique **aide** sa
#: classe (``vitl14`` 67,6 → 69,1 %, p=0,048). Ça n'invalide pas ce 2 : le garde
#: ne demande pas « un exemplaire unique est-il nuisible ? » mais « à partir de
#: combien de références une classe est-elle **utilement** couverte ? », et
#: c'est bien N=2 qui sort du régime canonique-seul en agrégat.
#:
#: ⚠️ **Ce 2 n'est PAS ``dino_thresholds.min_exemplars``, et ne doit jamais le
#: devenir.** Le découplage a été payant dès le soir de son écriture : le
#: plancher a été **retiré** le 2026-08-20 (``min_exemplars`` = 1, inactif) et
#: cette constante n'a pas bougé d'une ligne. Les deux répondent à deux
#: questions opposées : le plancher dit ce
#: que le BUILDER accepte d'écrire, celle-ci dit ce que le GARDE accepte de
#: compter. Les lier, c'est reconduire exactement le couplage qui a périmé le
#: seuil de 180 : desserrer le plancher desserrerait le garde du même geste, et
#: un plancher à 0 rendrait au garde son ancien compte « au moins un
#: exemplaire ». Le garde doit rester capable de dire « la banque que tu viens
#: de bâtir est trop pauvre », y compris quand c'est le plancher qu'on a bougé.
USEFUL_MIN_REFS = 2

#: Couverture utile minimale pour qu'un run soit promouvable.
#:
#: **Ce n'est pas une ambition, c'est une ligne de non-régression**, et c'est
#: pourquoi elle est basse. 118 = la couverture utile de la banque d'AVANT le
#: plancher (build ``23c637d93b43`` du 2026-08-19) : 182 classes à exemplaires
#: dont 64 à un seul, donc 118 à deux ou plus (distribution relevée sur
#: ``ml/state/eurio.replica.db`` le 2026-08-20 à 13:58 UTC, recopiée en tête de
#: ``serving/migrations/0011_dino_thresholds_min_exemplars.sql`` ; l'ancienne banque a été
#: écrasée sur disque depuis, ce chiffre n'est plus re-mesurable ici).
#:
#: La banque servie d'aujourd'hui (build ``365dcab2a253``, 2026-08-20T14:27Z)
#: en mesure **124** :
#:
#:     SELECT COUNT(*) FROM (SELECT class_id FROM dino_class_references
#:       WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14'
#:         AND method='fps' GROUP BY class_id HAVING COUNT(*) >= 2);
#:     -- 124   (eurio.replica.db, 2026-08-20T17:16Z)
#:
#: — soit 6 de marge. C'est le résultat que ce seuil rend lisible : sur la
#: métrique utile, le plancher n'a pas régressé, il a fait **+6**. Le 182 → 124
#: qui a l'air d'un effondrement compare deux métriques différentes.
#:
#: ⚠️ **Cette marge ne sera pas consommée par le retrait du plancher** (défaut
#: revenu à 1 le 2026-08-20 au soir) : le plancher ne faisait jamais descendre
#: une classe de ≥ 2 à < 2, il ne supprimait que celles à exactement 1. Le
#: compte utile est donc invariant. **C'est aussi pourquoi ce garde restera
#: MUET sur le changement de forme du prochain rebuild** — 68 classes y
#: retrouveront leur exemplaire unique sans que P1 en dise un mot. C'est le
#: comportement voulu ; il faut le savoir.
#:
#: Pourquoi pas un garde RELATIF au build précédent (la piste la plus propre) :
#: ``dino_anchor_builds`` porte bien l'historique, mais aucune de ses colonnes
#: ne dit la couverture UTILE d'un build (``n_classes``, ``n_rows``,
#: ``n_canonical``, ``n_exemplars``, ``exemplars_per_class`` — jamais la
#: distribution), et ``dino_class_references`` est remplacée à chaque build,
#: donc l'état d'hier n'existe plus nulle part. Le mesurer demanderait une
#: colonne ``n_classes_utiles`` sur ``dino_anchor_builds`` — cf. le docstring
#: de :func:`_p1_blockers`.
DEFAULT_MIN_USEFUL_CLASSES = 118

#: Clé PRÉPARÉE pour ``dino_thresholds``, volontairement pas encore branchée.
#:
#: Sa place est en base : c'est un réglage d'exploitation, il a la portée
#: exacte de la table (le couple banque × encodeur — un encodeur candidat
#: démarre à 0 classe utile et n'a pas à être jugé sur la ligne de la prod), et
#: la table journalise ses changements (``dino_threshold_changes``), ce qu'une
#: constante de code ne fait pas. Ce qu'il faudrait, dans l'ordre :
#:
#: 1. ``shared/dino_threshold_defaults.py`` : ``KEYS`` += cette clé,
#:    ``BOUNDS`` += ``(0, 5000)``, ``CLES_ENTIERES`` += cette clé (c'est un
#:    COMPTE — S1 a déjà montré ce que coûte un compte fractionnaire) ;
#: 2. une migration **0012** : le ``key`` de ``dino_thresholds`` porte un
#:    ``CHECK (key IN (…))`` qui énumère les six clés actuelles. ⚠️ 0011 n'est
#:    **pas encore appliquée au canonique** (``_schema_migrations`` y dit
#:    ``0008``) — mais elle est **livrée**, donc elle ne s'amende pas : il faut
#:    reconstruire la table comme 0011 l'a fait, plus son miroir dans
#:    ``state/schema.sql`` ;
#: 3. ici : résoudre le seuil par ``store.dino_thresholds.resolve`` et
#:    **journaliser sa ``source``** (``db`` vs ``code``) dans le message du
#:    bloqueur — un seuil réglé qui retomberait en silence sur le défaut serait
#:    la panne muette habituelle.
#:
#: Rien de tout cela n'est fait ici : ce lot ne crée pas de migration, et une
#: clé déclarée dans ``KEYS`` mais rejetée par le ``CHECK`` SQL donnerait un
#: 503 à l'écriture — un réglage qui a l'air possible et ne l'est pas.
THRESHOLD_KEY_MIN_USEFUL_CLASSES = "min_useful_classes"

#: Comment rebâtir la banque, en une commande qui marche là où on la lit.
#:
#: Le message disait ``scripts.build_dino_anchors --kind X`` (P3) et
#: ``… --force --push`` (P1). Mesuré le 2026-08-20 sur
#: ``ml/state/eurio.replica.db`` en appelant le préflight réel
#: (``scripts.build_dino_anchors.preflight_db_traceability``) sous
#: ``EURIO_DB_READONLY=1`` :
#:
#:     push=True  -> write_references=False   (la trace part au canonique)
#:     push=False -> REFUS: Base non inscriptible : …/eurio.replica.db
#:
#: Donc la variante SANS ``--push`` — celle de P3 — refuse de démarrer sous le
#: devShell, et celle de P1 marche. Les deux messages disent désormais la même
#: chose, avec le drapeau qui fait la différence et la sortie de secours.
_HINT_BUILD = (
    "go-task ml:dino-anchors:build -- --kind {kind} --force --push "
    "[le --push est ce qui la fait passer sous le devShell : la trace part au "
    "canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la "
    "commande AVANT l'encodage]"
)


class CalibrationNotVerified(RuntimeError):
    """Un run se déclare promouvable (``provisional=0``) alors que LA BASE où
    il s'écrit mesure des bloqueurs.

    Porte les bloqueurs mesurés, pour que l'appelant puisse les journaliser ou
    les recopier dans ``provisional_reason`` — jamais les jeter.
    """

    def __init__(self, run_id: str, blockers: Sequence[str]) -> None:
        self.run_id = run_id
        self.blockers = list(blockers)
        super().__init__(
            f"run {run_id!r} declare provisional=0 alors que la base mesure "
            f"{len(self.blockers)} bloqueur(s) : {' | '.join(self.blockers)} "
            "— corriger provisional/provisional_reason a partir de la mesure "
            "(store.encoder_bench.measured_blockers), ou ne pas ecrire"
        )


def measured_overlap(
    conn: sqlite3.Connection, run_id: str, baseline_run_id: str
) -> int | None:
    """``paired_overlap`` rendu SÛR : ``None`` quand il n'est pas mesurable.

    ``paired_overlap`` rend ``0`` dans deux situations incomparables — deux
    runs réellement disjoints, et un run dont les prédictions par crop ne sont
    tout simplement pas en base (la route accepte ``predictions: []``). Prendre
    ce ``0`` pour une mesure ferait exactement la panne que D16 décrit, à
    l'envers : un run parfaitement apparié déclaré « recouvrement nul ».

    D'où le contrat : ``None`` = non mesurable ici, l'appelant retombe sur la
    valeur déclarée (que ``_paired_blockers`` jugera) ; un entier = mesure, qui
    fait autorité sur le déclaratif.
    """
    if not _table_exists(conn, "encoder_bench_predictions"):
        return None
    n_run, n_base = conn.execute(
        "SELECT COALESCE(SUM(run_id = ?), 0), COALESCE(SUM(run_id = ?), 0) "
        "  FROM encoder_bench_predictions",
        (run_id, baseline_run_id),
    ).fetchone()
    if not n_run or not n_base:
        return None
    return paired_overlap(conn, run_id, baseline_run_id)


def measured_blockers(
    conn: sqlite3.Connection,
    run: EncoderBenchRun,
    *,
    min_useful_classes: int = DEFAULT_MIN_USEFUL_CLASSES,
) -> list[str]:
    """Les bloqueurs que **la base mesure** pour ce run. Le payload n'est pas cru.

    Seul ``run.provisional`` / ``run.provisional_reason`` sont ignorés : ce sont
    les champs déclaratifs, ceux qu'un appelant tiers peut forger. Tout le reste
    (le couple, le périmètre, la baseline) sert d'entrée à la mesure.

    ``n_paired`` est un cas à part : c'est le seul champ déclaratif que la base
    sait **recompter** (``measured_overlap``). Quand elle le peut, sa mesure
    l'emporte ; sinon le déclaré passe, et ``_paired_blockers`` le confronte au
    périmètre du run.
    """
    n_paired = run.n_paired
    if run.baseline_run_id:
        mesure = measured_overlap(conn, run.run_id, run.baseline_run_id)
        if mesure is not None:
            n_paired = mesure
    return calibration_blockers(
        conn,
        anchors_kind=run.anchors_kind,
        encoder_version=run.encoder_version,
        gold_sample_n=run.gold_sample_n,
        gold_n_crops=run.gold_n_crops,
        min_useful_classes=min_useful_classes,
        baseline_run_id=run.baseline_run_id,
        n_paired=n_paired,
    )


def record_run(conn: sqlite3.Connection, run: EncoderBenchRun) -> None:
    """Écrit (ou remplace) la ligne de run. L'appelant possède la transaction.

    ⚠️ **C'est ici que le garde de calibration est armé, et nulle part
    ailleurs.** M2 (2026-08-20) : ``calibration_blockers`` n'était appelé que
    par ``scripts/bench_encoder_dino`` — un chemin sur trois. ``POST
    /ingest/encoder-bench`` recopiait ``provisional`` depuis le corps HTTP, et
    un appel direct au store n'en parlait même pas. Quatre instances du même
    motif en deux jours (D1 volet P3, D1 volet P1, M1, M2) disent que brancher
    le garde sur *un chemin de plus* ne suffit pas : il est branché sur **la
    porte**, celle par laquelle toute écriture passe forcément.

    Règle : **un run ne peut pas s'écrire ``provisional=0`` dans une base qui
    mesure des bloqueurs.** La mesure se fait sur ``conn`` — la base de
    DESTINATION, pas la réplique où l'appelant a calculé. Violation =
    :class:`CalibrationNotVerified`, jamais un silence.

    Second garde, même porte : ``quantization`` doit appartenir à
    :data:`QUANTIZATIONS`. Une précision inventée passerait le typage (c'est un
    TEXT), s'écrirait, et rendrait deux bras de la matrice incomparables sans
    qu'aucune lecture ne le dise.

    ``provisional=1`` n'est pas mesuré : se déclarer non-promouvable est
    toujours recevable, et le faire mesurer coûterait quatre requêtes SQL à
    chaque run du banc pour un verdict qui ne peut que confirmer.

    Le dataclass peut porter un champ que le DDL de la base n'a pas encore.
    (``n_paired`` a été ce cas jusqu'au 2026-08-19 ; la colonne est désormais
    dans ``0009_encoder_bench.sql`` et son miroir ``state/schema.sql``, donc le
    garde ci-dessous est dormant — pas mort : il reste exercé par
    ``tests/test_encoder_bench_store.py::test_record_run_leve_si_la_colonne_manque``
    et couvrira le prochain champ ajouté sans DDL.)
    On n'insère que les colonnes réellement présentes — mais **perdre une valeur renseignée est interdit** : si un
    champ absent du DDL vaut autre chose que ``None``, on lève. Le contraire
    serait exactement la panne muette que ce module passe son temps à traquer :
    un run qui croit avoir tracé son recouvrement et n'a rien tracé.
    """
    if run.quantization not in QUANTIZATIONS:
        raise ValueError(
            f"encoder_bench_runs.quantization={run.quantization!r} hors "
            f"vocabulaire {QUANTIZATIONS} — une precision inventee rendrait "
            "deux bras de la matrice incomparables sans qu'aucune lecture ne "
            "le dise"
        )
    if int(run.provisional or 0) == 0:
        blockers = measured_blockers(conn, run)
        if blockers:
            raise CalibrationNotVerified(run.run_id, blockers)

    present = _table_columns(conn, "encoder_bench_runs")
    perdus = [
        c
        for c in _RUN_COLUMNS
        if c not in present and getattr(run, c) is not None
    ]
    if perdus:
        raise RuntimeError(
            "encoder_bench_runs: colonne(s) absente(s) du schema alors que le "
            f"run les renseigne : {', '.join(perdus)} — appliquer la migration "
            "(serving/migrations/0009_encoder_bench.sql + state/schema.sql) "
            "avant d'ecrire, plutot que de perdre la valeur en silence"
        )
    cols = [c for c in _RUN_COLUMNS if c in present]
    placeholders = ",".join("?" * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO encoder_bench_runs ({','.join(cols)}) "
        f"VALUES ({placeholders})",
        tuple(getattr(run, c) for c in cols),
    )


def record_predictions(
    conn: sqlite3.Connection,
    run_id: str,
    rows: Sequence[EncoderBenchPrediction],
    *,
    purge_empty: bool = False,
) -> int:
    """Remplace EN BLOC les prédictions du run (DELETE puis INSERT).

    Le remplacement en bloc, plutôt qu'un UPSERT ligne à ligne : un run rejoué
    sur un sous-ensemble plus petit ne doit pas laisser traîner les lignes de
    l'exécution précédente — elles fausseraient silencieusement l'apparié.

    **Une liste vide ne purge pas** (sauf ``purge_empty=True``). Le DELETE
    était inconditionnel : repousser un run pour corriger sa ``note`` ou son
    ``mcnemar_p`` — la route ``POST /ingest/encoder-bench`` accepte
    ``predictions: []`` — effaçait ses prédictions par crop, c'est-à-dire
    exactement ce qui rend l'apparié rejouable sans ré-encoder. Effacer est
    désormais un geste qui se demande.
    """
    if not rows:
        if purge_empty:
            conn.execute(
                "DELETE FROM encoder_bench_predictions WHERE run_id = ?", (run_id,)
            )
        return 0
    conn.execute("DELETE FROM encoder_bench_predictions WHERE run_id = ?", (run_id,))
    placeholders = ",".join("?" * len(_PRED_COLUMNS))
    conn.executemany(
        f"INSERT INTO encoder_bench_predictions ({','.join(_PRED_COLUMNS)}) "
        f"VALUES ({placeholders})",
        [
            tuple([run_id] + [getattr(r, c) for c in _PRED_COLUMNS[1:]])
            for r in rows
        ],
    )
    return len(rows)


def list_runs(
    conn: sqlite3.Connection,
    *,
    anchors_kind: str | None = None,
    encoder_version: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Les runs, du plus récent au plus ancien, filtrés par couple."""
    where: list[str] = []
    params: list[object] = []
    if anchors_kind:
        where.append("anchors_kind = ?")
        params.append(anchors_kind)
    if encoder_version:
        where.append("encoder_version = ?")
        params.append(encoder_version)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    params.append(int(limit))
    with _row_access(conn):
        rows = conn.execute(
            f"SELECT * FROM encoder_bench_runs{clause} "
            "ORDER BY created_at DESC, run_id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    with _row_access(conn):
        row = conn.execute(
            "SELECT * FROM encoder_bench_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def load_correctness(conn: sqlite3.Connection, run_id: str) -> dict[str, bool]:
    """``{asset_id: correct}`` — de quoi rejouer un apparié sans ré-encoder.

    C'est la raison d'être de la table ``predictions`` : comparer deux
    encodeurs déjà évalués coûte alors une requête, pas deux heures de GPU.
    """
    with _row_access(conn):
        rows = conn.execute(
            "SELECT asset_id, correct FROM encoder_bench_predictions WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    return {r["asset_id"]: bool(r["correct"]) for r in rows}


def paired_overlap(conn: sqlite3.Connection, run_id: str, baseline_run_id: str) -> int:
    """Nombre de crops COMMUNS aux deux runs — la mesure que D16 réclamait.

    ``paired_compare`` la calcule en mémoire (``PairedResult.n_paired``) au
    moment du bench, et c'est cette valeur que le banc trace dans
    ``encoder_bench_runs.n_paired``. Cette fonction est le recours d'APRÈS
    COUP : elle recompte depuis ``encoder_bench_predictions``, sans ré-encoder,
    et permet donc de vérifier un run déjà poussé — y compris un run dont le
    ``n_paired`` déclaré serait faux :

        SELECT COUNT(*) FROM encoder_bench_predictions a
          JOIN encoder_bench_predictions b USING (asset_id)
         WHERE a.run_id = ? AND b.run_id = ?
    """
    return conn.execute(
        "SELECT COUNT(*) FROM encoder_bench_predictions a "
        "  JOIN encoder_bench_predictions b USING (asset_id) "
        " WHERE a.run_id = ? AND b.run_id = ?",
        (run_id, baseline_run_id),
    ).fetchone()[0]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def calibration_blockers(
    conn: sqlite3.Connection,
    *,
    anchors_kind: str,
    encoder_version: str,
    gold_sample_n: int | None = None,
    gold_n_crops: int | None = None,
    min_useful_classes: int = DEFAULT_MIN_USEFUL_CLASSES,
    baseline_run_id: str | None = None,
    n_paired: int | None = None,
) -> list[str]:
    """Les raisons pour lesquelles un run n'est PAS promouvable. Vide = promouvable.

    Chaque raison se **mesure en SQL**, aucune n'est devinée :

    * **P3** — prédictions antérieures au dernier build de la banque ::

        SELECT COUNT(*) FROM image_asset_dino_predictions p
         WHERE p.anchors_kind=? AND p.encoder_version=?
           AND datetime(p.computed_at) < datetime(
                 (SELECT MAX(built_at) FROM dino_anchor_builds
                   WHERE anchors_kind=? AND encoder_version=?))

      Mesuré le 2026-08-19 sur ``ml/state/eurio.replica.db`` : **12454 sur
      12454**, le dernier build datant du 2026-08-19T00:28:21+00:00.

    * **P1** — classes réellement **couvertes** (≥ :data:`USEFUL_MIN_REFS`
      exemplaires) dans la banque servie,
      **POUR CET ENCODEUR**. Ce scope est désormais porté par l'identité de la
      ligne : depuis la migration 0010, la clé primaire de
      ``dino_class_references`` est ``(anchors_kind, encoder_version, class_id,
      eurio_id, asset_id)``. L'index ``idx_dino_class_refs_canonical`` reste
      nécessaire **en plus**, mais il est PARTIEL (``… WHERE asset_id IS
      NULL``) : il ne couvre que les canoniques, dont l'``asset_id`` NULL ne
      déduplique rien dans la PK. Avant 0010 l'encodeur n'était dans NI l'un NI
      l'autre pour les lignes ``fps`` — c'était le défaut M1 ::

        SELECT COUNT(*) FROM (
          SELECT class_id FROM dino_class_references
           WHERE anchors_kind=? AND encoder_version=? AND method='fps'
           GROUP BY class_id HAVING COUNT(*) >= 2)

      Mesuré le 2026-08-20 à 17:16 UTC sur ``ml/state/eurio.replica.db`` :
      **124** classes couvertes pour ``dinov2-vitl14`` (dont 64 à 8
      exemplaires ou plus), **0** pour tout candidat DINOv3.

    * **échantillon** — un run sur K crops sur N (K ≠ N) ne calibre rien de
      promouvable ; un run sur le gold ENTIER, si.

    * **apparié** — un run qui déclare une baseline doit prouver que la
      comparaison a porté sur le même jeu (cf. ``_paired_blockers``).

    Principe qui gouverne les trois : **ce qui n'est pas mesurable bloque**.
    Une table absente, un couple sans build tracé, un couple sans prédiction
    sont des bloqueurs — pas des feux verts par défaut.
    """
    blockers: list[str] = []
    blockers += _p3_blockers(conn, anchors_kind, encoder_version)
    blockers += _p1_blockers(
        conn, anchors_kind, encoder_version, min_useful_classes
    )

    # D8 : un run sur la TOTALITÉ du gold n'est pas un échantillon. Le bloqueur
    # tombait dès que ``gold_sample_n`` était renseigné, sans le comparer au
    # total — le seul contournement était de mentir sur la trace en passant
    # ``gold_sample_n=None``, l'exact inverse de l'intention du garde.
    # ``gold_n_crops`` inconnu reste bloquant : on ne peut pas prouver que le
    # run a couvert tout le gold.
    #
    # Le prédicat est ``!=`` et pas ``<`` : un run déclarant 99999 crops sur un
    # gold de 1958 n'est pas « plus que complet », c'est une trace incohérente
    # (désynchronisation ``--gold`` ↔ sidecar, ou payload forgé par un appelant
    # tiers de ``POST /ingest/encoder-bench``). Avec ``<`` il sortait
    # ``provisional=0`` — le garde récompensait le chiffre le plus faux.
    if gold_sample_n is not None and (
        gold_n_crops is None or gold_sample_n != gold_n_crops
    ):
        total = gold_n_crops if gold_n_crops is not None else "?"
        blockers.append(
            f"echantillon: run sur {gold_sample_n} crops sur les {total} du gold"
        )

    blockers += _paired_blockers(
        baseline_run_id, n_paired, gold_sample_n, gold_n_crops
    )

    return blockers


def _paired_blockers(
    baseline_run_id: str | None,
    n_paired: int | None,
    gold_sample_n: int | None,
    gold_n_crops: int | None,
) -> list[str]:
    """D16 — le recouvrement PARTIEL avec la baseline, rendu détectable.

    Le cas disjoint TOTAL est déjà couvert en amont (``paired_compare`` rend
    ``p_value=None, comparable=False`` sur intersection vide). Le recouvrement
    partiel, lui, est bien plus probable — deux ``--limit`` différents, deux
    états de cache, un run amputé — et il est **indiscernable** d'une égalité :
    1 crop commun sur 501 donne ``mcnemar_p=1.0, b=0, c=0``, exactement comme
    1958 crops parfaitement d'accord.

    Le seul moyen de les distinguer est le compte de paires. D'où la règle :
    **un run qui déclare une baseline sans dire sur combien de crops la
    comparaison a porté n'est pas promouvable**, et un recouvrement inférieur
    au périmètre du run non plus.

    ``n_paired`` se mesure sans ré-encoder avec :func:`paired_overlap`.
    """
    if baseline_run_id is None:
        return []
    if n_paired is None:
        return [
            f"apparie: run compare a {baseline_run_id} sans n_paired — le "
            "recouvrement n'est pas trace, un McNemar sur 1 crop commun est "
            "indiscernable d'une egalite sur tout le gold "
            "(store.encoder_bench.paired_overlap le mesure)"
        ]
    attendu = gold_sample_n if gold_sample_n is not None else gold_n_crops
    if attendu is None:
        return [
            f"apparie: {n_paired} crops communs avec {baseline_run_id}, mais le "
            "perimetre du run est inconnu (ni gold_sample_n ni gold_n_crops) — "
            "recouvrement invalidable"
        ]
    if n_paired != attendu:
        return [
            f"apparie: seulement {n_paired} crops communs avec "
            f"{baseline_run_id} sur les {attendu} du run — recouvrement "
            "partiel, la p-valeur ne porte pas sur le meme jeu"
        ]
    return []


def _p3_blockers(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str
) -> list[str]:
    """P3 — la fraîcheur des prédictions du couple, ou l'aveu qu'on l'ignore.

    ⚠️ Le point le plus important de ce module : **l'absence de preuve de
    fraîcheur bloque**. Version précédente : sans ligne dans
    ``dino_anchor_builds`` pour le couple, ``last_build`` valait NULL et tout
    le bloc était sauté — donc un encodeur CANDIDAT (celui qui n'a par
    construction jamais été bâti ni backfillé) sortait ``provisional=0``. Le
    garde s'auto-désarmait précisément sur les runs qu'il devait couvrir.

    Quatre états, un seul est un feu vert :

    * table(s) absente(s) → non mesurable, donc bloquant ;
    * aucun build tracé pour le couple → bloquant ;
    * build tracé mais zéro prédiction pour le couple → bloquant ;
    * prédictions antérieures au build → bloquant, avec leur compte.
    """
    hint = "relancer scripts.backfill_dino_predictions --force"
    couple = f"{anchors_kind}/{encoder_version}"

    missing = [
        t
        for t in ("dino_anchor_builds", "image_asset_dino_predictions")
        if not _table_exists(conn, t)
    ]
    if missing:
        return [
            f"P3: fraicheur non mesurable pour {couple} — table(s) absente(s) : "
            f"{', '.join(missing)} — base incomplete, ne rien promouvoir d'ici"
        ]

    last_build = conn.execute(
        "SELECT MAX(built_at) FROM dino_anchor_builds "
        " WHERE anchors_kind = ? AND encoder_version = ?",
        (anchors_kind, encoder_version),
    ).fetchone()[0]
    if not last_build:
        return [
            f"P3: aucun build trace dans dino_anchor_builds pour {couple} — "
            "la fraicheur des predictions ne peut pas etre prouvee — batir la "
            f"banque : {_HINT_BUILD.format(kind=anchors_kind)} ; puis {hint}"
        ]

    # `datetime()` des DEUX côtés : les deux colonnes ne portent pas le même
    # format et une comparaison de CHAÎNES les classe à l'envers.
    #
    #   image_asset_dino_predictions.computed_at → '2026-08-19 23:48:36'
    #   dino_anchor_builds.built_at              → '2026-08-19T14:36:14+00:00'
    #
    # L'espace vaut 0x20, le 'T' vaut 0x54 : toute prédiction paraît alors
    # ANTÉRIEURE à tout build du même jour, quelle que soit l'heure. Mesuré le
    # 2026-08-20 sur un pull frais du canonique, après le backfill P3 (12454
    # prédictions calculées de 23:20:42 à 23:48:36, build à 14:36:14, donc
    # postérieures de neuf heures) :
    #
    #   SUM(computed_at < built_at)                      → 12454   (faux)
    #   SUM(datetime(computed_at) < datetime(built_at))  → 0       (juste)
    #
    # Le sens de l'erreur sur-bloquait — jamais de faux « promouvable » — mais
    # rendait P3 IMPOSSIBLE à satisfaire : le garde bloquait à vie. Les deux
    # colonnes sont en UTC ; seule leur écriture diffère.
    n_total, n_stale = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(datetime(computed_at) < datetime(?)), 0) "
        "  FROM image_asset_dino_predictions "
        " WHERE anchors_kind = ? AND encoder_version = ?",
        (last_build, anchors_kind, encoder_version),
    ).fetchone()
    if not n_total:
        return [
            f"P3: aucune prediction {couple} en base alors qu'un build existe "
            f"({last_build}) — {hint}"
        ]
    if n_stale:
        return [
            f"P3: {n_stale} predictions {couple} anterieures au build courant "
            f"({last_build}) — {hint}"
        ]
    return []


def _p1_blockers(
    conn: sqlite3.Connection,
    anchors_kind: str,
    encoder_version: str,
    min_useful_classes: int,
) -> list[str]:
    """P1 — la couverture **utile** de la banque du couple.

    ⚠️ **Ce que ce garde mesure a changé le 2026-08-20, et c'est le point du
    lot.** Il comptait les classes ayant *au moins un* exemplaire, contre un
    seuil de **180** calibré quand la banque en affichait 182. On sait depuis
    que **64 de ces 182 n'avaient qu'un seul exemplaire** — le régime que la
    courbe held-out mesure SOUS le canonique seul (50,1 % contre 53,1 %). Le
    garde comparait donc la banque à un objectif fait d'un tiers de classes
    dégradantes, et il aurait bloqué le banc pour un rebuild qui, sur la
    couverture réelle, avait progressé. Sa mesure était juste, sa cible
    périmée — la forme la plus discrète de « un garde qui ne garde pas »
    (FINDINGS §8.9).

    Trois propriétés de la nouvelle mesure, dans l'ordre où elles comptent :

    * **elle ne dépend pas du plancher.** ``dino_thresholds.min_exemplars``
      décide de ce que le builder ÉCRIT ; :data:`USEFUL_MIN_REFS` décide de ce
      que le garde COMPTE. Retirer le plancher fait réapparaître des classes à
      un exemplaire dans la table — le compte, lui, ne bouge pas d'une ligne.
      C'est exactement le couplage qu'il ne faut pas refaire : un seuil dérivé
      du plancher se desserrerait au moment précis où il devrait tenir ;
    * **elle ne bouge pas quand le catalogue grandit.** Un ratio
      (classes couvertes / classes de la banque) tomberait à chaque commémo
      ajoutée par Numista, c'est-à-dire pour une raison qui n'est pas une
      régression de la banque ;
    * **son seuil est une ligne de non-régression mesurée**, pas une ambition
      (cf. :data:`DEFAULT_MIN_USEFUL_CLASSES`).

    Ce qu'elle n'est pas, et qu'il faudra peut-être : un garde **relatif** au
    build précédent, qui n'aurait aucune constante du tout. Il n'est pas
    mesurable aujourd'hui — ``dino_anchor_builds`` ne trace que des totaux
    (``n_classes``, ``n_rows``, ``n_canonical``, ``n_exemplars``), jamais la
    distribution, et ``dino_class_references`` est remplacée à chaque build. Il
    faudrait une colonne ``n_classes_utiles INTEGER`` sur
    ``dino_anchor_builds``, écrite par ``training.foundation.anchors`` avec le
    même prédicat que celui d'ici. Tant qu'elle n'existe pas, un garde relatif
    ne mesurerait rien — et « ce qui n'est pas mesurable bloque » ferait alors
    bloquer tous les runs, pour de mauvaises raisons.

    ⚠️ Même maladie que P3, déplacée : le compte ignorait ``encoder_version``
    alors que la ligne appartient au couple — sa clé primaire porte
    ``encoder_version`` depuis la migration 0010, et le DELETE de
    ``store.dino_references.replace_auto_references`` scope pareil
    (``encoder_version IN (?, '')``). ⚠️ Cette justification était FAUSSE quand
    elle a été écrite : elle citait ``UNIQUE(anchors_kind, encoder_version,
    class_id)``, un index **partiel aux canoniques**, pour justifier un compte
    sur les lignes ``fps`` — défaut M1, fermé par 0010. Deux symptômes mesurés,
    symétriques :

    * un candidat DINOv3 a **0** référence en base et P1 se taisait dès que le
      seuil était franchi par les lignes ``dinov2-vitl14`` — le garde validait
      la couverture d'un AUTRE encodeur ;
    * réciproquement, 60 classes ``fps`` arrivant pour le candidat faisaient
      passer P1 de « bloqué » à ``[]`` pour l'encodeur de PRODUCTION, dont la
      couverture n'avait pas bougé d'un pouce.

    Le prédicat est strict (``encoder_version = ?``), pas
    ``OR encoder_version IS NULL`` : les lignes NULL sont d'avant la migration
    0007 et n'appartiennent à aucun encodeur prouvable — les compter pour un
    candidat rouvrirait exactement le trou. Mesuré le 2026-08-19 sur
    ``ml/state/eurio.replica.db`` (``SELECT COALESCE(encoder_version,'<NULL>'),
    method, COUNT(DISTINCT class_id) FROM dino_class_references GROUP BY 1,2``)
    : aucune ligne NULL — 664 ``canonical`` et 125 ``fps``, toutes
    ``dinov2-vitl14``.

    Table absente = mesure impossible = bloquant, pour la même raison que P3 :
    un garde qui se tait quand il ne sait pas est un garde désarmé.
    """
    couple = f"{anchors_kind}/{encoder_version}"
    if not _table_exists(conn, "dino_class_references"):
        return [
            f"P1: couverture de la banque non mesurable pour {couple} — table "
            "dino_class_references absente"
        ]
    # Un seul passage rend les deux comptes : les classes couvertes, et celles
    # qui restent sous le palier. La seconde n'est pas décorative — sans elle,
    # « 124 classes couvertes » ne dit pas si la banque est pauvre ou si elle
    # est pleine de classes à un exemplaire, deux situations qui n'appellent
    # pas le même geste (scraper, ou juste rebâtir).
    n_utiles, n_sous_palier = conn.execute(
        "SELECT COALESCE(SUM(n >= ?), 0), COALESCE(SUM(n < ?), 0) FROM ("
        "  SELECT COUNT(*) AS n FROM dino_class_references "
        "   WHERE anchors_kind = ? AND encoder_version = ? AND method = 'fps' "
        "   GROUP BY class_id)",
        (USEFUL_MIN_REFS, USEFUL_MIN_REFS, anchors_kind, encoder_version),
    ).fetchone()
    if n_utiles >= min_useful_classes:
        return []
    reste = (
        f" ; {n_sous_palier} autres restent sous le palier de "
        f"{USEFUL_MIN_REFS} exemplaires et ne comptent pas "
        "(held-out : N=1 a 50,1 %, SOUS le canonique seul a 53,1 %)"
        if n_sous_palier
        else ""
    )
    return [
        f"P1: couverture utile insuffisante pour {couple} — {n_utiles} classes "
        f"a {USEFUL_MIN_REFS} exemplaires ou plus (attendu >= "
        f"{min_useful_classes}){reste} — enrichir (eurio-enrichment, "
        "eurio-review) puis rebatir : "
        + _HINT_BUILD.format(kind=anchors_kind)
    ]
