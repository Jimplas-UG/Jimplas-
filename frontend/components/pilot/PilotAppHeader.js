import React from 'react';
import { Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { PilotPill } from './PilotUI';

const TAB_TITLES = {
  scanner: 'Home',
  risk: 'Risk',
  trade: 'Trade',
  profile: 'Settings',
};

export default function PilotAppHeader({ tab, execOn, connected }) {
  const { colors: C } = useBilshenzTheme();
  const title = TAB_TITLES[tab] || 'BILSHENZ';

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingVertical: 4,
      }}>
      <View>
        <Text style={{ color: C.dim2, fontSize: 10, fontWeight: '600', letterSpacing: 1 }}>BILSHENZ</Text>
        <Text style={{ color: C.text, fontSize: 22, fontWeight: '800', letterSpacing: -0.3 }}>{title}</Text>
      </View>
      <View style={{ alignItems: 'flex-end', gap: 6 }}>
        {execOn ? (
          <PilotPill label="Auto exec ON" ok accent />
        ) : connected ? (
          <PilotPill label="Manual" warn />
        ) : (
          <PilotPill label="Offline" warn />
        )}
        <PilotPill label={connected ? 'Binance linked' : 'Not connected'} ok={connected} warn={!connected} />
      </View>
    </View>
  );
}
