// eslint-disable-next-line @typescript-eslint/no-var-requires
const fs = require('fs');
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, '..');
const backendRoot = path.resolve(monorepoRoot, 'backend');
const engineClient = path.resolve(projectRoot, 'client', 'engineClient.js');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(projectRoot);

config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, 'node_modules'),
  path.resolve(monorepoRoot, 'node_modules'),
];

// Never ship backend TypeScript to Expo Go — strategy runs on desk-api only.
config.resolver.blockList = [
  ...(Array.isArray(config.resolver.blockList) ? config.resolver.blockList : []),
  new RegExp(`${backendRoot.replace(/\\/g, '[\\\\/]')}[\\\\/]engine[\\\\/].*\\.(ts|tsx)$`),
  /[\\/]backend[\\/]engine[\\/]/,
  /[\\/]backend[\\/]strategy[\\/]/,
  /[\\/]backend[\\/]scripts[\\/]/,
];

config.transformer.minifierConfig = {
  compress: {
    drop_console: true,
    drop_debugger: true,
  },
  mangle: { toplevel: true },
};

function isEngineModule(moduleName) {
  return (
    moduleName === '../engine' ||
    moduleName === './engine' ||
    moduleName.endsWith('/engine') ||
    moduleName.endsWith('/engine/index') ||
    moduleName.endsWith('/engine/index.ts') ||
    moduleName.endsWith('/engine/index.js') ||
    moduleName.startsWith('./engine/') ||
    moduleName.startsWith('../engine/')
  );
}

function resolveAliasModule(moduleName) {
  if (!moduleName.startsWith('@/')) return null;
  const rel = moduleName.slice(2);
  const absBase = path.join(projectRoot, rel);
  const extensions = ['.js', '.jsx', '.ts', '.tsx', '.json'];
  for (const ext of extensions) {
    const candidate = absBase + ext;
    if (fs.existsSync(candidate)) return candidate;
  }
  if (fs.existsSync(absBase) && fs.statSync(absBase).isDirectory()) {
    for (const ext of extensions) {
      const idx = path.join(absBase, `index${ext}`);
      if (fs.existsSync(idx)) return idx;
    }
  }
  return null;
}

const prevResolve = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (isEngineModule(moduleName)) {
    return { type: 'sourceFile', filePath: engineClient };
  }
  const aliasPath = resolveAliasModule(moduleName);
  if (aliasPath) {
    return { type: 'sourceFile', filePath: aliasPath };
  }
  if (prevResolve) {
    return prevResolve(context, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;

