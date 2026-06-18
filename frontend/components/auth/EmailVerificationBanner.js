import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { apiResendVerification, friendlyAuthError } from '../../lib/authApi';
import { createAuthStyles } from '../../theme/authStyles';

/** Top-of-desk reminder when account email is not verified yet. */
export default function EmailVerificationBanner() {
  const { user, accessToken, verifyEmail, busy } = useAuth();
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const [expanded, setExpanded] = useState(false);
  const [token, setToken] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  if (!user || user.emailVerified) return null;

  const onVerify = async () => {
    setErr('');
    setMsg('');
    const res = await verifyEmail(token.trim());
    if (!res.ok) setErr(res.error || 'Verification failed');
    else setMsg('Email verified — you are fully activated.');
  };

  const onResend = async () => {
    if (!accessToken) return;
    setErr('');
    const res = await apiResendVerification(accessToken);
    if (!res.ok) setErr(friendlyAuthError(res.error));
    else if (res.data?.devLink) setMsg(`Dev link: ${res.data.devLink}`);
    else setMsg('Verification email sent.');
  };

  return (
    <View
      style={{
        marginHorizontal: 12,
        marginTop: 6,
        marginBottom: 4,
        padding: 12,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: 'rgba(255,179,0,0.35)',
        backgroundColor: 'rgba(255,179,0,0.08)',
      }}>
      <Pressable onPress={() => setExpanded((v) => !v)}>
        <Text style={{ color: C.amber, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 }}>
          VERIFY EMAIL · {user.email}
        </Text>
        <Text style={{ color: C.dim, fontSize: 10, marginTop: 4 }}>
          Tap to {expanded ? 'hide' : 'enter verification token'} — required for full account security.
        </Text>
      </Pressable>

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
          {err ? <Text style={{ color: C.red, fontSize: 10, marginTop: 6 }}>{err}</Text> : null}
          {msg ? <Text style={{ color: C.green, fontSize: 10, marginTop: 6 }}>{msg}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}
