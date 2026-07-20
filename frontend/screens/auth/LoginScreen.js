import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, Text, TextInput, View } from 'react-native';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { apiSendPhoneOtp, apiSendEmailOtp, friendlyAuthError } from '../../lib/authApi';
import { createAuthStyles } from '../../theme/authStyles';
import AuthShell from '../../components/auth/AuthShell';
import PasswordField from '../../components/auth/PasswordField';
import SocialAuthRow from '../../components/auth/SocialAuthRow';

export default function LoginScreen({ onRegister, onForgot, onOtp }) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const {
    loginEmail,
    loginWithBiometric,
    loginWithOtp,
    enableBiometric,
    biometricAvailable,
    biometricEnabled,
    busy,
    error,
    setError,
  } = useAuth();

  const [mode, setMode] = useState('email');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [localErr, setLocalErr] = useState('');

  const showErr = localErr || error;

  const onSubmitEmail = async () => {
    setLocalErr('');
    setError('');
    const res = await loginEmail(email.trim(), password);
    if (res.ok && biometricAvailable && !biometricEnabled) {
      Alert.alert('Biometric login', 'Enable Face ID / fingerprint for faster sign-in next time?', [
        { text: 'Not now', style: 'cancel' },
        { text: 'Enable', onPress: () => void enableBiometric() },
      ]);
    }
    if (!res.ok) setLocalErr(res.error);
  };

  const onSendOtp = async () => {
    setLocalErr('');
    const target = mode === 'phone' ? phone.trim() : email.trim();
    if (!target) {
      setLocalErr(mode === 'phone' ? 'Enter your phone number' : 'Enter your email');
      return;
    }
    const res = mode === 'phone' ? await apiSendPhoneOtp(target) : await apiSendEmailOtp(target);
    if (!res.ok) {
      setLocalErr(friendlyAuthError(res.error));
      return;
    }
    setOtpSent(true);
    if (res.data?.devCode) {
      Alert.alert('Dev OTP', `Code: ${res.data.devCode}`);
    }
  };

  const onVerifyOtp = async () => {
    setLocalErr('');
    const target = phone.trim();
    const res = await loginWithOtp(target, otp.trim(), 'phone');
    if (!res.ok) {
      setLocalErr(res.error || friendlyAuthError(error));
      return;
    }
    if (biometricAvailable && !biometricEnabled) {
      Alert.alert('Biometric login', 'Enable Face ID / fingerprint for faster sign-in next time?', [
        { text: 'Not now', style: 'cancel' },
        { text: 'Enable', onPress: () => void enableBiometric() },
      ]);
    }
  };

  return (
    <AuthShell>
      <View style={st.card}>
        <Text style={st.title}>Sign in</Text>
        <Text style={st.subtitle}>Secure access to your institutional trading desk.</Text>

        <View style={st.row}>
          {[
            { id: 'email', label: 'Email' },
            { id: 'phone', label: 'Phone OTP' },
          ].map((opt) => (
            <Pressable
              key={opt.id}
              onPress={() => {
                setMode(opt.id);
                setOtpSent(false);
                setLocalErr('');
              }}
              style={[st.chip, mode === opt.id && st.chipActive]}>
              <Text style={[st.chipTxt, mode === opt.id && st.chipTxtActive]}>{opt.label}</Text>
            </Pressable>
          ))}
        </View>

        {mode === 'email' ? (
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
            <PasswordField value={password} onChangeText={setPassword} placeholder="Password" />
            <Pressable onPress={onForgot} style={st.btnGhost}>
              <Text style={[st.btnGhostTxt, st.link]}>Forgot password?</Text>
            </Pressable>
            <Pressable style={[st.btn, busy && st.btnDisabled]} onPress={onSubmitEmail} disabled={busy}>
              {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.btnTxt}>SIGN IN</Text>}
            </Pressable>
          </>
        ) : (
          <>
            <Text style={st.label}>Phone</Text>
            <TextInput
              style={st.input}
              value={phone}
              onChangeText={setPhone}
              keyboardType="phone-pad"
              placeholder="+1 555 000 0000"
              placeholderTextColor={C.dim2}
            />
            {otpSent ? (
              <>
                <Text style={st.label}>Verification code</Text>
                <TextInput
                  style={st.input}
                  value={otp}
                  onChangeText={setOtp}
                  keyboardType="number-pad"
                  placeholder="6-digit code"
                  placeholderTextColor={C.dim2}
                  maxLength={6}
                />
                <Pressable style={[st.btn, busy && st.btnDisabled]} onPress={onVerifyOtp} disabled={busy}>
                  <Text style={st.btnTxt}>VERIFY & SIGN IN</Text>
                </Pressable>
              </>
            ) : (
              <Pressable style={st.btn} onPress={onSendOtp}>
                <Text style={st.btnTxt}>SEND OTP</Text>
              </Pressable>
            )}
          </>
        )}

        {showErr ? (
          <View style={st.errorBox}>
            <Text style={st.errorTxt}>{showErr}</Text>
          </View>
        ) : null}

        {biometricAvailable && biometricEnabled ? (
          <Pressable style={st.btnGhost} onPress={() => void loginWithBiometric()} disabled={busy}>
            <Text style={[st.btnGhostTxt, st.link]}>Use biometrics</Text>
          </Pressable>
        ) : null}

        <View style={st.divider}>
          <View style={st.dividerLine} />
          <Text style={st.dividerTxt}>OR</Text>
          <View style={st.dividerLine} />
        </View>

        <SocialAuthRow onError={setLocalErr} />
      </View>

      <View style={st.footer}>
        <Pressable onPress={onRegister}>
          <Text style={st.btnGhostTxt}>
            New to BSV32? <Text style={st.link}>Create account</Text>
          </Text>
        </Pressable>
      </View>
    </AuthShell>
  );
}
