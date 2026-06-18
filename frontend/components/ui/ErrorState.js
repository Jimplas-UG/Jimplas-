import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { radius, spacing, typography } from '../../theme/designTokens';

export default function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
  retryLabel = 'Retry',
  compact = false,
}) {
  const { colors: C, styles: appStyles } = useBilshenzTheme();

  return (
    <View
      style={[
        styles.wrap,
        compact ? styles.compact : null,
        { backgroundColor: C.redD, borderColor: 'rgba(255,61,87,0.35)' },
      ]}
      accessibilityRole="alert">
      <Text style={[styles.title, { color: C.red }]}>{title}</Text>
      {message ? (
        <Text style={[styles.msg, { color: C.text }]} numberOfLines={compact ? 2 : 5}>
          {message}
        </Text>
      ) : null}
      {onRetry ? (
        <Pressable
          onPress={onRetry}
          style={({ pressed }) => [
            appStyles.psSegChip,
            styles.retry,
            { borderColor: C.red, backgroundColor: pressed ? C.panel2 : C.panel },
          ]}
          accessibilityRole="button"
          accessibilityLabel={retryLabel}>
          <Text style={[styles.retryTxt, { color: C.goldL }]}>{retryLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginVertical: spacing.sm,
  },
  compact: {
    padding: spacing.md,
  },
  title: {
    ...typography.label,
    marginBottom: spacing.xs,
  },
  msg: {
    ...typography.body,
    lineHeight: 18,
  },
  retry: {
    marginTop: spacing.md,
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.lg,
    minHeight: 40,
    justifyContent: 'center',
  },
  retryTxt: {
    ...typography.label,
    fontSize: 11,
  },
});
