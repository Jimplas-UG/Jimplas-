import { getDeskApiUrl } from './envConfig';

function baseUrl() {
  return getDeskApiUrl().replace(/\/$/, '');
}

function parseDetail(j, fallback = 'Request failed') {
  if (typeof j?.detail === 'string') return j.detail;
  if (typeof j?.error === 'string') return j.error;
  return fallback;
}

async function authFetch(path, { method = 'GET', body, accessToken, timeoutMs = 20000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const res = await fetch(`${baseUrl()}${path}`, {
      method,
      headers,
      body: body != null ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    let json = {};
    try {
      json = text ? JSON.parse(text) : {};
    } catch {
      json = { detail: text || `HTTP ${res.status}` };
    }
    if (!res.ok) {
      return { ok: false, status: res.status, error: parseDetail(json, `HTTP ${res.status}`), data: json };
    }
    return { ok: true, status: res.status, data: json };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/abort/i.test(msg)) {
      return { ok: false, status: 0, error: 'Request timed out. Check your network and desk API URL.' };
    }
    return { ok: false, status: 0, error: msg.includes('Network') ? 'Network error — cannot reach auth server.' : msg };
  } finally {
    clearTimeout(timer);
  }
}

export function friendlyAuthError(error, fallback = 'Something went wrong') {
  if (!error) return fallback;
  if (/invalid email or password/i.test(error)) return 'Invalid email or password.';
  if (/session expired|unauthorized/i.test(error)) return 'Your session expired. Please sign in again.';
  if (/too many attempts/i.test(error)) return error;
  if (/network|timed out|fetch|failed to fetch|econnrefused|connection refused/i.test(error)) {
    return 'Cannot reach desk API. Start it first: cd backend && npm run desk-api';
  }
  return error;
}

/** True when auth API failed due to network/timeout — session should be kept. */
export function isAuthNetworkError(res) {
  if (!res || res.ok) return false;
  if (res.status === 0) return true;
  return /network|timed out|abort|fetch|failed to fetch|econnrefused|cannot reach/i.test(res.error || '');
}

export async function apiRegister(payload) {
  return authFetch('/v1/auth/register', { method: 'POST', body: payload });
}

export async function apiLoginEmail(email, password) {
  return authFetch('/v1/auth/login', { method: 'POST', body: { email, password } });
}

export async function apiSendPhoneOtp(phone) {
  return authFetch('/v1/auth/login/phone/send', { method: 'POST', body: { phone } });
}

export async function apiSendEmailOtp(email) {
  return authFetch('/v1/auth/login/otp/send', { method: 'POST', body: { email } });
}

export async function apiVerifyOtp(target, code, channel) {
  return authFetch('/v1/auth/login/otp/verify', { method: 'POST', body: { target, code, channel } });
}

export async function apiOAuthGoogle(idToken) {
  return authFetch('/v1/auth/oauth/google', { method: 'POST', body: { idToken } });
}

export async function apiOAuthApple(idToken) {
  return authFetch('/v1/auth/oauth/apple', { method: 'POST', body: { idToken } });
}

export async function apiRefresh(refreshToken, timeoutMs = 20000) {
  return authFetch('/v1/auth/refresh', { method: 'POST', body: { refreshToken }, timeoutMs });
}

export async function apiLogout(accessToken, refreshToken, allDevices = false) {
  return authFetch('/v1/auth/logout', {
    method: 'POST',
    accessToken,
    body: { refreshToken, allDevices },
  });
}

export async function apiMe(accessToken, timeoutMs = 5000) {
  return authFetch('/v1/auth/me', { accessToken, timeoutMs });
}

export async function apiUpdateProfile(accessToken, patch) {
  return authFetch('/v1/auth/me', { method: 'PATCH', accessToken, body: patch });
}

export async function apiChangePassword(accessToken, currentPassword, newPassword) {
  return authFetch('/v1/auth/change-password', {
    method: 'POST',
    accessToken,
    body: { currentPassword, newPassword },
  });
}

export async function apiVerifyEmail(token) {
  return authFetch('/v1/auth/verify-email', { method: 'POST', body: { token } });
}

export async function apiResendVerification(accessToken) {
  return authFetch('/v1/auth/resend-verification', { method: 'POST', accessToken });
}

export async function apiForgotPassword(email, via = 'email') {
  return authFetch('/v1/auth/forgot-password', { method: 'POST', body: { email, via } });
}

export async function apiResetPassword(payload) {
  return authFetch('/v1/auth/reset-password', { method: 'POST', body: payload });
}

export function extractAuthPayload(data) {
  if (!data?.tokens || !data?.user) return null;
  return {
    accessToken: data.tokens.accessToken,
    refreshToken: data.tokens.refreshToken,
    expiresIn: data.tokens.expiresIn,
    user: data.user,
  };
}
