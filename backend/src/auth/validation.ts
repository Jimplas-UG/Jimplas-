const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(email: string): string | null {
  const v = email?.trim() ?? '';
  if (!v) return 'Email is required';
  if (!EMAIL_RE.test(v)) return 'Enter a valid email address';
  if (v.length > 254) return 'Email is too long';
  return null;
}

export function validatePhone(phone: string): string | null {
  const digits = (phone ?? '').replace(/[^\d+]/g, '');
  if (!digits) return 'Phone number is required';
  if (digits.length < 8 || digits.length > 16) return 'Enter a valid phone number';
  return null;
}

export function validateFullName(name: string): string | null {
  const v = name?.trim() ?? '';
  if (!v) return 'Full name is required';
  if (v.length < 2) return 'Name is too short';
  if (v.length > 80) return 'Name is too long';
  return null;
}

export function validateTerms(accepted: boolean): string | null {
  if (!accepted) return 'You must accept the Terms & Conditions';
  return null;
}

export function validateOtpCode(code: string): string | null {
  const v = (code ?? '').trim();
  if (!/^\d{6}$/.test(v)) return 'Enter the 6-digit code';
  return null;
}
