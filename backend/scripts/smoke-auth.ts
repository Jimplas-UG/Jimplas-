/**
 * Smoke test BSV32 user auth API (register → login → me → refresh → logout).
 * Run: npx tsx scripts/smoke-auth.ts
 * Requires desk-api on DESK_API_PORT (default 8791).
 */
const AUTH_BASE = (process.env.DESK_API_URL || `http://127.0.0.1:${process.env.DESK_API_PORT || 8791}`).replace(
  /\/$/,
  '',
);

async function authReq(path: string, init: RequestInit = {}) {
  const res = await fetch(`${AUTH_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
    ...init,
  });
  const text = await res.text();
  let json: Record<string, unknown> = {};
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    json = { raw: text };
  }
  return { status: res.status, json };
}

function authAssert(cond: unknown, msg: string) {
  if (!cond) throw new Error(msg);
}

async function main() {
  const email = `trader.${Date.now()}@bsv32.test`;
  const password = 'TestPass1!';

  console.log('health…');
  const health = await authReq('/health', { method: 'GET' });
  authAssert(health.status === 200, `health failed: ${health.status}`);

  console.log('register…');
  const reg = await authReq('/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      fullName: 'Smoke Trader',
      email,
      password,
      confirmPassword: password,
      termsAccepted: true,
    }),
  });
  authAssert(reg.status === 201, `register failed: ${reg.status} ${JSON.stringify(reg.json)}`);
  const access = (reg.json as { tokens?: { accessToken: string } }).tokens?.accessToken;
  const refresh = (reg.json as { tokens?: { refreshToken: string } }).tokens?.refreshToken;
  authAssert(access && refresh, 'missing tokens from register');

  console.log('me…');
  const me = await authReq('/v1/auth/me', {
    method: 'GET',
    headers: { Authorization: `Bearer ${access}` },
  });
  authAssert(me.status === 200, `me failed: ${me.status}`);

  console.log('login…');
  const login = await authReq('/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  authAssert(login.status === 200, `login failed: ${login.status}`);

  console.log('refresh…');
  const ref = await authReq('/v1/auth/refresh', {
    method: 'POST',
    body: JSON.stringify({ refreshToken: refresh }),
  });
  authAssert(ref.status === 200, `refresh failed: ${ref.status}`);

  console.log('logout…');
  const out = await authReq('/v1/auth/logout', {
    method: 'POST',
    headers: { Authorization: `Bearer ${access}` },
    body: JSON.stringify({ refreshToken: refresh }),
  });
  authAssert(out.status === 200, `logout failed: ${out.status}`);

  console.log('OK — auth smoke passed');
}

main().catch((e) => {
  console.error('FAIL', e instanceof Error ? e.message : e);
  process.exit(1);
});
