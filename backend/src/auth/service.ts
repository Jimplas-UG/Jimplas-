import { randomBytes, randomInt, randomUUID } from 'node:crypto';
import {
  accessTtlSec,
  refreshTtlSec,
  signAccessToken,
  signRefreshToken,
  verifyRefreshToken,
} from './jwt';
import { verifyAppleIdToken, verifyGoogleIdToken } from './oauth';
import {
  hashOpaque,
  hashPassword,
  validatePasswordPolicy,
  verifyOpaque,
  verifyPassword,
} from './password';
import {
  bumpOtpAttempts,
  createUser,
  deleteEmailToken,
  deleteOtp,
  findEmailToken,
  findOtp,
  findRefreshToken,
  findUserByEmail,
  findUserById,
  findUserByPhone,
  findUserByProvider,
  normalizeEmail,
  normalizePhone,
  revokeAllUserRefreshTokens,
  revokeRefreshToken,
  saveEmailToken,
  saveOtp,
  saveRefreshToken,
  saveUser,
  updateUser,
} from './store';
import type { AuthTokens, PublicUser, UserRecord } from './types';
import { toPublicUser } from './types';
import { validateEmail, validateFullName, validateOtpCode, validatePhone, validateTerms } from './validation';

const OTP_TTL_MS = 10 * 60 * 1000;
const EMAIL_TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
const RESET_TOKEN_TTL_MS = 60 * 60 * 1000;
const MAX_OTP_ATTEMPTS = 5;

const loginAttempts = new Map<string, { count: number; until: number }>();

function rateLimitKey(ip: string, target: string) {
  return `${ip}:${target}`;
}

function checkRateLimit(ip: string, target: string, max = 8, windowMs = 15 * 60 * 1000): string | null {
  const key = rateLimitKey(ip, target);
  const now = Date.now();
  const row = loginAttempts.get(key);
  if (row && row.until > now && row.count >= max) {
    return 'Too many attempts. Please wait a few minutes and try again.';
  }
  if (!row || row.until <= now) {
    loginAttempts.set(key, { count: 1, until: now + windowMs });
    return null;
  }
  row.count += 1;
  return row.count >= max ? 'Too many attempts. Please wait a few minutes and try again.' : null;
}

function clearRateLimit(ip: string, target: string) {
  loginAttempts.delete(rateLimitKey(ip, target));
}

function genOtp(): string {
  return String(randomInt(100000, 999999));
}

function genToken(): string {
  return randomBytes(32).toString('hex');
}

async function issueTokens(user: UserRecord): Promise<AuthTokens> {
  const tokenId = randomUUID();
  const refreshToken = await signRefreshToken(user.id, tokenId);
  const accessToken = await signAccessToken(user.id, user.email);
  const expiresAt = new Date(Date.now() + refreshTtlSec() * 1000).toISOString();
  saveRefreshToken({
    id: tokenId,
    userId: user.id,
    tokenHash: hashOpaque(refreshToken),
    expiresAt,
    createdAt: new Date().toISOString(),
    revoked: false,
  });
  return { accessToken, refreshToken, expiresIn: accessTtlSec() };
}

function devOtpEnabled() {
  return process.env.AUTH_DEV_OTP === '1' || process.env.NODE_ENV !== 'production';
}

async function dispatchOtp(channel: 'email' | 'phone', target: string, code: string, purpose: string) {
  const msg = `[BSV32 Auth] ${purpose} OTP for ${target}: ${code}`;
  if (devOtpEnabled()) {
    console.info(msg);
    return { devCode: code };
  }
  // Production: plug SMTP/SMS provider via env (AUTH_SMTP_URL, AUTH_SMS_WEBHOOK)
  console.info(`[BSV32 Auth] OTP sent (${channel}) purpose=${purpose} target=${target.slice(0, 3)}***`);
  return {};
}

async function dispatchEmailLink(email: string, subject: string, link: string) {
  const msg = `[BSV32 Auth] ${subject} for ${email}: ${link}`;
  if (devOtpEnabled()) {
    console.info(msg);
    return { devLink: link };
  }
  console.info(`[BSV32 Auth] Email dispatched: ${subject} → ${email}`);
  return {};
}

export class AuthError extends Error {
  status: number;
  constructor(message: string, status = 400) {
    super(message);
    this.status = status;
  }
}

export async function registerUser(
  input: {
    fullName: string;
    email: string;
    phone?: string;
    password: string;
    confirmPassword: string;
    termsAccepted: boolean;
  },
  ip: string,
): Promise<{ user: PublicUser; tokens: AuthTokens; verification?: Record<string, string> }> {
  const emailErr = validateEmail(input.email);
  if (emailErr) throw new AuthError(emailErr);
  const nameErr = validateFullName(input.fullName);
  if (nameErr) throw new AuthError(nameErr);
  const termsErr = validateTerms(!!input.termsAccepted);
  if (termsErr) throw new AuthError(termsErr);
  if (input.phone) {
    const phoneErr = validatePhone(input.phone);
    if (phoneErr) throw new AuthError(phoneErr);
  }
  const passErr = validatePasswordPolicy(input.password);
  if (passErr) throw new AuthError(passErr);
  if (input.password !== input.confirmPassword) throw new AuthError('Passwords do not match');

  const email = normalizeEmail(input.email);
  const rl = checkRateLimit(ip, email);
  if (rl) throw new AuthError(rl, 429);
  if (findUserByEmail(email)) throw new AuthError('An account with this email already exists', 409);

  const user = createUser({
    email,
    phone: input.phone ? normalizePhone(input.phone) : null,
    fullName: input.fullName.trim(),
    passwordHash: hashPassword(input.password),
    emailVerified: false,
    phoneVerified: false,
    avatarUrl: null,
    providers: {},
    termsAcceptedAt: new Date().toISOString(),
  });

  const verifyToken = genToken();
  saveEmailToken({
    token: verifyToken,
    userId: user.id,
    purpose: 'verify_email',
    expiresAt: new Date(Date.now() + EMAIL_TOKEN_TTL_MS).toISOString(),
  });
  const base = process.env.AUTH_APP_URL?.trim() || 'bsv32://verify-email';
  const verification = await dispatchEmailLink(
    email,
    'Verify your email',
    `${base}?token=${verifyToken}`,
  );

  const tokens = await issueTokens(user);
  clearRateLimit(ip, email);
  return { user: toPublicUser(user), tokens, verification: verification as Record<string, string> };
}

export async function loginWithEmail(
  email: string,
  password: string,
  ip: string,
): Promise<{ user: PublicUser; tokens: AuthTokens }> {
  const emailErr = validateEmail(email);
  if (emailErr) throw new AuthError(emailErr);
  const norm = normalizeEmail(email);
  const rl = checkRateLimit(ip, norm);
  if (rl) throw new AuthError(rl, 429);

  const user = findUserByEmail(norm);
  if (!user?.passwordHash || !verifyPassword(password, user.passwordHash)) {
    throw new AuthError('Invalid email or password', 401);
  }
  clearRateLimit(ip, norm);
  const tokens = await issueTokens(user);
  return { user: toPublicUser(user), tokens };
}

export async function sendPhoneOtp(phone: string, purpose: 'login' | 'verify_email' | 'reset_password', ip: string) {
  const phoneErr = validatePhone(phone);
  if (phoneErr) throw new AuthError(phoneErr);
  const norm = normalizePhone(phone);
  const rl = checkRateLimit(ip, norm);
  if (rl) throw new AuthError(rl, 429);

  const code = genOtp();
  saveOtp({
    id: randomUUID(),
    target: norm,
    channel: 'phone',
    purpose,
    codeHash: hashOpaque(code),
    expiresAt: new Date(Date.now() + OTP_TTL_MS).toISOString(),
    attempts: 0,
  });
  const meta = await dispatchOtp('phone', norm, code, purpose);
  return { ok: true, expiresIn: OTP_TTL_MS / 1000, ...meta };
}

export async function sendEmailOtp(email: string, purpose: 'login' | 'reset_password', ip: string) {
  const emailErr = validateEmail(email);
  if (emailErr) throw new AuthError(emailErr);
  const norm = normalizeEmail(email);
  const rl = checkRateLimit(ip, norm);
  if (rl) throw new AuthError(rl, 429);

  const code = genOtp();
  saveOtp({
    id: randomUUID(),
    target: norm,
    channel: 'email',
    purpose,
    codeHash: hashOpaque(code),
    expiresAt: new Date(Date.now() + OTP_TTL_MS).toISOString(),
    attempts: 0,
  });
  const meta = await dispatchOtp('email', norm, code, purpose);
  return { ok: true, expiresIn: OTP_TTL_MS / 1000, ...meta };
}

export async function verifyOtpLogin(
  target: string,
  code: string,
  channel: 'email' | 'phone',
  ip: string,
): Promise<{ user: PublicUser; tokens: AuthTokens }> {
  const codeErr = validateOtpCode(code);
  if (codeErr) throw new AuthError(codeErr);
  const norm = channel === 'email' ? normalizeEmail(target) : normalizePhone(target);
  const rl = checkRateLimit(ip, `otp:${norm}`);
  if (rl) throw new AuthError(rl, 429);

  const otp = findOtp(norm, 'login');
  if (!otp) throw new AuthError('Code expired or not found. Request a new one.', 401);
  if (otp.attempts >= MAX_OTP_ATTEMPTS) throw new AuthError('Too many invalid attempts. Request a new code.', 429);
  if (new Date(otp.expiresAt).getTime() < Date.now()) {
    deleteOtp(otp.id);
    throw new AuthError('Code expired. Request a new one.', 401);
  }
  if (!verifyOpaque(code.trim(), otp.codeHash)) {
    bumpOtpAttempts(otp.id);
    throw new AuthError('Invalid verification code', 401);
  }
  deleteOtp(otp.id);

  let user = channel === 'email' ? findUserByEmail(norm) : findUserByPhone(norm);
  if (!user && channel === 'phone') {
    user = createUser({
      email: `${norm.replace(/\D/g, '')}@phone.bsv32.local`,
      phone: norm,
      fullName: 'Trader',
      passwordHash: null,
      emailVerified: false,
      phoneVerified: true,
      avatarUrl: null,
      providers: {},
      termsAcceptedAt: new Date().toISOString(),
    });
  }
  if (!user) throw new AuthError('No account found for this contact', 404);
  if (channel === 'phone' && !user.phoneVerified) {
    user = updateUser(user.id, { phoneVerified: true })!;
  }
  clearRateLimit(ip, `otp:${norm}`);
  const tokens = await issueTokens(user);
  return { user: toPublicUser(user), tokens };
}

export async function loginWithOAuth(
  provider: 'google' | 'apple',
  idToken: string,
  ip: string,
): Promise<{ user: PublicUser; tokens: AuthTokens }> {
  const profile =
    provider === 'google' ? await verifyGoogleIdToken(idToken) : await verifyAppleIdToken(idToken);
  if (!profile) throw new AuthError(`Invalid ${provider} token`, 401);

  const rl = checkRateLimit(ip, `${provider}:${profile.providerId}`);
  if (rl) throw new AuthError(rl, 429);

  let user = findUserByProvider(provider, profile.providerId);
  if (!user) {
    const byEmail = findUserByEmail(profile.email);
    if (byEmail) {
      user = updateUser(byEmail.id, {
        providers: { ...byEmail.providers, [provider]: profile.providerId },
        emailVerified: byEmail.emailVerified || profile.emailVerified,
        fullName: byEmail.fullName || profile.fullName,
      })!;
    } else {
      user = createUser({
        email: profile.email,
        phone: null,
        fullName: profile.fullName,
        passwordHash: null,
        emailVerified: profile.emailVerified,
        phoneVerified: false,
        avatarUrl: null,
        providers: { [provider]: profile.providerId },
        termsAcceptedAt: new Date().toISOString(),
      });
    }
  }
  clearRateLimit(ip, `${provider}:${profile.providerId}`);
  const tokens = await issueTokens(user);
  return { user: toPublicUser(user), tokens };
}

export async function refreshSession(refreshToken: string): Promise<{ user: PublicUser; tokens: AuthTokens }> {
  const claims = await verifyRefreshToken(refreshToken);
  if (!claims) throw new AuthError('Session expired. Please sign in again.', 401);
  const stored = findRefreshToken(claims.tid);
  if (!stored || stored.revoked || stored.userId !== claims.sub) {
    throw new AuthError('Session expired. Please sign in again.', 401);
  }
  if (new Date(stored.expiresAt).getTime() < Date.now()) {
    revokeRefreshToken(stored.id);
    throw new AuthError('Session expired. Please sign in again.', 401);
  }
  if (!verifyOpaque(refreshToken, stored.tokenHash)) {
    revokeRefreshToken(stored.id);
    throw new AuthError('Session invalid. Please sign in again.', 401);
  }
  const user = findUserById(claims.sub);
  if (!user) throw new AuthError('User not found', 404);
  revokeRefreshToken(stored.id);
  const tokens = await issueTokens(user);
  return { user: toPublicUser(user), tokens };
}

export async function logoutUser(refreshToken?: string) {
  if (!refreshToken) return;
  const claims = await verifyRefreshToken(refreshToken);
  if (claims) revokeRefreshToken(claims.tid);
}

export async function logoutAll(userId: string) {
  revokeAllUserRefreshTokens(userId);
}

export function getUserProfile(userId: string): PublicUser {
  const user = findUserById(userId);
  if (!user) throw new AuthError('User not found', 404);
  return toPublicUser(user);
}

export async function updateProfile(
  userId: string,
  patch: { fullName?: string; phone?: string; avatarUrl?: string | null },
): Promise<PublicUser> {
  const user = findUserById(userId);
  if (!user) throw new AuthError('User not found', 404);
  if (patch.fullName) {
    const err = validateFullName(patch.fullName);
    if (err) throw new AuthError(err);
  }
  if (patch.phone) {
    const err = validatePhone(patch.phone);
    if (err) throw new AuthError(err);
  }
  const next = updateUser(userId, {
    fullName: patch.fullName?.trim() ?? user.fullName,
    phone: patch.phone !== undefined ? normalizePhone(patch.phone) : user.phone,
    avatarUrl: patch.avatarUrl !== undefined ? patch.avatarUrl : user.avatarUrl,
  });
  if (!next) throw new AuthError('Update failed', 500);
  return toPublicUser(next);
}

export async function changePassword(userId: string, currentPassword: string, newPassword: string) {
  const user = findUserById(userId);
  if (!user) throw new AuthError('User not found', 404);
  if (!user.passwordHash) throw new AuthError('Password login not enabled for this account', 400);
  if (!verifyPassword(currentPassword, user.passwordHash)) {
    throw new AuthError('Current password is incorrect', 401);
  }
  const passErr = validatePasswordPolicy(newPassword);
  if (passErr) throw new AuthError(passErr);
  updateUser(userId, { passwordHash: hashPassword(newPassword) });
  revokeAllUserRefreshTokens(userId);
}

export async function verifyEmailToken(token: string): Promise<PublicUser> {
  const rec = findEmailToken(token, 'verify_email');
  if (!rec) throw new AuthError('Invalid or expired verification link', 400);
  if (new Date(rec.expiresAt).getTime() < Date.now()) {
    deleteEmailToken(token);
    throw new AuthError('Verification link expired', 400);
  }
  const user = updateUser(rec.userId, { emailVerified: true });
  if (!user) throw new AuthError('User not found', 404);
  deleteEmailToken(token);
  return toPublicUser(user);
}

export async function requestPasswordReset(email: string, ip: string, via: 'email' | 'otp' = 'email') {
  const emailErr = validateEmail(email);
  if (emailErr) throw new AuthError(emailErr);
  const norm = normalizeEmail(email);
  const user = findUserByEmail(norm);
  if (!user) return { ok: true, message: 'If an account exists, reset instructions were sent.' };

  if (via === 'otp') {
    return sendEmailOtp(norm, 'reset_password', ip);
  }

  const token = genToken();
  saveEmailToken({
    token,
    userId: user.id,
    purpose: 'reset_password',
    expiresAt: new Date(Date.now() + RESET_TOKEN_TTL_MS).toISOString(),
  });
  const base = process.env.AUTH_APP_URL?.trim() || 'bsv32://reset-password';
  const meta = await dispatchEmailLink(norm, 'Reset your password', `${base}?token=${token}`);
  return { ok: true, message: 'If an account exists, reset instructions were sent.', ...meta };
}

export async function resetPasswordWithToken(token: string, password: string, confirmPassword: string) {
  const passErr = validatePasswordPolicy(password);
  if (passErr) throw new AuthError(passErr);
  if (password !== confirmPassword) throw new AuthError('Passwords do not match');
  const rec = findEmailToken(token, 'reset_password');
  if (!rec) throw new AuthError('Invalid or expired reset link', 400);
  if (new Date(rec.expiresAt).getTime() < Date.now()) {
    deleteEmailToken(token);
    throw new AuthError('Reset link expired', 400);
  }
  updateUser(rec.userId, { passwordHash: hashPassword(password) });
  deleteEmailToken(token);
  revokeAllUserRefreshTokens(rec.userId);
  return { ok: true };
}

export async function resetPasswordWithOtp(email: string, code: string, password: string, confirmPassword: string) {
  const passErr = validatePasswordPolicy(password);
  if (passErr) throw new AuthError(passErr);
  if (password !== confirmPassword) throw new AuthError('Passwords do not match');
  const norm = normalizeEmail(email);
  const otp = findOtp(norm, 'reset_password');
  if (!otp || new Date(otp.expiresAt).getTime() < Date.now()) {
    throw new AuthError('Code expired. Request a new one.', 400);
  }
  if (!verifyOpaque(code.trim(), otp.codeHash)) {
    bumpOtpAttempts(otp.id);
    throw new AuthError('Invalid verification code', 401);
  }
  const user = findUserByEmail(norm);
  if (!user) throw new AuthError('User not found', 404);
  updateUser(user.id, { passwordHash: hashPassword(password) });
  deleteOtp(otp.id);
  revokeAllUserRefreshTokens(user.id);
  return { ok: true };
}

export async function resendVerification(userId: string) {
  const user = findUserById(userId);
  if (!user) throw new AuthError('User not found', 404);
  if (user.emailVerified) return { ok: true, message: 'Email already verified' };
  const verifyToken = genToken();
  saveEmailToken({
    token: verifyToken,
    userId: user.id,
    purpose: 'verify_email',
    expiresAt: new Date(Date.now() + EMAIL_TOKEN_TTL_MS).toISOString(),
  });
  const base = process.env.AUTH_APP_URL?.trim() || 'bsv32://verify-email';
  const meta = await dispatchEmailLink(user.email, 'Verify your email', `${base}?token=${verifyToken}`);
  return { ok: true, ...meta };
}
