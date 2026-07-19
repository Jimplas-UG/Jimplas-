import React from 'react';
import { Image, StyleSheet } from 'react-native';

/** Shared BS app mark — exact launcher artwork (not SVG redraw). */
const BRAND_LOGO = require('../../assets/brand/bs-app-logo.png');

/**
 * @param {{ size?: number, style?: object }} props
 */
export default function BrandLogo({ size = 120, style }) {
  return (
    <Image
      source={BRAND_LOGO}
      style={[styles.img, { width: size, height: size }, style]}
      resizeMode="contain"
      accessibilityLabel="Bilshenz"
    />
  );
}

const styles = StyleSheet.create({
  img: {
    backgroundColor: 'transparent',
  },
});
