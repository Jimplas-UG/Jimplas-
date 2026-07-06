import React, { Suspense, lazy, useCallback, useEffect, useRef } from 'react';
import { Dimensions, Platform, StyleSheet, Text, View } from 'react-native';
import Svg, { Defs, LinearGradient, Polygon, Stop, Text as SvgText } from 'react-native-svg';
import Animated, {
  Easing,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { fastSplash } from '../lib/devPreview';
import { MAIN_HEX, VB } from './logo/hexLogoGeometry';

const AnimatedView = Animated.View;
const CinematicSplashFull = lazy(() => import('./CinematicSplashFull'));

const { width: SCREEN_W } = Dimensions.get('window');
const LOGO_SIZE = Math.min(SCREEN_W * 0.46, 180);
const GOLD_BRIGHT = '#F2E2B0';
const serif = Platform.select({ ios: 'Georgia', android: 'serif', default: 'serif' });

/** Full cinematic open — ~8.3s + fade; hard cap 9s. */
export const OPENING_STEP_COUNT = 9;
export const SPLASH_MAX_MS = 9000;
export const CINEMATIC_SPLASH_MS = SPLASH_MAX_MS;

const FAST_HOLD_MS = 350;
const FAST_FADE_MS = 450;
export const FAST_SPLASH_MAX_MS = FAST_HOLD_MS + FAST_FADE_MS + 200;

function StaticLogo() {
  return (
    <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
      <Defs>
        <LinearGradient id="hexStroke" x1="0%" y1="0%" x2="100%" y2="100%">
          <Stop offset="0%" stopColor={GOLD_BRIGHT} />
          <Stop offset="100%" stopColor="#7A5C18" />
        </LinearGradient>
        <LinearGradient id="gradB" x1="0%" y1="0%" x2="100%" y2="100%">
          <Stop offset="0%" stopColor={GOLD_BRIGHT} />
          <Stop offset="100%" stopColor="#C98A2E" />
        </LinearGradient>
      </Defs>
      <Polygon points={MAIN_HEX} fill="rgba(212,180,90,0.06)" stroke="url(#hexStroke)" strokeWidth={1.35} />
      <SvgText x={27} y={45} fontSize={16} fontWeight="bold" fontFamily={serif} fill="url(#gradB)">
        BS
      </SvgText>
    </Svg>
  );
}

function FastOpeningSplash({ onComplete }) {
  const fade = useSharedValue(0);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const finish = useCallback(() => {
    onCompleteRef.current?.();
  }, []);

  useEffect(() => {
    fade.value = withTiming(1, { duration: 220, easing: Easing.out(Easing.cubic) });
    const hold = setTimeout(() => {
      fade.value = withTiming(0, { duration: FAST_FADE_MS, easing: Easing.inOut(Easing.cubic) }, (done) => {
        if (done) runOnJS(finish)();
      });
    }, FAST_HOLD_MS);
    const cap = setTimeout(finish, FAST_SPLASH_MAX_MS);
    return () => {
      clearTimeout(hold);
      clearTimeout(cap);
    };
  }, [fade, finish]);

  const rootStyle = useAnimatedStyle(() => ({ opacity: fade.value }));

  return (
    <AnimatedView style={[styles.root, rootStyle]}>
      <StaticLogo />
      <Text style={styles.title}>BSV32</Text>
    </AnimatedView>
  );
}

/**
 * Opening splash — fast fade in dev; full cinematic lazy-loaded in production.
 */
export default function CinematicSplash({ onComplete }) {
  if (fastSplash()) {
    return <FastOpeningSplash onComplete={onComplete} />;
  }

  return (
    <Suspense fallback={<FastOpeningSplash onComplete={onComplete} />}>
      <CinematicSplashFull onComplete={onComplete} />
    </Suspense>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#0A0E17',
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    marginTop: 18,
    color: GOLD_BRIGHT,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 3,
    fontFamily: serif,
  },
});
