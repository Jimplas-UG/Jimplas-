import React, { useCallback, useEffect, useRef } from 'react';
import { Dimensions, StyleSheet } from 'react-native';
import Animated, {
  Easing,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import BrandLogo from './logo/BrandLogo';

const AnimatedView = Animated.View;
const { width: SCREEN_W } = Dimensions.get('window');
const LOGO_SIZE = Math.min(SCREEN_W * 0.52, 220);

const HOLD_MS = 900;
const FADE_IN_MS = 280;
const FADE_OUT_MS = 480;
export const BRAND_SPLASH_MAX_MS = HOLD_MS + FADE_IN_MS + FADE_OUT_MS + 200;

/**
 * Lightweight opening: show the shared gold BS logo, then fade into the home tab.
 * Safe for release APKs (no heavy cinematic timeline).
 */
export default function BrandLogoSplash({ onComplete }) {
  const fade = useSharedValue(0);
  const scale = useSharedValue(0.92);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const finish = useCallback(() => {
    onCompleteRef.current?.();
  }, []);

  useEffect(() => {
    fade.value = withTiming(1, { duration: FADE_IN_MS, easing: Easing.out(Easing.cubic) });
    scale.value = withTiming(1, { duration: FADE_IN_MS + 120, easing: Easing.out(Easing.cubic) });
    const hold = setTimeout(() => {
      fade.value = withTiming(0, { duration: FADE_OUT_MS, easing: Easing.inOut(Easing.cubic) }, (done) => {
        if (done) runOnJS(finish)();
      });
    }, HOLD_MS);
    const cap = setTimeout(finish, BRAND_SPLASH_MAX_MS);
    return () => {
      clearTimeout(hold);
      clearTimeout(cap);
    };
  }, [fade, scale, finish]);

  const rootStyle = useAnimatedStyle(() => ({
    opacity: fade.value,
    transform: [{ scale: scale.value }],
  }));

  return (
    <AnimatedView style={[styles.root, rootStyle]}>
      <BrandLogo size={LOGO_SIZE} />
    </AnimatedView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#000000',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
