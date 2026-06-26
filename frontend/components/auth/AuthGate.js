import React from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import AuthNavigator from '../../screens/auth/AuthNavigator';

export default function AuthGate({ children }) {
  const { isAuthenticated, hydrated, authRequired } = useAuth();
  const { colors: C } = useBilshenzTheme();

  if (!authRequired) return children;

  if (!hydrated) {
    return (
      <View style={{ flex: 1, backgroundColor: C.appBg, alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <ActivityIndicator size="large" color={C.goldL} />
        <Text style={{ color: C.dim, fontSize: 12, marginTop: 16, textAlign: 'center' }}>
          Loading…
        </Text>
      </View>
    );
  }

  if (!isAuthenticated) return <AuthNavigator />;

  return children;
}
