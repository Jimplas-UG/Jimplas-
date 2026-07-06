import React from 'react';
import { ScrollView } from 'react-native';
import InstitutionalRiskDesk from '../components/InstitutionalRiskDesk';
import { useBilshenzTheme } from '../contexts/ThemeContext';

export default function RiskScreen({ pad, desk, onOpenProfile }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { baseUrl, connected, brokerFeed, riskDesk, useBrokerSession, handleMarginModeChange, effectiveAutoExecute } =
    desk;

  return (
    <ScrollView
      style={[styles.mobileTabBody, styles.ghBody, { flex: 1, paddingHorizontal: 0, backgroundColor: C.appBg }]}
      contentContainerStyle={{ paddingBottom: 24 }}
      keyboardShouldPersistTaps="handled">
      <InstitutionalRiskDesk
        pad={pad}
        config={riskDesk.config}
        metrics={riskDesk.metrics}
        hydrated={riskDesk.hydrated}
        onConfigChange={riskDesk.updateConfig}
        onMarginModeChange={handleMarginModeChange}
        onEmergencyStop={riskDesk.triggerEmergencyStop}
        onResumeTrading={riskDesk.resumeTrading}
        brokerConnected={connected}
        brokerAccount={useBrokerSession ? brokerFeed.account : null}
        brokerPositions={useBrokerSession ? brokerFeed.positions : []}
        brokerDeals={useBrokerSession ? brokerFeed.brokerDeals : []}
        binanceBaseUrl={baseUrl}
        livePrice={brokerFeed.price}
        bid={brokerFeed.bid}
        ask={brokerFeed.ask}
        onRefreshBroker={brokerFeed.refreshBrokerSnapshot}
        onBrokerCloseMsg={(msg) => desk.setLastBrokerMsg(`Close: ${msg}`)}
        feedReady={brokerFeed.feedReady}
        feedError={brokerFeed.feedError}
        autoExecute={effectiveAutoExecute}
        onOpenProfile={onOpenProfile}
      />
    </ScrollView>
  );
}
