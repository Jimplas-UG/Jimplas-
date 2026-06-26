import { useCallback, useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { buildBundleFromM30Bars } from '../lib/marketBundle';
import { TRADING_SYMBOL } from '../lib/tradingSymbol';
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
const FULL_BARS = 600;
const CACHE_KEY = '@bilshenz_v1/binanceFeedCache';
const CACHE_TTL_MS = 20 * 60 * 1000;
const STALE_CACHE_MS = 24 * 60 * 60 * 1000;
const MIN_CACHE_BARS = 16;
const STARTUP_TIMEOUT_MS = 6000;
const STARTUP_RETRIES = 0;

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
  if (Number.isFinite(mid)) setPrice(parseFloat(Number(mid).toFixed(2)));
  if (Number.isFinite(tk.bid) && Number.isFinite(tk.ask)) {
    setSpreadPips(parseFloat(((tk.ask - tk.bid) / PIP).toFixed(2)));
  }
  if (tk.symbol) setResolvedSymbol(tk.symbol);
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
  symbol = TRADING_SYMBOL,
  pollTicks = true,
  /** When true, load public quotes/bars even if API session is not logged in. */
  publicQuotes = true,
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
  const [symbolSpec, setSymbolSpec] = useState(null);
  const [feedError, setFeedError] = useState('');
  const [feedReady, setFeedReady] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const symRef = useRef(symbol);
  const bgLoadRef = useRef(false);
  const everReadyRef = useRef(false);

  const sessionActive = !!connected;
  const quotesActive = enabled && !!baseUrl?.trim() && (publicQuotes || sessionActive);

  const applyBars = useCallback((gold) => {
    if (!gold?.length) return false;
    setMarketBundle(buildBundleFromM30Bars(gold));
    const last = gold[gold.length - 1];
    if (last?.c != null) setPrice(parseFloat(Number(last.c).toFixed(2)));
    setFeedReady(true);
    everReadyRef.current = true;
    setFeedError('');
    return true;
  }, []);

  const loadBars = useCallback(
    async (count, { background = false } = {}) => {
      const b = baseUrl?.trim();
      if (!b || !quotesActive) return false;
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
    [baseUrl, quotesActive, sessionActive, applyBars],
  );

  useEffect(() => {
    symRef.current = symbol;
    setResolvedSymbol(symbol);
  }, [symbol]);

  useEffect(() => {
    if (!quotesActive) {
      if (!enabled) {
        setFeedReady(false);
        everReadyRef.current = false;
        if (!sessionActive) {
          setBrokerDeals([]);
          setPositions([]);
        }
      }
      return;
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
            symRef.current = spec.symbol;
            setResolvedSymbol(spec.symbol);
          }
        }
        if (sessionActive) {
          const st = await fetchStatusAccount(b);
          if (!cancelled && st.account) setAccount(st.account);
        }
        if (!cancelled && barsResult.ok && barsResult.bars.length) {
          void loadBars(FULL_BARS, { background: true });
        }
      })();
    })();

    return () => {
      cancelled = true;
    };
  }, [quotesActive, sessionActive, baseUrl, symbol, applyBars, loadBars, reloadNonce]);

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
      if (!cancelled && d.length) setBrokerDeals(d);
    };

    const refreshPositions = async () => {
      const p = await fetchBinancePositions(b, sym);
      if (!cancelled) setPositions(p);
    };

    void refreshAccount();
    void refreshDeals();
    void refreshPositions();

    const acctId = setInterval(refreshAccount, 5000);
    const dealsId = setInterval(refreshDeals, 20000);
    const posId = setInterval(refreshPositions, 8000);

    return () => {
      cancelled = true;
      clearInterval(acctId);
      clearInterval(dealsId);
      clearInterval(posId);
    };
  }, [sessionActive, enabled, baseUrl]);

  const refreshBrokerSnapshot = useCallback(async () => {
    if (!sessionActive || !enabled || !baseUrl?.trim()) return;
    const b = baseUrl.trim();
    const sym = symRef.current;
    const [st, d, p] = await Promise.all([
      fetchStatusAccount(b),
      fetchBinanceDeals(b, 100),
      fetchBinancePositions(b, sym),
    ]);
    if (st.account) setAccount(st.account);
    else if (!st.connected) setAccount(null);
    if (d.length) setBrokerDeals(d);
    setPositions(p);
  }, [sessionActive, enabled, baseUrl]);

  useEffect(() => {
    if (!quotesActive || !pollTicks) return undefined;
    let cancelled = false;
    let wsActive = false;
    let lastWsAt = 0;
    const tickSetters = { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol };

    const stopWs = subscribeBinanceTickStream(
      baseUrl,
      symRef.current,
      (tk) => {
        if (cancelled) return;
        wsActive = true;
        lastWsAt = Date.now();
        applyTickState(tk, tickSetters);
      },
      {
        onOpen: () => {
          if (!cancelled) wsActive = true;
        },
        onError: () => {
          wsActive = false;
        },
      },
    );

    const fallbackPoll = async () => {
      if (cancelled) return;
      if (wsActive && Date.now() - lastWsAt < 12000) return;
      const tk = await fetchBinanceTick(baseUrl, symRef.current);
      if (!cancelled) applyTickState(tk, tickSetters);
    };

    void fallbackPoll();
    const id = setInterval(fallbackPoll, 15000);

    return () => {
      cancelled = true;
      stopWs();
      clearInterval(id);
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
    feedError,
    feedReady,
    symbolSpec,
    refreshFeed,
    refreshBrokerSnapshot,
  };
}
