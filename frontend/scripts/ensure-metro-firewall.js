/**
 * Ensures Windows inbound firewall allows Metro (8081) + desk-api + bridge.
 * If rules are missing, launches elevated PowerShell (UAC) and waits briefly.
 */
const { execSync, spawn } = require('child_process');
const path = require('path');

const port = process.env.METRO_PORT || process.env.RCT_METRO_PORT || '8081';
const RULE_NAMES = [
  `Expo Metro TCP ${port}`,
  `Bilshenz Expo LAN TCP ${port}`,
  `Bilshenz Expo LAN TCP 8791`,
  `Bilshenz Expo LAN TCP 8766`,
  `Bilshenz Desk TCP 8791`,
  `Bilshenz Desk TCP 8766`,
];

function ruleEnabled(name) {
  try {
    const out = execSync(`netsh advfirewall firewall show rule name="${name}"`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return /Enabled:\s*Yes/i.test(out);
  } catch {
    return false;
  }
}

function metroFirewallOk() {
  if (process.platform !== 'win32') return true;
  return RULE_NAMES.some((n) => ruleEnabled(n));
}

function isAdmin() {
  if (process.platform !== 'win32') return true;
  try {
    execSync('net session', { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function addRulesInline() {
  const ports = [port, '8791', '8766'];
  for (const p of ports) {
    const ruleName = `Bilshenz Expo LAN TCP ${p}`;
    execSync(`netsh advfirewall firewall delete rule name="${ruleName}"`, { stdio: 'ignore' });
    execSync(
      `netsh advfirewall firewall add rule name="${ruleName}" dir=in action=allow protocol=TCP localport=${p} profile=any`,
      { stdio: 'ignore' },
    );
  }
}

function sleepMs(ms) {
  try {
    execSync(`powershell -NoProfile -Command "Start-Sleep -Milliseconds ${ms}"`, { stdio: 'ignore' });
  } catch {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      /* spin */
    }
  }
}

function requestUacFirewallFix() {
  const ps1 = path.join(__dirname, 'allow-expo-metro-firewall.ps1');
  console.log('[expo-go] Requesting Administrator approval (UAC) to open firewall…');
  spawn(
    'powershell.exe',
    [
      '-NoProfile',
      '-Command',
      `Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File \\"${ps1.replace(/\\/g, '\\\\')}\\"'`,
    ],
    { detached: true, stdio: 'ignore' },
  ).unref();
}

/**
 * @param {{ waitForUacMs?: number }} [opts]
 * @returns {boolean} true when Metro LAN port is allowed inbound
 */
function ensureMetroFirewall(opts = {}) {
  const waitForUacMs = opts.waitForUacMs ?? 45000;

  if (process.platform !== 'win32') return true;

  if (metroFirewallOk()) {
    console.log('[expo-go] Firewall OK for Metro LAN (port ' + port + ').');
    return true;
  }

  console.log('');
  console.log('[expo-go] Windows firewall is blocking phone access to Metro port ' + port + '.');
  console.log('[expo-go] This causes Expo Go "Failed to download remote update".');

  if (isAdmin()) {
    try {
      addRulesInline();
      if (metroFirewallOk()) {
        console.log('[expo-go] Added inbound firewall rules for ports ' + port + ', 8791, 8766.');
        return true;
      }
    } catch (e) {
      console.warn('[expo-go] Could not add firewall rules:', e.message);
    }
  } else {
    requestUacFirewallFix();
    console.log('[expo-go] Waiting up to ' + Math.round(waitForUacMs / 1000) + 's for UAC approval…');
    const deadline = Date.now() + waitForUacMs;
    while (Date.now() < deadline) {
      sleepMs(1000);
      if (metroFirewallOk()) {
        console.log('[expo-go] Firewall opened — phone can reach Metro on port ' + port + '.');
        return true;
      }
    }
  }

  console.log('');
  console.log('[expo-go] Firewall still blocking LAN. Options:');
  console.log('[expo-go]   1) Approve UAC → npm run fix:metro-firewall (Admin PowerShell in frontend/)');
  console.log('[expo-go]   2) npm run start:tunnel  (works without firewall; needs internet)');
  console.log('[expo-go]   3) npm run start:usb  (USB debugging + adb in PATH)');
  console.log('');
  return false;
}

if (require.main === module) {
  process.exit(ensureMetroFirewall() ? 0 : 1);
}

module.exports = { ensureMetroFirewall, metroFirewallOk };
