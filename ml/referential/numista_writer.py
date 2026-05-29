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
    mint_release_observations: int = 0
    prices: int = 0
    market_quotes: int = 0
    images: int = 0
    credits: int = 0
    observations: int = 0
    design_groups: int = 0
    variants: int = 0
    i18n_names: int = 0
    topics: int = 0


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
          design_group_id, ref_source, ref_native_id,
          variant_kind, variant_label, canonical_eurio_id
        ) VALUES (
          :eurio_id, :country, :country_name, :year, :face_value, :currency,
          :is_commemorative, :theme, :numista_id, :design_description,
          :design_group_id, :ref_source, :ref_native_id,
          :variant_kind, :variant_label, :canonical_eurio_id
        )
        ON CONFLICT (eurio_id) DO UPDATE SET
          country_name = excluded.country_name,
          theme = excluded.theme,
          numista_id = excluded.numista_id,
          design_description = excluded.design_description,
          design_group_id = excluded.design_group_id,
          ref_source = excluded.ref_source,
          ref_native_id = excluded.ref_native_id,
          variant_kind = excluded.variant_kind,
          variant_label = excluded.variant_label,
          canonical_eurio_id = excluded.canonical_eurio_id,
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

    # ─── mint_release_observations ─────────────────────────────────────

    def write_mint_release_observations(self, rows: list[dict]) -> None:
        """Mintage (et futurs facts par millésime) en provenance-first.

        UPSERT idempotent sur UNIQUE (mint_release_id, fact_type, source) —
        même pattern que write_observations (Type-level)."""
        sql = """
        INSERT INTO mint_release_observations
          (mint_release_id, fact_type, value_json, source)
        VALUES
          (:mint_release_id, :fact_type, :value_json, :source)
        ON CONFLICT (mint_release_id, fact_type, source) DO UPDATE SET
          value_json = excluded.value_json,
          observed_at = datetime('now')
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.mint_release_observations += 1

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

    # ─── Résolution nid → eurio_id (groupage variantes via related_types) ─

    def resolve_eurio_for_nid(self, nid: int | None, cache_dir=None) -> str | None:
        """eurio_id du Type canonique pour un ``numista_id`` donné.

        1) ligne ``coins`` canonique (canonical_eurio_id IS NULL) portant ce nid ;
        2) sinon, si ``cache_dir`` fourni, résout depuis le payload caché
           (``{cache_dir}/{nid}/type.json``) — utile quand le frère n'est pas
           encore écrit dans le même run.
        """
        if not nid:
            return None
        row = self.conn.execute(
            "SELECT eurio_id FROM coins WHERE numista_id = ? "
            "AND canonical_eurio_id IS NULL ORDER BY eurio_id LIMIT 1",
            (nid,),
        ).fetchone()
        if row:
            return row[0]
        if cache_dir is not None:
            import json
            from pathlib import Path

            from referential.numista_eurio_id import eurio_id_from_numista_payload
            p = Path(cache_dir) / str(nid) / "type.json"
            if p.exists():
                r = eurio_id_from_numista_payload(json.loads(p.read_text()))
                return r.eurio_id if r else None
        return None

    # ─── Désambiguïsation eurio_id (tiebreak variantes même finish) ─────

    def unique_eurio_id(self, base_eurio_id: str, numista_id: int) -> str:
        """Garantit l'unicité du PK eurio_id quand 2+ nids du même groupe
        partagent le même variant_kind (ex. deux « coloured » de la même pièce).

        Retourne ``base_eurio_id`` s'il est libre OU déjà possédé par ce nid ;
        sinon ``base-2``, ``base-3``… (compteur). Idempotent : la propriété est
        vérifiée via ``numista_id`` → un re-run retrouve sa propre ligne. Cas
        rare (aucune occurrence sur la zone euro actuelle) — filet anti-perte.
        """
        cur = self.conn.execute(
            "SELECT numista_id FROM coins WHERE eurio_id = ?", (base_eurio_id,)
        ).fetchone()
        if cur is None or cur[0] == numista_id:
            return base_eurio_id
        k = 2
        while True:
            cand = f"{base_eurio_id}-{k}"
            cur = self.conn.execute(
                "SELECT numista_id FROM coins WHERE eurio_id = ?", (cand,)
            ).fetchone()
            if cur is None or cur[0] == numista_id:
                return cand
            k += 1

    # ─── coin_variants — DÉPRÉCIÉ (chantier variantes) ──────────────────
    # Les variantes sont désormais des pièces coins first-class. Conservé
    # le temps de la migration (migrate_coin_variants_to_coins.py) ; plus
    # appelé par write_bundle.

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

    # ─── coin_topics ──────────────────────────────────────────────────

    def write_topics(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_topics
          (eurio_id, source, lang, topic, method, model, confidence)
        VALUES
          (:eurio_id, :source, :lang, :topic, :method, :model, :confidence)
        ON CONFLICT (eurio_id, source, lang) DO UPDATE SET
          topic      = excluded.topic,
          method     = excluded.method,
          model      = excluded.model,
          confidence = excluded.confidence,
          fetched_at = datetime('now')
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.topics += 1

    # ─── coin_names_i18n ───────────────────────────────────────────────

    def write_i18n_names(self, rows: list[dict]) -> None:
        sql = """
        INSERT INTO coin_names_i18n
          (eurio_id, lang, title, source, method, model, confidence)
        VALUES
          (:eurio_id, :lang, :title, :source, :method, :model, :confidence)
        ON CONFLICT (eurio_id, lang) DO UPDATE SET
          title      = excluded.title,
          source     = excluded.source,
          method     = excluded.method,
          model      = excluded.model,
          confidence = excluded.confidence,
          fetched_at = datetime('now')
        """
        for row in rows:
            self.conn.execute(sql, row)
            self.stats.i18n_names += 1

    # ─── Orchestration full bundle ─────────────────────────────────────

    def write_bundle(
        self, *, slug, payload: dict, issues: list[dict],
        prices_by_iid: dict[int, dict], mint_resolver,
        payload_fr: dict | None = None,
        cache_dir=None,
    ) -> None:
        """Pipeline complet pour un Type : appelle les transforms puis chaque
        write_* dans le bon ordre (FK : coins avant tout, mint_releases avant
        prices).

        ``cache_dir`` (optionnel) : permet de résoudre le canonique d'une
        variante via ``related_types`` même si le frère n'est pas encore en DB
        (lecture du payload caché). DB-only si absent."""
        from dataclasses import replace

        from referential.numista_transforms import (
            coin_canonical_image_rows, coin_credit_rows, coin_cross_ref_rows,
            coin_market_quote_rows, coin_name_i18n_rows, coin_observation_rows,
            coin_row, coin_source_ref_row, coin_topic_rows,
            design_group_row, mint_release_observation_rows,
            mint_release_price_rows, mint_release_rows,
        )

        review_reason: str | None = None
        if slug.canonical_eurio_id is not None:
            # 0a. Groupage par related_types (source primaire) : le slug de base
            #     ne suffit pas car le commemorated_topic diffère souvent entre
            #     canonique et variante. On résout le vrai canonique via les
            #     Types frères du payload.
            from referential.numista_eurio_id import related_canonical_nid
            nid_can, ambiguous = related_canonical_nid(payload)
            resolved = self.resolve_eurio_for_nid(nid_can, cache_dir) if nid_can else None
            if resolved and resolved != slug.eurio_id:
                slug = replace(slug, canonical_eurio_id=resolved)
            elif not resolved:
                # Pas de canonique résoluble → garde le base_slug en fallback
                # mais flag pour revue éditoriale.
                review_reason = "variant_canonical_unresolved"
            if ambiguous:
                review_reason = "variant_canonical_ambiguous"

            # 0b. Tiebreak : si 2+ nids du même groupe partagent le même
            #     variant_kind, désambiguïse le PK eurio_id (base-2…) AVANT de
            #     construire les rows filles (qui pointent slug.eurio_id).
            unique = self.unique_eurio_id(slug.eurio_id, int(payload["id"]))
            if unique != slug.eurio_id:
                slug = replace(slug, eurio_id=unique)

        # 1. design_groups d'abord (FK target depuis coins.design_group_id)
        self.write_design_group(design_group_row(slug))

        # 2. coins (FK target depuis tout le reste)
        self.write_coin(coin_row(slug, payload))
        if review_reason:
            self.conn.execute(
                "UPDATE coins SET needs_review = 1, review_reason = ? "
                "WHERE eurio_id = ?",
                (review_reason, slug.eurio_id),
            )

        # 3. source_ref + cross_refs + images + credits + observations + i18n
        #    (chantier variantes : plus de write_variant — la variante EST une
        #    pièce coins first-class, écrite en 2. ; coin_variants déprécié)
        self.write_source_ref(coin_source_ref_row(slug, payload))
        self.write_cross_refs(coin_cross_ref_rows(slug, payload))
        self.write_images(coin_canonical_image_rows(slug, payload))
        self.write_credits(coin_credit_rows(slug, payload))
        self.write_observations(coin_observation_rows(slug, payload))
        self.write_i18n_names(coin_name_i18n_rows(slug, payload, payload_fr))
        self.write_topics(coin_topic_rows(slug, payload, payload_fr))

        # 4. mint_releases (FK depuis prices) + leurs observations (mintage).
        #
        # Dédup sur la clé UNIQUE secondaire de coin_mint_releases
        # (parent_type_id, mint_year, mint_id, issue_type) : Numista modélise
        # des sous-variantes que notre granularité collapse (ex: « Proof » vs
        # « Proof (inversed) », ou deux « Coincard » la même année). Sans
        # dédup, le 2e INSERT viole la contrainte et fait rollback de TOUT le
        # bundle (on perdait alors la pièce entière). On garde 1 release par
        # clé et on redirige les iids des doublons vers le survivant — leurs
        # prix/mintage s'y rattachent (INSERT OR IGNORE / UPSERT idempotents).
        mr_rows = mint_release_rows(slug, issues, mint_resolver)
        deduped_rows: list[dict] = []
        iid_to_release_id: dict[int, str] = {}
        by_unique_key: dict[tuple, dict] = {}
        for r in mr_rows:
            key = (r["parent_type_id"], r["mint_year"], r["mint_id"], r["issue_type"])
            survivor = by_unique_key.get(key)
            if survivor is None:
                by_unique_key[key] = r
                deduped_rows.append(r)
                iid_to_release_id[r["_numista_iid"]] = r["id"]
            else:
                iid_to_release_id[r["_numista_iid"]] = survivor["id"]
        # Idempotence cross-write : purge les mint_releases périmés de CE parent
        # (id qui ne sera plus produit) — ex. millésimes hérités d'une collision
        # passée (variante écrite sous le slug canonique) ou issue retirée chez
        # Numista. Le ON CONFLICT(id) du writer couvre les ids stables ; la clé
        # UNIQUE secondaire (parent,year,mint,issue_type) plantait sinon.
        # ON DELETE CASCADE nettoie observations + prix des releases supprimés.
        new_ids = [r["id"] for r in deduped_rows]
        if new_ids:
            ph = ",".join("?" * len(new_ids))
            self.conn.execute(
                f"DELETE FROM coin_mint_releases WHERE parent_type_id = ? "
                f"AND id NOT IN ({ph})",
                [slug.eurio_id, *new_ids],
            )
        else:
            self.conn.execute(
                "DELETE FROM coin_mint_releases WHERE parent_type_id = ?",
                (slug.eurio_id,),
            )
        self.write_mint_releases(deduped_rows)
        self.write_mint_release_observations(
            mint_release_observation_rows(deduped_rows))

        # 5. prices par mint_release. iid_to_release_id couvre TOUS les iids
        # (y compris les doublons redirigés vers leur survivant).
        all_prices: list[dict] = []
        for iid, prices_payload in prices_by_iid.items():
            release_id = iid_to_release_id.get(iid)
            if not release_id:
                continue
            all_prices.extend(mint_release_price_rows(release_id, prices_payload))
        self.write_prices(all_prices)

        # 6. coin_market_quotes Type-level agrégé
        self.write_market_quotes(coin_market_quote_rows(slug.eurio_id, prices_by_iid))
