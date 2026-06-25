import React, { useLayoutEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import CinematicSplash, { SPLASH_MAX_MS } from './CinematicSplash';
import { hideBootSplash } from '../lib/bootSplash';
import { skipSplash } from '../lib/devPreview';

export { SPLASH_MAX_MS };

/**
 * Cinematic opening only — dismisses native static splash immediately, then plays animation.
 */
export default function AppOpeningSplash({ onComplete }) {
  useLayoutEffect(() => {
    hideBootSplash('opening-overlay');
  }, []);

  return (
    <View style={styles.overlay}>
      <CinematicSplash onComplete={onComplete} />
    </View>
  );
}

export function shouldPlayOpening() {
  return !skipSplash();
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 10000,
    elevation: 10000,
    backgroundColor: '#000000',
  },
});
