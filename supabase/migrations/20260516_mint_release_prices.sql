-- mint_release_prices : prix par grade Numista (7 grades bruts) attachés à un mint_release.
-- Voir docs/research/numista-clean-refetch-progress.md §Migration prix.

CREATE TABLE mint_release_prices (
  id               bigserial PRIMARY KEY,
  mint_release_id  text NOT NULL REFERENCES coin_mint_releases(id) ON DELETE CASCADE,
  source           text NOT NULL,
  grade_raw        text NOT NULL CHECK (grade_raw IN ('g','vg','f','vf','xf','au','unc')),
  grade_eurio      text CHECK (grade_eurio IN ('UNC','TTB','TB')),
  price            numeric NOT NULL,
  currency         text NOT NULL DEFAULT 'EUR',
  fetched_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (mint_release_id, source, grade_raw, fetched_at)
);

CREATE INDEX idx_mint_release_prices_release ON mint_release_prices(mint_release_id);
CREATE INDEX idx_mint_release_prices_source  ON mint_release_prices(source);

COMMENT ON TABLE mint_release_prices IS
  'Prix par grade Numista (7 grades bruts) attachés à une mint_release. Le grade_eurio dérivé est stocké pour la vue grand public (UNC/TTB/TB). Le grade_raw reste disponible pour drill-down aficionado. Voir docs/research/numista-clean-refetch-progress.md.';
