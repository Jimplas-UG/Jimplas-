// eslint-disable-next-line @typescript-eslint/no-var-requires
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

const useRemoteDesk = process.env.EXPO_PUBLIC_DESK_REMOTE === '1';
const engineStub = path.resolve(__dirname, 'client', 'engineStub.js');
const backendEngine = path.resolve(__dirname, '..', 'backend', 'engine', 'index.ts');

function isEngineModule(moduleName) {
  return (
    moduleName === '../engine' ||
    moduleName === './engine' ||
    moduleName.endsWith('/engine') ||
    moduleName.endsWith('/engine/index') ||
    moduleName.endsWith('/engine/index.ts') ||
    moduleName.startsWith('./engine/') ||
    moduleName.startsWith('../engine/')
  );
}

const prevResolve = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (isEngineModule(moduleName)) {
    const filePath = useRemoteDesk ? engineStub : backendEngine;
    return { type: 'sourceFile', filePath };
  }
  if (prevResolve) {
    return prevResolve(context, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

if (useRemoteDesk) {
  config.resolver.blockList = [
    ...(Array.isArray(config.resolver.blockList) ? config.resolver.blockList : []),
    /backend[\\/]engine[\\/].*\.ts$/,
    /backend[\\/]engine[\\/]reference[\\/]/,
  ];
}

module.exports = config;
