import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_PREFIX = '@bilshenz_v1/profileName/';

export function profileNameKey(profileId) {
  return `${STORAGE_PREFIX}${profileId}`;
}

export async function loadProfileName(profileId) {
  try {
    return (await AsyncStorage.getItem(profileNameKey(profileId))) || null;
  } catch {
    return null;
  }
}

export async function saveProfileName(profileId, name) {
  const trimmed = name.trim();
  if (!trimmed) {
    await AsyncStorage.removeItem(profileNameKey(profileId));
    return;
  }
  await AsyncStorage.setItem(profileNameKey(profileId), trimmed);
}

export async function clearProfileName(profileId) {
  await AsyncStorage.removeItem(profileNameKey(profileId));
}

export async function loadAllProfileNames(profileIds) {
  const keys = profileIds.map((id) => profileNameKey(id));
  const pairs = await AsyncStorage.multiGet(keys);
  const out = {};
  profileIds.forEach((id, i) => {
    const name = pairs[i]?.[1]?.trim();
    if (name) out[id] = name;
  });
  return out;
}

/** Up to two letters for avatar fallback when no photo. */
export function initialsFromName(name) {
  const parts = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase();
  }
  if (parts.length === 1 && parts[0].length >= 2) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  if (parts.length === 1) {
    return (parts[0][0] || '?').toUpperCase();
  }
  return '??';
}
