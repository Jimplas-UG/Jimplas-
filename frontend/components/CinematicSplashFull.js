import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Dimensions, Platform, StyleSheet, Text, View } from 'react-native';
import Svg, { Defs, Line, LinearGradient, Polygon, Stop, Text as SvgText } from 'react-native-svg';
import Animated, {
  Easing,
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { CX, CY, MAIN_HEX, VB } from './logo/hexLogoGeometry';

const AnimatedView = Animated.View;

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get('window');
const LOGO_SIZE = Math.min(SCREEN_W * 0.56, 210);

const GOLD = '#D4B45A';
const GOLD_BRIGHT = '#F2E2B0';
const GOLD_PALE = '#FFF4D0';

/** 9-step cinematic open ΓÇö ~8.3s animation + fade; hard cap 9s. */
export const OPENING_STEP_COUNT = 9;
export const SPLASH_MAX_MS = 9000;
export const CINEMATIC_SPLASH_MS = SPLASH_MAX_MS;

const PHASE_MS = 820;
const TITLE_MS = 900;
const FADE_MS = 550;
const ANIM_MS = OPENING_STEP_COUNT * PHASE_MS + TITLE_MS;
const HOLD_BEFORE_FADE_MS = 400;

const serif = Platform.select({ ios: 'Georgia', android: 'serif', default: 'serif' });

function hexPointsArray(pointsStr) {
  return pointsStr.split(' ').map((pair) => {
    const [x, y] = pair.split(',').map(Number);
    return { x, y };
  });
}

const HEX_VERTS = hexPointsArray(MAIN_HEX);

function EnergySpark({ phase }) {
  const style = useAnimatedStyle(() => {
    const p = interpolate(phase.value, [0, 0.6, 1.2], [0, 1, 0.35], Extrapolation.CLAMP);
    return {
      opacity: p,
      transform: [{ scale: interpolate(p, [0, 1], [0.2, 1.8]) }],
    };
  });
  return (
    <AnimatedView style={[styles.sparkCore, style]} pointerEvents="none">
      <View style={styles.sparkDot} />
    </AnimatedView>
  );
}

function ParticleRing({ phase }) {
  const particles = useMemo(
    () =>
      Array.from({ length: 18 }, (_, i) => ({
        angle: (i / 18) * Math.PI * 2,
        radius: LOGO_SIZE * (0.55 + (i % 3) * 0.04),
        size: 2 + (i % 3),
        delay: i * 0.04,
      })),
    [],
  );

  return (
    <>
      {particles.map((p, i) => (
        <OrbitingParticle key={i} p={p} phase={phase} />
      ))}
    </>
  );
}

function OrbitingParticle({ p, phase }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [0.8 + p.delay, 2.2], [0, 1], Extrapolation.CLAMP);
    const spin = p.angle + t * Math.PI * 1.6;
    const r = interpolate(t, [0, 0.7, 1], [p.radius * 1.35, p.radius * 0.92, p.radius * 0.78]);
    return {
      opacity: interpolate(t, [0, 0.15, 0.85, 1], [0, 0.95, 0.75, 0.5]),
      transform: [
        { translateX: Math.cos(spin) * r },
        { translateY: Math.sin(spin) * r },
        { scale: interpolate(t, [0, 1], [0.4, 1]) },
      ],
    };
  });
  return (
    <AnimatedView
      style={[
        styles.particle,
        { width: p.size, height: p.size, borderRadius: p.size, backgroundColor: GOLD_BRIGHT },
        style,
      ]}
      pointerEvents="none"
    />
  );
}

function HexEdge({ from, to, index, phase }) {
  const style = useAnimatedStyle(() => {
    const start = 1.8 + index * 0.08;
    const t = interpolate(phase.value, [start, start + 0.55], [0, 1], Extrapolation.CLAMP);
    const scatter = 28 + index * 4;
    return {
      opacity: t,
      transform: [
        { translateX: interpolate(t, [0, 1], [(from.x - CX) * scatter, 0]) },
        { translateY: interpolate(t, [0, 1], [(from.y - CY) * scatter, 0]) },
        { scale: interpolate(t, [0, 0.85, 1], [0.3, 1.06, 1]) },
      ],
    };
  });

  return (
    <AnimatedView style={[styles.hexEdge, style]} pointerEvents="none">
      <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
        <Defs>
          <LinearGradient id={`edge${index}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <Stop offset="0%" stopColor={GOLD_PALE} />
            <Stop offset="100%" stopColor={GOLD} />
          </LinearGradient>
        </Defs>
        <Line
          x1={from.x}
          y1={from.y}
          x2={to.x}
          y2={to.y}
          stroke={`url(#edge${index})`}
          strokeWidth={1.4}
          strokeLinecap="round"
        />
      </Svg>
    </AnimatedView>
  );
}

function HexFill({ phase }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [2.1, 2.8], [0, 1], Extrapolation.CLAMP);
    return { opacity: t, transform: [{ scale: interpolate(t, [0, 1], [0.85, 1]) }] };
  });
  return (
    <AnimatedView style={[styles.hexEdge, style]} pointerEvents="none">
      <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
        <Defs>
          <LinearGradient id="hexStroke" x1="0%" y1="0%" x2="100%" y2="100%">
            <Stop offset="0%" stopColor={GOLD_PALE} />
            <Stop offset="50%" stopColor={GOLD} />
            <Stop offset="100%" stopColor="#7A5C18" />
          </LinearGradient>
        </Defs>
        <Polygon
          points={MAIN_HEX}
          fill="rgba(212,180,90,0.04)"
          stroke="url(#hexStroke)"
          strokeWidth={1.35}
        />
      </Svg>
    </AnimatedView>
  );
}

function HexagonAssemble({ phase }) {
  return (
    <>
      {HEX_VERTS.map((from, i) => {
        const to = HEX_VERTS[(i + 1) % HEX_VERTS.length];
        return <HexEdge key={i} from={from} to={to} index={i} phase={phase} />;
      })}
      <HexFill phase={phase} />
    </>
  );
}

function LettersBS({ phase }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [3, 3.75], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: t,
      transform: [
        { scale: interpolate(t, [0, 0.7, 1], [0.5, 1.08, 1]) },
        { translateY: interpolate(t, [0, 1], [8, 0]) },
      ],
    };
  });

  const shine = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [3.2, 4.2], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: interpolate(t, [0, 0.4, 1], [0, 0.85, 0.25]),
      transform: [{ translateX: interpolate(t, [0, 1], [-LOGO_SIZE * 0.5, LOGO_SIZE * 0.55]) }],
    };
  });

  return (
    <AnimatedView style={[styles.logoLayer, style]} pointerEvents="none">
      <View style={styles.shineClip}>
        <AnimatedView style={[styles.metalShine, shine]} />
      </View>
      <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
        <Defs>
          <LinearGradient id="gradB" x1="0%" y1="0%" x2="100%" y2="100%">
            <Stop offset="0%" stopColor={GOLD_PALE} />
            <Stop offset="100%" stopColor="#C98A2E" />
          </LinearGradient>
          <LinearGradient id="gradS" x1="100%" y1="0%" x2="0%" y2="100%">
            <Stop offset="0%" stopColor={GOLD_BRIGHT} />
            <Stop offset="100%" stopColor="#7A5C18" />
          </LinearGradient>
        </Defs>
        <SvgText x={27} y={45} fontSize={16} fontWeight="bold" fontFamily={serif} fill="url(#gradB)">
          B
        </SvgText>
        <SvgText x={39} y={45} fontSize={16} fontWeight="bold" fontFamily={serif} fill="url(#gradS)">
          S
        </SvgText>
      </Svg>
    </AnimatedView>
  );
}

function GoldenBurst({ phase }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [4, 4.65], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: interpolate(t, [0, 0.25, 1], [0, 0.95, 0.22]),
      transform: [{ scale: interpolate(t, [0, 0.35, 1], [0.3, 1.45, 1.15]) }],
    };
  });
  return (
    <AnimatedView
      style={[
        styles.burst,
        { width: LOGO_SIZE * 2.1, height: LOGO_SIZE * 2.1, borderRadius: LOGO_SIZE },
        style,
      ]}
      pointerEvents="none"
    />
  );
}

function RippleRings({ phase }) {
  return [0, 1, 2].map((i) => <Ripple key={i} index={i} phase={phase} />);
}

function Ripple({ index, phase }) {
  const style = useAnimatedStyle(() => {
    const start = 4.8 + index * 0.12;
    const t = interpolate(phase.value, [start, start + 0.9], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: interpolate(t, [0, 0.2, 1], [0, 0.55, 0]),
      transform: [{ scale: 0.7 + t * (0.55 + index * 0.12) }],
    };
  });
  return (
    <AnimatedView
      style={[
        styles.ripple,
        { width: LOGO_SIZE * 1.35, height: LOGO_SIZE * 1.35, borderRadius: LOGO_SIZE },
        style,
      ]}
      pointerEvents="none"
    />
  );
}

function Logo3DStage({ phase, children }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [4.5, 5.8], [0, 1], Extrapolation.CLAMP);
    const rot = interpolate(t, [0, 0.45, 0.75, 1], [0, 14, -6, 0]);
    return {
      transform: [
        { perspective: 900 },
        { rotateY: `${rot}deg` },
        { rotateX: `${interpolate(t, [0, 0.5, 1], [4, -3, 0])}deg` },
        { scale: interpolate(t, [0, 0.5, 1], [0.96, 1.04, 1]) },
      ],
    };
  });
  return <AnimatedView style={[styles.stage3d, style]}>{children}</AnimatedView>;
}

function LightWaves({ phase }) {
  const waves = [0, 1, 2];
  return (
    <View style={styles.waveField} pointerEvents="none">
      {waves.map((i) => (
        <WaveLine key={i} index={i} phase={phase} />
      ))}
    </View>
  );
}

function WaveLine({ index, phase }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [5.2, 6.6], [0, 1], Extrapolation.CLAMP);
    const drift = (t + index * 0.2) % 1;
    return {
      opacity: 0.08 + t * 0.22,
      transform: [
        { translateX: interpolate(drift, [0, 1], [-40, 40]) },
        { translateY: index * 14 - 14 },
        { scaleX: 1 + index * 0.15 },
      ],
    };
  });
  return <AnimatedView style={[styles.waveLine, style]} />;
}

function FinalGlow({ phase }) {
  const halo = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [6.2, 7.2], [0, 1], Extrapolation.CLAMP);
    const pulse = interpolate(phase.value, [7, 8.5], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: 0.12 + t * 0.38 + Math.sin(pulse * Math.PI * 2) * 0.08,
      transform: [{ scale: 0.88 + t * 0.14 }],
    };
  });
  return (
    <AnimatedView
      style={[styles.halo, { width: LOGO_SIZE * 1.7, height: LOGO_SIZE * 1.7, borderRadius: LOGO_SIZE }, halo]}
      pointerEvents="none"
    />
  );
}

function AppTitle({ phase }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(phase.value, [7.5, 8.6], [0, 1], Extrapolation.CLAMP);
    return {
      opacity: t,
      transform: [{ translateY: interpolate(t, [0, 1], [18, 0]) }],
    };
  });
  return (
    <AnimatedView style={[styles.titleWrap, style]} pointerEvents="none">
      <Text style={styles.title}>BSV32 TRADING SYSTEM</Text>
    </AnimatedView>
  );
}

function AmbientGlow({ phase }) {
  const style = useAnimatedStyle(() => ({
    opacity: interpolate(phase.value, [0, 2, 8], [0, 0.35, 0.55], Extrapolation.CLAMP),
    transform: [{ scale: 0.9 + interpolate(phase.value, [0, 9], [0, 0.18]) }],
  }));
  return (
    <AnimatedView
      style={[styles.ambientGlow, { width: SCREEN_W * 0.95, height: SCREEN_W * 0.95, borderRadius: SCREEN_W }, style]}
      pointerEvents="none"
    />
  );
}

/**
 * 9-step cinematic opening ΓÇö energy ΓåÆ particles ΓåÆ hex ΓåÆ BS ΓåÆ burst ΓåÆ 3D ΓåÆ waves ΓåÆ lock ΓåÆ title.
 */
export default function CinematicSplash({ onComplete }) {
  const phase = useSharedValue(0);
  const fade = useSharedValue(1);
  const fadingRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const beginFade = useCallback(() => {
    if (fadingRef.current) return;
    fadingRef.current = true;
    fade.value = withTiming(0, { duration: FADE_MS, easing: Easing.inOut(Easing.cubic) }, (finished) => {
      if (finished && onCompleteRef.current) runOnJS(onCompleteRef.current)();
    });
  }, [fade]);

  useEffect(() => {
    phase.value = withTiming(OPENING_STEP_COUNT, {
      duration: ANIM_MS,
      easing: Easing.inOut(Easing.cubic),
    });
    const done = setTimeout(() => beginFade(), ANIM_MS + HOLD_BEFORE_FADE_MS);
    const cap = setTimeout(() => beginFade(), SPLASH_MAX_MS);
    return () => {
      clearTimeout(done);
      clearTimeout(cap);
    };
  }, [beginFade, phase]);

  const rootStyle = useAnimatedStyle(() => ({ opacity: fade.value }));

  return (
    <AnimatedView style={[styles.root, rootStyle]}>
      <View style={styles.bgVoid} />
      <AmbientGlow phase={phase} />
      <Logo3DStage phase={phase}>
        <View style={styles.logoStack}>
          <GoldenBurst phase={phase} />
          <RippleRings phase={phase} />
          <LightWaves phase={phase} />
          <FinalGlow phase={phase} />
          <EnergySpark phase={phase} />
          <ParticleRing phase={phase} />
          <HexagonAssemble phase={phase} />
          <LettersBS phase={phase} />
        </View>
      </Logo3DStage>
      <AppTitle phase={phase} />
    </AnimatedView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#0A0E17',
    alignItems: 'center',
    justifyContent: 'center',
  },
  bgVoid: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#0A0E17',
  },
  ambientGlow: {
    position: 'absolute',
    alignSelf: 'center',
    top: SCREEN_H * 0.2,
    backgroundColor: 'rgba(212,180,90,0.07)',
    shadowColor: GOLD,
    shadowOpacity: 0.45,
    shadowRadius: 80,
    shadowOffset: { width: 0, height: 0 },
  },
  stage3d: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoStack: {
    width: LOGO_SIZE,
    height: LOGO_SIZE,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoLayer: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hexEdge: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sparkCore: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sparkDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: GOLD_PALE,
    shadowColor: GOLD_BRIGHT,
    shadowOpacity: 1,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 0 },
  },
  particle: {
    position: 'absolute',
    shadowColor: GOLD,
    shadowOpacity: 0.9,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 0 },
  },
  shineClip: {
    ...StyleSheet.absoluteFillObject,
    overflow: 'hidden',
  },
  metalShine: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 28,
    backgroundColor: 'rgba(255,244,208,0.35)',
    transform: [{ skewX: '-12deg' }],
  },
  burst: {
    position: 'absolute',
    backgroundColor: 'rgba(242,226,176,0.22)',
    shadowColor: GOLD_BRIGHT,
    shadowOpacity: 0.95,
    shadowRadius: 50,
    shadowOffset: { width: 0, height: 0 },
  },
  ripple: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: 'rgba(242,226,176,0.35)',
    backgroundColor: 'transparent',
  },
  halo: {
    position: 'absolute',
    backgroundColor: 'rgba(212,180,90,0.1)',
    shadowColor: GOLD,
    shadowOpacity: 0.75,
    shadowRadius: 36,
    shadowOffset: { width: 0, height: 0 },
  },
  waveField: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  waveLine: {
    position: 'absolute',
    width: LOGO_SIZE * 1.4,
    height: 2,
    borderRadius: 1,
    backgroundColor: 'rgba(212,180,90,0.28)',
    shadowColor: GOLD,
    shadowOpacity: 0.5,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 },
  },
  titleWrap: {
    position: 'absolute',
    bottom: SCREEN_H * 0.14,
    alignItems: 'center',
    width: '100%',
    paddingHorizontal: 24,
  },
  title: {
    color: GOLD_BRIGHT,
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 3.2,
    textAlign: 'center',
    fontFamily: serif,
    textShadowColor: GOLD,
    textShadowRadius: 12,
    textShadowOffset: { width: 0, height: 0 },
  },
});
