import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, Platform } from 'react-native';
import * as LocalAuthentication from 'expo-local-authentication';
import {
  apiLoginEmail,
  apiLogout,
  apiMe,
  apiOAuthApple,
  apiOAuthGoogle,
  apiRefresh,
  apiRegister,
  apiVerifyEmail,
  apiVerifyOtp,
  extractAuthPayload,
  friendlyAuthError,
} from '../lib/authApi';
import {
  clearAuthSession,
  clearBiometricRefreshToken,
  isBiometricEnabled,
  loadAuthSession,
  loadBiometricRefreshToken,
  saveAuthSession,
  saveBiometricRefreshToken,
} from '../lib/authSession';

const AuthContext = createContext(null);

async function probeBiometricHardware() {
  if (Platform.OS === 'web') return { hw: false, enrolled: false };
  try {
    const hw = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    return { hw, enrolled };
  } catch {
    return { hw: false, enrolled: false };
  }
}

function isAuthRequired() {
  if (process.env.EXPO_PUBLIC_AUTH_REQUIRED === '0') return false;
  return process.env.EXPO_PUBLIC_AUTH_REQUIRED !== 'skip';
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [accessToken, setAccessToken] = useState('');
  const [refreshToken, setRefreshToken] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const [biometricEnabled, setBiometricEnabled] = useState(false);
  const refreshTimer = useRef(null);

  const applySession = useCallback(async (payload) => {
    if (!payload) return false;
    setUser(payload.user);
    setAccessToken(payload.accessToken);
    setRefreshToken(payload.refreshToken);
    setError('');
    await saveAuthSession({
      accessToken: payload.accessToken,
      refreshToken: payload.refreshToken,
      user: payload.user,
      expiresIn: payload.expiresIn,
    });
    return true;
  }, []);

  const clearSession = useCallback(async (remote = true) => {
    if (remote && accessToken) {
      try {
        await apiLogout(accessToken, refreshToken, false);
      } catch {
        /* ignore */
      }
    }
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    setUser(null);
    setAccessToken('');
    setRefreshToken('');
    setError('');
    await clearAuthSession();
  }, [accessToken, refreshToken]);

  const refreshAccess = useCallback(async (token = refreshToken, timeoutMs = 20000) => {
    if (!token) return false;
    const res = await apiRefresh(token, timeoutMs);
    if (!res.ok) return false;
    const payload = extractAuthPayload(res.data);
    if (!payload) return false;
    await applySession(payload);
    return true;
  }, [applySession, refreshToken]);

  const scheduleRefresh = useCallback(
    (expiresInSec = 14 * 60) => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      const ms = Math.max(60, (expiresInSec - 60) * 1000);
      refreshTimer.current = setTimeout(() => {
        void refreshAccess();
      }, ms);
    },
    [refreshAccess],
  );

  const signInWithPayload = useCallback(
    async (res, offerBiometric = true) => {
      const payload = extractAuthPayload(res.data);
      if (!payload) {
        setError('Invalid server response');
        return { ok: false };
      }
      await applySession(payload);
      scheduleRefresh(payload.expiresIn);
      if (offerBiometric && biometricAvailable) {
        const enabled = await isBiometricEnabled();
        setBiometricEnabled(enabled);
      }
      return { ok: true, user: payload.user, dev: res.data?.verification };
    },
    [applySession, biometricAvailable, scheduleRefresh],
  );

  const loginEmail = useCallback(
    async (email, password) => {
      setBusy(true);
      setError('');
      try {
        const res = await apiLoginEmail(email, password);
        if (!res.ok) {
          const msg = friendlyAuthError(res.error);
          setError(msg);
          return { ok: false, error: msg };
        }
        return await signInWithPayload(res);
      } finally {
        setBusy(false);
      }
    },
    [signInWithPayload],
  );

  const register = useCallback(
    async (payload) => {
      setBusy(true);
      setError('');
      try {
        const res = await apiRegister(payload);
        if (!res.ok) {
          const msg = friendlyAuthError(res.error);
          setError(msg);
          return { ok: false, error: msg };
        }
        return await signInWithPayload(res);
      } finally {
        setBusy(false);
      }
    },
    [signInWithPayload],
  );

  const loginGoogle = useCallback(
    async (idToken) => {
      setBusy(true);
      setError('');
      try {
        const res = await apiOAuthGoogle(idToken);
        if (!res.ok) {
          const msg = friendlyAuthError(res.error);
          setError(msg);
          return { ok: false, error: msg };
        }
        return await signInWithPayload(res);
      } finally {
        setBusy(false);
      }
    },
    [signInWithPayload],
  );

  const loginWithOtp = useCallback(
    async (target, code, channel) => {
      setBusy(true);
      setError('');
      try {
        const res = await apiVerifyOtp(target, code, channel);
        if (!res.ok) {
          const msg = friendlyAuthError(res.error);
          setError(msg);
          return { ok: false, error: msg };
        }
        return await signInWithPayload(res);
      } finally {
        setBusy(false);
      }
    },
    [signInWithPayload],
  );

  const loginApple = useCallback(
    async (idToken) => {
      setBusy(true);
      setError('');
      try {
        const res = await apiOAuthApple(idToken);
        if (!res.ok) {
          const msg = friendlyAuthError(res.error);
          setError(msg);
          return { ok: false, error: msg };
        }
        return await signInWithPayload(res);
      } finally {
        setBusy(false);
      }
    },
    [signInWithPayload],
  );

  const verifyEmail = useCallback(async (token) => {
    setBusy(true);
    setError('');
    try {
      const res = await apiVerifyEmail(token);
      if (!res.ok) {
        const msg = friendlyAuthError(res.error);
        setError(msg);
        return { ok: false, error: msg };
      }
      if (res.data?.user) setUser(res.data.user);
      return { ok: true, user: res.data.user };
    } finally {
      setBusy(false);
    }
  }, []);

  const logout = useCallback(
    async (allDevices = false) => {
      setBusy(true);
      try {
        try {
          if (accessToken) await apiLogout(accessToken, refreshToken, allDevices);
        } catch {
          /* ignore */
        }
        await clearBiometricRefreshToken();
        setBiometricEnabled(false);
        await clearSession(false);
      } finally {
        setBusy(false);
      }
    },
    [accessToken, clearSession, refreshToken],
  );

  const enableBiometric = useCallback(async () => {
    if (!refreshToken) return false;
    const ok = await saveBiometricRefreshToken(refreshToken);
    setBiometricEnabled(ok);
    return ok;
  }, [refreshToken]);

  const loginWithBiometric = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const { hw, enrolled } = await probeBiometricHardware();
      if (!hw || !enrolled) {
        setError('Biometrics not available on this device.');
        return { ok: false };
      }
      const token = await loadBiometricRefreshToken();
      if (!token) {
        setError('Enable biometric login after your next password sign-in.');
        return { ok: false };
      }
      const res = await apiRefresh(token);
      if (!res.ok) {
        setError(friendlyAuthError(res.error, 'Biometric session expired.'));
        return { ok: false };
      }
      return await signInWithPayload(res, false);
    } finally {
      setBusy(false);
    }
  }, [signInWithPayload]);

  const refreshProfile = useCallback(async () => {
    if (!accessToken) return;
    const res = await apiMe(accessToken);
    if (res.ok && res.data?.user) {
      setUser(res.data.user);
      await saveAuthSession({ accessToken, refreshToken, user: res.data.user });
    } else if (res.status === 401) {
      const ok = await refreshAccess();
      if (!ok) await clearSession(false);
    }
  }, [accessToken, clearSession, refreshAccess, refreshToken]);

  useEffect(() => {
    let cancelled = false;
    const BOOT_SPINNER_MS = 3500;
    const BOOT_REFRESH_MS = 6000;
    const spinnerCap = setTimeout(() => {
      if (!cancelled) setHydrated(true);
    }, BOOT_SPINNER_MS);

    (async () => {
      try {
        const { hw, enrolled } = await probeBiometricHardware();
        if (!cancelled) setBiometricAvailable(hw && enrolled);
        const bioOn = await isBiometricEnabled();
        if (!cancelled) setBiometricEnabled(bioOn);

        const stored = await loadAuthSession();
        if (stored.refreshToken) {
          const ok = await refreshAccess(stored.refreshToken, BOOT_REFRESH_MS);
          if (!ok && bioOn && hw && enrolled) {
            /* wait for explicit biometric tap */
          } else if (!ok) {
            await clearAuthSession();
          } else {
            scheduleRefresh();
          }
        } else if (stored.accessToken && stored.user) {
          setAccessToken(stored.accessToken);
          setUser(stored.user);
          const me = await apiMe(stored.accessToken);
          if (me.ok) setUser(me.data.user);
          else await clearAuthSession();
        }
      } catch {
        /* ignore */
      } finally {
        clearTimeout(spinnerCap);
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
      clearTimeout(spinnerCap);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [refreshAccess, scheduleRefresh]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active' && accessToken) void refreshProfile();
    });
    return () => sub.remove();
  }, [accessToken, refreshProfile]);

  const value = useMemo(
    () => ({
      user,
      accessToken,
      isAuthenticated: !!user && !!accessToken,
      hydrated,
      busy,
      error,
      setError,
      biometricAvailable,
      biometricEnabled,
      authRequired: isAuthRequired(),
      loginEmail,
      register,
      loginGoogle,
      loginApple,
      loginWithOtp,
      loginWithBiometric,
      enableBiometric,
      logout,
      refreshProfile,
      verifyEmail,
      refreshAccess,
    }),
    [
      user,
      accessToken,
      hydrated,
      busy,
      error,
      biometricAvailable,
      biometricEnabled,
      loginEmail,
      register,
      loginGoogle,
      loginApple,
      loginWithOtp,
      loginWithBiometric,
      enableBiometric,
      logout,
      refreshProfile,
      verifyEmail,
      refreshAccess,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export function useOptionalAuth() {
  return useContext(AuthContext);
}
