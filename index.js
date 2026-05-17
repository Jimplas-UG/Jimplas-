import React from 'react';
import { Platform, ScrollView, Text, View } from 'react-native';
import { registerRootComponent } from 'expo';

import App from './App';

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch(err, info) {
    console.error('[Bilshenz] RootErrorBoundary', err?.message, info?.componentStack);
  }

  render() {
    if (this.state.err) {
      const msg = this.state.err?.message ? String(this.state.err.message) : String(this.state.err);
      return (
        <View style={{ flex: 1, backgroundColor: '#1a0a0a', paddingTop: 48, paddingHorizontal: 16 }}>
          <Text style={{ color: '#f2e2b0', fontSize: 16, fontWeight: '800', marginBottom: 12 }}>App crashed on load</Text>
          <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 32 }}>
            <Text selectable style={{ color: '#ff8b8a', fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 11 }}>
              {msg}
            </Text>
          </ScrollView>
        </View>
      );
    }
    return this.props.children;
  }
}

function Root() {
  return (
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  );
}

registerRootComponent(Root);
