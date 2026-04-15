#!/usr/bin/env node
/**
 * Generate Android Compose theme files from shared/tokens.css.
 *
 * Parses CSS custom properties from :root { } and emits three Kotlin files:
 *
 *   app-android/src/main/java/com/musubi/eurio/ui/theme/Color.kt
 *   app-android/src/main/java/com/musubi/eurio/ui/theme/Shape.kt
 *   app-android/src/main/java/com/musubi/eurio/ui/theme/Spacing.kt
 *
 * See docs/design/_shared/parity-rules.md §R1 for the contract.
 *
 * Usage:
 *   node scripts/generate_android_tokens.mjs
 *   # or: go-task tokens:generate
 *
 * Exit codes:
 *   0  success (files written, possibly unchanged)
 *   1  parse / IO error
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..');
const TOKENS_PATH = join(REPO_ROOT, 'shared/tokens.css');
const THEME_DIR = join(
  REPO_ROOT,
  'app-android/src/main/java/com/musubi/eurio/ui/theme',
);

const HEADER = [
  '// ─────────────────────────────────────────────────────────────────────────────',
  '// AUTO-GENERATED from shared/tokens.css — DO NOT EDIT MANUALLY.',
  '// Run `go-task tokens:generate` (or `node scripts/generate_android_tokens.mjs`)',
  '// after editing shared/tokens.css to regenerate this file.',
  '// See docs/design/_shared/parity-rules.md §R1.',
  '// ─────────────────────────────────────────────────────────────────────────────',
];

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

// ─────────── Parse ───────────

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

// ─────────── Value helpers ───────────

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

// ─────────── Color.kt ───────────

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

// ─────────── Shape.kt ───────────

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
  // Shapes object (M3 mapping — use xs/sm/md/lg/xl if present)
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

// ─────────── Spacing.kt ───────────

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

// ─────────── Main ───────────

function writeFile(path, content) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, 'utf-8');
}

function main() {
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

  const colorPath = join(THEME_DIR, 'Color.kt');
  const shapePath = join(THEME_DIR, 'Shape.kt');
  const spacingPath = join(THEME_DIR, 'Spacing.kt');

  const colorKt = generateColorFile(tokens);
  const shapeKt = generateShapeFile(tokens);
  const spacingKt = generateSpacingFile(tokens);

  writeFile(colorPath, colorKt);
  writeFile(shapePath, shapeKt);
  writeFile(spacingPath, spacingKt);

  const totalTokens = Object.keys(tokens).length;
  const colorCount = (colorKt.match(/^val /gm) || []).length;
  const radiusCount = (shapeKt.match(/^    val /gm) || []).length;
  const spaceCount = (spacingKt.match(/^    val /gm) || []).length;

  console.log(`✓ parsed ${totalTokens} tokens from ${TOKENS_PATH}`);
  console.log(`✓ wrote ${colorCount} colors      → ${colorPath}`);
  console.log(`✓ wrote ${radiusCount} radii      → ${shapePath}`);
  console.log(`✓ wrote ${spaceCount} spacing     → ${spacingPath}`);
  return 0;
}

process.exit(main());
