import { useCallback, useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { buildBundleFromM30Bars } from '../lib/marketBundle';
import { DISPLAY_PIP_SIZE } from '../security/deskConstants';
import {
  fetchMt5BarsM30,
  fetchMt5ResolvedSymbol,
  fetchMt5Tick,
} from '../broker/mt5PythonApi';

const PIP = DISPLAY_PIP_SIZE;
/** Fast open: enough for all 15 engines (~10 days M30). */
const STARTUP_BARS = 480;
/** Background refresh: full structure history. */
const FULL_BARS = 2000;
const MACRO_STARTUP_BARS = 480;
const CACHE_KEY = '@bilshenz_v1/mt5FeedCache';
const CACHE_TTL_MS = 8 * 60 * 1000;

const DXY_CANDIDATES = ['USDX', 'DXY', 'USDIDX'];
const US10Y_CANDIDATES = ['US10Y', 'UST10Y'];

async function fetchBarsFirst(base, symbols, count) {
  for (const sym of symbols) {
    const bars = await fetchMt5BarsM30(base, sym, count);
    if (bars.length >= 50) return { bars, symbol: sym };
  }
  return { bars: [], symbol: null };
}

async function fetchStatusAccount(base) {
  try {
    const res = await fetch(`${base}/api/status`);
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
  const mid =
    Number.isFinite(tk.bid) && Number.isFinite(tk.ask) ? (tk.bid + tk.ask) / 2 : tk.last;
  if (Number.isFinite(mid)) setPrice(parseFloat(Number(mid).toFixed(2)));
  if (Number.isFinite(tk.bid) && Number.isFinite(tk.ask)) {
    setSpreadPips(parseFloat(((tk.ask - tk.bid) / PIP).toFixed(2)));
  }
  if (tk.symbol) setResolvedSymbol(tk.symbol);
}

function bundleFromGold(gold, dxyBars, uyBars) {
  return buildBundleFromM30Bars(gold, {
    dxyM30: dxyBars?.length ? dxyBars : undefined,
    us10yM30: uyBars?.length ? uyBars : undefined,
  });
}

/**
 * Live MT5 quotes, account, and M30 history for the app engine + UI.
 * @param {{ baseUrl: string, connected: boolean, enabled?: boolean, symbol?: string, pollTicks?: boolean }} p
 */
export function useMt5LiveFeed({
  baseUrl,
  connected,
  enabled = true,
  symbol = 'XAUUSD',
  pollTicks = true,
}) {
  const [price, setPrice] = useState(null);
  const [bid, setBid] = useState(null);
  const [ask, setAsk] = useState(null);
  const [spreadPips, setSpreadPips] = useState(null);
  const [dxy, setDxy] = useState(null);
  const [us10y, setUs10y] = useState(null);
  const [account, setAccount] = useState(null);
  const [marketBundle, setMarketBundle] = useState(null);
  const [resolvedSymbol, setResolvedSymbol] = useState(symbol);
  const [feedError, setFeedError] = useState('');
  const [feedReady, setFeedReady] = useState(false);
  const symRef = useRef(symbol);
  const fullLoadDoneRef = useRef(false);
  const inflightRef = useRef(false);
  const loadGenRef = useRef(0);

  const applyMacroLast = useCallback((dxyRes, uyRes) => {
    if (dxyRes?.bars?.length) {
      const d = dxyRes.bars[dxyRes.bars.length - 1].c;
      setDxy(parseFloat(Number(d).toFixed(2)));
    }
    if (uyRes?.bars?.length) {
      const u = uyRes.bars[uyRes.bars.length - 1].c;
      setUs10y(parseFloat(Number(u).toFixed(3)));
    }
  }, []);

  const applyGoldLast = useCallback((gold) => {
    const last = gold[gold.length - 1];
    if (last?.c != null) setPrice(parseFloat(Number(last.c).toFixed(2)));
  }, []);

  const writeCache = useCallback(
    async (gold, acc, dxyBars, uyBars, sym) => {
      try {
        await AsyncStorage.setItem(
          CACHE_KEY,
          JSON.stringify({
            t: Date.now(),
            baseUrl: baseUrl?.trim(),
            symbol: sym,
            gold,
            account: acc,
            dxyBars: dxyBars ?? [],
            uyBars: uyBars ?? [],
          })
        );
      } catch {
        /* ignore */
      }
    },
    [baseUrl]
  );

  const readCache = useCallback(async () => {
    try {
      const raw = await AsyncStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const j = JSON.parse(raw);
      if (!j?.gold?.length || Date.now() - (j.t ?? 0) > CACHE_TTL_MS) return null;
      if (j.baseUrl !== baseUrl?.trim()) return null;
      return j;
    } catch {
      return null;
    }
  }, [baseUrl]);

  const loadHistory = useCallback(
    async (barCount, opts = { macro: true }, gen = loadGenRef.current) => {
      const b = baseUrl?.trim();
      if (!b || !connected || inflightRef.current) return false;
      if (gen !== loadGenRef.current) return false;
      inflightRef.current = true;
      try {
        const sym = symRef.current;
        const gold = await fetchMt5BarsM30(b, sym, barCount);
        if (gen !== loadGenRef.current) return false;
        if (!gold.length) {
          setFeedError('No M30 bars from MT5');
          return false;
        }
        let dxyRes = { bars: [] };
        let uyRes = { bars: [] };
        if (opts.macro) {
          const macroN = Math.min(gold.length, barCount === FULL_BARS ? FULL_BARS : MACRO_STARTUP_BARS);
          [dxyRes, uyRes] = await Promise.all([
            fetchBarsFirst(b, DXY_CANDIDATES, macroN),
            fetchBarsFirst(b, US10Y_CANDIDATES, macroN),
          ]);
        }
        if (gen !== loadGenRef.current) return false;
        setMarketBundle(bundleFromGold(gold, dxyRes.bars, uyRes.bars));
        applyGoldLast(gold);
        applyMacroLast(dxyRes, uyRes);
        setFeedReady(true);
        setFeedError('');
        const st = await fetchStatusAccount(b);
        if (gen !== loadGenRef.current) return false;
        if (st.account) setAccount(st.account);
        void writeCache(gold, st.account, dxyRes.bars, uyRes.bars, sym);
        return true;
      } catch (e) {
        setFeedError(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        inflightRef.current = false;
      }
    },
    [baseUrl, connected, applyGoldLast, applyMacroLast, writeCache]
  );

  const bootstrap = useCallback(async () => {
    const b = baseUrl?.trim();
    if (!b || !connected) return;

    const cached = await readCache();
    if (cached?.gold?.length) {
      symRef.current = cached.symbol || symRef.current;
      setResolvedSymbol(symRef.current);
      if (cached.account) setAccount(cached.account);
      setMarketBundle(bundleFromGold(cached.gold, cached.dxyBars, cached.uyBars));
      applyGoldLast(cached.gold);
      applyMacroLast({ bars: cached.dxyBars }, { bars: cached.uyBars });
      setFeedReady(true);
      setFeedError('');

      const [status, tick] = await Promise.all([
        fetchStatusAccount(b),
        fetchMt5Tick(b, symRef.current),
      ]);
      if (!status.connected) {
        setFeedError('MT5 API not connected');
        setFeedReady(false);
        return;
      }
      if (status.account) setAccount(status.account);
      applyTickState(tick, { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol });

      if (!fullLoadDoneRef.current) {
        fullLoadDoneRef.current = true;
        void loadHistory(FULL_BARS, { macro: true }, loadGenRef.current);
      }
      return;
    }

    const [status, resolved, tick, gold] = await Promise.all([
      fetchStatusAccount(b),
      fetchMt5ResolvedSymbol(b, symbol),
      fetchMt5Tick(b, symRef.current),
      fetchMt5BarsM30(b, symRef.current, STARTUP_BARS),
    ]);

    if (!status.connected) {
      setFeedError('MT5 API not connected');
      setFeedReady(false);
      return;
    }
    if (status.account) setAccount(status.account);
    if (resolved) {
      symRef.current = resolved;
      setResolvedSymbol(resolved);
    }
    applyTickState(tick, { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol });

    if (!gold.length) {
      setFeedError('No M30 bars from MT5');
      setFeedReady(false);
      return;
    }

    setMarketBundle(bundleFromGold(gold));
    applyGoldLast(gold);
    setFeedReady(true);
    setFeedError('');

    const macroN = Math.min(gold.length, MACRO_STARTUP_BARS);
    const [dxyRes, uyRes] = await Promise.all([
      fetchBarsFirst(b, DXY_CANDIDATES, macroN),
      fetchBarsFirst(b, US10Y_CANDIDATES, macroN),
    ]);
    setMarketBundle(bundleFromGold(gold, dxyRes.bars, uyRes.bars));
    applyMacroLast(dxyRes, uyRes);
    void writeCache(gold, status.account, dxyRes.bars, uyRes.bars, symRef.current);

    if (!fullLoadDoneRef.current) {
      fullLoadDoneRef.current = true;
      void loadHistory(FULL_BARS, { macro: true }, loadGenRef.current);
    }
  }, [
    baseUrl,
    connected,
    symbol,
    readCache,
    applyGoldLast,
    applyMacroLast,
    writeCache,
    loadHistory,
  ]);

  useEffect(() => {
    if (!enabled || !connected || !baseUrl?.trim()) {
      loadGenRef.current += 1;
      setFeedReady(false);
      setMarketBundle(null);
      setPrice(null);
      setBid(null);
      setAsk(null);
      setSpreadPips(null);
      setAccount(null);
      fullLoadDoneRef.current = false;
      return undefined;
    }
    fullLoadDoneRef.current = false;
    const gen = ++loadGenRef.current;
    let cancelled = false;
    void (async () => {
      await bootstrap();
      if (cancelled || gen !== loadGenRef.current) return;
    })();
    const barId = setInterval(() => {
      void loadHistory(FULL_BARS, { macro: true }, loadGenRef.current);
    }, 90_000);
    const acctId = setInterval(async () => {
      const b = baseUrl.trim();
      const st = await fetchStatusAccount(b);
      if (st.account) setAccount(st.account);
    }, 5000);
    return () => {
      cancelled = true;
      clearInterval(barId);
      clearInterval(acctId);
    };
  }, [enabled, connected, baseUrl, symbol, bootstrap, loadHistory]);

  useEffect(() => {
    if (!pollTicks || !enabled || !connected || !baseUrl?.trim()) return undefined;
    const b = baseUrl.trim();
    let cancelled = false;
    const poll = async () => {
      const tk = await fetchMt5Tick(b, symRef.current);
      if (cancelled) return;
      applyTickState(tk, { setBid, setAsk, setPrice, setSpreadPips, setResolvedSymbol });
    };
    void poll();
    const id = setInterval(poll, 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollTicks, enabled, connected, baseUrl]);

  return {
    price,
    bid,
    ask,
    spreadPips,
    dxy,
    us10y,
    account,
    marketBundle,
    resolvedSymbol,
    feedError,
    feedReady,
  };
}
