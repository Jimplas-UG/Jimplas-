import React, { useMemo, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { createAuthStyles } from '../../theme/authStyles';

export default function PasswordField({
  label = 'Password',
  value,
  onChangeText,
  placeholder,
  error,
  showStrength,
}) {
  const { colors: C } = useBilshenzTheme();
  const st = useMemo(() => createAuthStyles(C), [C]);
  const [visible, setVisible] = useState(false);

  let strength = null;
  if (showStrength && value) {
    let score = 0;
    if (value.length >= 8) score += 1;
    if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score += 1;
    if (/\d/.test(value)) score += 1;
    if (/[^A-Za-z0-9]/.test(value)) score += 1;
    strength = score;
  }

  return (
    <View>
      <Text style={st.label}>{label}</Text>
      <View style={st.row}>
        <TextInput
          style={[st.input, { flex: 1 }, error ? st.inputError : null]}
          value={value}
          onChangeText={onChangeText}
          secureTextEntry={!visible}
          autoCapitalize="none"
          placeholder={placeholder}
          placeholderTextColor={C.dim2}
        />
        <Pressable onPress={() => setVisible((v) => !v)} style={[st.chip, { flex: 0, paddingHorizontal: 12 }]}>
          <Text style={st.chipTxt}>{visible ? 'Hide' : 'Show'}</Text>
        </Pressable>
      </View>
      {showStrength && strength != null ? (
        <View style={st.strengthRow}>
          {[1, 2, 3, 4].map((i) => (
            <View
              key={i}
              style={[
                st.strengthBar,
                {
                  backgroundColor:
                    strength >= i ? (strength >= 3 ? C.green : C.amber) : C.border,
                },
              ]}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}
