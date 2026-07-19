import React, { useEffect, useMemo, useRef } from 'react';
import { Animated, KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { createAuthStyles } from '../../theme/authStyles';
import BrandLogo from '../logo/BrandLogo';

export default function AuthShell({ children, scroll = true }) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const insets = useSafeAreaInsets();
  const fade = useRef(new Animated.Value(0)).current;
  const slide = useRef(new Animated.Value(16)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade, { toValue: 1, duration: 420, useNativeDriver: true }),
      Animated.timing(slide, { toValue: 0, duration: 420, useNativeDriver: true }),
    ]).start();
  }, [fade, slide]);

  const body = (
    <Animated.View style={{ flex: 1, opacity: fade, transform: [{ translateY: slide }] }}>
      <View style={st.hero}>
        <BrandLogo size={72} />
        <Animated.Text style={st.brand}>BILSHENZ</Animated.Text>
        <Animated.Text style={st.brandSub}>Institutional Desk · BSV32</Animated.Text>
      </View>
      {children}
    </Animated.View>
  );

  return (
    <KeyboardAvoidingView
      style={[st.root, { paddingTop: insets.top, paddingBottom: insets.bottom }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {scroll ? (
        <ScrollView contentContainerStyle={st.scroll} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
          {body}
        </ScrollView>
      ) : (
        <View style={st.scroll}>{body}</View>
      )}
    </KeyboardAvoidingView>
  );
}
