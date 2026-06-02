// Parse a cohort CSV (the format produced by `POST /lab/cohorts/{id}/captures/csv`
// and stored under ml/state/cohort_csvs/*.csv) back into a list of eurio_ids,
// so the user can create a cohort by uploading the same file.
//
// Expected shape (semicolon-delimited, optional `#` comment lines + header):
//
//   # mode=ablation
//   # Push: adb push mix-zone-17.csv ...
//   eurio_id;numista_id;display_name
//   ad-2014-2eur-standard-1st-type;68395;ad-2014-2eur-standard-1st-type
//   at-2002-2eur-standard-1st-map;64;at-2002-2eur-standard-1st-map
//
// Only the first column (eurio_id) is consumed — numista_id is re-derived
// server-side, and display_name is cosmetic. Comma-delimited files are also
// tolerated so a hand-rolled list still works.

export interface ParsedCohortCsv {
  /** Deduplicated eurio_ids, in first-seen order. */
  eurioIds: string[]
  /** Lines that were dropped because they didn't look like an eurio_id. */
  warnings: string[]
}

/** A plausible eurio_id: `<cc>-<year>-...` (e.g. `fr-2018-2eur-simone-veil`). */
const EURIO_ID_RE = /^[a-z]{2}-\d{4}-[a-z0-9-]+$/

export function parseCohortCsv(text: string): ParsedCohortCsv {
  const eurioIds: string[] = []
  const warnings: string[] = []
  const seen = new Set<string>()

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue

    const delimiter = line.includes(';') ? ';' : ','
    const first = (line.split(delimiter)[0] ?? '').trim()
    if (!first) continue

    // Skip the header row, however it's cased.
    if (first.toLowerCase() === 'eurio_id') continue

    if (!EURIO_ID_RE.test(first)) {
      warnings.push(first)
      continue
    }

    if (!seen.has(first)) {
      seen.add(first)
      eurioIds.push(first)
    }
  }

  return { eurioIds, warnings }
}

/** Derive a kebab-case cohort name from a filename (`mix-zone-17.csv` → `mix-zone-17`). */
export function cohortNameFromFilename(filename: string): string {
  return filename
    .replace(/\.[^.]+$/, '') // strip extension
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
