import React, { Suspense, lazy } from 'react';
import { ActivityIndicator, ScrollView, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { PilotSectionTitle } from '../components/pilot/PilotUI';

const BinanceBridgePanelLazy = lazy(() => import('../components/BinanceBridgePanel'));
const AccountProfileCardLazy = lazy(() => import('../components/auth/AccountProfileCard'));

function PanelFallback() {
  const { colors: C } = useBilshenzTheme();
  return (
    <View style={{ padding: 24, alignItems: 'center' }}>
      <ActivityIndicator color={C.accentLight} />
    </View>
  );
}

export default function ProfileScreen({ pad }) {
  const { colors: C, styles } = useBilshenzTheme();

  return (
    <ScrollView
      style={[styles.psTabBody, { flex: 1, backgroundColor: C.appBg }]}
      contentContainerStyle={{ paddingHorizontal: pad, paddingBottom: 32 }}
      keyboardShouldPersistTaps="handled">
      <PilotSectionTitle title="Account" />
      <Suspense fallback={<PanelFallback />}>
        <AccountProfileCardLazy />
      </Suspense>

      <View style={{ height: 20 }} />
      <PilotSectionTitle title="Exchange connection" />
      <Suspense fallback={<PanelFallback />}>
        <BinanceBridgePanelLazy />
      </Suspense>
    </ScrollView>
  );
}
