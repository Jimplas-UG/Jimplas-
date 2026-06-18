import React, { useEffect, useRef } from 'react';
import { Animated, StyleSheet, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { spacing, radius } from '../../theme/designTokens';

function PulseBlock({ style, opacityAnim }) {
  return (
    <Animated.View
      style={[
        styles.block,
        style,
        {
          opacity: opacityAnim.interpolate({
            inputRange: [0, 1],
            outputRange: [0.35, 0.75],
          }),
        },
      ]}
    />
  );
}

export default function SkeletonLoader({ rows = 3, height = 14, gap = spacing.sm, style }) {
  const { colors: C } = useBilshenzTheme();
  const anim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(anim, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(anim, { toValue: 0, duration: 900, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [anim]);

  return (
    <View style={[styles.wrap, style]} accessibilityRole="progressbar" accessibilityLabel="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <PulseBlock
          key={i}
          opacityAnim={anim}
          style={{
            height,
            width: i === rows - 1 ? '62%' : '100%',
            marginBottom: i < rows - 1 ? gap : 0,
            backgroundColor: C.panel2,
            borderColor: C.border,
          }}
        />
      ))}
    </View>
  );
}

export function SkeletonCard({ lines = 4, style }) {
  return (
    <View style={style}>
      <SkeletonLoader rows={lines} height={12} gap={10} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    width: '100%',
  },
  block: {
    borderRadius: radius.sm,
    borderWidth: StyleSheet.hairlineWidth,
  },
});
