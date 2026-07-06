import React, { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Pressable,
  Text,
  TextInput,
  View,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { useAuth } from '../../contexts/AuthContext';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { apiChangePassword, apiUpdateProfile, friendlyAuthError } from '../../lib/authApi';
import { createAuthStyles } from '../../theme/authStyles';
import { PilotCard } from '../pilot/PilotUI';
import PasswordField from './PasswordField';

function initials(name) {
  const p = String(name || 'U')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!p.length) return 'U';
  if (p.length === 1) return p[0].slice(0, 2).toUpperCase();
  return `${p[0][0]}${p[1][0]}`.toUpperCase();
}

export default function AccountProfileCard() {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const { user, accessToken, logout, refreshProfile, busy, biometricEnabled, enableBiometric, biometricAvailable } =
    useAuth();

  const [fullName, setFullName] = useState(user?.fullName ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [avatarUrl, setAvatarUrl] = useState(user?.avatarUrl ?? null);
  const [saving, setSaving] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [err, setErr] = useState('');

  React.useEffect(() => {
    setFullName(user?.fullName ?? '');
    setPhone(user?.phone ?? '');
    setAvatarUrl(user?.avatarUrl ?? null);
  }, [user]);

  const onSaveProfile = useCallback(async () => {
    if (!accessToken) return;
    setSaving(true);
    setErr('');
    const res = await apiUpdateProfile(accessToken, {
      fullName: fullName.trim(),
      phone: phone.trim() || undefined,
      avatarUrl,
    });
    setSaving(false);
    if (!res.ok) setErr(friendlyAuthError(res.error));
    else await refreshProfile();
  }, [accessToken, avatarUrl, fullName, phone, refreshProfile]);

  const onPickPhoto = useCallback(async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Photos', 'Allow photo library access to set a profile picture.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.85,
    });
    if (!result.canceled && result.assets?.[0]?.uri) {
      setAvatarUrl(result.assets[0].uri);
    }
  }, []);

  const onChangePassword = useCallback(async () => {
    if (!accessToken) return;
    setSaving(true);
    setErr('');
    const res = await apiChangePassword(accessToken, currentPassword, newPassword);
    setSaving(false);
    if (!res.ok) setErr(friendlyAuthError(res.error));
    else {
      Alert.alert('Password updated', 'Sign in again on other devices if needed.');
      setShowPw(false);
      setCurrentPassword('');
      setNewPassword('');
    }
  }, [accessToken, currentPassword, newPassword]);

  if (!user) return null;

  return (
    <PilotCard style={{ marginBottom: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <Pressable onPress={onPickPhoto}>
          {avatarUrl ? (
            <Image source={{ uri: avatarUrl }} style={{ width: 56, height: 56, borderRadius: 28 }} />
          ) : (
            <View
              style={{
                width: 56,
                height: 56,
                borderRadius: 28,
                backgroundColor: C.panel2,
                borderWidth: 1,
                borderColor: C.accent,
                alignItems: 'center',
                justifyContent: 'center',
              }}>
              <Text style={{ color: C.accentLight, fontWeight: '800', fontSize: 16 }}>{initials(fullName)}</Text>
            </View>
          )}
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={{ color: C.text, fontWeight: '800', fontSize: 15 }}>{fullName}</Text>
          <Text style={{ color: C.dim, fontSize: 11, marginTop: 2 }}>{user.email}</Text>
          <Text style={{ color: user.emailVerified ? C.green : C.amber, fontSize: 10, marginTop: 4 }}>
            {user.emailVerified ? 'Email verified' : 'Email not verified'}
          </Text>
        </View>
      </View>

      <Text style={st.label}>Display name</Text>
      <TextInput style={st.input} value={fullName} onChangeText={setFullName} placeholderTextColor={C.dim2} />

      <Text style={st.label}>Phone</Text>
      <TextInput
        style={st.input}
        value={phone ?? ''}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        placeholderTextColor={C.dim2}
      />

      <Pressable style={[st.btn, saving && st.btnDisabled]} onPress={onSaveProfile} disabled={saving}>
        {saving ? <ActivityIndicator color={C.accentLight} /> : <Text style={st.btnTxt}>SAVE PROFILE</Text>}
      </Pressable>

      <Pressable style={st.btnGhost} onPress={() => setShowPw((v) => !v)}>
        <Text style={[st.btnGhostTxt, st.link]}>{showPw ? 'Hide change password' : 'Change password'}</Text>
      </Pressable>

      {showPw ? (
        <>
          <PasswordField label="Current password" value={currentPassword} onChangeText={setCurrentPassword} />
          <PasswordField label="New password" value={newPassword} onChangeText={setNewPassword} showStrength />
          <Pressable style={st.btn} onPress={onChangePassword} disabled={saving}>
            <Text style={st.btnTxt}>UPDATE PASSWORD</Text>
          </Pressable>
        </>
      ) : null}

      {biometricAvailable && !biometricEnabled ? (
        <Pressable style={st.btnGhost} onPress={() => void enableBiometric()}>
          <Text style={[st.btnGhostTxt, st.link]}>Enable biometric login</Text>
        </Pressable>
      ) : null}

      {err ? (
        <View style={st.errorBox}>
          <Text style={st.errorTxt}>{err}</Text>
        </View>
      ) : null}

      <Pressable
        style={[st.btn, { marginTop: 16, borderColor: C.red, backgroundColor: 'rgba(255,61,87,0.12)' }]}
        onPress={() => {
          Alert.alert('Sign out', 'Log out of BSV32 on this device?', [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Log out', style: 'destructive', onPress: () => void logout() },
          ]);
        }}
        disabled={busy}>
        <Text style={[st.btnTxt, { color: C.red }]}>LOG OUT</Text>
      </Pressable>
    </PilotCard>
  );
}
