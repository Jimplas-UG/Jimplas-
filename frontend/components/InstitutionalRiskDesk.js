import React, { useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import Slider from '@react-native-community/slider';
import { BlurView } from 'expo-blur';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { fmtRiskUsd } from '../lib/riskDeskModel';
import { PARTITION_PRESETS_USD, LEVERAGE_PRESETS, MARGIN_MODE_PRESETS } from '../lib/riskDeskDefaults';
import OpenPositionsPanel from './OpenPositionsPanel';
import BinanceStatusStrip from './BinanceStatusStrip';

function RiskCard({ title, badge, children, C }) {
  return (
    <View style={[st.card, { borderColor: C.border }]}>
      {Platform.OS === 'ios' ? (
        <BlurView intensity={18} tint="dark" style={[StyleSheet.absoluteFillObject, { borderRadius: 14 }]} />
      ) : (
        <View style={[StyleSheet.absoluteFillObject, { backgroundColor: 'rgba(8,7,4,0.92)', borderRadius: 14 }]} />
      )}
      <View style={st.cardInner}>
        <View style={[st.cardHead, { borderBottomColor: C.border }]}>
          <Text style={[st.cardTitle, { color: C.goldL }]}>{title}</Text>
          {badge ? <Text style={[st.cardBadge, { color: C.gold }]}>{badge}</Text> : null}
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

function PctSlider({ label, value, onChange, min, max, step, suffix, C }) {
  return (
    <View style={st.sliderBlock}>
      <View style={st.sliderHdr}>
        <Text style={[st.sliderLab, { color: C.dim }]}>{label}</Text>
        <Text style={[st.sliderVal, { color: C.goldL }]}>
          {value.toFixed(step < 1 ? 1 : 0)}
          {suffix}
        </Text>
      </View>
      <Slider
        minimumValue={min}
        maximumValue={max}
        step={step}
        value={value}
        onValueChange={onChange}
        minimumTrackTintColor={C.gold}
        maximumTrackTintColor={C.border}
        thumbTintColor={C.goldL}
      />
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
                { borderColor: on ? C.gold : C.border, backgroundColor: on ? 'rgba(212,180,90,0.18)' : 'rgba(0,0,0,0.2)' },
                pressed && { opacity: 0.85 },
              ]}>
              <Text style={[st.chipTxt, { color: on ? C.goldL : C.text }]}>{format(opt)}</Text>
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
  autoExecute,
  onOpenProfile,
}) {
  const { colors: C } = useBilshenzTheme();
  const [confirmStop, setConfirmStop] = useState(false);
  const [marginBusy, setMarginBusy] = useState(false);

  if (!hydrated) {
    return (
      <View style={[st.loading, { paddingHorizontal: pad }]}>
        <ActivityIndicator color={C.gold} />
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
        <Text style={[st.heroTitle, { color: C.goldL }]}>INSTITUTIONAL RISK DESK</Text>
        <Text style={[st.heroSub, { color: C.dim }]}>
          Capital allocation & safety controls — independent from strategy signals
        </Text>
      </View>

      <View style={{ marginBottom: 10 }}>
        <BinanceStatusStrip
          feedReady={feedReady}
          feedError={feedError}
          connected={brokerConnected}
          autoExecute={autoExecute}
          onPressConnect={onOpenProfile}
        />
      </View>

      {config.emergencyStop ? (
        <View style={[st.alertBanner, { borderColor: C.red, backgroundColor: 'rgba(255,61,87,0.12)' }]}>
          <Text style={[st.alertTitle, { color: C.red }]}>EMERGENCY STOP ACTIVE</Text>
          <Text style={[st.alertSub, { color: C.dim }]}>All new trades blocked until resumed.</Text>
          <Pressable
            onPress={onResumeTrading}
            style={[st.resumeBtn, { borderColor: C.gold }]}>
            <Text style={{ color: C.goldL, fontWeight: '800', fontSize: 11 }}>RESUME TRADING</Text>
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
          Balance above your partition stays protected and is never used for position sizing.
        </Text>
      </RiskCard>

      {/* 2. Risk Controls */}
      <RiskCard title="RISK CONTROLS" badge="LIMITS" C={C}>
        <PctSlider label="Risk per trade" value={config.riskPerTradePct} onChange={(v) => onConfigChange({ riskPerTradePct: v })} min={0.1} max={5} step={0.1} suffix="%" C={C} />
        <PctSlider label="Max daily loss" value={config.maxDailyLossPct} onChange={(v) => onConfigChange({ maxDailyLossPct: v })} min={0.5} max={25} step={0.5} suffix="%" C={C} />
        <PctSlider label="Max weekly loss" value={config.maxWeeklyLossPct} onChange={(v) => onConfigChange({ maxWeeklyLossPct: v })} min={1} max={40} step={0.5} suffix="%" C={C} />
        <PctSlider label="Max drawdown" value={config.maxDrawdownPct} onChange={(v) => onConfigChange({ maxDrawdownPct: v })} min={1} max={50} step={0.5} suffix="%" C={C} />
        <View style={st.row2}>
          <View style={st.stepper}>
            <Text style={[st.sliderLab, { color: C.dim }]}>Max open positions</Text>
            <View style={st.stepRow}>
              <Pressable onPress={() => onConfigChange({ maxOpenPositions: Math.max(1, config.maxOpenPositions - 1) })} style={[st.stepBtn, { borderColor: C.border }]}>
                <Text style={{ color: C.text }}>−</Text>
              </Pressable>
              <Text style={[st.stepVal, { color: C.goldL }]}>{config.maxOpenPositions}</Text>
              <Pressable onPress={() => onConfigChange({ maxOpenPositions: Math.min(20, config.maxOpenPositions + 1) })} style={[st.stepBtn, { borderColor: C.border }]}>
                <Text style={{ color: C.text }}>+</Text>
              </Pressable>
            </View>
          </View>
        </View>
        <PctSlider label="Max exposure / asset" value={config.maxExposurePerAssetPct} onChange={(v) => onConfigChange({ maxExposurePerAssetPct: v })} min={5} max={100} step={1} suffix="%" C={C} />
        <PctSlider label="Max portfolio exposure" value={config.maxPortfolioExposurePct} onChange={(v) => onConfigChange({ maxPortfolioExposurePct: v })} min={10} max={100} step={1} suffix="%" C={C} />
      </RiskCard>

      {/* 3. Leverage Controls */}
      <RiskCard title="LEVERAGE CONTROLS" badge={`${config.defaultLeverage}x · ${config.marginMode}`} C={C}>
        <View style={st.metricGrid}>
          <MetricTile label="Selected leverage" value={`${config.defaultLeverage}x`} color={C.goldL} C={C} />
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
            <ActivityIndicator size="small" color={C.gold} />
            <Text style={{ color: C.dim, fontSize: 10 }}>Updating margin mode on Binance…</Text>
          </View>
        ) : null}
        {!marginOk && brokerConnected ? (
          <Text style={[st.ruleNote, { color: C.red }]}>
            Binance reports {activeMargin} but you selected {config.marginMode}. Tap again or close positions to switch.
          </Text>
        ) : null}
      </RiskCard>

      {/* 4. Live Risk Dashboard */}
      <RiskCard title="LIVE RISK DASHBOARD" badge={brokerConnected ? 'LIVE' : 'SIM'} C={C}>
        <View style={st.metricGrid}>
          <MetricTile label="Used margin" value={fmtRiskUsd(metrics.usedMargin)} C={C} />
          <MetricTile label="Free margin" value={fmtRiskUsd(metrics.freeMargin)} C={C} />
          <MetricTile label="Open exposure" value={fmtRiskUsd(metrics.openExposure)} sub={`${metrics.exposurePct.toFixed(1)}%`} C={C} />
          <MetricTile label="Daily P&L" value={fmtRiskUsd(metrics.dailyPnl)} color={metrics.dailyPnl >= 0 ? C.green : C.red} C={C} />
          <MetricTile label="Weekly P&L" value={fmtRiskUsd(metrics.weeklyPnl)} color={metrics.weeklyPnl >= 0 ? C.green : C.red} C={C} />
          <MetricTile label="Drawdown" value={`${metrics.drawdownPct.toFixed(1)}%`} color={metrics.drawdownPct >= config.maxDrawdownPct ? C.red : C.amber} C={C} />
          <MetricTile label="Risk utilization" value={`${metrics.riskUtilizationPct.toFixed(0)}%`} C={C} />
          <MetricTile
            label="Liq. buffer"
            value={metrics.liquidationBuffer != null ? `${metrics.liquidationBuffer.toFixed(1)}%` : '—'}
            color={metrics.liquidationBuffer != null && metrics.liquidationBuffer < 5 ? C.red : C.green}
            C={C}
          />
        </View>
        {brokerConnected ? (
          <OpenPositionsPanel
            positions={brokerPositions ?? []}
            brokerDeals={brokerDeals ?? []}
            livePrice={livePrice}
            bid={bid}
            ask={ask}
            binanceBaseUrl={binanceBaseUrl}
            brokerConnected={brokerConnected}
            onRefresh={onRefreshBroker}
            onCloseMessage={onBrokerCloseMsg}
          />
        ) : null}
      </RiskCard>

      {/* 5. Safety Controls */}
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
        <ToggleRow label="Auto-stop on daily loss limit" value={config.autoStopDailyLoss} onChange={(v) => onConfigChange({ autoStopDailyLoss: v })} C={C} />
        <ToggleRow label="Auto-stop on drawdown limit" value={config.autoStopDrawdown} onChange={(v) => onConfigChange({ autoStopDrawdown: v })} C={C} />
        <ToggleRow label="Auto-stop on API errors (3+)" value={config.autoStopApiErrors} onChange={(v) => onConfigChange({ autoStopApiErrors: v })} C={C} />
        {config.apiErrorStreak > 0 ? (
          <Text style={[st.ruleNote, { color: C.amber }]}>API error streak: {config.apiErrorStreak}</Text>
        ) : null}
      </RiskCard>

      {/* 6. Analytics */}
      <RiskCard title="ANALYTICS" badge={`${metrics.closedTrades} closed`} C={C}>
        <View style={st.metricGrid}>
          <MetricTile label="Win rate" value={metrics.winRatePct != null ? `${metrics.winRatePct.toFixed(1)}%` : '—'} C={C} />
          <MetricTile label="Avg R:R" value={metrics.avgRiskReward != null ? `1 : ${metrics.avgRiskReward.toFixed(2)}` : '—'} C={C} />
          <MetricTile label="Largest win" value={fmtRiskUsd(metrics.largestWin)} color={C.green} C={C} />
          <MetricTile label="Largest loss" value={fmtRiskUsd(metrics.largestLoss)} color={C.red} C={C} />
          <MetricTile label="Current drawdown" value={`${metrics.drawdownPct.toFixed(1)}%`} C={C} />
          <MetricTile label="Peak equity" value={fmtRiskUsd(metrics.peakEquity)} C={C} />
        </View>
      </RiskCard>

      {/* 7. Validation Rules */}
      <View style={[st.rulesBox, { borderColor: C.border }]}>
        <Text style={[st.rulesTitle, { color: C.teal }]}>VALIDATION RULES</Text>
        <Text style={[st.ruleLine, { color: C.dim }]}>• Protected capital is never used for trading.</Text>
        <Text style={[st.ruleLine, { color: C.dim }]}>• Trades exceeding limits are rejected at execution only.</Text>
        <Text style={[st.ruleLine, { color: C.dim }]}>• This desk affects sizing & capital — not signals, TP, or SL logic.</Text>
      </View>
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
        trackColor={{ false: C.border, true: 'rgba(212,180,90,0.45)' }}
        thumbColor={value ? C.goldL : C.dim2}
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
  card: { borderRadius: 14, borderWidth: 1, overflow: 'hidden' },
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
  rulesBox: { borderWidth: 1, borderRadius: 12, padding: 14, marginTop: 4 },
  rulesTitle: { fontSize: 10, fontWeight: '800', letterSpacing: 0.5, marginBottom: 8 },
  ruleLine: { fontSize: 10, lineHeight: 16, marginTop: 2 },
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
