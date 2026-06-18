export type AuthProvider = 'email' | 'google' | 'apple' | 'phone';

export interface UserRecord {
  id: string;
  email: string;
  phone: string | null;
  fullName: string;
  passwordHash: string | null;
  emailVerified: boolean;
  phoneVerified: boolean;
  avatarUrl: string | null;
  providers: Partial<Record<'google' | 'apple', string>>;
  termsAcceptedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RefreshTokenRecord {
  id: string;
  userId: string;
  tokenHash: string;
  expiresAt: string;
  createdAt: string;
  revoked: boolean;
}

export interface OtpRecord {
  id: string;
  target: string;
  channel: 'email' | 'phone';
  purpose: 'login' | 'verify_email' | 'reset_password';
  codeHash: string;
  expiresAt: string;
  attempts: number;
}

export interface EmailTokenRecord {
  token: string;
  userId: string;
  purpose: 'verify_email' | 'reset_password';
  expiresAt: string;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface PublicUser {
  id: string;
  email: string;
  phone: string | null;
  fullName: string;
  emailVerified: boolean;
  phoneVerified: boolean;
  avatarUrl: string | null;
  providers: string[];
  createdAt: string;
}

export function toPublicUser(u: UserRecord): PublicUser {
  const providers: string[] = [];
  if (u.passwordHash) providers.push('email');
  if (u.providers.google) providers.push('google');
  if (u.providers.apple) providers.push('apple');
  if (u.phoneVerified) providers.push('phone');
  return {
    id: u.id,
    email: u.email,
    phone: u.phone,
    fullName: u.fullName,
    emailVerified: u.emailVerified,
    phoneVerified: u.phoneVerified,
    avatarUrl: u.avatarUrl,
    providers,
    createdAt: u.createdAt,
  };
}
