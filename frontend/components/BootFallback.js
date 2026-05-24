import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import StaticHexLogo from './logo/StaticHexLogo';

/**
 * Minimal shell when main desk UI fails to mount — avoids permanent black screen.
 */
export default function BootFallback({ message, onRetry }) {
  return (
    <View style={styles.root}>
      <StaticHexLogo size={96} />
      <Text style={styles.title}>Bilshenz</Text>
      <Text style={styles.msg}>{message || 'Starting desk…'}</Text>
      {onRetry ? (
        <Pressable style={styles.btn} onPress={onRetry}>
          <Text style={styles.btnText}>Retry</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#100E0A',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  title: {
    marginTop: 12,
    color: '#D4B45A',
    fontSize: 22,
    fontWeight: '800',
  },
  msg: {
    marginTop: 16,
    color: '#aaa',
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 20,
  },
  btn: {
    marginTop: 24,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: '#D4B45A',
    borderRadius: 6,
  },
  btnText: { color: '#F2E2B0', fontWeight: '700' },
});
