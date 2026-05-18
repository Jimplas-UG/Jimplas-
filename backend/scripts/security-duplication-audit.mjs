/**
 * Duplication-risk audit — surfaces files/strings that could help reverse-engineer the desk.
 * Run: npm run security:audit
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const lines = [];

function walk(dir, acc = []) {
  for (const name of fs.readdirSync(dir)) {
    if (name === 'node_modules' || name === '.expo' || name === '.git') continue;
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, acc);
    else acc.push(p);
  }
  return acc;
}

const SENSITIVE = [
  /jimplas/i,
  /pineV5/i,
  /leftSideScan/i,
  /defaultBilshenzConfig/,
  /riskPctAtr/,
  /p1VolumeAtrMult/,
  /wickRatioMin/,
  /athZoneLow/,
  /yieldHighThreshold/,
  /leftScanBars/,
  /hard_block/i,
  /computeBilshenzSnapshot/,
  /signalEngine/,
  /\.pine$/,
];

const files = walk(root);
const hits = [];

for (const f of files) {
  const rel = path.relative(root, f).replace(/\\/g, '/');
  if (rel.startsWith('src/server.ts')) continue;
  if (!/\.(ts|tsx|js|mjs|pine|txt|md)$/i.test(rel)) continue;
  let text = '';
  try {
    text = fs.readFileSync(f, 'utf8');
  } catch {
    continue;
  }
  const matched = SENSITIVE.filter((re) => re.test(text) || re.test(rel));
  if (matched.length) {
    hits.push({ rel, patterns: matched.map((r) => r.toString()) });
  }
}

lines.push('BILSHENZ DUPLICATION-RISK AUDIT');
lines.push(`Generated: ${new Date().toISOString()}`);
lines.push('');
lines.push('=== CLIENT BUNDLE (Metro ships when EXPO_PUBLIC_DESK_REMOTE is not 1) ===');
lines.push('engine/*.ts — FULL strategy (critical) unless remote mode + metro stub');
lines.push('hooks/deskComputeLocal.js — re-exports engine');
lines.push('App.js — INTEL panels gated by SHOW_STRATEGY_INTEL (__DEV__ only by default)');
lines.push('');
lines.push('=== MITIGATIONS IN PLACE ===');
lines.push('- security/sanitizeDesk.js strips snapshot for production UI');
lines.push('- security/publicLabels.js — BUY/SELL/WAIT, opaque block codes');
lines.push('- src/server.ts — desk API (npm run desk-api)');
lines.push('- ../frontend/metro.config.js — blocks backend engine when EXPO_PUBLIC_DESK_REMOTE=1');
lines.push('- ../frontend/client/engineStub.js — replaces engine in remote bundle');
lines.push('');
lines.push('=== FILES MATCHING SENSITIVE PATTERNS ===');
for (const h of hits.sort((a, b) => a.rel.localeCompare(b.rel))) {
  lines.push(`${h.rel}`);
  lines.push(`  ${h.patterns.join(', ')}`);
}
lines.push('');
lines.push('=== REMAINING HIGH RISK (even after changes) ===');
lines.push('1. Dev builds (__DEV__) still bundle full engine — use release + DESK_REMOTE=1 for phones');
lines.push('2. engine/reference/*.pine in repo — exclude from distribution zips');
lines.push('3. scripts/* backtest + *.txt outputs — private CI only');
lines.push('4. Lot sizing formula in utils/riskSizing.js — reveals risk÷(pips×$/pip)');
lines.push('5. Webhook/Telegram payloads may include entry/SL/TP — server should sign orders');
lines.push('6. Hermes bundle is decompilable — remote API is the real protection');
lines.push('');
lines.push(`Total flagged paths: ${hits.length}`);

const out = path.join(root, 'scripts', 'security-duplication-audit-output.txt');
fs.writeFileSync(out, lines.join('\n'), 'utf8');
console.log(lines.join('\n'));
console.log(`\nWrote ${out}`);
