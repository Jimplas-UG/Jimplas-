/**
 * Locate adb on Windows/macOS/Linux when it is not on PATH.
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const adbName = process.platform === 'win32' ? 'adb.exe' : 'adb';

function sdkRoots() {
  const home = process.env.USERPROFILE || process.env.HOME || '';
  const localApp = process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
  const bundled = path.join(__dirname, '..', '.tools', 'platform-tools');
  return [
    bundled,
    process.env.ANDROID_HOME,
    process.env.ANDROID_SDK_ROOT,
    path.join(localApp, 'Android', 'Sdk'),
    path.join(home, 'AppData', 'Local', 'Android', 'Sdk'),
    'C:\\Android\\android-sdk',
  ].filter(Boolean);
}

function resolveAdbPath() {
  for (const root of sdkRoots()) {
    const candidate = path.join(root, adbName);
    if (fs.existsSync(candidate)) return candidate;
    const nested = path.join(root, 'platform-tools', adbName);
    if (fs.existsSync(nested)) return nested;
  }
  return null;
}

function execAdbSync(args, options = {}) {
  const adb = resolveAdbPath();
  const cmd = adb ? `"${adb}" ${args}` : `adb ${args}`;
  return execSync(cmd, {
    encoding: 'utf8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 8000,
    ...options,
  });
}

function adbHasDevice() {
  try {
    const out = execAdbSync('devices');
    const lines = out
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('List of devices'));
    return lines.some((l) => /\tdevice$/.test(l));
  } catch {
    return false;
  }
}

function adbReverseTcp(port) {
  try {
    execAdbSync(`reverse tcp:${port} tcp:${port}`);
    return true;
  } catch {
    return false;
  }
}

module.exports = {
  resolveAdbPath,
  adbHasDevice,
  adbReverseTcp,
};
