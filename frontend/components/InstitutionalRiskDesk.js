import React, { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { fmtRiskUsd } from '../lib/riskDeskModel';
import { PARTITION_PRESETS_USD, LEVERAGE_PRESETS, MARGIN_MODE_PRESETS } from '../lib/riskDeskDefaults';
import OpenPositionsPanel from './OpenPositionsPanel';
import BinanceStatusStrip from './BinanceStatusStrip';

function RiskCard({ title, badge, children, C }) {
  return (
    <View style={[st.card, { borderColor: C.border, backgroundColor: C.panel }]}>
      <View style={st.cardInner}>
        <View style={[st.cardHead, { borderBottomColor: C.border }]}>
          <Text style={[st.cardTitle, { color: C.text }]}>{title}</Text>
          {badge ? <Text style={[st.cardBadge, { color: C.accentLight }]}>{badge}</Text> : null}
        </View>
        {children}
      </View>
    </View>
  );
}

function MetricTile({ label, value, sub, color, C }) {
  return (
    <View style={[st.metricTile, { borderColor: C.border }]}>
      <Text style={[st.metricLab, { color: C.dim }]}>{label}</Text>
      <Text style={[st.metricVal, { color: color ?? C.text }]}>{value}</Text>
      {sub ? <Text style={[st.metricSub, { color: C.dim }]}>{sub}</Text> : null}
    </View>
  );
}

function PresetChipRow({ label, hint, options, value, onChange, format, C }) {
  return (
    <View style={st.presetBlock}>
      <Text style={[st.sliderLab, { color: C.dim }]}>{label}</Text>
      {hint ? <Text style={[st.presetHint, { color: C.dim }]}>{hint}</Text> : null}
      <View style={st.chipRow}>
        {options.map((opt) => {
          const on = value === opt;
          return (
            <Pressable
              key={String(opt)}
              onPress={() => onChange(opt)}
              style={({ pressed }) => [
                st.chip,
                { borderColor: on ? C.accent : C.border, backgroundColor: on ? C.accentDim : C.panel2 },
                pressed && { opacity: 0.85 },
              ]}>
              <Text style={[st.chipTxt, { color: on ? C.accentLight : C.text }]}>{format(opt)}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default function InstitutionalRiskDesk({
  pad = 16,
  config,
  metrics,
  hydrated,
  onConfigChange,
  onMarginModeChange,
  onEmergencyStop,
  onResumeTrading,
  brokerConnected,
  brokerAccount,
  brokerPositions,
  brokerDeals,
  binanceBaseUrl,
  livePrice,
  bid,
  ask,
  onRefreshBroker,
  onBrokerCloseMsg,
  feedReady,
  feedError,
  onOpenProfile,
}) {
  const { colors: C } = useBilshenzTheme();
  const [confirmStop, setConfirmStop] = useState(false);
  const [marginBusy, setMarginBusy] = useState(false);

  if (!hydrated) {
    return (
      <View style={[st.loading, { paddingHorizontal: pad }]}>
        <ActivityIndicator color={C.accentLight} />
        <Text style={{ color: C.dim, marginTop: 12, fontSize: 12 }}>Loading risk desk…</Text>
      </View>
    );
  }

  const levCapOk = metrics.activeLeverage <= config.defaultLeverage;
  const activeMargin = (brokerAccount?.margin_type ?? config.marginMode).toUpperCase();
  const marginOk = !brokerConnected || activeMargin === config.marginMode;

  const applyMarginMode = async (mode) => {
    if (marginBusy || mode === config.marginMode) return;
    setMarginBusy(true);
    try {
      if (onMarginModeChange) await onMarginModeChange(mode);
      else onConfigChange({ marginMode: mode });
    } finally {
      setMarginBusy(false);
    }
  };

  return (
    <ScrollView
      style={{ flex: 1 }}
      contentContainerStyle={[st.scroll, { paddingHorizontal: pad, paddingBottom: 32 }]}
      showsVerticalScrollIndicator={false}>
      <View style={st.hero}>
        <Text style={[st.heroTitle, { color: C.text }]}>Risk settings</Text>
        <Text style={[st.heroSub, { color: C.dim }]}>
          Tick scanner capital split — short 50%, long legs 40% each (USDT-M Futures)
        </Text>
      </View>

      <View style={{ marginBottom: 10 }}>
        <BinanceStatusStrip
          feedReady={feedReady}
          feedError={feedError}
          connected={brokerConnected}
          onPressConnect={onOpenProfile}
        />
      </View>

      {config.emergencyStop ? (
        <View style={[st.alertBanner, { borderColor: C.red, backgroundColor: 'rgba(255,61,87,0.12)' }]}>
          <Text style={[st.alertTitle, { color: C.red }]}>EMERGENCY STOP ACTIVE</Text>
          <Text style={[st.alertSub, { color: C.dim }]}>All new trades blocked until resumed.</Text>
          <Pressable
            onPress={onResumeTrading}
            style={[st.resumeBtn, { borderColor: C.accent }]}>
            <Text style={{ color: C.accentLight, fontWeight: '800', fontSize: 11 }}>RESUME TRADING</Text>
          </Pressable>
        </View>
      ) : null}

      {/* 1. Capital Allocation */}
      <RiskCard title="CAPITAL ALLOCATION" badge={`$${config.partitionUsd} AT RISK`} C={C}>
        <View style={st.metricGrid}>
          <MetricTile label="Total Balance" value={fmtRiskUsd(metrics.totalBalance)} C={C} />
          <MetricTile
            label="Your partition"
            value={fmtRiskUsd(metrics.partitionUsd)}
            sub="Ready to lose"
            color={C.amber}
            C={C}
          />
          <MetricTile label="Active partition" value={fmtRiskUsd(metrics.tradingPartition)} sub="Used for sizing" C={C} />
          <MetricTile label="Protected capital" value={fmtRiskUsd(metrics.protectedCapital)} sub="Not traded" color={C.teal} C={C} />
          <MetricTile label="Available to trade" value={fmtRiskUsd(metrics.availableTradingCapital)} color={C.green} C={C} />
        </View>
        <View style={st.metricGrid}>
          <MetricTile
            label="Short"
            value={`${config.shortPartitionPct}%`}
            sub={fmtRiskUsd(metrics.shortLegUsd)}
            color={C.accentLight}
            C={C}
          />
          <MetricTile
            label="Long 1"
            value={`${config.long1PartitionPct}%`}
            sub={fmtRiskUsd(metrics.long1LegUsd)}
            color={C.teal}
            C={C}
          />
          <MetricTile
            label="Long 2"
            value={`${config.long2PartitionPct}%`}
            sub={fmtRiskUsd(metrics.long2LegUsd)}
            color={C.amber}
            C={C}
          />
        </View>
        <PresetChipRow
          label="Subscribe partition"
          hint="Pick what you are ready to lose — only this slice is used for new trades."
          options={PARTITION_PRESETS_USD}
          value={config.partitionUsd}
          onChange={(v) => onConfigChange({ partitionUsd: v })}
          format={(v) => `$${v}`}
          C={C}
        />
        <Text style={[st.ruleNote, { color: C.dim }]}>
          Balance above your partition stays protected and is never allocated to new trades.
        </Text>
      </RiskCard>

      {/* Leverage + margin (Binance Futures) */}
      <RiskCard title="LEVERAGE CONTROLS" badge={`${config.defaultLeverage}x · ${config.marginMode}`} C={C}>
        <View style={st.metricGrid}>
          <MetricTile label="Selected leverage" value={`${config.defaultLeverage}x`} color={C.accentLight} C={C} />
          <MetricTile label="Active on Binance" value={`${metrics.activeLeverage}x`} color={levCapOk ? C.green : C.red} C={C} />
          <MetricTile
            label="Margin on Binance"
            value={brokerConnected ? activeMargin : config.marginMode}
            color={marginOk ? C.green : C.red}
            C={C}
          />
        </View>
        <PresetChipRow
          label="Leverage"
          hint="Toggle the leverage you want — trades above this are blocked."
          options={LEVERAGE_PRESETS}
          value={config.defaultLeverage}
          onChange={(v) => onConfigChange({ defaultLeverage: v, maxAllowedLeverage: v })}
          format={(v) => `${v}x`}
          C={C}
        />
        <PresetChipRow
          label="Margin mode"
          hint={
            brokerConnected
              ? 'Applies to Binance Futures for this symbol. Close open positions first if Binance rejects the switch.'
              : 'Saved for when you connect — Isolated limits risk per position; Cross shares wallet margin.'
          }
          options={MARGIN_MODE_PRESETS}
          value={config.marginMode}
          onChange={applyMarginMode}
          format={(v) => (v === 'ISOLATED' ? 'Isolated' : 'Cross')}
          C={C}
        />
        {marginBusy ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8 }}>
            <ActivityIndicator size="small" color={C.accent} />
            <Text style={{ color: C.dim, fontSize: 10 }}>Updating margin mode on Binance…</Text>
          </View>
        ) : null}
        {!marginOk && brokerConnected ? (
          <Text style={[st.ruleNote, { color: C.red }]}>
            Binance reports {activeMargin} but you selected {config.marginMode}. Tap again or close positions to switch.
          </Text>
        ) : null}
      </RiskCard>

      {/* Live account + positions */}
      <RiskCard title="BINANCE ACCOUNT" badge={brokerConnected ? 'LIVE' : 'OFFLINE'} C={C}>
        <View style={st.metricGrid}>
          <MetricTile label="Used margin" value={fmtRiskUsd(metrics.usedMargin)} C={C} />
          <MetricTile label="Free margin" value={fmtRiskUsd(metrics.freeMargin)} C={C} />
          <MetricTile label="Open exposure" value={fmtRiskUsd(metrics.openExposure)} sub={`${metrics.exposurePct.toFixed(1)}%`} C={C} />
          <MetricTile label="Floating P&L" value={fmtRiskUsd(metrics.dailyPnl)} color={metrics.dailyPnl >= 0 ? C.green : C.red} C={C} />
          <MetricTile label="Drawdown" value={`${metrics.drawdownPct.toFixed(1)}%`} color={metrics.drawdownPct >= config.maxDrawdownPct ? C.red : C.amber} C={C} />
        </View>
        {brokerConnected ? (
          <OpenPositionsPanel
            positions={brokerPositions ?? []}
            brokerDeals={brokerDeals ?? []}
        livePrice={livePrice}
        bid={bid}
        ask={ask}
        quoteSymbol={brokerPositions?.length === 1 ? brokerPositions[0]?.symbol : null}
        binanceBaseUrl={binanceBaseUrl}
            brokerConnected={brokerConnected}
            onRefresh={onRefreshBroker}
            onCloseMessage={onBrokerCloseMsg}
          />
        ) : null}
      </RiskCard>

      {/* Safety */}
      <RiskCard title="SAFETY CONTROLS" badge="GUARD" C={C}>
        <Pressable
          onPress={() => {
            if (!confirmStop) {
              setConfirmStop(true);
              return;
            }
            onEmergencyStop();
            setConfirmStop(false);
          }}
          style={[st.emergencyBtn, { borderColor: C.red, backgroundColor: confirmStop ? C.red : 'rgba(255,61,87,0.15)' }]}>
          <Text style={[st.emergencyTxt, { color: confirmStop ? '#fff' : C.red }]}>
            {confirmStop ? 'TAP AGAIN TO CONFIRM STOP' : 'EMERGENCY STOP TRADING'}
          </Text>
        </Pressable>
        <ToggleRow label="Pause new trades" value={config.pauseNewTrades} onChange={(v) => onConfigChange({ pauseNewTrades: v })} C={C} />
        {config.apiErrorStreak > 0 ? (
          <Text style={[st.ruleNote, { color: C.amber }]}>API error streak: {config.apiErrorStreak}</Text>
        ) : null}
      </RiskCard>
    </ScrollView>
  );
}

function ToggleRow({ label, value, onChange, C }) {
  return (
    <View style={st.toggleRow}>
      <Text style={[st.toggleLab, { color: C.text }]}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: C.border, true: 'rgba(124,108,240,0.45)' }}
        thumbColor={value ? C.accentLight : C.dim2}
      />
    </View>
  );
}

const st = StyleSheet.create({
  scroll: { paddingTop: 8, gap: 12 },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: 48 },
  hero: { marginBottom: 4 },
  heroTitle: { fontSize: 14, fontWeight: '800', letterSpacing: 1 },
  heroSub: { fontSize: 10, lineHeight: 15, marginTop: 4 },
  card: { borderRadius: 16, borderWidth: 1, overflow: 'hidden' },
  cardInner: { padding: 12 },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingBottom: 10, marginBottom: 8, borderBottomWidth: 1 },
  cardTitle: { fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  cardBadge: { fontSize: 9, fontWeight: '800', letterSpacing: 0.4 },
  metricGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 8 },
  metricTile: { width: '47%', flexGrow: 1, borderWidth: 1, borderRadius: 10, padding: 10, minWidth: 140 },
  metricLab: { fontSize: 9, fontWeight: '700', letterSpacing: 0.3 },
  metricVal: { fontSize: 16, fontWeight: '800', marginTop: 4 },
  metricSub: { fontSize: 9, marginTop: 2 },
  sliderBlock: { marginTop: 8 },
  sliderHdr: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sliderLab: { fontSize: 10, fontWeight: '600' },
  sliderVal: { fontSize: 11, fontWeight: '800' },
  row2: { flexDirection: 'row', gap: 12 },
  stepper: { flex: 1, marginTop: 8 },
  stepRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 6 },
  stepBtn: { width: 36, height: 36, borderRadius: 8, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  stepVal: { fontSize: 18, fontWeight: '800', minWidth: 28, textAlign: 'center' },
  ruleNote: { fontSize: 9, lineHeight: 14, marginTop: 10 },
  alertBanner: { borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 8 },
  alertTitle: { fontSize: 12, fontWeight: '800', letterSpacing: 0.5 },
  alertSub: { fontSize: 10, marginTop: 4 },
  resumeBtn: { marginTop: 10, paddingVertical: 10, borderRadius: 8, borderWidth: 1, alignItems: 'center' },
  emergencyBtn: { paddingVertical: 14, borderRadius: 10, borderWidth: 1, alignItems: 'center', marginBottom: 12 },
  emergencyTxt: { fontSize: 11, fontWeight: '800', letterSpacing: 0.5 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, minHeight: 44 },
  toggleLab: { flex: 1, fontSize: 11, fontWeight: '600', paddingRight: 12 },
  presetBlock: { marginTop: 10 },
  presetHint: { fontSize: 9, lineHeight: 14, marginTop: 4, marginBottom: 8 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    minWidth: 72,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipTxt: { fontSize: 13, fontWeight: '800', letterSpacing: 0.3 },
});
