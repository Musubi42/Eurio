# Audit qualité — traductions i18n v2

Lot : `ml/state/i18n_results_v2.jsonl` (1584 lignes) croisé avec `ml/state/i18n_llm_worklist_v2.json` (396 coins × 4 langues : de/it/es/nl).

Méthode : chaque ligne croisée par `eurio_id` avec le `title_en` de référence. Note méthodologique importante : le worklist contient de nombreux coins où `theme_en` et `title_en` ne correspondent pas (ex. `de-2024` theme = "Paulskirche Constitution" mais title = "Bundesländer II Mecklenburg-Vorpommern" ; `gr-2014` theme = "Ionian Islands" mais title = "Domenikos Theotokopoulos / El Greco"). Les traducteurs ont systématiquement et correctement traduit le `title_en` (source de vérité Numista), pas le `theme_en`. Ces écarts ne sont donc PAS des erreurs.

## Erreurs bloquantes

Aucune erreur bloquante trouvée.

Vérifications ciblées effectuées sur les cas à risque :
- Le cas connu `de-2008-2eur-st-michaelis-church-hamburg` (title_en "...Hamburg Mule" = erreur de frappe / hybride) est correctement rendu : de "Fehlprägung", it "conio ibrido", es "error de acuñación", nl "muntfout". Pas de contresens "muildier" (mulet). Conforme.
- Aucune dénomination incohérente : toutes les lignes commencent par "2 Euro"/"2 Euros", cohérent avec des pièces de 2 €.
- Aucune mauvaise langue détectée : chaque `title` est bien dans la langue annoncée.
- Formes consacrées vérifiées et correctes : noms de souverains localisés (Felipe VI / Henri-Hendrik-Enrico, Guillaume/Willem/Wilhelm), institutions (Institut monétaire européen → EWI/IME/EMI), événements (JMJ → Weltjugendtag / Giornata Mondiale della Gioventù / Wereldjongerendagen), traités (Élysée), villes (Ávila, Cordoue, Liège). Aucune hallucination de nom officiel.

## Avertissements mineurs (non bloquants — n'empêchent pas l'import)

1. `fi-2010-2eur-currency-decree-of-1860-...` — les 4 langues (de/it/es/nl) ont `title: "UNCERTAIN"` avec `confidence: "uncertain"`. Le traducteur a explicitement renoncé (title_en ambigu : "Rahapaja - Mark"). À traiter à part : ne pas importer ces 4 lignes telles quelles, ou les marquer pour repasse manuelle.

2. `fr-2015-2eur-70-years-of-peace-in-europe` — lang `de` et `nl` sont `"UNCERTAIN"` (it et es OK : "Festa della Federazione" / "Fiesta de la Federación"). 2 lignes à repasser, idem.

3. `it-2024-2eur-...financial-police` lang `nl` = "Financiële Politie" (calque). title_en = "Financial Police" ; le corps réel est la "Guardia di Finanza" (de/it gardent "Guardia di Finanza", es "Guardia de Finanzas"). Le NL "Financiële Politie" reste une traduction littérale fidèle du title_en — acceptable, simple incohérence stylistique inter-langues, pas un contresens.

Total UNCERTAIN à exclure/repasser : 6 lignes.

## Compte final

- Lignes auditées : 1584
- Erreurs bloquantes : 0
- Avertissements mineurs : 3 (couvrant 6 lignes `UNCERTAIN` produites volontairement par les traducteurs + 1 note stylistique)

Verdict : lot importable. Recommandation : importer les 1578 lignes `assisted`, exclure ou router vers repasse manuelle les 6 lignes `UNCERTAIN`.
