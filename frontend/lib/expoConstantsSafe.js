/**
 * Safe reads from expo-constants.
 * Module is lazy-loaded — importing expo-constants at startup crashes Expo Go Android
 * ("lateinit property launcher has not been initialized").
 */

function safeManifestRead(read) {
  try {
    return read();
  } catch {
    return undefined;
  }
}

function getConstantsModule() {
  // eslint-disable-next-line global-require
  return require('expo-constants').default;
}

/** @returns {Record<string, unknown> | null} */
export function safeConstantsExtra() {
  const Constants = getConstantsModule();
  const fromConfig = Constants.expoConfig?.extra;
  if (fromConfig) return fromConfig;
  const fromManifest2 = Constants.manifest2?.extra;
  if (fromManifest2) return fromManifest2;
  return safeManifestRead(() => Constants.manifest?.extra) ?? null;
}

export function safeConstantsExtraKey(key) {
  return safeConstantsExtra()?.[key];
}

/** Debugger host strings (may include port), newest Expo APIs first. */
export function safeDebuggerHostCandidates() {
  const Constants = getConstantsModule();
  const out = [];
  const push = (v) => {
    if (typeof v === 'string' && v.trim()) out.push(v.trim());
  };
  push(Constants.expoGoConfig?.debuggerHost);
  push(Constants.manifest2?.extra?.expoGo?.debuggerHost);
  push(safeManifestRead(() => Constants.manifest?.debuggerHost));
  return out;
}

export function safeExpoHostUri() {
  const Constants = getConstantsModule();
  const uri = Constants.expoConfig?.hostUri;
  return typeof uri === 'string' ? uri : undefined;
}
