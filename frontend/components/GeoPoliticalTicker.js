import React, { useCallback, useEffect, useRef } from 'react';
import {
  Animated,
  Easing,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';

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

function TickerSegment({ fontSize, lineHeight, labels, tapeTheme }) {
  return (
    <View style={styles.segment}>
      {labels.map((label, i) => (
        <View key={`${label}-${i}`} style={styles.item}>
          <AlertDot color={DOT_COLORS[i % DOT_COLORS.length]} />
          <Text
            style={[
              styles.itemText,
              {
                fontSize,
                lineHeight,
                color: tapeTheme.text,
                textShadowColor: tapeTheme.glow,
                fontFamily: TAPE_FONT,
              },
            ]}
            numberOfLines={1}>
            {label}
          </Text>
          <Text
            style={[
              styles.sep,
              { fontSize: fontSize - 1, color: tapeTheme.textMuted, fontFamily: TAPE_FONT },
            ]}>
            ·
          </Text>
        </View>
      ))}
    </View>
  );
}

/**
 * Infinite horizontal tape (RTL) for geopolitical / market-style alerts.
 * Hold to pause; release to resume. Uses RN Animated (Expo Go–safe on Android).
 *
 * @param {object} [style] — outer container style
 * @param {number} [loopDurationMs=21000] — time (ms) to scroll one full strip
 * @param {string[]} [items] — when set, tape shows these strings; else fallback demo labels
 */
export default function GeoPoliticalTicker({ style, loopDurationMs = 21000, items, tapeTheme }) {
  const theme = tapeTheme ?? THEME;
  const { width: windowWidth } = useWindowDimensions();
  const fontSize = windowWidth < 360 ? 10.5 : 11.5;
  const lineHeight = fontSize + 6;

  const labels =
    Array.isArray(items) && items.length > 0
      ? items.filter((s) => typeof s === 'string' && s.trim().length > 0)
      : FALLBACK_TICKER_ITEMS;

  const labelsKey = labels.join('|');

  const translateX = useRef(new Animated.Value(0)).current;
  const segmentWRef = useRef(0);
  const lastLayoutWRef = useRef(0);
  const loopRef = useRef(null);
  const pausedRef = useRef(false);
  const durationRef = useRef(Math.max(4000, loopDurationMs));

  const stopMarquee = useCallback(() => {
    if (loopRef.current) {
      loopRef.current.stop();
      loopRef.current = null;
    }
  }, []);

  const startMarquee = useCallback(
    (segmentW) => {
      if (segmentW <= 0) return;
      stopMarquee();
      segmentWRef.current = segmentW;
      translateX.setValue(0);
      const duration = durationRef.current;
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(translateX, {
            toValue: -segmentW,
            duration,
            easing: Easing.linear,
            useNativeDriver: true,
          }),
          Animated.timing(translateX, {
            toValue: 0,
            duration: 0,
            useNativeDriver: true,
          }),
        ])
      );
      loopRef.current = loop;
      if (!pausedRef.current) loop.start();
    },
    [stopMarquee, translateX]
  );

  useEffect(() => {
    lastLayoutWRef.current = 0;
  }, [labelsKey]);

  useEffect(() => {
    durationRef.current = Math.max(4000, loopDurationMs);
    if (segmentWRef.current > 0 && !pausedRef.current) {
      startMarquee(segmentWRef.current);
    }
  }, [loopDurationMs, startMarquee]);

  useEffect(() => () => stopMarquee(), [stopMarquee]);

  const onStripLayout = useCallback(
    (e) => {
      const w = e.nativeEvent.layout.width;
      if (w <= 0) return;
      if (Math.abs(w - lastLayoutWRef.current) < 2) return;
      lastLayoutWRef.current = w;
      startMarquee(w);
    },
    [startMarquee]
  );

  const onPressIn = useCallback(() => {
    pausedRef.current = true;
    stopMarquee();
  }, [stopMarquee]);

  const onPressOut = useCallback(() => {
    pausedRef.current = false;
    if (segmentWRef.current > 0) startMarquee(segmentWRef.current);
  }, [startMarquee]);

  return (
    <View
      style={[
        styles.outer,
        { borderColor: theme.barBorder, backgroundColor: theme.barBg },
        style,
      ]}>
      <View style={styles.clip}>
        <Animated.View style={[styles.track, { transform: [{ translateX }] }]}>
          <View onLayout={onStripLayout} style={styles.measureWrap} collapsable={false}>
            <TickerSegment fontSize={fontSize} lineHeight={lineHeight} labels={labels} tapeTheme={theme} />
          </View>
          <TickerSegment key="__dup" fontSize={fontSize} lineHeight={lineHeight} labels={labels} tapeTheme={theme} />
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
    marginLeft: 10,
    fontWeight: '300',
    opacity: 0.85,
  },
  touchShield: {
    ...StyleSheet.absoluteFillObject,
  },
});
