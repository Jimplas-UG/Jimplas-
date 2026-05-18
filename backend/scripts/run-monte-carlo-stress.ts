/**
 * Monte Carlo stress tests on a closed-trade journal export from
 * run-xau-12mo-yahoo-backtest.ts (--export-closed-trades).
 *
 * Modes (survivorship / path + shocks):
 *   shuffle    — random order of the same trades (compounding path sensitivity)
 *   bootstrap  — resample trades with replacement (empirical distribution)
 *   winstress  — shuffle + each WIN flips to LOSS with prob --win-flip-prob
 *
 * Usage:
 *   npx tsx scripts/run-monte-carlo-stress.ts --journal=scripts/mc-seed-journal.json --sims=3000 --seed=42
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import type { BilshenzEngineConfig, TradeJournalRow } from '../engine/types';
import { defaultBilshenzConfig } from '../engine';
import {
  cloneJournalRow,
  equityAfterAutoTrades,
  maxDrawdownFromSeries,
  mulberry32,
  sampleWithReplacement,
  shuffleInPlace,
} from './lib/journalEquityPath';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

type JournalExportV1 = {
  version: 1;
  startEquity: number;
  riskPct: number;
  pipSize: number;
  simUsdPerEnginePip: number;
  cfgSnapshot: Partial<BilshenzEngineConfig>;
  trades: TradeJournalRow[];
};

function readArgStr(name: string): string | null {
  const argv = process.argv.slice(2);
  const p = `--${name}=`;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith(p)) return a.slice(p.length).trim();
    if (a === `--${name}` && argv[i + 1]) return argv[i + 1]!.trim();
  }
  return null;
}

function readArgN(name: string, def: number): number {
  const s = readArgStr(name);
  if (s == null) return def;
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : def;
}

function stressFlipWins(rows: TradeJournalRow[], flipProb: number, rand: () => number): TradeJournalRow[] {
  if (flipProb <= 0) return rows.map(cloneJournalRow);
  return rows.map((r) => {
    const c = cloneJournalRow(r);
    if (c.out === 'WIN' && rand() < flipProb) {
      c.out = 'LOSS';
    }
    return c;
  });
}

function runSuite(
  sims: number,
  baseTrades: TradeJournalRow[],
  rand: () => number,
  cfg: BilshenzEngineConfig,
  pip: number,
  simPip: number,
  startEq: number,
  riskPct: number,
  mode: 'shuffle' | 'bootstrap' | 'winstress',
  winFlipProb: number
): { ends: number[]; dds: number[] } {
  const ends: number[] = [];
  const dds: number[] = [];
  const n = baseTrades.length;

  for (let i = 0; i < sims; i++) {
    let work: TradeJournalRow[];
    if (mode === 'bootstrap') {
      work = sampleWithReplacement(baseTrades, n, rand).map(cloneJournalRow);
    } else {
      work = baseTrades.map(cloneJournalRow);
      shuffleInPlace(work, rand);
    }
    if (mode === 'winstress') {
      work = stressFlipWins(work, winFlipProb, rand);
    }
    const { endEquity, series } = equityAfterAutoTrades(work, pip, simPip, startEq, riskPct, cfg, null);
    ends.push(endEquity);
    dds.push(maxDrawdownFromSeries(startEq, series));
  }
  return { ends, dds };
}

function fmtPct(x: number): string {
  if (!Number.isFinite(x)) return '—';
  return `${x >= 0 ? '+' : ''}${x.toFixed(2)}%`;
}

async function main() {
  const journalPath = readArgStr('journal');
  if (!journalPath) {
    console.error('Usage: --journal=path/to/export.json (from --export-closed-trades)');
    process.exit(1);
  }
  const resolved = path.resolve(journalPath);
  if (!fs.existsSync(resolved)) {
    console.error(`Journal file not found: ${resolved}`);
    process.exit(1);
  }

  const sims = Math.max(100, Math.min(500_000, Math.floor(readArgN('sims', 2000))));
  const seed = Math.floor(readArgN('seed', 1337));
  const winFlipProb = Math.max(0, Math.min(1, readArgN('win-flip-prob', 0.05)));

  const raw = JSON.parse(fs.readFileSync(resolved, 'utf8')) as JournalExportV1;
  if (raw.version !== 1 || !Array.isArray(raw.trades)) {
    throw new Error('Invalid journal JSON (expected version 1 with trades[])');
  }

  const cfg: BilshenzEngineConfig = { ...defaultBilshenzConfig, ...raw.cfgSnapshot };
  const pip = raw.pipSize ?? cfg.pipSize;
  const simPip = raw.simUsdPerEnginePip ?? cfg.simUsdPerEnginePip;
  const startEq = raw.startEquity ?? 10_000;
  const riskPct = raw.riskPct ?? 0.01;

  const trades = raw.trades.filter(
    (r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS'
  ) as TradeJournalRow[];
  if (trades.length < 5) {
    console.warn(`Warning: only ${trades.length} closed trades — Monte Carlo will be noisy.`);
  }

  const baseline = equityAfterAutoTrades(trades, pip, simPip, startEq, riskPct, cfg, null);
  const baseDd = maxDrawdownFromSeries(startEq, baseline.series);
  const baseRet = ((baseline.endEquity - startEq) / startEq) * 100;

  const lines: string[] = [];
  lines.push('BILSHENZ — Monte Carlo equity stress (journal replay)');
  lines.push(`Journal: ${resolved}`);
  lines.push(`Trades: ${trades.length}  |  Start equity: $${startEq.toLocaleString()}  |  Risk/trade: ${(riskPct * 100).toFixed(2)}%`);
  lines.push(`Sims per suite: ${sims}  |  Seed: ${seed}  |  Win→loss shock (winstress only): ${(winFlipProb * 100).toFixed(1)}%`);
  lines.push('');
  lines.push(`Baseline (historical order): end $${baseline.endEquity.toFixed(2)}  (${fmtPct(baseRet)})  max DD $${baseDd.toFixed(2)}`);
  lines.push('');

  const suites: Array<{ label: string; mode: 'shuffle' | 'bootstrap' | 'winstress' }> = [
    { label: 'ORDER SHUFFLE (path / compounding)', mode: 'shuffle' },
    { label: 'BOOTSTRAP WITH REPLACEMENT (sampling variation)', mode: 'bootstrap' },
    { label: 'SHUFFLE + WIN STRESS (random adverse fills)', mode: 'winstress' },
  ];

  for (const s of suites) {
    const rand = mulberry32(seed + s.mode.length * 997);
    const { ends, dds } = runSuite(
      sims,
      trades,
      rand,
      cfg,
      pip,
      simPip,
      startEq,
      riskPct,
      s.mode,
      s.mode === 'winstress' ? winFlipProb : 0
    );
    ends.sort((a, b) => a - b);
    dds.sort((a, b) => a - b);
    const q = (arr: number[], p: number) => arr[Math.floor((arr.length - 1) * p)] ?? NaN;
    lines.push(`--- ${s.label} ---`);
    lines.push(
      `End equity  p5/p25/p50/p75/p95: ${q(ends, 0.05).toFixed(2)} / ${q(ends, 0.25).toFixed(2)} / ${q(ends, 0.5).toFixed(2)} / ${q(ends, 0.75).toFixed(2)} / ${q(ends, 0.95).toFixed(2)}`
    );
    lines.push(
      `Max DD $    p5/p25/p50/p75/p95: ${q(dds, 0.05).toFixed(0)} / ${q(dds, 0.25).toFixed(0)} / ${q(dds, 0.5).toFixed(0)} / ${q(dds, 0.75).toFixed(0)} / ${q(dds, 0.95).toFixed(0)}`
    );
    const fracLoss = ends.filter((e) => e < startEq * 0.92).length / sims;
    lines.push(`Rough tail: fraction of paths ending below −8% vs start: ${(fracLoss * 100).toFixed(1)}%`);
    lines.push('');
  }

  lines.push('Interpretation: bootstrap/shuffle do not create new edges — they stress-test');
  lines.push('path dependence and resampling noise. Winstress injects extra LOSS outcomes.');
  lines.push('Survivorship bias in live trading is not fully captured; use forward demo too.');

  const outPath = path.join(__dirname, 'monte-carlo-stress-output.txt');
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log('');
  console.log(`Full report: ${outPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
