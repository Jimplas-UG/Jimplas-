import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { fetchBinanceTradeCalendar } from '../broker/binanceFuturesApi';
import {
  CALENDAR_VIEWS,
  aggregateDealsToDays,
  fmtCalendarMoney,
  indexDaysByDate,
  monthGrid,
  weekCells,
  yearMonths,
} from '../lib/tradeCalendarModel';

const WEEKDAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

/** Drop desks-impossible day aggregates (phantom ~qty USD losses). */
export function sanitizeCalendarDays(days, maxDayAbs = 20000) {
  return (days ?? [])
    .map((row) => {
      const pnl = Number(row?.pnl ?? 0);
      if (!Number.isFinite(pnl) || Math.abs(pnl) > maxDayAbs) {
        return null;
      }
      return { ...row, pnl, trades: Number(row?.trades ?? 0) };
    })
    .filter(Boolean);
}

function PnlCell({ cell, C, compact }) {
  const pnl = Number(cell.pnl ?? 0);
  const win = pnl > 0;
  const loss = pnl < 0;
  const bg = win ? 'rgba(0,230,118,0.18)' : loss ? 'rgba(255,61,87,0.18)' : C.panel2;
  const border = win ? 'rgba(0,230,118,0.45)' : loss ? 'rgba(255,61,87,0.45)' : C.border;
  const col = win ? C.green : loss ? C.red : C.dim;
  return (
    <View style={[st.cell, compact && st.cellCompact, { backgroundColor: bg, borderColor: border }]}>
      <Text style={[st.cellDay, { color: C.dim }]}>{cell.day ?? cell.label}</Text>
      {cell.hasData ? (
        <>
          <Text style={[st.cellPnl, { color: col }]}>{fmtCalendarMoney(pnl)}</Text>
          <Text style={[st.cellTrades, { color: C.dim }]}>
            {cell.trades} {cell.trades === 1 ? 'close' : 'closes'}
          </Text>
        </>
      ) : (
        <Text style={[st.cellDash, { color: C.dim }]}>—</Text>
      )}
    </View>
  );
}

export default function TradeResultsCalendar({ binanceBaseUrl, brokerConnected, brokerDeals = [] }) {
  const { colors: C } = useBilshenzTheme();
  const [view, setView] = useState('month');
  const [cursor, setCursor] = useState(() => new Date());
  const [serverDays, setServerDays] = useState([]);
  const [totalPnl, setTotalPnl] = useState(0);
  const [loading, setLoading] = useState(false);

  const [calendarMeta, setCalendarMeta] = useState({ tz: '', since: '', source: '' });

  const dealsSignature = useMemo(() => {
    if (!brokerDeals?.length) return '0';
    const last = brokerDeals[0];
    const stamp = last?.time ?? last?.timestamp ?? last?.id ?? '';
    return `${brokerDeals.length}:${stamp}`;
  }, [brokerDeals]);

  const applyLocalDays = useCallback((deals) => {
    const local = aggregateDealsToDays(deals);
    setServerDays(local);
    setTotalPnl(local.reduce((s, d) => s + d.pnl, 0));
  }, []);

  useEffect(() => {
    if (!brokerConnected || !binanceBaseUrl?.trim()) {
      applyLocalDays(brokerDeals);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const j = await fetchBinanceTradeCalendar(binanceBaseUrl, 400);
        if (cancelled) return;
        if (j?.days?.length) {
          const clean = sanitizeCalendarDays(j.days);
          setServerDays(clean);
          const sum = clean.reduce((s, d) => s + Number(d.pnl ?? 0), 0);
          // Period total always from days — ignore poisoned j.total_pnl
          setTotalPnl(Number.isFinite(sum) ? sum : 0);
          setCalendarMeta({
            tz: j.tz || 'Africa/Nairobi',
            since: j.since || '',
            source: j.source || 'income',
          });
        } else {
          applyLocalDays(brokerDeals);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [binanceBaseUrl, brokerConnected, dealsSignature, applyLocalDays]);

  const dayMap = useMemo(() => indexDaysByDate(serverDays), [serverDays]);
  const y = cursor.getFullYear();
  const m = cursor.getMonth();

  const periodTotal = useMemo(() => {
    if (view === 'month') {
      const prefix = `${y}-${String(m + 1).padStart(2, '0')}`;
      return serverDays.filter((d) => d.date?.startsWith(prefix)).reduce((s, d) => s + Number(d.pnl || 0), 0);
    }
    if (view === 'year') {
      return serverDays.filter((d) => d.date?.startsWith(String(y))).reduce((s, d) => s + Number(d.pnl || 0), 0);
    }
    if (view === 'week') {
      return weekCells(cursor, dayMap).reduce((s, c) => s + (c.hasData ? Number(c.pnl || 0) : 0), 0);
    }
    return totalPnl;
  }, [view, y, m, cursor, serverDays, dayMap, totalPnl]);

  const title =
    view === 'month'
      ? cursor.toLocaleString('en-US', { month: 'long', year: 'numeric' })
      : view === 'year'
        ? String(y)
        : view === 'week'
          ? 'This week'
          : 'All time';

  const shift = (dir) => {
    const next = new Date(cursor);
    if (view === 'month') next.setMonth(next.getMonth() + dir);
    else if (view === 'year') next.setFullYear(next.getFullYear() + dir);
    else next.setDate(next.getDate() + dir * 7);
    setCursor(next);
  };

  const cells =
    view === 'month'
      ? monthGrid(y, m, dayMap)
      : view === 'week'
        ? weekCells(cursor, dayMap)
        : view === 'year'
          ? yearMonths(y, dayMap)
          : serverDays.slice(-60).map((d) => {
              const parts = d.date.split('-');
              return { ...d, day: Number(parts[2]), hasData: true };
            });

  return (
    <View style={[st.wrap, { borderColor: C.border, backgroundColor: C.panel }]}>
      <View style={[st.head, { borderBottomColor: C.border }]}>
        <Text style={[st.title, { color: C.text }]}>Trade results</Text>
        <Text style={[st.badge, { color: loading ? C.amber : C.teal }]}>
          {loading ? '…' : calendarMeta.tz ? `LIVE · ${calendarMeta.tz.split('/').pop()}` : 'LIVE'}
        </Text>
      </View>

      <View style={st.tabs}>
        {CALENDAR_VIEWS.map((v) => {
          const on = view === v.id;
          return (
            <Pressable
              key={v.id}
              onPress={() => setView(v.id)}
              style={[st.tab, on && { backgroundColor: C.green, borderColor: C.green }]}>
              <Text style={[st.tabTxt, { color: on ? '#0a1a12' : C.dim }]}>{v.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <View style={st.summaryRow}>
        <View style={[st.summaryCard, { borderColor: C.border, backgroundColor: C.panel2 }]}>
          <Text style={[st.summaryLab, { color: C.dim }]}>Total P&L</Text>
          <Text style={[st.summaryVal, { color: periodTotal >= 0 ? C.green : C.red }]}>
            ${Math.abs(periodTotal).toFixed(2)}
            {periodTotal < 0 ? ' loss' : ''}
          </Text>
        </View>
        <View style={[st.summaryCard, { borderColor: C.border, backgroundColor: C.panel2 }]}>
          <Text style={[st.summaryLab, { color: C.dim }]}>Period</Text>
          <Text style={[st.summaryValSm, { color: C.text }]}>{title}</Text>
        </View>
      </View>

      {view !== 'all' ? (
        <View style={st.navRow}>
          <Pressable onPress={() => shift(-1)} hitSlop={8}>
            <Text style={{ color: C.accentLight, fontSize: 18 }}>‹</Text>
          </Pressable>
          <Text style={[st.navTitle, { color: C.text }]}>{title}</Text>
          <Pressable onPress={() => shift(1)} hitSlop={8}>
            <Text style={{ color: C.accentLight, fontSize: 18 }}>›</Text>
          </Pressable>
        </View>
      ) : null}

      {view === 'month' ? (
        <View style={st.dowRow}>
          {WEEKDAYS.map((w) => (
            <Text key={w} style={[st.dow, { color: C.dim }]}>
              {w}
            </Text>
          ))}
        </View>
      ) : null}

      <View style={[st.grid, view === 'year' && st.gridYear]}>
        {cells.map((cell) => (
          <PnlCell
            key={cell.date ?? `${cell.month}-${cell.label}`}
            cell={cell}
            C={C}
            compact={view === 'year'}
          />
        ))}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { borderWidth: 1, borderRadius: 16, overflow: 'hidden', marginTop: 10 },
  head: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
  },
  title: { fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  badge: { fontSize: 10, fontWeight: '800' },
  tabs: { flexDirection: 'row', gap: 6, padding: 10 },
  tab: {
    flex: 1,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    alignItems: 'center',
  },
  tabTxt: { fontSize: 10, fontWeight: '800' },
  summaryRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 10, paddingBottom: 8 },
  summaryCard: { flex: 1, borderWidth: 1, borderRadius: 12, padding: 10 },
  summaryLab: { fontSize: 9, fontWeight: '700', letterSpacing: 0.4 },
  summaryVal: { fontSize: 20, fontWeight: '800', marginTop: 4 },
  summaryValSm: { fontSize: 13, fontWeight: '700', marginTop: 6 },
  navRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingBottom: 8,
  },
  navTitle: { fontSize: 13, fontWeight: '700' },
  dowRow: { flexDirection: 'row', paddingHorizontal: 10, marginBottom: 4 },
  dow: { flex: 1, textAlign: 'center', fontSize: 9, fontWeight: '700' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', padding: 8, gap: 6 },
  gridYear: { gap: 8 },
  cell: {
    width: '12.5%',
    minWidth: 42,
    flexGrow: 1,
    aspectRatio: 0.95,
    borderRadius: 12,
    borderWidth: 1,
    padding: 6,
    justifyContent: 'space-between',
  },
  cellCompact: { width: '30%', minWidth: 90 },
  cellDay: { fontSize: 10, fontWeight: '700' },
  cellPnl: { fontSize: 11, fontWeight: '800', textAlign: 'center' },
  cellTrades: { fontSize: 8, fontWeight: '600', textAlign: 'center' },
  cellDash: { fontSize: 14, textAlign: 'center', marginTop: 8 },
});
