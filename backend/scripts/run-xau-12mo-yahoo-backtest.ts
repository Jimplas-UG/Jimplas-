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
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --from=2026-01-01 --to=2026-05-18 --live-profile --mt5-api=http://127.0.0.1:8765
 *   npx tsx scripts/run-xau-12mo-yahoo-backtest.ts ... --export-closed-trades=scripts/mc-seed-journal.json
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import type { Bar, BiasSnapshot, RiskSnapshot, TradeJournalRow } from '../engine/types';
import {
  buildBundleFromM30Bars,
  buildTradeRecommendation,
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
import { applyJournalSignalThrottle } from '../engine/signalThrottle';
import { m30ToM15Bars } from '../engine/m15Bars';
import type { BilshenzEngineConfig } from '../engine/types';
import { leftSideScanPineV5 } from '../engine/pineV5SignalEngine';
import { hourlyBarsToM30Series, maybeUpsampleBarsToM30, parseTradingViewChartCsv } from './lib/tradingViewChartCsv';
import { parseIcMarketsMt5ExportBarsCsv } from './lib/mt5ExportBarsCsv';
import { equityAfterAutoTrades, type RealisticCosts } from './lib/journalEquityPath';

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

function parseUtcDateArg(s: string, label: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.trim());
  if (!m) throw new Error(`Invalid ${label} (use YYYY-MM-DD): ${s}`);
  return Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, 0, 0, 0, 0);
}

/** Custom journal window: `--from=2026-01-01 --to=2026-05-18` (`to` exclusive, same as default window). */
function readCustomRangeFromArgs(): { startMs: number; endMs: number } | null {
  const argv = process.argv.slice(2);
  let from: string | null = null;
  let to: string | null = null;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--from=')) from = a.slice('--from='.length);
    else if (a === '--from' && argv[i + 1]) from = argv[i + 1]!;
    else if (a.startsWith('--to=')) to = a.slice('--to='.length);
    else if (a === '--to' && argv[i + 1]) to = argv[i + 1]!;
  }
  if (!from && !to) return null;
  if (!from || !to) throw new Error('Custom range requires both --from=YYYY-MM-DD and --to=YYYY-MM-DD');
  const startMs = parseUtcDateArg(from, '--from');
  const endMs = parseUtcDateArg(to, '--to');
  if (endMs <= startMs) throw new Error('--to must be after --from (exclusive end)');
  return { startMs, endMs };
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

function readArgN(name: string, def: number): number {
  const argv = process.argv.slice(2);
  const p = `--${name}=`;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith(p)) {
      const v = parseFloat(a.slice(p.length));
      return Number.isFinite(v) ? v : def;
    }
    if (a === `--${name}` && argv[i + 1]) {
      const v = parseFloat(argv[i + 1]!);
      return Number.isFinite(v) ? v : def;
    }
  }
  return def;
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

/** Override broker spread in realistic mode (stress tests). */
function readSpreadPipsOverrideFromArgs(): number | null {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--spread-pips=')) {
      const v = parseFloat(a.slice('--spread-pips='.length));
      if (Number.isFinite(v) && v > 0) return v;
    } else if (a === '--spread-pips' && argv[i + 1]) {
      const v = parseFloat(argv[i + 1]!);
      if (Number.isFinite(v) && v > 0) return v;
    }
  }
  return null;
}

/** Appended to output filename, e.g. `--out-suffix=stress` → `backtest-xau-12mo-live-stress-output.txt`. */
function readOutSuffixFromArgs(): string {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--out-suffix=')) return a.slice('--out-suffix='.length).trim();
    if (a === '--out-suffix' && argv[i + 1]) return argv[i + 1]!.trim();
  }
  return '';
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

function readExportClosedTradesPath(): string | null {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--export-closed-trades=')) return path.resolve(a.slice('--export-closed-trades='.length).trim());
    if (a === '--export-closed-trades' && argv[i + 1]) return path.resolve(argv[i + 1]!.trim());
  }
  return null;
}

function riskForBarSlice(
  sub: ReturnType<typeof sliceMarketBundleToM30End>,
  cfg: typeof defaultBilshenzConfig,
  opts?: { inSession?: boolean; bullClean?: boolean; bearClean?: boolean }
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
  return computeRisk(m30, sub.h4, cfg, atrVal, dxyClose ?? null, dxyClose3 ?? null, us10yClose ?? null, close, opts);
}

function biasForBarSlice(sub: ReturnType<typeof sliceMarketBundleToM30End>): BiasSnapshot {
  const m30 = sub.m30;
  const close = m30[m30.length - 1]!.c;
  return computeBias(sub.h4, sub.d1, close);
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
    if (a === '--exness' || a === '--use-mt5') return 'http://127.0.0.1:8765';
  }
  /** Default: connected Exness/broker terminal via local Python API (not Yahoo). */
  if (!readMt5CsvPathFromArgs() && !readTradingViewCsvPathFromArgs()) {
    return 'http://127.0.0.1:8765';
  }
  return null;
}

function allowYahooFallbackFromArgs(): boolean {
  return process.argv.slice(2).some((a) => a === '--yahoo-fallback' || a === '--yahoo');
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
  const spreadPipsOverride = readSpreadPipsOverrideFromArgs();
  const outSuffix = readOutSuffixFromArgs();
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
  const customRange = readCustomRangeFromArgs();
  const liveProfile = process.argv.includes('--live-profile');
  let RANGE_START_MS: number;
  let RANGE_END_MS: number;
  if (customRange) {
    RANGE_START_MS = customRange.startMs;
    RANGE_END_MS = customRange.endMs;
  } else if (windowAnchor === 'start') {
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
    if (!mt5Broker) {
      mt5Broker = await fetchMt5BrokerContext(
        mt5Api,
        symbol,
        defaultBilshenzConfig.pipSize,
        defaultBilshenzConfig.simUsdPerEnginePip
      );
    }
    if (!mt5Broker?.server) {
      throw new Error(
        'MT5 API not connected — open Exness MT5, log in to demo/live, run mt5_trading_system/python/start-api.ps1'
      );
    }
    console.error(
      `Fetching ${symbol} M30 from MT5 (${mt5Broker.server}) via ${mt5Api} (${new Date(FETCH_START_MS).toISOString()} → ${new Date(fetchEndMs).toISOString()}) ...`
    );
    m30All = await fetchMt5ApiM30Bars(mt5Api, symbol, FETCH_START_MS, fetchEndMs);
    if (m30All.length < WARMUP + 100) {
      throw new Error(
        `Too few M30 bars from MT5 API (${m30All.length}). Open XAUUSD chart in MT5 and scroll/load more history.`
      );
    }
    const resolved = mt5Broker.server ? ` · server ${mt5Broker.server}` : '';
    dataNote = `Exness/broker MT5 terminal${resolved} — ${symbol} M30 (${m30All.length} bars)`;
  } else {
    const fetchEndMs = RANGE_END_MS + 24 * 3600 * 1000;
    const p1 = Math.floor(FETCH_START_MS / 1000);
    const p2 = Math.floor(fetchEndMs / 1000);
    if (!allowYahooFallbackFromArgs()) {
      throw new Error(
        'No MT5 data source. Start Exness MT5 + start-api.ps1 (port 8765), or pass --mt5-api=… / --mt5-csv=…. Yahoo only with --yahoo-fallback.'
      );
    }
    console.error(
      'No MT5/IC CSV or MT5 API; using Yahoo GC=F 1h (--yahoo-fallback).'
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
  const engineSpreadPips =
    spreadPipsOverride ?? mt5Broker?.spreadPips ?? defaultBilshenzConfig.currentSpreadPips;
  const cfg = {
    ...defaultBilshenzConfig,
    maxDailyTrades,
    usePineV5: true,
    enableP1: true,
    enableP2: true,
    enableP3: true,
    journalSlPips: 2,
    currentSpreadPips: engineSpreadPips,
    spreadBaselinePips: mt5Broker?.spreadPips ?? defaultBilshenzConfig.spreadBaselinePips,
    enableExecutionHardening:
      process.argv.includes('--no-hardening') ? false : defaultBilshenzConfig.enableExecutionHardening,
    newsActive: false,
    nfpBlackout: false,
    geoRisk: 'LOW' as const,
    showHistory: !liveProfile,
    showHistoryMode: false,
    useLegacyTpClampOnly: true,
    p2UseStrictFilters: false,
    tpClampMinRiskReward: 1,
    tpClampSlFraction: 0,
    maxSlPipsForEntry: 0,
    journalSizingSlPips: 20,
    riskScaleWideStops: false,
    maxDailyLossPct: readArgN('max-daily-loss-pct', defaultBilshenzConfig.maxDailyLossPct),
    maxDrawdownPct: readArgN('max-drawdown-pct', defaultBilshenzConfig.maxDrawdownPct),
    signalOnClosedBarOnly: true,
  };

  const tSr = Date.now();
  const srSeries = replaySrBarByBar(base.m30, cfg);
  console.error(`replaySrBarByBar (${m30All.length} bars): ${((Date.now() - tSr) / 1000).toFixed(2)}s`);

  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;
  let runningEquity = STARTING_EQUITY_USD;
  let peakEquityTrack = STARTING_EQUITY_USD;
  let dayStartEquityTrack = STARTING_EQUITY_USD;
  let lastClosedN = 0;
  let skippedRiskHalt = 0;

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
      dayStartEquityTrack = runningEquity;
    }

    const closedSoFar = journalRows.filter(
      (r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS'
    );
    if (closedSoFar.length !== lastClosedN) {
      lastClosedN = closedSoFar.length;
      const { endEquity } = equityAfterAutoTrades(
        closedSoFar,
        cfg.pipSize,
        cfg.simUsdPerEnginePip,
        STARTING_EQUITY_USD,
        RISK_PCT,
        cfg,
        null
      );
      runningEquity = endEquity;
      peakEquityTrack = Math.max(peakEquityTrack, runningEquity);
    }

    const sr = srSeries[idx]!;
    const sub = sliceMarketBundleToM30End(fullBundle, idx);
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
    const risk = riskForBarSlice(sub, cfg, {
      inSession: session.inSession,
      bullClean: range.bullClean,
      bearClean: range.bearClean,
    });
    const bias = biasForBarSlice(sub);
    const { signals: rawSignals, levels, gates } = computeGatesAndSignalsJimplasFluidity({
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
    const signals = applyJournalSignalThrottle({
      cfg,
      m30,
      idx,
      signals: rawSignals,
      journalRows,
      aggregateDeps: {
        sessionOk: session.inSession,
        maxTradesReached: gates.maxTradesReached,
        newsActive: cfg.newsActive,
        nfpBlackout: cfg.nfpBlackout,
        spreadBlocked: risk.spreadBlocked,
        dxyBlocksBuy: risk.dxyBlocksBuy,
        athZoneBlocked: risk.athZoneBlocked,
        geoHigh: risk.geoHigh,
      },
    });

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
      barLow: bar.l,
      barHigh: bar.h,
      setupLevels: levels,
    });
    const sig = trade.allowed && trade.side != null;
    if (sig && lastBarSig !== bar.t && tradeCount < cfg.maxDailyTrades) {
      let riskHalted = false;
      if (cfg.maxDailyLossPct > 0 && dayStartEquityTrack > 0) {
        const dayLossPct =
          ((dayStartEquityTrack - runningEquity) / dayStartEquityTrack) * 100;
        if (dayLossPct >= cfg.maxDailyLossPct) riskHalted = true;
      }
      if (!riskHalted && cfg.maxDrawdownPct > 0 && peakEquityTrack > 0) {
        const ddPct = ((peakEquityTrack - runningEquity) / peakEquityTrack) * 100;
        if (ddPct >= cfg.maxDrawdownPct) riskHalted = true;
      }
      if (riskHalted) {
        skippedRiskHalt += 1;
        lastBarSig = bar.t;
        continue;
      }
      const prev = { rows: journalRows, count: journalRows.length };
      const next = pushJournalRow(
        prev,
        {
          anyBuy: trade.side === 'BUY',
          anySell: trade.side === 'SELL',
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
  const realisticSpreadPips =
    spreadPipsOverride ?? mt5Broker?.spreadPips ?? cfg.currentSpreadPips;
  const realisticCosts: RealisticCosts | null = realisticMode
    ? {
        spreadPips: realisticSpreadPips,
        slippagePipsPerSide: slippagePips,
        lossSlPips: (structural, sizing) => {
          if (brokerSlCap != null) return Math.min(structural, brokerSlCap);
          return structural;
        },
      }
    : null;

  const closedRows = resolvedInRange.filter((r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS');
  const closedChrono = [...closedRows].sort((a, b) => a.barIndex - b.barIndex);

  const exportPath = readExportClosedTradesPath();
  if (exportPath) {
    const exportBundle = {
      version: 1 as const,
      exportedAt: new Date().toISOString(),
      startEquity: STARTING_EQUITY_USD,
      riskPct: RISK_PCT,
      pipSize: pip,
      simUsdPerEnginePip: simPip,
      realisticMode,
      realisticCosts: realisticCosts
        ? {
            spreadPips: realisticCosts.spreadPips,
            slippagePipsPerSide: realisticCosts.slippagePipsPerSide,
            brokerSlCap: brokerSlCap ?? null,
          }
        : null,
      dataNote,
      rangeStart: RANGE_START_MS,
      rangeEnd: RANGE_END_MS,
      journalMonths,
      windowAnchor,
      liveProfile,
      cfgSnapshot: {
        journalSizingSlPips: cfg.journalSizingSlPips,
        riskScaleWideStops: cfg.riskScaleWideStops,
        journalSlPips: cfg.journalSlPips,
        currentSpreadPips: cfg.currentSpreadPips,
        tp1MaxRewardPips: cfg.tp1MaxRewardPips,
        tp1MinRewardPips: cfg.tp1MinRewardPips,
        useLegacyTpClampOnly: cfg.useLegacyTpClampOnly,
      },
      trades: closedChrono,
    };
    fs.mkdirSync(path.dirname(exportPath), { recursive: true });
    fs.writeFileSync(exportPath, JSON.stringify(exportBundle, null, 2), 'utf8');
    console.error(`Exported closed trades for Monte Carlo: ${exportPath}`);
  }

  const { endEquity, series } = equityAfterAutoTrades(
    closedChrono,
    pip,
    simPip,
    STARTING_EQUITY_USD,
    RISK_PCT,
    cfg,
    realisticCosts
  );
  const idealEnd =
    realisticMode
      ? equityAfterAutoTrades(
          closedChrono,
          pip,
          simPip,
          STARTING_EQUITY_USD,
          RISK_PCT,
          cfg,
          null
        ).endEquity
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

  const rangeLabel = customRange
    ? `${new Date(RANGE_START_MS).toISOString().slice(0, 10)} → ${new Date(RANGE_END_MS).toISOString().slice(0, 10)}`
    : `${journalMonths} month(s) · ${windowAnchor}`;
  const lines: string[] = [];
  lines.push(
    `BILSHENZ — XAU backtest (M30 engine, journal + throttle) · ${liveProfile ? 'LIVE profile (session-only)' : 'research (showHistory)'}`
  );
  lines.push(`Data: ${dataNote}`);
  lines.push(`Journal window: ${rangeLabel}`);
  lines.push(`Max daily trades (NY day cap): ${maxDailyTrades}`);
  lines.push(
    `Risk halts: daily loss ${cfg.maxDailyLossPct}% · max DD ${cfg.maxDrawdownPct}% (skipped signals: ${skippedRiskHalt})`
  );
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
      const spreadLabel = spreadPipsOverride != null ? 'stress override' : 'broker';
      lines.push(
        `Spread: ${realisticCosts.spreadPips.toFixed(2)} pips (${spreadLabel}) · Slippage: ${realisticCosts.slippagePipsPerSide.toFixed(2)} p/side`
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

  const tradePnls = series.map((s) => s.pnl);
  let grossProfitUsd = 0;
  let grossLossUsd = 0;
  for (const p of tradePnls) {
    if (p > 0) grossProfitUsd += p;
    else if (p < 0) grossLossUsd += -p;
  }
  const profitFactor =
    grossLossUsd > 1e-6 ? grossProfitUsd / grossLossUsd : grossProfitUsd > 1e-6 ? Number.POSITIVE_INFINITY : 0;
  lines.push('');
  lines.push('--- Risk metrics (USD PnL per closed trade, compounding risk) ---');
  lines.push(`Gross profit (wins): $${grossProfitUsd.toFixed(2)}`);
  lines.push(`Gross loss (losses): $${grossLossUsd.toFixed(2)}`);
  lines.push(
    `Profit factor (gross profit / gross loss): ${
      profitFactor === Number.POSITIVE_INFINITY ? '∞ (no losing trades)' : profitFactor.toFixed(2)
    }`
  );

  lines.push('');
  lines.push('--- Weaknesses / improvement hooks (heuristic) ---');
  const wk: string[] = [];
  if (wr.p1Wr + wr.p3Wr < 1 && wr.p2Wr > 40) {
    wk.push('Signals cluster in P2; P1/P3 rarely fire — review breakout / flip gates or P2 filters.');
  }
  if (wr.winRatePct < 50) {
    wk.push('Win rate under 50% — expectancy depends on R-multiple; check average win vs loss in journal.');
  }
  if (maxDd > STARTING_EQUITY_USD * 0.15) {
    wk.push('Max drawdown exceeds ~15% of starting equity in this sim — consider lower risk % or fewer daily trades.');
  }
  if (netPnl < 0) {
    wk.push('Net negative over window — validate on demo; check sessions, spread, and symbol calibration.');
  }
  if (halfLossN > 0) {
    wk.push(`${halfLossN} half-loss (M15) exits — compare vs holding full SL for your style.`);
  }
  if (realisticMode && idealEnd != null && endEquity > 0 && idealEnd > endEquity * 1.1) {
    wk.push('Large gap vs frictionless “ideal” run — spreads/slippage/SL cap dominate; tune realistic execution.');
  }
  if (wk.length === 0) wk.push('No automatic red flags from rule-of-thumb thresholds — still validate on demo.');
  for (const line of wk) lines.push(`• ${line}`);

  const outSlug = customRange
    ? `${new Date(RANGE_START_MS).toISOString().slice(0, 10)}_${new Date(RANGE_END_MS).toISOString().slice(0, 10)}${liveProfile ? '-live' : ''}`
    : `${journalMonths}mo${liveProfile ? '-live' : ''}`;
  const suffixPart = outSuffix ? `-${outSuffix.replace(/^-/, '')}` : '';
  const outPath = path.join(__dirname, `backtest-xau-${outSlug}${suffixPart}-output.txt`);
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log('');
  console.log(`Full report: ${outPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
