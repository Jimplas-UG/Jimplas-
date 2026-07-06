/**
 * Deferred app shell — loaded after registerRootComponent so expo-constants
 * does not run before Expo Go finishes Android launcher init.
 */
import './security/productionGuard';
import { useMockApi } from './lib/devPreview';
import { tryMockFetch } from './mocks/mockApi';
import React from 'react';
import { Platform, ScrollView, Text, View } from 'react-native';
import { hideBootSplash } from './lib/bootSplash';
import App from './App';

if (useMockApi() && typeof global.fetch === 'function') {
  const _nativeFetch = global.fetch.bind(global);
  global.fetch = async (url, init) => {
    const mock = tryMockFetch(url, init);
    if (mock) return mock;
    try {
      return await _nativeFetch(url, init);
    } catch (e) {
      const fallback = tryMockFetch(url, init);
      if (fallback) return fallback;
      throw e;
    }
  };
}

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch(err, info) {
    hideBootSplash('error-boundary');
    console.error('[Bilshenz] RootErrorBoundary', err?.message, info?.componentStack);
  }

  render() {
    if (this.state.err) {
      const msg = this.state.err?.message ? String(this.state.err.message) : String(this.state.err);
      return (
        <View style={{ flex: 1, backgroundColor: '#100E0A', paddingTop: 48, paddingHorizontal: 16 }}>
          <Text style={{ color: '#D4B45A', fontSize: 18, fontWeight: '800', marginBottom: 8 }}>Bilshenz</Text>
          <Text style={{ color: '#ff8b8a', fontSize: 14, fontWeight: '700', marginBottom: 12 }}>
            Something went wrong on startup
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
    return this.props.children;
  }
}

export default function AppBootstrap() {
  return (
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  );
}
