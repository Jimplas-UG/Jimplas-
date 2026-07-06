import React, { useCallback, useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { radius, spacing, typography } from '../theme/designTokens';
import { getDefaultBinanceBridgeUrl } from '../utils/binanceApiUrl';
import { binanceFetch } from '../broker/binanceFuturesApi';

const ONBOARDING_KEY = '@bilshenz_v1/onboardingDone';

export function useOnboardingDone() {
  const [done, setDone] = useState(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const v = await AsyncStorage.getItem(ONBOARDING_KEY);
      if (!cancelled) setDone(v === '1');
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  const markDone = useCallback(async () => {
    await AsyncStorage.setItem(ONBOARDING_KEY, '1');
    setDone(true);
  }, []);
  return { done, markDone };
}

export default function OnboardingGate({ visible, onComplete, onOpenProfile }) {
  const { colors: C, styles: appStyles } = useBilshenzTheme();
  const { baseUrl, connected } = useBinanceBridge();
  const [probe, setProbe] = useState(null);
  const [busy, setBusy] = useState(false);

  const runProbe = useCallback(async () => {
    setBusy(true);
    setProbe(null);
    try {
      const url = baseUrl || getDefaultBinanceBridgeUrl();
      const res = await binanceFetch(url, '/health', {}, 8000);
      if (res.ok) {
        const j = await res.json();
        setProbe({ ok: true, mode: j.mode ?? 'unknown' });
      } else {
        setProbe({ ok: false, error: `HTTP ${res.status}` });
      }
    } catch (e) {
      setProbe({ ok: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }, [baseUrl]);

  useEffect(() => {
    if (visible) void runProbe();
  }, [visible, runProbe]);

  if (!visible) return null;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onComplete}>
      <View style={styles.backdrop}>
        <View style={[styles.card, { backgroundColor: C.panel, borderColor: C.border }]}>
          <Text style={[styles.kicker, { color: C.gold }]}>BSV3.2 · BINANCE FUTURES</Text>
          <Text style={[styles.headline, { color: C.goldL }]}>Welcome to your trading desk</Text>
          <ScrollView style={styles.scroll} showsVerticalScrollIndicator={false}>
            <Step n={1} title="Start the bridge" body="On your PC run: cd binance_trading_system/python && .\\start-api.ps1 — port 8766." C={C} />
            <Step n={2} title="Connect from Profile" body="Open Profile → enter testnet API keys → Connect. Use testnet first." C={C} />
            <Step n={3} title="Verify scanner" body="Scanner tab shows live USDT-M tick momentum when the bridge is reachable." C={C} />
            <View style={[styles.probe, { borderColor: C.border, backgroundColor: C.panel2 }]}>
              <Text style={[styles.probeLbl, { color: C.dim }]}>BRIDGE CHECK</Text>
              {busy ? (
                <Text style={{ color: C.dim, fontSize: 12 }}>Probing…</Text>
              ) : probe?.ok ? (
                <Text style={{ color: C.green, fontSize: 12 }}>OK · mode={probe.mode}</Text>
              ) : (
                <Text style={{ color: C.red, fontSize: 12 }}>{probe?.error ?? 'Unreachable'}</Text>
              )}
              <Pressable onPress={runProbe} style={({ pressed }) => [styles.linkBtn, pressed && { opacity: 0.85 }]}>
                <Text style={{ color: C.blue, fontSize: 11 }}>Re-test bridge</Text>
              </Pressable>
            </View>
          </ScrollView>
          <Pressable
            onPress={() => {
              onOpenProfile?.();
            }}
            style={({ pressed }) => [appStyles.psSegChip, styles.secondary, pressed && { opacity: 0.88 }]}>
            <Text style={[styles.btnTxt, { color: C.text }]}>OPEN PROFILE</Text>
          </Pressable>
          <Pressable
            onPress={onComplete}
            style={({ pressed }) => [appStyles.psSegChip, appStyles.psSegChipOn, styles.primary, pressed && { opacity: 0.88 }]}>
            <Text style={[styles.btnTxt, { color: C.goldL }]}>
              {connected ? 'ENTER DESK' : 'CONTINUE (connect later)'}
            </Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

function Step({ n, title, body, C }) {
  return (
    <View style={styles.step}>
      <View style={[styles.badge, { borderColor: C.goldD, backgroundColor: C.panel2 }]}>
        <Text style={{ color: C.gold, fontSize: 11, fontWeight: '700' }}>{n}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[styles.stepTitle, { color: C.goldL }]}>{title}</Text>
        <Text style={[styles.stepBody, { color: C.dim }]}>{body}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.72)',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  card: {
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.xl,
    maxHeight: '88%',
  },
  kicker: {
    ...typography.label,
    marginBottom: spacing.xs,
  },
  headline: {
    ...typography.title,
    marginBottom: spacing.lg,
  },
  scroll: {
    maxHeight: 320,
    marginBottom: spacing.lg,
  },
  step: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  badge: {
    width: 28,
    height: 28,
    borderRadius: radius.pill,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepTitle: {
    ...typography.label,
    fontSize: 11,
    marginBottom: 4,
  },
  stepBody: {
    ...typography.caption,
    lineHeight: 16,
  },
  probe: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  probeLbl: {
    ...typography.label,
    marginBottom: spacing.xs,
  },
  linkBtn: {
    marginTop: spacing.sm,
    alignSelf: 'flex-start',
  },
  primary: {
    marginTop: spacing.sm,
    minHeight: 44,
    justifyContent: 'center',
  },
  secondary: {
    minHeight: 44,
    justifyContent: 'center',
  },
  btnTxt: {
    ...typography.label,
    textAlign: 'center',
  },
});
