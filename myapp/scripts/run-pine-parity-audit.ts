/**
 * Static + smoke audit: Pine v5 Gold Strategy vs engine (usePineV5).
 * Run: npx tsx scripts/run-pine-parity-audit.ts
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import { defaultBilshenzConfig, computeBias, computeRisk } from '../engine';
import { atr, lastFinite } from '../engine/indicators';
import { replaySrBarByBar, nearestResStack, nearestSupStack } from '../engine/srEngine';
import { computeGatesAndSignalsPineV5, leftSideScanPineV5 } from '../engine/pineV5SignalEngine';
import { sessionFromUtcEpochMs } from '../engine/sessionEngine';
import { buildBundleFromM30Bars } from '../engine/syntheticMarket';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

type Check = { id: string; ok: boolean; detail: string };

const checks: Check[] = [];

function check(id: string, ok: boolean, detail: string) {
  checks.push({ id, ok, detail });
}

function main() {
  const cfg = { ...defaultBilshenzConfig, usePineV5: true, showHistory: false };

  check('cfg.usePineV5', cfg.usePineV5 === true, `usePineV5=${cfg.usePineV5}`);
  check('cfg.pivot', cfg.pivotLeft === 3 && cfg.pivotRight === 3, `pivot ${cfg.pivotLeft}/${cfg.pivotRight} (Pine 3/3)`);
  check('cfg.zone', cfg.zoneHalfWidthPips === 3, `zoneHalfWidthPips=${cfg.zoneHalfWidthPips} (Pine zone_pip=3)`);
  check('cfg.maxDailyTrades', cfg.maxDailyTrades === 3, `maxDailyTrades=${cfg.maxDailyTrades} (Pine 3)`);
  check('cfg.throttleOff', cfg.lossCooldownBars === 0 && cfg.p3MaxSameSideInLookback === 0, 'journal throttle disabled');

  const pineRef = path.join(__dirname, '../engine/reference/Bilshenz-Gold-Strategy.pine');
  check('pine.reference', fs.existsSync(pineRef), fs.existsSync(pineRef) ? 'reference stub present' : 'missing reference');

  const coreMqh = path.resolve(__dirname, '../../mt5_trading_system/mql5/Include/Bilshenz/BilshenzCore.mqh');
  const mqh = fs.readFileSync(coreMqh, 'utf8');
  check('mql5.prevNearest', mqh.includes('prevNearestRes'), 'BzSrSnap has prev nearest stack');
  check('mql5.p1Sweep', mqh.includes('sweptBelow') && mqh.includes('prevSup'), 'P1 sweep uses prev level');
  check('mql5.p2Breakout', mqh.includes('brokeUp') && mqh.includes('isBullish'), 'P2 breakout + bias');
  check('mql5.p3Flip', mqh.includes('BzBrokenBelow') && mqh.includes('upperWickPct'), 'P3 flip retest');
  check('mql5.nySession', mqh.includes('BzInPineSessionNY'), 'NY session (not UTC 7-22 only)');
  check('mql5.anyBuySession', mqh.includes('inSession && !maxTradesReached'), 'anyBuy requires in_session');

  const bars = buildBundleFromM30Bars(
    Array.from({ length: 400 }, (_, i) => {
      const base = 2650 + Math.sin(i / 20) * 30;
      const o = base + (i % 5) * 0.2;
      const c = base + ((i + 2) % 7) * 0.15;
      const h = Math.max(o, c) + 2 + (i % 3);
      const l = Math.min(o, c) - 2 - (i % 4);
      return { t: Date.UTC(2025, 0, 1) + i * 30 * 60 * 1000, o, h, l, c };
    })
  ).m30;

  const srSeries = replaySrBarByBar(bars, cfg);
  const idx = bars.length - 1;
  const sr = srSeries[idx]!;
  const stackRes = nearestResStack(sr.r1, sr.r2, sr.r3, bars[idx]!.c);
  check('sr.nearestStack', sr.nearestRes === stackRes, `nearestRes stack match (${sr.nearestRes} vs ${stackRes})`);

  const sub = { m30: bars, h4: bars, d1: bars, w1: bars, mn1: bars, dxyCloseSeries: [100], us10yCloseSeries: [4.2] };
  const bias = computeBias(sub.h4, sub.d1, bars[idx]!.c, bars);
  check('bias.h4Ema', bias.ema50H4 != null, `H4 EMA50=${bias.ema50H4?.toFixed(2)}`);

  const atrArr = atr(bars, cfg.atrLen);
  const risk = computeRisk(bars, sub.h4, cfg, lastFinite(atrArr), 100, 99, 4.2, bars[idx]!.c);
  check('risk.spreadPine', risk.spreadBlocked === (cfg.currentSpreadPips > cfg.maxSpreadPips), 'spread = broker only');

  const range = leftSideScanPineV5({
    nearestRes: sr.nearestRes,
    nearestSup: sr.nearestSup,
    close: bars[idx]!.c,
    pip: cfg.pipSize,
    m30: bars,
    idx,
    minPips: cfg.minRangePips,
  });

  const session = sessionFromUtcEpochMs(bars[idx]!.t);
  const { signals, gates } = computeGatesAndSignalsPineV5({
    cfg,
    inSession: session.inSession,
    hasStructure: true,
    structureOk: true,
    dailyTradeCount: 0,
    risk,
    bias,
    sr,
    range,
    m30: bars,
    idx,
  });

  check('signals.shape', typeof signals.p1Buy === 'boolean' && typeof signals.anyBuy === 'boolean', 'signal flags ok');
  if (signals.anyBuy && !session.inSession) {
    check('anyBuy.session', false, 'anyBuy true outside session (Pine violation)');
  } else {
    check('anyBuy.session', true, session.inSession ? 'anyBuy in session ok' : 'no anyBuy OOS');
  }
  check('gates.live', typeof gates.liveGateBuy === 'boolean', 'gates exported');

  const failed = checks.filter((c) => !c.ok);
  const lines: string[] = [];
  lines.push('BILSHENZ PINE v5 PARITY AUDIT');
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push(`Checks: ${checks.length}  |  Passed: ${checks.length - failed.length}  |  Failed: ${failed.length}`);
  lines.push('');
  for (const c of checks) {
    lines.push(`${c.ok ? 'PASS' : 'FAIL'}  ${c.id}  —  ${c.detail}`);
  }
  if (failed.length) {
    lines.push('');
    lines.push('FAILED IDS: ' + failed.map((f) => f.id).join(', '));
  } else {
    lines.push('');
    lines.push('All checks passed. Run MT5 backtest for bar-level confirmation.');
  }

  const outPath = path.join(__dirname, 'audit-pine-parity-output.txt');
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log(`\nReport: ${outPath}`);
  process.exit(failed.length ? 1 : 0);
}

main();
