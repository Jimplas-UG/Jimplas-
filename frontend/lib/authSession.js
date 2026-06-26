/**
 * Secure JWT session storage for BSV32 user auth.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export const STORAGE_AUTH_ACCESS = '@bilshenz_v1/authAccessToken';
export const STORAGE_AUTH_REFRESH = '@bilshenz_v1/authRefreshToken';
export const STORAGE_AUTH_USER = '@bilshenz_v1/authUser';
export const STORAGE_AUTH_LOGGED_IN = '@bilshenz_v1/authLoggedIn';
export const STORAGE_AUTH_BIOMETRIC = '@bilshenz_v1/authBiometricEnabled';
export const SECURE_REFRESH_KEY = 'bilshenz.auth.refreshToken';

function canUseSecureStore() {
  return Platform.OS !== 'web';
}

export async function saveAuthSession({ accessToken, refreshToken, user, expiresIn }) {
  await AsyncStorage.multiSet([
    [STORAGE_AUTH_ACCESS, accessToken || ''],
    [STORAGE_AUTH_USER, JSON.stringify(user || null)],
    [STORAGE_AUTH_BIOMETRIC, await AsyncStorage.getItem(STORAGE_AUTH_BIOMETRIC).then((v) => v || '0')],
    [STORAGE_AUTH_REFRESH, refreshToken || ''],
    [STORAGE_AUTH_LOGGED_IN, accessToken && user ? '1' : '0'],
  ]);
  if (canUseSecureStore() && refreshToken) {
    await SecureStore.setItemAsync(SECURE_REFRESH_KEY, refreshToken);
  }
}

export async function loadAuthSession() {
  const pairs = await AsyncStorage.multiGet([
    STORAGE_AUTH_ACCESS,
    STORAGE_AUTH_USER,
    STORAGE_AUTH_REFRESH,
    STORAGE_AUTH_LOGGED_IN,
  ]);
  const m = Object.fromEntries(pairs);
  let refreshToken = '';
  if (canUseSecureStore()) {
    try {
      refreshToken = (await SecureStore.getItemAsync(SECURE_REFRESH_KEY)) || '';
    } catch {
      refreshToken = '';
    }
  }
  if (!refreshToken) refreshToken = m[STORAGE_AUTH_REFRESH] || '';
  let user = null;
  try {
    user = m[STORAGE_AUTH_USER] ? JSON.parse(m[STORAGE_AUTH_USER]) : null;
  } catch {
    user = null;
  }
  return {
    accessToken: m[STORAGE_AUTH_ACCESS] || '',
    refreshToken,
    user,
    loggedIn: m[STORAGE_AUTH_LOGGED_IN] === '1',
  };
}

export async function clearAuthSession() {
  await AsyncStorage.multiRemove([
    STORAGE_AUTH_ACCESS,
    STORAGE_AUTH_REFRESH,
    STORAGE_AUTH_USER,
    STORAGE_AUTH_LOGGED_IN,
  ]);
  if (canUseSecureStore()) {
    try {
      await SecureStore.deleteItemAsync(SECURE_REFRESH_KEY);
      await SecureStore.deleteItemAsync(`${SECURE_REFRESH_KEY}.bio`);
    } catch {
      /* ignore */
    }
  }
}

export async function isBiometricEnabled() {
  return (await AsyncStorage.getItem(STORAGE_AUTH_BIOMETRIC)) === '1';
}

export async function setBiometricEnabled(enabled) {
  await AsyncStorage.setItem(STORAGE_AUTH_BIOMETRIC, enabled ? '1' : '0');
}

export async function saveBiometricRefreshToken(refreshToken) {
  if (!canUseSecureStore() || !refreshToken) return false;
  try {
    await SecureStore.setItemAsync(`${SECURE_REFRESH_KEY}.bio`, refreshToken, {
      requireAuthentication: true,
      authenticationPrompt: 'Unlock BSV32',
    });
    await setBiometricEnabled(true);
    return true;
  } catch {
    return false;
  }
}

export async function loadBiometricRefreshToken() {
  if (!canUseSecureStore()) return null;
  try {
    return await SecureStore.getItemAsync(`${SECURE_REFRESH_KEY}.bio`, {
      requireAuthentication: true,
      authenticationPrompt: 'Sign in with biometrics',
    });
  } catch {
    return null;
  }
}

export async function clearBiometricRefreshToken() {
  if (!canUseSecureStore()) return;
  try {
    await SecureStore.deleteItemAsync(`${SECURE_REFRESH_KEY}.bio`);
  } catch {
    /* ignore */
  }
  await setBiometricEnabled(false);
}
