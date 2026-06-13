# BSV3.2 — Local Android / Expo Dev Preview Guide

Complete offline UI development with **mock APIs**, **hot reload**, and a **dev navigator** for every screen.

---

## Quick start (recommended)

### 1. Install dependencies

```powershell
cd frontend
npm install
```

### 2. Start Metro in dev preview mode

```powershell
npm run start:dev
```

This enables:
- `EXPO_PUBLIC_DEV_PREVIEW=1` — dev tools + navigator
- `EXPO_PUBLIC_MOCK_API=1` — desk/MT5/Binance APIs mocked (no backend required)
- `EXPO_PUBLIC_SKIP_SPLASH=1` — skip cinematic splash
- Hot reload / Fast Refresh (save any file to reload)

### 3. Preview on Android

**Option A — Expo Go (fastest)**

1. Install [Expo Go SDK 52](https://expo.dev/go?sdkVersion=52) on your phone or emulator.
2. Scan the QR code from the Metro terminal, or open `exp://YOUR_LAN_IP:8081`.
3. USB debugging (most reliable on Windows):

```powershell
npm run android:dev
```

Then in Expo Go open `exp://127.0.0.1:8081`.

**Option B — Android Emulator (Android Studio)**

1. Open Android Studio → Device Manager → start a virtual device.
2. Ensure `adb devices` shows the emulator.
3. Run:

```powershell
npm run android:dev
```

4. Open Expo Go on the emulator and connect to Metro.

**Option C — Native debug build**

```powershell
npm run prebuild:android
npm run android
```

Requires Android SDK + JDK. Slower first build; full native modules.

---

## Dev Navigator (all screens)

When `npm run start:dev` is active, a **⚙ floating button** appears (bottom-right).

Tap it to open **DEV NAVIGATOR**:

| Screen | Tab ID | Contents |
|--------|--------|----------|
| Home | `home` | Dashboard, filters, session grid |
| Intel / Desk | `desk` | Full strategy intel panels |
| Trade | `trade` | Execute panel, signals |
| Profile | `profile` | Settings, MT5/Binance bridge |
| Risk | `risk` | P&L, spread, ATR tiers |
| UI Showcase | `showcase` | Component gallery |

**Debug Inspector** (from dev menu): navigation state, snapshot summary, mock API call log.

---

## Mock API (offline mode)

When mock API is on, these work **without** desk-api, MT5, or Binance:

| Endpoint | Mock behavior |
|----------|---------------|
| `POST /v1/desk/compute` | BUY P1 signal, NY session, full snapshot |
| `POST /v1/desk/execute-gate` | `{ ok: true }` |
| `/api/status`, `/api/bars`, `/api/tick` | Paper account + XAUUSDT klines |
| `/api/order` | Simulated fill |

To use **real** backend while keeping dev menu:

```powershell
$env:EXPO_PUBLIC_MOCK_API = "0"
npm run start:dev
```

---

## Hot reload

Metro Fast Refresh is enabled by default:

- Edit any `.js` file → UI updates on save
- Full reload: shake device → **Reload**, or press `r` in Metro terminal
- Clear cache: `npm run start:dev:clear`

---

## Environment variables (dev preview)

| Variable | Dev default | Purpose |
|----------|-------------|---------|
| `EXPO_PUBLIC_DEV_PREVIEW` | `1` | Dev menu + showcase |
| `EXPO_PUBLIC_MOCK_API` | `1` | Offline mock responses |
| `EXPO_PUBLIC_SKIP_SPLASH` | `1` | Skip splash animation |
| `EXPO_PUBLIC_BROKER_MODE` | `binance` | MT5 / binance / paper |
| `EXPO_PUBLIC_DESK_API_URL` | auto LAN | Real desk-api when mock off |

Copy `frontend/.env.example` to `.env.local` for persistent overrides.

---

## Testing every screen (checklist)

1. **Start:** `npm run start:dev`
2. **Open app** on emulator/device via Expo Go
3. **Dev menu ⚙** → tap each tile (Home, Intel, Trade, Profile, Risk, Showcase)
4. **Profile** → scroll to Binance bridge panel → CONNECT (mock attach works offline)
5. **Showcase** → verify logo, header, ticker, buttons, palette swatches
6. **Debug Inspector** → confirm mock API log entries after navigating
7. **Trade tab** → verify signal card renders (mock BUY P1)
8. **Resize** → rotate device / use different emulator sizes

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Failed to download remote update" | `npm run fix:metro-firewall` or `npm run start:usb` |
| Blank loading screen | Ensure `npm run start:dev` (not plain `npm start`) for mock API |
| Metro port in use | `npm run start:dev:clear` or kill node on 8081 |
| `@babel/runtime` errors | Do **not** set `EXPO_PUBLIC_DESK_LOCAL=1` in Expo Go |
| Emulator can't reach PC | `adb reverse tcp:8081 tcp:8081` |

---

## Exact launch command

```powershell
cd "c:\Users\Amoskole\Binance BSV3.2\frontend"
npm install
npm run android:dev
```

Then open **Expo Go** → `exp://127.0.0.1:8081` (USB) or scan LAN QR from terminal.

For production-style testing with real desk-api:

```powershell
cd ..\backend
npm run desk-api
cd ..\frontend
$env:EXPO_PUBLIC_MOCK_API = "0"
npm run start:dev
```
