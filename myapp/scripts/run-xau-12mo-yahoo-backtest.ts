/**
 * 12-month XAU backtest from **your** OHLC file, in this priority:
 *
 * 1. **IC Markets / MT5** — `View → Symbols → Bars` → select XAUUSD, timeframe **M30 or H1** → Request → **Export Bars** CSV  
 *    Pass `--mt5-csv=…` or set `MT5_CSV` / `IC_MARKETS_CSV`. Optional `MT5_CSV_OFFSET_MS` shifts all bar times (broker server vs UTC).
 *
 * 2. **TradingView** — Supercharts **Download chart data…** CSV (`--tradingview-csv` or `TRADINGVIEW_CSV`).
 *
 * 3. **Live MT5 Python API** — `--mt5-api=http://127.0.0.1:8765` or `MT5_API_URL` (terminal logged in, `npm run mt5-api`).
 *
 * 4. **Yahoo `GC=F` 1h** (fallback only; not broker pricing).
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
  buildBundleFromM30Bars,
  computeBias,
  computeRisk,
  defaultBilshenzConfig,
  pushJournalRow,
  resolveJournalOnBar,
  resolveOutcomeForward,
  sliceMarketBundleToM30End,
  winRateFromJournal,
} from '../engine';
import { atr, lastFinite } from '../engine/indicators';
import { nyYmdKey, sessionFromUtcEpochMs } from '../engine/sessionEngine';
import { replaySrBarByBar } from '../engine/srEngine';
import { computeGatesAndSignalsJimplasFluidity } from '../engine/jimplasFluiditySignalEngine';
import { m30ToM15Bars } from '../engine/m15Bars';
import { riskScaleForSlTpMismatch } from '../engine/tradeGeometry';
import type { BilshenzEngineConfig } from '../engine/types';
import { leftSideScanPineV5 } from '../engine/pineV5SignalEngine';
import { hourlyBarsToM30Series, maybeUpsampleBarsToM30, parseTradingViewChartCsv } from './lib/tradingViewChartCsv';
import { parseIcMarketsMt5ExportBarsCsv } from './lib/mt5ExportBarsCsv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Yahoo chart symbol (COMEX gold continuous); spot XAUUSD is not served for 30m on Yahoo. */
const YAHOO_GOLD = 'GC=F';

let STARTING_EQUITY_USD = 50_000;
let RISK_PCT = 0.01;
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

function readEquityFromArgs(): number {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--equity=')) {
      const v = parseFloat(a.slice('--equity='.length));
      if (Number.isFinite(v) && v > 0) return v;
    } else if (a === '--equity' && argv[i + 1]) {
      const v = parseFloat(argv[i + 1]!);
      if (Number.isFinite(v) && v > 0) return v;
    }
  }
  const env = process.env.BACKTEST_EQUITY;
  if (env) {
    const v = parseFloat(env);
    if (Number.isFinite(v) && v > 0) return v;
  }
  return STARTING_EQUITY_USD;
}

function readRiskPctFromArgs(): number {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--risk-pct=')) {
      const v = parseFloat(a.slice('--risk-pct='.length));
      if (Number.isFinite(v) && v > 0) return v / 100;
    } else if (a === '--risk-pct' && argv[i + 1]) {
      const v = parseFloat(argv[i + 1]!);
      if (Number.isFinite(v) && v > 0) return v / 100;
    }
  }
  return RISK_PCT;
}

type Mt5BrokerContext = {
  equity: number | null;
  balance: number | null;
  spreadPips: number;
  usdPerPipPerLot: number;
  server: string | null;
  currency: string | null;
};

async function fetchMt5BrokerContext(
  baseUrl: string,
  symbol: string,
  pipSize: number,
  fallbackUsdPerPip: number
): Promise<Mt5BrokerContext> {
  const b = baseUrl.replace(/\/$/, '');
  let equity: number | null = null;
  let balance: number | null = null;
  let server: string | null = null;
  let currency: string | null = null;
  try {
    const res = await fetch(`${b}/api/status`);
    if (res.ok) {
      const j = (await res.json()) as {
        connected?: boolean;
        account?: { equity?: number; balance?: number; server?: string; currency?: string };
      };
      if (j.connected && j.account) {
        server = j.account.server ?? null;
        currency = j.account.currency ?? null;
        const eq = j.account.equity;
        const bal = j.account.balance;
        if (eq != null && Number.isFinite(eq) && eq > 0) equity = eq;
        if (bal != null && Number.isFinite(bal) && bal > 0) balance = bal;
      }
    }
  } catch {
    /* offline */
  }

  let spreadPips = defaultBilshenzConfig.currentSpreadPips;
  let usdPerPipPerLot = fallbackUsdPerPip;
  try {
    const specRes = await fetch(`${b}/api/symbol/${encodeURIComponent(symbol)}?pip_size=${pipSize}`);
    if (specRes.ok) {
      const spec = (await specRes.json()) as {
        spread_pips?: number;
        usd_per_pip_per_lot?: number;
      };
      if (spec.spread_pips != null && Number.isFinite(spec.spread_pips) && spec.spread_pips > 0) {
        spreadPips = spec.spread_pips;
      }
      if (
        spec.usd_per_pip_per_lot != null &&
        Number.isFinite(spec.usd_per_pip_per_lot) &&
        spec.usd_per_pip_per_lot > 0
      ) {
        usdPerPipPerLot = spec.usd_per_pip_per_lot;
      }
    }
  } catch {
    /* spec endpoint optional on older API builds */
  }

  return { equity, balance, spreadPips, usdPerPipPerLot, server, currency };
}

type RealisticCosts = {
  spreadPips: number;
  slippagePipsPerSide: number;
  /** Loss distance in pips (chart SL or capped broker SL). */
  lossSlPips: (structural: number, sizing: number) => number;
};

function readRealisticFromArgs(): boolean {
  return process.argv.slice(2).some((a) => a === '--realistic' || a === '--closer');
}

/** When set, losses cap at this SL distance (live: size on 20p, place broker SL at journal distance). */
function readBrokerSlPipsFromArgs(): number | null {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--broker-sl-pips=')) {
      const v = parseFloat(a.slice('--broker-sl-pips='.length));
      if (Number.isFinite(v) && v > 0) return v;
    } else if (a === '--broker-sl-pips' && argv[i + 1]) {
      const v = parseFloat(argv[i + 1]!);
      if (Number.isFinite(v) && v > 0) return v;
    }
  }
  return null;
}

function readSlippagePipsFromArgs(): number {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--slippage-pips=')) {
      const v = parseFloat(a.slice('--slippage-pips='.length));
      if (Number.isFinite(v) && v >= 0) return v;
    } else if (a === '--slippage-pips' && argv[i + 1]) {
      const v = parseFloat(argv[i + 1]!);
      if (Number.isFinite(v) && v >= 0) return v;
    }
  }
  return 0.4;
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

function riskForBarSlice(
  sub: ReturnType<typeof sliceMarketBundleToM30End>,
  cfg: typeof defaultBilshenzConfig
): RiskSnapshot {
  const m30 = sub.m30;
  const close = m30[m30.length - 1]!.c;
  const atrArr = atr(m30, cfg.atrLen);
  const atrVal = lastFinite(atrArr);
  const dxy = sub.dxyCloseSeries;
  const dxyClose = dxy.length ? dxy[dxy.length - 1]! : null;
  const dxyClose3 = dxy.length > 3 ? dxy[dxy.length - 4]! : dxyClose;
  const uy = sub.us10yCloseSeries;
  const us10yClose = uy.length ? uy[uy.length - 1]! : null;
  return computeRisk(m30, sub.h4, cfg, atrVal, dxyClose ?? null, dxyClose3 ?? null, us10yClose ?? null, close);
}

function biasForBarSlice(sub: ReturnType<typeof sliceMarketBundleToM30End>): BiasSnapshot {
  const m30 = sub.m30;
  const close = m30[m30.length - 1]!.c;
  return computeBias(sub.h4, sub.d1, close);
}

function rewardMultiple(row: TradeJournalRow, pipSize: number, cfg: BilshenzEngineConfig): number {
  const slPips = Math.abs(row.entry - row.sl) / pipSize;
  const tpPips = Math.abs(row.tp1! - row.entry) / pipSize;
  if (slPips <= 0) return 0;
  const raw = tpPips / slPips;
  const cap = cfg.tp1MaxRewardPips / slPips;
  return Math.min(Math.max(raw, 0.35), Math.max(cap * 1.05, 0.5));
}

function pnlUsdForClosed(
  row: TradeJournalRow,
  outcome: 'WIN' | 'LOSS' | 'HALF_LOSS',
  pipSize: number,
  simUsdPerEnginePip: number,
  riskUsd: number,
  cfg: BilshenzEngineConfig,
  realistic?: RealisticCosts | null
): number {
  const structuralSl = Math.abs(row.entry - row.sl) / pipSize;
  if (structuralSl <= 0 || !Number.isFinite(row.tp1)) return 0;
  const sizingSl =
    cfg.journalSizingSlPips > 0 ? cfg.journalSizingSlPips : structuralSl;
  const scale = cfg.riskScaleWideStops ? riskScaleForSlTpMismatch(structuralSl, cfg) : 1;
  const adjRisk = riskUsd * scale;
  const lots = adjRisk / (sizingSl * simUsdPerEnginePip);
  const pipUsd = simUsdPerEnginePip;

  if (realistic) {
    const rtPips = realistic.spreadPips + realistic.slippagePipsPerSide * 2;
    const frictionUsd = rtPips * pipUsd * lots;
    if (outcome === 'LOSS') {
      const lossPips = realistic.structuralLossOnSl ? structuralSl : sizingSl;
      return -lossPips * pipUsd * lots - frictionUsd;
    }
    if (outcome === 'HALF_LOSS') {
      const lossPips = realistic.structuralLossOnSl ? structuralSl * 0.5 : sizingSl * 0.5;
      return -lossPips * pipUsd * lots - frictionUsd;
    }
    const tpPips = Math.abs(row.tp1! - row.entry) / pipSize;
    const netTp = Math.max(0, tpPips - rtPips);
    return netTp * pipUsd * lots;
  }

  if (outcome === 'LOSS') return -adjRisk;
  if (outcome === 'HALF_LOSS') return -adjRisk * 0.5;
  const tpPips = Math.abs(row.tp1! - row.entry) / pipSize;
  return tpPips * pipUsd * lots;
}

function equityAfterAutoTrades(
  closedChrono: TradeJournalRow[],
  pipSize: number,
  simUsdPerEnginePip: number,
  startEquity: number,
  cfg: BilshenzEngineConfig,
  realistic?: RealisticCosts | null
): { endEquity: number; series: { bar: number; equity: number; pnl: number }[] } {
  let equity = startEquity;
  const series: { bar: number; equity: number; pnl: number }[] = [];
  for (const r of closedChrono) {
    if (r.out !== 'WIN' && r.out !== 'LOSS' && r.out !== 'HALF_LOSS') continue;
    const riskUsd = equity * RISK_PCT;
    const pnl = pnlUsdForClosed(r, r.out, pipSize, simUsdPerEnginePip, riskUsd, cfg, realistic);
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

function readMt5ApiUrlFromArgs(): string | null {
  const env = process.env.MT5_API_URL?.trim();
  if (env) return env.replace(/\/$/, '');
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--mt5-api=')) return a.slice('--mt5-api='.length).replace(/\/$/, '');
    if (a === '--mt5-api' && argv[i + 1]) return argv[i + 1]!.replace(/\/$/, '');
  }
  return null;
}

async function fetchMt5ApiM30Bars(
  baseUrl: string,
  symbol: string,
  fromMs: number,
  toMs: number
): Promise<Bar[]> {
  const b = baseUrl.replace(/\/$/, '');
  const st = await fetch(`${b}/api/status`);
  if (!st.ok) throw new Error(`MT5 API status HTTP ${st.status}`);
  const sj = (await st.json()) as { connected?: boolean };
  if (!sj.connected) throw new Error('MT5 API not connected — open MT5 and CONNECT in Profile');

  const url = `${b}/api/bars/${encodeURIComponent(symbol)}?from_ms=${fromMs}&to_ms=${toMs}`;
  const res = await fetch(url);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`MT5 bars HTTP ${res.status}: ${txt.slice(0, 300)}`);
  }
  const j = (await res.json()) as { bars?: Bar[]; symbol?: string };
  const bars = Array.isArray(j.bars) ? j.bars : [];
  return bars.filter((x) => Number.isFinite(x.t) && Number.isFinite(x.c)).sort((a, b) => a.t - b.t);
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
  const mt5Api = readMt5ApiUrlFromArgs();
  const useMt5Equity = process.argv.includes('--equity-from-mt5');
  const realisticMode = readRealisticFromArgs();
  const slippagePips = readSlippagePipsFromArgs();
  const brokerSlCap = readBrokerSlPipsFromArgs();
  let mt5Broker: Mt5BrokerContext | null = null;
  const symbol = process.env.MT5_SYMBOL?.trim() || 'XAUUSD';

  if (useMt5Equity && mt5Api) {
    mt5Broker = await fetchMt5BrokerContext(
      mt5Api,
      symbol,
      defaultBilshenzConfig.pipSize,
      defaultBilshenzConfig.simUsdPerEnginePip
    );
    const eq = mt5Broker.equity ?? mt5Broker.balance;
    if (eq != null) STARTING_EQUITY_USD = eq;
    else console.error('MT5 connected but no equity in /api/status — using default starting equity');
  } else {
    STARTING_EQUITY_USD = readEquityFromArgs();
  }
  RISK_PCT = readRiskPctFromArgs();
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
  } else if (mt5Api) {
    const fetchEndMs = RANGE_END_MS + 24 * 3600 * 1000;
    if (realisticMode && !mt5Broker) {
      mt5Broker = await fetchMt5BrokerContext(
        mt5Api,
        symbol,
        defaultBilshenzConfig.pipSize,
        defaultBilshenzConfig.simUsdPerEnginePip
      );
    }
    console.error(
      `Fetching ${symbol} M30 from MT5 API ${mt5Api} (${new Date(FETCH_START_MS).toISOString()} → ${new Date(fetchEndMs).toISOString()}) ...`
    );
    m30All = await fetchMt5ApiM30Bars(mt5Api, symbol, FETCH_START_MS, fetchEndMs);
    if (m30All.length < WARMUP + 100) {
      throw new Error(
        `Too few M30 bars from MT5 API (${m30All.length}). Open XAUUSD chart in MT5 and scroll/load more history.`
      );
    }
    dataNote = `MT5 live API ${mt5Api} — ${symbol} M30 (${m30All.length} bars)`;
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
    usePineV5: true,
    enableP1: true,
    enableP2: true,
    enableP3: true,
    journalSlPips: 2,
    currentSpreadPips: 1.5,
    newsActive: false,
    nfpBlackout: false,
    geoRisk: 'LOW' as const,
    showHistory: true,
    showHistoryMode: false,
    useLegacyTpClampOnly: true,
    p2UseStrictFilters: false,
    enableM15AdverseExit: false,
    tpClampMinRiskReward: 1,
    tpClampSlFraction: 0,
    maxSlPipsForEntry: 0,
    tp1MinRewardPips: 10,
    tp1MaxRewardPips: 28,
    journalSizingSlPips: 20,
    riskScaleWideStops: false,
  };

  const tSr = Date.now();
  const srSeries = replaySrBarByBar(base.m30, cfg);
  console.error(`replaySrBarByBar (${m30All.length} bars): ${((Date.now() - tSr) / 1000).toFixed(2)}s`);

  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;

  const m30 = base.m30;
  const m15 = m30ToM15Bars(m30);
  const journalCtx = { m30, m15, cfg };
  const fullBundle = base;
  const t0 = Date.now();
  for (let idx = WARMUP; idx < m30.length; idx++) {
    const bar = m30[idx]!;
    journalRows = resolveJournalOnBar(journalRows, bar, idx, journalCtx);

    if (bar.t < RANGE_START_MS || bar.t >= RANGE_END_MS) continue;

    const ymd = nyYmdKey(bar.t);
    if (nyDay !== ymd) {
      nyDay = ymd;
      tradeCount = 0;
    }

    const sr = srSeries[idx]!;
    const sub = sliceMarketBundleToM30End(fullBundle, idx);
    const bias = biasForBarSlice(sub);
    const risk = riskForBarSlice(sub, cfg);
    const hasStructure = !(sr.r1 == null && sr.r2 == null && sr.r3 == null && sr.s1 == null && sr.s2 == null && sr.s3 == null);
    const range = leftSideScanPineV5({
      nearestRes: sr.nearestRes,
      nearestSup: sr.nearestSup,
      close: bar.c,
      pip: cfg.pipSize,
      m30,
      idx,
      minPips: cfg.minRangePips,
    });
    const session = sessionFromUtcEpochMs(bar.t);
    const prevSession = idx >= 1 ? sessionFromUtcEpochMs(m30[idx - 1]!.t) : session;
    const atrArr = atr(m30, cfg.atrLen);
    const atrVal = lastFinite(atrArr);
    const { signals, levels } = computeGatesAndSignalsJimplasFluidity({
      cfg,
      inSession: session.inSession,
      session,
      prevInSession: prevSession.inSession,
      hasStructure,
      structureOk: hasStructure,
      dailyTradeCount: tradeCount,
      risk,
      bias,
      sr,
      m30,
      h4: sub.h4,
      idx,
      atrVal,
    });

    const sig = signals.anyBuy || signals.anySell;
    if (sig && lastBarSig !== bar.t && tradeCount < cfg.maxDailyTrades) {
      const slBuffer = cfg.journalSlPips * cfg.pipSize;
      const prev = { rows: journalRows, count: journalRows.length };
      const next = pushJournalRow(
        prev,
        {
          anyBuy: signals.anyBuy,
          anySell: signals.anySell,
          barIndex: idx,
          timeStr: new Date(bar.t).toISOString(),
          close: bar.c,
          nearestRes: sr.nearestRes,
          nearestSup: sr.nearestSup,
          slBuffer,
          barLow: bar.l,
          barHigh: bar.h,
          signals,
          cfg,
          setupLevels: levels,
          m30,
        },
        { maxJournalRows: MAX_JOURNAL }
      );
      journalRows = next.rows;
      tradeCount += 1;
      lastBarSig = bar.t;
    }
  }
  const elapsed = ((Date.now() - t0) / 1000).toFixed(2);

  const resolved: TradeJournalRow[] = journalRows.map((r) => {
    if (r.out !== 'OPEN') return r;
    return resolveOutcomeForward(m30, m15, r, cfg);
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
  let simPip = cfg.simUsdPerEnginePip;
  if (realisticMode && mt5Broker?.usdPerPipPerLot) {
    simPip = mt5Broker.usdPerPipPerLot;
  }
  const realisticCosts: RealisticCosts | null = realisticMode
    ? {
        spreadPips: mt5Broker?.spreadPips ?? cfg.currentSpreadPips,
        slippagePipsPerSide: slippagePips,
        lossSlPips: (structural, sizing) => {
          if (brokerSlCap != null) return Math.min(structural, brokerSlCap);
          return structural;
        },
      }
    : null;

  const closedRows = resolvedInRange.filter((r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS');
  const closedChrono = [...closedRows].sort((a, b) => a.barIndex - b.barIndex);
  const { endEquity, series } = equityAfterAutoTrades(
    closedChrono,
    pip,
    simPip,
    STARTING_EQUITY_USD,
    cfg,
    realisticCosts
  );
  const idealEnd =
    realisticMode
      ? equityAfterAutoTrades(closedChrono, pip, cfg.simUsdPerEnginePip, STARTING_EQUITY_USD, cfg, null).endEquity
      : null;

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
  if (realisticMode) {
    lines.push('');
    lines.push('--- Realistic mode (closer to live MT5) ---');
    if (mt5Broker?.server) lines.push(`MT5 server: ${mt5Broker.server}`);
    if (mt5Broker?.currency) lines.push(`Account currency: ${mt5Broker.currency}`);
    if (realisticCosts) {
      lines.push(
        `Spread: ${realisticCosts.spreadPips.toFixed(2)} pips (broker) · Slippage: ${realisticCosts.slippagePipsPerSide.toFixed(2)} p/side`
      );
      lines.push(`$/pip/lot: $${simPip.toFixed(2)} (broker tick value)`);
      const lossLbl =
        brokerSlCap != null
          ? `broker SL capped at ${brokerSlCap}p (live parity)`
          : 'full chart SL distance (worst case if wide stop fills)';
      lines.push(`Loss model: ${lossLbl} · Lots sized on ${cfg.journalSizingSlPips}p risk · friction deducted`);
    }
    if (idealEnd != null) {
      const idealNet = idealEnd - STARTING_EQUITY_USD;
      lines.push(
        `Ideal model (no friction, -1R losses): $${idealEnd.toFixed(2)} (${idealNet >= 0 ? '+' : ''}${((idealNet / STARTING_EQUITY_USD) * 100).toFixed(1)}%) — for comparison`
      );
    }
  }
  lines.push('');
  const netPnl = endEquity - STARTING_EQUITY_USD;
  const netPct = STARTING_EQUITY_USD > 0 ? (netPnl / STARTING_EQUITY_USD) * 100 : 0;
  lines.push(`Starting equity: $${STARTING_EQUITY_USD.toLocaleString()}`);
  lines.push(`Ending equity (closed trades, compounding ${(RISK_PCT * 100).toFixed(2)}%): $${endEquity.toFixed(2)}`);
  lines.push(`Net PnL: $${netPnl >= 0 ? '+' : ''}${netPnl.toFixed(2)} (${netPct >= 0 ? '+' : ''}${netPct.toFixed(2)}%)`);
  lines.push(`Max drawdown (on equity curve): $${maxDd.toFixed(2)}`);
  lines.push('');
  lines.push(`Trades opened in window: ${resolvedInRange.length}  (OPEN at end: ${openN})`);
  const halfLossN = resolvedInRange.filter((r) => r.out === 'HALF_LOSS').length;
  lines.push(
    `Closed in window: ${wr.totalWins + wr.totalLosses}  |  Wins: ${wr.totalWins}  |  Losses: ${wr.totalLosses} (incl. ${halfLossN} half-loss M15 exits)`
  );
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
