/**
 * Guards: wrong-symbol / absurd mark must never inflate floating PnL.
 * Run: node frontend/lib/liveFloatingPnl.test.js
 */
const {
  liveLegProfit,
  liveFloatingTotal,
  isPlausibleMark,
  resolveLegMark,
  heroFloatingPnl,
  MAX_PNL_NOTIONAL_MULT,
} = require('./liveFloatingPnl.js');

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const short = {
  symbol: 'USUSDT',
  type: 'SELL',
  positionSide: 'SHORT',
  price_open: 0.03184,
  volume: 3924,
  profit: -12.5,
};
const long = {
  symbol: 'USUSDT',
  type: 'BUY',
  positionSide: 'LONG',
  price_open: 0.03269,
  volume: 6136,
  profit: 18.2,
};

assert(!isPlausibleMark(0.03184, 248.05), 'QNT mark vs US entry must be rejected');
assert(!isPlausibleMark(0.03269, 0.3302), 'SOON mark vs US entry must be rejected');

assert(resolveLegMark(short, 248.05, 'QNTUSDT') == null, 'cross-symbol resolve must be null');
assert(resolveLegMark(short, 248.05, 'USUSDT') == null, 'absurd same-label mark must be null');
assert(resolveLegMark({ ...short, price_current: 248.05 }, null, null) == null, 'polluted price_current rejected');

const qntPnL = liveLegProfit(short, 248.05, 'USUSDT');
assert(Math.abs(qntPnL) < 200, `QNT-on-US must not show ~-$973k, got ${qntPnL}`);
assert(qntPnL === -12.5, `expect sticky -12.5, got ${qntPnL}`);

const soonPnL = liveLegProfit(long, 0.3302, 'SOONUSDT');
assert(soonPnL === 18.2, `cross-symbol soon must use sticky, got ${soonPnL}`);

const noQuote = liveFloatingTotal([short, long], 248.05, null);
assert(Math.abs(noQuote - 5.7) < 1e-9, `no quoteSymbol must not broadcast mark, got ${noQuote}`);

const matched = liveLegProfit({ ...short, profit: -1 }, 0.032, 'USUSDT');
assert(Math.abs(matched - (0.03184 - 0.032) * 3924) < 1e-6, `same-symbol tick ok, got ${matched}`);

const polluted = { ...short, profit: -973223.26, price_current: 248.05 };
const clamped = liveLegProfit(polluted, null, null);
const cap = 0.03184 * 3924 * MAX_PNL_NOTIONAL_MULT;
assert(Math.abs(clamped) <= cap + 1e-6, `polluted sticky clamped, got ${clamped}`);

const heroBug = liveFloatingTotal(
  [
    { ...long, profit: 1825.52, price_current: 0.3302 },
    { ...short, profit: -1170.76, price_current: 0.3302 },
  ],
  0.3302,
  'USUSDT',
);
assert(Math.abs(heroBug) < 500, `SOON-on-US pair total must stay near exposure, got ${heroBug}`);

assert(heroFloatingPnl([]) === 0, 'flat book hero floating must be 0');
assert(heroFloatingPnl(null) === 0, 'null positions hero floating must be 0');
assert(heroFloatingPnl([], -999) === 0, 'must ignore stale account.profit when flat');
assert(
  heroFloatingPnl([{ symbol: 'X', type: 'SELL', volume: 10, price_open: 1, profit: -3 }]) === -3,
  'open book uses sticky when no mark',
);

console.log('liveFloatingPnl.test.js OK');
