import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { createAuthStyles } from '../../theme/authStyles';
import AuthShell from '../../components/auth/AuthShell';
import PasswordField from '../../components/auth/PasswordField';
import SocialAuthRow from '../../components/auth/SocialAuthRow';

export default function RegisterScreen({ onLogin }) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const { register, busy, error, setError } = useAuth();

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [terms, setTerms] = useState(false);
  const [localErr, setLocalErr] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(''), 3000);
    return () => clearTimeout(t);
  }, [notice]);

  const showErr = localErr || error;

  const onSubmit = async () => {
    setLocalErr('');
    setError('');
    const res = await register({
      fullName: fullName.trim(),
      email: email.trim(),
      phone: phone.trim() || undefined,
      password,
      confirmPassword,
      termsAccepted: terms,
    });
    if (!res.ok) {
      setLocalErr(res.error);
      return;
    }
    if (res.dev?.devLink) {
      setNotice(`Dev verification link: ${res.dev.devLink}`);
    } else {
      setNotice('Check your inbox for a verification link to activate your account.');
    }
  };

  return (
    <AuthShell>
      <View style={st.card}>
        <Text style={st.title}>Create account</Text>
        <Text style={st.subtitle}>Institutional-grade access to BSV32 trading desk.</Text>

        <Text style={st.label}>Full name</Text>
        <TextInput
          style={st.input}
          value={fullName}
          onChangeText={setFullName}
          placeholder="John Doe"
          placeholderTextColor={C.dim2}
        />

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

        <Text style={st.label}>Phone (optional)</Text>
        <TextInput
          style={st.input}
          value={phone}
          onChangeText={setPhone}
          keyboardType="phone-pad"
          placeholder="+1 555 000 0000"
          placeholderTextColor={C.dim2}
        />

        <PasswordField value={password} onChangeText={setPassword} placeholder="Min 8 chars" showStrength />
        <PasswordField
          label="Confirm password"
          value={confirmPassword}
          onChangeText={setConfirmPassword}
          placeholder="Repeat password"
        />

        <Pressable style={st.checkRow} onPress={() => setTerms((v) => !v)}>
          <View style={[st.checkBox, terms && st.checkBoxOn]}>
            {terms ? <Text style={{ color: C.goldL, fontSize: 12 }}>✓</Text> : null}
          </View>
          <Text style={{ color: C.dim, fontSize: 12, flex: 1, lineHeight: 18 }}>
            I agree to the Terms & Conditions and Privacy Policy.
          </Text>
        </Pressable>

        <Pressable style={[st.btn, (busy || !terms) && st.btnDisabled]} onPress={onSubmit} disabled={busy || !terms}>
          {busy ? <ActivityIndicator color={C.goldL} /> : <Text style={st.btnTxt}>CREATE ACCOUNT</Text>}
        </Pressable>

        {showErr ? (
          <View style={st.errorBox}>
            <Text style={st.errorTxt}>{showErr}</Text>
          </View>
        ) : null}

        {notice ? (
          <View style={[st.errorBox, { borderColor: 'rgba(255,179,0,0.35)', backgroundColor: 'rgba(255,179,0,0.08)' }]}>
            <Text style={[st.errorTxt, { color: C.amber }]}>{notice}</Text>
          </View>
        ) : null}

        <View style={st.divider}>
          <View style={st.dividerLine} />
          <Text style={st.dividerTxt}>OR</Text>
          <View style={st.dividerLine} />
        </View>

        <SocialAuthRow onError={setLocalErr} />
      </View>

      <View style={st.footer}>
        <Pressable onPress={onLogin}>
          <Text style={st.btnGhostTxt}>
            Already have an account? <Text style={st.link}>Sign in</Text>
          </Text>
        </Pressable>
      </View>
    </AuthShell>
  );
}
