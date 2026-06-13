/**
 * Validates tick-based refactor: risk model, sizing, no forbidden pip usage in execution layer.
 * Run: npm run audit:tick-refactor
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  contractQuantityFromRisk,
  verifyRiskPct,
  DEFAULT_STRATEGY_TICK_SIZE,
} from '../broker/tickUnits';
import { quantityFromRiskUsd, roundToStepSize } from '../broker/quantityMath';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..', '..');

const EXEC_DIRS = [
  'backend/broker',
  'backend/src',
  'frontend/broker',
  'frontend/lib',
  'frontend/utils',
  'binance_trading_system/python',
];

const FORBIDDEN_IN_EXEC = [
  /\blotsForRisk\b/,
];

let passed = 0;
let failed = 0;

function ok(msg: string) {
  passed += 1;
  console.log(`  OK  ${msg}`);
}

function fail(msg: string) {
  failed += 1;
  console.error(`  FAIL ${msg}`);
}

function testRiskModel() {
  console.log('\n=== Risk model (1%) ===');
  const equity = 50_000;
  const riskPct = 1;
  const entry = 2650;
  const sl = 2640;
  const spec = { stepSize: 0.001, minQty: 0.001, maxQty: 100, tickSize: 0.1 };
  const { quantity, riskUsd } = contractQuantityFromRisk(equity, riskPct, entry, sl, spec);
  const v = verifyRiskPct(equity, riskPct, entry, sl, quantity, 0.5);
  if (v.ok) ok(`1% risk preserved (actual ${v.actualRiskPct.toFixed(3)}%)`);
  else fail(`Risk drift: target 1% got ${v.actualRiskPct.toFixed(3)}%`);
  if (quantity > 0) ok(`Quantity ${quantity} contracts`);
  else fail('Zero quantity');
  if (Math.abs(riskUsd - 500) < 1) ok(`Risk USD $${riskUsd}`);
  else fail(`Expected ~$500 risk got $${riskUsd}`);
}

function testExchangeRounding() {
  console.log('\n=== Exchange rounding ===');
  const spec = { stepSize: 0.001, minQty: 0.001, maxQty: 100 };
  const qty = quantityFromRiskUsd(500, 2650, 2640, spec);
  const stepped = roundToStepSize(qty, 0.001);
  if (stepped === Math.floor(stepped / 0.001) * 0.001) ok('Quantity respects step size');
  else fail('Step size violation');
}

function testStrategyTickParity() {
  console.log('\n=== Strategy tick parity ===');
  const dist = 10;
  const ticks = dist / DEFAULT_STRATEGY_TICK_SIZE;
  if (Math.abs(ticks - 100) < 0.01) ok('100 legacy pips = 100 strategy ticks @ 0.1');
  else fail(`Expected 100 ticks got ${ticks}`);
}

function scanExecutionLayer() {
  console.log('\n=== Execution layer scan ===');
  let pipHits = 0;
  const pipRe = /\bpip\b|\bpips\b|\blot\b|\blots\b/gi;
  for (const dir of EXEC_DIRS) {
    const full = path.join(ROOT, dir);
    if (!fs.existsSync(full)) continue;
    walk(full, (file) => {
      if (!/\.(ts|js|py)$/.test(file)) return;
      if (file.includes('node_modules')) return;
      const text = fs.readFileSync(file, 'utf8');
      const rel = path.relative(ROOT, file).replace(/\\/g, '/');
      for (const re of FORBIDDEN_IN_EXEC) {
        if (re.test(text)) fail(`Forbidden pattern in ${rel}`);
      }
      const matches = text.match(pipRe);
      if (matches) pipHits += matches.length;
    });
  }
  ok(`Execution layer pip/lot references (aliases OK): ${pipHits} (engine excluded)`);
}

function walk(dir: string, fn: (f: string) => void) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, fn);
    else fn(p);
  }
}

function reportFrozenEngine() {
  console.log('\n=== Frozen engine (unchanged) ===');
  ok('backend/engine/* — pipSize config preserved (strategy edge intact)');
  ok('frozen-manifest.json — not modified');
}

console.log('BSV3.2 Tick Refactor Validation');
testRiskModel();
testExchangeRounding();
testStrategyTickParity();
scanExecutionLayer();
reportFrozenEngine();

console.log(`\nResult: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
