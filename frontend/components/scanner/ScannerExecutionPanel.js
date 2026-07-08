import React, { useMemo } from 'react';
import { Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { PilotCard, PilotSectionTitle } from '../pilot/PilotUI';
import { formatPairLabel } from '../../lib/futuresSymbol';
import {
  GAIN_THRESHOLD_PCT,
  RETRACE_ENTRY_PCT,
  executionStatusHint,
  pickExecutionCandidates,
} from '../../lib/scannerExecution';
import { spacing, radius } from '../../theme/designTokens';

function fmtPct(n, decimals = 2) {
  const v = Number(n);
  if (!Number.isFinite(v)) return '—';
  const prefix = v > 0 ? '+' : '';
  return `${prefix}${v.toFixed(decimals)}%`;
}

function fmtPx(n) {
  const x = Number(n);
  if (!Number.isFinite(x) || x <= 0) return '—';
  if (x >= 1000) return x.toFixed(2);
  if (x >= 1) return x.toFixed(4);
  return x.toFixed(6);
}

function statusColor(status, C) {
  if (status === 'Pending') return C.accentLight;
  if (status === 'Watching') return C.amber;
  return C.dim;
}

function CandidateRow({ row, C }) {
  const retrace = Math.max(0, Number(row.retracePct ?? 0));
  const progress = Math.min(1, retrace / RETRACE_ENTRY_PCT);
  const hint = executionStatusHint(row);

  return (
    <View
      style={{
        borderWidth: 1,
        borderColor: row.status === 'Pending' ? 'rgba(124,108,240,0.45)' : C.border,
        backgroundColor: row.status === 'Pending' ? 'rgba(124,108,240,0.08)' : C.panel2,
        borderRadius: radius.lg,
        padding: spacing.md,
        marginBottom: spacing.sm,
      }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={{ color: C.text, fontSize: 15, fontWeight: '800' }}>{row.coin || row.symbol}</Text>
        <Text style={{ color: statusColor(row.status, C), fontSize: 11, fontWeight: '800', letterSpacing: 0.5 }}>
          {row.status?.toUpperCase()}
        </Text>
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 8 }}>
        <Meta label="Gain" value={fmtPct(row.pctGain)} color={C.green} C={C} />
        <Meta label="Window" value={row.timeframe || '—'} C={C} />
        <Meta label="Retrace" value={fmtPct(retrace)} color={retrace >= RETRACE_ENTRY_PCT ? C.accentLight : C.amber} C={C} />
        <Meta label="Price" value={fmtPx(row.price)} C={C} />
      </View>

      <View style={{ marginTop: 10 }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
          <Text style={{ color: C.dim, fontSize: 9, fontWeight: '700' }}>RETRACE TO ENTRY</Text>
          <Text style={{ color: C.dim, fontSize: 9, fontWeight: '700' }}>
            {retrace.toFixed(2)}% / {RETRACE_ENTRY_PCT}%
          </Text>
        </View>
        <View style={{ height: 6, borderRadius: radius.pill, backgroundColor: C.border, overflow: 'hidden' }}>
          <View
            style={{
              width: `${Math.round(progress * 100)}%`,
              height: '100%',
              borderRadius: radius.pill,
              backgroundColor: row.status === 'Pending' ? C.accentLight : C.amber,
            }}
          />
        </View>
      </View>

      {hint ? (
        <Text style={{ color: C.dim, fontSize: 10, lineHeight: 15, marginTop: 8 }}>{hint}</Text>
      ) : null}
    </View>
  );
}

function Meta({ label, value, color, C }) {
  return (
    <View>
      <Text style={{ color: C.dim, fontSize: 9, fontWeight: '700', letterSpacing: 0.4 }}>{label}</Text>
      <Text style={{ color: color ?? C.text, fontSize: 12, fontWeight: '800', marginTop: 2 }}>{value}</Text>
    </View>
  );
}

export default function ScannerExecutionPanel({ rows, scannerMeta, ready }) {
  const { colors: C } = useBilshenzTheme();

  const candidates = useMemo(() => pickExecutionCandidates(rows), [rows]);

  return (
    <PilotCard style={{ marginBottom: spacing.md, padding: spacing.md }}>
      <PilotSectionTitle title="Execution queue" />
      <Text style={{ color: C.dim, fontSize: 11, lineHeight: 16, marginBottom: spacing.sm }}>
        Short when a symbol gains ≥{GAIN_THRESHOLD_PCT}% (1m–15m), then retraces {RETRACE_ENTRY_PCT}% from the peak.
      </Text>

      {!ready ? (
        <Text style={{ color: C.dim, fontSize: 12, textAlign: 'center', paddingVertical: 16 }}>
          Syncing scanner…
        </Text>
      ) : candidates.length ? (
        candidates.map((row) => <CandidateRow key={row.symbol} row={row} C={C} />)
      ) : (
        <View
          style={{
            borderWidth: 1,
            borderColor: C.border,
            borderRadius: radius.lg,
            padding: spacing.md,
            backgroundColor: C.panel2,
          }}>
          <Text style={{ color: C.text, fontSize: 12, fontWeight: '700' }}>No armed entries</Text>
          <Text style={{ color: C.dim, fontSize: 11, lineHeight: 16, marginTop: 6 }}>
            Movers above {GAIN_THRESHOLD_PCT}% appear here as Watching, then Pending after a {RETRACE_ENTRY_PCT}% pullback.
            {scannerMeta?.watchlist
              ? ` Scanner tracking ${scannerMeta.watchlist} active target${scannerMeta.watchlist === 1 ? '' : 's'}.`
              : ''}
          </Text>
        </View>
      )}
    </PilotCard>
  );
}

export function ScannerQuoteStrip({ candidate }) {
  const { colors: C } = useBilshenzTheme();
  if (!candidate?.symbol) return null;
  const label = formatPairLabel(candidate.symbol);
  const price = Number(candidate.price);

  return (
    <View style={{ borderWidth: 1, borderColor: C.border, borderRadius: radius.lg, backgroundColor: C.panel, padding: spacing.md, marginBottom: spacing.md }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={{ color: C.text, fontSize: 11, fontWeight: '800', letterSpacing: 0.5 }}>Scanner quote</Text>
        <Text style={{ color: C.accentLight, fontSize: 10, fontWeight: '800' }}>{label}</Text>
      </View>
      <Text style={{ color: C.text, fontSize: 22, fontWeight: '800', marginTop: 8 }}>{fmtPx(price)}</Text>
      <Text style={{ color: C.dim, fontSize: 10, marginTop: 4 }}>
        {candidate.status} · {fmtPct(candidate.pctGain)} on {candidate.timeframe || 'tick'}
      </Text>
    </View>
  );
}
