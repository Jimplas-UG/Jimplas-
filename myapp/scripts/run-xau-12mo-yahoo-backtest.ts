/**
 * 12-month XAU backtest from **your** OHLC file, in this priority:
 *
 * 1. **IC Markets / MT5** — `View → Symbols → Bars` → select XAUUSD, timeframe **M30 or H1** → Request → **Export Bars** CSV  
 *    Pass `--mt5-csv=…` or set `MT5_CSV` / `IC_MARKETS_CSV`. Optional `MT5_CSV_OFFSET_MS` shifts all bar times (broker server vs UTC).
 *
 * 2. **TradingView** — Supercharts **Download chart data…** CSV (`--tradingview-csv` or `TRADINGVIEW_CSV`).
 *
 * 3. **Yahoo `GC=F` 1h** (fallback only; not IC pricing).
 *
 * Default journal window: UTC ending **2026-05-01** (exclusive), length **12 months** (starts 2025-05-01).
 * Override length: `--months=1` … `--window=start` = from **2025-05-01** forward N months; `--window=end` (default) = N months ending **2026-05-01** (exclusive). `--max-daily-trades=N` overrides the NY-day journal cap (default from engine config, usually 5).
 *
 * Examples:
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --mt5-csv ./XAUUSD_M30_export.csv
 *   set IC_MARKETS_CSV=C:\\path\\XAUUSD_H1.csv && npx tsx scripts/run-xau-12mo-yahoo-backtest.ts
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --tradingview-csv ./tv.csv
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --months=1 --window=start
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --max-daily-trades=10
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import type { Bar, BiasSnapshot, RiskSnapshot, TradeJournalRow } from '../engine/types';
import {
  applyJournalSignalThrottle,
  buildBundleFromM30Bars,
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
import { hourlyBarsToM30Series, maybeUpsampleBarsToM30, parseTradingViewChartCsv } from './lib/tradingViewChartCsv';
import { parseIcMarketsMt5ExportBarsCsv } from './lib/mt5ExportBarsCsv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Yahoo chart symbol (COMEX gold continuous); spot XAUUSD is not served for 30m on Yahoo. */
const YAHOO_GOLD = 'GC=F';

const STARTING_EQUITY_USD = 50_000;
const RISK_PCT = 0.01;
const WARMUP = 80;
const MAX_JOURNAL = 200_000;

/** First instant of the default 12m journal window (UTC). Used when `--window=start`. */
const DEFAULT_RANGE_START_MS = Date.UTC(2025, 4, 1, 0, 0, 0, 0);

/** Exclusive UTC end of the default journal window (first instant not counted). Used when `--window=end`. */
const DEFAULT_RANGE_END_MS = Date.UTC(2026, 4, 1, 0, 0, 0, 0);

function utcAddMonths(utcMs: number, deltaMonths: number): number {
  const d = new Date(utcMs);
  d.setUTCFullYear(d.getUTCFullYear(), d.getUTCMonth() + deltaMonths, d.getUTCDate());
  return d.getTime();
}

/** Journal window length from argv `--months=N` (default 12, clamped 1–120). */
function readJournalMonthsFromArgs(): number {
  const argv = process.argv.slice(2);
  let n = 12;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--months=')) {
      const v = parseInt(a.slice('--months='.length), 10);
      if (Number.isFinite(v)) n = v;
    } else if (a === '--months' && argv[i + 1]) {
      const v = parseInt(argv[i + 1]!, 10);
      if (Number.isFinite(v)) n = v;
    }
  }
  return Math.max(1, Math.min(120, n));
}

/** `--window=start` → journal from 2025-05-01; `--window=end` → journal ending 2026-05-01 (default). */
function readWindowAnchorFromArgs(): 'start' | 'end' {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--window=')) {
      const v = a.slice('--window='.length).trim().toLowerCase();
      if (v === 'start') return 'start';
    } else if (a === '--window' && argv[i + 1]) {
      const v = argv[i + 1]!.trim().toLowerCase();
      if (v === 'start') return 'start';
    }
  }
  return 'end';
}

/** Overrides {@link defaultBilshenzConfig.maxDailyTrades} (clamped 1–25). */
function readMaxDailyTradesFromArgs(): number {
  const argv = process.argv.slice(2);
  let n = defaultBilshenzConfig.maxDailyTrades;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--max-daily-trades=')) {
      const v = parseInt(a.slice('--max-daily-trades='.length), 10);
      if (Number.isFinite(v)) n = v;
    } else if (a === '--max-daily-trades' && argv[i + 1]) {
      const v = parseInt(argv[i + 1]!, 10);
      if (Number.isFinite(v)) n = v;
    }
  }
  return Math.max(1, Math.min(25, n));
}

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
    atrMode: 'STANDARD — Risk 1% (backtest sim)',
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

const CHUNK_SEC = 90 * 24 * 3600;

function readMt5CsvPathFromArgs(): string | null {
  const env = (process.env.MT5_CSV ?? process.env.IC_MARKETS_CSV)?.trim();
  if (env) return path.resolve(env);
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--mt5-csv=')) return path.resolve(a.slice('--mt5-csv='.length));
    if (a.startsWith('--ic-markets-csv=')) return path.resolve(a.slice('--ic-markets-csv='.length));
    if (a === '--mt5-csv' && argv[i + 1]) return path.resolve(argv[i + 1]!);
    if (a === '--ic-markets-csv' && argv[i + 1]) return path.resolve(argv[i + 1]!);
  }
  return null;
}

function readTradingViewCsvPathFromArgs(): string | null {
  const env = process.env.TRADINGVIEW_CSV?.trim();
  if (env) return path.resolve(env);
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--tradingview-csv=')) return path.resolve(a.slice('--tradingview-csv='.length));
    if (a === '--tradingview-csv' && argv[i + 1]) return path.resolve(argv[i + 1]!);
  }
  return null;
}

async function fetchYahoo1hGoldBars(period1Sec: number, period2Sec: number): Promise<Bar[]> {
  const byT = new Map<number, Bar>();
  for (let a = period1Sec; a < period2Sec; ) {
    const b = Math.min(a + CHUNK_SEC, period2Sec);
    if (a >= b) break;
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(YAHOO_GOLD)}?useYfid=true&interval=1h&period1=${a}&period2=${b}`;
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; BilshenzBacktest/1)' } });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Yahoo HTTP ${res.status}: ${txt.slice(0, 300)}`);
    }
    const j: unknown = await res.json();
    const chart = j as { chart?: { result?: Array<{ timestamp?: number[]; indicators?: { quote?: Array<Record<string, (number | null)[]>> } }> } };
    const r0 = chart.chart?.result?.[0];
    const ts = r0?.timestamp;
    const q = r0?.indicators?.quote?.[0];
    if (!ts?.length || !q) {
      console.warn(`Yahoo: no bars in chunk ${a}..${b}`);
    } else {
      for (let i = 0; i < ts.length; i++) {
        const o = q.open?.[i];
        const h = q.high?.[i];
        const l = q.low?.[i];
        const c = q.close?.[i];
        if (o == null || h == null || l == null || c == null || !Number.isFinite(o + h + l + c)) continue;
        const tSec = ts[i]!;
        byT.set(tSec, { t: tSec * 1000, o, h, l, c });
      }
    }
    a = b;
    await new Promise((r) => setTimeout(r, 250));
  }
  return [...byT.values()].sort((x, y) => x.t - y.t);
}

async function main() {
  const journalMonths = readJournalMonthsFromArgs();
  const windowAnchor = readWindowAnchorFromArgs();
  const maxDailyTrades = readMaxDailyTradesFromArgs();
  let RANGE_START_MS: number;
  let RANGE_END_MS: number;
  if (windowAnchor === 'start') {
    RANGE_START_MS = DEFAULT_RANGE_START_MS;
    RANGE_END_MS = utcAddMonths(RANGE_START_MS, journalMonths);
  } else {
    RANGE_END_MS = DEFAULT_RANGE_END_MS;
    RANGE_START_MS = utcAddMonths(RANGE_END_MS, -journalMonths);
  }
  const FETCH_START_MS = utcAddMonths(RANGE_START_MS, -2);

  const mt5Csv = readMt5CsvPathFromArgs();
  const tvCsv = readTradingViewCsvPathFromArgs();
  let m30All: Bar[];
  let dataNote: string;

  if (mt5Csv) {
    if (!fs.existsSync(mt5Csv)) throw new Error(`MT5 / IC Markets CSV not found: ${mt5Csv}`);
    console.error(`Loading IC Markets (MT5 Export Bars) CSV: ${mt5Csv}`);
    const raw = parseIcMarketsMt5ExportBarsCsv(fs.readFileSync(mt5Csv, 'utf8'));
    m30All = maybeUpsampleBarsToM30(raw);
    if (m30All.length < WARMUP + 100) {
      throw new Error(`Too few M30 bars after MT5 CSV parse (${m30All.length}). Request full range in Symbols → Bars before export.`);
    }
    dataNote = `IC Markets MT5 export: ${path.basename(mt5Csv)} (${raw.length} rows → ${m30All.length} M30 bars)`;
  } else if (tvCsv) {
    if (!fs.existsSync(tvCsv)) throw new Error(`TradingView CSV not found: ${tvCsv}`);
    console.error(`Loading TradingView chart export: ${tvCsv}`);
    const raw = parseTradingViewChartCsv(fs.readFileSync(tvCsv, 'utf8'));
    m30All = maybeUpsampleBarsToM30(raw);
    if (m30All.length < WARMUP + 100) {
      throw new Error(`Too few M30 bars after CSV parse (${m30All.length}). Load more history in TV before export.`);
    }
    dataNote = `TradingView chart export: ${path.basename(tvCsv)} (${raw.length} rows → ${m30All.length} M30 bars)`;
  } else {
    const fetchEndMs = RANGE_END_MS + 24 * 3600 * 1000;
    const p1 = Math.floor(FETCH_START_MS / 1000);
    const p2 = Math.floor(fetchEndMs / 1000);
    console.error(
      'No MT5/IC CSV (--mt5-csv / MT5_CSV / IC_MARKETS_CSV) or TradingView CSV; using Yahoo GC=F 1h.'
    );
    console.error(
      `Fetching ${YAHOO_GOLD} 1h from ${new Date(FETCH_START_MS).toISOString()} to ${new Date(fetchEndMs).toISOString()} (upsampling to M30) ...`
    );
    const hourly = await fetchYahoo1hGoldBars(p1, p2);
    m30All = hourlyBarsToM30Series(hourly);
    if (m30All.length < WARMUP + 100) {
      throw new Error(`Too few M30 bars from Yahoo (${m30All.length}). Check network or symbol.`);
    }
    dataNote = `Yahoo ${YAHOO_GOLD} 1h → ${m30All.length} M30 bars (upsampled)`;
  }

  const base = buildBundleFromM30Bars(m30All);
  const cfg = {
    ...defaultBilshenzConfig,
    maxDailyTrades,
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
  console.error(`replaySrBarByBar (${m30All.length} bars): ${((Date.now() - tSr) / 1000).toFixed(2)}s`);

  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;

  const m30 = base.m30;
  const t0 = Date.now();
  for (let idx = WARMUP; idx < m30.length; idx++) {
    const bar = m30[idx]!;
    journalRows = resolveJournalOnBar(journalRows, bar, idx);

    if (bar.t < RANGE_START_MS || bar.t >= RANGE_END_MS) continue;

    const ymd = nyYmdKey(bar.t);
    if (nyDay !== ymd) {
      nyDay = ymd;
      tradeCount = 0;
    }

    const sr = srSeries[idx]!;
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

  const inRange = (r: TradeJournalRow) => {
    const bi = r.barIndex;
    if (bi < 0 || bi >= m30.length) return false;
    const t = m30[bi]!.t;
    return t >= RANGE_START_MS && t < RANGE_END_MS;
  };

  const resolvedInRange = resolved.filter(inRange);
  const wr = winRateFromJournal(resolvedInRange);

  const pip = cfg.pipSize;
  const simPip = cfg.simUsdPerEnginePip;
  const closedRows = resolvedInRange.filter((r) => r.out === 'WIN' || r.out === 'LOSS');
  const closedChrono = [...closedRows].sort((a, b) => a.barIndex - b.barIndex);
  const { endEquity, series } = equityAfterAutoTrades(closedChrono, pip, simPip, STARTING_EQUITY_USD);

  const openN = resolvedInRange.filter((r) => r.out === 'OPEN').length;
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
  lines.push(`BILSHENZ — ${journalMonths}-month XAU backtest (M30 engine, journal + throttle)`);
  lines.push(`Data: ${dataNote}`);
  lines.push(`Journal window mode: ${windowAnchor} (${journalMonths} month(s))`);
  lines.push(`Max daily trades (NY day cap): ${maxDailyTrades}`);
  lines.push(
    `Window (journal entries): ${new Date(RANGE_START_MS).toISOString().slice(0, 10)} → ${new Date(RANGE_END_MS).toISOString().slice(0, 10)} exclusive end`
  );
  lines.push(`M30 bars loaded: ${m30All.length}  |  Main loop: ${elapsed}s`);
  lines.push('');
  lines.push(`Starting equity: $${STARTING_EQUITY_USD.toLocaleString()}`);
  lines.push(`Ending equity (closed trades, compounding ${(RISK_PCT * 100).toFixed(2)}%): $${endEquity.toFixed(2)}`);
  lines.push(`Max drawdown (on equity curve): $${maxDd.toFixed(2)}`);
  lines.push('');
  lines.push(`Trades opened in window: ${resolvedInRange.length}  (OPEN at end: ${openN})`);
  lines.push(`Closed in window: ${wr.totalWins + wr.totalLosses}  |  Wins: ${wr.totalWins}  |  Losses: ${wr.totalLosses}`);
  lines.push(`Win rate (closed): ${wr.winRatePct.toFixed(2)}%`);
  lines.push(`P1 / P2 / P3 WR: ${wr.p1Wr.toFixed(1)}% / ${wr.p2Wr.toFixed(1)}% / ${wr.p3Wr.toFixed(1)}%`);

  const outPath = path.join(__dirname, `backtest-xau-${journalMonths}mo-output.txt`);
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log('');
  console.log(`Full report: ${outPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
