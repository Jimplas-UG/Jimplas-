import React, { memo } from 'react';
import { View } from 'react-native';
import InstitutionalRiskDesk from '../components/InstitutionalRiskDesk';
import { useBilshenzTheme } from '../contexts/ThemeContext';

function RiskScreen({ pad, desk, onOpenProfile, active = true }) {
  const { colors: C, styles } = useBilshenzTheme();
  const {
    baseUrl,
    connected,
    brokerFeed,
    riskDesk,
    useBrokerSession,
    handleMarginModeChange,
    triggerEmergencyStop,
    resumeTrading,
  } = desk;

  return (
    <View
      style={[styles.mobileTabBody, styles.ghBody, { flex: 1, paddingHorizontal: 0, backgroundColor: C.appBg }]}
      pointerEvents={active ? 'auto' : 'none'}>
      <InstitutionalRiskDesk
        pad={pad}
        config={riskDesk.config}
        metrics={riskDesk.metrics}
        hydrated={riskDesk.hydrated}
        onConfigChange={riskDesk.updateConfig}
        onMarginModeChange={handleMarginModeChange}
        onEmergencyStop={triggerEmergencyStop}
        onResumeTrading={resumeTrading}
        brokerConnected={connected || (brokerFeed.positions?.length > 0)}
        brokerAccount={brokerFeed.account}
        brokerPositions={brokerFeed.positions || []}
        brokerPositionsStale={!!brokerFeed.positionsStale}
        brokerPositionsCoolS={brokerFeed.positionsCoolS || 0}
        brokerDeals={brokerFeed.brokerDeals || []}
        binanceBaseUrl={baseUrl}
        livePrice={brokerFeed.price}
        bid={brokerFeed.bid}
        ask={brokerFeed.ask}
        onRefreshBroker={brokerFeed.refreshBrokerSnapshot}
        onRefreshAfterClose={brokerFeed.refreshAfterClose}
        onOptimisticClose={brokerFeed.applyOptimisticClose}
        onBrokerCloseMsg={(msg) => desk.setLastBrokerMsg(`Close: ${msg}`)}
        feedReady={brokerFeed.feedReady}
        feedError={brokerFeed.feedError}
        onOpenProfile={onOpenProfile}
      />
    </View>
  );
}

export default memo(RiskScreen);
