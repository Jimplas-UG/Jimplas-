import React from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';

import { useBilshenzTheme } from '../contexts/ThemeContext';
import AnimatedHexLogo from './logo/AnimatedHexLogo';
import { VB } from './logo/hexLogoGeometry';

const serifHeading = Platform.select({
  ios: 'Georgia',
  android: 'serif',
  default: 'serif',
});

export default function BilshenzHeader() {
  const { colors: C } = useBilshenzTheme();

  return (
    <View style={styles.headerRow} testID="bilshenz-header">
      <AnimatedHexLogo size={VB} />
      <View style={styles.textStack}>
        <Text style={[styles.h1, { fontFamily: serifHeading, color: C.goldL }]}>BILSHENZ</Text>
        <Text style={[styles.sub, { color: C.dim }]}>Jimplas Capital Management · USDT-M Institutional Desk</Text>
        <Text style={[styles.vtag, { color: C.dim2 }]}>AUTOMATED · RISK-MANAGED · BINANCE FUTURES</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    flexShrink: 1,
  },
  textStack: {
    flexDirection: 'column',
    gap: 2,
    flexShrink: 1,
    minWidth: 0,
  },
  h1: {
    fontSize: 22,
    fontWeight: '900',
    letterSpacing: 6,
  },
  sub: {
    fontSize: 8,
    fontWeight: '500',
    letterSpacing: 3,
    textTransform: 'uppercase',
  },
  vtag: {
    fontSize: 7,
    fontWeight: '600',
    letterSpacing: 2,
  },
});
