import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Pressable, Text, TextInput, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { apiResendVerification, friendlyAuthError } from '../../lib/authApi';
import { createAuthStyles } from '../../theme/authStyles';
import { elevation, motion, radius } from '../../theme/designTokens';

const DISMISS_KEY = '@bilshenz_v1/emailVerifyToastDismissed';
const VISIBLE_MS = 5500;

/** Brief home-tab toast when account email is not verified yet. */
export default function EmailVerificationBanner({ active = false, onOpenProfile }) {
  const { user, accessToken, verifyEmail, busy } = useAuth();
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const [sessionDismissed, setSessionDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [token, setToken] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [mounted, setMounted] = useState(false);
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(-28)).current;
  const hideTimer = useRef(null);
  const verifyDismissTimer = useRef(null);

  const shouldShow = Boolean(active && user && !user.emailVerified && !sessionDismissed);

  const persistDismiss = useCallback(async () => {
    if (user?.id) await AsyncStorage.setItem(`${DISMISS_KEY}:${user.id}`, '1');
  }, [user?.id]);

  const animateOut = useCallback(
    (onDone) => {
      Animated.parallel([
        Animated.timing(opacity, { toValue: 0, duration: motion.normal, useNativeDriver: true }),
        Animated.timing(translateY, { toValue: -28, duration: motion.normal, useNativeDriver: true }),
      ]).start(({ finished }) => {
        if (finished) {
          setMounted(false);
          setExpanded(false);
          onDone?.();
        }
      });
    },
    [opacity, translateY],
  );

  const dismiss = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    animateOut(() => {
      setSessionDismissed(true);
      void persistDismiss();
    });
  }, [animateOut, persistDismiss]);

  const animateIn = useCallback(() => {
    setMounted(true);
    opacity.setValue(0);
    translateY.setValue(-28);
    Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: motion.slow, useNativeDriver: true }),
      Animated.timing(translateY, { toValue: 0, duration: motion.slow, useNativeDriver: true }),
    ]).start();
  }, [opacity, translateY]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!user?.id || user.emailVerified) {
        setSessionDismissed(false);
        return;
      }
      const v = await AsyncStorage.getItem(`${DISMISS_KEY}:${user.id}`);
      if (!cancelled && v === '1') setSessionDismissed(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.id, user?.emailVerified]);

  useEffect(
    () => () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
      if (verifyDismissTimer.current) clearTimeout(verifyDismissTimer.current);
    },
    [],
  );

  useEffect(() => {
    if (!shouldShow) {
      if (hideTimer.current) clearTimeout(hideTimer.current);
      if (mounted && !active) {
        animateOut();
      }
      return undefined;
    }
    animateIn();
    hideTimer.current = setTimeout(() => {
      if (!expanded) dismiss();
    }, VISIBLE_MS);
    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, [shouldShow, active, animateIn, animateOut, dismiss, expanded]);

  const onVerify = async () => {
    setErr('');
    setMsg('');
    const res = await verifyEmail(token.trim());
    if (!res.ok) setErr(res.error || 'Verification failed');
    else {
      setMsg('Email verified — you are fully activated.');
      if (hideTimer.current) clearTimeout(hideTimer.current);
      verifyDismissTimer.current = setTimeout(() => dismiss(), 1200);
    }
  };

  const onResend = async () => {
    if (!accessToken) return;
    setErr('');
    const res = await apiResendVerification(accessToken);
    if (!res.ok) setErr(friendlyAuthError(res.error));
    else if (res.data?.devLink) setMsg(`Dev link: ${res.data.devLink}`);
    else setMsg('Verification email sent.');
  };

  if (!mounted || !user || user.emailVerified) return null;

  return (
    <Animated.View
      pointerEvents="box-none"
      style={{
        position: 'absolute',
        top: 6,
        left: 12,
        right: 12,
        zIndex: 1200,
        opacity,
        transform: [{ translateY }],
      }}>
      <View
        style={{
          padding: 12,
          borderRadius: radius.lg,
          borderWidth: 1,
          borderColor: 'rgba(255,179,0,0.35)',
          backgroundColor: 'rgba(18,14,8,0.96)',
          ...elevation.card,
        }}>
        <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
          <Pressable style={{ flex: 1 }} onPress={() => setExpanded((v) => !v)}>
            <Text style={{ color: C.amber, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 }}>
              VERIFY EMAIL
            </Text>
            <Text style={{ color: C.dim, fontSize: 10, marginTop: 4 }}>{user.email}</Text>
            <Text style={{ color: C.dim2, fontSize: 10, marginTop: 4 }}>
              {expanded ? 'Enter token below' : 'Tap to verify · auto-hides shortly'}
            </Text>
          </Pressable>
          <Pressable
            onPress={dismiss}
            hitSlop={10}
            style={{
              width: 24,
              height: 24,
              borderRadius: 12,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'rgba(255,255,255,0.06)',
            }}>
            <Text style={{ color: C.dim, fontSize: 12, fontWeight: '700' }}>×</Text>
          </Pressable>
        </View>

        {expanded ? (
          <View style={{ marginTop: 10 }}>
            <TextInput
              style={[st.input, { marginTop: 0 }]}
              value={token}
              onChangeText={setToken}
              placeholder="Paste token from email"
              placeholderTextColor={C.dim2}
              autoCapitalize="none"
            />
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
              <Pressable style={[st.btn, { flex: 1, marginTop: 0 }]} onPress={onVerify} disabled={busy}>
                {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.btnTxt}>VERIFY</Text>}
              </Pressable>
              <Pressable style={[st.chip, { flex: 1, justifyContent: 'center' }]} onPress={onResend}>
                <Text style={st.chipTxt}>Resend</Text>
              </Pressable>
            </View>
            {onOpenProfile ? (
              <Pressable onPress={onOpenProfile} style={{ marginTop: 8 }}>
                <Text style={{ color: C.gold, fontSize: 10, fontWeight: '700' }}>Open Profile →</Text>
              </Pressable>
            ) : null}
            {err ? <Text style={{ color: C.red, fontSize: 10, marginTop: 6 }}>{err}</Text> : null}
            {msg ? <Text style={{ color: C.green, fontSize: 10, marginTop: 6 }}>{msg}</Text> : null}
          </View>
        ) : null}
      </View>
    </Animated.View>
  );
}
