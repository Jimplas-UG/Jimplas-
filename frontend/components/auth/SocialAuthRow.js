import React, { useMemo } from 'react';
import { ActivityIndicator, Platform, Pressable, Text, View } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import { makeRedirectUri } from 'expo-auth-session';
import Constants from 'expo-constants';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { createAuthStyles } from '../../theme/authStyles';

WebBrowser.maybeCompleteAuthSession();

function extra(key) {
  const c = Constants.expoConfig?.extra ?? Constants.manifest2?.extra ?? Constants.manifest?.extra;
  return c?.[key];
}

export default function SocialAuthRow({ onError }) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const { loginGoogle, loginApple, busy } = useAuth();
  const googleClientId =
    process.env.EXPO_PUBLIC_GOOGLE_CLIENT_ID?.trim() || extra('googleClientId') || '';
  const appleClientId = process.env.EXPO_PUBLIC_APPLE_CLIENT_ID?.trim() || extra('appleClientId') || '';

  const onGoogle = async () => {
    if (!googleClientId) {
      onError?.('Google Sign-In not configured. Set EXPO_PUBLIC_GOOGLE_CLIENT_ID.');
      return;
    }
    try {
      const redirectUri = makeRedirectUri({ scheme: 'bilshenz' });
      const authUrl =
        `https://accounts.google.com/o/oauth2/v2/auth?` +
        `client_id=${encodeURIComponent(googleClientId)}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        '&response_type=id_token&scope=openid%20email%20profile' +
        `&nonce=${encodeURIComponent(String(Date.now()))}`;
      const res = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);
      if (res.type !== 'success' || !res.url) {
        onError?.('Google sign-in cancelled.');
        return;
      }
      const hash = res.url.split('#')[1] || res.url.split('?')[1] || '';
      const params = Object.fromEntries(new URLSearchParams(hash));
      const idToken = params.id_token;
      if (!idToken) {
        onError?.('Google did not return an ID token.');
        return;
      }
      const out = await loginGoogle(idToken);
      if (!out.ok) onError?.(out.error);
    } catch (e) {
      onError?.(e instanceof Error ? e.message : 'Google sign-in failed');
    }
  };

  const onApple = async () => {
    if (Platform.OS !== 'ios') {
      onError?.('Apple Sign-In is available on iOS.');
      return;
    }
    if (!appleClientId) {
      onError?.('Apple Sign-In not configured. Set EXPO_PUBLIC_APPLE_CLIENT_ID.');
      return;
    }
    try {
      const redirectUri = makeRedirectUri({ scheme: 'bilshenz' });
      const authUrl =
        `https://appleid.apple.com/auth/authorize?` +
        `client_id=${encodeURIComponent(appleClientId)}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        '&response_type=id_token&scope=name%20email&response_mode=fragment';
      const res = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);
      if (res.type !== 'success' || !res.url) {
        onError?.('Apple sign-in cancelled.');
        return;
      }
      const hash = res.url.split('#')[1] || '';
      const params = Object.fromEntries(new URLSearchParams(hash));
      const idToken = params.id_token;
      if (!idToken) {
        onError?.('Apple did not return an ID token.');
        return;
      }
      const out = await loginApple(idToken);
      if (!out.ok) onError?.(out.error);
    } catch (e) {
      onError?.(e instanceof Error ? e.message : 'Apple sign-in failed');
    }
  };

  return (
    <View style={st.socialRow}>
      <Pressable style={st.socialBtn} onPress={onGoogle} disabled={busy}>
        {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.socialTxt}>Google</Text>}
      </Pressable>
      {Platform.OS === 'ios' ? (
        <Pressable style={st.socialBtn} onPress={onApple} disabled={busy}>
          <Text style={st.socialTxt}>Apple</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
