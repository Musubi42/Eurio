"""Archive read-only — scripts legacy du chantier coin-richness.

Voir ``README.md`` pour le contexte et le mapping vers les modules
modernes.

⚠️ **Ne pas importer depuis du code de production.** Les modules d'ici
peuvent avoir des dépendances cassées (imports internes pointant vers
``referential.audit_apply_common`` etc.) — c'est volontaire, l'archive
n'est pas un package importable, juste de l'histoire pour audit.
"""
