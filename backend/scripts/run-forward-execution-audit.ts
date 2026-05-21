/**
 * 30-day forward demo execution audit — compares live JSONL log vs frozen sim baseline.
 * Prerequisites:
 *   1. npm run strategy:freeze
 *   2. STRATEGY_FREEZE=1 npm run desk-api (logs via /v1/validation/event)
 *   3. Run AUTO-EXEC on Exness demo for 30 days (zero parameter changes)
 *
 * Usage:
 *   npm run audit:forward-execution
 *   npm run audit:forward-execution -- --days=30 --fetch-baseline
 */
import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEFAULT_ALERT_THRESHOLDS, evaluateValidationAlerts } from '../validation/alerts';
import { computeDrift, liveStatsFromEvents, simVsLiveVariancePct } from '../validation/driftAnalysis';
import {
  buildExecutionAuditScores,
  formatExecutionAuditReport,
} from '../validation/executionAuditReport';
import { filterEvents, forwardDemoLogPath, loadForwardDemoEvents } from '../validation/forwardDemoStore';
import type { SimBaseline30d } from '../validation/types';
import {
  isStrategyFreezeEnforced,
  productionFrozenConfig,
  verifyFrozenStrategy,
} from '../strategy/frozenProduction';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_ROOT = path.join(__dirname, '..');
const BASELINE_CACHE = path.join(__dirname, 'forward-sim-baseline-30d.json');
const REPORT_PATH = path.join(__dirname, 'forward-execution-audit-report.txt');

function readDays(): number {
  const a = process.argv.find((x) => x.startsWith('--days='));
  if (a) return Math.max(7, Math.min(90, parseInt(a.split('=')[1]!, 10)));
  return 30;
}

function readFetchBaseline(): boolean {
  return process.argv.includes('--fetch-baseline');
}

function parseBacktestTxt(txt: string) {
  const end = txt.match(/Ending equity.*: \$([0-9,.]+)/);
  const dd = txt.match(/Max drawdown.*: \$([0-9,.]+)/);
  const wr = txt.match(/Win rate \(closed\): ([0-9.]+)%/);
  const pf = txt.match(/Profit factor.*: ([0-9.]+)/);
  const tr = txt.match(/Trades opened in window: ([0-9]+)/);
  const spread = txt.match(/Spread: ([0-9.]+) pips/);
  return {
    endEquity: end ? parseFloat(end[1]!.replace(/,/g, '')) : 1000,
    maxDd: dd ? parseFloat(dd[1]!.replace(/,/g, '')) : 0,
    winRate: wr ? parseFloat(wr[1]!) : 0,
    profitFactor: pf ? parseFloat(pf[1]!) : 0,
    trades: tr ? parseInt(tr[1]!, 10) : 0,
    spreadPips: spread ? parseFloat(spread[1]!) : 3.08,
  };
}

function fetchSimBaseline30d(days: number): SimBaseline30d {
  const to = new Date();
  const from = new Date();
  from.setUTCDate(from.getUTCDate() - days);
  const fromS = from.toISOString().slice(0, 10);
  const toS = to.toISOString().slice(0, 10);
  const outSuffix = 'forward-baseline-30d';
  const cmd = [
    'npx tsx scripts/run-xau-12mo-yahoo-backtest.ts',
    `--from=${fromS}`,
    `--to=${toS}`,
    '--exness',
    '--risk-pct=1',
    '--realistic',
    '--broker-sl-pips=20',
    '--live-profile',
    `--out-suffix=${outSuffix}`,
  ].join(' ');
  console.error(`>> Sim baseline ${fromS} → ${toS}`);
  execSync(cmd, { cwd: BACKEND_ROOT, stdio: ['inherit', 'pipe', 'inherit'] });
  const outFile = path.join(__dirname, `backtest-xau-${fromS}_${toS}-live-${outSuffix}-output.txt`);
  const txt = fs.readFileSync(outFile, 'utf8');
  const m = parseBacktestTxt(txt);
  const startEquity = 1000;
  const baseline: SimBaseline30d = {
    windowDays: days,
    generatedAt: new Date().toISOString(),
    startEquity,
    endEquity: m.endEquity,
    netPct: ((m.endEquity - startEquity) / startEquity) * 100,
    trades: m.trades,
    winRatePct: m.winRate,
    profitFactor: m.profitFactor,
    maxDrawdownUsd: m.maxDd,
    spreadPips: m.spreadPips,
    slippagePipsPerSide: 0.4,
  };
  fs.writeFileSync(BASELINE_CACHE, JSON.stringify(baseline, null, 2), 'utf8');
  return baseline;
}

function loadSimBaseline(days: number): SimBaseline30d {
  if (readFetchBaseline() || !fs.existsSync(BASELINE_CACHE)) {
    return fetchSimBaseline30d(days);
  }
  const cached = JSON.parse(fs.readFileSync(BASELINE_CACHE, 'utf8')) as SimBaseline30d;
  if (cached.windowDays === days) return cached;
  return fetchSimBaseline30d(days);
}

async function main() {
  const days = readDays();
  const sinceMs = Date.now() - days * 86400000;

  const freeze = verifyFrozenStrategy(BACKEND_ROOT, productionFrozenConfig());
  const freezeOk = freeze.ok;
  const freezeErrors = freeze.ok ? [] : freeze.errors;

  if (!freezeOk) {
    console.error('Strategy freeze check FAILED:');
    freeze.errors.forEach((e) => console.error(`  • ${e}`));
    console.error('Run: npm run strategy:freeze');
  }

  const sim = loadSimBaseline(days);
  const allEvents = loadForwardDemoEvents(0);
  const events = filterEvents(allEvents, { sinceMs });
  const live = liveStatsFromEvents(events, sim.startEquity);

  const drift = computeDrift(sim, live);
  const variancePct = simVsLiveVariancePct(drift, sim, live);
  const alerts = evaluateValidationAlerts(sim, live, drift, {
    ...DEFAULT_ALERT_THRESHOLDS,
    maxDrawdownUsd: Math.max(DEFAULT_ALERT_THRESHOLDS.maxDrawdownUsd, sim.maxDrawdownUsd * 1.35),
  });
  const scores = buildExecutionAuditScores(variancePct, live, alerts);

  const report = formatExecutionAuditReport({
    generatedAt: new Date().toISOString(),
    windowDays: days,
    sim,
    live,
    drift,
    alerts,
    scores,
    freezeOk,
    freezeErrors,
    logPath: forwardDemoLogPath(),
    eventCount: events.length,
  });

  fs.writeFileSync(REPORT_PATH, report, 'utf8');
  console.log(report);
  console.error(`\nReport: ${REPORT_PATH}`);
  console.error(`Forward log: ${forwardDemoLogPath()}`);
  console.error(`Freeze enforced (desk-api): ${isStrategyFreezeEnforced() ? 'yes' : 'set STRATEGY_FREEZE=1'}`);

  if (!freezeOk) process.exit(2);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
