/* scenes/profile-set.js — sidecar for profile-set.html (Agent B5-bis · Phase 2)
 *
 * Renders the plateau (8 cells) of a given set, the missing list, and wires
 * the CTA buttons. SetRule heuristics are deliberately simplified: a tiny
 * table maps known set ids to a label/description + a builder function that
 * returns a list of { id, label, faceValueCents } required cells.
 *
 * Known set ids coming from profile-achievements.js and profile.js :
 *   circulation-fr       → FR 8 denominations
 *   circulation-de       → DE 8 denominations
 *   circulation-<iso2>   → any country 8 denominations (fallback)
 *   eurozone-founding    → 12 founding countries, 1 coin each
 *   grande-chasse        → 21 euro countries, 1 coin each
 *   commemoratives-2e    → 10 commemorative 2 € coins (count-based)
 */

const STANDARD_DENOMS = [
  { cents: 1,   label: '1 c'  },
  { cents: 2,   label: '2 c'  },
  { cents: 5,   label: '5 c'  },
  { cents: 10,  label: '10 c' },
  { cents: 20,  label: '20 c' },
  { cents: 50,  label: '50 c' },
  { cents: 100, label: '1 €'  },
  { cents: 200, label: '2 €'  },
];

const COUNTRY_NAMES = {
  AT: 'Autriche',  BE: 'Belgique',  BG: 'Bulgarie', CY: 'Chypre',
  DE: 'Allemagne', EE: 'Estonie',   ES: 'Espagne',  FI: 'Finlande',
  FR: 'France',    GR: 'Grèce',     HR: 'Croatie',  IE: 'Irlande',
  IT: 'Italie',    LT: 'Lituanie',  LU: 'Luxembourg', LV: 'Lettonie',
  MT: 'Malte',     NL: 'Pays-Bas',  PT: 'Portugal', SI: 'Slovénie',
  SK: 'Slovaquie',
};

const FOUNDING = ['BE','DE','ES','FI','FR','GR','IE','IT','LU','NL','AT','PT'];
const ALL_EZ = ['AT','BE','BG','CY','DE','EE','ES','FI','FR','GR','HR','IE','IT','LT','LU','LV','MT','NL','PT','SI','SK'];

// ───────── Set definitions ─────────

function circulationSet(iso2) {
  const cc = iso2.toUpperCase();
  const name = COUNTRY_NAMES[cc] || cc;
  return {
    eyebrow: `Série · ${name}`,
    titleHead: 'Huit pièces,',
    titleEm: `une série ${name.toLowerCase()}.`,
    desc: `Toutes les pièces de circulation ${genderise(name)}, du centime à deux euros.`,
    buildRequired(data) {
      // Pick 1 coin per denomination from the country. Prefer non-commemorative.
      return STANDARD_DENOMS.map(d => {
        const pool = (data.filterCoins
          ? data.filterCoins({ country: cc, faceValueCents: d.cents, isCommemorative: false })
          : []);
        // Fallback : any coin of the right country/value, even if commemorative.
        const pick = pool[0] || (data.filterCoins
          ? data.filterCoins({ country: cc, faceValueCents: d.cents })[0]
          : null);
        return {
          id: pick ? pick.eurioId : `${cc.toLowerCase()}-standard-${d.cents}c`,
          label: d.label,
          faceValueCents: d.cents,
          countryCode: cc,
          year: pick ? pick.year : null,
        };
      });
    },
  };
}

function countrySetFromList(list, labelHead, emText, desc) {
  return {
    eyebrow: `Série · ${list.length} pays`,
    titleHead: labelHead,
    titleEm: emText,
    desc,
    buildRequired(data) {
      return list.map(cc => {
        const pick = (data.filterCoins ? data.filterCoins({ country: cc })[0] : null);
        return {
          id: pick ? pick.eurioId : `${cc.toLowerCase()}-any`,
          label: COUNTRY_NAMES[cc] || cc,
          faceValueCents: pick ? pick.faceValueCents : 200,
          countryCode: cc,
          year: pick ? pick.year : null,
        };
      });
    },
    matchMode: 'country',
  };
}

function genderise(name) {
  // Super-rough French article fitting: `françaises`, `allemandes`, etc.
  // Fallback: use the country name verbatim.
  const adj = {
    'France': 'françaises',
    'Allemagne': 'allemandes',
    'Italie': 'italiennes',
    'Espagne': 'espagnoles',
    'Portugal': 'portugaises',
    'Belgique': 'belges',
    'Pays-Bas': 'néerlandaises',
    'Autriche': 'autrichiennes',
    'Irlande': 'irlandaises',
    'Finlande': 'finlandaises',
  }[name];
  return adj || `de ${name}`;
}

function resolveSet(setId) {
  if (!setId) return circulationSet('fr');

  // circulation-<iso2>
  const m = /^circulation-([a-z]{2})$/i.exec(setId);
  if (m) return circulationSet(m[1]);

  if (setId === 'eurozone-founding') {
    return countrySetFromList(
      FOUNDING,
      'Douze pays,',
      'une union fondatrice.',
      'Les douze pays fondateurs de la zone euro, une pièce par pays.'
    );
  }
  if (setId === 'grande-chasse') {
    return countrySetFromList(
      ALL_EZ,
      'Vingt-et-un pays,',
      'la grande chasse.',
      'Une pièce de chaque pays de la zone euro — l\'aboutissement.'
    );
  }
  if (setId === 'commemoratives-2e') {
    return {
      eyebrow: 'Série · 2 € commémoratives',
      titleHead: 'Dix commémoratives,',
      titleEm: 'une décennie.',
      desc: 'Dix pièces commémoratives de 2 € issues de toute la zone euro.',
      buildRequired(data) {
        // Count-based: we render 10 abstract slots and check against any
        // owned 2 € commemorative. The first N are "acquise" where N is the
        // owned count capped at 10.
        const slots = [];
        for (let i = 0; i < 10; i++) {
          slots.push({
            id: `commem-slot-${i + 1}`,
            label: `N° ${i + 1}`,
            faceValueCents: 200,
            countryCode: null,
            year: null,
          });
        }
        return slots;
      },
      matchMode: 'count-commemorative-2e',
    };
  }

  // Unknown set id → fall back to France.
  return circulationSet('fr');
}

// ───────── Ownership matching ─────────

function ownedSet(required, collection, matchMode) {
  const ids = new Set(collection.map(c => c.eurioId));
  const owned = new Set();

  if (matchMode === 'country') {
    const byCc = {};
    collection.forEach(c => {
      const cc = (c.eurioId || '').slice(0, 2).toUpperCase();
      byCc[cc] = (byCc[cc] || 0) + 1;
    });
    required.forEach(r => {
      if (r.countryCode && byCc[r.countryCode]) owned.add(r.id);
    });
    return owned;
  }

  if (matchMode === 'count-commemorative-2e') {
    const count = collection.filter(c => {
      const id = c.eurioId || '';
      return id.includes('-2eur-') && !id.endsWith('-standard');
    }).length;
    required.slice(0, Math.min(required.length, count)).forEach(r => owned.add(r.id));
    return owned;
  }

  // Default : exact eurio_id match, with a soft fallback on country+denom.
  const byCcDenom = {};
  collection.forEach(c => {
    const cc = (c.eurioId || '').slice(0, 2).toUpperCase();
    // Very rough: scrape face value from the id (e.g. "fr-2020-50c-standard")
    const faceMatch = /-(\d+)(c|eur)-/i.exec(c.eurioId || '');
    let cents = null;
    if (faceMatch) {
      cents = faceMatch[2].toLowerCase() === 'eur'
        ? parseInt(faceMatch[1], 10) * 100
        : parseInt(faceMatch[1], 10);
    }
    const k = `${cc}:${cents}`;
    byCcDenom[k] = (byCcDenom[k] || 0) + 1;
  });
  required.forEach(r => {
    if (ids.has(r.id)) { owned.add(r.id); return; }
    const k = `${r.countryCode}:${r.faceValueCents}`;
    if (byCcDenom[k]) owned.add(r.id);
  });
  return owned;
}

// ───────── Rendering helpers ─────────

function metalClassFor(cents) {
  if (cents == null) return 'nordic';
  if (cents <= 5) return 'copper';
  if (cents <= 50) return 'nordic';
  if (cents < 100) return 'silver';
  return 'bimetal';
}

function cellHtml(slot, isOwned) {
  const metal = isOwned ? metalClassFor(slot.faceValueCents) : '';
  const discCls = isOwned ? `profile-set-disc ${metal}` : 'profile-set-disc is-missing';
  const cellCls = isOwned ? 'profile-set-cell' : 'profile-set-cell is-missing';
  const metaText = slot.year ? String(slot.year) : (isOwned ? 'Acquise' : 'Manquante');
  return `
    <div class="${cellCls}">
      <div class="${discCls}">
        <div class="profile-set-disc__val">${slot.label}</div>
        ${isOwned ? '<div class="profile-set-disc__check">✓</div>' : ''}
      </div>
      <div class="profile-set-cell__info">
        <div class="profile-set-cell__title">${slot.label}</div>
        <div class="profile-set-cell__meta">${metaText}</div>
      </div>
    </div>`;
}

function missingBlockHtml(missing) {
  if (!missing.length) {
    return `
      <div class="profile-set-missing">
        <h3>Série complète</h3>
        <p style="font-size:var(--text-sm);color:var(--ink-400);margin-top:4px;">
          Toutes les pièces du plateau sont à toi. Magnifique.
        </p>
      </div>`;
  }
  const items = missing.map(m => `
    <li>
      <span class="profile-set-missing__name">${m.label}</span>
      <span class="profile-set-missing__cta">Scanner</span>
    </li>`).join('');
  return `
    <div class="profile-set-missing">
      <h3>Encore ${missing.length} pièce${missing.length > 1 ? 's' : ''}</h3>
      <ul>${items}</ul>
    </div>`;
}

// ───────── Mount ─────────

export function mount(ctx) {
  const { params, state, data, navigate } = ctx;
  const root = document.querySelector('[data-scene="profile-set"]');
  if (!root) return;

  const setId = params && params.setId ? params.setId : 'circulation-fr';
  const def = resolveSet(setId);
  const required = def.buildRequired(data) || [];
  const collection = state.state.collection || [];
  const owned = ownedSet(required, collection, def.matchMode);

  const have = required.filter(r => owned.has(r.id)).length;
  const total = required.length;
  const missing = required.filter(r => !owned.has(r.id));

  // Hero text
  const setEyebrow = root.querySelector('[data-bind="set-eyebrow"]');
  if (setEyebrow) setEyebrow.textContent = def.eyebrow;

  const setTitle = root.querySelector('[data-bind="set-title"]');
  if (setTitle) {
    setTitle.textContent = def.titleEm;
    // Update the static h1 prefix ("Huit pièces,") if set supplies one.
    const h1 = setTitle.closest('h1');
    if (h1 && def.titleHead) {
      // Replace the first text node before <br>.
      const br = h1.querySelector('br');
      if (br && br.previousSibling) {
        br.previousSibling.textContent = def.titleHead;
      }
    }
  }

  const setDesc = root.querySelector('[data-bind="set-desc"]');
  if (setDesc) setDesc.textContent = def.desc;

  // Progress
  const setHave = root.querySelector('[data-bind="set-have"]');
  if (setHave) setHave.textContent = String(have);
  const setTotal = root.querySelector('[data-bind="set-total"]');
  if (setTotal) setTotal.textContent = String(total);
  const fill = root.querySelector('[data-bind="set-fill"]');
  if (fill) fill.style.width = `${total ? Math.round((have / total) * 100) : 0}%`;

  // Planche grid
  const planche = root.querySelector('[data-bind="planche"]');
  if (planche) {
    planche.innerHTML = required.map(r => cellHtml(r, owned.has(r.id))).join('');
  }

  // Missing block
  const missingBlock = root.querySelector('[data-bind="missing-block"]');
  if (missingBlock) missingBlock.innerHTML = missingBlockHtml(missing);

  // CTA subline
  const ctaSub = root.querySelector('[data-bind="cta-sub"]');
  if (ctaSub) {
    ctaSub.textContent = missing.length
      ? `Il t'en manque ${missing.length}`
      : 'Série complète — continue d\'explorer';
  }

  // Back link → keep the hardcoded href in HTML, but also trap clicks so the
  // router handles it instead of a full reload.
  const back = root.querySelector('.profile-set-back');
  if (back && navigate) {
    back.addEventListener('click', ev => {
      ev.preventDefault();
      navigate('#/profile/achievements');
    });
  }

  const cta = root.querySelector('.profile-set-cta');
  if (cta && navigate) {
    cta.addEventListener('click', ev => {
      ev.preventDefault();
      navigate('#/scan');
    });
  }
}
