import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Dimensions, Image, Platform, StyleSheet, View } from 'react-native';
import Svg, {
  Circle,
  Defs,
  G,
  Line,
  LinearGradient,
  Polygon,
  RadialGradient,
  Stop,
  Text as SvgText,
} from 'react-native-svg';
import Animated, {
  Easing,
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import * as SplashScreen from 'expo-splash-screen';
import { CX, CY, DIAMONDS, FRAGMENT_ANCHORS, INNER_HEX, MAIN_HEX, VB } from './logo/hexLogoGeometry';

const AnimatedView = Animated.View;

const BRAND_LOGO = require('../assets/brand/bs-app-logo.png');

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get('window');
const LOGO_SIZE = Math.min(SCREEN_W * 0.58, 220);

/** Black + gold ethereal palette (no blue). */
const COLORS = {
  black: '#000000',
  void: '#050403',
  abyss: '#0A0806',
  gold: '#D4B45A',
  goldBright: '#F2E2B0',
  goldPale: '#FFF4D0',
  goldDim: 'rgba(212,180,90,0.35)',
  goldWire: 'rgba(242,226,176,0.72)',
  amber: '#C98A2E',
  bronze: '#7A5C18',
};

/** Hard cap: cinematic open — fade to home within 8s. */
export const SPLASH_MAX_MS = 8000;

const WIRE_ASSEMBLY_MS = 2800;
const MATERIALIZE_MS = 1000;
const GOLD_SWEEP_MS = 900;
const MIN_GLOW_MS = 700;
const FADE_MS = 500;
const START_DELAY_MS = 180;
const ANIM_DONE_MS = START_DELAY_MS + WIRE_ASSEMBLY_MS + MATERIALIZE_MS + GOLD_SWEEP_MS + MIN_GLOW_MS;

const FRAGMENTS = [
  { id: 'outerRing', delay: 0, scatter: { x: 108, y: -52, r: 58, s: 0.26 } },
  { id: 'mainHex', delay: 0.06, scatter: { x: -98, y: 62, r: -52, s: 0.3 } },
  { id: 'innerRing', delay: 0.14, scatter: { x: 92, y: 88, r: 44, s: 0.28 } },
  { id: 'diamonds', delay: 0.22, scatter: { x: -88, y: -96, r: -68, s: 0.22 } },
  { id: 'innerHex', delay: 0.3, scatter: { x: 104, y: 28, r: 76, s: 0.34 } },
  { id: 'radar', delay: 0.38, scatter: { x: 8, y: -118, r: 135, s: 0.18 } },
  { id: 'center', delay: 0.46, scatter: { x: -122, y: -18, r: -95, s: 0.14 } },
  { id: 'letterB', delay: 0.54, scatter: { x: -128, y: 42, r: -28, s: 0.38 } },
  { id: 'letterS', delay: 0.6, scatter: { x: 132, y: -72, r: 42, s: 0.38 } },
];

const CONNECTIONS = [
  ['outerRing', 'mainHex'],
  ['mainHex', 'innerHex'],
  ['innerHex', 'diamonds'],
  ['mainHex', 'innerRing'],
  ['innerHex', 'radar'],
  ['mainHex', 'letterB'],
  ['mainHex', 'letterS'],
  ['center', 'mainHex'],
];

const serifSvg = Platform.select({ ios: 'Georgia', android: 'serif', default: 'serif' });

function LogoDefs({ mode }) {
  const wire = mode === 'wireframe';
  return (
    <Defs>
      <RadialGradient id="hexFill" cx={CX} cy={CY} r={30} gradientUnits="userSpaceOnUse">
        <Stop offset="0%" stopColor={wire ? 'rgba(212,180,90,0.14)' : '#1A1408'} />
        <Stop offset="55%" stopColor={wire ? 'rgba(122,92,24,0.06)' : '#0C0A06'} />
        <Stop offset="100%" stopColor="#000000" />
      </RadialGradient>
      <LinearGradient id="metalFill" x1="0%" y1="0%" x2="100%" y2="100%">
        <Stop offset="0%" stopColor="#3A3020" />
        <Stop offset="35%" stopColor="#1A160E" />
        <Stop offset="70%" stopColor="#0A0806" />
        <Stop offset="100%" stopColor="#000000" />
      </LinearGradient>
      <LinearGradient id="goldLine" x1="0%" y1="0%" x2="100%" y2="100%">
        <Stop offset="0%" stopColor={wire ? COLORS.goldPale : COLORS.goldPale} />
        <Stop offset="45%" stopColor={COLORS.gold} />
        <Stop offset="100%" stopColor={COLORS.bronze} />
      </LinearGradient>
      <LinearGradient id="holoStroke" x1="0%" y1="0%" x2="100%" y2="100%">
        <Stop offset="0%" stopColor="rgba(255,244,208,0.95)" />
        <Stop offset="100%" stopColor="rgba(212,180,90,0.45)" />
      </LinearGradient>
      <LinearGradient id="gradB" x1="0%" y1="0%" x2="100%" y2="100%">
        <Stop offset="0%" stopColor={wire ? COLORS.goldPale : COLORS.goldBright} />
        <Stop offset="100%" stopColor={wire ? COLORS.bronze : COLORS.amber} />
      </LinearGradient>
      <LinearGradient id="gradS" x1="100%" y1="0%" x2="0%" y2="100%">
        <Stop offset="0%" stopColor={wire ? COLORS.goldPale : COLORS.goldBright} />
        <Stop offset="100%" stopColor={wire ? COLORS.bronze : COLORS.bronze} />
      </LinearGradient>
      <LinearGradient id="goldBeam" x1="0%" y1="0%" x2="100%" y2="0%">
        <Stop offset="0%" stopColor="rgba(212,180,90,0)" />
        <Stop offset="50%" stopColor="#F2E2B0" />
        <Stop offset="100%" stopColor="rgba(212,180,90,0)" />
      </LinearGradient>
    </Defs>
  );
}

function LogoPiece({ id, mode }) {
  const wire = mode === 'wireframe';
  const stroke = wire ? 'url(#holoStroke)' : 'url(#goldLine)';
  const sw = wire ? 0.88 : 1.2;

  switch (id) {
    case 'mainHex':
      return (
        <Polygon
          points={MAIN_HEX}
          fill={wire ? 'rgba(212,180,90,0.05)' : 'url(#metalFill)'}
          stroke={stroke}
          strokeWidth={sw}
          strokeDasharray={wire ? '5,3' : undefined}
        />
      );
    case 'innerHex':
      return (
        <Polygon
          points={INNER_HEX}
          fill="none"
          stroke={COLORS.gold}
          strokeWidth={wire ? 0.72 : 0.58}
          strokeOpacity={wire ? 0.88 : 0.72}
          strokeDasharray={wire ? '4,3' : '2,2'}
        />
      );
    case 'diamonds':
      return (
        <G>
          {DIAMONDS.map((pts, i) => (
            <Polygon
              key={i}
              points={pts}
              fill={wire ? 'none' : COLORS.goldBright}
              fillOpacity={wire ? 0 : i < 4 ? 0.92 : 0.62}
              stroke={stroke}
              strokeWidth={wire ? 0.55 : 0}
            />
          ))}
        </G>
      );
    case 'outerRing':
      return (
        <G>
          <Circle
            cx={CX}
            cy={CY}
            r={35}
            fill="none"
            stroke={COLORS.gold}
            strokeWidth={wire ? 0.48 : 0.4}
            strokeOpacity={wire ? 0.7 : 0.55}
            strokeDasharray={wire ? '3,5' : '2,4'}
          />
          <Line x1={40} y1={5} x2={40} y2={9} stroke={stroke} strokeWidth={1} strokeOpacity={0.92} />
          <Line x1={40} y1={71} x2={40} y2={75} stroke={stroke} strokeWidth={1} strokeOpacity={0.92} />
          <Line x1={71} y1={40} x2={75} y2={40} stroke={stroke} strokeWidth={1} strokeOpacity={0.92} />
          <Line x1={5} y1={40} x2={9} y2={40} stroke={stroke} strokeWidth={1} strokeOpacity={0.92} />
          <Line x1={14.4} y1={14.4} x2={17.2} y2={17.2} stroke={stroke} strokeWidth={0.75} strokeOpacity={0.55} />
          <Line x1={62.8} y1={62.8} x2={65.6} y2={65.6} stroke={stroke} strokeWidth={0.75} strokeOpacity={0.55} />
          <Line x1={65.6} y1={14.4} x2={62.8} y2={17.2} stroke={stroke} strokeWidth={0.75} strokeOpacity={0.55} />
          <Line x1={17.2} y1={62.8} x2={14.4} y2={65.6} stroke={stroke} strokeWidth={0.75} strokeOpacity={0.55} />
        </G>
      );
    case 'innerRing':
      return (
        <Circle
          cx={CX}
          cy={CY}
          r={28}
          fill="none"
          stroke={COLORS.gold}
          strokeWidth={wire ? 0.42 : 0.34}
          strokeDasharray={wire ? '2,4' : '1,5'}
          strokeOpacity={wire ? 0.75 : 0.48}
        />
      );
    case 'radar':
      return (
        <G>
          <Line
            x1={40}
            y1={40}
            x2={40}
            y2={11}
            stroke={COLORS.goldBright}
            strokeWidth={wire ? 0.85 : 1}
            strokeOpacity={wire ? 0.85 : 0.7}
            strokeLinecap="round"
            strokeDasharray={wire ? '2,2' : undefined}
          />
          <Circle
            cx={40}
            cy={11}
            r={1.6}
            fill={wire ? 'none' : COLORS.goldBright}
            stroke={wire ? COLORS.gold : 'none'}
            strokeWidth={wire ? 0.8 : 0}
            fillOpacity={wire ? 0 : 0.95}
          />
        </G>
      );
    case 'center':
      return (
        <Circle
          cx={CX}
          cy={CY}
          r={wire ? 2.2 : 2.6}
          fill={wire ? 'none' : COLORS.goldBright}
          stroke={stroke}
          strokeWidth={wire ? 0.9 : 0}
          fillOpacity={wire ? 0 : 1}
        />
      );
    case 'letterB':
      return (
        <SvgText
          x={27}
          y={45}
          fontSize={16}
          fontWeight="bold"
          fontFamily={serifSvg}
          fill={wire ? 'none' : 'url(#gradB)'}
          stroke={stroke}
          strokeWidth={wire ? 0.78 : 0.32}>
          B
        </SvgText>
      );
    case 'letterS':
      return (
        <SvgText
          x={39}
          y={45}
          fontSize={16}
          fontWeight="bold"
          fontFamily={serifSvg}
          fill={wire ? 'none' : 'url(#gradS)'}
          stroke={stroke}
          strokeWidth={wire ? 0.78 : 0}>
          S
        </SvgText>
      );
    default:
      return null;
  }
}

function FragmentSlot({ frag, assembly, lockPulse, materialize }) {
  const motionStyle = useAnimatedStyle(() => {
    const start = frag.delay;
    const span = 0.38;
    const p = interpolate(assembly.value, [start, start + span], [0, 1], Extrapolation.CLAMP);
    const lock = interpolate(p, [0.78, 0.9, 0.96, 1], [0, 1, 1.05, 1]);
    const snap = lock * (1 + lockPulse.value * 0.04);
    return {
      opacity: interpolate(p, [0, 0.12, 1], [0, 0.92, 1], Extrapolation.CLAMP),
      transform: [
        { translateX: interpolate(p, [0, 1], [frag.scatter.x, 0]) },
        { translateY: interpolate(p, [0, 1], [frag.scatter.y, 0]) },
        { rotate: `${interpolate(p, [0, 1], [frag.scatter.r, 0])}deg` },
        { scale: interpolate(p, [0, 0.88, 1], [frag.scatter.s, 1.04, 1]) * snap },
      ],
    };
  });

  const wireLayerStyle = useAnimatedStyle(() => ({
    opacity: (1 - materialize.value) * (0.86 + Math.sin(assembly.value * 20) * 0.08),
  }));

  const solidLayerStyle = useAnimatedStyle(() => ({
    opacity: 0,
  }));

  return (
    <AnimatedView style={[styles.fragment, { width: LOGO_SIZE, height: LOGO_SIZE }, motionStyle]}>
      <AnimatedView style={[StyleSheet.absoluteFill, wireLayerStyle]} pointerEvents="none">
        <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
          <LogoDefs mode="wireframe" />
          <LogoPiece id={frag.id} mode="wireframe" />
        </Svg>
      </AnimatedView>
      <AnimatedView style={[StyleSheet.absoluteFill, solidLayerStyle]} pointerEvents="none">
        <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
          <LogoDefs mode="solid" />
          <LogoPiece id={frag.id} mode="solid" />
        </Svg>
      </AnimatedView>
    </AnimatedView>
  );
}

function EnergyLines({ assembly, lineReveal, materialize }) {
  const style = useAnimatedStyle(() => {
    const holo = 1 - materialize.value * 0.6;
    return {
      opacity:
        interpolate(assembly.value, [0.4, 0.72], [0, 1], Extrapolation.CLAMP) * (0.3 + lineReveal.value * 0.7) * holo,
      transform: [{ scale: 0.9 + lineReveal.value * 0.1 + materialize.value * 0.04 }],
    };
  });

  return (
    <AnimatedView style={[styles.fragment, { width: LOGO_SIZE, height: LOGO_SIZE }, style]} pointerEvents="none">
      <Svg width={LOGO_SIZE} height={LOGO_SIZE} viewBox={`0 0 ${VB} ${VB}`}>
        <Defs>
          <LinearGradient id="goldBeam" x1="0%" y1="0%" x2="100%" y2="0%">
            <Stop offset="0%" stopColor="rgba(212,180,90,0)" />
            <Stop offset="50%" stopColor="#F2E2B0" />
            <Stop offset="100%" stopColor="rgba(212,180,90,0)" />
          </LinearGradient>
        </Defs>
        {CONNECTIONS.map(([a, b]) => {
          const p1 = FRAGMENT_ANCHORS[a];
          const p2 = FRAGMENT_ANCHORS[b];
          if (!p1 || !p2) return null;
          return (
            <Line
              key={`${a}-${b}`}
              x1={p1.x}
              y1={p1.y}
              x2={p2.x}
              y2={p2.y}
              stroke="url(#goldBeam)"
              strokeWidth={0.8}
              strokeDasharray="3,4"
            />
          );
        })}
      </Svg>
    </AnimatedView>
  );
}

function GoldLightSweep({ sweep, materialize }) {
  const brightStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(sweep.value, [0, 1], [-LOGO_SIZE * 0.8, LOGO_SIZE * 0.9]) },
      { skewX: '-6deg' },
    ],
    opacity: interpolate(materialize.value, [0.3, 0.65], [0, 0.75], Extrapolation.CLAMP),
  }));

  const warmStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(sweep.value, [0, 1], [LOGO_SIZE * 0.9, -LOGO_SIZE * 0.8]) },
      { skewX: '6deg' },
    ],
    opacity: interpolate(materialize.value, [0.3, 0.65], [0, 0.55], Extrapolation.CLAMP),
  }));

  const bandH = LOGO_SIZE * 1.25;

  return (
    <View style={[styles.sweepClip, { width: LOGO_SIZE, height: LOGO_SIZE }]} pointerEvents="none">
      <AnimatedView
        style={[styles.sweepBand, { height: bandH, backgroundColor: 'rgba(242,226,176,0.28)' }, brightStyle]}
      />
      <AnimatedView
        style={[styles.sweepBand, { height: bandH, backgroundColor: 'rgba(201,138,46,0.22)' }, warmStyle]}
      />
      <AnimatedView style={[styles.sweepBand, styles.sweepCoreBright, brightStyle]} />
      <AnimatedView style={[styles.sweepBand, styles.sweepCoreWarm, warmStyle]} />
    </View>
  );
}

function EtherealMist({ materialize, glow, camera }) {
  const mistA = useAnimatedStyle(() => ({
    opacity: 0.12 + materialize.value * 0.18 + glow.value * 0.12,
    transform: [
      { scale: 1.4 + camera.value * 0.2 },
      { translateY: interpolate(camera.value, [0, 1], [20, -8]) },
    ],
  }));
  const mistB = useAnimatedStyle(() => ({
    opacity: 0.08 + glow.value * 0.2,
    transform: [{ scale: 1.1 + glow.value * 0.15 }, { rotate: `${camera.value * 12}deg` }],
  }));

  return (
    <>
      <AnimatedView style={[styles.mistOrb, styles.mistOrbLg, mistA]} pointerEvents="none" />
      <AnimatedView style={[styles.mistOrb, styles.mistOrbSm, mistB]} pointerEvents="none" />
    </>
  );
}

function DepthFloor({ materialize, camera }) {
  const style = useAnimatedStyle(() => ({
    opacity: materialize.value * 0.5,
    transform: [
      { scaleX: 0.68 + camera.value * 0.38 + materialize.value * 0.14 },
      { scaleY: 0.32 + materialize.value * 0.18 },
    ],
  }));

  return <AnimatedView style={[styles.depthFloor, style]} pointerEvents="none" />;
}

function LockSparks({ lockPulse, materialize }) {
  const angles = [0, 55, 110, 165, 220, 295];
  const hubStyle = useAnimatedStyle(() => ({
    opacity: materialize.value * lockPulse.value * 0.9,
  }));

  return (
    <AnimatedView style={[styles.sparkHub, hubStyle]} pointerEvents="none">
      {angles.map((deg) => (
        <SparkFlare key={deg} angle={deg} lockPulse={lockPulse} />
      ))}
    </AnimatedView>
  );
}

function SparkFlare({ angle, lockPulse }) {
  const style = useAnimatedStyle(() => ({
    opacity: lockPulse.value * 0.85,
    transform: [
      { rotate: `${angle}deg` },
      { translateX: LOGO_SIZE * 0.42 },
      { scale: 0.3 + lockPulse.value * 1.3 },
    ],
  }));

  return (
    <AnimatedView style={[styles.spark, style]} pointerEvents="none">
      <View style={styles.sparkCore} />
    </AnimatedView>
  );
}

function ParticleField({ assembly, particles, camera }) {
  return particles.map((p, i) => <Particle key={i} p={p} assembly={assembly} camera={camera} />);
}

function Particle({ p, assembly, camera }) {
  const style = useAnimatedStyle(() => {
    const drift = interpolate(assembly.value, [0, 1], [1, 0], Extrapolation.CLAMP);
    const parallax = 1 - p.depth * 0.32;
    const zoom = 0.88 + camera.value * 0.14;
    return {
      opacity: drift * (0.4 + Math.sin((assembly.value + p.phase) * Math.PI * 3) * 0.25) * 0.8,
      transform: [
        { translateX: p.x * drift * parallax },
        { translateY: p.y * drift * parallax },
        { scale: (0.5 + (1 - drift) * 0.5) * zoom * parallax },
      ],
    };
  });

  return (
    <AnimatedView
      style={[
        styles.particle,
        {
          width: p.size,
          height: p.size,
          borderRadius: p.size,
          backgroundColor: p.bright ? COLORS.goldPale : COLORS.gold,
        },
        style,
      ]}
    />
  );
}

function BrandLogoBitmap({ assembly, materialize, glow, camera }) {
  const style = useAnimatedStyle(() => {
    const assemble = assembly.value;
    const mat = materialize.value;
    const breathe = 1 + glow.value * 0.06;
    return {
      opacity: interpolate(assemble, [0, 0.25, 0.55, 1], [0, 0.2, 0.72, 1], Extrapolation.CLAMP) * mat,
      transform: [
        { translateY: interpolate(camera.value, [0, 1], [18, -4]) },
        {
          scale:
            interpolate(assemble, [0, 0.7, 1], [0.68, 0.94, 1], Extrapolation.CLAMP) *
            interpolate(mat, [0, 1], [0.92, 1.04], Extrapolation.CLAMP) *
            breathe,
        },
      ],
    };
  });

  return (
    <AnimatedView style={[styles.brandLogoWrap, { width: LOGO_SIZE, height: LOGO_SIZE }, style]} pointerEvents="none">
      <Image source={BRAND_LOGO} style={styles.brandLogoImg} resizeMode="contain" />
    </AnimatedView>
  );
}

function DepthGrid({ camera }) {
  const style = useAnimatedStyle(() => ({
    opacity: 0.06 + camera.value * 0.08,
    transform: [{ scale: 1.12 - camera.value * 0.06 }, { translateY: camera.value * 16 }],
  }));

  return <AnimatedView style={[styles.depthGrid, style]} pointerEvents="none" />;
}

/**
 * Black & gold ethereal logo splash — stays until `appReady`, then fades to home.
 * @param {{ appReady: boolean, onComplete: () => void }} props
 */
export default function CinematicSplash({ appReady = false, onComplete }) {
  const assembly = useSharedValue(0);
  const materialize = useSharedValue(0);
  const lineReveal = useSharedValue(0);
  const sweep = useSharedValue(0);
  const camera = useSharedValue(0);
  const glow = useSharedValue(0);
  const lockPulse = useSharedValue(0);
  const fade = useSharedValue(1);
  const [animDone, setAnimDone] = useState(false);
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

  const particles = useMemo(
    () =>
      Array.from({ length: 20 }, (_, i) => ({
        x: ((i * 17) % 11 - 5) * (LOGO_SIZE * 0.26),
        y: ((i * 23) % 13 - 6) * (LOGO_SIZE * 0.24),
        size: 1.5 + (i % 4) * 0.5,
        phase: i * 0.09,
        bright: i % 3 === 0,
        depth: (i % 5) / 5,
      })),
    [],
  );

  useEffect(() => {
    SplashScreen.hideAsync().catch(() => {});
  }, []);

  useEffect(() => {
    const wireEnd = START_DELAY_MS + WIRE_ASSEMBLY_MS;
    const matEnd = wireEnd + MATERIALIZE_MS;
    const scanEnd = matEnd + GOLD_SWEEP_MS;

    camera.value = withDelay(
      START_DELAY_MS,
      withTiming(1, { duration: ANIM_DONE_MS, easing: Easing.inOut(Easing.cubic) }),
    );

    assembly.value = withDelay(
      START_DELAY_MS,
      withTiming(1, { duration: WIRE_ASSEMBLY_MS, easing: Easing.out(Easing.cubic) }),
    );

    lineReveal.value = withDelay(wireEnd - 500, withTiming(1, { duration: 420, easing: Easing.inOut(Easing.quad) }));

    materialize.value = withDelay(
      wireEnd,
      withTiming(1, { duration: MATERIALIZE_MS, easing: Easing.inOut(Easing.cubic) }),
    );

    sweep.value = withDelay(
      wireEnd + 180,
      withTiming(1, { duration: GOLD_SWEEP_MS, easing: Easing.inOut(Easing.quad) }),
    );

    lockPulse.value = withDelay(
      wireEnd + 100,
      withRepeat(
        withSequence(withTiming(1, { duration: 100 }), withTiming(0, { duration: 140 })),
        5,
        false,
      ),
    );

    glow.value = withDelay(
      scanEnd,
      withTiming(1, { duration: 480, easing: Easing.out(Easing.quad) }),
    );

    const doneTimer = setTimeout(() => setAnimDone(true), ANIM_DONE_MS);
    return () => clearTimeout(doneTimer);
  }, [assembly, camera, glow, lineReveal, lockPulse, materialize, sweep]);

  useEffect(() => {
    const capTimer = setTimeout(() => beginFade(), SPLASH_MAX_MS);
    return () => clearTimeout(capTimer);
  }, [beginFade]);

  useEffect(() => {
    if (!animDone) return;
    if (appReady) {
      beginFade();
      return;
    }
    glow.value = withRepeat(
      withSequence(withTiming(1, { duration: 1100 }), withTiming(0.82, { duration: 1100 })),
      -1,
      true,
    );
  }, [animDone, appReady, beginFade, glow]);

  const rootStyle = useAnimatedStyle(() => ({
    opacity: fade.value,
  }));

  const cameraStageStyle = useAnimatedStyle(() => {
    const z = camera.value;
    return {
      transform: [
        { perspective: 920 },
        { translateY: interpolate(z, [0, 1], [32, -8]) },
        { scale: interpolate(z, [0, 0.5, 1], [0.86, 0.97, 1.08]) },
      ],
    };
  });

  const logoLiftStyle = useAnimatedStyle(() => ({
    transform: [
      { translateY: interpolate(materialize.value, [0, 1], [10, -6]) },
      { scale: interpolate(materialize.value, [0, 1], [0.95, 1.03]) * (1 + glow.value * 0.04) },
    ],
  }));

  const haloStyle = useAnimatedStyle(() => ({
    opacity: 0.1 + glow.value * 0.55 + materialize.value * 0.15,
    transform: [{ scale: 0.8 + glow.value * 0.28 + camera.value * 0.08 }],
  }));

  const ringStyle = useAnimatedStyle(() => ({
    opacity: 0.18 + materialize.value * 0.5 + glow.value * 0.4,
    transform: [{ scale: 0.86 + materialize.value * 0.16 + glow.value * 0.08 }],
  }));

  const holoGridStyle = useAnimatedStyle(() => ({
    opacity: (1 - materialize.value) * 0.28,
  }));

  return (
    <AnimatedView style={[styles.root, rootStyle]}>
      <View style={styles.bgBase} />
      <View style={styles.bgWarmGlow} />
      <DepthGrid camera={camera} />
      <AnimatedView style={[styles.bgHoloGrid, holoGridStyle]} pointerEvents="none" />
      <View style={styles.vignetteTop} />
      <View style={styles.vignetteBottom} />

      <AnimatedView style={[styles.stage, cameraStageStyle]}>
        <EtherealMist materialize={materialize} glow={glow} camera={camera} />
        <ParticleField assembly={assembly} particles={particles} camera={camera} />

        <AnimatedView
          style={[styles.halo, { width: LOGO_SIZE * 1.65, height: LOGO_SIZE * 1.65, borderRadius: LOGO_SIZE }, haloStyle]}
        />
        <AnimatedView
          style={[
            styles.goldRing,
            { width: LOGO_SIZE * 1.16, height: LOGO_SIZE * 1.16, borderRadius: LOGO_SIZE },
            ringStyle,
          ]}
        />

        <AnimatedView style={[styles.logoLift, logoLiftStyle]}>
          <DepthFloor materialize={materialize} camera={camera} />
          <View style={[styles.logoCluster, { width: LOGO_SIZE, height: LOGO_SIZE }]}>
            <EnergyLines assembly={assembly} lineReveal={lineReveal} materialize={materialize} />
            {FRAGMENTS.map((frag) => (
              <FragmentSlot
                key={frag.id}
                frag={frag}
                assembly={assembly}
                lockPulse={lockPulse}
                materialize={materialize}
              />
            ))}
            <BrandLogoBitmap assembly={assembly} materialize={materialize} glow={glow} camera={camera} />
            <GoldLightSweep sweep={sweep} materialize={materialize} />
            <LockSparks lockPulse={lockPulse} materialize={materialize} />
          </View>
        </AnimatedView>
      </AnimatedView>
    </AnimatedView>
  );
}

export const CINEMATIC_SPLASH_MS = SPLASH_MAX_MS;

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: COLORS.black,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bgBase: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: COLORS.black,
  },
  bgWarmGlow: {
    position: 'absolute',
    top: SCREEN_H * 0.22,
    alignSelf: 'center',
    width: SCREEN_W * 0.9,
    height: SCREEN_W * 0.9,
    borderRadius: SCREEN_W,
    backgroundColor: 'rgba(122,92,24,0.07)',
  },
  bgHoloGrid: {
    ...StyleSheet.absoluteFillObject,
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.08)',
  },
  depthGrid: {
    ...StyleSheet.absoluteFillObject,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: 'rgba(122,92,24,0.05)',
    backgroundColor: 'rgba(5,4,3,0.5)',
  },
  vignetteTop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: SCREEN_H * 0.4,
    backgroundColor: 'rgba(0,0,0,0.72)',
  },
  vignetteBottom: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: SCREEN_H * 0.32,
    backgroundColor: 'rgba(0,0,0,0.68)',
  },
  stage: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoLift: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoCluster: {
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    borderRadius: LOGO_SIZE * 0.2,
  },
  fragment: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
  },
  halo: {
    position: 'absolute',
    backgroundColor: 'rgba(212,180,90,0.1)',
    shadowColor: COLORS.gold,
    shadowOpacity: 0.85,
    shadowRadius: 44,
    shadowOffset: { width: 0, height: 0 },
  },
  goldRing: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: 'rgba(242,226,176,0.35)',
    backgroundColor: 'transparent',
    shadowColor: COLORS.goldBright,
    shadowOpacity: 0.45,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 0 },
  },
  mistOrb: {
    position: 'absolute',
    borderRadius: 999,
    backgroundColor: 'rgba(212,180,90,0.12)',
  },
  mistOrbLg: {
    width: LOGO_SIZE * 2.2,
    height: LOGO_SIZE * 2.2,
    shadowColor: COLORS.gold,
    shadowOpacity: 0.35,
    shadowRadius: 60,
    shadowOffset: { width: 0, height: 0 },
  },
  mistOrbSm: {
    width: LOGO_SIZE * 1.4,
    height: LOGO_SIZE * 1.4,
    backgroundColor: 'rgba(242,226,176,0.06)',
  },
  sweepClip: {
    ...StyleSheet.absoluteFillObject,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sweepBand: {
    position: 'absolute',
    width: 24,
    borderRadius: 2,
    shadowColor: COLORS.goldBright,
    shadowOpacity: 0.8,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 0 },
  },
  sweepCoreBright: {
    width: 5,
    backgroundColor: 'rgba(255,244,208,0.9)',
  },
  sweepCoreWarm: {
    width: 4,
    backgroundColor: 'rgba(201,138,46,0.85)',
    shadowColor: COLORS.amber,
  },
  depthFloor: {
    position: 'absolute',
    bottom: -LOGO_SIZE * 0.18,
    width: LOGO_SIZE * 1.12,
    height: LOGO_SIZE * 0.22,
    borderRadius: LOGO_SIZE,
    backgroundColor: 'rgba(212,180,90,0.06)',
    shadowColor: '#000',
    shadowOpacity: 0.9,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 10 },
  },
  particle: {
    position: 'absolute',
    shadowColor: COLORS.gold,
    shadowOpacity: 0.85,
    shadowRadius: 5,
    shadowOffset: { width: 0, height: 0 },
  },
  sparkHub: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  spark: {
    position: 'absolute',
    width: 10,
    height: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sparkCore: {
    width: 10,
    height: 2,
    borderRadius: 1,
    backgroundColor: COLORS.goldPale,
    shadowColor: COLORS.goldBright,
    shadowOpacity: 1,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 },
  },
  brandLogoWrap: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 12,
  },
  brandLogoImg: {
    width: '100%',
    height: '100%',
  },
});
