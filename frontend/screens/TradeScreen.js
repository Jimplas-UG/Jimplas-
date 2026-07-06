import React from 'react';
import { ScrollView, Text, View } from 'react-native';
import BinanceStatusStrip from '../components/BinanceStatusStrip';
import OpenPositionsPanel from '../components/OpenPositionsPanel';
import { PilotCard, PilotHeroBalance, PilotSectionTitle } from '../components/pilot/PilotUI';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { spacing } from '../theme/designTokens';

export default function TradeScreen({ pad, desk, scanner, onOpenProfile }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { baseUrl, connected, brokerFeed, useBrokerSession, lastBrokerMsg, setLastBrokerMsg, effectiveAutoExecute } =
    desk;
  const account = useBrokerSession ? brokerFeed.account : null;

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
        execEnabled={scanner?.scannerMeta?.exec_enabled !== false}
        autoExecute={effectiveAutoExecute}
        execBlock={scanner?.scannerMeta?.exec_block}
        lastExecError={scanner?.scannerMeta?.last_exec_error}
        onPressConnect={onOpenProfile}
        style={{ marginBottom: spacing.md }}
      />

      {lastBrokerMsg ? (
        <PilotCard style={{ marginBottom: spacing.md, padding: spacing.md }}>
          <Text style={{ color: C.amber, fontSize: 12, fontWeight: '600' }} numberOfLines={3}>
            {lastBrokerMsg}
          </Text>
        </PilotCard>
      ) : null}

      <PilotSectionTitle title="Open positions" />
      <OpenPositionsPanel
        positions={useBrokerSession ? brokerFeed.positions : []}
        brokerDeals={useBrokerSession ? brokerFeed.brokerDeals : []}
        livePrice={brokerFeed.price}
        bid={brokerFeed.bid}
        ask={brokerFeed.ask}
        binanceBaseUrl={baseUrl}
        brokerConnected={connected}
        onRefresh={brokerFeed.refreshBrokerSnapshot}
        onCloseMessage={(msg) => setLastBrokerMsg(msg)}
      />
    </ScrollView>
  );
}
