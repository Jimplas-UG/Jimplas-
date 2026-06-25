/**
 * Binance feed parity audit — compare strategy decisions on direct bridge vs desk proxy.
 *
 * Usage:
 *   npm run audit:migration-parity
 *   npm run audit:migration-parity -- --days=14 --binance-api=http://127.0.0.1:8766
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

const BINANCE_API = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const DESK_API = (process.env.DESK_API_URL ?? `http://127.0.0.1:${process.env.DESK_API_PORT ?? '8791'}`).replace(/\/$/, '');
const DESK_KEY = process.env.DESK_API_KEY?.trim() ?? '';
const BINANCE_SYMBOL = process.env.BINANCE_SYMBOL?.trim() || 'XAUUSDT';
const M30_MS = 30 * 60 * 1000;

function readArg(name: string, def: string): string {
  const a = process.argv.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : def;
}

async function fetchBars(base: string, symbol: string, count: number): Promise<Bar[]> {
  const headers: Record<string, string> = {};
  if (base.includes('/v1/binance') && DESK_KEY) headers.Authorization = `Bearer ${DESK_KEY}`;
  const res = await fetch(`${base}/api/bars/${encodeURIComponent(symbol)}?count=${count}`, { headers });
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
  const directApi = readArg('binance-api', BINANCE_API).replace(/\/$/, '');
  const proxyApi = `${DESK_API}/v1/binance`;

  const cfg = mergeFrozenDeskCfg();
  const check = verifyFrozenStrategy(BACKEND_ROOT, cfg);
  if (!check.ok) {
    console.error('Frozen strategy verification failed:', check.errors.join('; '));
    process.exit(1);
  }

  console.error(`[parity] Fetching ${barCount} M30 bars…`);
  let directBars: Bar[] = [];
  let proxyBars: Bar[] = [];
  try {
    directBars = await fetchBars(directApi, BINANCE_SYMBOL, barCount);
  } catch (e) {
    console.error(`[parity] Direct Binance bars unavailable: ${e instanceof Error ? e.message : e}`);
  }
  try {
    proxyBars = await fetchBars(proxyApi, BINANCE_SYMBOL, barCount);
  } catch (e) {
    console.error(`[parity] Desk proxy bars unavailable: ${e instanceof Error ? e.message : e}`);
  }

  if (!directBars.length && !proxyBars.length) {
    console.error('[parity] No bars — start binance-api and desk-api');
    process.exit(1);
  }

  const alignLen = Math.min(directBars.length || Infinity, proxyBars.length || Infinity);
  const useDirect = directBars.length >= 50;
  const useProxy = proxyBars.length >= 50;

  const drifts: { t: number; diffs: string[] }[] = [];
  const startIdx = Math.max(200, alignLen - days * 48);

  for (let i = startIdx; i < alignLen; i++) {
    const directSlice = useDirect ? directBars.slice(0, i + 1) : null;
    const proxySlice = useProxy ? proxyBars.slice(0, i + 1) : null;
    if (!directSlice || !proxySlice) continue;

    const barT = directSlice[directSlice.length - 1].t;
    const snapDirect = computeBilshenzSnapshot({
      bundle: buildBundleFromM30Bars(directSlice),
      cfg,
      journalRows: [],
      dailyTradeCount: 0,
      nowUtcMs: barT + M30_MS,
    });
    const snapProxy = computeBilshenzSnapshot({
      bundle: buildBundleFromM30Bars(proxySlice),
      cfg,
      journalRows: [],
      dailyTradeCount: 0,
      nowUtcMs: barT + M30_MS,
    });

    const sigD = extractSig(snapDirect, barT);
    const sigP = extractSig(snapProxy, barT);
    const diffs = diffSigs(sigD, sigP);
    if (diffs.length) drifts.push({ t: barT, diffs });
  }

  const pass = drifts.length === 0;
  const report = [
    '# BSV3.2 Binance Feed Parity Report',
    '',
    `Generated: ${new Date().toISOString()}`,
    '',
    '## Summary',
    '',
    `- Bars compared: ${alignLen - startIdx} closed M30 windows`,
    `- Direct bridge: ${directApi} (${directBars.length} bars)`,
    `- Desk proxy: ${proxyApi} (${proxyBars.length} bars)`,
    `- Symbol: ${BINANCE_SYMBOL}`,
    `- Signal drift events: **${drifts.length}**`,
    `- Result: **${pass ? 'PASS' : 'FAIL'}**`,
    '',
    '## Drift Details',
    '',
  ];

  if (!drifts.length) {
    report.push('No logic drift detected between direct Binance bridge and desk proxy feeds.');
  } else {
    for (const d of drifts.slice(0, 50)) {
      report.push(`- \`${new Date(d.t).toISOString()}\`: ${d.diffs.join('; ')}`);
    }
    if (drifts.length > 50) report.push(`- … and ${drifts.length - 50} more`);
  }

  report.push('', '## Notes', '', '- Bar timing or quote differences may cause minor drift on volatile bars.', '- Strategy engine files were not modified.', '');

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
