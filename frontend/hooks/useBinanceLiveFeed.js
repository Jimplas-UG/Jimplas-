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
} from '../broker/binanceFuturesApi';

const PIP = DISPLAY_PIP_SIZE;
const STARTUP_BARS = 480;
const FULL_BARS = 2000;
const CACHE_KEY = '@bilshenz_v1/binanceFeedCache';
const CACHE_TTL_MS = 8 * 60 * 1000;

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
  const symRef = useRef(symbol);
  const inflightRef = useRef(false);

  const sessionActive = !!connected;
  const quotesActive = enabled && !!baseUrl?.trim() && (publicQuotes || sessionActive);

  const loadBars = useCallback(
    async (count) => {
      const b = baseUrl?.trim();
      if (!b || !quotesActive) return false;
      if (inflightRef.current) return false;
      inflightRef.current = true;
      try {
        const sym = symRef.current;
        const gold = await fetchBinanceBarsM30(b, sym, count);
        if (!gold.length) {
          setFeedError('No M30 bars from Binance');
          return false;
        }
        setMarketBundle(buildBundleFromM30Bars(gold));
        const last = gold[gold.length - 1];
        if (last?.c != null) setPrice(parseFloat(Number(last.c).toFixed(2)));
        setFeedReady(true);
        setFeedError('');
        if (sessionActive) {
          const st = await fetchStatusAccount(b);
          if (st.account) setAccount(st.account);
        }
        return true;
      } catch (e) {
        setFeedError(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        inflightRef.current = false;
      }
    },
    [baseUrl, quotesActive, sessionActive],
  );

  useEffect(() => {
    if (!quotesActive) {
      setFeedReady(false);
      if (!sessionActive) {
        setBrokerDeals([]);
        setPositions([]);
      }
      return;
    }
    let cancelled = false;
    (async () => {
      const spec = await fetchBinanceSymbolSpec(baseUrl, symbol);
      if (spec) setSymbolSpec(spec);
      if (spec?.symbol) {
        symRef.current = spec.symbol;
        setResolvedSymbol(spec.symbol);
      }
      await loadBars(STARTUP_BARS);
      if (!cancelled) void loadBars(FULL_BARS);
    })();
    return () => {
      cancelled = true;
    };
  }, [quotesActive, sessionActive, baseUrl, symbol, loadBars]);

  useEffect(() => {
    if (!sessionActive || !enabled || !baseUrl?.trim()) return undefined;
    const b = baseUrl.trim();
    const sym = symRef.current;
    let cancelled = false;

    const refreshAccount = async () => {
      const st = await fetchStatusAccount(b);
      if (!cancelled && st.account) setAccount(st.account);
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

  useEffect(() => {
    if (!quotesActive || !pollTicks) return;
    let cancelled = false;
    const poll = async () => {
      const tk = await fetchBinanceTick(baseUrl, symRef.current);
      if (!cancelled) {
        applyTickState(tk, { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol });
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [quotesActive, pollTicks, baseUrl]);

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
  };
}
