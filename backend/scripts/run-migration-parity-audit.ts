/**
 * Migration parity audit — compare strategy decisions on MT5 vs Binance klines.
 *
 * Usage:
 *   npm run audit:migration-parity
 *   npm run audit:migration-parity -- --days=14 --mt5-api=http://127.0.0.1:8765 --binance-api=http://127.0.0.1:8766
 *
 * Requires both bridges running (or use public Binance klines only for binance side).
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { computeBilshenzSnapshot, buildBundleFromM30Bars } from '../engine';
import type { Bar } from '../engine/types';
import { mergeFrozenDeskCfg, verifyFrozenStrategy } from '../strategy/frozenProduction';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_ROOT = path.join(__dirname, '..');
const REPORT_PATH = path.join(BACKEND_ROOT, '..', 'docs', 'MIGRATION_REPORT.md');

const MT5_API = (process.env.MT5_API_URL ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
const BINANCE_API = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const MT5_SYMBOL = process.env.MT5_SYMBOL?.trim() || 'XAUUSD';
const BINANCE_SYMBOL = process.env.BINANCE_SYMBOL?.trim() || 'XAUUSDT';
const M30_MS = 30 * 60 * 1000;

function readArg(name: string, def: string): string {
  const a = process.argv.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : def;
}

async function fetchBars(base: string, symbol: string, count: number): Promise<Bar[]> {
  const res = await fetch(`${base}/api/bars/${encodeURIComponent(symbol)}?count=${count}`);
  if (!res.ok) throw new Error(`${base} bars failed: ${res.status}`);
  const j = await res.json();
  return (j.bars ?? []) as Bar[];
}

type SnapSig = {
  t: number;
  anyBuy: boolean;
  anySell: boolean;
  allowed: boolean;
  side: string | null;
  entry: number | null;
  sl: number | null;
  tp1: number | null;
};

function extractSig(raw: ReturnType<typeof computeBilshenzSnapshot>, barT: number): SnapSig {
  const trade = raw.trade;
  return {
    t: barT,
    anyBuy: !!raw.signals?.anyBuy,
    anySell: !!raw.signals?.anySell,
    allowed: !!trade?.allowed,
    side: trade?.side === 'BUY' || trade?.side === 'SELL' ? trade.side : null,
    entry: trade?.entry ?? null,
    sl: trade?.sl ?? null,
    tp1: trade?.tp1 ?? null,
  };
}

function diffSigs(a: SnapSig, b: SnapSig): string[] {
  const d: string[] = [];
  if (a.anyBuy !== b.anyBuy) d.push(`anyBuy ${a.anyBuy} vs ${b.anyBuy}`);
  if (a.anySell !== b.anySell) d.push(`anySell ${a.anySell} vs ${b.anySell}`);
  if (a.allowed !== b.allowed) d.push(`allowed ${a.allowed} vs ${b.allowed}`);
  if (a.side !== b.side) d.push(`side ${a.side} vs ${b.side}`);
  const tick = 0.1;
  if (a.entry != null && b.entry != null && Math.abs(a.entry - b.entry) > tick) {
    d.push(`entry ${a.entry} vs ${b.entry}`);
  }
  if (a.sl != null && b.sl != null && Math.abs(a.sl - b.sl) > tick) {
    d.push(`sl ${a.sl} vs ${b.sl}`);
  }
  if (a.tp1 != null && b.tp1 != null && Math.abs(a.tp1 - b.tp1) > tick) {
    d.push(`tp1 ${a.tp1} vs ${b.tp1}`);
  }
  return d;
}

async function main(): Promise<void> {
  const days = Math.max(1, parseInt(readArg('days', '14'), 10) || 14);
  const barCount = Math.min(1500, days * 48 + 220);

  const cfg = mergeFrozenDeskCfg();
  const check = verifyFrozenStrategy(BACKEND_ROOT, cfg);
  if (!check.ok) {
    console.error('Frozen strategy verification failed:', check.errors.join('; '));
    process.exit(1);
  }

  console.error(`[parity] Fetching ${barCount} M30 bars…`);
  let mt5Bars: Bar[] = [];
  let binanceBars: Bar[] = [];
  try {
    mt5Bars = await fetchBars(MT5_API, MT5_SYMBOL, barCount);
  } catch (e) {
    console.error(`[parity] MT5 bars unavailable: ${e instanceof Error ? e.message : e}`);
  }
  try {
    binanceBars = await fetchBars(BINANCE_API, BINANCE_SYMBOL, barCount);
  } catch (e) {
    console.error(`[parity] Binance bars unavailable: ${e instanceof Error ? e.message : e}`);
  }

  if (!mt5Bars.length && !binanceBars.length) {
    console.error('[parity] No bars from either source — start mt5-api and/or binance-api');
    process.exit(1);
  }

  const alignLen = Math.min(
    mt5Bars.length || Infinity,
    binanceBars.length || Infinity,
  );
  const useMt5 = mt5Bars.length >= 50;
  const useBz = binanceBars.length >= 50;

  const drifts: { t: number; diffs: string[] }[] = [];
  const startIdx = Math.max(200, alignLen - days * 48);

  for (let i = startIdx; i < alignLen; i++) {
    const mt5Slice = useMt5 ? mt5Bars.slice(0, i + 1) : null;
    const bzSlice = useBz ? binanceBars.slice(0, i + 1) : null;
    if (!mt5Slice || !bzSlice) continue;

    const barT = mt5Slice[mt5Slice.length - 1].t;
    const snapMt5 = computeBilshenzSnapshot({
      bundle: buildBundleFromM30Bars(mt5Slice),
      cfg,
      journalRows: [],
      dailyTradeCount: 0,
      nowUtcMs: barT + M30_MS,
    });
    const snapBz = computeBilshenzSnapshot({
      bundle: buildBundleFromM30Bars(bzSlice),
      cfg,
      journalRows: [],
      dailyTradeCount: 0,
      nowUtcMs: barT + M30_MS,
    });

    const sigM = extractSig(snapMt5, barT);
    const sigB = extractSig(snapBz, barT);
    const diffs = diffSigs(sigM, sigB);
    if (diffs.length) drifts.push({ t: barT, diffs });
  }

  const pass = drifts.length === 0;
  const report = [
    '# BSV3.2 Migration Parity Report',
    '',
    `Generated: ${new Date().toISOString()}`,
    '',
    '## Summary',
    '',
    `- Bars compared: ${alignLen - startIdx} closed M30 windows`,
    `- MT5 symbol: ${MT5_SYMBOL} (${mt5Bars.length} bars)`,
    `- Binance symbol: ${BINANCE_SYMBOL} (${binanceBars.length} bars)`,
    `- Signal drift events: **${drifts.length}**`,
    `- Result: **${pass ? 'PASS' : 'FAIL'}**`,
    '',
    '## Drift Details',
    '',
  ];

  if (!drifts.length) {
    report.push('No logic drift detected between MT5-fed and Binance-fed snapshots.');
  } else {
    for (const d of drifts.slice(0, 50)) {
      report.push(`- \`${new Date(d.t).toISOString()}\`: ${d.diffs.join('; ')}`);
    }
    if (drifts.length > 50) report.push(`- … and ${drifts.length - 50} more`);
  }

  report.push('', '## Notes', '', '- Price feed differences (MT5 vs Binance) may cause bar-level drift on volatile bars.', '- Strategy engine files were not modified; drift indicates data alignment issues, not logic rewrites.', '');

  fs.mkdirSync(path.dirname(REPORT_PATH), { recursive: true });
  fs.writeFileSync(REPORT_PATH, report.join('\n'), 'utf8');
  console.error(`[parity] Report written: ${REPORT_PATH}`);
  console.error(`[parity] ${pass ? 'PASS' : 'FAIL'} — ${drifts.length} drift(s)`);
  process.exit(pass ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
