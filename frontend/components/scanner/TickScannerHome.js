import React, { useMemo } from 'react';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { PilotCard, PilotSectionTitle } from '../pilot/PilotUI';
import ScannerEngineVisual from './ScannerEngineVisual';
import { radius, spacing } from '../../theme/designTokens';

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
  const vals = [row.pct3m, row.pct5m, row.pct15m, row.pctGain].map(Number).filter((v) => Number.isFinite(v));
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
        minWidth: 340,
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
        minWidth: 340,
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
    </View>
  );
}

export default function TickScannerHome({
  rows,
  ready,
  error,
  connected,
  autoExecute,
  scannerMeta,
}) {
  const { colors: C } = useBilshenzTheme();

  const execOn =
    connected &&
    (autoExecute ?? scannerMeta?.exec_enabled !== false) &&
    scannerMeta?.exec_enabled !== false;

  const marketRows = useMemo(() => {
    return [...(rows || [])].sort((a, b) => activityScore(b) - activityScore(a)).slice(0, 24);
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
            {!ready ? (
              <View style={{ paddingVertical: 28, alignItems: 'center' }}>
                <ActivityIndicator color={C.accentLight} />
                <Text style={{ color: C.dim, fontSize: 12, marginTop: 10 }}>Syncing market data…</Text>
              </View>
            ) : marketRows.length ? (
              marketRows.map((row) => <MarketTableRow key={row.symbol} row={row} C={C} />)
            ) : (
              <Text style={{ color: C.dim, fontSize: 12, textAlign: 'center', paddingVertical: 22, lineHeight: 18 }}>
                Scanning USDT-M pairs — movers rank here by 3m / 5m / 15m change.
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
