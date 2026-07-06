import '@expo/metro-runtime';
import 'react-native-reanimated';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, ScrollView, Text, View } from 'react-native';
import { registerRootComponent } from 'expo';
import { hideBootSplash, initBootSplash } from './lib/bootSplash';

initBootSplash();
if (typeof __DEV__ !== 'undefined' && __DEV__) {
  setTimeout(() => hideBootSplash('dev-fast-hide'), 400);
}

function StartupError({ err }) {
  const msg = err?.message ? String(err.message) : String(err);
  return (
    <View style={{ flex: 1, backgroundColor: '#100E0A', paddingTop: 48, paddingHorizontal: 16 }}>
      <Text style={{ color: '#D4B45A', fontSize: 18, fontWeight: '800', marginBottom: 8 }}>Bilshenz</Text>
      <Text style={{ color: '#ff8b8a', fontSize: 14, fontWeight: '700', marginBottom: 12 }}>
        Startup failed
      </Text>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 32 }}>
        <Text
          selectable
          style={{
            color: '#F2E2B0',
            fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
            fontSize: 11,
            lineHeight: 16,
          }}>
          {msg}
        </Text>
      </ScrollView>
    </View>
  );
}

function Bootstrap() {
  const [AppRoot, setAppRoot] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = async (attempt = 0) => {
      try {
        // Expo Go Android: launcher must finish before expo-constants reads manifest.
        if (attempt === 0) {
          await new Promise((r) => setTimeout(r, Platform.OS === 'android' ? 120 : 0));
        }
        const mod = await import('./AppBootstrap');
        if (!cancelled) {
          setAppRoot(() => mod.default);
          hideBootSplash('bootstrap-ready');
        }
      } catch (e) {
        if (cancelled) return;
        if (attempt < 4 && /manifest|launcher|HostObject/i.test(String(e?.message || e))) {
          await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
          return load(attempt + 1);
        }
        setErr(e);
        hideBootSplash('bootstrap-error');
        console.error('[Bilshenz] bootstrap failed', e);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) return <StartupError err={err} />;
  if (!AppRoot) {
    return (
      <View style={{ flex: 1, backgroundColor: '#0A0E17', alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator size="large" color="#7C6CF0" />
      </View>
    );
  }
  return <AppRoot />;
}

registerRootComponent(Bootstrap);
