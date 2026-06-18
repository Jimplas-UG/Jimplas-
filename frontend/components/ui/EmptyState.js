import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { radius, spacing, typography } from '../../theme/designTokens';

export default function EmptyState({ title = 'No data', message, icon = '—' }) {
  const { colors: C } = useBilshenzTheme();

  return (
    <View style={[styles.wrap, { borderColor: C.border, backgroundColor: C.panel }]} accessibilityRole="text">
      <Text style={[styles.icon, { color: C.dim }]}>{icon}</Text>
      <Text style={[styles.title, { color: C.goldL }]}>{title}</Text>
      {message ? <Text style={[styles.msg, { color: C.dim }]}>{message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.xl,
    alignItems: 'center',
    marginVertical: spacing.sm,
  },
  icon: {
    fontSize: 28,
    marginBottom: spacing.sm,
  },
  title: {
    ...typography.label,
    marginBottom: spacing.xs,
  },
  msg: {
    ...typography.caption,
    textAlign: 'center',
    lineHeight: 16,
  },
});
