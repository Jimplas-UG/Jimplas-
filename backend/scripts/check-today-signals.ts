/**
 * Quick audit: today's M30 bars → signals / trade.allowed from live Binance bars.
 * Run: npx tsx scripts/check-today-signals.ts
 */
import { computeBilshenzSnapshot, defaultBilshenzConfig, buildBundleFromM30Bars } from '../engine';
import { sessionFromUtcEpochMs, nyYmdKey } from '../engine/sessionEngine';

const BINANCE = process.env.BINANCE_API || 'http://127.0.0.1:8766';

async function main() {
  const res = await fetch(`${BINANCE}/api/bars/XAUUSDT?count=120`);
  if (!res.ok) {
    console.error('bars fetch failed', res.status);
    process.exit(1);
  }
  const data = (await res.json()) as { bars: { t: number; o: number; h: number; l: number; c: number }[] };
  const bars = data.bars ?? [];
  const today = nyYmdKey(Date.now());
  const cfg = {
    ...defaultBilshenzConfig,
    usePineV5: true,
    geoRisk: 'LOW' as const,
    newsActive: false,
    nfpBlackout: false,
  };
  const bundle = buildBundleFromM30Bars(bars);
  const todayBars = bundle.m30.filter((b) => nyYmdKey(b.t) === today);

  console.log('');
  console.log('=== Today signal audit ===');
  console.log('NY date:', today);
  console.log('M30 bars today:', todayBars.length);
  console.log('Now UTC:', new Date().toISOString());
  console.log('Current session:', sessionFromUtcEpochMs(Date.now()));
  console.log('');

  let signals = 0;
  let allowed = 0;

  for (let i = Math.max(40, bundle.m30.length - todayBars.length - 5); i < bundle.m30.length; i++) {
    const bar = bundle.m30[i]!;
    if (nyYmdKey(bar.t) !== today) continue;
    const sub = { ...bundle, m30: bundle.m30.slice(0, i + 1) };
    const snap = computeBilshenzSnapshot({
      bundle: sub,
      cfg,
      dailyTradeCount: 0,
      journalRows: [],
      nowUtcMs: bar.t + 60_000,
    });
    const sig = snap.signals.anyBuy || snap.signals.anySell;
    const sess = sessionFromUtcEpochMs(bar.t);
    if (sig) {
      signals++;
      const tr = snap.trade;
      const flag = tr.allowed ? 'ALLOW' : 'BLOCK';
      if (tr.allowed) allowed++;
      console.log(
        new Date(bar.t).toISOString().slice(11, 16),
        sess.inSession ? sess.name : 'DEAD',
        tr.side,
        flag,
        tr.blocks?.length ? `(${tr.blocks.join('; ')})` : '',
      );
    }
  }

  console.log('');
  console.log('Signals today:', signals, '| Executable (allowed):', allowed);
  if (signals === 0) {
    console.log('No strategy signals on today\'s closed M30 bars — auto-exec has nothing to fire.');
  } else if (allowed === 0) {
    console.log('Signals fired but all blocked by session/gates — check DEAD ZONE / structure / risk blocks.');
  }
  console.log('');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
