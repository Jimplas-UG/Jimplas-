import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_PREFIX = '@bilshenz_v1/profilePhoto/';

export function profilePhotoKey(profileId) {
  return `${STORAGE_PREFIX}${profileId}`;
}

export async function loadProfilePhoto(profileId) {
  try {
    return (await AsyncStorage.getItem(profilePhotoKey(profileId))) || null;
  } catch {
    return null;
  }
}

export async function saveProfilePhoto(profileId, uri) {
  await AsyncStorage.setItem(profilePhotoKey(profileId), uri);
}

export async function clearProfilePhoto(profileId) {
  await AsyncStorage.removeItem(profilePhotoKey(profileId));
}

export async function loadAllProfilePhotos(profileIds) {
  const keys = profileIds.map((id) => profilePhotoKey(id));
  const pairs = await AsyncStorage.multiGet(keys);
  const out = {};
  profileIds.forEach((id, i) => {
    const uri = pairs[i]?.[1];
    if (uri) out[id] = uri;
  });
  return out;
}
