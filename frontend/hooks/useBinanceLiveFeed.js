import { useCallback, useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { buildBundleFromM30Bars } from '../lib/marketBundle';
import { DEFAULT_CHART_SYMBOL, sanitizeFuturesSymbol } from '../lib/futuresSymbol';
import { roundFuturesMid } from '../lib/futuresPrice';
import { DISPLAY_PIP_SIZE } from '../security/deskConstants';
import {
  fetchBinanceBarsM30,
  fetchBinanceDeals,
  fetchBinancePositions,
  fetchBinanceSymbolSpec,
  fetchBinanceTick,
  binanceFetch,
  pickReachableBinanceBridgeUrl,
} from '../broker/binanceFuturesApi';
import { subscribeBinanceTickStream } from '../broker/binanceTickStream';
import { formatBinanceNetworkError } from '../utils/binanceApiUrl';
import { rewriteLocalhostBridgeUrl } from '../utils/bridgeLanUrl';

const PIP = DISPLAY_PIP_SIZE;
/** Minimum M30 bars for engine gates on first paint (~1 day). */
const STARTUP_BARS = 48;
/** Deeper history loaded in background after UI is interactive. */
const FULL_BARS = 240;
const CACHE_KEY = '@bilshenz_v1/binanceFeedCache';
const CACHE_TTL_MS = 20 * 60 * 1000;
const STALE_CACHE_MS = 24 * 60 * 60 * 1000;
const MIN_CACHE_BARS = 12;
const STARTUP_TIMEOUT_MS = 4500;
const STARTUP_RETRIES = 1;

async function fetchStatusAccount(base) {
  try {
    const res = await binanceFetch(base, '/api/status', {}, 12000);
    if (!res.ok) return { connected: false, account: null };
    const j = await res.json();
    return { connected: !!j.connected, account: j.connected && j.account ? j.account : null };
  } catch {
    return { connected: false, account: null };
  }
}

function applyTickState(tk, setters) {
  if (!tk) return;
  const { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol } = setters;
  if (Number.isFinite(tk.bid)) setBid(tk.bid);
  if (Number.isFinite(tk.ask)) setAsk(tk.ask);
  const mid = Number.isFinite(tk.bid) && Number.isFinite(tk.ask) ? (tk.bid + tk.ask) / 2 : null;
  if (Number.isFinite(mid)) setPrice(roundFuturesMid(mid));
  if (Number.isFinite(tk.bid) && Number.isFinite(tk.ask)) {
    setSpreadPips(parseFloat(((tk.ask - tk.bid) / PIP).toFixed(2)));
  }
  if (tk.symbol) setResolvedSymbol(sanitizeFuturesSymbol(tk.symbol, DEFAULT_CHART_SYMBOL));
}

async function readBarCache(sym) {
  try {
    const raw = await AsyncStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.bars?.length || parsed.sym !== sym) return null;
    const age = Date.now() - (parsed.ts ?? 0);
    if (age > STALE_CACHE_MS) return null;
    return { bars: parsed.bars, stale: age > CACHE_TTL_MS };
  } catch {
    return null;
  }
}

async function writeBarCache(sym, bars) {
  if (!bars?.length) return;
  try {
    await AsyncStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ ts: Date.now(), sym, bars: bars.slice(-FULL_BARS) }),
    );
  } catch {
    /* ignore */
  }
}

/**
 * Live Binance Futures quotes, account, and M30 history.
 */
export function useBinanceLiveFeed({
  baseUrl,
  connected,
  enabled = true,
  symbol = DEFAULT_CHART_SYMBOL,
  pollTicks = true,
  loadBars = true,
  /** When true, load public quotes/bars even if API session is not logged in. */
  publicQuotes = true,
  /** Slow REST/UI churn without tearing WebSocket (e.g. Profile tab). */
  pauseFeedUi = false,
  onBridgeUrlResolved,
}) {
  const [price, setPrice] = useState(null);
  const [bid, setBid] = useState(null);
  const [ask, setAsk] = useState(null);
  const [spreadPips, setSpreadPips] = useState(null);
  const [account, setAccount] = useState(null);
  const [marketBundle, setMarketBundle] = useState(null);
  const [resolvedSymbol, setResolvedSymbol] = useState(symbol);
  const [brokerDeals, setBrokerDeals] = useState([]);
  const [positions, setPositions] = useState([]);
  const [positionsStale, setPositionsStale] = useState(false);
  const [positionsCoolS, setPositionsCoolS] = useState(0);
  const [symbolSpec, setSymbolSpec] = useState(null);
  const [feedError, setFeedError] = useState('');
  const [feedReady, setFeedReady] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const symRef = useRef(symbol);
  const bgLoadRef = useRef(false);
  const everReadyRef = useRef(false);
  const positionsRef = useRef([]);
  const emptyPosStreakRef = useRef(0);
  const pauseFeedUiRef = useRef(pauseFeedUi);
  pauseFeedUiRef.current = pauseFeedUi;
  const lastTickUiAtRef = useRef(0);

  const sessionActive = !!connected;
  const bridgeActive = enabled && !!baseUrl?.trim() && (publicQuotes || sessionActive);
  const quotesActive = bridgeActive;
  const barsActive = bridgeActive && loadBars;

  const applyBars = useCallback((bars) => {
    if (!bars?.length) return false;
    setMarketBundle(buildBundleFromM30Bars(bars));
    const last = bars[bars.length - 1];
    if (last?.c != null) setPrice(roundFuturesMid(last.c));
    setFeedReady(true);
    everReadyRef.current = true;
    setFeedError('');
    return true;
  }, []);

  const loadM30Bars = useCallback(
    async (count, { background = false } = {}) => {
      const b = baseUrl?.trim();
      if (!b || !barsActive) return false;
      if (background && bgLoadRef.current) return false;
      if (background) bgLoadRef.current = true;
      try {
        const sym = symRef.current;
        const result = await fetchBinanceBarsM30(b, sym, count, background ? undefined : STARTUP_TIMEOUT_MS, {
          retries: background ? 2 : STARTUP_RETRIES,
        });
        if (!result.ok || !result.bars.length) {
          if (!background) {
            setFeedError(result.error || 'No M30 bars from Binance');
          }
          return false;
        }
        applyBars(result.bars);
        void writeBarCache(sym, result.bars);
        if (sessionActive) {
          const st = await fetchStatusAccount(b);
          if (st.account) setAccount(st.account);
        }
        return true;
      } catch (e) {
        if (!background) setFeedError(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        if (background) bgLoadRef.current = false;
      }
    },
    [baseUrl, barsActive, sessionActive, applyBars],
  );

  useEffect(() => {
    symRef.current = sanitizeFuturesSymbol(symbol, DEFAULT_CHART_SYMBOL);
    setResolvedSymbol(symRef.current);
  }, [symbol]);

  useEffect(() => {
    if (!enabled || !baseUrl?.trim()) {
      if (!enabled) {
        setFeedReady(false);
        everReadyRef.current = false;
        if (!sessionActive) {
          setBrokerDeals([]);
          setPositions([]);
          positionsRef.current = [];
          setPositionsStale(false);
          emptyPosStreakRef.current = 0;
        }
      }
      return;
    }
    if (!loadBars) {
      let cancelled = false;
      const tickSetters = { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol };
      setFeedReady(true);
      everReadyRef.current = true;

      void (async () => {
        let b = rewriteLocalhostBridgeUrl(baseUrl.trim());
        if (b !== baseUrl.trim()) {
          onBridgeUrlResolved?.(b);
        }
        const sym = symRef.current;
        if (pollTicks) {
          const tk = await fetchBinanceTick(b, sym);
          if (!cancelled) applyTickState(tk, tickSetters);
        }
        if (sessionActive) {
          const st = await fetchStatusAccount(b);
          if (!cancelled && st.account) setAccount(st.account);
        }
        const spec = await fetchBinanceSymbolSpec(b, sym);
        if (!cancelled && spec?.symbol) {
          const clean = sanitizeFuturesSymbol(spec.symbol, sym);
          symRef.current = clean;
          setResolvedSymbol(clean);
          setSymbolSpec(spec);
        }
      })();

      return () => {
        cancelled = true;
      };
    }
    let cancelled = false;
    const tickSetters = { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol };

    (async () => {
      let b = rewriteLocalhostBridgeUrl(baseUrl.trim());
      if (b !== baseUrl.trim()) {
        onBridgeUrlResolved?.(b);
      }

      const cachedPromise = readBarCache(symbol);
      const barsPromise = fetchBinanceBarsM30(b, symbol, STARTUP_BARS, STARTUP_TIMEOUT_MS, {
        retries: STARTUP_RETRIES,
      });
      const tickPromise = fetchBinanceTick(b, symbol);

      const cached = await cachedPromise;
      if (!cancelled && cached?.bars?.length >= MIN_CACHE_BARS) {
        applyBars(cached.bars);
      }

      let [barsResult, tk] = await Promise.all([barsPromise, tickPromise]);

      if (!barsResult.ok || !barsResult.bars.length) {
        try {
          const health = await binanceFetch(b, '/health', {}, 2500);
          if (!health.ok) {
            const picked = await pickReachableBinanceBridgeUrl(b, symbol);
            if (picked && picked !== b) {
              b = picked;
              onBridgeUrlResolved?.(picked);
              [barsResult, tk] = await Promise.all([
                fetchBinanceBarsM30(b, symbol, STARTUP_BARS, STARTUP_TIMEOUT_MS, { retries: STARTUP_RETRIES }),
                fetchBinanceTick(b, symbol),
              ]);
            }
          }
        } catch {
          const picked = await pickReachableBinanceBridgeUrl(b, symbol);
          if (picked && picked !== b) {
            b = picked;
            onBridgeUrlResolved?.(picked);
            [barsResult, tk] = await Promise.all([
              fetchBinanceBarsM30(b, symbol, STARTUP_BARS, STARTUP_TIMEOUT_MS, { retries: STARTUP_RETRIES }),
              fetchBinanceTick(b, symbol),
            ]);
          }
        }
      }

      if (cancelled) return;

      applyTickState(tk, tickSetters);

      if (barsResult.ok && barsResult.bars.length) {
        applyBars(barsResult.bars);
        void writeBarCache(symRef.current, barsResult.bars);
      } else if (!cached?.bars?.length) {
        setFeedError(
          formatBinanceNetworkError(barsResult.error || 'No M30 bars — bridge may be offline.', b),
        );
      }

      void (async () => {
        const spec = await fetchBinanceSymbolSpec(b, symbol);
        if (cancelled) return;
        if (spec) {
          setSymbolSpec(spec);
          if (spec?.symbol) {
            const clean = sanitizeFuturesSymbol(spec.symbol, symRef.current);
            symRef.current = clean;
            setResolvedSymbol(clean);
          }
        }
        if (sessionActive) {
          const st = await fetchStatusAccount(b);
          if (!cancelled && st.account) setAccount(st.account);
        }
        if (!cancelled && barsResult.ok && barsResult.bars.length) {
          void loadM30Bars(FULL_BARS, { background: true });
        }
      })();
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled, loadBars, pollTicks, sessionActive, baseUrl, symbol, applyBars, reloadNonce, onBridgeUrlResolved]);

  const refreshFeed = useCallback(() => {
    setFeedError('');
    bgLoadRef.current = false;
    setReloadNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!sessionActive || !enabled || !baseUrl?.trim()) return undefined;
    const b = baseUrl.trim();
    const sym = symRef.current;
    let cancelled = false;

    const refreshAccount = async () => {
      const st = await fetchStatusAccount(b);
      if (!cancelled) {
        if (st.account) setAccount(st.account);
        else if (!st.connected) setAccount(null);
      }
    };

    const refreshDeals = async () => {
      const d = await fetchBinanceDeals(b, 100);
      if (!cancelled) setBrokerDeals(d);
    };

    const applyPositionsResult = (result) => {
      if (!result || typeof result !== 'object' || !('positions' in result)) {
        // Legacy callers may still pass a bare array — ignore clearing.
        if (Array.isArray(result)) {
          if (result.length) {
            positionsRef.current = result;
            setPositions(result);
            setPositionsStale(false);
            emptyPosStreakRef.current = 0;
          }
        }
        return;
      }
      const next = Array.isArray(result.positions) ? result.positions : [];
      const cool = Number(result.restCoolS) || 0;
      setPositionsCoolS(cool);
      // Never claim FLAT while REST is cooling — sticky last-good may be empty payload.
      if (cool >= 0.5 && next.length === 0) {
        if (positionsRef.current.length > 0) setPositionsStale(true);
        return;
      }
      if (result.ok && next.length === 0 && !result.stale && cool < 0.5) {
        emptyPosStreakRef.current += 1;
        // Require two consecutive confirmed-empty polls before FLAT (avoids flicker).
        if (emptyPosStreakRef.current >= 2 || positionsRef.current.length === 0) {
          positionsRef.current = [];
          setPositions([]);
          setPositionsStale(false);
        } else {
          setPositionsStale(true);
        }
        return;
      }
      if (next.length > 0) {
        emptyPosStreakRef.current = 0;
        positionsRef.current = next;
        setPositions(next);
        setPositionsStale(!!result.stale || cool > 0.5 || result.ok === false);
        return;
      }
      // Error / cool with empty payload — keep last known.
      if (positionsRef.current.length > 0) {
        setPositionsStale(true);
        return;
      }
      setPositionsStale(!!result.stale || result.ok === false);
    };

    const refreshPositions = async () => {
      const result = await fetchBinancePositions(b);
      if (!cancelled) applyPositionsResult(result);
    };

    void refreshAccount();
    void refreshDeals();
    void refreshPositions();

    // Active desk: fast position sync. Profile pause: slow REST, keep connection.
    const posMs = pauseFeedUi ? 15000 : 3000;
    const acctMs = pauseFeedUi ? 20000 : 8000;
    const dealsMs = pauseFeedUi ? 45000 : 20000;
    const acctId = setInterval(refreshAccount, acctMs);
    const dealsId = setInterval(refreshDeals, dealsMs);
    const posId = setInterval(refreshPositions, posMs);

    return () => {
      cancelled = true;
      clearInterval(acctId);
      clearInterval(dealsId);
      clearInterval(posId);
    };
  }, [sessionActive, enabled, baseUrl, pauseFeedUi]);

  const refreshBrokerSnapshot = useCallback(async () => {
    if (!sessionActive || !enabled || !baseUrl?.trim()) return;
    const b = baseUrl.trim();
    const [st, d, posResult] = await Promise.all([
      fetchStatusAccount(b),
      fetchBinanceDeals(b, 100),
      fetchBinancePositions(b),
    ]);
    if (st.account) setAccount(st.account);
    else if (!st.connected) setAccount(null);
    setBrokerDeals(d);
    const next = Array.isArray(posResult?.positions) ? posResult.positions : [];
    const cool = Number(posResult?.restCoolS) || 0;
    setPositionsCoolS(cool);
    // Confirmed exchange snapshot (ok, not stale, not cooling) always wins — including empty after close.
    if (posResult?.ok && !posResult?.stale && cool < 0.5) {
      positionsRef.current = next;
      setPositions(next);
      setPositionsStale(false);
      emptyPosStreakRef.current = next.length === 0 ? 2 : 0;
    } else if (next.length > 0) {
      positionsRef.current = next;
      setPositions(next);
      setPositionsStale(!!posResult?.stale || cool > 0.5 || posResult?.ok === false);
      emptyPosStreakRef.current = 0;
    } else if (positionsRef.current.length > 0) {
      setPositionsStale(true);
    } else {
      setPositionsStale(!!posResult?.stale || posResult?.ok === false);
    }
  }, [sessionActive, enabled, baseUrl]);

  const applyOptimisticClose = useCallback(({ symbol, positionSide = null, closePair = false } = {}) => {
    if (symbol === '*') {
      positionsRef.current = [];
      setPositions([]);
      setPositionsStale(false);
      emptyPosStreakRef.current = 2;
      return;
    }
    const sym = String(symbol || '').toUpperCase();
    if (!sym) return;
    const prev = positionsRef.current || [];
    let next;
    if (closePair || !positionSide) {
      next = prev.filter((p) => String(p.symbol || '').toUpperCase() !== sym);
    } else {
      const ps = String(positionSide).toUpperCase();
      // SHORT manual close flattens the pair on the bridge — clear all legs for symbol.
      if (ps === 'SHORT') {
        next = prev.filter((p) => String(p.symbol || '').toUpperCase() !== sym);
      } else {
        next = prev.filter((p) => {
          if (String(p.symbol || '').toUpperCase() !== sym) return true;
          const leg = String(p.positionSide || p.leg || (p.type === 'SELL' ? 'SHORT' : 'LONG')).toUpperCase();
          return leg !== ps;
        });
      }
    }
    positionsRef.current = next;
    setPositions(next);
    setPositionsStale(false);
    emptyPosStreakRef.current = next.length === 0 ? 2 : 0;
  }, []);

  const refreshAfterClose = useCallback(async () => {
    if (!sessionActive || !enabled || !baseUrl?.trim()) return;
    // Immediate refresh + one quick follow-up (positions/user stream usually settle in <200ms).
    await refreshBrokerSnapshot();
    await new Promise((r) => setTimeout(r, 180));
    await refreshBrokerSnapshot();
  }, [sessionActive, enabled, baseUrl, refreshBrokerSnapshot]);

  useEffect(() => {
    if (!quotesActive || !pollTicks) return undefined;
    let cancelled = false;
    let lastWsAt = 0;
    const tickSetters = { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol };
    const WS_STALE_MS = 5000;
    const POLL_HEALTHY_MS = 10000;
    const POLL_STALE_MS = 3000;

    const fallbackPoll = async () => {
      if (cancelled) return;
      const wsFresh = lastWsAt > 0 && Date.now() - lastWsAt < WS_STALE_MS;
      if (wsFresh) return;
      const tk = await fetchBinanceTick(baseUrl, symRef.current);
      if (!cancelled) applyTickState(tk, tickSetters);
    };

    const stopWs = subscribeBinanceTickStream(
      baseUrl,
      symRef.current,
      (tk) => {
        if (cancelled) return;
        lastWsAt = Date.now();
        // Throttle UI tick renders on Profile — keep WS connected underneath.
        if (pauseFeedUiRef.current) {
          if (Date.now() - lastTickUiAtRef.current < 1000) return;
          lastTickUiAtRef.current = Date.now();
        }
        applyTickState(tk, tickSetters);
      },
      {
        onOpen: () => {
          if (!cancelled) lastWsAt = Date.now();
        },
        onError: () => {
          lastWsAt = 0;
          void fallbackPoll();
        },
        onClose: () => {
          lastWsAt = 0;
          void fallbackPoll();
        },
      },
    );

    void fallbackPoll();
    const id = setInterval(() => {
      const stale = !lastWsAt || Date.now() - lastWsAt >= WS_STALE_MS;
      if (stale) void fallbackPoll();
    }, POLL_STALE_MS);
    const slowId = setInterval(fallbackPoll, POLL_HEALTHY_MS);

    return () => {
      cancelled = true;
      stopWs();
      clearInterval(id);
      clearInterval(slowId);
    };
  }, [quotesActive, pollTicks, baseUrl, reloadNonce]);

  return {
    price,
    bid,
    ask,
    spreadPips,
    dxy: null,
    us10y: null,
    account,
    marketBundle,
    resolvedSymbol,
    brokerDeals,
    positions,
    positionsStale,
    positionsCoolS,
    feedError,
    feedReady,
    symbolSpec,
    refreshFeed,
    refreshBrokerSnapshot,
    refreshAfterClose,
    applyOptimisticClose,
  };
}
