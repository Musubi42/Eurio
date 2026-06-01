// _eurozone.js — données mock partagées de l'eurozone (proto).
// Source unique pour la carte (carte-a-gratter) ; vault-catalog-map.js garde sa
// propre copie en référence. owned/total = progression mock par pays.
// NB : Portugal est volontairement COMPLET (42/42) — cible du scratch-reveal
// (chunk D2), pays assez grand et isolé pour gratter confortablement. Bulgarie
// à 0 illustre l'état « gravé ». Zéro hasard : la complétion est une donnée.

export const EUROZONE = [
  { iso: 'AT', name: 'Autriche',    flag: '🇦🇹', owned: 18, total: 42 },
  { iso: 'BE', name: 'Belgique',    flag: '🇧🇪', owned: 22, total: 38 },
  { iso: 'BG', name: 'Bulgarie',    flag: '🇧🇬', owned:  0, total: 24 },
  { iso: 'CY', name: 'Chypre',      flag: '🇨🇾', owned:  4, total: 26 },
  { iso: 'DE', name: 'Allemagne',   flag: '🇩🇪', owned: 38, total: 62 },
  { iso: 'EE', name: 'Estonie',     flag: '🇪🇪', owned:  5, total: 28 },
  { iso: 'ES', name: 'Espagne',     flag: '🇪🇸', owned: 26, total: 58 },
  { iso: 'FI', name: 'Finlande',    flag: '🇫🇮', owned: 14, total: 42 },
  { iso: 'FR', name: 'France',      flag: '🇫🇷', owned: 45, total: 68 },
  { iso: 'GR', name: 'Grèce',       flag: '🇬🇷', owned:  9, total: 38 },
  { iso: 'HR', name: 'Croatie',     flag: '🇭🇷', owned:  3, total: 26 },
  { iso: 'IE', name: 'Irlande',     flag: '🇮🇪', owned: 12, total: 34 },
  { iso: 'IT', name: 'Italie',      flag: '🇮🇹', owned: 28, total: 58 },
  { iso: 'LT', name: 'Lituanie',    flag: '🇱🇹', owned:  6, total: 28 },
  { iso: 'LU', name: 'Luxembourg',  flag: '🇱🇺', owned: 19, total: 36 },
  { iso: 'LV', name: 'Lettonie',    flag: '🇱🇻', owned:  5, total: 28 },
  { iso: 'MT', name: 'Malte',       flag: '🇲🇹', owned:  8, total: 30 },
  { iso: 'NL', name: 'Pays-Bas',    flag: '🇳🇱', owned: 20, total: 38 },
  { iso: 'PT', name: 'Portugal',    flag: '🇵🇹', owned: 42, total: 42 },
  { iso: 'SI', name: 'Slovénie',    flag: '🇸🇮', owned: 22, total: 30 },
  { iso: 'SK', name: 'Slovaquie',   flag: '🇸🇰', owned:  8, total: 34 },
];

// Centres approximatifs (viewBox 400×500) pour les labels des grands pays.
export const LABEL_CENTERS = {
  FR: { x: 155, y: 278 },
  DE: { x: 226, y: 238 },
  IT: { x: 244, y: 336 },
  ES: { x: 108, y: 350 },
  PT: { x:  44, y: 338 },
};

export const isComplete = (c) => c.total > 0 && c.owned >= c.total;
