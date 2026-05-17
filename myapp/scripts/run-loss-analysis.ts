/**
 * Diagnose backtest losses: R:R, TP distance, setup mix, bias, session, SL-first vs TP-first.
 * npx tsx scripts/run-loss-analysis.ts --mt5-api=http://127.0.0.1:8765
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import type { Bar, TradeJournalRow } from '../engine/types';
import {
  buildBundleFromM30Bars,
  computeBias,
  computeRisk,
  defaultBilshenzConfig,
  pushJournalRow,
  resolveJournalOnBar,
  sliceMarketBundleToM30End,
} from '../engine';
import { atr, lastFinite } from '../engine/indicators';
import { nyYmdKey, sessionFromUtcEpochMs } from '../engine/sessionEngine';
import { replaySrBarByBar } from '../engine/srEngine';
import { computeGatesAndSignalsPineV5, leftSideScanPineV5 } from '../engine/pineV5SignalEngine';
import { rewardRiskRatio, clampTp1ForJournal } from '../engine/tradeGeometry';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WARMUP = 80;
const RANGE_START_MS = Date.UTC(2025, 4, 1);
const RANGE_END_MS = Date.UTC(2026, 4, 1);
const FETCH_START_MS = RANGE_START_MS - 60 * 24 * 3600 * 1000;

type Enriched = TradeJournalRow & {
  rr: number | null;
  rewardPips: number;
  riskPips: number;
  session: string;
  biasAligned: boolean;
  barsToClose: number | null;
};

async function fetchMt5Bars(): Promise<Bar[]> {
  const base = (process.env.MT5_API_URL ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
  const url = `${base}/api/bars/XAUUSD?from_ms=${FETCH_START_MS}&to_ms=${RANGE_END_MS + 86400000}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`MT5 bars HTTP ${res.status}`);
  const j = (await res.json()) as { bars?: Bar[] };
  return (j.bars ?? []).filter((x) => Number.isFinite(x.t)).sort((a, b) => a.t - b.t);
}

function resolveOutcomeFixed(m30: Bar[], row: TradeJournalRow): { out: 'WIN' | 'LOSS' | 'OPEN'; bars: number | null } {
  if (row.tp1 == null || !Number.isFinite(row.tp1)) return { out: 'OPEN', bars: null };
  for (let i = row.barIndex + 1; i < m30.length; i++) {
    const b = m30[i];
    if (row.dir === 'BUY') {
      const slHit = b.l <= row.sl;
      const tpHit = b.h >= row.tp1;
      if (slHit && tpHit) return { out: 'LOSS', bars: i - row.barIndex }; // conservative: SL first same bar
      if (slHit) return { out: 'LOSS', bars: i - row.barIndex };
      if (tpHit) return { out: 'WIN', bars: i - row.barIndex };
    } else {
      const slHit = b.h >= row.sl;
      const tpHit = b.l <= row.tp1;
      if (slHit && tpHit) return { out: 'LOSS', bars: i - row.barIndex };
      if (slHit) return { out: 'LOSS', bars: i - row.barIndex };
      if (tpHit) return { out: 'WIN', bars: i - row.barIndex };
    }
  }
  return { out: 'OPEN', bars: null };
}

function pct(n: number, d: number) {
  return d > 0 ? ((n / d) * 100).toFixed(1) : '—';
}

function summarizeBucket(label: string, rows: Enriched[]) {
  const closed = rows.filter((r) => r.out === 'WIN' || r.out === 'LOSS');
  const w = closed.filter((r) => r.out === 'WIN').length;
  const l = closed.filter((r) => r.out === 'LOSS').length;
  const avgRr = closed.length ? closed.reduce((s, r) => s + (r.rr ?? 0), 0) / closed.length : 0;
  const avgRew = closed.length ? closed.reduce((s, r) => s + r.rewardPips, 0) / closed.length : 0;
  const avgRisk = closed.length ? closed.reduce((s, r) => s + r.riskPips, 0) / closed.length : 0;
  console.log(
    `  ${label.padEnd(28)} closed=${closed.length}  W=${w} L=${l}  WR=${pct(w, closed.length)}%  avgR:R=${avgRr.toFixed(2)}  avgTP=${avgRew.toFixed(0)}p  avgSL=${avgRisk.toFixed(1)}p`
  );
}

async function main() {
  console.error('Loading MT5 bars...');
  const m30All = await fetchMt5Bars();
  const base = buildBundleFromM30Bars(m30All);
  const cfg = {
    ...defaultBilshenzConfig,
    usePineV5: true,
    showHistory: true,
    maxDailyTrades: 3,
    journalSlPips: 2,
  };
  const m30 = base.m30;
  const srSeries = replaySrBarByBar(m30, cfg);
  const pip = cfg.pipSize;

  const trades: Enriched[] = [];
  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;

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
    const sub = sliceMarketBundleToM30End(base, idx);
    const bias = computeBias(sub.h4, sub.d1, bar.c, m30);
    const atrArr = atr(m30, cfg.atrLen);
    const risk = computeRisk(m30, sub.h4, cfg, lastFinite(atrArr), null, null, null, bar.c);
    const range = leftSideScanPineV5({
      nearestRes: sr.nearestRes,
      nearestSup: sr.nearestSup,
      close: bar.c,
      pip,
      m30,
      idx,
      minPips: cfg.minRangePips,
    });
    const session = sessionFromUtcEpochMs(bar.t);
    const { signals } = computeGatesAndSignalsPineV5({
      cfg,
      inSession: session.inSession,
      hasStructure: true,
      structureOk: true,
      dailyTradeCount: tradeCount,
      risk,
      bias,
      sr,
      range,
      m30,
      idx,
    });

    if ((signals.anyBuy || signals.anySell) && lastBarSig !== bar.t && tradeCount < 3) {
      const slBuffer = cfg.journalSlPips * pip;
      const isB = signals.anyBuy;
      const stype = signals.p1Buy || signals.p1Sell ? 'P1' : signals.p2Buy || signals.p2Sell ? 'P2' : 'P3';
      const sl = isB ? bar.l - slBuffer : bar.h + slBuffer;
      const rawTp = isB ? sr.nearestRes : sr.nearestSup;
      const tp1 = rawTp;
      const clampedTp = clampTp1ForJournal(isB ? 'BUY' : 'SELL', bar.c, sl, rawTp, cfg);

      const row: TradeJournalRow = {
        entry: bar.c,
        sl,
        tp1,
        dir: isB ? 'BUY' : 'SELL',
        type: stype,
        time: new Date(bar.t).toISOString(),
        out: 'OPEN',
        barIndex: idx,
      };
      const { out, bars } = resolveOutcomeFixed(m30, row);
      const riskPips = Math.abs(row.entry - row.sl) / pip;
      const rewardPips = row.tp1 != null ? Math.abs(row.tp1 - row.entry) / pip : 0;
      const rr = row.tp1 != null ? rewardRiskRatio(row.entry, row.sl, row.tp1, row.dir) : null;
      const biasAligned =
        (row.dir === 'BUY' && bias.isBullish) || (row.dir === 'SELL' && bias.isBearish);

      trades.push({
        ...row,
        out,
        rr,
        rewardPips,
        riskPips,
        session: session.name,
        biasAligned,
        barsToClose: bars,
      });

      journalRows = [row, ...journalRows].slice(0, 500);
      tradeCount++;
      lastBarSig = bar.t;
    }
  }

  const closed = trades.filter((r) => r.out === 'WIN' || r.out === 'LOSS');
  const losses = closed.filter((r) => r.out === 'LOSS');
  const wins = closed.filter((r) => r.out === 'WIN');

  console.log('\n=== BILSHENZ 12mo LOSS ANALYSIS (MT5 XAUUSD, Pine v5, showHistory=true) ===\n');
  console.log(`Closed: ${closed.length}  Wins: ${wins.length}  Losses: ${losses.length}  WR: ${pct(wins.length, closed.length)}%`);
  console.log(`Still OPEN: ${trades.filter((r) => r.out === 'OPEN').length}\n`);

  console.log('--- By setup type ---');
  summarizeBucket('P1 Wick', closed.filter((r) => r.type === 'P1'));
  summarizeBucket('P2 Breakout', closed.filter((r) => r.type === 'P2'));
  summarizeBucket('P3 Flip', closed.filter((r) => r.type === 'P3'));

  console.log('\n--- By session ---');
  for (const s of ['PRE_LONDON', 'LONDON', 'NEW_YORK'] as const) {
    summarizeBucket(s, closed.filter((r) => r.session === s));
  }

  console.log('\n--- HTF bias alignment (P2 requires strict bias) ---');
  summarizeBucket('Bias ALIGNED', closed.filter((r) => r.biasAligned));
  summarizeBucket('Bias NOT aligned', closed.filter((r) => !r.biasAligned));

  console.log('\n--- Reward:Risk at entry (full-structure TP1) ---');
  summarizeBucket('R:R < 1.0 (TP closer than SL)', closed.filter((r) => (r.rr ?? 0) < 1));
  summarizeBucket('R:R 1.0 – 2.0', closed.filter((r) => (r.rr ?? 0) >= 1 && (r.rr ?? 0) < 2));
  summarizeBucket('R:R 2.0 – 4.0', closed.filter((r) => (r.rr ?? 0) >= 2 && (r.rr ?? 0) < 4));
  summarizeBucket('R:R >= 4.0 (moon-shot TP)', closed.filter((r) => (r.rr ?? 0) >= 4));

  console.log('\n--- TP distance (pips to nearest S/R) ---');
  summarizeBucket('TP < 15 pips', closed.filter((r) => r.rewardPips < 15));
  summarizeBucket('TP 15–28 pips', closed.filter((r) => r.rewardPips >= 15 && r.rewardPips < 28));
  summarizeBucket('TP 28–50 pips', closed.filter((r) => r.rewardPips >= 28 && r.rewardPips < 50));
  summarizeBucket('TP >= 50 pips', closed.filter((r) => r.rewardPips >= 50));

  console.log('\n--- SL distance (wick + 2 pip buffer) ---');
  summarizeBucket('SL < 5 pips (very tight)', closed.filter((r) => r.riskPips < 5));
  summarizeBucket('SL 5–15 pips', closed.filter((r) => r.riskPips >= 5 && r.riskPips < 15));
  summarizeBucket('SL >= 15 pips', closed.filter((r) => r.riskPips >= 15));

  // Simulated: what if TP were clamped to max 28 pips?
  let clampWins = 0;
  let clampLosses = 0;
  for (const t of trades) {
    if (t.out === 'OPEN') continue;
    const ctp = clampTp1ForJournal(t.dir, t.entry, t.sl, t.tp1, cfg);
    if (ctp == null) continue;
    const sim = { ...t, tp1: ctp };
    const { out } = resolveOutcomeFixed(m30, sim);
    if (out === 'WIN') clampWins++;
    else if (out === 'LOSS') clampLosses++;
  }
  const clampClosed = clampWins + clampLosses;
  console.log('\n--- SIMULATION: TP clamped 10–28 pips (tradeGeometry) ---');
  console.log(
    `  Would be: W=${clampWins} L=${clampLosses} WR=${pct(clampWins, clampClosed)}%  (vs actual ${pct(wins.length, closed.length)}%)`
  );

  // Simulated: showHistory false = require bullClean/bearClean
  console.log('\n--- Loss drivers (qualitative) ---');
  const bigTpLosses = losses.filter((r) => r.rewardPips >= 40);
  const tightSlLosses = losses.filter((r) => r.riskPips < 8);
  const p3Losses = losses.filter((r) => r.type === 'P3');
  console.log(`  Losses with TP >= 40 pips away: ${bigTpLosses.length} / ${losses.length} (${pct(bigTpLosses.length, losses.length)}%)`);
  console.log(`  Losses with SL < 8 pips (tight wick stop): ${tightSlLosses.length} / ${losses.length}`);
  console.log(`  P3 losses: ${p3Losses.length} (P3 closed WR was 0% in headline backtest)`);

  const lines: string[] = [];
  lines.push('See console output for full breakdown.');
  fs.writeFileSync(path.join(__dirname, 'loss-analysis-output.txt'), lines.join('\n'), 'utf8');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
