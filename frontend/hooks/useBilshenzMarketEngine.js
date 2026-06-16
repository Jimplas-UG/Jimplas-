import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { InteractionManager, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  buildManualJournalEntry,
  buildSyntheticMarketBundle,
  computeBilshenzSnapshot,
  defaultBilshenzConfig,
  nyYmdKey,
  patchBundleLast,
  m30ToM15Bars,
  resolveJournalOnBar,
  sliceMarketBundleToM30End,
} from './deskComputeLocal';
import { requestDeskSnapshot, offlineSnapshotFallback } from '../services/strategyService';
import { ensureDeskSnapshot } from '../lib/snapshotDefaults';
import { buildDeskPrefs, sanitizeSnapshot } from '../security/sanitizeDesk';
import { ENABLE_DESK_DIAGNOSTICS, IS_PRODUCTION_DESK, USE_REMOTE_DESK } from '../security/deskMode';

const STORAGE_JOURNAL = '@bilshenz_v1/journalRows';
const STORAGE_TRADES = '@bilshenz_v1/tradeCount';
const STORAGE_DAY = '@bilshenz_v1/nyYmd';

/** Lightweight placeholder until synthetic bundle is built off the UI thread. */
const BOOT_SNAPSHOT = {
  asOf: 0,
  session: {
    preLondon: false,
    london: false,
    newYork: false,
    inSession: false,
    name: 'DEAD',
    sessionLabel: 'STANDBY',
  },
  bias: {
    ema50H4: null,
    ema21M30: null,
    dHigh0: null,
    dHigh1: null,
    dLow0: null,
    dLow1: null,
    bullStructure: false,
    bearStructure: false,
    isBullish: false,
    isBearish: false,
  },
  sr: {
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
    nearestRes: null,
    nearestSup: null,
    poiRes: null,
    poiSup: null,
    flipSupLevel: null,
    flipResLevel: null,
    prevNearestRes: null,
    prevNearestSup: null,
    zonePip: 0,
  },
  range: {
    bullPips: 0,
    bearPips: 0,
    bullRangeOk: false,
    bearRangeOk: false,
    bullClean: false,
    bearClean: false,
    bullChop: 0,
    bearChop: 0,
  },
  wick: {
    candleRange: 0,
    bodySize: 0,
    upperWick: 0,
    lowerWick: 0,
    bodyRatio: 0,
    wickRatio: 0,
    upperWickRatio: 0,
    lowerWickRatio: 0,
    isDoji: false,
    isValidBreakout: false,
    isValidRejection: false,
    jimplasFlipBuy: false,
    jimplasFlipSell: false,
  },
  risk: {
    atrVal: null,
    atrPips: null,
    atrMode: '—',
    chopZone: false,
    brokerSpreadBlocked: false,
    barRangeBlocked: false,
    spreadBlocked: false,
    dxyRising: false,
    dxyBlocksBuy: false,
    yieldHigh: false,
    athZoneBlocked: false,
    geoMedium: false,
    geoHigh: false,
    h4SwingHigh1: null,
    h4SwingHigh2: null,
    h4SwingLow1: null,
    h4SwingLow2: null,
  },
  gates: {
    hasStructure: false,
    structureOk: false,
    masterBlock: true,
    sessionGate: false,
    liveGateBuy: false,
    liveGateSell: false,
    hardBlockBuy: true,
    hardBlockSell: true,
    maxTradesReached: false,
  },
  signals: {
    p1Buy: false,
    p1Sell: false,
    p2Buy: false,
    p2Sell: false,
    p3Buy: false,
    p3Sell: false,
    anyBuy: false,
    anySell: false,
  },
  winRate: {
    totalWins: 0,
    totalLosses: 0,
    winRatePct: 0,
    p1Wr: 0,
    p2Wr: 0,
    p3Wr: 0,
    journal: [],
  },
  trade: {
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
  },
  structureLevels: { pdh: null, pdl: null, wh: null, wl: null, mh: null, ml: null },
  dxyClose: null,
  us10yClose: null,
  labelGap: 0,
  slBuffer: 0,
};

function rowsEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const x = a[i];
    const y = b[i];
    if (x.out !== y.out || x.entry !== y.entry || x.sl !== y.sl || x.tp1 !== y.tp1 || x.time !== y.time) return false;
  }
  return true;
}

function engineReducer(state, action) {
  if (action.type === 'HYDRATE') {
    if (state.liveFrozen) {
      return { ...state, hydrated: true };
    }
    const rows = Array.isArray(action.journalRows) ? action.journalRows : [];
    const tc = Number.isFinite(action.tradeCount) ? Math.max(0, Math.floor(action.tradeCount)) : 0;
    return { ...state, journalRows: rows, tradeCount: tc, hydrated: true };
  }
  if (action.type === 'BACKTEST_ENTER') {
    return {
      ...state,
      liveFrozen: { journalRows: state.journalRows, tradeCount: state.tradeCount },
      journalRows: [],
      tradeCount: 0,
      lastBarSig: null,
    };
  }
  if (action.type === 'BACKTEST_EXIT') {
    if (!state.liveFrozen) return state;
    return {
      ...state,
      journalRows: state.liveFrozen.journalRows,
      tradeCount: state.liveFrozen.tradeCount,
      lastBarSig: null,
      liveFrozen: null,
    };
  }
  if (action.type === 'NY_RESET') {
    if (state.liveFrozen) return state;
    return { ...state, tradeCount: 0, lastBarSig: null, journalRows: [] };
  }
  if (action.type === 'AUTO_TRADE_COUNT') {
    const cap = action.maxDailyTrades;
    if (state.tradeCount >= cap) return state;
    return { ...state, tradeCount: Math.min(cap, state.tradeCount + 1) };
  }
  if (action.type === 'EXEC') {
    const { maxDailyTrades, snapshot, bundle, now } = action;
    if (state.tradeCount >= maxDailyTrades) return state;
    const t = snapshot?.trade;
    if (!t?.side || !t.allowed) return state;
    const bar = bundle.m30[bundle.m30.length - 1];
    const idx = bundle.m30.length - 1;
    const timeStr = new Date(now.getTime()).toISOString().slice(11, 16) + ' UTC';
    const row = buildManualJournalEntry({
      trade: t,
      barIndex: idx,
      timeStr,
      m30: bundle.m30,
      cfg: action.cfg ?? defaultBilshenzConfig,
    });
    if (!row) return state;
    const m15 = m30ToM15Bars(bundle.m30);
    const resolved = resolveJournalOnBar(state.journalRows, bar, idx, {
      m30: bundle.m30,
      m15,
      cfg: action.cfg ?? defaultBilshenzConfig,
    });
    const nextRows = [row, ...resolved].slice(0, 20);
    return {
      ...state,
      journalRows: nextRows,
      tradeCount: Math.min(maxDailyTrades, state.tradeCount + 1),
    };
  }
  if (action.type === 'TICK') {
    const { bundle, snapshot, cfg, now, countSignalTowardCap = true } = action;
    const bar = bundle.m30[bundle.m30.length - 1];
    const idx = bundle.m30.length - 1;
    const m15 = m30ToM15Bars(bundle.m30);
    const journalCtx = { m30: bundle.m30, m15, cfg: action.cfg ?? defaultBilshenzConfig };
    const resolved = resolveJournalOnBar(state.journalRows, bar, idx, journalCtx);
    const sig = snapshot.signals?.anyBuy || snapshot.signals?.anySell;

    if (sig && state.lastBarSig !== bar.t) {
      const maxDailyTrades = action.cfg?.maxDailyTrades ?? 5;
      let nextRows = resolved;
      let nextCount = state.tradeCount;
      if (countSignalTowardCap && state.tradeCount < maxDailyTrades) {
        const tr = snapshot.trade;
        const sideMatch =
          (tr?.side === 'BUY' && snapshot.signals?.anyBuy) ||
          (tr?.side === 'SELL' && snapshot.signals?.anySell);
        if (tr?.allowed && sideMatch) {
          const timeStr = new Date(now.getTime()).toISOString().slice(11, 16) + ' UTC';
          const row = buildManualJournalEntry({
            trade: tr,
            barIndex: idx,
            timeStr,
            m30: bundle.m30,
            cfg: action.cfg ?? defaultBilshenzConfig,
          });
          if (row) {
            nextRows = [row, ...resolved].slice(0, 20);
            nextCount = Math.min(maxDailyTrades, state.tradeCount + 1);
          }
        }
      } else if (!countSignalTowardCap && state.tradeCount < maxDailyTrades) {
        const tr = snapshot.trade;
        const sideMatch =
          (tr?.side === 'BUY' && snapshot.signals?.anyBuy) ||
          (tr?.side === 'SELL' && snapshot.signals?.anySell);
        if (tr?.allowed && sideMatch) {
          const timeStr = new Date(now.getTime()).toISOString().slice(11, 16) + ' UTC';
          const row = buildManualJournalEntry({
            trade: tr,
            barIndex: idx,
            timeStr,
            m30: bundle.m30,
            cfg: action.cfg ?? defaultBilshenzConfig,
          });
          if (row) {
            nextRows = [row, ...resolved].slice(0, 20);
          }
        }
      }
      return {
        ...state,
        journalRows: nextRows,
        tradeCount: nextCount,
        lastBarSig: bar.t,
      };
    }

    if (rowsEqual(resolved, state.journalRows)) {
      return state;
    }
    return { ...state, journalRows: resolved };
  }
  return state;
}

/**
 * @param {object} p
 * @param {number} p.price
 * @param {number} p.spread
 * @param {number} p.dxy
 * @param {number} p.us10y
 * @param {Date} p.now
 * @param {'LOW'|'MEDIUM'|'HIGH'} p.geoRisk
 * @param {boolean} p.newsActive
 * @param {boolean} p.nfpBlackout
 * @param {number} [p.maxDailyTrades]
 * @param {number} [p.simUsdPerEnginePip]
 * @param {number} [p.initialTradeCount]
 * @param {'live'|'backtest'} [p.runMode]
 * @param {number} [p.backtestEndIndex] — inclusive M30 index into the full synthetic series (only when runMode === 'backtest')
 * @param {import('../engine').MarketBundle | null} [p.brokerMarketBundle] — live M30 bundle from Binance bridge
 * @param {boolean} [p.useBrokerData] — when true, do not build synthetic bars (wait for bridge bundle)
 * @param {boolean} [p.brokerFeedReady] — blocks synthetic bundle while Binance feed is loading
 * @param {boolean} [p.noSyntheticFallback] — never fall back to synthetic bars (Binance live feed)
 * @param {boolean} [p.countSignalTowardCap] — when false, journal row on signal but daily cap increments only via broker ACK
 * @param {number|null} [p.accountEquity] — live account equity for desk daily-loss / drawdown gates
 */
export function useBilshenzMarketEngine({
  price,
  spread,
  dxy,
  us10y,
  now,
  geoRisk,
  newsActive,
  nfpBlackout,
  maxDailyTrades = 5,
  simUsdPerEnginePip,
  initialTradeCount = 0,
  runMode = 'live',
  backtestEndIndex = 0,
  brokerMarketBundle = null,
  useBrokerData = false,
  brokerFeedReady = false,
  noSyntheticFallback = false,
  countSignalTowardCap = true,
  accountEquity = null,
}) {
  const anchorPriceRef = useRef(price);
  const baseRef = useRef(null);
  const prevUseBrokerRef = useRef(useBrokerData);
  const peakEquityRef = useRef(0);
  const dayStartEquityRef = useRef(0);
  const equityDayRef = useRef('');
  const [bundleReady, setBundleReady] = useState(false);

  useEffect(() => {
    const eq = Number(accountEquity);
    if (!Number.isFinite(eq) || eq <= 0) return;
    const ymd = nyYmdKey(Date.now());
    if (equityDayRef.current !== ymd) {
      equityDayRef.current = ymd;
      dayStartEquityRef.current = eq;
    }
    peakEquityRef.current = Math.max(peakEquityRef.current || eq, eq);
  }, [accountEquity]);

  useEffect(() => {
    if (!useBrokerData) {
      if (prevUseBrokerRef.current && runMode === 'live') {
        baseRef.current = null;
        setBundleReady(false);
      }
      prevUseBrokerRef.current = false;
      return;
    }
    if (runMode !== 'live' && runMode !== 'backtest') return;
    if (!brokerMarketBundle?.m30?.length) {
      baseRef.current = null;
      setBundleReady(false);
      return;
    }
    baseRef.current = brokerMarketBundle;
    anchorPriceRef.current = brokerMarketBundle.m30[brokerMarketBundle.m30.length - 1].c;
    setBundleReady(true);
    prevUseBrokerRef.current = true;
  }, [brokerMarketBundle, runMode, useBrokerData]);

  useEffect(() => {
    let cancelled = false;
    const barCount = Platform.OS === 'web' ? 480 : 320;
    const build = () => {
      if (cancelled || baseRef.current) return;
      if (useBrokerData && brokerMarketBundle?.m30?.length) return;
      if (runMode === 'live' && (useBrokerData || brokerFeedReady)) return;
      if (runMode === 'backtest' && useBrokerData) return;
      baseRef.current = buildSyntheticMarketBundle({
        anchorClose: anchorPriceRef.current,
        count: barCount,
      });
      setBundleReady(true);
    };
    const handle = InteractionManager.runAfterInteractions(build);
    return () => {
      cancelled = true;
      handle.cancel?.();
    };
  }, [runMode, brokerMarketBundle, useBrokerData, brokerFeedReady]);

  /** Don't block UI forever if bridge never responds (non-Binance builds only). */
  useEffect(() => {
    if (bundleReady || runMode !== 'live' || !useBrokerData || !brokerFeedReady) return;
    if (noSyntheticFallback) return;
    const waitMs = USE_REMOTE_DESK ? 1200 : 6000;
    const t = setTimeout(() => {
      if (baseRef.current) return;
      baseRef.current = buildSyntheticMarketBundle({
        anchorClose: anchorPriceRef.current,
        count: Platform.OS === 'web' ? 480 : 240,
      });
      setBundleReady(true);
    }, waitMs);
    return () => clearTimeout(t);
  }, [bundleReady, runMode, useBrokerData, brokerFeedReady, noSyntheticFallback]);

  const [state, dispatch] = useReducer(engineReducer, {
    journalRows: [],
    tradeCount: initialTradeCount,
    lastBarSig: null,
    hydrated: false,
    liveFrozen: null,
  });

  const pineDayRef = useRef(nyYmdKey(now.getTime()));
  const prevRunMode = useRef(runMode);

  useEffect(() => {
    if (runMode === 'backtest' && prevRunMode.current !== 'backtest') {
      dispatch({ type: 'BACKTEST_ENTER' });
    }
    if (runMode === 'live' && prevRunMode.current !== 'live') {
      dispatch({ type: 'BACKTEST_EXIT' });
    }
    prevRunMode.current = runMode;
  }, [runMode]);

  const baseM30Len = baseRef.current?.m30?.length ?? 0;
  const clampedBtEnd = useMemo(() => {
    if (!bundleReady || baseM30Len < 1) return 0;
    if (runMode !== 'backtest') return baseM30Len - 1;
    const max = baseM30Len - 1;
    const min = Math.min(80, max);
    const raw = Number.isFinite(backtestEndIndex) ? Math.floor(backtestEndIndex) : max;
    return Math.max(min, Math.min(max, raw));
  }, [bundleReady, runMode, backtestEndIndex, baseM30Len]);

  const bundle = useMemo(() => {
    if (!bundleReady || !baseRef.current) return null;
    const base = baseRef.current;
    if (runMode === 'backtest') {
      return sliceMarketBundleToM30End(base, clampedBtEnd);
    }
    const lastDx = base.dxyCloseSeries?.length ? base.dxyCloseSeries[base.dxyCloseSeries.length - 1] : 99;
    const lastUy = base.us10yCloseSeries?.length ? base.us10yCloseSeries[base.us10yCloseSeries.length - 1] : 4.35;
    const dx = useBrokerData ? (dxy ?? lastDx) : dxy;
    const uy = useBrokerData ? (us10y ?? lastUy) : (us10y ?? 4.35);
    return patchBundleLast(base, price, dx, uy);
  }, [bundleReady, runMode, clampedBtEnd, price, dxy, us10y, useBrokerData]);

  const cfg = useMemo(() => {
    const cap = Number.isFinite(maxDailyTrades) ? Math.max(1, Math.min(10, Math.floor(maxDailyTrades))) : 5;
    const simUsd =
      simUsdPerEnginePip != null && Number.isFinite(simUsdPerEnginePip) && simUsdPerEnginePip > 0
        ? simUsdPerEnginePip
        : defaultBilshenzConfig.simUsdPerEnginePip;
    return {
      ...defaultBilshenzConfig,
      currentSpreadPips: spread,
      geoRisk: geoRisk ?? 'LOW',
      newsActive: !!newsActive,
      nfpBlackout: !!nfpBlackout,
      maxDailyTrades: cap,
      simUsdPerEnginePip: simUsd,
    };
  }, [spread, geoRisk, newsActive, nfpBlackout, maxDailyTrades, simUsdPerEnginePip]);

  const buildEquityRisk = useCallback(() => {
    const eq = Number(accountEquity);
    if (!Number.isFinite(eq) || eq <= 0) return null;
    return {
      currentEquity: eq,
      peakEquity: peakEquityRef.current || eq,
      dayStartEquity: dayStartEquityRef.current || eq,
    };
  }, [accountEquity]);

  const nowUtcMs = useMemo(() => {
    if (runMode === 'backtest' && bundle?.m30?.length) {
      return bundle.m30[bundle.m30.length - 1].t;
    }
    return now.getTime();
  }, [runMode, bundle, now]);

  const localSnapshot = useMemo(() => {
    if (!bundle || USE_REMOTE_DESK) return BOOT_SNAPSHOT;
    return computeBilshenzSnapshot({
      bundle,
      cfg,
      dailyTradeCount: state.tradeCount,
      journalRows: state.journalRows,
      nowUtcMs,
      equityRisk: buildEquityRisk(),
    });
  }, [bundle, cfg, state.tradeCount, state.journalRows, nowUtcMs, buildEquityRisk]);

  const [remoteSnapshot, setRemoteSnapshot] = useState(null);
  const [remoteError, setRemoteError] = useState(null);

  useEffect(() => {
    if (!USE_REMOTE_DESK || !bundle) return;
    let cancelled = false;
    const prefs = buildDeskPrefs({
      spread,
      geoRisk,
      newsActive,
      nfpBlackout,
      maxDailyTrades,
      simUsdPerEnginePip,
    });
    requestDeskSnapshot({
      bundle,
      prefs,
      journalRows: state.journalRows,
      dailyTradeCount: state.tradeCount,
      nowUtcMs,
      equityRisk: buildEquityRisk(),
    })
      .then((snap) => {
        if (!cancelled) {
          setRemoteSnapshot(snap);
          setRemoteError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRemoteSnapshot((prev) => offlineSnapshotFallback(prev));
          setRemoteError(IS_PRODUCTION_DESK ? 'OFFLINE' : 'Desk API error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    bundle,
    spread,
    geoRisk,
    newsActive,
    nfpBlackout,
    maxDailyTrades,
    simUsdPerEnginePip,
    state.tradeCount,
    state.journalRows,
    nowUtcMs,
    accountEquity,
    buildEquityRisk,
  ]);

  const rawSnapshot = USE_REMOTE_DESK ? remoteSnapshot ?? BOOT_SNAPSHOT : localSnapshot;

  const snapshot = useMemo(() => {
    const sanitized = sanitizeSnapshot(rawSnapshot, { geoRisk });
    return ensureDeskSnapshot(sanitized ?? rawSnapshot, BOOT_SNAPSHOT);
  }, [rawSnapshot, geoRisk]);

  const bundleRef = useRef(bundle);
  const snapshotRef = useRef(snapshot);
  bundleRef.current = bundle;
  snapshotRef.current = snapshot;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [[, jStr], [, tStr], [, dayStr]] = await AsyncStorage.multiGet([STORAGE_JOURNAL, STORAGE_TRADES, STORAGE_DAY]);
        if (cancelled) return;
        const today = nyYmdKey(Date.now());
        if (dayStr != null && dayStr !== today) {
          dispatch({ type: 'HYDRATE', journalRows: [], tradeCount: 0 });
          await AsyncStorage.multiSet([
            [STORAGE_JOURNAL, '[]'],
            [STORAGE_TRADES, '0'],
            [STORAGE_DAY, today],
          ]).catch(() => {});
          return;
        }
        let rows = [];
        if (jStr) {
          const parsed = JSON.parse(jStr);
          rows = Array.isArray(parsed) ? parsed : [];
        }
        const tc = tStr != null ? parseInt(tStr, 10) : 0;
        dispatch({
          type: 'HYDRATE',
          journalRows: rows,
          tradeCount: Number.isFinite(tc) ? tc : 0,
        });
      } catch {
        if (!cancelled) dispatch({ type: 'HYDRATE', journalRows: [], tradeCount: 0 });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!state.hydrated || state.liveFrozen) return;
    AsyncStorage.multiSet([
      [STORAGE_JOURNAL, JSON.stringify(state.journalRows)],
      [STORAGE_TRADES, String(state.tradeCount)],
      [STORAGE_DAY, nyYmdKey(Date.now())],
    ]).catch(() => {});
  }, [state.hydrated, state.liveFrozen, state.journalRows, state.tradeCount]);

  useEffect(() => {
    if (state.liveFrozen) return;
    const ymd = nyYmdKey(now.getTime());
    if (pineDayRef.current !== ymd) {
      pineDayRef.current = ymd;
      dispatch({ type: 'NY_RESET' });
      AsyncStorage.multiSet([
        [STORAGE_JOURNAL, '[]'],
        [STORAGE_TRADES, '0'],
        [STORAGE_DAY, ymd],
      ]).catch(() => {});
    }
  }, [now, state.liveFrozen]);

  const lastBar = bundle?.m30?.length ? bundle.m30[bundle.m30.length - 1] : null;
  const tickNow = useMemo(() => {
    if (runMode === 'backtest' && bundle?.m30?.length) {
      return new Date(bundle.m30[bundle.m30.length - 1].t);
    }
    return now;
  }, [runMode, bundle, now]);

  useEffect(() => {
    if (!lastBar || !bundleRef.current) return;
    dispatch({
      type: 'TICK',
      bundle: bundleRef.current,
      snapshot: snapshotRef.current,
      cfg,
      now: tickNow,
      countSignalTowardCap,
    });
  }, [
    lastBar?.t,
    lastBar?.c,
    lastBar?.h,
    lastBar?.l,
    snapshot.signals?.anyBuy,
    snapshot.signals?.anySell,
    snapshot.trade?.allowed,
    snapshot.trade?.side,
    snapshot.trade?.rr,
    snapshot.winRate?.totalWins,
    snapshot.winRate?.totalLosses,
    snapshot.slBuffer,
    snapshot.sr?.nearestRes,
    snapshot.sr?.nearestSup,
    cfg,
    tickNow.getTime(),
    runMode,
    countSignalTowardCap,
  ]);

  const incrementExecuteTrade = useCallback(() => {
    const b = bundleRef.current;
    if (!b?.m30?.length) return;
    const simNow = runMode === 'backtest' ? new Date(b.m30[b.m30.length - 1].t) : new Date();
    dispatch({
      type: 'EXEC',
      maxDailyTrades: cfg.maxDailyTrades,
      snapshot: snapshotRef.current,
      bundle: bundleRef.current,
      now: simNow,
    });
  }, [cfg.maxDailyTrades, runMode]);

  const bumpAutoTradeCount = useCallback(() => {
    dispatch({ type: 'AUTO_TRADE_COUNT', maxDailyTrades: cfg.maxDailyTrades });
  }, [cfg.maxDailyTrades]);

  const getDeskExecuteGateBody = useCallback(() => {
    if (!bundle) return null;
    return {
      bundle,
      prefs: buildDeskPrefs({
        spread,
        geoRisk,
        newsActive,
        nfpBlackout,
        maxDailyTrades,
        simUsdPerEnginePip,
      }),
      journalRows: state.journalRows,
      dailyTradeCount: state.tradeCount,
      nowUtcMs,
      equityRisk: buildEquityRisk(),
    };
  }, [
    bundle,
    spread,
    geoRisk,
    newsActive,
    nfpBlackout,
    maxDailyTrades,
    simUsdPerEnginePip,
    state.journalRows,
    state.tradeCount,
    nowUtcMs,
    buildEquityRisk,
  ]);

  if (ENABLE_DESK_DIAGNOSTICS && remoteError) {
    console.warn('[desk-remote]', remoteError);
  }

  return {
    snapshot,
    journalRows: state.journalRows,
    tradeCount: state.tradeCount,
    lastBarSig: state.lastBarSig,
    incrementExecuteTrade,
    bumpAutoTradeCount,
    maxDailyTrades: cfg.maxDailyTrades,
    bundle: IS_PRODUCTION_DESK ? null : bundle,
    cfg: IS_PRODUCTION_DESK ? null : cfg,
    hydrated: state.hydrated,
    bundleReady,
    backtestActive: !!state.liveFrozen,
    m30BaseLength: baseM30Len,
    backtestEndClamped: clampedBtEnd,
    backtestWarmupMin: Math.min(80, Math.max(0, baseM30Len - 1)),
    deskRemote: USE_REMOTE_DESK,
    deskRemoteError: remoteError,
    getDeskExecuteGateBody,
  };
}
