/** Expo config — production forces remote desk-api (strategy protection). */
const isProd = process.env.NODE_ENV === 'production' || process.env.EAS_BUILD === 'true';
const lanIp =
  process.env.REACT_NATIVE_PACKAGER_HOSTNAME ||
  process.env.EXPO_PACKAGER_HOSTNAME ||
  '127.0.0.1';

module.exports = ({ config }) => {
  const deskApiUrl = process.env.EXPO_PUBLIC_DESK_API_URL || `http://${lanIp}:8791`;
  const deskApiKey = process.env.EXPO_PUBLIC_DESK_API_KEY || '';
  const extra = {
    ...config.extra,
    deskApiUrl,
    deskApiKey,
    deskRemote: isProd ? '1' : process.env.EXPO_PUBLIC_DESK_REMOTE ?? '1',
  };
  const projectId = process.env.EAS_PROJECT_ID ?? config.extra?.eas?.projectId;
  if (projectId) {
    extra.eas = { ...(config.extra?.eas ?? {}), projectId };
  }

  const plugins = [...(config.plugins || [])];
  if (!plugins.some((p) => (Array.isArray(p) ? p[0] : p) === 'expo-build-properties')) {
    plugins.push([
      'expo-build-properties',
      {
        android: {
          minSdkVersion: 24,
          targetSdkVersion: 34,
          compileSdkVersion: 35,
          usesCleartextTraffic: true,
          enableMinifyInReleaseBuilds: true,
          enableShrinkResourcesInReleaseBuilds: false,
        },
      },
    ]);
  }

  return {
    ...config,
    plugins,
    android: {
      ...config.android,
      package: 'com.jimplas.bilshenz',
      permissions: ['INTERNET', 'ACCESS_NETWORK_STATE'],
      adaptiveIcon: config.android?.adaptiveIcon ?? {
        foregroundImage: './assets/adaptive-icon.png',
        backgroundColor: '#000000',
      },
    },
    extra,
  };
};
