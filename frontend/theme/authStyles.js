import { StyleSheet } from 'react-native';
import { radius, spacing, typography } from './designTokens';

export function createAuthStyles(C) {
  return StyleSheet.create({
    root: {
      flex: 1,
      backgroundColor: C.appBg,
    },
    scroll: {
      flexGrow: 1,
      paddingHorizontal: spacing.xl,
      paddingBottom: spacing.xxxl,
    },
    hero: {
      alignItems: 'center',
      paddingTop: spacing.xxxl,
      paddingBottom: spacing.xl,
    },
    brand: {
      fontSize: 28,
      fontWeight: '900',
      color: C.goldL,
      letterSpacing: 4,
    },
    brandSub: {
      marginTop: spacing.sm,
      fontSize: 11,
      color: C.dim,
      letterSpacing: 2,
      fontWeight: '600',
      textTransform: 'uppercase',
    },
    card: {
      borderRadius: radius.lg,
      borderWidth: 1,
      borderColor: C.border,
      backgroundColor: C.panel,
      padding: spacing.xl,
      marginBottom: spacing.lg,
    },
    title: {
      ...typography.title,
      color: C.text,
      marginBottom: spacing.xs,
    },
    subtitle: {
      fontSize: 12,
      color: C.dim,
      lineHeight: 18,
      marginBottom: spacing.lg,
    },
    label: {
      ...typography.label,
      color: C.dim,
      marginBottom: spacing.sm,
      marginTop: spacing.md,
    },
    input: {
      borderWidth: 1,
      borderColor: C.border,
      borderRadius: radius.md,
      backgroundColor: C.inputBg,
      color: C.text,
      paddingHorizontal: spacing.md,
      paddingVertical: 12,
      fontSize: 14,
    },
    inputError: {
      borderColor: C.red,
    },
    row: {
      flexDirection: 'row',
      gap: spacing.sm,
      alignItems: 'center',
    },
    chip: {
      flex: 1,
      paddingVertical: 10,
      borderRadius: radius.md,
      borderWidth: 1,
      borderColor: C.border,
      alignItems: 'center',
    },
    chipActive: {
      borderColor: C.gold,
      backgroundColor: 'rgba(212,180,90,0.12)',
    },
    chipTxt: {
      fontSize: 11,
      fontWeight: '700',
      color: C.dim,
      letterSpacing: 0.5,
    },
    chipTxtActive: {
      color: C.goldL,
    },
    btn: {
      marginTop: spacing.lg,
      borderRadius: radius.md,
      paddingVertical: 14,
      alignItems: 'center',
      backgroundColor: C.goldD,
      borderWidth: 1,
      borderColor: C.gold,
    },
    btnDisabled: {
      opacity: 0.45,
    },
    btnTxt: {
      color: C.goldL,
      fontSize: 13,
      fontWeight: '800',
      letterSpacing: 1.2,
    },
    btnGhost: {
      marginTop: spacing.md,
      paddingVertical: 10,
      alignItems: 'center',
    },
    btnGhostTxt: {
      color: C.dim,
      fontSize: 12,
      fontWeight: '600',
    },
    errorBox: {
      marginTop: spacing.md,
      padding: spacing.md,
      borderRadius: radius.md,
      borderWidth: 1,
      borderColor: 'rgba(255,61,87,0.35)',
      backgroundColor: 'rgba(255,61,87,0.08)',
    },
    errorTxt: {
      color: C.red,
      fontSize: 12,
      lineHeight: 18,
    },
    strengthRow: {
      flexDirection: 'row',
      gap: 4,
      marginTop: spacing.sm,
    },
    strengthBar: {
      flex: 1,
      height: 3,
      borderRadius: 2,
      backgroundColor: C.border,
    },
    divider: {
      flexDirection: 'row',
      alignItems: 'center',
      marginVertical: spacing.lg,
      gap: spacing.md,
    },
    dividerLine: {
      flex: 1,
      height: 1,
      backgroundColor: C.border,
    },
    dividerTxt: {
      fontSize: 10,
      color: C.dim2,
      fontWeight: '700',
      letterSpacing: 1,
    },
    socialRow: {
      flexDirection: 'row',
      gap: spacing.sm,
    },
    socialBtn: {
      flex: 1,
      borderWidth: 1,
      borderColor: C.border,
      borderRadius: radius.md,
      paddingVertical: 12,
      alignItems: 'center',
      backgroundColor: C.panel2,
    },
    socialTxt: {
      fontSize: 12,
      fontWeight: '700',
      color: C.text,
    },
    link: {
      color: C.goldL,
      fontWeight: '700',
    },
    checkRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      marginTop: spacing.md,
    },
    checkBox: {
      width: 20,
      height: 20,
      borderRadius: 4,
      borderWidth: 1,
      borderColor: C.border,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 2,
    },
    checkBoxOn: {
      borderColor: C.gold,
      backgroundColor: 'rgba(212,180,90,0.2)',
    },
    footer: {
      alignItems: 'center',
      marginTop: spacing.lg,
    },
    fadeIn: {
      opacity: 1,
    },
  });
}

export function passwordStrengthClient(password) {
  if (!password) return { level: 0, label: '' };
  let score = 0;
  if (password.length >= 8) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  if (password.length >= 12) score += 1;
  const labels = ['', 'Weak', 'Fair', 'Good', 'Strong', 'Strong'];
  return { level: score, label: labels[score] || '' };
}
