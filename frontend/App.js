import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
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
import { ThemeProvider, useBilshenzTheme } from './contexts/ThemeContext';
import { AuthProvider } from './contexts/AuthContext';
import { BinanceBridgeProvider, useBinanceBridge } from './contexts/BinanceBridgeContext';
import { DevPreviewProvider } from './contexts/DevPreviewContext';
import { useTickScanner } from './hooks/useTickScanner';
import { useDeskSession } from './hooks/useDeskSession';

const RiskScreenLazy = lazy(() => import('./screens/RiskScreen'));
const TradeScreenLazy = lazy(() => import('./screens/TradeScreen'));
const ProfileScreenLazy = lazy(() => import('./screens/ProfileScreen'));

const AppOpeningSplashLazy = lazy(() => import('./components/AppOpeningSplash'));

function TabFallback() {
  const { colors: C } = useBilshenzTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: C.appBg }}>
      <ActivityIndicator color={C.goldL} />
    </View>
  );
}

function AppContent() {
  const { colors: C, styles } = useBilshenzTheme();
  const insets = useSafeAreaInsets();
  const { baseUrl, connected, sessionEpoch } = useBinanceBridge();
  const [tab, setTab] = useState('scanner');
  const [mounted, setMounted] = useState({ scanner: true });

  const onTabChange = useCallback((name) => {
    setTab(name);
    setMounted((m) => (m[name] ? m : { ...m, [name]: true }));
  }, []);

  const deskEnabled = !!baseUrl?.trim() && (tab === 'risk' || tab === 'trade');
  const scannerEnabled = !!baseUrl?.trim() && (tab === 'scanner' || tab === 'trade');

  const desk = useDeskSession({
    enabled: deskEnabled,
    loadBars: false,
    pollTicks: deskEnabled,
  });
  const tickScanner = useTickScanner(baseUrl, {
    enabled: scannerEnabled,
    connected,
    sessionEpoch,
  });

  const { done: onboardingDone, markDone: markOnboardingDone } = useOnboardingDone();

  const pad = Math.max(16, Math.min(24, 14 + insets.left));
  const openProfile = useCallback(() => setTab('profile'), []);

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
        <View style={tabStyle('scanner')}>
          <ScannerScreen
            pad={pad}
            scanner={tickScanner}
            onOpenProfile={openProfile}
            connected={connected}
            account={homeAccount}
          />
        </View>
      ) : null}
      {mounted.risk ? (
        <View style={tabStyle('risk')}>
          <Suspense fallback={<TabFallback />}>
            <RiskScreenLazy pad={pad} desk={desk} onOpenProfile={openProfile} active={tab === 'risk'} />
          </Suspense>
        </View>
      ) : null}
      {mounted.trade ? (
        <View style={tabStyle('trade')}>
          <Suspense fallback={<TabFallback />}>
            <TradeScreenLazy pad={pad} desk={desk} scanner={tickScanner} onOpenProfile={openProfile} active={tab === 'trade'} />
          </Suspense>
        </View>
      ) : null}
      {mounted.profile ? (
        <View style={tabStyle('profile')}>
          <Suspense fallback={<TabFallback />}>
            <ProfileScreenLazy pad={pad} />
          </Suspense>
        </View>
      ) : null}

      <AppBottomNav tab={tab} onChange={onTabChange} bottomInset={insets.bottom} />

      <OnboardingGate
        visible={onboardingDone === false}
        onComplete={markOnboardingDone}
        onOpenProfile={() => {
          setTab('profile');
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
                <Suspense fallback={null}>
                  <AppOpeningSplashLazy onComplete={() => setShowOpening(false)} />
                </Suspense>
              ) : null}
            </BinanceBridgeProvider>
          </DevPreviewProvider>
        </AuthProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
