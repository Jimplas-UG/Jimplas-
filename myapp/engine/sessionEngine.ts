import { DateTime } from 'luxon';

import type { SessionName, SessionSnapshot } from './types';

const NY = 'America/New_York';

export function sessionFromUtcEpochMs(tUtcMs: number): SessionSnapshot {
  const dt = DateTime.fromMillis(tUtcMs, { zone: 'utc' }).setZone(NY);
  const mins = dt.hour * 60 + dt.minute;

  const preLondon = mins >= 19 * 60 && mins < 23 * 60;
  const london = mins >= 2 * 60 && mins < 6 * 60;
  const newYork = mins >= 7 * 60 && mins < 12 * 60;
  const inSession = preLondon || london || newYork;

  let name: SessionName = 'DEAD';
  let sessionLabel = '☠ DEAD ZONE · ALL OTHER TIMES';
  if (preLondon) {
    name = 'PRE_LONDON';
    sessionLabel = '① PRE-LONDON · 19:00–23:00 EST';
  } else if (london) {
    name = 'LONDON';
    sessionLabel = '② LONDON · 02:00–06:00 EST';
  } else if (newYork) {
    name = 'NEW_YORK';
    sessionLabel = '③ NEW YORK · 07:00–12:00 EST';
  }

  return { preLondon, london, newYork, inSession, name, sessionLabel };
}

export function nyDayOfMonth(tUtcMs: number): number {
  return DateTime.fromMillis(tUtcMs, { zone: 'utc' }).setZone(NY).day;
}

/** New York calendar date `yyyy-MM-dd` — use for daily sim reset (not `nyDayOfMonth`, which is only 1–31). */
export function nyYmdKey(tUtcMs: number): string {
  return DateTime.fromMillis(tUtcMs, { zone: 'utc' }).setZone(NY).toFormat('yyyy-LL-dd');
}

export function nyWeekday(tUtcMs: number): number {
  return DateTime.fromMillis(tUtcMs, { zone: 'utc' }).setZone(NY).weekday;
}
