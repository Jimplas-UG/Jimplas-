/**
 * Smoke-test Expo Go LAN connectivity (run while Metro is up).
 * Usage: node scripts/smoke-expo-go.js [ip] [port]
 */
const http = require('http');
const os = require('os');

function pickLanIp() {
  const nets = os.networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const addr of nets[name] || []) {
      if (addr.family === 'IPv4' && !addr.internal && addr.address.startsWith('192.168.')) {
        return addr.address;
      }
    }
  }
  return '127.0.0.1';
}

const ip = process.argv[2] || pickLanIp();
const port = process.argv[3] || process.env.METRO_PORT || '8081';

function get(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: 10000 }, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => resolve({ status: res.statusCode, body: body.slice(0, 200) }));
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('timeout'));
    });
  });
}

async function main() {
  const expUrl = `exp://${ip}:${port}`;
  console.log('');
  console.log('=== Expo Go smoke test ===');
  console.log('URL:', expUrl);
  console.log('');

  const targets = [
    `http://127.0.0.1:${port}/`,
    `http://${ip}:${port}/`,
  ];

  let ok = 0;
  for (const url of targets) {
    try {
      const r = await get(url);
      const pass = r.status >= 200 && r.status < 500;
      console.log(pass ? 'OK' : 'FAIL', url, '→', r.status);
      if (pass) ok += 1;
    } catch (e) {
      console.log('FAIL', url, '→', e.message);
    }
  }

  console.log('');
  if (ok === targets.length) {
    console.log('PASS — Metro reachable on LAN. Scan:', expUrl);
    process.exit(0);
  }
  console.log('FAIL — Metro not reachable on LAN IP. Run as Admin: npm run connect:phone');
  process.exit(1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
