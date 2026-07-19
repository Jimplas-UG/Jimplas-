import React, { useLayoutEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import BrandLogoSplash, { BRAND_SPLASH_MAX_MS } from './BrandLogoSplash';
import { hideBootSplash } from '../lib/bootSplash';

export const SPLASH_MAX_MS = BRAND_SPLASH_MAX_MS;

/**
 * Opening overlay — shared BS logo, then home tab.
 * Dismisses the native splash immediately so the PNG logo is what the user sees.
 */
export default function AppOpeningSplash({ onComplete }) {
  useLayoutEffect(() => {
    hideBootSplash('opening-overlay');
  }, []);

  return (
    <View style={styles.overlay}>
      <BrandLogoSplash onComplete={onComplete} />
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 10000,
    elevation: 10000,
    backgroundColor: '#000000',
  },
});
