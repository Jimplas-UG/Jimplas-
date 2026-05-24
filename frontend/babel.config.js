module.exports = function (api) {
  api.cache(true);
  const isProd =
    process.env.BABEL_ENV === 'production' ||
    process.env.NODE_ENV === 'production' ||
    process.env.EAS_BUILD === 'true';

  const plugins = ['react-native-reanimated/plugin'];
  if (isProd) {
    plugins.unshift(['transform-remove-console', { exclude: ['error'] }]);
  }

  return {
    presets: ['babel-preset-expo'],
    plugins,
  };
};
