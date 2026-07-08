import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
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

const AppOpeningSplashLazy = lazy(() => import('./components/AppOpeningSplash'));

function AppContent() {
  const { colors: C, styles } = useBilshenzTheme();
  const insets = useSafeAreaInsets();
  const { baseUrl, connected, sessionEpoch } = useBinanceBridge();
  const [tab, setTab] = useState('scanner');

  const needsScanner = tab === 'scanner' || tab === 'trade';
  const needsDesk = tab === 'risk' || tab === 'trade';

  const desk = useDeskSession({
    enabled: needsScanner || needsDesk,
    loadBars: needsDesk,
    pollTicks: needsDesk || tab === 'trade',
  });
  const tickScanner = useTickScanner(baseUrl, {
    enabled: !!baseUrl?.trim() && needsScanner,
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

  useEffect(() => {
    hideBootSplash('app-content-ready');
  }, []);

  let body = null;
  if (tab === 'scanner') {
    body = (
      <ScannerScreen
        pad={pad}
        scanner={tickScanner}
        onOpenProfile={openProfile}
        connected={connected}
        account={homeAccount}
      />
    );
  } else if (tab === 'risk') {
    body = <RiskScreen pad={pad} desk={desk} onOpenProfile={openProfile} />;
  } else if (tab === 'trade') {
    body = <TradeScreen pad={pad} desk={desk} scanner={tickScanner} onOpenProfile={openProfile} />;
  } else {
    body = <ProfileScreen pad={pad} />;
  }

  return (
    <SafeAreaView style={[styles.safeRoot, { backgroundColor: C.appBg }]} edges={['top', 'left', 'right']}>
      <View style={{ paddingHorizontal: pad, paddingTop: 6, paddingBottom: 10, backgroundColor: C.appBg }}>
        <BilshenzHeader />
      </View>
      <EmailVerificationBanner />

      {body}

      <AppBottomNav tab={tab} onChange={setTab} bottomInset={insets.bottom} />

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
