/**
 * Pre-flight checks before release APK / EAS build.
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
let failed = 0;

function fail(msg) {
  console.error('FAIL', msg);
  failed += 1;
}

function ok(msg) {
  console.log('OK', msg);
}

const icon = path.join(ROOT, 'assets', 'icon.png');
if (!fs.existsSync(icon) || fs.statSync(icon).size < 5000) {
  fail('Missing or placeholder icon.png — run npm run assets:generate');
} else {
  ok(`icon.png (${Math.round(fs.statSync(icon).size / 1024)} KB)`);
}

const appJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'app.json'), 'utf8'));
if (!appJson.expo?.name || appJson.expo.name.includes('Desk')) {
  fail(`App display name should be "Bilshenz", got "${appJson.expo?.name}"`);
} else {
  ok(`app name: ${appJson.expo.name}`);
}

if (!appJson.expo?.extra?.eas?.projectId) {
  fail('Missing EAS projectId in app.json');
} else {
  ok('EAS project linked');
}

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
if (!pkg.dependencies['babel-plugin-transform-remove-console']) {
  if (!pkg.devDependencies?.['babel-plugin-transform-remove-console']) {
    fail('babel-plugin-transform-remove-console must be in dependencies');
  } else {
    fail('babel-plugin-transform-remove-console should be in dependencies (not only devDependencies)');
  }
} else {
  ok('babel-plugin-transform-remove-console in dependencies');
}

const strategy = fs.readFileSync(path.join(ROOT, 'services', 'strategyService.js'), 'utf8');
if (/import\s*\{[^}]*IS_PRODUCTION_DESK[^}]*\}[^;]*;\s*\nimport[^;]*IS_PRODUCTION_DESK/.test(strategy)) {
  fail('Duplicate IS_PRODUCTION_DESK import in strategyService.js');
} else {
  ok('strategyService imports clean');
}

const indexJs = fs.readFileSync(path.join(ROOT, 'index.js'), 'utf8');
if (!indexJs.includes("import 'react-native-reanimated'")) {
  fail('index.js must import react-native-reanimated');
} else {
  const firstLine = indexJs.split('\n').find((l) => l.startsWith('import '));
  if (!firstLine?.includes('react-native-reanimated')) {
    fail('react-native-reanimated must be the first import in index.js');
  } else {
    ok('reanimated is first import');
  }
}

if (!indexJs.includes('./lib/bootSplash')) {
  fail('index.js must import bootSplash (release black-screen fix)');
} else {
  ok('bootSplash wired in index.js');
}

const appJs = fs.readFileSync(path.join(ROOT, 'App.js'), 'utf8');
if (appJs.includes('SplashScreen.preventAutoHideAsync()') && !fs.existsSync(path.join(ROOT, 'lib', 'bootSplash.js'))) {
  fail('App.js calls preventAutoHideAsync without lib/bootSplash.js');
} else if (appJs.includes('SplashScreen.preventAutoHideAsync()')) {
  fail('Remove SplashScreen.preventAutoHideAsync from App.js — use lib/bootSplash.js only');
} else {
  ok('App.js splash guard clean');
}

if (!appJs.includes('CinematicSplash') || !appJs.includes('SPLASH_MAX_MS')) {
  fail('App.js must use CinematicSplash with SPLASH_MAX_MS for 8s production boot');
} else {
  ok('CinematicSplash 8s boot wired in App.js');
}

if (!fs.existsSync(path.join(ROOT, 'lib', 'bootSplash.js'))) {
  fail('Missing lib/bootSplash.js');
} else {
  ok('bootSplash.js present');
}

if (!fs.existsSync(path.join(ROOT, 'components', 'logo', 'buildHexLogoSvg.js'))) {
  fail('Missing buildHexLogoSvg.js — icon assets will be wrong');
} else {
  ok('icon generator present');
}

try {
  const gitRoot = execSync('git rev-parse --show-toplevel', { cwd: ROOT, encoding: 'utf8' }).trim();
  const rel = path.relative(gitRoot, ROOT).replace(/\\/g, '/');
  const prefix = rel ? `${rel}/` : '';
  const porcelain = execSync('git status --porcelain', { cwd: gitRoot, encoding: 'utf8' });
  const pending = porcelain
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .filter((l) => {
      const file = l.slice(3).replace(/\\/g, '/');
      return file.startsWith(prefix);
    });
  if (pending.length) {
    fail(
      `Uncommitted frontend changes — EAS builds old git code. Commit first:\n${pending.slice(0, 12).join('\n')}${
        pending.length > 12 ? `\n... +${pending.length - 12} more` : ''
      }`,
    );
  } else {
    ok('git tree clean for frontend (EAS will include fixes)');
  }
} catch {
  ok('git check skipped');
}

console.log('==> Bundle smoke test');
try {
  execSync('npx expo export --platform android --output-dir .expo-release-verify', {
    cwd: ROOT,
    stdio: 'pipe',
    env: {
      ...process.env,
      BABEL_ENV: 'production',
      EAS_BUILD: 'true',
      EXPO_PUBLIC_DESK_LOCAL: '0',
      EXPO_PUBLIC_DESK_REMOTE: '1',
    },
  });
  ok('Android JS bundle exports');
  fs.rmSync(path.join(ROOT, '.expo-release-verify'), { recursive: true, force: true });
} catch (e) {
  const out = (e.stdout?.toString() || '') + (e.stderr?.toString() || '');
  fail(`Bundle export failed: ${out.slice(-800)}`);
}

if (failed) {
  console.error(`\nVERIFY_FAILED (${failed} issue(s))`);
  process.exit(1);
}
console.log('\nVERIFY_OK');
