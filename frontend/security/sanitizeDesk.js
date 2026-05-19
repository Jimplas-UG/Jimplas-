import {
  publicChannelStates,
  publicRiskLevel,
  publicSessionLabel,
  publicSetupPill,
  publicSignalSide,
  publicStatusLine,
  publicTradeStatus,
} from './publicLabels';
import { EMPTY_SIGNALS, EMPTY_WIN_RATE } from '../lib/snapshotDefaults';
import { SHOW_STRATEGY_INTEL } from './deskMode';

const EMPTY_TRADE_SANITIZE = {
  allowed: false,
  side: null,
  setup: null,
  entry: null,
  sl: null,
  tp1: null,
  rr: null,
  confidencePct: 0,
  reason: '',
  blocks: [],
};

/**
 * Strip internal snapshot to trader-safe fields. Full engine snapshot is never passed to UI in production.
 * @param {object|null} raw
 * @param {{ geoRisk?: string }} [opts]
 */
export function sanitizeSnapshot(raw, opts = {}) {
  if (!raw) return null;
  const trade = raw.trade ?? EMPTY_TRADE_SANITIZE;
  const side = publicSignalSide(trade);
  const status = publicTradeStatus(trade);
  const conf =
    trade.confidencePct != null && Number.isFinite(trade.confidencePct)
      ? Math.round(trade.confidencePct * 10) / 10
      : null;

  const publicTrade = {
    allowed: !!trade.allowed && status === 'READY',
    side: side === 'WAIT' ? null : side,
    entry: trade.entry != null && Number.isFinite(trade.entry) ? trade.entry : null,
    sl: trade.sl != null && Number.isFinite(trade.sl) ? trade.sl : null,
    tp1: trade.tp1 != null && Number.isFinite(trade.tp1) ? trade.tp1 : null,
    rr: trade.rr != null && Number.isFinite(trade.rr) ? trade.rr : null,
    confidencePct: conf ?? 0,
    status,
    statusLine: publicStatusLine(trade),
    setupPill: publicSetupPill(trade),
  };

  if (SHOW_STRATEGY_INTEL) {
    return {
      ...raw,
      trade: { ...trade, status, statusLine: publicStatusLine(trade) },
      _public: buildPublicOverlay(raw, opts),
    };
  }

  return {
    asOf: raw.asOf ?? 0,
    session: {
      inSession: !!raw.session?.inSession,
      sessionLabel: publicSessionLabel(raw.session),
      preLondon: !!raw.session?.preLondon,
      london: !!raw.session?.london,
      newYork: !!raw.session?.newYork,
    },
    signals: {
      ...EMPTY_SIGNALS,
      ...(raw.signals ?? {}),
      anyBuy: !!raw.signals?.anyBuy,
      anySell: !!raw.signals?.anySell,
      p1Buy: !!raw.signals?.p1Buy,
      p1Sell: !!raw.signals?.p1Sell,
      p2Buy: !!raw.signals?.p2Buy,
      p2Sell: !!raw.signals?.p2Sell,
      p3Buy: !!raw.signals?.p3Buy,
      p3Sell: !!raw.signals?.p3Sell,
    },
    trade: publicTrade,
    winRate: {
      ...EMPTY_WIN_RATE,
      totalWins: raw.winRate?.totalWins ?? 0,
      totalLosses: raw.winRate?.totalLosses ?? 0,
      winRatePct: raw.winRate?.winRatePct ?? 0,
    },
    risk: {
      riskLevel: publicRiskLevel(raw.risk, opts.geoRisk),
      atrMode: raw.risk?.atrMode ? String(raw.risk.atrMode).split('—')[0].trim() : '—',
    },
    channels: publicChannelStates(raw.signals),
    dxyClose: null,
    us10yClose: null,
    _public: buildPublicOverlay(raw, opts),
    _sanitized: true,
  };
}

function buildPublicOverlay(raw, opts) {
  return {
    signal: publicSignalSide(raw.trade),
    confidencePct: raw.trade?.confidencePct ?? 0,
    tradeStatus: publicTradeStatus(raw.trade),
    riskLevel: publicRiskLevel(raw.risk, opts.geoRisk),
    sessionLabel: publicSessionLabel(raw.session),
    setupPill: publicSetupPill(raw.trade),
    channels: publicChannelStates(raw.signals),
  };
}

/** Hide exact S/R ladder from production UI. */
export function sanitizeSrView(sr) {
  if (!sr || SHOW_STRATEGY_INTEL) return sr;
  return {
    currentPrice: sr.currentPrice,
    pos: sr.pos ?? '—',
    verdictVal: sr.verdictVal ?? '—',
    verdictSub: 'Desk scan complete',
    verdictLabelColor: sr.verdictLabelColor,
    verdictValColor: sr.verdictValColor,
    verdictBorder: sr.verdictBorder,
    verdictBg: sr.verdictBg,
    bullClean: !!sr.bullClean,
    bearClean: !!sr.bearClean,
    bullPips: sr.bullPips != null ? Math.round(sr.bullPips) : 0,
    bearPips: sr.bearPips != null ? Math.round(sr.bearPips) : 0,
    immRes: null,
    immSup: null,
    poiRes: null,
    poiSup: null,
    distRes: '—',
    distSup: '—',
    distPoiRes: '—',
    distPoiSup: '—',
    r1: null,
    r2: null,
    r3: null,
    s1: null,
    s2: null,
    s3: null,
    r1Flipped: false,
    r2Flipped: false,
    r3Flipped: false,
    s1Flipped: false,
    s2Flipped: false,
    s3Flipped: false,
  };
}

/** User prefs only — never ship defaultBilshenzConfig to client in production. */
export function buildDeskPrefs({
  spread,
  geoRisk,
  newsActive,
  nfpBlackout,
  maxDailyTrades,
  simUsdPerEnginePip,
}) {
  return {
    spread,
    geoRisk: geoRisk ?? 'LOW',
    newsActive: !!newsActive,
    nfpBlackout: !!nfpBlackout,
    maxDailyTrades,
    simUsdPerEnginePip,
  };
}
