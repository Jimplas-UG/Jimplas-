/**
 * Jimplas Fluidity engine smoke audit.
 * Run: npx tsx scripts/run-jimplas-audit.ts
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import { computeBias, computeRisk, defaultBilshenzConfig } from '../engine';
import { atr, lastFinite } from '../engine/indicators';
import { computeGatesAndSignalsJimplasFluidity } from '../engine/jimplasFluiditySignalEngine';
import { sessionFromUtcEpochMs } from '../engine/sessionEngine';
import { replaySrBarByBar } from '../engine/srEngine';
import { buildBundleFromM30Bars } from '../engine/syntheticMarket';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

type Check = { id: string; ok: boolean; detail: string };
const checks: Check[] = [];

function check(id: string, ok: boolean, detail: string) {
  checks.push({ id, ok, detail });
}

function main() {
  const cfg = { ...defaultBilshenzConfig, usePineV5: true, p2UseStrictFilters: false, journalSizingSlPips: 20 };

  check('cfg.jimplasActive', cfg.usePineV5 === true, 'usePineV5 routes Jimplas engine');
  check('cfg.p2Loose', cfg.p2UseStrictFilters === false, 'P2 loose (volume mode)');
  check(
    'cfg.tpClamp',
    cfg.useLegacyTpClampOnly && cfg.tp1MinRewardPips === 14 && cfg.tp1MaxRewardPips === 32,
    'TP clamp 14–32 pips (m15+tp14/32 live profile)'
  );
  check('cfg.m15Exit', cfg.enableM15AdverseExit === true, 'M15 adverse half-loss exit enabled');
  check('cfg.journalSizing', cfg.journalSizingSlPips === 20, 'journalSizingSlPips=20');
  check(
    'pine.reference',
    fs.existsSync(path.join(__dirname, '../engine/reference/Jimplas-Fluidity-Strategy.pine')),
    'Jimplas Pine reference present'
  );
  check(
    'riskSizing.util',
    fs.existsSync(path.join(__dirname, '../../frontend/utils/riskSizing.js')),
    'live lot sizing helper present'
  );

  const bars = buildBundleFromM30Bars(
    Array.from({ length: 400 }, (_, i) => {
      const base = 2650 + Math.sin(i / 20) * 30;
      return {
        t: Date.UTC(2025, 0, 1) + i * 30 * 60 * 1000,
        o: base,
        h: base + 3,
        l: base - 3,
        c: base + 0.5,
      };
    })
  ).m30;

  const srSeries = replaySrBarByBar(bars, cfg);
  const idx = bars.length - 1;
  const sr = srSeries[idx]!;
  const sub = { m30: bars, h4: bars, d1: bars, w1: bars, mn1: bars, dxyCloseSeries: [100], us10yCloseSeries: [4.2] };
  const bias = computeBias(sub.h4, sub.d1, bars[idx]!.c, bars);
  const atrVal = lastFinite(atr(bars, cfg.atrLen));
  const risk = computeRisk(bars, sub.h4, cfg, atrVal, 100, 99, 4.2, bars[idx]!.c);
  const session = sessionFromUtcEpochMs(bars[idx]!.t);
  const prevSession = sessionFromUtcEpochMs(bars[idx - 1]!.t);

  const { signals, gates, levels } = computeGatesAndSignalsJimplasFluidity({
    cfg,
    inSession: session.inSession,
    session,
    prevInSession: prevSession.inSession,
    hasStructure: true,
    structureOk: true,
    dailyTradeCount: 0,
    risk,
    bias,
    sr,
    m30: bars,
    h4: bars,
    idx,
    atrVal,
  });

  check('signals.shape', typeof signals.p2Buy === 'boolean' && typeof signals.anyBuy === 'boolean', 'signal flags ok');
  check('gates.shape', typeof gates.liveGateBuy === 'boolean', 'gates ok');
  check('levels.nullOrSetup', levels == null || !!levels.setup, 'setup levels when signal');

  const failed = checks.filter((c) => !c.ok);
  const lines: string[] = [];
  lines.push('BILSHENZ JIMPLAS FLUIDITY AUDIT');
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
    lines.push('All Jimplas checks passed.');
  }

  const outPath = path.join(__dirname, 'audit-jimplas-output.txt');
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.log(`\nReport: ${outPath}`);
  process.exit(failed.length ? 1 : 0);
}

main();
