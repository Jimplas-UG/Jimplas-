import React, { useCallback, useEffect } from 'react';
import { Platform, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useFrameCallback,
  useSharedValue,
} from 'react-native-reanimated';

const THEME = {
  barBg: '#0C0A07',
  barBorder: '#2A2418',
  text: '#E9E0C8',
  textMuted: '#7A6C45',
  glow: 'rgba(212, 180, 90, 0.42)',
};

const DOT_COLORS = ['#D4B45A', '#FF3D57', '#FFB300'];

const FALLBACK_TICKER_ITEMS = [
  'GEOPOLITICAL: HIGH',
  'NFP BLACKOUT: MAY 8',
  'ATR VOLATILITY: ELEVATED',
  'FED WATCH: ACTIVE',
  'LIQUIDITY RISK: MODERATE',
];

const TAPE_FONT = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  default: 'monospace',
});

function AlertDot({ color }) {
  return (
    <View style={[styles.dot, { backgroundColor: color }]}>
      <View style={[styles.dotInner, { backgroundColor: color }]} />
    </View>
  );
}

function TickerSegment({ fontSize, lineHeight, labels }) {
  return (
    <View style={styles.segment}>
      {labels.map((label, i) => (
        <View key={`${label}-${i}`} style={styles.item}>
          <AlertDot color={DOT_COLORS[i % DOT_COLORS.length]} />
          <Text
            style={[
              styles.itemText,
              { fontSize, lineHeight, textShadowColor: THEME.glow, fontFamily: TAPE_FONT },
            ]}
            numberOfLines={1}>
            {label}
          </Text>
          <Text style={[styles.sep, { fontSize: fontSize - 1, fontFamily: TAPE_FONT }]}>·</Text>
        </View>
      ))}
    </View>
  );
}

/**
 * Infinite horizontal tape (RTL) for geopolitical / market-style alerts.
 * Hold to pause; release to resume. Uses Reanimated frame loop for seamless wrap.
 *
 * @param {object} [style] — outer container style
 * @param {number} [loopDurationMs=21000] — time (ms) to scroll one full strip (~18–25s recommended)
 * @param {string[]} [items] — when set, tape shows these strings (e.g. live engine risk strip); else fallback demo labels
 */
export default function GeoPoliticalTicker({ style, loopDurationMs = 21000, items }) {
  const { width: windowWidth } = useWindowDimensions();
  const fontSize = windowWidth < 360 ? 10.5 : 11.5;
  const lineHeight = fontSize + 6;

  const labels =
    Array.isArray(items) && items.length > 0 ? items.filter((s) => typeof s === 'string' && s.trim().length > 0) : FALLBACK_TICKER_ITEMS;

  const translateX = useSharedValue(0);
  const contentWidth = useSharedValue(0);
  const paused = useSharedValue(false);
  const loopMsSv = useSharedValue(loopDurationMs);

  useEffect(() => {
    loopMsSv.value = loopDurationMs;
  }, [loopDurationMs, loopMsSv]);

  const onStripLayout = useCallback(
    (e) => {
      const w = e.nativeEvent.layout.width;
      if (w > 0) {
        contentWidth.value = w;
      }
    },
    [contentWidth]
  );

  const onFrame = useCallback((frame) => {
    'worklet';
    const w = contentWidth.value;
    if (w <= 0) return;
    if (paused.value) return;

    const dt = frame.timeSincePreviousFrame;
    if (dt == null || dt <= 0 || dt > 120) return;

    const loopMs = Math.max(4000, loopMsSv.value);
    const pxPerMs = w / loopMs;
    let next = translateX.value - pxPerMs * dt;
    while (next <= -w) {
      next += w;
    }
    translateX.value = next;
  }, []);

  useFrameCallback(onFrame, true);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: translateX.value }],
  }));

  const onPressIn = useCallback(() => {
    paused.value = true;
  }, [paused]);

  const onPressOut = useCallback(() => {
    paused.value = false;
  }, [paused]);

  return (
    <View style={[styles.outer, style]}>
      <View style={styles.clip}>
        <Animated.View style={[styles.track, animatedStyle]}>
          <View onLayout={onStripLayout} style={styles.measureWrap} collapsable={false}>
            <TickerSegment fontSize={fontSize} lineHeight={lineHeight} labels={labels} />
          </View>
          <TickerSegment key="__dup" fontSize={fontSize} lineHeight={lineHeight} labels={labels} />
        </Animated.View>
      </View>
      <Pressable
        accessibilityRole="adjustable"
        accessibilityLabel="Geopolitical alert ticker. Hold to pause."
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        pressRetentionOffset={{ top: 24, left: 40, bottom: 24, right: 40 }}
        style={styles.touchShield}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  outer: {
    width: '100%',
    paddingVertical: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: THEME.barBorder,
    backgroundColor: THEME.barBg,
  },
  clip: {
    overflow: 'hidden',
    justifyContent: 'center',
  },
  track: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'nowrap',
  },
  measureWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
  },
  segment: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingRight: 28,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 20,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    marginRight: 8,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 3,
    elevation: 2,
  },
  dotInner: {
    width: 5,
    height: 5,
    borderRadius: 3,
    opacity: 0.95,
  },
  itemText: {
    color: THEME.text,
    fontWeight: '600',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 10,
  },
  sep: {
    color: THEME.textMuted,
    marginLeft: 10,
    fontWeight: '300',
    opacity: 0.85,
  },
  touchShield: {
    ...StyleSheet.absoluteFillObject,
  },
});
