import React from 'react';
import { ScrollView } from 'react-native';
import BinanceStatusStrip from '../components/BinanceStatusStrip';
import TickScannerHome from '../components/scanner/TickScannerHome';
import { PilotHeroBalance } from '../components/pilot/PilotUI';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';

export default function ScannerScreen({ pad, scanner, onOpenProfile, connected: connectedProp, account = null }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { connected: bridgeConnected, sessionExec } = useBinanceBridge();
  const connected = connectedProp ?? bridgeConnected;

  return (
    <ScrollView
      style={[styles.ghBody, { flex: 1, backgroundColor: C.appBg }]}
      contentContainerStyle={{ paddingHorizontal: pad, paddingBottom: 24 }}
      keyboardShouldPersistTaps="handled">
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
      />
    </ScrollView>
  );
}
