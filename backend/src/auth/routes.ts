import type { IncomingMessage, ServerResponse } from 'node:http';
import { verifyAccessToken } from './jwt';
import {
  AuthError,
  changePassword,
  getUserProfile,
  loginWithEmail,
  loginWithOAuth,
  logoutAll,
  logoutUser,
  refreshSession,
  registerUser,
  requestPasswordReset,
  resendVerification,
  resetPasswordWithOtp,
  resetPasswordWithToken,
  sendEmailOtp,
  sendPhoneOtp,
  updateProfile,
  verifyEmailToken,
  verifyOtpLogin,
} from './service';

function clientIp(req: IncomingMessage): string {
  const fwd = req.headers['x-forwarded-for'];
  if (typeof fwd === 'string' && fwd) return fwd.split(',')[0].trim();
  return req.socket.remoteAddress ?? '0.0.0.0';
}

function sendJson(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

async function readBody<T>(req: IncomingMessage): Promise<T> {
  const chunks: Buffer[] = [];
  let total = 0;
  return new Promise((resolve, reject) => {
    req.on('data', (c) => {
      total += c.length;
      if (total > 256 * 1024) {
        req.destroy();
        reject(new Error('body too large'));
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

export async function extractUserId(req: IncomingMessage): Promise<string | null> {
  const h = req.headers.authorization ?? '';
  const m = /^Bearer\s+(.+)$/i.exec(h);
  if (!m) return null;
  const claims = await verifyAccessToken(m[1]);
  return claims?.sub ?? null;
}

export function isAuthPath(pathname: string): boolean {
  return pathname.startsWith('/v1/auth/');
}

export async function handleAuthRoute(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<boolean> {
  const path = url.pathname;
  if (!isAuthPath(path)) return false;

  const ip = clientIp(req);

  try {
    if (path === '/v1/auth/register' && req.method === 'POST') {
      const body = await readBody<{
        fullName: string;
        email: string;
        phone?: string;
        password: string;
        confirmPassword: string;
        termsAccepted: boolean;
      }>(req);
      const out = await registerUser(body, ip);
      sendJson(res, 201, { ok: true, ...out });
      return true;
    }

    if (path === '/v1/auth/login' && req.method === 'POST') {
      const body = await readBody<{ email: string; password: string }>(req);
      const out = await loginWithEmail(body.email, body.password, ip);
      sendJson(res, 200, { ok: true, ...out });
      return true;
    }

    if (path === '/v1/auth/login/phone/send' && req.method === 'POST') {
      const body = await readBody<{ phone: string }>(req);
      const out = await sendPhoneOtp(body.phone, 'login', ip);
      sendJson(res, 200, out);
      return true;
    }

    if (path === '/v1/auth/login/otp/send' && req.method === 'POST') {
      const body = await readBody<{ email: string }>(req);
      const out = await sendEmailOtp(body.email, 'login', ip);
      sendJson(res, 200, out);
      return true;
    }

    if (path === '/v1/auth/login/otp/verify' && req.method === 'POST') {
      const body = await readBody<{ target: string; code: string; channel?: 'email' | 'phone' }>(req);
      const channel = body.channel ?? (body.target.includes('@') ? 'email' : 'phone');
      const out = await verifyOtpLogin(body.target, body.code, channel, ip);
      sendJson(res, 200, { ok: true, ...out });
      return true;
    }

    if (path === '/v1/auth/oauth/google' && req.method === 'POST') {
      const body = await readBody<{ idToken: string }>(req);
      const out = await loginWithOAuth('google', body.idToken, ip);
      sendJson(res, 200, { ok: true, ...out });
      return true;
    }

    if (path === '/v1/auth/oauth/apple' && req.method === 'POST') {
      const body = await readBody<{ idToken: string }>(req);
      const out = await loginWithOAuth('apple', body.idToken, ip);
      sendJson(res, 200, { ok: true, ...out });
      return true;
    }

    if (path === '/v1/auth/refresh' && req.method === 'POST') {
      const body = await readBody<{ refreshToken: string }>(req);
      const out = await refreshSession(body.refreshToken);
      sendJson(res, 200, { ok: true, ...out });
      return true;
    }

    if (path === '/v1/auth/logout' && req.method === 'POST') {
      const body = await readBody<{ refreshToken?: string; allDevices?: boolean }>(req);
      const userId = await extractUserId(req);
      if (body.allDevices && userId) await logoutAll(userId);
      else await logoutUser(body.refreshToken);
      sendJson(res, 200, { ok: true });
      return true;
    }

    if (path === '/v1/auth/me' && req.method === 'GET') {
      const userId = await extractUserId(req);
      if (!userId) {
        sendJson(res, 401, { detail: 'Unauthorized' });
        return true;
      }
      sendJson(res, 200, { ok: true, user: getUserProfile(userId) });
      return true;
    }

    if (path === '/v1/auth/me' && req.method === 'PATCH') {
      const userId = await extractUserId(req);
      if (!userId) {
        sendJson(res, 401, { detail: 'Unauthorized' });
        return true;
      }
      const body = await readBody<{ fullName?: string; phone?: string; avatarUrl?: string | null }>(req);
      const user = await updateProfile(userId, body);
      sendJson(res, 200, { ok: true, user });
      return true;
    }

    if (path === '/v1/auth/change-password' && req.method === 'POST') {
      const userId = await extractUserId(req);
      if (!userId) {
        sendJson(res, 401, { detail: 'Unauthorized' });
        return true;
      }
      const body = await readBody<{ currentPassword: string; newPassword: string }>(req);
      await changePassword(userId, body.currentPassword, body.newPassword);
      sendJson(res, 200, { ok: true });
      return true;
    }

    if (path === '/v1/auth/verify-email' && req.method === 'POST') {
      const body = await readBody<{ token: string }>(req);
      const user = await verifyEmailToken(body.token);
      sendJson(res, 200, { ok: true, user });
      return true;
    }

    if (path === '/v1/auth/resend-verification' && req.method === 'POST') {
      const userId = await extractUserId(req);
      if (!userId) {
        sendJson(res, 401, { detail: 'Unauthorized' });
        return true;
      }
      const out = await resendVerification(userId);
      sendJson(res, 200, out);
      return true;
    }

    if (path === '/v1/auth/forgot-password' && req.method === 'POST') {
      const body = await readBody<{ email: string; via?: 'email' | 'otp' }>(req);
      const out = await requestPasswordReset(body.email, ip, body.via ?? 'email');
      sendJson(res, 200, out);
      return true;
    }

    if (path === '/v1/auth/reset-password' && req.method === 'POST') {
      const body = await readBody<{
        token?: string;
        email?: string;
        code?: string;
        password: string;
        confirmPassword: string;
      }>(req);
      if (body.token) {
        await resetPasswordWithToken(body.token, body.password, body.confirmPassword);
      } else if (body.email && body.code) {
        await resetPasswordWithOtp(body.email, body.code, body.password, body.confirmPassword);
      } else {
        throw new AuthError('Provide reset token or email + OTP code');
      }
      sendJson(res, 200, { ok: true });
      return true;
    }

    sendJson(res, 404, { detail: 'Not found' });
    return true;
  } catch (e) {
    if (e instanceof AuthError) {
      sendJson(res, e.status, { detail: e.message });
      return true;
    }
    console.error('[auth]', e);
    sendJson(res, 500, { detail: 'Authentication service error' });
    return true;
  }
}
