import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { apiResendVerification, friendlyAuthError } from '../../lib/authApi';
import { createAuthStyles } from '../../theme/authStyles';
import AuthShell from '../../components/auth/AuthShell';

export default function VerifyEmailScreen({ onDone, initialToken = '' }) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const { verifyEmail, user, accessToken, busy, error, setError } = useAuth();
  const [token, setToken] = useState(initialToken);
  const [localErr, setLocalErr] = useState('');
  const [msg, setMsg] = useState('');

  const onVerify = async () => {
    setLocalErr('');
    setError('');
    const res = await verifyEmail(token.trim());
    if (!res.ok) setLocalErr(res.error);
    else {
      setMsg('Email verified successfully.');
      onDone?.();
    }
  };

  const onResend = async () => {
    if (!accessToken) return;
    setLocalErr('');
    const res = await apiResendVerification(accessToken);
    if (!res.ok) setLocalErr(friendlyAuthError(res.error));
    else if (res.data?.devLink) setMsg(`Dev link: ${res.data.devLink}`);
    else setMsg('Verification email sent.');
  };

  return (
    <AuthShell>
      <View style={st.card}>
        <Text style={st.title}>Verify email</Text>
        <Text style={st.subtitle}>
          {user?.emailVerified
            ? 'Your email is already verified.'
            : 'Paste the verification token from your email or use the in-app link.'}
        </Text>

        {!user?.emailVerified ? (
          <>
            <Text style={st.label}>Verification token</Text>
            <TextInput
              style={st.input}
              value={token}
              onChangeText={setToken}
              autoCapitalize="none"
              placeholder="Paste token"
              placeholderTextColor={C.dim2}
            />
            <Pressable style={[st.btn, busy && st.btnDisabled]} onPress={onVerify} disabled={busy}>
              {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.btnTxt}>VERIFY EMAIL</Text>}
            </Pressable>
            <Pressable style={st.btnGhost} onPress={onResend}>
              <Text style={[st.btnGhostTxt, st.link]}>Resend verification email</Text>
            </Pressable>
          </>
        ) : null}

        {(localErr || error) && (
          <View style={st.errorBox}>
            <Text style={st.errorTxt}>{localErr || error}</Text>
          </View>
        )}
        {msg ? <Text style={{ color: C.green, marginTop: 12, fontSize: 12 }}>{msg}</Text> : null}
      </View>
    </AuthShell>
  );
}
