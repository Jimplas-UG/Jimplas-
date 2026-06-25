/**
 * Guaranteed native splash dismissal — prevents permanent black screen on release APK.
 */
import * as SplashScreen from 'expo-splash-screen';

const FORCE_HIDE_MS = 10000;
let hideStarted = false;
let forceTimer = null;

export function initBootSplash() {
  SplashScreen.preventAutoHideAsync().catch(() => {});
  if (forceTimer) clearTimeout(forceTimer);
  forceTimer = setTimeout(() => {
    hideBootSplash('force-timeout');
  }, FORCE_HIDE_MS);
}

export async function hideBootSplash(_reason) {
  if (hideStarted) return;
  hideStarted = true;
  if (forceTimer) {
    clearTimeout(forceTimer);
    forceTimer = null;
  }
  try {
    await SplashScreen.hideAsync();
  } catch {
    /* native splash may already be gone */
  }
}
