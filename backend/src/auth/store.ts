import { randomUUID } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { EmailTokenRecord, OtpRecord, RefreshTokenRecord, UserRecord } from './types';

const DATA_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../auth/data');
const USERS_FILE = path.join(DATA_DIR, 'users.json');
const REFRESH_FILE = path.join(DATA_DIR, 'refresh_tokens.json');
const OTP_FILE = path.join(DATA_DIR, 'otps.json');
const EMAIL_TOKENS_FILE = path.join(DATA_DIR, 'email_tokens.json');

type DbShape<T> = { items: T[] };

const fileCache = new Map<string, { mtimeMs: number; data: DbShape<unknown> }>();

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function readDbCached<T>(file: string): DbShape<T> {
  ensureDataDir();
  if (!fs.existsSync(file)) return { items: [] };
  try {
    const mtimeMs = fs.statSync(file).mtimeMs;
    const hit = fileCache.get(file);
    if (hit && hit.mtimeMs === mtimeMs) return hit.data as DbShape<T>;
    const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    const data: DbShape<T> = Array.isArray(raw?.items) ? raw : { items: [] };
    fileCache.set(file, { mtimeMs, data: data as DbShape<unknown> });
    return data;
  } catch {
    return { items: [] };
  }
}

function readDb<T>(file: string): DbShape<T> {
  return readDbCached<T>(file);
}

function writeDb<T>(file: string, data: DbShape<T>) {
  ensureDataDir();
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  fs.renameSync(tmp, file);
  try {
    fileCache.set(file, { mtimeMs: fs.statSync(file).mtimeMs, data: data as DbShape<unknown> });
  } catch {
    fileCache.delete(file);
  }
}

export function listUsers(): UserRecord[] {
  return readDb<UserRecord>(USERS_FILE).items;
}

export function findUserById(id: string): UserRecord | null {
  return listUsers().find((u) => u.id === id) ?? null;
}

export function findUserByEmail(email: string): UserRecord | null {
  const norm = email.trim().toLowerCase();
  return listUsers().find((u) => u.email === norm) ?? null;
}

export function findUserByPhone(phone: string): UserRecord | null {
  const norm = normalizePhone(phone);
  return listUsers().find((u) => u.phone === norm) ?? null;
}

export function findUserByProvider(provider: 'google' | 'apple', providerId: string): UserRecord | null {
  return listUsers().find((u) => u.providers[provider] === providerId) ?? null;
}

export function saveUser(user: UserRecord): UserRecord {
  const db = readDb<UserRecord>(USERS_FILE);
  const idx = db.items.findIndex((u) => u.id === user.id);
  if (idx >= 0) db.items[idx] = user;
  else db.items.push(user);
  writeDb(USERS_FILE, db);
  return user;
}

export function createUser(partial: Omit<UserRecord, 'id' | 'createdAt' | 'updatedAt'>): UserRecord {
  const now = new Date().toISOString();
  const user: UserRecord = {
    ...partial,
    id: randomUUID(),
    email: partial.email.trim().toLowerCase(),
    phone: partial.phone ? normalizePhone(partial.phone) : null,
    createdAt: now,
    updatedAt: now,
  };
  return saveUser(user);
}

export function updateUser(id: string, patch: Partial<UserRecord>): UserRecord | null {
  const user = findUserById(id);
  if (!user) return null;
  const next: UserRecord = {
    ...user,
    ...patch,
    id: user.id,
    email: patch.email ? patch.email.trim().toLowerCase() : user.email,
    phone: patch.phone !== undefined ? (patch.phone ? normalizePhone(patch.phone) : null) : user.phone,
    updatedAt: new Date().toISOString(),
  };
  return saveUser(next);
}

export function saveRefreshToken(rec: RefreshTokenRecord) {
  const db = readDb<RefreshTokenRecord>(REFRESH_FILE);
  db.items.push(rec);
  writeDb(REFRESH_FILE, db);
}

export function findRefreshToken(id: string): RefreshTokenRecord | null {
  return readDb<RefreshTokenRecord>(REFRESH_FILE).items.find((t) => t.id === id) ?? null;
}

export function revokeRefreshToken(id: string) {
  const db = readDb<RefreshTokenRecord>(REFRESH_FILE);
  const t = db.items.find((x) => x.id === id);
  if (t) t.revoked = true;
  writeDb(REFRESH_FILE, db);
}

export function revokeAllUserRefreshTokens(userId: string) {
  const db = readDb<RefreshTokenRecord>(REFRESH_FILE);
  for (const t of db.items) {
    if (t.userId === userId) t.revoked = true;
  }
  writeDb(REFRESH_FILE, db);
}

export function saveOtp(rec: OtpRecord) {
  const db = readDb<OtpRecord>(OTP_FILE);
  db.items = db.items.filter((o) => !(o.target === rec.target && o.purpose === rec.purpose));
  db.items.push(rec);
  writeDb(OTP_FILE, db);
}

export function findOtp(target: string, purpose: OtpRecord['purpose']): OtpRecord | null {
  const norm = target.includes('@') ? target.trim().toLowerCase() : normalizePhone(target);
  const items = readDb<OtpRecord>(OTP_FILE).items;
  return items.find((o) => o.target === norm && o.purpose === purpose) ?? null;
}

export function deleteOtp(id: string) {
  const db = readDb<OtpRecord>(OTP_FILE);
  db.items = db.items.filter((o) => o.id !== id);
  writeDb(OTP_FILE, db);
}

export function bumpOtpAttempts(id: string) {
  const db = readDb<OtpRecord>(OTP_FILE);
  const o = db.items.find((x) => x.id === id);
  if (o) o.attempts += 1;
  writeDb(OTP_FILE, db);
}

export function saveEmailToken(rec: EmailTokenRecord) {
  const db = readDb<EmailTokenRecord>(EMAIL_TOKENS_FILE);
  db.items = db.items.filter((t) => !(t.userId === rec.userId && t.purpose === rec.purpose));
  db.items.push(rec);
  writeDb(EMAIL_TOKENS_FILE, db);
}

export function findEmailToken(token: string, purpose: EmailTokenRecord['purpose']): EmailTokenRecord | null {
  return readDb<EmailTokenRecord>(EMAIL_TOKENS_FILE).items.find((t) => t.token === token && t.purpose === purpose) ?? null;
}

export function deleteEmailToken(token: string) {
  const db = readDb<EmailTokenRecord>(EMAIL_TOKENS_FILE);
  db.items = db.items.filter((t) => t.token !== token);
  writeDb(EMAIL_TOKENS_FILE, db);
}

export function normalizePhone(phone: string): string {
  return phone.replace(/[^\d+]/g, '');
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}
