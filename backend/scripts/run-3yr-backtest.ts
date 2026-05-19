/**
 * Headless 3-year M30 replay on seeded synthetic XAU-like data (no external OHLC in repo).
 * O(n) S&R via replaySrBarByBar; per-bar gates match signal path (neutral bias; Pine entries ignore bias).
 *
 * Run from myapp: npx tsx scripts/run-3yr-backtest.ts
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import type { Bar, BiasSnapshot, RiskSnapshot, TradeJournalRow } from '../engine/types';
import {
  applyJournalSignalThrottle,
  buildSyntheticMarketBundle,
  buildManualJournalEntry,
  buildTradeRecommendation,
  defaultBilshenzConfig,
  resolveJournalOnBar,
  winRateFromJournal,
} from '../engine';
import { nyYmdKey, sessionFromUtcEpochMs } from '../engine/sessionEngine';
import { replaySrBarByBar } from '../engine/srEngine';
import { leftSideScan, computeGatesAndSignals } from '../engine/signalEngine';
import { wickMetricsAt } from '../engine/wickEngine';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const ACCOUNT_USD = 50_000;
const RISK_PCT = 0.005;
const M30_PER_DAY = 48;
const THREE_YR_BARS = Math.floor(3 * 365.25 * M30_PER_DAY);
const WARMUP = 80;
const MAX_JOURNAL = 200_000;

const neutralBias: BiasSnapshot = {
  ema50H4: null,
  ema21M30: null,
  dHigh0: null,
  dHigh1: null,
  dLow0: null,
  dLow1: null,
  bullStructure: false,
  bearStructure: false,
  isBullish: false,
  isBearish: false,
};

function riskForBar(bar: Bar, close: number, cfg: typeof defaultBilshenzConfig): RiskSnapshot {
  const pip = cfg.pipSize;
  const barRangePips = (bar.h - bar.l) / pip;
  const barRangeBlocked = barRangePips > cfg.maxSpreadPips * 10;
  const brokerSpreadBlocked = cfg.currentSpreadPips > cfg.maxSpreadPips;
  const spreadBlocked = brokerSpreadBlocked || barRangeBlocked;
  return {
    atrVal: null,
    atrPips: null,
    atrMode: 'STANDARD — Risk 0.5%',
    chopZone: false,
    brokerSpreadBlocked,
    barRangeBlocked,
    spreadBlocked,
    dxyRising: false,
    dxyBlocksBuy: false,
    yieldHigh: false,
    athZoneBlocked: close >= cfg.athZoneLow,
    geoMedium: false,
    geoHigh: false,
    h4SwingHigh1: null,
    h4SwingHigh2: null,
    h4SwingLow1: null,
    h4SwingLow2: null,
  };
}

function resolveOutcome(m30: Bar[], row: TradeJournalRow): 'WIN' | 'LOSS' | 'OPEN' {
  if (row.tp1 == null || !Number.isFinite(row.tp1)) return 'OPEN';
  for (let i = row.barIndex + 1; i < m30.length; i++) {
    const b = m30[i];
    if (row.dir === 'BUY') {
      if (b.l <= row.sl) return 'LOSS';
      if (b.h >= row.tp1) return 'WIN';
    } else {
      if (b.h >= row.sl) return 'LOSS';
      if (b.l <= row.tp1) return 'WIN';
    }
  }
  return 'OPEN';
}

function pnlUsdForClosed(
  row: TradeJournalRow,
  outcome: 'WIN' | 'LOSS',
  pipSize: number,
  simUsdPerEnginePip: number,
  riskUsd: number
): number {
  const slPips = Math.abs(row.entry - row.sl) / pipSize;
  const tp1 = row.tp1;
  if (slPips <= 0 || tp1 == null || !Number.isFinite(tp1)) return 0;
  const lots = riskUsd / (slPips * simUsdPerEnginePip);
  if (outcome === 'LOSS') return -riskUsd;
  const tpPips = Math.abs(tp1 - row.entry) / pipSize;
  return tpPips * simUsdPerEnginePip * lots;
}

function main() {
  const endT = Date.UTC(2026, 4, 13, 20, 0, 0);
  const base = buildSyntheticMarketBundle({
    anchorClose: 3288.5,
    anchorTimeMs: endT,
    count: THREE_YR_BARS,
    seed: 0x58415544,
    volatilityMul: 0.26,
  });

  const cfg = {
    ...defaultBilshenzConfig,
    journalSlPips: 50,
    currentSpreadPips: 1.2,
    newsActive: false,
    nfpBlackout: false,
    geoRisk: 'LOW' as const,
    showHistory: true,
    showHistoryMode: false,
    p3MinRewardRisk: 0.54,
  };

  const tSr = Date.now();
  const srSeries = replaySrBarByBar(base.m30, cfg);
  console.error(`replaySrBarByBar: ${((Date.now() - tSr) / 1000).toFixed(2)}s`);

  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;

  const t0 = Date.now();
  const m30 = base.m30;
  for (let idx = WARMUP; idx < m30.length; idx++) {
    const bar = m30[idx];
    const ymd = nyYmdKey(bar.t);
    if (nyDay !== ymd) {
      nyDay = ymd;
      tradeCount = 0;
    }

    journalRows = resolveJournalOnBar(journalRows, bar, idx);
    const sr = srSeries[idx];
    const range = leftSideScan({
      immRes: sr.nearestRes,
      immSup: sr.nearestSup,
      close: bar.c,
      pip: cfg.pipSize,
      m30,
      idx,
      minPips: cfg.minRangePips,
      lsBars: cfg.leftScanBars,
      lsChopMax: cfg.leftScanMaxChop,
    });
    const wick = wickMetricsAt(m30, idx);
    const session = sessionFromUtcEpochMs(bar.t);
    const risk = riskForBar(bar, bar.c, cfg);
    const hasStructure = sr.nearestRes != null || sr.nearestSup != null;
    const { gates, signals: rawSignals } = computeGatesAndSignals({
      cfg,
      inSession: session.inSession,
      hasStructure,
      structureOk: hasStructure,
      dailyTradeCount: tradeCount,
      risk,
      bias: neutralBias,
      sr,
      range,
      wick,
      m30,
      idx,
    });
    const sessionOk = session.inSession || cfg.showHistory;
    const signals = applyJournalSignalThrottle({
      cfg,
      m30,
      idx,
      signals: rawSignals,
      journalRows,
      aggregateDeps: {
        sessionOk,
        maxTradesReached: gates.maxTradesReached,
        newsActive: cfg.newsActive,
        nfpBlackout: cfg.nfpBlackout,
        spreadBlocked: risk.spreadBlocked,
        dxyBlocksBuy: risk.dxyBlocksBuy,
        athZoneBlocked: risk.athZoneBlocked,
        geoHigh: risk.geoHigh,
      },
    });

    const sig = signals.anyBuy || signals.anySell;
    if (sig && lastBarSig !== bar.t) {
      if (tradeCount < cfg.maxDailyTrades) {
        const slBuffer = cfg.journalSlPips * cfg.pipSize;
        const trade = buildTradeRecommendation({
          cfg,
          session,
          gates,
          risk,
          signals,
          close: bar.c,
          nearestRes: sr.nearestRes,
          nearestSup: sr.nearestSup,
          slBuffer,
          bullClean: range.bullClean,
          bearClean: range.bearClean,
        });
        const sideMatch =
          (trade.side === 'BUY' && signals.anyBuy) || (trade.side === 'SELL' && signals.anySell);
        if (trade.allowed && sideMatch) {
          const row = buildManualJournalEntry({
            trade,
            barIndex: idx,
            timeStr: new Date(bar.t).toISOString(),
          });
          if (row) {
            journalRows = [row, ...journalRows].slice(0, MAX_JOURNAL);
            tradeCount += 1;
          }
        }
      }
      lastBarSig = bar.t;
    }
  }
  const elapsed = ((Date.now() - t0) / 1000).toFixed(2);

  const resolved: TradeJournalRow[] = journalRows.map((r) => {
    if (r.out !== 'OPEN') return r;
    const o = resolveOutcome(m30, r);
    if (o === 'OPEN') return r;
    return { ...r, out: o };
  });

  const wr = winRateFromJournal(resolved);
  const riskUsd = ACCOUNT_USD * RISK_PCT;
  const pip = cfg.pipSize;
  const simPip = cfg.simUsdPerEnginePip;

  let netPnl = 0;
  for (const r of resolved) {
    if (r.out !== 'WIN' && r.out !== 'LOSS') continue;
    netPnl += pnlUsdForClosed(r, r.out, pip, simPip, riskUsd);
  }
  const openN = resolved.filter((r) => r.out === 'OPEN').length;

  const lines: string[] = [];
  lines.push('BILSHENZ — 3-year synthetic XAUUSD M30 backtest (seeded RNG, engine signals)');
  lines.push(`Bars: ${THREE_YR_BARS} M30 (~3 calendar years @ ${M30_PER_DAY}/day)`);
  lines.push(`Warmup bars skipped: ${WARMUP}`);
  lines.push(`Main loop: ${elapsed}s`);
  lines.push('');
  lines.push('DISCLAIMER: No real XAUUSD tick/OHLC file ships with this repo; prices are synthetic.');
  lines.push('Results are for strategy plumbing / regression only — not predictive of live performance.');
  lines.push('');
  lines.push(`Account (notional): $${ACCOUNT_USD.toLocaleString()}`);
  lines.push(`Assumed risk per trade: ${(RISK_PCT * 100).toFixed(2)}% = $${riskUsd.toFixed(2)}`);
  lines.push(`Journal SL distance: ${cfg.journalSlPips} pips (${(cfg.journalSlPips * cfg.pipSize).toFixed(2)} price)`);
  lines.push('');
  lines.push(`CLOSED trades: ${wr.totalWins + wr.totalLosses}  |  Wins: ${wr.totalWins}  |  Losses: ${wr.totalLosses}`);
  lines.push(`Win rate: ${wr.winRatePct.toFixed(2)}%`);
  lines.push(`P1 WR: ${wr.p1Wr.toFixed(1)}%  |  P2 WR: ${wr.p2Wr.toFixed(1)}%  |  P3 WR: ${wr.p3Wr.toFixed(1)}%`);
  lines.push(`Unresolved (OPEN at series end): ${openN}`);
  lines.push(`Modeled net P&L (closed only, fixed $ risk/trade): $${netPnl.toFixed(2)}`);
  lines.push('');
  lines.push('--- Last 50 closed trades (newest first in journal) ---');
  const closedRows = resolved.filter(
    (r): r is TradeJournalRow & { out: 'WIN' | 'LOSS' } => r.out === 'WIN' || r.out === 'LOSS'
  );
  for (const r of closedRows.slice(0, 50)) {
    const pnl = pnlUsdForClosed(r, r.out, pip, simPip, riskUsd);
    lines.push(
      `${r.out.padEnd(4)} ${r.dir} ${r.type} entry=${r.entry.toFixed(2)} SL=${r.sl.toFixed(2)} TP1=${r.tp1?.toFixed(2) ?? '—'} bar=${r.barIndex}  ~$${pnl.toFixed(2)}`
    );
  }

  const outPath = path.join(__dirname, 'backtest-3yr-output.txt');
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log('');
  console.log(`Full report: ${outPath}`);
}

main();
