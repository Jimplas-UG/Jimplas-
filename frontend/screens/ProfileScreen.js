import React, { memo } from 'react';
import { ScrollView, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { PilotSectionTitle } from '../components/pilot/PilotUI';
import BinanceBridgePanel from '../components/BinanceBridgePanel';
import AccountProfileCard from '../components/auth/AccountProfileCard';

function ProfileScreen({ pad, active = true }) {
  const { colors: C, styles } = useBilshenzTheme();

  return (
    <ScrollView
      style={[styles.psTabBody, { flex: 1, backgroundColor: C.appBg }]}
      contentContainerStyle={{ paddingHorizontal: pad, paddingBottom: 32 }}
      keyboardShouldPersistTaps="handled"
      scrollEnabled={active}>
      <PilotSectionTitle title="Account" />
      <AccountProfileCard />

      <View style={{ height: 20 }} />
      <PilotSectionTitle title="Exchange connection" />
      <BinanceBridgePanel />
    </ScrollView>
  );
}

export default memo(ProfileScreen);
