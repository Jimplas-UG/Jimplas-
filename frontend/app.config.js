/** Expo config — embed desk-api defaults for Expo Go (override with env vars). */
const lanIp =
  process.env.REACT_NATIVE_PACKAGER_HOSTNAME ||
  process.env.EXPO_PACKAGER_HOSTNAME ||
  '127.0.0.1';

module.exports = ({ config }) => ({
  ...config,
  extra: {
    ...config.extra,
    deskApiUrl: process.env.EXPO_PUBLIC_DESK_API_URL || `http://${lanIp}:8791`,
    deskRemote: '1',
  },
});
