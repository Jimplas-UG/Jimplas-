/**
 * 3-month M30 backtest: same auto-trade path as the app (signal → journal row on bar,
 * NY-day maxDailyTrades cap, resolveJournalOnBar TP/SL). Starting equity $50,000;
 * compounding risk = 0.5% of current equity per closed trade (chronological order).
 *
 * Data: seeded synthetic XAU-like bundle (no real OHLC in repo).
 *
 * Run from myapp: npx tsx scripts/run-3mo-autotrade-backtest.ts
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

const STARTING_EQUITY_USD = 50_000;
const RISK_PCT = 0.005;
const M30_PER_DAY = 48;
/** Three calendar months at ~30.4375 days/month (365.25/12). */
const THREE_MO_BARS = Math.floor(3 * (365.25 / 12) * M30_PER_DAY);
const WARMUP = 80;
const MAX_JOURNAL = 50_000;

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
  if (slPips <= 0 || !Number.isFinite(row.tp1)) return 0;
  const lots = riskUsd / (slPips * simUsdPerEnginePip);
  if (outcome === 'LOSS') return -riskUsd;
  const tpPips = Math.abs(row.tp1 - row.entry) / pipSize;
  return tpPips * simUsdPerEnginePip * lots;
}

/** Auto-trade equity path: each trade risks RISK_PCT × equity before that trade closes. */
function equityAfterAutoTrades(
  closedChrono: TradeJournalRow[],
  pipSize: number,
  simUsdPerEnginePip: number,
  startEquity: number
): { endEquity: number; series: { bar: number; equity: number; pnl: number }[] } {
  let equity = startEquity;
  const series: { bar: number; equity: number; pnl: number }[] = [];
  for (const r of closedChrono) {
    if (r.out !== 'WIN' && r.out !== 'LOSS') continue;
    const riskUsd = equity * RISK_PCT;
    const pnl = pnlUsdForClosed(r, r.out, pipSize, simUsdPerEnginePip, riskUsd);
    equity += pnl;
    series.push({ bar: r.barIndex, equity, pnl });
  }
  return { endEquity: equity, series };
}

function main() {
  const endT = Date.UTC(2026, 4, 13, 20, 0, 0);
  const base = buildSyntheticMarketBundle({
    anchorClose: 3288.5,
    anchorTimeMs: endT,
    count: THREE_MO_BARS,
    seed: 0x5841554d, // 'XAU' + month variant
    volatilityMul: 0.26,
  });

  const cfg = {
    ...defaultBilshenzConfig,
    journalSlPips: 50,
    currentSpreadPips: 1.2,
    newsActive: false,
    nfpBlackout: false,
    geoRisk: 'LOW' as const,
    /** Headless replay: allow signals outside London/NY (matches signalEngine `showHistory`). */
    showHistory: true,
    showHistoryMode: false,
    /** 50-pip SL and 28-pip max TP → R:R ~0.56; default P3 floor would reject every P3. */
    p3MinRewardRisk: 0.54,
  };

  const tSr = Date.now();
  const srSeries = replaySrBarByBar(base.m30, cfg);
  console.error(`replaySrBarByBar (${THREE_MO_BARS} bars): ${((Date.now() - tSr) / 1000).toFixed(2)}s`);

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
  const pip = cfg.pipSize;
  const simPip = cfg.simUsdPerEnginePip;

  const closedRows = resolved.filter((r) => r.out === 'WIN' || r.out === 'LOSS');
  const closedChrono = [...closedRows].sort((a, b) => a.barIndex - b.barIndex);
  const { endEquity, series } = equityAfterAutoTrades(closedChrono, pip, simPip, STARTING_EQUITY_USD);

  const openN = resolved.filter((r) => r.out === 'OPEN').length;
  let peak = STARTING_EQUITY_USD;
  let maxDd = 0;
  let run = STARTING_EQUITY_USD;
  for (const s of series) {
    run = s.equity;
    if (run > peak) peak = run;
    const dd = peak - run;
    if (dd > maxDd) maxDd = dd;
  }

  const lines: string[] = [];
  lines.push('BILSHENZ — 3-month auto-trade backtest (synthetic XAUUSD M30, bot logic)');
  lines.push(`Bars: ${THREE_MO_BARS} M30 (~3 calendar months @ ${M30_PER_DAY}/day)`);
  lines.push(`Warmup skipped: ${WARMUP}  |  Main loop: ${elapsed}s`);
  lines.push('');
  lines.push('Mode: auto — on each signal bar, one journal entry (same as app TICK), max 3 trades/NY day.');
  lines.push('Sizing: each closed trade risks 0.5% of equity at that trade (compounding), then P&L applied.');
  lines.push(`Journal SL: ${cfg.journalSlPips} pips from entry (${(cfg.journalSlPips * cfg.pipSize).toFixed(2)} price).`);
  lines.push('');
  lines.push(`Starting equity: $${STARTING_EQUITY_USD.toLocaleString()}`);
  lines.push(`Ending equity:   $${endEquity.toFixed(2)}`);
  lines.push(`Net change:      $${(endEquity - STARTING_EQUITY_USD).toFixed(2)}`);
  lines.push(`Max drawdown (peak-to-trough on equity curve): $${maxDd.toFixed(2)}`);
  lines.push('');
  lines.push(`Closed trades: ${wr.totalWins + wr.totalLosses}  |  W: ${wr.totalWins}  L: ${wr.totalLosses}`);
  lines.push(`Win rate: ${wr.winRatePct.toFixed(2)}%`);
  lines.push(`P1 / P2 / P3 WR: ${wr.p1Wr.toFixed(1)}% / ${wr.p2Wr.toFixed(1)}% / ${wr.p3Wr.toFixed(1)}%`);
  lines.push(`Still OPEN at end: ${openN}`);
  lines.push('');
  lines.push('--- Last 30 closed trades (chronological, oldest → newest in file order) ---');
  let eqWalk = STARTING_EQUITY_USD;
  const rowLines: string[] = [];
  for (const r of closedChrono) {
    const ru = eqWalk * RISK_PCT;
    const pnl = pnlUsdForClosed(r, r.out as 'WIN' | 'LOSS', pip, simPip, ru);
    eqWalk += pnl;
    rowLines.push(
      `${r.out} ${r.dir} ${r.type} bar=${r.barIndex} entry=${r.entry.toFixed(2)} TP1=${r.tp1?.toFixed(2) ?? '—'}  pnl=$${pnl.toFixed(2)}  equity~$${eqWalk.toFixed(2)}`
    );
  }
  lines.push(...rowLines.slice(-30));

  const outPath = path.join(__dirname, 'backtest-3mo-autotrade-output.txt');
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log('');
  console.log(`Full report: ${outPath}`);
}

main();
