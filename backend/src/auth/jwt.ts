import { SignJWT, jwtVerify } from 'jose';

const ACCESS_TTL_SEC = Number(process.env.AUTH_ACCESS_TTL_SEC) || 15 * 60;
const REFRESH_TTL_SEC = Number(process.env.AUTH_REFRESH_TTL_SEC) || 30 * 24 * 60 * 60;

function secretKey(): Uint8Array {
  const raw = process.env.AUTH_JWT_SECRET?.trim() || process.env.DESK_API_KEY?.trim() || 'bsv32-dev-auth-secret-change-me';
  return new TextEncoder().encode(raw);
}

export interface AccessClaims {
  sub: string;
  email: string;
  type: 'access';
}

export interface RefreshClaims {
  sub: string;
  tid: string;
  type: 'refresh';
}

export async function signAccessToken(userId: string, email: string): Promise<string> {
  return new SignJWT({ email, type: 'access' })
    .setProtectedHeader({ alg: 'HS256' })
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime(`${ACCESS_TTL_SEC}s`)
    .setIssuer('bsv32')
    .sign(secretKey());
}

export async function signRefreshToken(userId: string, tokenId: string): Promise<string> {
  return new SignJWT({ tid: tokenId, type: 'refresh' })
    .setProtectedHeader({ alg: 'HS256' })
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime(`${REFRESH_TTL_SEC}s`)
    .setIssuer('bsv32')
    .sign(secretKey());
}

export async function verifyAccessToken(token: string): Promise<AccessClaims | null> {
  try {
    const { payload } = await jwtVerify(token, secretKey(), { issuer: 'bsv32' });
    if (payload.type !== 'access' || typeof payload.sub !== 'string') return null;
    return {
      sub: payload.sub,
      email: String(payload.email ?? ''),
      type: 'access',
    };
  } catch {
    return null;
  }
}

export async function verifyRefreshToken(token: string): Promise<RefreshClaims | null> {
  try {
    const { payload } = await jwtVerify(token, secretKey(), { issuer: 'bsv32' });
    if (payload.type !== 'refresh' || typeof payload.sub !== 'string' || typeof payload.tid !== 'string') {
      return null;
    }
    return { sub: payload.sub, tid: payload.tid, type: 'refresh' };
  } catch {
    return null;
  }
}

export function accessTtlSec(): number {
  return ACCESS_TTL_SEC;
}

export function refreshTtlSec(): number {
  return REFRESH_TTL_SEC;
}
