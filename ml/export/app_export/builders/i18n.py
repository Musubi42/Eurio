"""Builders for i18n tables: coin_name_i18n and coin_description_i18n.

Sources
-------
- coin_names_i18n       : (eurio_id, lang) PK — no duplicates by construction.
                          Langs: fr/en/de/it/es/nl (6 EU languages via Numista API).
- coin_descriptions_i18n: PK is (eurio_id, source, lang) — one source 'bce_official'
                          covers all 24 EU languages, so (eurio_id, lang) is already
                          unique. No dedup logic needed in practice.

Target column contracts
-----------------------
coin_name_i18n        : {eurio_id, lang, title}
coin_description_i18n : {eurio_id, lang, title, description}

Provenance columns (source, method, model, confidence, fetched_at) are intentionally
dropped — the app schema exposes a read-only projection; provenance stays in eurio.db.
"""

from __future__ import annotations

import sqlite3


def build_coin_name_i18n(con: sqlite3.Connection) -> list[dict]:
    """Project all rows from coin_names_i18n to {eurio_id, lang, title}.

    The SQLite table already enforces PRIMARY KEY (eurio_id, lang), so no
    deduplication is required here.  All 6 langs (fr/en/de/it/es/nl) are
    projected without filtering.
    """
    cur = con.execute(
        "SELECT eurio_id, lang, title FROM coin_names_i18n ORDER BY eurio_id, lang"
    )
    return [{"eurio_id": row["eurio_id"], "lang": row["lang"], "title": row["title"]}
            for row in cur.fetchall()]


def build_coin_description_i18n(con: sqlite3.Connection) -> list[dict]:
    """Project all rows from coin_descriptions_i18n to {eurio_id, lang, title, description}.

    The current dataset has exactly one source ('bce_official') which means
    (eurio_id, lang) is already unique.  The query uses DISTINCT ON-equivalent
    logic via GROUP BY + source precedence ordering so the builder stays correct
    even if a second source is added in the future.

    Source precedence (best first): bce_official > any other source.
    Within a tied source, the row with the latest fetched_at wins.
    """
    cur = con.execute(
        """
        SELECT
            eurio_id,
            lang,
            title,
            description
        FROM coin_descriptions_i18n AS d
        WHERE (eurio_id, source, lang) IN (
            SELECT eurio_id, source, lang
            FROM (
                SELECT
                    eurio_id,
                    lang,
                    source,
                    fetched_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY eurio_id, lang
                        ORDER BY
                            CASE source
                                WHEN 'bce_official' THEN 0
                                ELSE 1
                            END,
                            fetched_at DESC
                    ) AS rn
                FROM coin_descriptions_i18n
            )
            WHERE rn = 1
        )
        ORDER BY eurio_id, lang
        """
    )
    return [
        {
            "eurio_id": row["eurio_id"],
            "lang": row["lang"],
            "title": row["title"],
            "description": row["description"],
        }
        for row in cur.fetchall()
    ]
