import React, { useMemo } from 'react';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { PilotCard, PilotSectionTitle } from '../pilot/PilotUI';
import ScannerEngineVisual from './ScannerEngineVisual';
import { radius, spacing } from '../../theme/designTokens';
import { isExecutionQueueStatus, isActiveTradeStatus, formatScannerStatus } from '../../lib/scannerExecution';

function statusColor(status, C) {
  if (status === 'Pending') return C.accentLight;
  if (status === 'Watching') return C.amber;
  if (isActiveTradeStatus(status)) return C.teal;
  return C.dim2;
}

function rowPriority(row) {
  const status = row?.status || '';
  if (status === 'Pending') return 0;
  if (status === 'Watching') return 1;
  if (isActiveTradeStatus(status)) return 2;
  return 3;
}

function fmtVol(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v <= 0) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(Math.round(v));
}

function fmtPct(n, decimals = 2) {
  const v = Number(n);
  if (!Number.isFinite(v) || Math.abs(v) < 0.02) return '—';
  const prefix = v > 0 ? '+' : '';
  return `${prefix}${v.toFixed(decimals)}%`;
}

function pctColor(v, C) {
  const n = Number(v);
  if (!Number.isFinite(n) || Math.abs(n) < 0.02) return C.dim2;
  return n > 0 ? C.green : C.red;
}

function activityScore(row) {
  const vals = [row.pct1m, row.pct3m, row.pct5m, row.pct15m, row.pctGain].map(Number).filter((v) => Number.isFinite(v));
  if (!vals.length) return 0;
  return Math.min(1, Math.max(...vals.map((v) => Math.abs(v))) / 12);
}

function ActivityBar({ score, C }) {
  const w = `${Math.round(Math.min(1, Math.max(0, score)) * 100)}%`;
  const hot = score >= 0.45;
  return (
    <View
      style={{
        height: 5,
        borderRadius: radius.pill,
        backgroundColor: C.border,
        overflow: 'hidden',
        width: 36,
      }}>
      <View
        style={{
          width: w,
          height: '100%',
          borderRadius: radius.pill,
          backgroundColor: hot ? C.accentLight : C.teal,
          opacity: 0.35 + score * 0.65,
        }}
      />
    </View>
  );
}

const TF_COLS = [
  { key: 'pct1m', label: '1m' },
  { key: 'pct3m', label: '3m' },
  { key: 'pct5m', label: '5m' },
  { key: 'pct15m', label: '15m' },
];

function MarketTableHeader({ C }) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 10,
        paddingHorizontal: 4,
        borderBottomWidth: 1,
        borderBottomColor: C.border,
        minWidth: 380,
      }}>
      <Text style={{ width: 64, color: C.dim, fontSize: 10, fontWeight: '800', letterSpacing: 0.8 }}>Asset</Text>
      {TF_COLS.map((col) => (
        <Text
          key={col.key}
          style={{
            width: 48,
            color: C.dim,
            fontSize: 10,
            fontWeight: '800',
            letterSpacing: 0.6,
            textAlign: 'right',
          }}>
          {col.label}
        </Text>
      ))}
      <Text
        style={{
          width: 56,
          color: C.dim,
          fontSize: 10,
          fontWeight: '800',
          letterSpacing: 0.6,
          textAlign: 'right',
        }}>
        Status
      </Text>
      <Text
        style={{
          width: 44,
          color: C.dim,
          fontSize: 10,
          fontWeight: '800',
          letterSpacing: 0.6,
          textAlign: 'right',
        }}>
        24h
      </Text>
      <Text
        style={{
          width: 40,
          color: C.dim,
          fontSize: 10,
          fontWeight: '800',
          letterSpacing: 0.6,
          textAlign: 'right',
        }}>
        Flow
      </Text>
      <Text
        style={{
          width: 44,
          color: C.dim,
          fontSize: 10,
          fontWeight: '800',
          letterSpacing: 0.6,
          textAlign: 'right',
        }}>
        Vol
      </Text>
    </View>
  );
}

function MarketTableRow({ row, C }) {
  const score = activityScore(row);
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 10,
        paddingHorizontal: 4,
        borderBottomWidth: 1,
        borderBottomColor: C.border,
        minWidth: 380,
      }}>
      <Text style={{ width: 64, color: C.text, fontSize: 12, fontWeight: '800' }} numberOfLines={1}>
        {row.coin || row.symbol}
      </Text>
      {TF_COLS.map((col) => (
        <Text
          key={col.key}
          style={{
            width: 48,
            color: pctColor(row[col.key], C),
            fontSize: 11,
            fontWeight: '700',
            textAlign: 'right',
            fontVariant: ['tabular-nums'],
          }}>
          {fmtPct(row[col.key])}
        </Text>
      ))}
      <Text
        style={{
          width: 56,
          color: statusColor(row.status, C),
          fontSize: 10,
          fontWeight: '800',
          textAlign: 'right',
        }}
        numberOfLines={1}>
        {isExecutionQueueStatus(row.status) ? row.status : row.status === 'Scanning' ? '—' : formatScannerStatus(row.status) || '—'}
      </Text>
      <Text
        style={{
          width: 44,
          color: pctColor(row.pct24h, C),
          fontSize: 11,
          fontWeight: '700',
          textAlign: 'right',
          fontVariant: ['tabular-nums'],
        }}>
        {fmtPct(row.pct24h, 1)}
      </Text>
      <View style={{ width: 40, alignItems: 'flex-end' }}>
        <ActivityBar score={score} C={C} />
      </View>
      <Text
        style={{
          width: 44,
          color: C.dim2,
          fontSize: 10,
          fontWeight: '700',
          textAlign: 'right',
          fontVariant: ['tabular-nums'],
        }}>
        {fmtVol(row.volume24h)}
      </Text>
    </View>
  );
}

export default function TickScannerHome({
  rows,
  ready,
  error,
  connected,
  sessionExec,
  scannerMeta,
}) {
  const { colors: C } = useBilshenzTheme();

  const execOn =
    connected &&
    (sessionExec?.canExecute === true || (sessionExec?.canExecute !== false && scannerMeta?.can_execute !== false));

  const marketRows = useMemo(() => {
    return [...(rows || [])]
      .sort((a, b) => {
        const pr = rowPriority(a) - rowPriority(b);
        if (pr !== 0) return pr;
        return activityScore(b) - activityScore(a);
      })
      .slice(0, 24);
  }, [rows]);

  const pulse = useMemo(() => {
    if (!marketRows.length) return ready ? 0.35 : 0.2;
    const top = marketRows.slice(0, 5).reduce((s, r) => s + activityScore(r), 0) / Math.min(5, marketRows.length);
    return top;
  }, [marketRows, ready]);

  return (
    <View style={{ flex: 1 }}>
      <ScannerEngineVisual
        ready={ready}
        execOn={execOn}
        connected={connected}
        pulse={pulse}
        rows={marketRows}
      />

      <PilotCard style={{ marginBottom: spacing.md, paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: spacing.xs }}>
        <PilotSectionTitle title="Market overview" />
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flex: 1, minWidth: '100%' }}>
            <MarketTableHeader C={C} />
            {!ready && !error ? (
              <View style={{ paddingVertical: 28, alignItems: 'center' }}>
                <ActivityIndicator color={C.accentLight} />
                <Text style={{ color: C.dim, fontSize: 12, marginTop: 10 }}>Syncing market data…</Text>
              </View>
            ) : marketRows.length ? (
              marketRows.map((row) => <MarketTableRow key={row.symbol} row={row} C={C} />)
            ) : (
              <Text style={{ color: C.dim, fontSize: 12, textAlign: 'center', paddingVertical: 22, lineHeight: 18 }}>
                {connected
                  ? 'Engine live — ranking USDT-M movers by 1m / 3m / 5m / 15m tick change (max 15m).'
                  : 'Connect Binance to arm execution. Market scan loads in the background.'}
              </Text>
            )}
          </View>
        </ScrollView>
        {error ? (
          <Text style={{ color: C.amber, fontSize: 11, textAlign: 'center', paddingVertical: 8 }} numberOfLines={2}>
            Connection issue — engine will retry automatically.
          </Text>
        ) : null}
      </PilotCard>
    </View>
  );
}
