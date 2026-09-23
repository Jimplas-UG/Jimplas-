import React, { memo } from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';

const NAV = [
  { id: 'scanner', icon: '⌂', label: 'Home' },
  { id: 'risk', icon: '◎', label: 'Risk' },
  { id: 'trade', icon: '↗', label: 'Trade' },
  { id: 'profile', icon: '⚙', label: 'Settings' },
];

function AppBottomNav({ tab, onChange, bottomInset, pad = 16 }) {
  const { colors: C } = useBilshenzTheme();

  return (
    <View style={[st.outer, { paddingHorizontal: pad, paddingBottom: Math.max(bottomInset, 8) }]}>
      <View style={[st.bar, { backgroundColor: C.panel, borderColor: C.border }]}>
        {NAV.map((it) => {
          const active = tab === it.id;
          return (
            <Pressable
              key={it.id}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              onPress={() => onChange(it.id)}
              hitSlop={6}
              style={({ pressed }) => [st.item, pressed && { opacity: 0.85 }]}>
              <View
                style={[
                  st.itemInner,
                  active && { backgroundColor: C.accentDim, borderColor: 'rgba(124,108,240,0.35)' },
                ]}>
                <Text style={[st.icon, { color: active ? C.accentLight : C.dim2 }]}>{it.icon}</Text>
                <Text style={[st.lbl, { color: active ? C.accentLight : C.dim }]} numberOfLines={1}>
                  {it.label}
                </Text>
              </View>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default memo(AppBottomNav);

const st = StyleSheet.create({
  outer: {
    paddingTop: 6,
  },
  bar: {
    flexDirection: 'row',
    borderRadius: 20,
    borderWidth: 1,
    padding: 4,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: -2 },
        shadowOpacity: 0.25,
        shadowRadius: 10,
      },
      android: { elevation: 8 },
      default: {},
    }),
  },
  item: { flex: 1, minWidth: 0 },
  itemInner: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 4,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: 'transparent',
    gap: 2,
  },
  icon: { fontSize: 18, fontWeight: '600' },
  lbl: { fontSize: 10, fontWeight: '700' },
});
