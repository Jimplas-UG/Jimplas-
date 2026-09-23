import React, { memo } from 'react';
import { ScrollView } from 'react-native';
import BinanceStatusStrip from '../components/BinanceStatusStrip';
import TickScannerHome from '../components/scanner/TickScannerHome';
import { PilotHeroBalance } from '../components/pilot/PilotUI';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';

function ScannerScreen({ pad, scanner, onOpenProfile, connected: connectedProp, account = null, active = true }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { connected: bridgeConnected, sessionExec, linkHealth, restCoolS } = useBinanceBridge();
  const connected = connectedProp ?? bridgeConnected;

  return (
    <ScrollView
      style={[styles.ghBody, { flex: 1, backgroundColor: C.appBg }]}
      contentContainerStyle={{ paddingHorizontal: pad, paddingBottom: 24 }}
      keyboardShouldPersistTaps="handled"
      scrollEnabled={active}
      removeClippedSubviews>
      <PilotHeroBalance
        balance={account?.balance}
        floating={account?.profit}
        connected={connected}
        onConnect={onOpenProfile}
      />

      <BinanceStatusStrip
        scannerReady={scanner.ready}
        scannerError={scanner.error}
        connected={connected}
        linkHealth={linkHealth}
        restCoolS={restCoolS}
        execReady={sessionExec.canExecute === true || scanner.scannerMeta?.can_execute === true}
        execBlock={sessionExec.block || scanner.scannerMeta?.exec_block}
        lastExecError={scanner.scannerMeta?.last_exec_error}
        onPressConnect={onOpenProfile}
        style={{ marginBottom: 12 }}
      />

      <TickScannerHome
        rows={scanner.rows}
        ready={scanner.ready}
        error={scanner.error}
        scannerMeta={scanner.scannerMeta}
        connected={connected}
        sessionExec={sessionExec}
        active={active}
      />
    </ScrollView>
  );
}

function scannerPropsEqual(prev, next) {
  if (prev.active !== next.active || prev.pad !== next.pad || prev.connected !== next.connected) return false;
  if (prev.account !== next.account || prev.onOpenProfile !== next.onOpenProfile) return false;
  if (!next.active) {
    // Hidden Home tab: ignore row churn while Trade is open.
    return (
      prev.scanner?.ready === next.scanner?.ready &&
      prev.scanner?.error === next.scanner?.error &&
      prev.scanner?.scannerMeta === next.scanner?.scannerMeta
    );
  }
  return (
    prev.scanner?.rows === next.scanner?.rows &&
    prev.scanner?.ready === next.scanner?.ready &&
    prev.scanner?.error === next.scanner?.error &&
    prev.scanner?.scannerMeta === next.scanner?.scannerMeta &&
    prev.scanner?.executionEvents === next.scanner?.executionEvents
  );
}

export default memo(ScannerScreen, scannerPropsEqual);
