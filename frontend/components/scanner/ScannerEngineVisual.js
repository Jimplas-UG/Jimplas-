import React, { useEffect, useMemo, useState } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, Line, LinearGradient, RadialGradient, Stop } from 'react-native-svg';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { PilotPill } from '../pilot/PilotUI';
import { radius, spacing } from '../../theme/designTokens';

const FIELD_W = 168;
const FIELD_H = 108;
const FALLBACK_COINS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'AVAX', 'LINK', 'ADA', 'MATIC'];

const BUBBLE_LAYOUT = [
  { x: 8, y: 12, size: 34, drift: 5 },
  { x: 42, y: 4, size: 28, drift: 4 },
  { x: 78, y: 18, size: 32, drift: 6 },
  { x: 112, y: 8, size: 26, drift: 3 },
  { x: 136, y: 32, size: 30, drift: 5 },
  { x: 22, y: 48, size: 36, drift: 7 },
  { x: 58, y: 56, size: 40, drift: 4 },
  { x: 98, y: 52, size: 32, drift: 6 },
  { x: 128, y: 68, size: 28, drift: 3 },
  { x: 6, y: 72, size: 26, drift: 4 },
];

function bubbleHot(row) {
  if (!row) return false;
  const vals = [row.pct3m, row.pct5m, row.pct15m, row.pctGain].map(Number).filter((v) => Number.isFinite(v));
  if (!vals.length) return false;
  return Math.max(...vals.map((v) => Math.abs(v))) >= 1.2;
}

function bubbleTone(row, hot) {
  if (!row) return { ring: '#7C6CF0', glow: 'rgba(124,108,240,0.35)', text: '#E8E4FF' };
  const pct = Number(row.pct5m ?? row.pct3m ?? 0);
  if (hot && pct > 0) return { ring: '#34D399', glow: 'rgba(52,211,153,0.45)', text: '#D1FAE5' };
  if (hot && pct < 0) return { ring: '#F87171', glow: 'rgba(248,113,113,0.4)', text: '#FECACA' };
  if (hot) return { ring: '#38BDF8', glow: 'rgba(56,189,248,0.4)', text: '#E0F2FE' };
  return { ring: '#8B5CF6', glow: 'rgba(139,92,246,0.28)', text: '#DDD6FE' };
}

function CoinBubble({ symbol, row, layout, index, ready }) {
  const hot = bubbleHot(row);
  const tone = bubbleTone(row, hot);
  const scale = useSharedValue(0);
  const ty = useSharedValue(0);
  const pulse = useSharedValue(1);

  useEffect(() => {
    const popDelay = index * 90 + (ready ? 0 : 400);
    scale.value = withDelay(popDelay, withSpring(1, { damping: 11, stiffness: 140, mass: 0.7 }));
    ty.value = withDelay(
      popDelay,
      withRepeat(
        withSequence(
          withTiming(-layout.drift, { duration: 1600 + index * 180, easing: Easing.inOut(Easing.sin) }),
          withTiming(layout.drift, { duration: 1600 + index * 180, easing: Easing.inOut(Easing.sin) }),
        ),
        -1,
        true,
      ),
    );
    if (hot) {
      pulse.value = withRepeat(
        withSequence(withTiming(1.08, { duration: 700 }), withTiming(1, { duration: 700 })),
        -1,
        true,
      );
    }
  }, [hot, index, layout.drift, ready, pulse, scale, ty]);

  const anim = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value * pulse.value }, { translateY: ty.value }],
  }));

  const label = String(symbol || '?').slice(0, 5);
  const fontSize = layout.size > 34 ? 10 : layout.size > 30 ? 9 : 8;

  return (
    <Animated.View
      style={[
        st.bubble,
        {
          left: layout.x,
          top: layout.y,
          width: layout.size,
          height: layout.size,
          borderRadius: layout.size / 2,
          borderColor: tone.ring,
          shadowColor: tone.ring,
          backgroundColor: 'rgba(12,16,28,0.82)',
        },
        anim,
      ]}>
      <View
        style={[
          st.bubbleInner,
          {
            width: layout.size - 6,
            height: layout.size - 6,
            borderRadius: (layout.size - 6) / 2,
            backgroundColor: tone.glow,
          },
        ]}>
        <Text style={[st.bubbleText, { color: tone.text, fontSize }]} numberOfLines={1}>
          {label}
        </Text>
        {hot ? <View style={[st.hotDot, { backgroundColor: tone.ring }]} /> : null}
      </View>
    </Animated.View>
  );
}

function ScanField({ bubbles, ready, ms, activity }) {
  const sweep = (ms / 2400) % 1;
  const ringPulse = 0.35 + activity * 0.45;

  return (
    <View style={st.field}>
      <Svg width={FIELD_W} height={FIELD_H} style={StyleSheet.absoluteFill}>
        <Defs>
          <RadialGradient id="fieldGlow" cx="50%" cy="50%" r="55%">
            <Stop offset="0%" stopColor="#7C6CF0" stopOpacity={0.18} />
            <Stop offset="55%" stopColor="#06B6D4" stopOpacity={0.06} />
            <Stop offset="100%" stopColor="#000" stopOpacity={0} />
          </RadialGradient>
          <LinearGradient id="sweepGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <Stop offset="0%" stopColor="#38BDF8" stopOpacity={0} />
            <Stop offset="50%" stopColor="#A78BFA" stopOpacity={0.55} />
            <Stop offset="100%" stopColor="#22D3EE" stopOpacity={0} />
          </LinearGradient>
        </Defs>

        <Circle cx={FIELD_W / 2} cy={FIELD_H / 2} r={FIELD_H * 0.48} fill="url(#fieldGlow)" />

        {[22, 38, 54].map((r) => (
          <Circle
            key={r}
            cx={FIELD_W / 2}
            cy={FIELD_H / 2}
            r={r}
            fill="none"
            stroke="#7C6CF0"
            strokeWidth={0.5}
            strokeOpacity={0.12 + ringPulse * 0.08}
          />
        ))}

        {Array.from({ length: 8 }, (_, i) => {
          const a = (i / 8) * Math.PI * 2;
          const x2 = FIELD_W / 2 + Math.cos(a) * 58;
          const y2 = FIELD_H / 2 + Math.sin(a) * 48;
          return (
            <Line
              key={`spoke-${i}`}
              x1={FIELD_W / 2}
              y1={FIELD_H / 2}
              x2={x2}
              y2={y2}
              stroke="#94A3B8"
              strokeWidth={0.35}
              strokeOpacity={0.08}
            />
          );
        })}

        <Line
          x1={FIELD_W / 2}
          y1={FIELD_H / 2}
          x2={FIELD_W / 2 + Math.cos(sweep * Math.PI * 2 - Math.PI / 2) * 62}
          y2={FIELD_H / 2 + Math.sin(sweep * Math.PI * 2 - Math.PI / 2) * 50}
          stroke="url(#sweepGrad)"
          strokeWidth={2}
          strokeLinecap="round"
          strokeOpacity={0.65}
        />

        <Circle
          cx={FIELD_W / 2}
          cy={FIELD_H / 2}
          r={3.5}
          fill="#38BDF8"
          fillOpacity={0.5 + ringPulse * 0.35}
        />
        <Circle cx={FIELD_W / 2} cy={FIELD_H / 2} r={1.6} fill="#F0ABFC" fillOpacity={0.9} />
      </Svg>

      <View style={st.reticle} pointerEvents="none">
        <View style={[st.reticleRing, { opacity: 0.25 + ringPulse * 0.2 }]} />
        <View style={st.reticleCrossH} />
        <View style={st.reticleCrossV} />
      </View>

      {bubbles.map((b, i) => (
        <CoinBubble key={`${b.symbol}-${i}`} symbol={b.symbol} row={b.row} layout={b.layout} index={i} ready={ready} />
      ))}

      <View style={st.fieldScan} pointerEvents="none">
        <View
          style={[
            st.fieldScanBar,
            {
              opacity: 0.2 + activity * 0.25,
              transform: [{ translateX: sweep * FIELD_W - 20 }],
            },
          ]}
        />
      </View>
    </View>
  );
}

/**
 * Futuristic entry scanner — coin bubbles drift in a live search field.
 */
export default function ScannerEngineVisual({ ready, execOn, connected, pulse = 0.5, rows = [] }) {
  const { colors: C } = useBilshenzTheme();
  const [tick, setTick] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 250);
    return () => clearInterval(id);
  }, []);

  const ms = tick;
  const breathe = 0.5 + ((Math.sin((ms / 1200) * Math.PI * 2) + 1) / 2) * 0.5;
  const activity = Math.min(1, Math.max(0.15, pulse * breathe));

  const statusLabel = !connected ? 'Link required' : !ready ? 'Indexing' : execOn ? 'Hunting' : 'Env halt';
  const statusOk = connected && ready && execOn;

  const huntLine = useMemo(() => {
    if (!connected) return 'Connect Binance to start scanning for entries';
    if (!ready) return 'Mapping USDT-M movers into the search field';
    if (execOn) return 'Qualified bubbles surface · execution armed on signal';
    return 'Scanner live · set SCANNER_EXEC=1 on server to arm orders';
  }, [connected, ready, execOn]);

  const bubbles = useMemo(() => {
    const movers = [...(rows || [])].slice(0, BUBBLE_LAYOUT.length);
    return BUBBLE_LAYOUT.map((layout, i) => {
      const row = movers[i];
      const symbol = row?.coin || row?.symbol?.replace(/USDT$/i, '') || FALLBACK_COINS[i % FALLBACK_COINS.length];
      return { layout, row, symbol };
    });
  }, [rows]);

  const hotCount = bubbles.filter((b) => bubbleHot(b.row)).length;

  return (
    <View style={[st.wrap, { backgroundColor: '#070A12', borderColor: 'rgba(56,189,248,0.22)' }]}>
      <View style={st.row}>
        <ScanField bubbles={bubbles} ready={ready} ms={ms} activity={activity} />

        <View style={st.copy}>
          <Text style={st.eyebrow}>ENTRY SCANNER · LIVE SEARCH</Text>
          <Text style={[st.title, { color: C.text }]} numberOfLines={1}>
            Bubble hunt
          </Text>
          <Text style={[st.sub, { color: C.dim2 }]} numberOfLines={2}>
            {huntLine}
          </Text>
          {ready && hotCount > 0 ? (
            <Text style={[st.hotHint, { color: C.teal }]}>
              {hotCount} active {hotCount === 1 ? 'target' : 'targets'} in field
            </Text>
          ) : null}
          <View style={st.pills}>
            <PilotPill label={statusLabel} ok={statusOk} warn={connected && !statusOk} accent={statusOk} />
            {connected ? (
              <PilotPill label={execOn ? 'Armed' : 'Halted'} ok={execOn} warn={!execOn} accent={execOn} />
            ) : null}
          </View>
        </View>
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    borderRadius: radius.lg,
    borderWidth: 1,
    marginBottom: spacing.md,
    overflow: 'hidden',
    ...Platform.select({
      ios: {
        shadowColor: '#38BDF8',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.18,
        shadowRadius: 14,
      },
      android: { elevation: 4 },
      default: {},
    }),
  },
  row: {
    flexDirection: 'row',
    alignItems: 'stretch',
    minHeight: FIELD_H + 12,
  },
  field: {
    width: FIELD_W,
    height: FIELD_H + 12,
    overflow: 'hidden',
    borderRightWidth: 1,
    borderRightColor: 'rgba(56,189,248,0.1)',
    backgroundColor: '#050810',
  },
  fieldScan: {
    ...StyleSheet.absoluteFillObject,
    overflow: 'hidden',
  },
  fieldScanBar: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 28,
    backgroundColor: 'rgba(167,139,250,0.14)',
  },
  reticle: {
    position: 'absolute',
    left: FIELD_W / 2 - 18,
    top: FIELD_H / 2 - 18,
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
  },
  reticleRing: {
    position: 'absolute',
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#38BDF8',
  },
  reticleCrossH: {
    position: 'absolute',
    width: 36,
    height: 1,
    backgroundColor: 'rgba(56,189,248,0.35)',
  },
  reticleCrossV: {
    position: 'absolute',
    width: 1,
    height: 36,
    backgroundColor: 'rgba(56,189,248,0.35)',
  },
  bubble: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.2,
    ...Platform.select({
      ios: { shadowOffset: { width: 0, height: 0 }, shadowOpacity: 0.55, shadowRadius: 8 },
      android: { elevation: 3 },
      default: {},
    }),
  },
  bubbleInner: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  bubbleText: {
    fontWeight: '800',
    letterSpacing: 0.3,
    textAlign: 'center',
  },
  hotDot: {
    position: 'absolute',
    top: 3,
    right: 3,
    width: 5,
    height: 5,
    borderRadius: 3,
  },
  copy: {
    flex: 1,
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    minWidth: 0,
  },
  eyebrow: {
    fontSize: 8,
    fontWeight: '800',
    letterSpacing: 1.4,
    color: '#67E8F9',
    marginBottom: 2,
  },
  title: {
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 0.2,
  },
  sub: {
    fontSize: 10,
    lineHeight: 14,
    marginTop: 3,
  },
  hotHint: {
    fontSize: 9,
    fontWeight: '700',
    marginTop: 4,
    letterSpacing: 0.3,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: spacing.sm,
  },
});
