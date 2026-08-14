#!/usr/bin/env node
/**
 * Génère les fichiers de thème par plateforme à partir de shared/tokens.css.
 *
 * `shared/tokens.css` est la SOURCE CANONIQUE (règle R2 de CLAUDE.md). Ce script
 * la parse une fois, puis délègue l'émission à une **cible** enregistrée dans
 * TARGETS. Aujourd'hui une seule cible existe (`android`) ; en ajouter une
 * (iOS/Swift, Flutter, tokens JSON…) = ajouter une entrée dans TARGETS, sans
 * toucher au parsing ni au CLI.
 *
 * Usage :
 *   node scripts/generate_tokens.mjs                 # toutes les cibles
 *   node scripts/generate_tokens.mjs --target android
 *   node scripts/generate_tokens.mjs --check         # ne rien écrire, sortir 1 si dérive
 *   # ou : go-task tokens:generate / go-task tokens:check
 *
 * Contrat d'une cible :
 *   { name, description, outputs(tokens) -> [{ path, content }] }
 *   `path` est absolu ; `content` est la chaîne complète du fichier.
 *
 * Codes de sortie :
 *   0  succès (ou, en --check, tout est à jour)
 *   1  erreur de parsing / IO
 *   2  --check : au moins un fichier a dérivé de shared/tokens.css
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..');
const TOKENS_PATH = join(REPO_ROOT, 'shared/tokens.css');

const HEADER = [
  '// ─────────────────────────────────────────────────────────────────────────────',
  '// AUTO-GENERATED from shared/tokens.css — DO NOT EDIT MANUALLY.',
  '// Run `go-task tokens:generate` (or `node scripts/generate_tokens.mjs`)',
  '// after editing shared/tokens.css to regenerate this file.',
  '// See docs/design/_shared/parity-rules.md §R1.',
  '// ─────────────────────────────────────────────────────────────────────────────',
];

// ─────────── Parse (commun à toutes les cibles) ───────────

function parseTokens(css) {
  const rootMatch = css.match(/:root\s*\{([\s\S]*?)\n\}/);
  if (!rootMatch) {
    throw new Error('Could not locate :root { … } block in tokens.css');
  }
  const body = rootMatch[1];
  const tokens = {};
  const regex = /--([a-z0-9-]+)\s*:\s*([^;]+);/g;
  let m;
  while ((m = regex.exec(body)) !== null) {
    tokens[m[1].trim()] = m[2].trim();
  }
  return tokens;
}

// ═════════════════════════════════════════════════════════════════════════════
// Cible : android (Kotlin / Jetpack Compose)
// ═════════════════════════════════════════════════════════════════════════════

const ANDROID_THEME_DIR = join(
  REPO_ROOT,
  'app-android/src/main/java/com/musubi/eurio/ui/theme',
);

// Override map : CSS token name → Kotlin symbol.
// Avoids shadowing `androidx.compose.material3.Surface` composable.
const NAME_OVERRIDES = {
  surface: 'PaperSurface',
  'surface-1': 'PaperSurface1',
  'surface-2': 'PaperSurface2',
  'surface-3': 'PaperSurface3',
};

function kebabToPascal(name) {
  if (NAME_OVERRIDES[name]) return NAME_OVERRIDES[name];
  return name
    .split('-')
    .map((p) => (p.length ? p[0].toUpperCase() + p.slice(1) : ''))
    .join('');
}

function hexTo0xFF(value) {
  const v = value.trim();
  if (!v.startsWith('#')) return null;
  let hex = v.slice(1);
  if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
  if (hex.length !== 6) return null;
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null;
  return `0xFF${hex.toUpperCase()}`;
}

function pxToDp(value) {
  const v = value.trim();
  const m = v.match(/^(-?\d+(?:\.\d+)?)px$/);
  if (!m) return null;
  const num = parseFloat(m[1]);
  return num % 1 === 0 ? `${num}.dp` : `${num}f.dp`;
}

const COLOR_GROUPS = [
  { title: 'Indigo scale (brand primary)', test: (n) => /^indigo(-|$)/.test(n) },
  { title: 'Gold scale (accents, moments)', test: (n) => /^gold(-|$)/.test(n) || n === 'gold' },
  {
    title: 'Surfaces & ink (PaperSurface override évite le shadow de M3 Surface)',
    test: (n) => /^(surface|ink|paper)(-|$)/.test(n) || n === 'ink' || n === 'paper',
  },
  { title: 'Neutral grays', test: (n) => /^gray-/.test(n) },
  { title: 'Semantic', test: (n) => ['success', 'warning', 'danger', 'debug-red'].includes(n) },
];

function generateColorFile(tokens) {
  const lines = [
    ...HEADER,
    '',
    'package com.musubi.eurio.ui.theme',
    '',
    'import androidx.compose.ui.graphics.Color',
    '',
  ];
  for (const group of COLOR_GROUPS) {
    const entries = Object.entries(tokens).filter(([name]) => group.test(name));
    if (entries.length === 0) continue;
    lines.push(`// ${group.title}`);
    for (const [name, value] of entries) {
      const lit = hexTo0xFF(value);
      if (!lit) continue; // skip rgba, var refs, etc.
      const kotlinName = kebabToPascal(name);
      lines.push(`val ${kotlinName} = Color(${lit})`);
    }
    lines.push('');
  }
  return lines.join('\n');
}

function generateShapeFile(tokens) {
  const radii = Object.entries(tokens).filter(
    ([name, value]) => /^radius-/.test(name) && pxToDp(value) !== null,
  );
  const lines = [
    ...HEADER,
    '',
    'package com.musubi.eurio.ui.theme',
    '',
    'import androidx.compose.foundation.shape.RoundedCornerShape',
    'import androidx.compose.material3.Shapes',
    'import androidx.compose.ui.unit.dp',
    '',
    '// Mirror de --radius-* dans shared/tokens.css',
    'object EurioRadii {',
  ];
  for (const [name, value] of radii) {
    // `radius-xs` → `xs` ; prefix `r` if starts with a digit (Kotlin ident).
    let short = name.replace(/^radius-/, '');
    if (/^\d/.test(short)) short = 'r' + short;
    const dp = pxToDp(value);
    lines.push(`    val ${short} = ${dp}`);
  }
  lines.push('}');
  lines.push('');
  lines.push('val EurioShapes = Shapes(');
  const shapeMap = [
    ['extraSmall', 'xs'],
    ['small', 'sm'],
    ['medium', 'md'],
    ['large', 'lg'],
    ['extraLarge', 'xl'],
  ];
  for (const [m3, short] of shapeMap) {
    if (radii.some(([name]) => name === `radius-${short}`)) {
      lines.push(`    ${m3} = RoundedCornerShape(EurioRadii.${short}),`);
    }
  }
  lines.push(')');
  lines.push('');
  return lines.join('\n');
}

function generateSpacingFile(tokens) {
  const spaces = Object.entries(tokens).filter(
    ([name, value]) => /^space-\d+$/.test(name) && pxToDp(value) !== null,
  ).sort(([a], [b]) => {
    const na = parseInt(a.replace('space-', ''), 10);
    const nb = parseInt(b.replace('space-', ''), 10);
    return na - nb;
  });
  const lines = [
    ...HEADER,
    '',
    'package com.musubi.eurio.ui.theme',
    '',
    'import androidx.compose.ui.unit.dp',
    '',
    '// Mirror de --space-* dans shared/tokens.css',
    '// Convention : sN = N comme dans le proto (ex : s4 = var(--space-4) = 16px).',
    'object EurioSpacing {',
  ];
  for (const [name, value] of spaces) {
    // `space-4` → `s4`
    const short = 's' + name.replace(/^space-/, '');
    const dp = pxToDp(value);
    lines.push(`    val ${short} = ${dp}`);
  }
  lines.push('}');
  lines.push('');
  return lines.join('\n');
}

// ═════════════════════════════════════════════════════════════════════════════
// Registre des cibles
// ═════════════════════════════════════════════════════════════════════════════
//
// Pour ajouter iOS le jour venu : une entrée `ios` dont `outputs()` renvoie
// p. ex. [{ path: '<ios>/Sources/DesignSystem/Tokens.swift', content: … }].
// Le parsing, le CLI, --check et le rapport sont déjà mutualisés — il n'y a
// que l'émission à écrire. Ne pas créer de cible tant qu'aucun consommateur
// n'existe : une cible sans consommateur est de la dette (R0).

const TARGETS = {
  android: {
    description: 'Kotlin / Jetpack Compose (Color.kt, Shape.kt, Spacing.kt)',
    outputs: (tokens) => [
      { path: join(ANDROID_THEME_DIR, 'Color.kt'), content: generateColorFile(tokens) },
      { path: join(ANDROID_THEME_DIR, 'Shape.kt'), content: generateShapeFile(tokens) },
      { path: join(ANDROID_THEME_DIR, 'Spacing.kt'), content: generateSpacingFile(tokens) },
    ],
  },
};

// ═════════════════════════════════════════════════════════════════════════════
// CLI
// ═════════════════════════════════════════════════════════════════════════════

function parseArgs(argv) {
  const opts = { targets: Object.keys(TARGETS), check: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--check') {
      opts.check = true;
    } else if (a === '--target') {
      const name = argv[++i];
      if (!name || !TARGETS[name]) {
        throw new Error(
          `cible inconnue: ${name ?? '(manquante)'}. Connues: ${Object.keys(TARGETS).join(', ')}`,
        );
      }
      opts.targets = [name];
    } else if (a === '--help' || a === '-h') {
      opts.help = true;
    } else {
      throw new Error(`argument inconnu: ${a}`);
    }
  }
  return opts;
}

function usage() {
  console.log('Usage: node scripts/generate_tokens.mjs [--target <nom>] [--check]');
  console.log('\nCibles disponibles :');
  for (const [name, t] of Object.entries(TARGETS)) {
    console.log(`  ${name.padEnd(10)} ${t.description}`);
  }
}

function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (e) {
    console.error(`error: ${e.message}`);
    return 1;
  }
  if (opts.help) {
    usage();
    return 0;
  }

  let css;
  try {
    css = readFileSync(TOKENS_PATH, 'utf-8');
  } catch (e) {
    console.error(`error: cannot read ${TOKENS_PATH}: ${e.message}`);
    return 1;
  }
  let tokens;
  try {
    tokens = parseTokens(css);
  } catch (e) {
    console.error(`error: parse failure: ${e.message}`);
    return 1;
  }

  console.log(`✓ parsed ${Object.keys(tokens).length} tokens from ${TOKENS_PATH}`);

  const drifted = [];
  for (const name of opts.targets) {
    let outputs;
    try {
      outputs = TARGETS[name].outputs(tokens);
    } catch (e) {
      console.error(`error: cible ${name}: ${e.message}`);
      return 1;
    }
    for (const { path, content } of outputs) {
      const rel = relative(REPO_ROOT, path);
      if (opts.check) {
        const current = existsSync(path) ? readFileSync(path, 'utf-8') : null;
        if (current === content) {
          console.log(`  ✓ à jour      ${rel}`);
        } else {
          console.log(`  ✗ DÉRIVE      ${rel}${current === null ? ' (absent)' : ''}`);
          drifted.push(rel);
        }
      } else {
        mkdirSync(dirname(path), { recursive: true });
        writeFileSync(path, content, 'utf-8');
        const vals = (content.match(/^ *val /gm) || []).length;
        console.log(`  ✓ ${String(vals).padStart(3)} valeurs → ${rel}`);
      }
    }
  }

  if (opts.check && drifted.length > 0) {
    console.error(
      `\nerror: ${drifted.length} fichier(s) ont dérivé de shared/tokens.css.` +
        `\nLance \`go-task tokens:generate\` et committe le résultat avec le .css (règle R2).`,
    );
    return 2;
  }
  return 0;
}

process.exit(main(process.argv.slice(2)));
