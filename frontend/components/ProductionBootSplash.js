import React, { useEffect, useRef } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { hideBootSplash } from '../lib/bootSplash';
import StaticHexLogo from './logo/StaticHexLogo';

const LOGO_SIZE = 120;
/** Cosmetic overlay only — app renders underneath immediately. */
export const PRODUCTION_BOOT_MS = 350;

/**
 * Non-blocking boot overlay (no Reanimated — avoids worklet black-screen on some devices).
 * @param {{ onComplete: () => void }} props
 */
export default function ProductionBootSplash({ onComplete }) {
  const doneRef = useRef(false);

  useEffect(() => {
    const finish = () => {
      if (doneRef.current) return;
      doneRef.current = true;
      hideBootSplash('prod-overlay-done');
      onComplete?.();
    };
    hideBootSplash('prod-overlay-mount');
    const quick = setTimeout(finish, PRODUCTION_BOOT_MS);
    const cap = setTimeout(finish, 4000);
    return () => {
      clearTimeout(quick);
      clearTimeout(cap);
    };
  }, [onComplete]);

  return (
    <View style={styles.root} pointerEvents="none">
      <StaticHexLogo size={LOGO_SIZE} />
      <Text style={styles.title}>Bilshenz</Text>
      <ActivityIndicator color="#D4B45A" style={styles.spinner} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#100E0A',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 50,
  },
  title: {
    marginTop: 14,
    color: '#D4B45A',
    fontSize: 18,
    fontWeight: '800',
    letterSpacing: 2,
  },
  spinner: { marginTop: 20 },
});
