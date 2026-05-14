import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  buildManualJournalEntry,
  buildSyntheticMarketBundle,
  computeBilshenzSnapshot,
  defaultBilshenzConfig,
  nyYmdKey,
  patchBundleLast,
  resolveJournalOnBar,
  sliceMarketBundleToM30End,
} from '../engine';

const STORAGE_JOURNAL = '@bilshenz_v1/journalRows';
const STORAGE_TRADES = '@bilshenz_v1/tradeCount';
const STORAGE_DAY = '@bilshenz_v1/nyYmd';

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
    const row = buildManualJournalEntry({ trade: t, barIndex: idx, timeStr });
    if (!row) return state;
    const resolved = resolveJournalOnBar(state.journalRows, bar, idx);
    const nextRows = [row, ...resolved].slice(0, 20);
    return {
      ...state,
      journalRows: nextRows,
      tradeCount: Math.min(maxDailyTrades, state.tradeCount + 1),
    };
  }
  if (action.type === 'TICK') {
    const { bundle, snapshot, cfg, now } = action;
    const bar = bundle.m30[bundle.m30.length - 1];
    const idx = bundle.m30.length - 1;
    const resolved = resolveJournalOnBar(state.journalRows, bar, idx);
    const sig = snapshot.signals.anyBuy || snapshot.signals.anySell;

    if (sig && state.lastBarSig !== bar.t) {
      const maxDailyTrades = action.cfg?.maxDailyTrades ?? 5;
      let nextRows = resolved;
      let nextCount = state.tradeCount;
      if (state.tradeCount < maxDailyTrades) {
        const tr = snapshot.trade;
        const sideMatch =
          (tr?.side === 'BUY' && snapshot.signals.anyBuy) ||
          (tr?.side === 'SELL' && snapshot.signals.anySell);
        if (tr?.allowed && sideMatch) {
          const timeStr = new Date(now.getTime()).toISOString().slice(11, 16) + ' UTC';
          const row = buildManualJournalEntry({ trade: tr, barIndex: idx, timeStr });
          if (row) {
            nextRows = [row, ...resolved].slice(0, 20);
            nextCount = Math.min(maxDailyTrades, state.tradeCount + 1);
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
}) {
  const baseRef = useRef(null);
  if (!baseRef.current) {
    baseRef.current = buildSyntheticMarketBundle({ anchorClose: price, count: 480 });
  }

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

  const baseM30Len = baseRef.current.m30.length;
  const clampedBtEnd = useMemo(() => {
    if (runMode !== 'backtest') return baseM30Len - 1;
    const max = baseM30Len - 1;
    const min = Math.min(80, max);
    const raw = Number.isFinite(backtestEndIndex) ? Math.floor(backtestEndIndex) : max;
    return Math.max(min, Math.min(max, raw));
  }, [runMode, backtestEndIndex, baseM30Len]);

  const bundle = useMemo(() => {
    if (runMode === 'backtest') {
      return sliceMarketBundleToM30End(baseRef.current, clampedBtEnd);
    }
    return patchBundleLast(baseRef.current, price, dxy, us10y ?? 4.35);
  }, [runMode, clampedBtEnd, price, dxy, us10y]);

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

  const nowUtcMs = useMemo(() => {
    if (runMode === 'backtest' && bundle.m30.length) {
      return bundle.m30[bundle.m30.length - 1].t;
    }
    return now.getTime();
  }, [runMode, bundle.m30, now]);

  const snapshot = useMemo(
    () =>
      computeBilshenzSnapshot({
        bundle,
        cfg,
        dailyTradeCount: state.tradeCount,
        journalRows: state.journalRows,
        nowUtcMs,
      }),
    [bundle, cfg, state.tradeCount, state.journalRows, nowUtcMs]
  );

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

  const lastBar = bundle.m30[bundle.m30.length - 1];
  const tickNow = useMemo(() => {
    if (runMode === 'backtest' && bundle.m30.length) {
      return new Date(bundle.m30[bundle.m30.length - 1].t);
    }
    return now;
  }, [runMode, bundle.m30, now]);

  useEffect(() => {
    dispatch({
      type: 'TICK',
      bundle: bundleRef.current,
      snapshot: snapshotRef.current,
      cfg,
      now: tickNow,
    });
  }, [
    lastBar.t,
    lastBar.c,
    lastBar.h,
    lastBar.l,
    snapshot.signals.anyBuy,
    snapshot.signals.anySell,
    snapshot.trade?.allowed,
    snapshot.trade?.side,
    snapshot.trade?.rr,
    snapshot.winRate.totalWins,
    snapshot.winRate.totalLosses,
    snapshot.slBuffer,
    snapshot.sr.nearestRes,
    snapshot.sr.nearestSup,
    cfg,
    tickNow.getTime(),
    runMode,
  ]);

  const incrementExecuteTrade = useCallback(() => {
    const b = bundleRef.current;
    const simNow = runMode === 'backtest' && b.m30.length ? new Date(b.m30[b.m30.length - 1].t) : new Date();
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

  return {
    snapshot,
    journalRows: state.journalRows,
    tradeCount: state.tradeCount,
    lastBarSig: state.lastBarSig,
    incrementExecuteTrade,
    bumpAutoTradeCount,
    bundle,
    cfg,
    hydrated: state.hydrated,
    backtestActive: !!state.liveFrozen,
    m30BaseLength: baseM30Len,
    backtestEndClamped: clampedBtEnd,
    backtestWarmupMin: Math.min(80, baseM30Len - 1),
  };
}
