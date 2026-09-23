import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { displayDealPnl, isCloseDeal } from '../lib/dealPnl';
import { formatFuturesPrice } from '../lib/futuresPrice';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'closed', label: 'Closed' },
  { id: 'long', label: 'Long' },
  { id: 'short', label: 'Short' },
  { id: 'win', label: 'Winning' },
  { id: 'loss', label: 'Losing' },
  { id: 'today', label: 'Today' },
];

function fmtUsd(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  const sign = x >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(x).toFixed(2)}`;
}

function fmtPx(n) {
  return formatFuturesPrice(n);
}

function fmtTime(ms) {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '—';
  const d = new Date(t);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')} ${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')} UTC`;
}

function sideOf(deal) {
  const s = String(deal?.positionSide || deal?.side || deal?.type || '').toUpperCase();
  if (s.includes('SHORT') || s === 'SELL') return 'SHORT';
  if (s.includes('LONG') || s === 'BUY') return 'LONG';
  return s || '—';
}

function startOfUtcDay() {
  const d = new Date();
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

/**
 * Clear exchange-reconciled fill/close history (from bridge /api/logs deals).
 */
export default function TradeHistoryPanel({ brokerDeals = [], limit = 40 }) {
  const { colors: C } = useBilshenzTheme();
  const [filter, setFilter] = useState('all');

  const rows = useMemo(() => {
    const day0 = startOfUtcDay();
    let list = Array.isArray(brokerDeals) ? [...brokerDeals] : [];
    list.sort((a, b) => (b.time ?? 0) - (a.time ?? 0));
    list = list.filter((d) => {
      const pnl = displayDealPnl(d);
      const side = sideOf(d);
      const closed = isCloseDeal(d) || d?.realized_pnl != null || d?.profit != null;
      if (filter === 'closed') return closed;
      if (filter === 'long') return side === 'LONG';
      if (filter === 'short') return side === 'SHORT';
      if (filter === 'win') return Number(pnl) > 0;
      if (filter === 'loss') return Number(pnl) < 0;
      if (filter === 'today') return Number(d.time) >= day0;
      return true;
    });
    return list.slice(0, limit);
  }, [brokerDeals, filter, limit]);

  return (
    <View style={[st.wrap, { borderColor: C.border, backgroundColor: C.panel }]}>
      <Text style={[st.title, { color: C.text }]}>Trade history</Text>
      <Text style={[st.sub, { color: C.dim }]}>
        Exchange fills · realized PnL from Binance · newest first
      </Text>
      <View style={st.filters}>
        {FILTERS.map((f) => {
          const on = filter === f.id;
          return (
            <Pressable
              key={f.id}
              onPress={() => setFilter(f.id)}
              style={[st.chip, { borderColor: on ? C.accentLight : C.border, backgroundColor: on ? 'rgba(167,139,250,0.16)' : C.panel2 }]}>
              <Text style={{ color: on ? C.accentLight : C.dim, fontSize: 10, fontWeight: '700' }}>{f.label}</Text>
            </Pressable>
          );
        })}
      </View>

      {!rows.length ? (
        <Text style={[st.empty, { color: C.dim }]}>No fills for this filter.</Text>
      ) : (
        rows.map((d, i) => {
          const pnl = Number(displayDealPnl(d));
          const side = sideOf(d);
          const px = d.price ?? d.fill_price ?? d.avgPrice;
          const qty = d.volume ?? d.qty ?? d.quantity;
          const fee = d.commission ?? d.fee;
          const orderId = d.order ?? d.orderId ?? d.order_id;
          return (
            <View key={`${d.id || orderId || i}-${d.time || i}`} style={[st.card, { borderColor: C.border }]}>
              <View style={st.row}>
                <Text style={[st.sym, { color: C.text }]}>{d.symbol || '—'}</Text>
                <Text style={{ color: side === 'SHORT' ? C.red : C.green, fontWeight: '800', fontSize: 11 }}>{side}</Text>
                <Text style={{ color: Number.isFinite(pnl) ? (pnl >= 0 ? C.green : C.red) : C.dim, fontWeight: '800', marginLeft: 'auto' }}>
                  {fmtUsd(pnl)}
                </Text>
              </View>
              <Text style={[st.meta, { color: C.dim }]}>{fmtTime(d.time)}</Text>
              <View style={st.grid}>
                <Meta label="Price" value={fmtPx(px)} C={C} />
                <Meta label="Qty" value={qty != null ? String(qty) : '—'} C={C} />
                <Meta label="Fee" value={fee != null ? fmtUsd(-Math.abs(Number(fee))) : '—'} C={C} />
                <Meta label="Order" value={orderId != null ? String(orderId) : '—'} C={C} />
              </View>
              <Text style={[st.status, { color: C.dim2 }]}>
                {isCloseDeal(d) ? 'CLOSE FILL' : 'FILL'} · exchange-reconciled
              </Text>
            </View>
          );
        })
      )}
    </View>
  );
}

function Meta({ label, value, C }) {
  return (
    <View style={st.metaCell}>
      <Text style={{ color: C.dim, fontSize: 9, fontWeight: '700' }}>{label}</Text>
      <Text style={{ color: C.text, fontSize: 11, fontWeight: '600' }} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { borderWidth: 1, borderRadius: 16, padding: 12, marginTop: 12 },
  title: { fontSize: 13, fontWeight: '800' },
  sub: { fontSize: 10, marginTop: 4, marginBottom: 10, lineHeight: 14 },
  filters: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  empty: { fontSize: 12, paddingVertical: 16, textAlign: 'center' },
  card: { borderWidth: 1, borderRadius: 12, padding: 10, marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sym: { fontSize: 13, fontWeight: '800' },
  meta: { fontSize: 10, marginTop: 4 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 8, gap: 8 },
  metaCell: { width: '47%', minWidth: 120 },
  status: { fontSize: 9, marginTop: 8, fontWeight: '700', letterSpacing: 0.3 },
});
