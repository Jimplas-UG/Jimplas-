import React, { useCallback, useEffect, useMemo, useState, startTransition } from 'react';
import { View } from 'react-native';
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { hideBootSplash } from './lib/bootSplash';
import { shouldPlayOpening } from './lib/devPreview';
import BootFallback from './components/BootFallback';
import BilshenzHeader from './components/BilshenzHeader';
import EmailVerificationBanner from './components/auth/EmailVerificationBanner';
import AuthGate from './components/auth/AuthGate';
import OnboardingGate, { useOnboardingDone } from './components/OnboardingGate';
import AppBottomNav from './components/AppBottomNav';
import ScannerScreen from './screens/ScannerScreen';
import RiskScreen from './screens/RiskScreen';
import TradeScreen from './screens/TradeScreen';
import ProfileScreen from './screens/ProfileScreen';
import { ThemeProvider, useBilshenzTheme } from './contexts/ThemeContext';
import { AuthProvider } from './contexts/AuthContext';
import { BinanceBridgeProvider, useBinanceBridge } from './contexts/BinanceBridgeContext';
import { DevPreviewProvider } from './contexts/DevPreviewContext';
import { useTickScanner } from './hooks/useTickScanner';
import { useDeskSession } from './hooks/useDeskSession';

// Opening splash stays lazy — not on the tab path.
const AppOpeningSplash = React.lazy(() => import('./components/AppOpeningSplash'));

function AppContent() {
  const { colors: C, styles } = useBilshenzTheme();
  const insets = useSafeAreaInsets();
  const { baseUrl, connected, sessionEpoch } = useBinanceBridge();
  const [tab, setTab] = useState('scanner');
  // Mount tabs on first visit only — shell/header/nav/feeds stay alive; no remount on return.
  const [mounted, setMounted] = useState({
    scanner: true,
    risk: false,
    trade: false,
    profile: false,
  });
  const [tradeVisited, setTradeVisited] = useState(false);

  const onTabChange = useCallback((name) => {
    startTransition(() => {
      setTab(name);
      if (name === 'trade') setTradeVisited(true);
      setMounted((m) => (m[name] ? m : { ...m, [name]: true }));
    });
  }, []);

  const hasApi = !!baseUrl?.trim();
  const deskEnabled = hasApi;
  const scannerEnabled = hasApi;

  // Keep quote WS + desk feeds alive across ALL tabs — navigation must not tear Binance down.
  // pauseFeedUi slows REST churn on Profile without disconnecting streams.
  const desk = useDeskSession({
    enabled: deskEnabled,
    loadBars: tradeVisited || tab === 'trade',
    pollTicks: true,
    pauseFeedUi: tab === 'profile',
  });
  const tickScanner = useTickScanner(baseUrl, {
    enabled: scannerEnabled,
    connected,
    sessionEpoch,
    // Buffer scanner row churn off Home/Trade so tab switches stay instant.
    pauseUi: tab !== 'scanner' && tab !== 'trade',
  });

  const { done: onboardingDone, markDone: markOnboardingDone } = useOnboardingDone();

  const pad = Math.max(16, Math.min(24, 14 + insets.left));
  const openProfile = useCallback(() => onTabChange('profile'), [onTabChange]);

  const homeAccount = useMemo(() => {
    if (!connected || !desk.brokerFeed?.account) return null;
    return desk.brokerFeed.account;
  }, [connected, desk.brokerFeed?.account]);

  const tabStyle = useCallback(
    (name) => ({
      flex: 1,
      display: tab === name ? 'flex' : 'none',
    }),
    [tab],
  );

  useEffect(() => {
    hideBootSplash('app-content-ready');
  }, []);

  return (
    <SafeAreaView style={[styles.safeRoot, { backgroundColor: C.appBg }]} edges={['top', 'left', 'right']}>
      <View style={{ paddingHorizontal: pad, paddingTop: 6, paddingBottom: 10, backgroundColor: C.appBg }}>
        <BilshenzHeader />
      </View>
      <EmailVerificationBanner />

      {mounted.scanner ? (
        <View style={tabStyle('scanner')} pointerEvents={tab === 'scanner' ? 'auto' : 'none'} collapsable={false}>
          <ScannerScreen
            pad={pad}
            scanner={tickScanner}
            onOpenProfile={openProfile}
            connected={connected}
            account={homeAccount}
            active={tab === 'scanner'}
          />
        </View>
      ) : null}
      {mounted.risk ? (
        <View style={tabStyle('risk')} pointerEvents={tab === 'risk' ? 'auto' : 'none'} collapsable={false}>
          <RiskScreen pad={pad} desk={desk} onOpenProfile={openProfile} active={tab === 'risk'} />
        </View>
      ) : null}
      {mounted.trade ? (
        <View style={tabStyle('trade')} pointerEvents={tab === 'trade' ? 'auto' : 'none'} collapsable={false}>
          <TradeScreen
            pad={pad}
            desk={desk}
            scanner={tickScanner}
            onOpenProfile={openProfile}
            active={tab === 'trade'}
          />
        </View>
      ) : null}
      {mounted.profile ? (
        <View style={tabStyle('profile')} pointerEvents={tab === 'profile' ? 'auto' : 'none'} collapsable={false}>
          <ProfileScreen pad={pad} active={tab === 'profile'} />
        </View>
      ) : null}

      <AppBottomNav tab={tab} onChange={onTabChange} bottomInset={insets.bottom} pad={pad} />

      <OnboardingGate
        visible={onboardingDone === false}
        onComplete={markOnboardingDone}
        onOpenProfile={() => {
          onTabChange('profile');
          markOnboardingDone();
        }}
      />
    </SafeAreaView>
  );
}

class AppContentBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null, key: 0 };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch(err) {
    hideBootSplash('content-boundary');
    console.error('[Bilshenz] AppContentBoundary', err?.message);
  }

  render() {
    if (this.state.err) {
      return (
        <BootFallback
          message={this.state.err?.message || 'App failed to load.'}
          onRetry={() => this.setState({ err: null, key: this.state.key + 1 })}
        />
      );
    }
    return <AppContent key={this.state.key} />;
  }
}

function AppRoot() {
  const { styles, colors: C } = useBilshenzTheme();
  return (
    <View style={[styles.appShell, { backgroundColor: C.appBg }]}>
      <AppContentBoundary />
    </View>
  );
}

export default function App() {
  const [showOpening, setShowOpening] = useState(() => shouldPlayOpening());

  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AuthProvider>
          <DevPreviewProvider>
            <BinanceBridgeProvider>
              <AuthGate>
                <AppRoot />
              </AuthGate>
              {showOpening ? (
                <React.Suspense fallback={null}>
                  <AppOpeningSplash onComplete={() => setShowOpening(false)} />
                </React.Suspense>
              ) : null}
            </BinanceBridgeProvider>
          </DevPreviewProvider>
        </AuthProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
