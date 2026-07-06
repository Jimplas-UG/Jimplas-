import React, { useEffect, useState } from 'react';
import { ScrollView } from 'react-native';
import BinanceStatusStrip from '../components/BinanceStatusStrip';
import TickScannerHome from '../components/scanner/TickScannerHome';
import { PilotHeroBalance } from '../components/pilot/PilotUI';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { fetchBinanceSession } from '../broker/binanceFuturesApi';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';

export default function ScannerScreen({ pad, scanner, onOpenProfile, connected: connectedProp, autoExecute }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { baseUrl, connected: bridgeConnected } = useBinanceBridge();
  const connected = connectedProp ?? bridgeConnected;
  const [account, setAccount] = useState(null);

  useEffect(() => {
    if (!connected || !baseUrl) {
      setAccount(null);
      return undefined;
    }
    let cancelled = false;
    void (async () => {
      const session = await fetchBinanceSession(baseUrl, 8000, 0);
      if (!cancelled && session.ok) setAccount(session.account);
    })();
    return () => {
      cancelled = true;
    };
  }, [connected, baseUrl]);

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
        execEnabled={autoExecute ?? scanner.scannerMeta?.exec_enabled !== false}
        autoExecute={autoExecute}
        execBlock={scanner.scannerMeta?.exec_block}
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
        autoExecute={autoExecute}
      />
    </ScrollView>
  );
}
