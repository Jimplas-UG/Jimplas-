/**
 * Config matrix on shared MT5 M30 data (12mo, realistic, live profile).
 * Usage:
 *   npx tsx scripts/run-backtest-matrix.ts --mt5-api=http://127.0.0.1:8765
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import type { Bar, BiasSnapshot, BilshenzEngineConfig, RiskSnapshot, TradeJournalRow } from '../engine/types';
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
import { applyJournalSignalThrottle } from '../engine/signalThrottle';
import {
  equityAfterAutoTrades,
  maxDrawdownFromSeries,
  type RealisticCosts,
} from './lib/journalEquityPath';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const TARGET_EQUITY = 7000;
const START_EQUITY = 1000;
const RISK_PCT = 0.01;
const WARMUP = 80;
const MAX_JOURNAL = 200_000;
const RANGE_START_MS = Date.UTC(2025, 4, 1);
const RANGE_END_MS = Date.UTC(2026, 4, 1);
const FETCH_START_MS = Date.UTC(2025, 2, 1);
const FETCH_END_MS = RANGE_END_MS + 24 * 3600 * 1000;
/** Max DD $ acceptable vs $1k start (~30%). */
const MAX_DD_OK_USD = 320;

type Variant = {
  id: string;
  p2Strict: boolean;
  m15Exit: boolean;
  tpMin: number;
  tpMax: number;
  lossCooldownBars?: number;
  p2BlockChop?: boolean;
};

const VARIANTS: Variant[] = [
  { id: 'baseline', p2Strict: false, m15Exit: false, tpMin: 10, tpMax: 28 },
  { id: 'strict_p2', p2Strict: true, m15Exit: false, tpMin: 10, tpMax: 28 },
  { id: 'm15_exit', p2Strict: false, m15Exit: true, tpMin: 10, tpMax: 28 },
  { id: 'tp_14_32', p2Strict: false, m15Exit: false, tpMin: 14, tpMax: 32 },
  { id: 'strict+m15', p2Strict: true, m15Exit: true, tpMin: 10, tpMax: 28 },
  { id: 'strict+tp14_32', p2Strict: true, m15Exit: false, tpMin: 14, tpMax: 32 },
  { id: 'm15+tp14_32', p2Strict: false, m15Exit: true, tpMin: 14, tpMax: 32 },
  { id: 'full_combo', p2Strict: true, m15Exit: true, tpMin: 14, tpMax: 32 },
  { id: 'full+cooldown6', p2Strict: true, m15Exit: true, tpMin: 14, tpMax: 32, lossCooldownBars: 6 },
  { id: 'full+chop_block', p2Strict: true, m15Exit: true, tpMin: 14, tpMax: 32, p2BlockChop: true },
  { id: 'full+all_guards', p2Strict: true, m15Exit: true, tpMin: 14, tpMax: 32, lossCooldownBars: 6, p2BlockChop: true },
];

type MatrixRow = {
  id: string;
  endEquity: number;
  netPct: number;
  maxDd: number;
  maxDdPct: number;
  trades: number;
  wins: number;
  losses: number;
  halfLoss: number;
  winRate: number;
  profitFactor: number;
  gapTo7k: number;
  ddOk: boolean;
};

function readMt5Api(): string {
  const env = process.env.MT5_API_URL?.trim();
  if (env) return env.replace(/\/$/, '');
  for (const a of process.argv.slice(2)) {
    if (a.startsWith('--mt5-api=')) return a.slice('--mt5-api='.length).replace(/\/$/, '');
  }
  return 'http://127.0.0.1:8765';
}

async function fetchMt5Bars(baseUrl: string, symbol: string): Promise<Bar[]> {
  const b = baseUrl.replace(/\/$/, '');
  const st = await fetch(`${b}/api/status`);
  if (!st.ok) throw new Error(`MT5 status HTTP ${st.status}`);
  const sj = (await st.json()) as { connected?: boolean };
  if (!sj.connected) throw new Error('MT5 API not connected');
  const res = await fetch(`${b}/api/bars/${encodeURIComponent(symbol)}?from_ms=${FETCH_START_MS}&to_ms=${FETCH_END_MS}`);
  if (!res.ok) throw new Error(`MT5 bars HTTP ${res.status}`);
  const j = (await res.json()) as { bars?: Bar[] };
  const bars = (j.bars ?? []).filter((x) => Number.isFinite(x.t) && Number.isFinite(x.c));
  return bars.sort((a, b) => a.t - b.t);
}

async function fetchBroker(baseUrl: string, symbol: string) {
  const b = baseUrl.replace(/\/$/, '');
  let spreadPips = defaultBilshenzConfig.currentSpreadPips;
  let usdPerPipPerLot = defaultBilshenzConfig.simUsdPerEnginePip;
  let server: string | null = null;
  try {
    const res = await fetch(`${b}/api/status`);
    if (res.ok) {
      const j = (await res.json()) as { account?: { server?: string } };
      server = j.account?.server ?? null;
    }
    const specRes = await fetch(`${b}/api/symbol/${encodeURIComponent(symbol)}?pip_size=0.1`);
    if (specRes.ok) {
      const spec = (await specRes.json()) as { spread_pips?: number; usd_per_pip_per_lot?: number };
      if (spec.spread_pips != null && spec.spread_pips > 0) spreadPips = spec.spread_pips;
      if (spec.usd_per_pip_per_lot != null && spec.usd_per_pip_per_lot > 0) {
        usdPerPipPerLot = spec.usd_per_pip_per_lot;
      }
    }
  } catch {
    /* optional */
  }
  return { spreadPips, usdPerPipPerLot, server };
}

function riskForBarSlice(
  sub: ReturnType<typeof sliceMarketBundleToM30End>,
  cfg: BilshenzEngineConfig
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

function buildCfg(v: Variant, maxDailyTrades: number): BilshenzEngineConfig {
  return {
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
    geoRisk: 'LOW',
    showHistory: false,
    showHistoryMode: false,
    useLegacyTpClampOnly: true,
    p2UseStrictFilters: v.p2Strict,
    enableM15AdverseExit: v.m15Exit,
    p2BlockInChopZone: v.p2BlockChop ?? false,
    lossCooldownBars: v.lossCooldownBars ?? 0,
    tpClampMinRiskReward: 1,
    tpClampSlFraction: 0,
    maxSlPipsForEntry: 0,
    tp1MinRewardPips: v.tpMin,
    tp1MaxRewardPips: v.tpMax,
    journalSizingSlPips: 20,
    riskScaleWideStops: false,
    maxDailyLossPct: 3,
    maxDrawdownPct: 15,
    signalOnClosedBarOnly: true,
  };
}

function runVariant(
  v: Variant,
  m30: Bar[],
  fullBundle: ReturnType<typeof buildBundleFromM30Bars>,
  srSeries: ReturnType<typeof replaySrBarByBar>,
  realisticCosts: RealisticCosts,
  simPip: number
): MatrixRow {
  const cfg = buildCfg(v, 3);
  const m15 = m30ToM15Bars(m30);
  const journalCtx = { m30, m15, cfg };

  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;
  let runningEquity = START_EQUITY;
  let peakEquityTrack = START_EQUITY;
  let dayStartEquityTrack = START_EQUITY;
  let lastClosedN = 0;

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
        START_EQUITY,
        RISK_PCT,
        cfg,
        null
      );
      runningEquity = endEquity;
      peakEquityTrack = Math.max(peakEquityTrack, runningEquity);
    }

    const sr = srSeries[idx]!;
    const sub = sliceMarketBundleToM30End(fullBundle, idx);
    const bias = biasForBarSlice(sub);
    const risk = riskForBarSlice(sub, cfg);
    const hasStructure = !(
      sr.r1 == null &&
      sr.r2 == null &&
      sr.r3 == null &&
      sr.s1 == null &&
      sr.s2 == null &&
      sr.s3 == null
    );
    const session = sessionFromUtcEpochMs(bar.t);
    const prevSession = idx >= 1 ? sessionFromUtcEpochMs(m30[idx - 1]!.t) : session;
    const atrArr = atr(m30, cfg.atrLen);
    const atrVal = lastFinite(atrArr);
    const { gates, signals: rawSignals, levels } = computeGatesAndSignalsJimplasFluidity({
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

    const sig = signals.anyBuy || signals.anySell;
    if (sig && lastBarSig !== bar.t && tradeCount < cfg.maxDailyTrades) {
      let riskHalted = false;
      if (cfg.maxDailyLossPct > 0 && dayStartEquityTrack > 0) {
        const dayLossPct = ((dayStartEquityTrack - runningEquity) / dayStartEquityTrack) * 100;
        if (dayLossPct >= cfg.maxDailyLossPct) riskHalted = true;
      }
      if (!riskHalted && cfg.maxDrawdownPct > 0 && peakEquityTrack > 0) {
        const ddPct = ((peakEquityTrack - runningEquity) / peakEquityTrack) * 100;
        if (ddPct >= cfg.maxDrawdownPct) riskHalted = true;
      }
      if (riskHalted) {
        lastBarSig = bar.t;
        continue;
      }
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

  const resolved = journalRows.map((r) =>
    r.out !== 'OPEN' ? r : resolveOutcomeForward(m30, m15, r, cfg)
  );
  const inRange = (r: TradeJournalRow) => {
    const t = m30[r.barIndex]?.t;
    return t != null && t >= RANGE_START_MS && t < RANGE_END_MS;
  };
  const resolvedInRange = resolved.filter(inRange);
  const wr = winRateFromJournal(resolvedInRange);
  const closedChrono = resolvedInRange
    .filter((r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS')
    .sort((a, b) => a.barIndex - b.barIndex);

  const { endEquity, series } = equityAfterAutoTrades(
    closedChrono,
    cfg.pipSize,
    simPip,
    START_EQUITY,
    RISK_PCT,
    cfg,
    realisticCosts
  );
  const maxDd = maxDrawdownFromSeries(START_EQUITY, series);
  const halfLoss = resolvedInRange.filter((r) => r.out === 'HALF_LOSS').length;
  const tradePnls = series.map((s) => s.pnl);
  let grossProfitUsd = 0;
  let grossLossUsd = 0;
  for (const p of tradePnls) {
    if (p > 0) grossProfitUsd += p;
    else if (p < 0) grossLossUsd += -p;
  }
  const pf = grossLossUsd > 0 ? grossProfitUsd / grossLossUsd : grossProfitUsd > 0 ? 99 : 0;
  const netPct = ((endEquity - START_EQUITY) / START_EQUITY) * 100;
  const maxDdPct = START_EQUITY > 0 ? (maxDd / START_EQUITY) * 100 : 0;

  return {
    id: v.id,
    endEquity,
    netPct,
    maxDd,
    maxDdPct,
    trades: wr.totalWins + wr.totalLosses,
    wins: wr.totalWins,
    losses: wr.totalLosses - halfLoss,
    halfLoss,
    winRate: wr.winRatePct,
    profitFactor: pf,
    gapTo7k: TARGET_EQUITY - endEquity,
    ddOk: maxDd <= MAX_DD_OK_USD,
  };
}

async function main() {
  const mt5Api = readMt5Api();
  const symbol = process.env.MT5_SYMBOL?.trim() || 'XAUUSD';
  console.error(`Loading ${symbol} M30 from ${mt5Api} ...`);
  const m30All = await fetchMt5Bars(mt5Api, symbol);
  if (m30All.length < WARMUP + 100) throw new Error(`Too few bars: ${m30All.length}`);
  const broker = await fetchBroker(mt5Api, symbol);
  const base = buildBundleFromM30Bars(m30All);
  const m30 = base.m30;
  const baseCfg = buildCfg({ id: 'sr', p2Strict: false, m15Exit: false, tpMin: 10, tpMax: 28 }, 3);
  console.error(`replaySrBarByBar (${m30.length} bars) ...`);
  const srSeries = replaySrBarByBar(m30, baseCfg);
  const realisticCosts: RealisticCosts = {
    spreadPips: broker.spreadPips,
    slippagePipsPerSide: 0.4,
    lossSlPips: (structural) => Math.min(structural, 20),
  };
  const simPip = broker.usdPerPipPerLot;

  const rows: MatrixRow[] = [];
  const t0 = Date.now();
  for (const v of VARIANTS) {
    console.error(`  run ${v.id} ...`);
    rows.push(runVariant(v, m30, base, srSeries, realisticCosts, simPip));
  }
  console.error(`Matrix done in ${((Date.now() - t0) / 1000).toFixed(1)}s`);

  const acceptable = rows.filter((r) => r.ddOk);
  acceptable.sort((a, b) => Math.abs(a.gapTo7k) - Math.abs(b.gapTo7k));
  rows.sort((a, b) => b.endEquity - a.endEquity);

  const lines: string[] = [];
  lines.push('BILSHENZ — 12mo config matrix (MT5 M30, realistic, live profile)');
  lines.push(`Data: ${m30.length} M30 bars · server: ${broker.server ?? 'unknown'}`);
  lines.push(`Start $${START_EQUITY} · risk ${(RISK_PCT * 100).toFixed(2)}%/trade · target $${TARGET_EQUITY}`);
  lines.push(`DD filter: max DD ≤ $${MAX_DD_OK_USD} (~${((MAX_DD_OK_USD / START_EQUITY) * 100).toFixed(0)}% of start)`);
  lines.push('');
  lines.push(
    'id                  | end$    | gap$7k | maxDD$ | DD%  | trds | WR%   | PF   | halfL | flags'
  );
  lines.push(
    '--------------------|---------|--------|--------|------|------|-------|------|-------|------------------'
  );
  for (const r of rows) {
    const v = VARIANTS.find((x) => x.id === r.id)!;
    const flags = [
      v.p2Strict ? 'strict' : '',
      v.m15Exit ? 'm15' : '',
      `tp${v.tpMin}/${v.tpMax}`,
      v.lossCooldownBars ? `cd${v.lossCooldownBars}` : '',
      v.p2BlockChop ? 'chop' : '',
    ]
      .filter(Boolean)
      .join(' ');
    const mark = r.ddOk ? (r.endEquity >= TARGET_EQUITY ? '✓≥7k' : '') : 'DD!';
    lines.push(
      `${r.id.padEnd(20)}| ${r.endEquity.toFixed(0).padStart(7)} | ${r.gapTo7k >= 0 ? '+' : ''}${r.gapTo7k.toFixed(0).padStart(5)} | ${r.maxDd.toFixed(0).padStart(6)} | ${r.maxDdPct.toFixed(1).padStart(4)} | ${String(r.trades).padStart(4)} | ${r.winRate.toFixed(1).padStart(5)} | ${r.profitFactor.toFixed(2).padStart(4)} | ${String(r.halfLoss).padStart(5)} | ${flags} ${mark}`
    );
  }
  lines.push('');
  if (acceptable.length) {
    const best = acceptable[0]!;
    lines.push(`Closest to $7k (DD ok): **${best.id}** → $${best.endEquity.toFixed(2)} (gap $${best.gapTo7k.toFixed(0)}, max DD $${best.maxDd.toFixed(0)})`);
    const hit7k = acceptable.filter((r) => r.endEquity >= TARGET_EQUITY);
    if (hit7k.length) {
      lines.push(`Hit $7k+ with acceptable DD: ${hit7k.map((r) => `${r.id}=$${r.endEquity.toFixed(0)}`).join(', ')}`);
    } else {
      lines.push('None reached $7k within DD limit; best acceptable is above.');
    }
  } else {
    lines.push('No variant met the DD limit — relax MAX_DD_OK_USD or accept higher drawdown.');
  }
  lines.push('');
  lines.push(`Baseline reference: end $${rows.find((r) => r.id === 'baseline')?.endEquity.toFixed(2) ?? 'n/a'}`);

  const outPath = path.join(__dirname, 'backtest-matrix-output.txt');
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log(`\nFull report: ${outPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
