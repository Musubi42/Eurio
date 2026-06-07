"""Package `state` — données locales (eurio.db, schema.sql, artefacts de run) et
modules d'accès résiduels (`source_status`, `sources_runs`, `archive`).

Le store SQLite a migré vers le package `store/` (refacto ML chunks 5-7) ;
ce package ne ré-exporte plus rien — importer `from store import …`.
"""
