import { createRemoteJWKSet, jwtVerify } from 'jose';

const GOOGLE_JWKS = createRemoteJWKSet(new URL('https://www.googleapis.com/oauth2/v3/certs'));
const APPLE_JWKS = createRemoteJWKSet(new URL('https://appleid.apple.com/auth/keys'));

export interface OAuthProfile {
  provider: 'google' | 'apple';
  providerId: string;
  email: string;
  fullName: string;
  emailVerified: boolean;
}

export async function verifyGoogleIdToken(idToken: string): Promise<OAuthProfile | null> {
  const clientId = process.env.AUTH_GOOGLE_CLIENT_ID?.trim();
  try {
    if (clientId) {
      const { payload } = await jwtVerify(idToken, GOOGLE_JWKS, {
        issuer: ['https://accounts.google.com', 'accounts.google.com'],
        audience: clientId,
      });
      const sub = String(payload.sub ?? '');
      const email = String(payload.email ?? '').toLowerCase();
      if (!sub || !email) return null;
      return {
        provider: 'google',
        providerId: sub,
        email,
        fullName: String(payload.name ?? email.split('@')[0]),
        emailVerified: payload.email_verified === true,
      };
    }
    const res = await fetch(`https://oauth2.googleapis.com/tokeninfo?id_token=${encodeURIComponent(idToken)}`);
    if (!res.ok) return null;
    const j = (await res.json()) as Record<string, string>;
    const sub = j.sub;
    const email = (j.email ?? '').toLowerCase();
    if (!sub || !email) return null;
    if (clientId && j.aud !== clientId) return null;
    return {
      provider: 'google',
      providerId: sub,
      email,
      fullName: j.name || email.split('@')[0],
      emailVerified: j.email_verified === 'true',
    };
  } catch {
    return null;
  }
}

export async function verifyAppleIdToken(idToken: string): Promise<OAuthProfile | null> {
  const clientId = process.env.AUTH_APPLE_CLIENT_ID?.trim();
  if (!clientId) return null;
  try {
    const { payload } = await jwtVerify(idToken, APPLE_JWKS, {
      issuer: 'https://appleid.apple.com',
      audience: clientId,
    });
    const sub = String(payload.sub ?? '');
    const email = String(payload.email ?? '').toLowerCase();
    if (!sub) return null;
    return {
      provider: 'apple',
      providerId: sub,
      email: email || `${sub}@privaterelay.appleid.com`,
      fullName: 'Apple User',
      emailVerified: payload.email_verified === true || !!email,
    };
  } catch {
    return null;
  }
}
