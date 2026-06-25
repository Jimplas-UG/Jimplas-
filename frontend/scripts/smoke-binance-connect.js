/**
 * Smoke test: Binance bridge reachability + login error handling (no real keys required).
 * Run: node frontend/scripts/smoke-binance-connect.js [baseUrl]
 */
const BASE = (process.argv[2] || 'http://127.0.0.1:8766').replace(/\/$/, '');

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { signal: AbortSignal.timeout(15000) });
  const text = await res.text();
  let json = {};
  try {
    json = JSON.parse(text);
  } catch {
    /* text */
  }
  return { ok: res.ok, status: res.status, json, text };
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(20000),
  });
  const text = await res.text();
  let json = {};
  try {
    json = JSON.parse(text);
  } catch {
    /* text */
  }
  return { ok: res.ok, status: res.status, json, text };
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function main() {
  console.log(`=== smoke-binance-connect: ${BASE} ===`);

  const health = await get('/health');
  assert(health.ok && health.json.ok, `health failed: ${health.text}`);
  console.log('✓ health', health.json.mode);

  const status = await get('/api/status');
  assert(status.ok, `status failed: ${status.text}`);
  console.log('✓ status connected=', status.json.connected);

  const logout = await post('/api/logout', {});
  assert(logout.ok, 'logout failed');
  console.log('✓ logout');

  const badLogin = await post('/api/login', {
    api_key: 'invalid_key_smoke_test',
    api_secret: 'invalid_secret_smoke_test',
    testnet: true,
  });
  assert(badLogin.status === 401, `expected 401 for bad login, got ${badLogin.status}`);
  const detail = typeof badLogin.json.detail === 'string' ? badLogin.json.detail : JSON.stringify(badLogin.json.detail);
  assert(/invalid|api-key|signature|failed/i.test(detail), `unexpected login error: ${detail}`);
  console.log('✓ login rejects bad keys:', detail.slice(0, 80));

  const after = await get('/api/status');
  assert(!after.json.connected, 'status should be disconnected after failed login');
  console.log('✓ status disconnected after failed login');

  console.log('SMOKE_OK');
}

main().catch((e) => {
  console.error('SMOKE_FAIL', e.message);
  process.exit(1);
});
