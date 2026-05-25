"""Writer SQLite pour les rows produites par ``numista_transforms``.

Sous-chunk P.7c.3 du chantier coin-richness. Prend une connexion sqlite3
(passed-in pour permettre transaction + rollback côté caller) et applique
les UPSERT idempotents sur les 10 tables cibles.

Doctrine SQLite-only + provenance first-class :
  - Tous les inserts portent ``source='numista_api'`` (vocabulaire registry).
  - Tables source-aware (coin_observations, coin_market_quotes, …) ont la
    FK source → source_registry enforced post-P.6 wipe.

Idempotence par table (UNIQUE/PK constraints) :

| Table                    | Conflict target                                        |
|--------------------------|--------------------------------------------------------|
| coins                    | PK eurio_id                                            |
| coin_source_refs         | UNIQUE (target_kind, target_id, source)                |
| coin_cross_refs          | PK (eurio_id, ref_type)                                |
| coin_mint_releases       | PK id (=`{eurio_id}/numista-{iid}`)                   |
| mint_release_prices      | UNIQUE (mint_release_id, source, grade_raw, fetched_at)|
| coin_market_quotes       | UNIQUE (source, eurio_id, period_start, condition_raw) |
| coin_canonical_images    | PK (eurio_id, source, role)                            |
| coin_credits             | PK (eurio_id, role, name, source)                      |
| coin_observations        | UNIQUE (eurio_id, source, observation_type)            |
| design_groups            | PK id                                                  |
| coin_variants            | PK id                                                  |

mint_release_prices NE fait PAS d'UPDATE — chaque fetch à un timestamp
distinct ajoute des rows historisées (cf. ROADMAP §9 "idempotence
refetch" — INSERT OR REPLACE sur (target, fact_type, source) qui pour les
prices est par-fetched_at).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class WriteStats:
    coins: int = 0
    source_refs: int = 0
    cross_refs: int = 0
    mint_releases: int = 0
    prices: int = 0
    market_quotes: int = 0
    images: int = 0
    credits: int = 0
    observations: int = 0
    design_groups: int = 0
    variants: int = 0


class NumistaWriter:
    """Applique les rows produites par numista_transforms sur une connexion
    sqlite3 (autocommit ou transaction selon caller).

    Le caller est responsable de :
      - PRAGMA foreign_keys=ON (Store le fait par défaut)
      - Wrap en transaction si idempotence transactionnelle souhaitée
      - close() de la connexion
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.stats = WriteStats()

    # ─── Helpers ───────────────────────────────────────────────────────

    def _upsert_one(self, sql: str, params: tuple) -> None:
        self.conn.execute(sql, params)

    def _upsert_many(self, sql: str, params_list: list[tuple]) -> int:
        if not params_list:
            return 0
        self.conn.executemany(sql, params_list)
        return len(params_list)

    # ─── coins ─────────────────────────────────────────────────────────

    def write_coin(self, row: dict) -> None:
        sql = """
        INSERT INTO coins (
          eurio_id, country, country_name, year, face_value, currency,
          is_commemorative, theme, numista_id, design_description,
          design_group_id, ref_source, ref_native_id
        ) VALUES (
          :eurio_id, :country, :country_name, :year, :face_value, :currency,
          :is_commemorative, :theme, :numista_id, :design_description,
          :design_group_id, :ref_source, :ref_native_id
        )
        ON CONFLICT (eurio_id) DO UPDATE SET
          country_name = excluded.country_name,
          theme = excluded.theme,
          numista_id = excluded.numista_id,
          design_description = excluded.design_description,
          design_group_id = excluded.design_group_id,
          ref_source = excluded.ref_source,
          ref_native_id = excluded.ref_native_id,
          updated_at = datetime('now')
        """
        self.conn.execute(sql, row)
        self.stats.coins += 1

    # ─── coin_source_refs ──────────────────────────────────────────────

    def write_source_ref(self, row: dict) -> None:
        sql = """
        INSERT INTO coin_source_refs
          (target_kind, target_id, source, source_native_id, source_url)
        VALUES
          (:target_kind, :target_id, :source, :source_native_id, :source_url)
        ON CONFLICT (target_kind, target_id, source) DO UPDATE SET
          source_native_id = excluded.source_native_id,
          source_url = excluded.source_url,
          fetched_at = datetime('now')
        """
        self.conn.execute(sql, row)
        self.stats.source_refs += 1

    # ─── coin_cross_refs ───────────────────────────────────────────────

    def write_cross_refs(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_cross_refs (eurio_id, ref_type, ref_value)
        VALUES (:eurio_id, :ref_type, :ref_value)
        ON CONFLICT (eurio_id, ref_type) DO UPDATE SET
          ref_value = excluded.ref_value
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.cross_refs += 1

    # ─── coin_mint_releases ────────────────────────────────────────────

    def write_mint_releases(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_mint_releases
          (id, parent_type_id, mint_year, mint_id, issue_type, notes)
        VALUES
          (:id, :parent_type_id, :mint_year, :mint_id, :issue_type, :notes)
        ON CONFLICT (id) DO UPDATE SET
          mint_id = excluded.mint_id,
          issue_type = excluded.issue_type,
          notes = excluded.notes,
          updated_at = datetime('now')
        """
        for row in rows:
            # Strip our private "_*" carriers (mintage, mint_letter, iid)
            row_db = {k: v for k, v in row.items() if not k.startswith("_")}
            self.conn.execute(sql, row_db)
            self.stats.mint_releases += 1

    # ─── mint_release_prices ───────────────────────────────────────────

    def write_prices(self, rows: list[dict]) -> None:
        """Pas d'UPDATE : chaque fetched_at distinct = nouvelle row historisée.
        UNIQUE (mint_release_id, source, grade_raw, fetched_at) protège contre
        re-runs trop rapides (timestamps identiques)."""
        sql = """
        INSERT OR IGNORE INTO mint_release_prices
          (mint_release_id, source, grade_raw, grade_eurio, price, currency, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = [(r["mint_release_id"], r["source"], r["grade_raw"],
                   r["grade_eurio"], r["price"], r["currency"], r["fetched_at"])
                  for r in rows]
        if params:
            self.conn.executemany(sql, params)
            self.stats.prices += len(params)

    # ─── coin_market_quotes ────────────────────────────────────────────

    def write_market_quotes(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_market_quotes
          (id, eurio_id, source, condition_raw, condition_normalized, currency,
           p10, p50, p90, sample_size, period_start, period_end)
        VALUES
          (:id, :eurio_id, :source, :condition_raw, :condition_normalized, :currency,
           :p10, :p50, :p90, :sample_size, :period_start, :period_end)
        ON CONFLICT (source, eurio_id, period_start, condition_raw) DO UPDATE SET
          p10 = excluded.p10,
          p50 = excluded.p50,
          p90 = excluded.p90,
          sample_size = excluded.sample_size,
          period_end = excluded.period_end,
          fetched_at = datetime('now')
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.market_quotes += 1

    # ─── coin_canonical_images ─────────────────────────────────────────

    def write_images(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_canonical_images (eurio_id, source, role, url, local_path)
        VALUES (:eurio_id, :source, :role, :url, :local_path)
        ON CONFLICT (eurio_id, source, role) DO UPDATE SET
          url = excluded.url,
          local_path = excluded.local_path
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.images += 1

    # ─── coin_credits ──────────────────────────────────────────────────

    def write_credits(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_credits (eurio_id, role, name, source, source_ref, position)
        VALUES (:eurio_id, :role, :name, :source, :source_ref, :position)
        ON CONFLICT (eurio_id, role, name, source) DO UPDATE SET
          source_ref = excluded.source_ref,
          position = excluded.position
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.credits += 1

    # ─── coin_observations ─────────────────────────────────────────────

    def write_observations(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_observations
          (eurio_id, source, observation_type, payload_json)
        VALUES
          (:eurio_id, :source, :observation_type, :payload_json)
        ON CONFLICT (eurio_id, source, observation_type) DO UPDATE SET
          payload_json = excluded.payload_json,
          recorded_at = datetime('now')
        """
        for row in rows:
            # coin_observations actuelle (pré-P.6 wipe) n'a pas la colonne
            # source_ref. Post-wipe elle l'aura. On retire pour compat.
            row_db = {k: v for k, v in row.items() if k != "source_ref"}
            self.conn.execute(sql, row_db)
            self.stats.observations += 1

    # ─── design_groups ─────────────────────────────────────────────────

    def write_design_group(self, row: dict | None) -> None:
        if not row:
            return
        sql = """
        INSERT INTO design_groups (id, designation, description)
        VALUES (:id, :designation, :description)
        ON CONFLICT (id) DO UPDATE SET
          designation = excluded.designation,
          description = excluded.description,
          updated_at = datetime('now')
        """
        self.conn.execute(sql, row)
        self.stats.design_groups += 1

    # ─── coin_variants ─────────────────────────────────────────────────

    def write_variant(self, row: dict | None) -> None:
        if not row:
            return
        sql = """
        INSERT INTO coin_variants
          (id, parent_type_id, finish, obverse_url, reverse_url, notes)
        VALUES
          (:id, :parent_type_id, :finish, :obverse_url, :reverse_url, :notes)
        ON CONFLICT (id) DO UPDATE SET
          finish = excluded.finish,
          obverse_url = excluded.obverse_url,
          reverse_url = excluded.reverse_url,
          notes = excluded.notes,
          updated_at = datetime('now')
        """
        self.conn.execute(sql, row)
        self.stats.variants += 1

    # ─── Orchestration full bundle ─────────────────────────────────────

    def write_bundle(
        self, *, slug, payload: dict, issues: list[dict],
        prices_by_iid: dict[int, dict], mint_resolver,
    ) -> None:
        """Pipeline complet pour un Type : appelle les transforms puis chaque
        write_* dans le bon ordre (FK : coins avant tout, mint_releases avant
        prices)."""
        from referential.numista_transforms import (
            coin_canonical_image_rows, coin_credit_rows, coin_cross_ref_rows,
            coin_market_quote_rows, coin_observation_rows, coin_row,
            coin_source_ref_row, coin_variant_row, design_group_row,
            mint_release_price_rows, mint_release_rows,
        )

        # 1. design_groups d'abord (FK target depuis coins.design_group_id)
        self.write_design_group(design_group_row(slug))

        # 2. coins (FK target depuis tout le reste)
        self.write_coin(coin_row(slug, payload))

        # 3. source_ref + cross_refs + images + credits + observations + variant
        self.write_source_ref(coin_source_ref_row(slug, payload))
        self.write_cross_refs(coin_cross_ref_rows(slug, payload))
        self.write_images(coin_canonical_image_rows(slug, payload))
        self.write_credits(coin_credit_rows(slug, payload))
        self.write_observations(coin_observation_rows(slug, payload))
        self.write_variant(coin_variant_row(slug, payload))

        # 4. mint_releases (FK depuis prices)
        mr_rows = mint_release_rows(slug, issues, mint_resolver)
        self.write_mint_releases(mr_rows)

        # 5. prices par mint_release. Le mapping iid → mint_release_id est
        # dans mr_rows (via _numista_iid privé).
        iid_to_release_id = {r["_numista_iid"]: r["id"] for r in mr_rows}
        all_prices: list[dict] = []
        for iid, prices_payload in prices_by_iid.items():
            release_id = iid_to_release_id.get(iid)
            if not release_id:
                continue
            all_prices.extend(mint_release_price_rows(release_id, prices_payload))
        self.write_prices(all_prices)

        # 6. coin_market_quotes Type-level agrégé
        self.write_market_quotes(coin_market_quote_rows(slug.eurio_id, prices_by_iid))
