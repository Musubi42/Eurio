"""Connexion SQLite + bootstrap du schéma (socle partagé de Store).

Single-writer, multi-reader via WAL. Thread-safe via connexions par thread et
un write lock. Le swap de driver (libSQL, chunk 6) se localisera ici.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# schema.sql reste sous state/ jusqu'à la restructure (chunk 7).
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "state" / "schema.sql"


def _env_readonly() -> bool:
    """Lit ``EURIO_DB_READONLY`` (Direction A, C5). Vrai → tout Store construit
    sans ``read_only`` explicite s'ouvre en ``mode=ro`` (la DB locale est une
    réplique pull-ée du VPS, jamais un canonique). Source unique de vérité de
    la sémantique du flag — ``store.resolve_db_readonly()`` délègue ici."""
    return os.environ.get("EURIO_DB_READONLY", "").strip().lower() in (
        "1", "true", "yes",
    )


def _register_phash_udfs(conn: sqlite3.Connection) -> None:
    """Register UDFs for perceptual-hash dedup queries (D-07).

    SQLite < 3.43 has no native bit_count, and even on newer versions the
    function is not exposed by stock Python sqlite3 builds. We register two
    deterministic Python UDFs:

      - ``hamming(a, b)``     → Hamming distance between two 64-bit ints
      - ``phash_match(a,b,t)``→ 1 if Hamming(a, b) ≤ t, else 0

    Use ``phash_match(phash, ?, 4)`` in WHERE clauses for cluster lookups
    (cf. D-07 Hamming ≤ 4). Both functions tolerate NULL inputs by
    returning NULL / 0 respectively.
    """

    def _hamming(a: int | None, b: int | None) -> int | None:
        if a is None or b is None:
            return None
        # Python ints are arbitrary precision; mask to 64 bits to stay
        # consistent with the schema (`phash INTEGER` = signed 64-bit).
        x = (int(a) ^ int(b)) & 0xFFFFFFFFFFFFFFFF
        return x.bit_count()  # Python 3.10+

    def _phash_match(a: int | None, b: int | None, threshold: int) -> int:
        d = _hamming(a, b)
        if d is None:
            return 0
        return 1 if d <= int(threshold) else 0

    # `deterministic=True` lets SQLite use these in indexed expressions and
    # query optimizations (see https://www.sqlite.org/c3ref/create_function.html).
    conn.create_function("hamming", 2, _hamming, deterministic=True)
    conn.create_function("phash_match", 3, _phash_match, deterministic=True)


class StoreBase:
    def __init__(self, db_path: Path, *, read_only: bool | None = None) -> None:
        # C5 (Direction A) : sans choix explicite du caller, le mode vient de
        # ``EURIO_DB_READONLY`` — poser le flag sur une machine cliente (Mac/PC)
        # bascule TOUS les Store en ``mode=ro`` sans toucher les ~40 call-sites.
        # Le writer canonique (serving/server_serve.py) passe ``read_only=False``
        # explicite et reste immunisé contre le flag.
        if read_only is None:
            read_only = _env_readonly()
        self._db_path = Path(db_path)
        self._read_only = read_only
        # Filet Direction A : la réplique locale (`eurio.replica.db`) est écrasée
        # toutes les 120 s par `sqlite3_rsync` — l'ouvrir en écriture (flag
        # `EURIO_DB_READONLY` oublié) exécuterait le bootstrap dessus, la ferait
        # diverger du VPS et entrerait en collision avec le pull concurrent.
        # Écrire la réplique est TOUJOURS une erreur : on refuse au constructeur
        # plutôt que de corrompre en silence. Le writer canonique n'est pas
        # concerné (il pointe `/var/lib/eurio/eurio.db`, jamais la réplique).
        if not read_only and self._db_path.name == "eurio.replica.db":
            raise RuntimeError(
                f"Refus d'ouvrir la réplique {self._db_path.name} en écriture : "
                "poser EURIO_DB_READONLY=1 (la réplique est un miroir read-only du "
                "VPS, rafraîchi par sqlite3_rsync). Écrire dessus la ferait diverger "
                "et entrerait en collision avec le pull autopull."
            )
        if not read_only:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        self._bootstrap()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if self._read_only:
                # `mode=ro` : refuse toute écriture au niveau du driver SQLite
                # (pas seulement une convention côté appli). Pas de PRAGMA
                # d'écriture ici — journal_mode=WAL/synchronous modifient le
                # fichier et échouent ("attempt to write a readonly database")
                # sur une réplique pull-ée en mode non-WAL (post VACUUM INTO).
                conn = sqlite3.connect(
                    f"file:{self._db_path}?mode=ro",
                    uri=True,
                    check_same_thread=False,
                    isolation_level=None,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                )
            else:
                conn = sqlite3.connect(
                    self._db_path,
                    check_same_thread=False,
                    isolation_level=None,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                )
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            _register_phash_udfs(conn)
            self._local.conn = conn
        return conn

    def _bootstrap(self) -> None:
        if self._read_only:
            # Précondition Direction A (C5) : une réplique pull-ée depuis le
            # VPS a TOUJOURS un schéma à jour — le canonique applique son
            # propre bootstrap en écriture. En lecture seule on ne peut de
            # toute façon rien migrer (fichier `mode=ro`), donc no-op complet.
            return
        schema = _SCHEMA_PATH.read_text()
        with self._write_lock:
            conn = self._connection()
            # Pre-bootstrap: colonnes que les CREATE INDEX du schema référencent
            # mais qui n'existent pas sur les DB antérieures au chunk 9 (cascade
            # sync). Doit tourner AVANT executescript, sinon les CREATE INDEX
            # idx_*_storage_status plantent sur "no such column: storage_status".
            _STORAGE_STATUS_DECL = (
                "TEXT NOT NULL DEFAULT 'present' CHECK "
                "(storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'))"
            )
            for table in ("source_images", "image_assets"):
                # Fresh DB: la table n'existe pas encore — executescript la
                # créera avec storage_status déjà dans CREATE TABLE. Skip ALTER.
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not exists:
                    continue
                self._ensure_column(
                    conn,
                    table=table,
                    column="storage_status",
                    decl=_STORAGE_STATUS_DECL,
                )
            # Reaper précis recrop : `pid` (subprocess détaché) sur les DB
            # antérieures. Pas référencée par un index → ALTER simple, idempotent.
            # Fresh DB : cohort_jobs créée par executescript avec pid déjà dedans.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cohort_jobs'"
            ).fetchone():
                self._ensure_column(
                    conn, table="cohort_jobs", column="pid", decl="INTEGER"
                )
            # Progression du rebuild DINO (n_done/n_total) sur les DB qui ont
            # déjà la table. Pas d'index dessus → ALTER simple, idempotent.
            # Fresh DB : créées par executescript avec les colonnes dedans.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='dino_rebuild_jobs'"
            ).fetchone():
                for col in ("n_done", "n_total"):
                    self._ensure_column(
                        conn, table="dino_rebuild_jobs", column=col, decl="INTEGER"
                    )
            # Scan v2 du Jeu d'entraînement : composantes d'audit du verdict
            # (ancre canonique vs consensus intra-classe) + Phase 2 funnel
            # (denom-probe, sim absolue, suggestion typée) sur les DB qui ont
            # la table v1. Pas d'index dessus → ALTER simple, idempotent. Le
            # CHECK des valeurs vit dans schema.sql (fresh) ; l'ALTER pose la
            # colonne nue — le code garantit les valeurs.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='cohort_training_scan_results'"
            ).fetchone():
                for column, decl in (
                    ("anchor_sim", "REAL"),
                    ("consensus_sim", "REAL"),
                    ("intruder_reason", "TEXT"),
                    ("dismissed", "INTEGER NOT NULL DEFAULT 0"),
                    ("denom_score", "REAL"),
                    ("denom_verdict", "TEXT"),
                    ("abs_max_sim", "REAL"),
                    ("suggestion", "TEXT"),
                    ("suggestion_reason", "TEXT"),
                    ("suggestion_applied", "INTEGER NOT NULL DEFAULT 0"),
                    ("suggestion_applied_at", "TEXT"),
                ):
                    self._ensure_column(
                        conn, table="cohort_training_scan_results",
                        column=column, decl=decl,
                    )
            # Chantier variantes : les vues v_ebay_freshness* et
            # v_orphan_eurio_refs (recréées par executescript) référencent
            # coins.canonical_eurio_id → la colonne doit exister AVANT
            # executescript sur les DB antérieures. Fresh DB : coins n'existe
            # pas encore, executescript la créera avec les 3 colonnes.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='coins'"
            ).fetchone():
                for column, decl in (
                    ("variant_kind", "TEXT NOT NULL DEFAULT 'classic'"),
                    ("variant_label", "TEXT"),
                    ("canonical_eurio_id", "TEXT"),
                ):
                    self._ensure_column(conn, table="coins", column=column, decl=decl)
            # C0 pre-bootstrap : dédup discarded_listings AVANT executescript.
            # executescript re-crée le CREATE TABLE IF NOT EXISTS avec
            # UNIQUE(source, source_ref) — si des doublons existent, la
            # création de l'index UNIQUE planterait. On dédupe d'abord.
            # Guard : si la table n'existe pas encore (fresh DB), skip — elle
            # sera créée proprement avec la contrainte par executescript.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='discarded_listings'"
            ).fetchone():
                # Passe 1 : garder 1ère row par triplet (source, source_ref, reason).
                conn.execute(
                    """
                    DELETE FROM discarded_listings
                     WHERE id NOT IN (
                       SELECT MIN(id)
                         FROM discarded_listings
                        GROUP BY source, source_ref, reason
                     )
                    """
                )
                # Passe 2 : garder 1ère row par paire (source, source_ref).
                conn.execute(
                    """
                    DELETE FROM discarded_listings
                     WHERE id NOT IN (
                       SELECT MIN(id)
                         FROM discarded_listings
                        GROUP BY source, source_ref
                     )
                    """
                )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_discarded_listings_source_ref "
                    "ON discarded_listings(source, source_ref)"
                )
            # WS1 pre-bootstrap : review_queue.lane/lane_source AVANT executescript
            # car schema.sql crée idx_review_queue_lane_status ON (lane, status) —
            # planterait sur "no such column: lane" pour les DB antérieures. Fresh
            # DB : review_queue n'existe pas encore, executescript la créera avec
            # les colonnes dans le CREATE TABLE.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_queue'"
            ).fetchone():
                self._ensure_column(
                    conn, table="review_queue", column="lane",
                    decl="TEXT CHECK (lane IS NULL OR lane IN "
                         "('manual','auto_accept','ccproxy'))",
                )
                self._ensure_column(
                    conn, table="review_queue", column="lane_source",
                    decl="TEXT NOT NULL DEFAULT 'auto' "
                         "CHECK (lane_source IN ('auto','human'))",
                )
            # Model B (C6b) pre-bootstrap : run_id sur image_asset_dino_predictions
            # AVANT executescript, car schema.sql crée idx_dino_pred_run ON (run_id)
            # → planterait sur "no such column: run_id" pour les DB antérieures.
            # Fresh DB : la table n'existe pas, executescript la crée avec run_id.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='image_asset_dino_predictions'"
            ).fetchone():
                self._ensure_column(
                    conn, table="image_asset_dino_predictions", column="run_id",
                    decl="TEXT REFERENCES source_runs(id) ON DELETE SET NULL",
                )
                # Migration 0013 — même patron : sur une base antérieure la table
                # existe sans `stale_since`, `CREATE TABLE IF NOT EXISTS` ne
                # l'ajoute pas, et l'index partiel qui la référence échoue en
                # « no such column » AVANT que quoi que ce soit d'autre tourne.
                self._ensure_column(
                    conn, table="image_asset_dino_predictions",
                    column="stale_since", decl="TEXT",
                )
            # Migration 0007 — sur une base ANTÉRIEURE, `dino_class_references`
            # existe sans ces colonnes : `CREATE TABLE IF NOT EXISTS` ne les
            # ajoute pas, et l'index qui les référence échoue ensuite en
            # « no such column ». Même patron que run_id ci-dessus.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='dino_class_references'"
            ).fetchone():
                for column in ("encoder_version", "build_id", "source_path"):
                    self._ensure_column(
                        conn, table="dino_class_references", column=column,
                        decl="TEXT",
                    )
                # L'ancien index unique n'a pas l'encodeur : le laisser
                # empêcherait deux banques du même kind de coexister.
                conn.execute("DROP INDEX IF EXISTS idx_dino_class_refs_canonical")
            # Migration 0014 pre-bootstrap : `image_assets.eval_corpus` AVANT
            # executescript, car schema.sql crée l'index PARTIEL
            # idx_image_assets_eval_corpus ON (eval_corpus) WHERE eval_corpus IS
            # NOT NULL → sur une base antérieure il planterait en « no such
            # column: eval_corpus » avant que quoi que ce soit d'autre tourne.
            # Base fraîche : la table n'existe pas encore, executescript la crée
            # avec la colonne. Même patron que run_id / stale_since ci-dessus.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='image_assets'"
            ).fetchone():
                self._ensure_column(
                    conn, table="image_assets", column="eval_corpus", decl="TEXT",
                )
            conn.executescript(schema)
            # Seed source_registry (idempotent, INSERT OR IGNORE) : la FK
            # coin_source_refs.source → source_registry (ON DELETE RESTRICT) est
            # enforced dès le 1er run touchant price_aggregate. Sans ce seed au
            # bootstrap, toute DB fraîche crashe en IntegrityError opaque. Le seed
            # est une propriété du schéma, pas un rite manuel (F05 #3).
            from .source_registry_seed import seed_source_registry
            seed_source_registry(conn)
            self._ensure_column(
                conn,
                table="training_runs",
                column="aug_recipe_id",
                decl="TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL",
            )
            self._ensure_column(
                conn,
                table="training_staging",
                column="aug_recipe_id",
                decl="TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL",
            )
            self._ensure_column(
                conn,
                table="benchmark_runs",
                column="per_condition_json",
                decl="TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                conn,
                table="experiment_cohorts",
                column="status",
                decl="TEXT NOT NULL DEFAULT 'draft'",
            )
            self._ensure_column(
                conn,
                table="experiment_cohorts",
                column="frozen_at",
                decl="TEXT",
            )
            self._ensure_column(
                conn,
                table="experiment_iterations",
                column="augmentations_seed",
                decl="INTEGER",
            )
            self._ensure_column(
                conn,
                table="source_images",
                column="is_lot_suspected",
                decl="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="review_queue",
                column="kind",
                decl="TEXT NOT NULL DEFAULT 'single'",
            )
            # Chunk B 2026-05-25 — audit additive.
            self._ensure_column(
                conn,
                table="review_queue",
                column="decision_engine_version",
                decl="TEXT",
            )
            self._ensure_column(
                conn,
                table="review_queue",
                column="decision_metadata_json",
                decl="TEXT NOT NULL DEFAULT '{}'",
            )
            # WS1 lane/lane_source : ajoutés en PRE-bootstrap (avant executescript)
            # car schema.sql crée idx_review_queue_lane_status. Cf. plus haut.
            for column, decl in (
                ("target_country", "TEXT"),
                ("country_anchors_count", "INTEGER"),
                ("top_k_country_json", "TEXT"),
                ("top1_country_eurio_id", "TEXT"),
                ("top1_country_sim", "REAL"),
                ("top2_country_eurio_id", "TEXT"),
                ("top2_country_sim", "REAL"),
                ("country_spread", "REAL"),
                # Face detection (C7) : reverse-ness + marge vs obverse-ness.
                ("reverse_sim", "REAL"),
                ("face_margin", "REAL"),
                # Gate dénomination (C7 pilier 2) : score 2€-ness probe DINO+bimétal.
                ("denom_2eur_score", "REAL"),
            ):
                self._ensure_column(
                    conn,
                    table="image_asset_dino_predictions",
                    column=column,
                    decl=decl,
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dino_pred_top1_country "
                "ON image_asset_dino_predictions(top1_country_eurio_id)"
            )
            for column, decl in (
                ("download_endpoint", "TEXT"),
                ("download_status", "TEXT"),
                ("download_error", "TEXT"),
                ("download_http_status", "INTEGER"),
                ("crop_status", "TEXT"),
                ("crop_error", "TEXT"),
                ("n_crops_detected", "INTEGER"),
                ("route_decision", "TEXT"),
                ("route_reason", "TEXT"),
                # Détections persistées au scrape (detect_circles_multi complet :
                # cercles acceptés + rejetés). Lues telles quelles par la review
                # lot (Examination plate) → plus de recompute live au chargement.
                # JSON list[CircleDetection]. Cf. plan review-lot Chunk A.
                ("detections_json", "TEXT"),
            ):
                self._ensure_column(
                    conn,
                    table="source_images",
                    column=column,
                    decl=decl,
                )
            # Funnel ventilé sur discovery_searches (chunk 0 auto-validation) :
            # N0 itemSummaries → N1 post-groups → N2 post-theme → N3 kept.
            # `browse_url` (F3) : URL d'appel Browse exacte pour le débug.
            for column, decl in (
                ("n_summaries", "INTEGER"),
                ("n_after_groups", "INTEGER"),
                ("browse_url", "TEXT"),
            ):
                self._ensure_column(
                    conn,
                    table="discovery_searches",
                    column=column,
                    decl=decl,
                )
            # eBay multi-marketplace (B1). marketplace = mkt qui a yieldé
            # le listing/search en premier ; marketplace_found_json = liste
            # complète (dédup cross-mkt). Cf. docs/sources-refacto/
            # ebay-multi-marketplace/schema.md.
            for table, column, decl in (
                ("source_images", "marketplace", "TEXT"),
                ("source_images", "marketplace_found_json", "TEXT"),
                ("discovery_searches", "marketplace", "TEXT"),
                ("discarded_listings", "marketplace", "TEXT"),
                # i18n bootstrap (Numista scrape + LLM translation). Cf.
                # docs/sources-refacto/ebay-multi-marketplace/i18n-strategy.md.
                # 'confidence' = 'canon' (scraped) | 'llm' | 'manual'.
                # 'model' carries the LLM id for confidence='llm', else NULL.
                ("coin_names_i18n", "confidence",
                 "TEXT NOT NULL DEFAULT 'canon'"),
                ("coin_names_i18n", "model", "TEXT"),
            ):
                self._ensure_column(conn, table=table, column=column, decl=decl)
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_source_images_marketplace "
                "ON source_images(marketplace) WHERE marketplace IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_discovery_searches_marketplace "
                "ON discovery_searches(marketplace) WHERE marketplace IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_discarded_listings_marketplace "
                "ON discarded_listings(marketplace) WHERE marketplace IS NOT NULL",
            ):
                conn.execute(index_sql)
            # Verdict vs target_eurio_id (chunk 6 auto-validation).
            # CHECK column-level avec NULL autorisé pour les rows backfillées
            # avant chunk 6 ou sans target connu.
            for column, decl in (
                (
                    "vs_target_verdict",
                    "TEXT CHECK (vs_target_verdict IS NULL "
                    "OR vs_target_verdict IN "
                    "('convergent','partial','absent','contradict'))",
                ),
                ("contradictions_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("convergences_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                self._ensure_column(
                    conn,
                    table="listing_text_signals",
                    column=column,
                    decl=decl,
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_listing_text_signals_verdict "
                "ON listing_text_signals(vs_target_verdict)"
            )
            # Pipeline prix & état (chunk C1). Sur source_images : signaux
            # de vélocité (date de mise en ligne, quantité vendue) pour la
            # pondération de l'agrégation prix. Sur listing_text_signals :
            # taxonomie du listing (single/lot/coffret/graded_slab) + état
            # numismatique, extraits du titre par l'étape text_signals (C2).
            # NULL sur les rows antérieures. Cf. docs/sources-refacto/
            # ebay-multi-marketplace/.
            for table, column, decl in (
                ("source_images", "listing_origin_date", "TEXT"),
                ("source_images", "sold_qty", "INTEGER"),
                ("listing_text_signals", "listing_kind",
                 "TEXT CHECK (listing_kind IS NULL OR listing_kind IN "
                 "('single','lot','coffret','graded_slab'))"),
                ("listing_text_signals", "listing_kind_confidence", "REAL"),
                ("listing_text_signals", "condition_normalized",
                 "TEXT CHECK (condition_normalized IS NULL OR "
                 "condition_normalized IN ('UNC','TTB','TB','unknown'))"),
                ("listing_text_signals", "condition_confidence", "REAL"),
            ):
                self._ensure_column(conn, table=table, column=column, decl=decl)
            # ─── Harmonisation des données (docs/data-harmonization/) ──────
            # Colonnes canoniques + cycle de vie sur `coins`. Les DB fraîches
            # les ont via schema.sql ; ici on rattrape les DB existantes. Les
            # index sur ces colonnes suivent : executescript tourne AVANT ces
            # ALTER et ne peut donc pas les créer.
            for column, decl in (
                ("ref_source", "TEXT"),
                ("ref_native_id", "TEXT"),
                ("currency", "TEXT NOT NULL DEFAULT 'EUR'"),
                ("collector_only", "INTEGER NOT NULL DEFAULT 0"),
                ("design_description", "TEXT"),
                ("mintage", "INTEGER"),
                ("mintage_source", "TEXT"),
                ("design_group_id",
                 "TEXT REFERENCES design_groups(id) ON DELETE SET NULL"),
                ("status",
                 "TEXT NOT NULL DEFAULT 'referenced' "
                 "CHECK (status IN ('referenced','trained'))"),
                ("status_computed_at", "TEXT"),
                ("needs_review", "INTEGER NOT NULL DEFAULT 0"),
                ("review_reason", "TEXT"),
                ("last_seen_in_catalog_at", "TEXT"),
                ("updated_at", "TEXT"),
            ):
                self._ensure_column(conn, table="coins", column=column, decl=decl)
            self._ensure_column(
                conn,
                table="image_assets",
                column="origin",
                decl="TEXT CHECK (origin IS NULL OR "
                "origin IN ('canonical','collected','synthetic'))",
            )
            # Coin richness P.3b : split source/method on i18n + aliases.
            # `source` reste TEXT libre tant que le recreate P.6 n'a pas posé
            # la FK source_registry. `method` ajouté pour capturer la méthode
            # de dérivation ('llm_v1', 'acronym', etc.) séparément.
            self._ensure_column(
                conn, table="coin_names_i18n", column="method", decl="TEXT",
            )
            self._ensure_column(
                conn, table="coin_aliases", column="method", decl="TEXT",
            )
            # Coin richness P.8a : colonnes Supabase rapatriées sur `coins`.
            # personal_owned/lent_to_me sont des flags admin (peu utilisés,
            # remplaceront le coffre utilisateur en Phase 5+). series_id FK
            # vers coin_series (table créée par schema.sql en P.8a).
            self._ensure_column(
                conn, table="coins", column="personal_owned",
                decl="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn, table="coins", column="lent_to_me",
                decl="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn, table="coins", column="series_id", decl="TEXT",
            )
            # Chantier crop-quality-overhaul (2026-06-03) : colonnes de tilt
            # pour image_assets. Calculées par crop_tilt_backfill_db.py.
            for _col, _decl in (
                ("tilt_deg",         "REAL"),
                ("axis_ratio",       "REAL"),
                ("tilt_trustworthy", "INTEGER DEFAULT 0"),
                # Gate dénomination (C7 pilier 2) : verdict binaire 2€ vs junk,
                # miroir de `face`. Écrit si NULL (anti-clobber labels humains).
                ("denom", "TEXT"),
            ):
                self._ensure_column(conn, table="image_assets", column=_col, decl=_decl)
            # C2 cohort-pipeline : flag is_rescue_candidate pré-calculé.
            # 1 = commémo valide dans le mauvais bucket (récupérable),
            # 0 = vrai bruit (noise_title/below_face/above_extreme/non_eur).
            self._ensure_column(
                conn,
                table="discarded_listings",
                column="is_rescue_candidate",
                decl="INTEGER",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_discarded_listings_rescue "
                "ON discarded_listings(is_rescue_candidate) "
                "WHERE is_rescue_candidate IS NOT NULL"
            )
            # Backfill des rows existantes (idempotent : WHERE is_rescue_candidate IS NULL).
            conn.execute(
                """
                UPDATE discarded_listings
                   SET is_rescue_candidate = CASE
                         WHEN reason = 'theme_mismatch'
                              OR reason LIKE 'commemo_in_standard_run:%' THEN 1
                         WHEN reason IN (
                              'noise_title','below_face','above_extreme','non_eur'
                         ) THEN 0
                         ELSE NULL
                       END
                 WHERE is_rescue_candidate IS NULL
                """
            )
            # C1 cohort-pipeline : rescue commémo rétroactif. Colonne pour
            # lier un discard rescapé à la source_image correspondante sans
            # reparsing de la colonne `reason`.
            self._ensure_column(
                conn,
                table="discarded_listings",
                column="rescued_source_image_id",
                decl="TEXT",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_discarded_listings_rescued "
                "ON discarded_listings(rescued_source_image_id) "
                "WHERE rescued_source_image_id IS NOT NULL"
            )
            # ─── C0 — Backfill discovery_log (cohort-pipeline) ─────────────
            # Dédup + index UNIQUE posés en pre-bootstrap (avant executescript).
            # Ici : backfill discovery_log pour les rejets sans entrée existante.
            # INSERT OR IGNORE = idempotent. Rows fantômes (last_run_id=NULL)
            # — leur rôle est uniquement de bloquer le re-fetch futur.
            conn.execute(
                """
                INSERT OR IGNORE INTO discovery_log (id, source, source_ref, pipeline_state)
                SELECT hex(randomblob(16)), source, source_ref, 'rejected'
                  FROM discarded_listings dl
                 WHERE NOT EXISTS (
                   SELECT 1 FROM discovery_log dlog
                    WHERE dlog.source = dl.source
                      AND dlog.source_ref = dl.source_ref
                 )
                """
            )
            # Index NON unique : un numista_id de circulation est partagé par
            # N millésimes (ex. nid 135 = 23 pièces) → (ref_source,ref_native_id)
            # n'est pas unique. L'unicité réelle relève de la génération (Chunk 2).
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_coins_ref "
                "ON coins(ref_source, ref_native_id)",
                "CREATE INDEX IF NOT EXISTS idx_coins_status ON coins(status)",
                "CREATE INDEX IF NOT EXISTS idx_coins_design_group "
                "ON coins(design_group_id) WHERE design_group_id IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_coins_needs_review "
                "ON coins(needs_review) WHERE needs_review = 1",
                "CREATE INDEX IF NOT EXISTS idx_coins_canonical "
                "ON coins(canonical_eurio_id) WHERE canonical_eurio_id IS NOT NULL",
            ):
                conn.execute(index_sql)
            # ─── Model B — backfill source_image_runs (parité A↔B) ─────────
            # `source_image_runs` (lien M:N run↔image) est créée par schema.sql,
            # mais le CREATE ne peuple pas les DB existantes. Reconstruit les
            # liens depuis les deux sources d'attribution : source_images.run_id
            # (first-seen) + image_assets.run_id (récupère les liens HISTORIQUES
            # qu'un re-scrape avait volés — l'asset garde le run qui l'a créé).
            # Gardé : ne tourne que si la table est vide (idempotent, one-shot).
            already_linked = conn.execute(
                "SELECT 1 FROM source_image_runs LIMIT 1"
            ).fetchone()
            if already_linked is None:
                # Filtre anti-orphelins : ne lier que les rows dont les cibles FK
                # existent (le canonique traîne ~503 violations FK historiques
                # image_assets→source_runs, dette séparée C8). FK ON ici → un
                # INSERT orphelin lèverait ; on les exclut proprement.
                conn.execute(
                    "INSERT OR IGNORE INTO source_image_runs (source_image_id, run_id) "
                    "SELECT id, run_id FROM source_images "
                    " WHERE run_id IS NOT NULL "
                    "   AND run_id IN (SELECT id FROM source_runs)"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO source_image_runs (source_image_id, run_id) "
                    "SELECT ia.source_image_id, ia.run_id FROM image_assets ia "
                    " WHERE ia.run_id IS NOT NULL "
                    "   AND ia.run_id IN (SELECT id FROM source_runs) "
                    "   AND ia.source_image_id IN (SELECT id FROM source_images)"
                )
            # Live-tests verdict eq (design_group mesh). Strict is_correct
            # (eurio_id exact) ne peut jamais matcher un label design_group →
            # le §5 doit lire is_correct_eq, recomputé server-side au sync.
            # Pas d'index dessus → ALTER simple. Fresh DB : déjà dans schema.sql.
            self._ensure_column(
                conn,
                table="iteration_live_tests",
                column="is_correct_eq",
                decl="INTEGER NOT NULL DEFAULT 0",
            )
            n_coins = conn.execute("SELECT count(*) AS n FROM coins").fetchone()["n"]
            if n_coins == 0:
                logger.warning(
                    "coins table is empty — run `go-task ml:bootstrap-coins` to mirror "
                    "eurio_referential.json (required for v_ebay_freshness and freshness queue)"
                )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        decl: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {r["name"] for r in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    @contextmanager
    def _writing(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def wal_checkpoint(self) -> None:
        with self._write_lock:
            self._connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")
