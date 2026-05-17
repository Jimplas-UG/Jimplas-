import 'react-native-reanimated';
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
          <Text style={{ color: '#aaa', fontSize: 12, marginBottom: 8 }}>
            Copy this text from the screen (or use Expo Go → View error log) and share it for debugging.
          </Text>
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

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
function Root() {
  return (
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  );
}

registerRootComponent(Root);
