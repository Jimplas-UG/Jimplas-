import React from 'react';
import { BlurView } from 'expo-blur';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';

const Row = ({ style, children, ...rest }) => (
  <View style={[{ flexDirection: 'row', alignItems: 'center' }, style]} {...rest}>
    {children}
  </View>
);

export default function ScannerBottomNav({ tab, onChange, bottomInset }) {
  const { styles } = useBilshenzTheme();
  const items = [
    { id: 'scanner', icon: '◎', label: 'SCANNER' },
    { id: 'profile', icon: '👤', label: 'PROFILE' },
  ];

  return (
    <View style={[styles.bottomNavOuter, { paddingBottom: Math.max(bottomInset, 4) }]}>
      <View style={styles.bottomNavBar}>
        {Platform.OS === 'ios' ? (
          <BlurView intensity={28} tint="dark" style={StyleSheet.absoluteFillObject} />
        ) : (
          <View style={[StyleSheet.absoluteFillObject, { backgroundColor: 'rgba(10,9,0,0.96)' }]} />
        )}
        <View style={styles.bottomNavBarTint} />
        <Row style={styles.bottomNavRow}>
          {items.map((it) => {
            const active = tab === it.id;
            return (
              <Pressable
                key={it.id}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
                onPress={() => onChange(it.id)}
                style={({ pressed }) => [
                  styles.bottomNavItem,
                  active && styles.bottomNavItemActive,
                  pressed && styles.bottomNavItemPressed,
                ]}>
                {active ? (
                  <View style={styles.bottomNavActiveCapWrap} pointerEvents="none">
                    <View style={styles.bottomNavActiveCap} />
                  </View>
                ) : null}
                <View style={styles.bottomNavItemInner}>
                  <Text style={[styles.bottomNavIcon, active && styles.bottomNavIconActive]}>{it.icon}</Text>
                  <Text
                    numberOfLines={1}
                    style={[styles.bottomNavLbl, active && styles.bottomNavLblActive]}>
                    {it.label}
                  </Text>
                </View>
              </Pressable>
            );
          })}
        </Row>
      </View>
    </View>
  );
}
