import React, { useMemo } from 'react';
import { ScrollView, Text, View } from 'react-native';
import BinanceStatusStrip from '../components/BinanceStatusStrip';
import DiagnosticsPanel from '../components/DiagnosticsPanel';
import OpenPositionsPanel from '../components/OpenPositionsPanel';
import TradeResultsCalendar from '../components/TradeResultsCalendar';
import ScannerExecutionPanel, { ScannerQuoteStrip } from '../components/scanner/ScannerExecutionPanel';
import { PilotCard, PilotHeroBalance, PilotSectionTitle } from '../components/pilot/PilotUI';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { useDiagnostics } from '../hooks/useDiagnostics';
import { pickPrimaryExecutionCandidate } from '../lib/scannerExecution';
import { spacing } from '../theme/designTokens';

export default function TradeScreen({ pad, desk, scanner, onOpenProfile, active = true }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { sessionExec } = useBinanceBridge();
  const { baseUrl, connected, brokerFeed, useBrokerSession, lastBrokerMsg, setLastBrokerMsg } = desk;
  const { diagnostics, loading: diagLoading, refresh: refreshDiag } = useDiagnostics(baseUrl, {
    enabled: active && connected,
    intervalMs: 30000,
  });

  const account = useBrokerSession ? brokerFeed.account : null;

  const executionLead = useMemo(
    () => pickPrimaryExecutionCandidate(scanner?.rows, scanner?.scannerMeta),
    [scanner?.rows, scanner?.scannerMeta],
  );

  const positionSymbol =
    useBrokerSession && brokerFeed.positions?.length === 1 ? brokerFeed.positions[0]?.symbol : null;

  return (
    <ScrollView
      style={[styles.mobileTabBody, { flex: 1, backgroundColor: C.appBg }]}
      contentContainerStyle={{ paddingHorizontal: pad, paddingBottom: 24 }}
      keyboardShouldPersistTaps="handled">
      <PilotHeroBalance
        balance={account?.balance}
        floating={account?.profit}
        connected={connected}
        onConnect={onOpenProfile}
      />

      <BinanceStatusStrip
        scannerReady={scanner?.ready}
        scannerError={scanner?.error}
        feedReady={brokerFeed.feedReady}
        feedError={brokerFeed.feedError}
        connected={connected}
        execReady={sessionExec.canExecute === true || scanner?.scannerMeta?.can_execute === true}
        execBlock={sessionExec.block || scanner?.scannerMeta?.exec_block}
        lastExecError={scanner?.scannerMeta?.last_exec_error}
        onPressConnect={onOpenProfile}
        style={{ marginBottom: spacing.md }}
      />

      <DiagnosticsPanel
        diagnostics={diagnostics}
        loading={diagLoading}
        onRefresh={refreshDiag}
        style={{ marginBottom: spacing.md }}
      />

      {lastBrokerMsg ? (
        <PilotCard style={{ marginBottom: spacing.md, padding: spacing.md }}>
          <Text style={{ color: C.amber, fontSize: 12, fontWeight: '600' }} numberOfLines={3}>
            {lastBrokerMsg}
          </Text>
        </PilotCard>
      ) : null}

      <ScannerExecutionPanel
        rows={scanner?.rows}
        scannerMeta={scanner?.scannerMeta}
        ready={scanner?.ready}
        executionEvents={scanner?.executionEvents}
      />

      {executionLead ? <ScannerQuoteStrip candidate={executionLead} /> : null}

      <PilotSectionTitle title="Open positions" />
      <OpenPositionsPanel
        positions={useBrokerSession ? brokerFeed.positions : []}
        brokerDeals={useBrokerSession ? brokerFeed.brokerDeals : []}
        livePrice={executionLead?.price ?? brokerFeed.price}
        bid={brokerFeed.bid}
        ask={brokerFeed.ask}
        quoteSymbol={positionSymbol}
        hideQuote
        binanceBaseUrl={baseUrl}
        brokerConnected={connected}
        onRefresh={brokerFeed.refreshBrokerSnapshot}
        onRefreshAfterClose={brokerFeed.refreshAfterClose}
        onCloseMessage={(msg) => setLastBrokerMsg(msg)}
      />

      <PilotSectionTitle title="Performance" />
      <TradeResultsCalendar
        binanceBaseUrl={baseUrl}
        brokerConnected={connected && useBrokerSession}
        brokerDeals={useBrokerSession ? brokerFeed.brokerDeals : []}
        active={active}
      />
    </ScrollView>
  );
}
