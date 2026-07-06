import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { PilotPill } from './pilot/PilotUI';

function StatusChip({ label, ok, warn, accent, onPress }) {
  const body = <PilotPill label={label} ok={ok} warn={warn} accent={accent} />;
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [pressed && { opacity: 0.85 }]}>
        {body}
      </Pressable>
    );
  }
  return body;
}

/**
 * Compact desk status — tick scanner feed, bridge account, execution mode.
 */
export default function BinanceStatusStrip({
  scannerReady,
  scannerError,
  feedReady,
  feedError,
  connected,
  execEnabled,
  autoExecute,
  execBlock,
  lastExecError,
  onPressConnect,
  style,
}) {
  const { colors: C } = useBilshenzTheme();
  const ready = scannerReady ?? feedReady;
  const err = scannerError ?? feedError;
  const execOn = execEnabled ?? autoExecute;
  const blockHint = execBlock || (lastExecError ? String(lastExecError).slice(0, 48) : '');

  const scannerOk = !!ready;
  const scannerWarn = !scannerOk && !err;
  const scannerLabel = scannerOk ? 'Scanner live' : err ? 'Scanner offline' : 'Connecting…';
  const acctLabel = connected ? 'Account linked' : 'Tap to connect';
  let execLabel = connected ? (execOn ? 'Auto exec ON' : 'Exec OFF') : 'Exec —';
  if (connected && execOn && blockHint) {
    execLabel = 'Exec blocked';
  } else if (connected && !execOn && blockHint && execBlock === 'exec_disabled') {
    execLabel = 'Exec OFF';
  }

  return (
    <View style={[st.wrap, { backgroundColor: C.panel, borderColor: C.border }, style]}>
      <Text style={[st.title, { color: C.text }]}>System status</Text>
      <View style={st.row}>
        <StatusChip label={scannerLabel} ok={scannerOk} warn={scannerWarn} />
        <StatusChip
          label={acctLabel}
          ok={connected}
          warn={!connected && scannerOk}
          onPress={!connected && onPressConnect ? onPressConnect : undefined}
        />
        <StatusChip
          label={execLabel}
          ok={connected && execOn && !blockHint}
          accent={connected && execOn && !blockHint}
          warn={connected && (!execOn || !!blockHint)}
        />
      </View>
      {connected && blockHint ? (
        <Text style={[st.hint, { color: C.amber }]} numberOfLines={2}>
          {blockHint}
        </Text>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 12,
    paddingHorizontal: 14,
  },
  title: { fontSize: 12, fontWeight: '700', marginBottom: 10 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  hint: { fontSize: 11, marginTop: 8, lineHeight: 15 },
});
