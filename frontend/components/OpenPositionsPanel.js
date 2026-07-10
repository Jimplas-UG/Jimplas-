import React, { useCallback, useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { formatFuturesPrice } from '../lib/futuresPrice';
import { postBinanceClosePosition, postBinanceCloseAllPositions } from '../broker/binanceFuturesApi';
import { formatPairLabel } from '../lib/futuresSymbol';

function fmtPx(n) {
  return formatFuturesPrice(n);
}

function fmtUsd(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  const sign = x >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(x).toFixed(2)}`;
}

function fmtVol(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  if (x >= 1000) return x.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(x);
}

function parseCloseError(r) {
  if (r.error) return String(r.error);
  const s = r.bodySnippet || '';
  if (s.includes('less_than_equal') && s.includes('volume')) {
    return 'Close blocked by server — update the app or try again (volume limit).';
  }
  try {
    const j = JSON.parse(s);
    if (Array.isArray(j) && j[0]?.msg) return j[0].msg;
    if (j?.error) return String(j.error);
    if (j?.detail?.error) return String(j.detail.error);
  } catch {
    /* plain text */
  }
  return s || 'Could not close position';
}

function fmtDealTime(ms) {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '—';
  const d = new Date(t);
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')} UTC`;
}

export default function OpenPositionsPanel({
  positions = [],
  brokerDeals = [],
  livePrice,
  bid,
  ask,
  binanceBaseUrl,
  brokerConnected,
  quoteSymbol,
  hideQuote = false,
  onRefresh,
  onRefreshAfterClose,
  onCloseMessage,
}) {
  const { colors: C, styles: appStyles } = useBilshenzTheme();
  const [closingKey, setClosingKey] = useState(null);
  const pairLabel = formatPairLabel(
    quoteSymbol || (positions.length === 1 ? positions[0]?.symbol : null) || 'BTCUSDT',
  );

  const watchDeals = useMemo(() => {
    const rows = Array.isArray(brokerDeals) ? [...brokerDeals] : [];
    return rows.sort((a, b) => (b.time ?? 0) - (a.time ?? 0)).slice(0, 8);
  }, [brokerDeals]);

  const totalFloating = useMemo(
    () => positions.reduce((sum, p) => sum + Number(p.profit ?? 0), 0),
    [positions],
  );

  const confirmClose = useCallback(
    (pos) => {
      if (!brokerConnected || !binanceBaseUrl?.trim()) {
        Alert.alert('Not connected', 'Connect Binance in Profile first.');
        return;
      }
      const profit = Number(pos.profit ?? 0);
      const profitLbl = fmtUsd(profit);
      Alert.alert(
        'Close position?',
        `${pos.type} ${pos.volume} ${pos.symbol ?? pairLabel}\nEntry ${fmtPx(pos.price_open)} · Now ${fmtPx(livePrice)}\nFloating ${profitLbl}`,
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Close now',
            style: profit >= 0 ? 'default' : 'destructive',
            onPress: () => {
              void (async () => {
                const key = `${pos.symbol}-${pos.type}-${pos.price_open}`;
                setClosingKey(key);
                try {
                  const r = await postBinanceClosePosition(binanceBaseUrl, {
                    symbol: pos.symbol,
                  });
                  if (r.ok) {
                    const closed = r.closed?.[0];
                    const realized = Number(closed?.realized_pnl ?? closed?.profit ?? 0);
                    const msg = closed
                      ? `Closed ${closed.side} ${fmtVol(closed.volume)} @ ${fmtPx(closed.fill_price)} · P&L ${fmtUsd(realized)}`
                      : 'Position closed';
                    onCloseMessage?.(msg);
                    if (onRefreshAfterClose) {
                      await onRefreshAfterClose();
                    } else {
                      await onRefresh?.();
                    }
                  } else {
                    const err = parseCloseError(r);
                    const lat = r.latencyMs != null ? ` (${r.latencyMs} ms)` : '';
                    Alert.alert('Close failed', `${err}${lat}`);
                  }
                } catch (e) {
                  Alert.alert('Close failed', e instanceof Error ? e.message : String(e));
                } finally {
                  setClosingKey(null);
                }
              })();
            },
          },
        ],
      );
    },
    [brokerConnected, binanceBaseUrl, livePrice, onRefresh, onRefreshAfterClose, onCloseMessage, pairLabel],
  );

  const confirmCloseAll = useCallback(() => {
    if (!brokerConnected || !binanceBaseUrl?.trim()) {
      Alert.alert('Not connected', 'Connect Binance in Profile first.');
      return;
    }
    Alert.alert(
      'Close all positions?',
      `This will market-close all ${positions.length} open position(s) on Binance.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Close all',
          style: 'destructive',
          onPress: () => {
            void (async () => {
              setClosingKey('__all__');
              try {
                const r = await postBinanceCloseAllPositions(binanceBaseUrl);
                if (r.ok) {
                  onCloseMessage?.(`Closed ${r.closed?.length ?? 0} leg(s)`);
                  if (onRefreshAfterClose) {
                    await onRefreshAfterClose();
                  } else {
                    await onRefresh?.();
                  }
                } else {
                  Alert.alert('Close all failed', parseCloseError(r));
                }
              } catch (e) {
                Alert.alert('Close all failed', e instanceof Error ? e.message : String(e));
              } finally {
                setClosingKey(null);
              }
            })();
          },
        },
      ],
    );
  }, [brokerConnected, binanceBaseUrl, positions.length, onRefresh, onRefreshAfterClose, onCloseMessage]);

  return (
    <View style={st.wrap}>
      {!hideQuote ? (
        <View style={[st.panel, { borderColor: C.border, backgroundColor: C.panel }]}>
          <View style={[st.head, { borderBottomColor: C.border }]}>
            <Text style={[st.title, { color: C.text }]}>Futures quote</Text>
            <Text style={[st.badge, { color: C.accentLight }]}>{pairLabel}</Text>
          </View>
          <View style={st.watchRow}>
            <WatchCell label="BID" value={fmtPx(bid)} color={C.red} />
            <WatchCell label="MID" value={fmtPx(livePrice)} color={C.text} large />
            <WatchCell label="ASK" value={fmtPx(ask)} color={C.green} />
          </View>
          <Text style={[st.watchHint, { color: C.dim }]}>
            USDT-M perpetual · updates while Binance is connected
          </Text>
        </View>
      ) : null}

      <View style={[st.panel, { borderColor: C.border, backgroundColor: C.panel, marginTop: hideQuote ? 0 : 10 }]}>
        <View style={[st.head, { borderBottomColor: C.border }]}>
          <Text style={[st.title, { color: C.text }]}>Open positions</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            {positions.length > 1 ? (
              <Pressable onPress={confirmCloseAll} disabled={closingKey === '__all__'} hitSlop={8}>
                <Text style={{ color: C.red, fontSize: 10, fontWeight: '800' }}>
                  {closingKey === '__all__' ? '…' : 'CLOSE ALL'}
                </Text>
              </Pressable>
            ) : null}
            <Text style={[st.badge, { color: positions.length ? C.green : C.dim }]}>
              {positions.length ? String(positions.length) : 'FLAT'}
            </Text>
          </View>
        </View>

        {!brokerConnected ? (
          <Text style={[st.empty, { color: C.dim }]}>Connect Binance in Profile to watch live positions.</Text>
        ) : !positions.length ? (
          <Text style={[st.empty, { color: C.dim }]}>No open positions — flat on Binance.</Text>
        ) : (
          <>
            <View style={[st.totalRow, { borderColor: C.border }]}>
              <Text style={[st.totalLbl, { color: C.dim }]}>TOTAL FLOATING</Text>
              <Text style={[st.totalVal, { color: totalFloating >= 0 ? C.green : C.red }]}>
                {fmtUsd(totalFloating)}
              </Text>
            </View>
            {positions.map((p, i) => {
              const key = `${p.symbol}-${p.type}-${p.price_open}-${i}`;
              const profit = Number(p.profit ?? 0);
              const entry = Number(p.price_open ?? 0);
              const sideCol = p.type === 'BUY' ? C.green : C.red;
              const dist =
                Number.isFinite(livePrice) && entry > 0
                  ? formatFuturesPrice(p.type === 'BUY' ? livePrice - entry : entry - livePrice)
                  : '—';
              const busy = closingKey === `${p.symbol}-${p.type}-${p.price_open}`;
              return (
                <View key={key} style={[st.posCard, { borderColor: C.border, backgroundColor: C.panel2 }]}>
                  <View style={st.posTop}>
                    <Text style={[st.posSide, { color: sideCol }]}>
                      {p.type} · {fmtVol(p.volume)} {p.symbol}
                    </Text>
                    <Text style={[st.posPnl, { color: profit >= 0 ? C.green : C.red }]}>{fmtUsd(profit)}</Text>
                  </View>
                  <View style={st.posMeta}>
                    <Text style={[st.metaTxt, { color: C.dim }]}>Entry {fmtPx(entry)}</Text>
                    <Text style={[st.metaTxt, { color: C.dim }]}>Move {dist}</Text>
                    {p.leverage > 0 ? (
                      <Text style={[st.metaTxt, { color: C.amber }]}>{p.leverage}x lev</Text>
                    ) : null}
                    {p.margin_type ? (
                      <Text style={[st.metaTxt, { color: p.margin_type === 'ISOLATED' ? C.green : C.red }]}>
                        {p.margin_type}
                      </Text>
                    ) : null}
                    {p.sl > 0 ? <Text style={[st.metaTxt, { color: C.dim }]}>SL {fmtPx(p.sl)}</Text> : null}
                    {p.tp > 0 ? <Text style={[st.metaTxt, { color: C.dim }]}>TP {fmtPx(p.tp)}</Text> : null}
                  </View>
                  <Pressable
                    onPress={() => confirmClose(p)}
                    disabled={busy}
                    style={({ pressed }) => [
                      st.closeBtn,
                      {
                        borderColor: profit >= 0 ? 'rgba(0,230,118,0.45)' : 'rgba(255,61,87,0.45)',
                        backgroundColor: profit >= 0 ? 'rgba(0,230,118,0.12)' : 'rgba(255,61,87,0.12)',
                        opacity: pressed || busy ? 0.75 : 1,
                      },
                    ]}>
                    {busy ? (
                      <ActivityIndicator size="small" color={C.accentLight} />
                    ) : (
                      <Text style={[st.closeTxt, { color: profit >= 0 ? C.green : C.red }]}>
                        {profit >= 0 ? 'CLOSE IN PROFIT' : 'CLOSE AT LOSS'}
                      </Text>
                    )}
                  </Pressable>
                </View>
              );
            })}
          </>
        )}
      </View>

      <View style={[st.panel, { borderColor: C.border, backgroundColor: C.panel, marginTop: 10 }]}>
        <View style={[st.head, { borderBottomColor: C.border }]}>
          <Text style={[st.title, { color: C.text }]}>Recent fills</Text>
          <Text style={[st.badge, { color: C.teal }]}>Log</Text>
        </View>
        {!watchDeals.length ? (
          <Text style={[st.empty, { color: C.dim }]}>Recent fills appear here after trades execute.</Text>
        ) : (
          watchDeals.map((d, i) => {
            const pl = Number(d.profit ?? 0);
            const isCloseFill = pl !== 0;
            return (
              <View key={`${d.ticket ?? i}-${d.time ?? i}`} style={[st.logRow, { borderBottomColor: C.border }]}>
                <Text style={[st.logTime, { color: C.dim }]}>{fmtDealTime(d.time)}</Text>
                <Text style={[st.logSide, { color: d.type === 'BUY' ? C.green : C.red }]}>
                  {d.type} {fmtVol(d.volume)} {d.symbol ? `· ${d.symbol.replace('USDT', '')}` : ''}
                </Text>
                <Text style={[st.logPl, { color: isCloseFill ? (pl >= 0 ? C.green : C.red) : C.dim }]}>
                  {isCloseFill ? fmtUsd(pl) : `@ ${fmtPx(d.price)}`}
                </Text>
              </View>
            );
          })
        )}
      </View>
    </View>
  );
}

function WatchCell({ label, value, color, large }) {
  return (
    <View style={st.watchCell}>
      <Text style={[st.watchLab, { color }]}>{label}</Text>
      <Text style={[large ? st.watchValLg : st.watchVal, { color }]}>{value}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { marginBottom: 10 },
  panel: { borderWidth: 1, borderRadius: 16, overflow: 'hidden' },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
  },
  title: { fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  badge: { fontSize: 10, fontWeight: '800', letterSpacing: 0.4 },
  watchRow: { flexDirection: 'row', paddingHorizontal: 8, paddingTop: 12, paddingBottom: 4 },
  watchCell: { flex: 1, alignItems: 'center' },
  watchLab: { fontSize: 9, fontWeight: '700', letterSpacing: 0.5 },
  watchVal: { fontSize: 14, fontWeight: '800', marginTop: 4 },
  watchValLg: { fontSize: 18, fontWeight: '800', marginTop: 2 },
  watchHint: { fontSize: 9, textAlign: 'center', paddingBottom: 10, paddingHorizontal: 12 },
  empty: { fontSize: 11, lineHeight: 16, padding: 14 },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginHorizontal: 12,
    marginTop: 10,
    paddingBottom: 8,
    borderBottomWidth: 1,
  },
  totalLbl: { fontSize: 9, fontWeight: '700', letterSpacing: 0.4 },
  totalVal: { fontSize: 16, fontWeight: '800' },
  posCard: { marginHorizontal: 12, marginTop: 10, marginBottom: 4, borderWidth: 1, borderRadius: 14, padding: 12 },
  posTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  posSide: { fontSize: 12, fontWeight: '800' },
  posPnl: { fontSize: 15, fontWeight: '800' },
  posMeta: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 8 },
  metaTxt: { fontSize: 10, fontWeight: '600' },
  closeBtn: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  closeTxt: { fontSize: 11, fontWeight: '800', letterSpacing: 0.5 },
  logRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 8,
  },
  logTime: { width: 62, fontSize: 9, fontWeight: '600' },
  logSide: { flex: 1, fontSize: 10, fontWeight: '700' },
  logPl: { fontSize: 11, fontWeight: '800' },
});
