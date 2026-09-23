import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { PilotPill } from './pilot/PilotUI';

function StatusChip({ label, ok, warn, accent, onPress, style }) {
  const body = <PilotPill label={label} ok={ok} warn={warn} accent={accent} />;
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [st.chip, style, pressed && { opacity: 0.85 }]}>
        {body}
      </Pressable>
    );
  }
  return <View style={[st.chip, style]}>{body}</View>;
}

/**
 * Compact desk status — Binance link health, scanner, execution.
 */
export default function BinanceStatusStrip({
  scannerReady,
  scannerError,
  feedReady,
  feedError,
  connected,
  linkHealth,
  restCoolS = 0,
  execReady,
  execBlock,
  lastExecError,
  onPressConnect,
  style,
}) {
  const { colors: C } = useBilshenzTheme();
  const ready = scannerReady ?? feedReady;
  const err = scannerError ?? feedError;
  const blockHint = execBlock || (lastExecError ? String(lastExecError).slice(0, 48) : '');
  const envHalt = blockHint === 'SCANNER_EXEC=0' || blockHint === 'FORWARD_DRY_RUN';
  const armed = connected && execReady === true && !envHalt;

  const scannerOk = !!ready;
  const scannerWarn = !scannerOk && !err;
  const scannerLabel = scannerOk ? 'Scanner live' : err ? 'Scanner offline' : 'Connecting…';

  const health = String(linkHealth || (connected ? 'CONNECTED' : 'DISCONNECTED')).toUpperCase();
  let acctLabel = 'Tap to connect';
  let acctOk = false;
  let acctWarn = false;
  if (health === 'CONNECTED') {
    acctLabel = 'Binance connected';
    acctOk = true;
  } else if (health === 'DEGRADED') {
    acctLabel = restCoolS > 0.5 ? `Degraded · cool ${Math.ceil(restCoolS)}s` : 'Degraded · syncing';
    acctOk = true;
    acctWarn = true;
  } else if (health === 'RECONNECTING') {
    acctLabel = 'Reconnecting…';
    acctWarn = true;
  } else if (health === 'AUTH_ERROR') {
    acctLabel = 'Auth error';
  } else if (connected) {
    acctLabel = 'Account linked';
    acctOk = true;
  }

  let execLabel = 'Exec —';
  if (connected || health === 'CONNECTED' || health === 'DEGRADED') {
    if (envHalt) execLabel = 'Halted (env)';
    else if (armed) execLabel = 'Exec ready';
    else if (execReady === false) execLabel = 'Not armed';
    else execLabel = 'Arming…';
  }

  return (
    <View style={[st.wrap, { backgroundColor: C.panel, borderColor: C.border }, style]}>
      <Text style={[st.title, { color: C.text }]}>System status</Text>
      <View style={st.row}>
        <StatusChip label={scannerLabel} ok={scannerOk} warn={scannerWarn} />
        <StatusChip
          label={acctLabel}
          ok={acctOk}
          warn={acctWarn || (!connected && scannerOk)}
          onPress={!connected && onPressConnect ? onPressConnect : undefined}
        />
        <StatusChip
          label={execLabel}
          ok={armed}
          accent={armed}
          warn={(connected || health === 'DEGRADED') && !armed}
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
  row: { flexDirection: 'row', gap: 8 },
  chip: { flex: 1, minWidth: 0 },
  hint: { fontSize: 11, marginTop: 8, lineHeight: 15 },
});
