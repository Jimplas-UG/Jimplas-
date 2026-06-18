import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, Text, TextInput, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { apiForgotPassword, apiResetPassword, friendlyAuthError } from '../../lib/authApi';
import { createAuthStyles } from '../../theme/authStyles';
import AuthShell from '../../components/auth/AuthShell';
import PasswordField from '../../components/auth/PasswordField';

export default function ForgotPasswordScreen({ onLogin, initialToken = '' }) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);

  const [step, setStep] = useState(initialToken ? 'reset' : 'request');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [token, setToken] = useState(initialToken);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [via, setVia] = useState('email');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const onRequest = async () => {
    setBusy(true);
    setErr('');
    try {
      const res = await apiForgotPassword(email.trim(), via);
      if (!res.ok) {
        setErr(friendlyAuthError(res.error));
        return;
      }
      if (res.data?.devLink) Alert.alert('Dev reset link', res.data.devLink);
      if (via === 'otp') {
        setStep('reset');
        if (res.data?.devCode) Alert.alert('Dev OTP', res.data.devCode);
      } else {
        Alert.alert('Check your email', 'If an account exists, we sent reset instructions.');
        onLogin?.();
      }
    } finally {
      setBusy(false);
    }
  };

  const onReset = async () => {
    setBusy(true);
    setErr('');
    try {
      const payload = token
        ? { token, password, confirmPassword }
        : { email: email.trim(), code: code.trim(), password, confirmPassword };
      const res = await apiResetPassword(payload);
      if (!res.ok) {
        setErr(friendlyAuthError(res.error));
        return;
      }
      Alert.alert('Password updated', 'You can now sign in with your new password.');
      onLogin?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <View style={st.card}>
        <Text style={st.title}>{step === 'request' ? 'Forgot password' : 'Reset password'}</Text>
        <Text style={st.subtitle}>
          {step === 'request'
            ? 'We will send a secure reset link or OTP to your email.'
            : 'Choose a strong new password for your account.'}
        </Text>

        {step === 'request' ? (
          <>
            <Text style={st.label}>Email</Text>
            <TextInput
              style={st.input}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              placeholder="you@firm.com"
              placeholderTextColor={C.dim2}
            />
            <View style={st.row}>
              {[
                { id: 'email', label: 'Email link' },
                { id: 'otp', label: 'OTP code' },
              ].map((opt) => (
                <Pressable
                  key={opt.id}
                  onPress={() => setVia(opt.id)}
                  style={[st.chip, via === opt.id && st.chipActive]}>
                  <Text style={[st.chipTxt, via === opt.id && st.chipTxtActive]}>{opt.label}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable style={[st.btn, busy && st.btnDisabled]} onPress={onRequest} disabled={busy}>
              {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.btnTxt}>SEND RESET</Text>}
            </Pressable>
          </>
        ) : (
          <>
            {!token ? (
              <>
                <Text style={st.label}>OTP code</Text>
                <TextInput
                  style={st.input}
                  value={code}
                  onChangeText={setCode}
                  keyboardType="number-pad"
                  placeholder="6-digit code"
                  placeholderTextColor={C.dim2}
                  maxLength={6}
                />
              </>
            ) : null}
            <PasswordField value={password} onChangeText={setPassword} showStrength placeholder="New password" />
            <PasswordField
              label="Confirm password"
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              placeholder="Repeat password"
            />
            <Pressable style={[st.btn, busy && st.btnDisabled]} onPress={onReset} disabled={busy}>
              {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.btnTxt}>UPDATE PASSWORD</Text>}
            </Pressable>
          </>
        )}

        {err ? (
          <View style={st.errorBox}>
            <Text style={st.errorTxt}>{err}</Text>
          </View>
        ) : null}
      </View>

      <View style={st.footer}>
        <Pressable onPress={onLogin}>
          <Text style={st.btnGhostTxt}>
            Back to <Text style={st.link}>Sign in</Text>
          </Text>
        </Pressable>
      </View>
    </AuthShell>
  );
}
